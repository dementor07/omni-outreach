import time
import uuid
import threading

import logfire
import rollbar
from logger import setup_stdio_tee
from db import fetch_enabled_campaigns, fetch_one, insert_run, complete_run, interrupt_stale_runs
from outbound_dispatcher import dispatch_loop
from rollbar_init import init_rollbar
from logfire_init import init_logfire
from schema import verify_runtime_schema
import config
import lead_ingestion
import invitation_service
import acceptance_checker
import first_message_service
import followup_service
import conversation_guard
import manual_message_service
import approval_checker

DEFAULT_CORE_INTERVAL_SECONDS = 60 * 60
DEFAULT_MANUAL_INTERVAL_SECONDS = 15 * 60

_manual_lock = threading.Lock()


def _sleep_or_stop(stop_event: threading.Event | None, seconds: float) -> None:
    if stop_event is None:
        time.sleep(seconds)
        return
    stop_event.wait(seconds)


def campaign_worker(campaign_id: str, stop_event: threading.Event | None = None):
    """
    Run a single loop per campaign (core + manual) in one thread.
    Each thread has its own config state via threading.local(), so no lock is needed.
    """
    config.set_campaign(campaign_id)

    if not config.get_accounts():
        print(
            f"[campaign-worker:{campaign_id}] WARNING: no LinkedIn accounts configured in DB"
            " — will retry on each run cycle",
            flush=True,
        )

    def load_intervals():
        core = int(config.cfg("CORE_RUN_INTERVAL_SECONDS", DEFAULT_CORE_INTERVAL_SECONDS))
        manual = int(config.cfg("MANUAL_RUN_INTERVAL_SECONDS", DEFAULT_MANUAL_INTERVAL_SECONDS))
        return int(core), int(manual)

    def run_once(run_id: str):
        config.refresh_campaign()
        insert_run(run_id, campaign_id)
        error = None
        try:
            with logfire.span("campaign.run_once", campaign_id=campaign_id, run_id=run_id):
                lead_ingestion.ingest_leads()
                invitation_service.send_invitations()
                acceptance_checker.check_acceptance()
                first_message_service.send_first_messages()
                followup_service.send_followups()
                conversation_guard.check_inbound_replies()
        except Exception as e:
            error = str(e)
            raise
        finally:
            complete_run(run_id, error=error)

    print(f"Automation runner started for campaign {campaign_id}")

    next_core = 0
    next_manual = 0

    while not (stop_event and stop_event.is_set()):
        try:
            config.refresh_campaign()

            # Skip entire iteration if campaign is paused or global kill switch is off
            from db_config_loader import load_db_config
            _live_cfg = load_db_config(campaign_id)
            if not _live_cfg.get("IS_ACTIVE", True):
                print(f"[campaign-loop:{campaign_id}] Paused — skipping run")
                _sleep_or_stop(stop_event, 30)
                continue
            if not _live_cfg.get("GLOBAL_ACTIVE", True):
                print(f"[campaign-loop:{campaign_id}] Global automation paused — skipping run")
                _sleep_or_stop(stop_event, 30)
                continue

            core_interval, manual_interval = load_intervals()
            now = time.time()

            if now >= next_core:
                run_id = str(uuid.uuid4())
                try:
                    run_once(run_id)
                except Exception as e:
                    print(f"[core-loop:{campaign_id}] Error: {e}")
                    rollbar.report_exc_info(extra_data={"campaign_id": campaign_id, "run_id": run_id})
                next_core = now + core_interval

            if now >= next_manual:
                acquired_manual_lock = _manual_lock.acquire(blocking=False)
                if acquired_manual_lock:
                    try:
                        manual_message_service.send_manual_messages_from_sheet()
                    except Exception as e:
                        print(f"[manual-loop:{campaign_id}] Error: {e}")
                        rollbar.report_exc_info(extra_data={"campaign_id": campaign_id, "loop": "manual"})
                    finally:
                        _manual_lock.release()
                try:
                    approval_checker.check_approvals(campaign_id)
                except Exception as e:
                    print(f"[approval-loop:{campaign_id}] Error: {e}")
                    rollbar.report_exc_info(extra_data={"campaign_id": campaign_id, "loop": "approval"})
                if acquired_manual_lock:
                    next_manual = now + manual_interval

        except Exception as e:
            print(f"[campaign-loop:{campaign_id}] Error: {e}")
            rollbar.report_exc_info(extra_data={"campaign_id": campaign_id, "loop": "outer"})

        _sleep_or_stop(stop_event, 1)

    print(f"[campaign-worker:{campaign_id}] Stop requested — exiting", flush=True)


DEFAULT_DISCOVERY_INTERVAL = 900  # 15 min fallback


def _discovery_interval() -> int:
    row = fetch_one(
        "SELECT campaign_discovery_interval_seconds FROM system_constants ORDER BY updated_at DESC LIMIT 1"
    )
    if row and row.get("campaign_discovery_interval_seconds"):
        return int(row["campaign_discovery_interval_seconds"])
    return DEFAULT_DISCOVERY_INTERVAL


def _start_campaign_worker(campaign_id: str) -> dict:
    stop_event = threading.Event()
    thread = threading.Thread(target=campaign_worker, args=(campaign_id, stop_event), daemon=True)
    thread.start()
    return {"thread": thread, "stop_event": stop_event}


def _reconcile_workers(active_workers: dict[str, dict], campaigns: list[str]) -> dict[str, dict]:
    wanted = set(campaigns)
    current = set(active_workers.keys())

    new_campaigns = [c for c in campaigns if c not in active_workers]
    removed_campaigns = [c for c in active_workers if c not in wanted]

    if new_campaigns:
        print(f"[runner] Discovered new campaigns: {', '.join(new_campaigns)}")

    for campaign_id in removed_campaigns:
        worker = active_workers[campaign_id]
        worker["stop_event"].set()
        worker["thread"].join(timeout=5)
        del active_workers[campaign_id]
        print(f"[runner] Stopped worker for {campaign_id}")

    for campaign_id in new_campaigns:
        active_workers[campaign_id] = _start_campaign_worker(campaign_id)
        print(f"[runner] Started worker for {campaign_id}")

    return active_workers


def main():
    init_rollbar()
    init_logfire()
    setup_stdio_tee()
    verify_runtime_schema()

    # Mark any runs left in 'running' state from a previous crash/restart
    interrupted = interrupt_stale_runs()
    if interrupted:
        print(f"[runner] Startup: marked {interrupted} zombie run(s) as 'interrupted'")

    # Start global dispatcher thread (single process)
    dispatcher_thread = threading.Thread(target=dispatch_loop, daemon=True)
    dispatcher_thread.start()

    # Track which campaigns have a running worker thread
    active_workers: dict[str, dict] = {}

    while True:
        campaigns = fetch_enabled_campaigns()
        active_workers = _reconcile_workers(active_workers, campaigns)

        if not active_workers:
            print("[runner] No enabled campaigns found. Waiting...")

        time.sleep(_discovery_interval())


if __name__ == "__main__":
    main()
