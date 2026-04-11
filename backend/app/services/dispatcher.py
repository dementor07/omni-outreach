"""
Core outreach dispatcher.

run_once()          — picks up queued tasks and executes them
_queue_invitations() — assigns LinkedIn accounts to new leads and queues invite tasks
_check_acceptances() — detects accepted connections and triggers sequence scheduling
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db import execute, fetch_all, fetch_one
from app.services import linkedin, email, voice, renderer, sequencer

log = logging.getLogger(__name__)

BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 300  # 5 minutes


# ── Helpers ───────────────────────────────────────────────────────────────────

def _in_active_hours(campaign: dict) -> bool:
    tz = ZoneInfo(campaign.get("timezone") or "UTC")
    local_now = datetime.now(timezone.utc).astimezone(tz)
    h = local_now.hour
    return campaign["active_hours_start"] <= h < campaign["active_hours_end"]


def _next_window_start(campaign: dict) -> datetime:
    tz = ZoneInfo(campaign.get("timezone") or "UTC")
    local_now = datetime.now(timezone.utc).astimezone(tz)
    start_h = campaign["active_hours_start"]
    if local_now.hour < start_h:
        next_window = local_now.replace(hour=start_h, minute=0, second=0, microsecond=0)
    else:
        next_window = (local_now + timedelta(days=1)).replace(
            hour=start_h, minute=0, second=0, microsecond=0
        )
    return next_window.astimezone(timezone.utc)


def _public_id(linkedin_url: str) -> str:
    return linkedin_url.strip().rstrip("/").split("?")[0].split("/in/")[-1]


async def _log_event(
    lead_id: str, campaign_id: str, event_type: str,
    channel: str | None = None, meta: dict | None = None
) -> None:
    await execute(
        """
        INSERT INTO events (lead_id, campaign_id, event_type, channel, meta, occurred_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        """,
        lead_id, campaign_id, event_type, channel, meta or {},
    )


async def _mark_sent(queue_id: str) -> None:
    await execute(
        "UPDATE queue SET status='sent', sent_at=NOW(), locked_by=NULL WHERE id=$1",
        queue_id,
    )


async def _fail_task(queue_id: str, reason: str, current_retry: int) -> None:
    if current_retry < MAX_RETRIES:
        await execute(
            """
            UPDATE queue SET
                status='queued',
                retry_count=retry_count+1,
                scheduled_at=NOW() + ($1 || ' seconds')::interval,
                locked_by=NULL, locked_at=NULL,
                failure_reason=$2
            WHERE id=$3
            """,
            str(RETRY_DELAY_SECONDS), reason, queue_id,
        )
    else:
        await execute(
            "UPDATE queue SET status='failed', failure_reason=$1, locked_by=NULL WHERE id=$2",
            reason, queue_id,
        )


# ── Channel handlers ──────────────────────────────────────────────────────────

async def _handle_linkedin_invite(task: dict, lead: dict, campaign: dict) -> None:
    account = await fetch_one(
        "SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"]
    )
    if not account:
        raise RuntimeError("LinkedIn account not found")

    # Daily cap check
    tz = campaign.get("timezone") or "UTC"
    count_row = await fetch_one(
        """
        SELECT COUNT(*) AS cnt FROM queue q
        WHERE q.channel='linkedin_invite'
          AND q.status='sent'
          AND q.sent_at >= DATE_TRUNC('day', NOW() AT TIME ZONE $1)
          AND q.payload->>'linkedin_account_id' = $2
        """,
        tz, str(account["id"]),
    )
    daily_count = count_row["cnt"] if count_row else 0
    if daily_count >= account["daily_invite_cap"]:
        # Unlock without consuming retry
        await execute(
            "UPDATE queue SET status='queued', locked_by=NULL, locked_at=NULL WHERE id=$1",
            task["id"],
        )
        return

    provider_id = task.get("payload", {}).get("provider_id")
    if not provider_id:
        # Resolve from profile
        profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), account["unipile_id"])
        provider_id = profile.get("provider_id") or profile.get("id")
        if not provider_id:
            raise RuntimeError("Could not resolve provider_id from LinkedIn profile")

    await linkedin.send_invite(account["unipile_id"], provider_id)
    await execute("UPDATE leads SET invited_at=NOW() WHERE id=$1", lead["id"])
    await execute(
        "UPDATE queue SET payload=payload || $1 WHERE id=$2",
        {"provider_id": provider_id}, task["id"],
    )
    await _log_event(lead["id"], lead["campaign_id"], "invite_sent", "linkedin_invite")
    await _mark_sent(task["id"])


async def _handle_linkedin_dm(task: dict, lead: dict, campaign: dict) -> None:
    account = await fetch_one(
        "SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"]
    )
    if not account:
        raise RuntimeError("LinkedIn account not found")

    template = await fetch_one(
        "SELECT subject, body FROM templates WHERE step_id=$1 LIMIT 1", task["step_id"]
    )
    if not template:
        raise RuntimeError("No template found for step")

    message = renderer.render(template["body"], lead)

    if not lead.get("chat_id"):
        # First DM — open chat + send message atomically
        payload = task.get("payload", {})
        provider_id = payload.get("provider_id")
        if not provider_id:
            profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), account["unipile_id"])
            provider_id = profile.get("provider_id") or profile.get("id")
        data = await linkedin.start_chat_with_message(account["unipile_id"], provider_id, message)
        await execute("UPDATE leads SET chat_id=$1 WHERE id=$2", data["chat_id"], lead["id"])
    else:
        payload = task.get("payload", {})
        provider_id = payload.get("provider_id", "")
        await linkedin.send_message(lead["chat_id"], message, account["unipile_id"], provider_id)

    await _log_event(lead["id"], lead["campaign_id"], "dm_sent", "linkedin_dm")
    await _mark_sent(task["id"])


async def _handle_email(task: dict, lead: dict, campaign: dict) -> None:
    step = await fetch_one("SELECT * FROM sequence_steps WHERE id=$1", task["step_id"])
    if not step or not step.get("email_account_id"):
        raise RuntimeError("No email account configured for step")

    acct = await fetch_one("SELECT * FROM email_accounts WHERE id=$1", step["email_account_id"])
    if not acct:
        raise RuntimeError("Email account not found")

    template = await fetch_one(
        "SELECT subject, body FROM templates WHERE step_id=$1 LIMIT 1", task["step_id"]
    )
    if not template:
        raise RuntimeError("No template found for step")

    if not lead.get("email"):
        raise RuntimeError("Lead has no email address")

    subject = renderer.render(template["subject"] or "", lead)
    body = renderer.render(template["body"], lead)

    await email.send_email(
        from_name=acct["from_name"],
        from_email=acct["from_email"],
        smtp_host=acct["smtp_host"],
        smtp_port=acct["smtp_port"],
        smtp_username=acct["smtp_username"],
        smtp_password=acct["smtp_password"],
        smtp_use_tls=acct["smtp_use_tls"],
        to_email=lead["email"],
        subject=subject,
        body_html=body,
    )
    await _log_event(lead["id"], lead["campaign_id"], "email_sent", "email")
    await _mark_sent(task["id"])


async def _handle_voice(task: dict, lead: dict, campaign: dict) -> None:
    step = await fetch_one("SELECT * FROM sequence_steps WHERE id=$1", task["step_id"])
    if not step or not step.get("voice_agent_id"):
        raise RuntimeError("No voice agent configured for step")

    agent = await fetch_one("SELECT * FROM voice_agents WHERE id=$1", step["voice_agent_id"])
    if not agent:
        raise RuntimeError("Voice agent not found")

    if not lead.get("phone"):
        raise RuntimeError("Lead has no phone number")

    await voice.make_call(
        agent["retell_agent_id"],
        lead["phone"],
        metadata={"lead_id": str(lead["id"]), "campaign_id": str(lead["campaign_id"])},
    )
    await _log_event(lead["id"], lead["campaign_id"], "call_made", "voice")
    await _mark_sent(task["id"])


async def _process_task(task: dict, worker_id: str) -> None:
    campaign = await fetch_one("SELECT * FROM campaigns WHERE id=$1", task["campaign_id"])
    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", task["lead_id"])

    if not campaign or not lead:
        await _fail_task(task["id"], "campaign or lead not found", task["retry_count"])
        return

    # Active hours re-check
    if not _in_active_hours(campaign):
        next_start = _next_window_start(campaign)
        await execute(
            "UPDATE queue SET status='queued', locked_by=NULL, locked_at=NULL, scheduled_at=$1 WHERE id=$2",
            next_start, task["id"],
        )
        return

    # Simulation mode
    if campaign.get("simulation_mode"):
        log.info(f"[dispatcher:sim] task={task['id']} channel={task['channel']}")
        await _log_event(lead["id"], campaign["id"], f"simulated_{task['channel']}", task["channel"])
        await _mark_sent(task["id"])
        return

    try:
        ch = task["channel"]
        if ch == "linkedin_invite":
            await _handle_linkedin_invite(task, lead, campaign)
        elif ch == "linkedin_dm":
            await _handle_linkedin_dm(task, lead, campaign)
        elif ch == "email":
            await _handle_email(task, lead, campaign)
        elif ch == "voice":
            await _handle_voice(task, lead, campaign)
        else:
            raise RuntimeError(f"Unknown channel: {ch}")
    except Exception as e:
        log.exception(f"[dispatcher] task={task['id']} failed: {e}")
        await _fail_task(task["id"], str(e)[:500], task["retry_count"])


# ── Public interface ──────────────────────────────────────────────────────────

async def run_once(worker_id: str = "worker-0") -> None:
    """Batch-lock and process queued tasks."""
    tasks = await fetch_all(
        """
        WITH candidates AS (
            SELECT q.id FROM queue q
            JOIN campaigns c ON c.id = q.campaign_id
            WHERE q.status='queued'
              AND q.scheduled_at <= NOW()
              AND c.status='active'
            ORDER BY q.scheduled_at
            LIMIT $1
            FOR UPDATE OF q SKIP LOCKED
        )
        UPDATE queue SET status='locked', locked_at=NOW(), locked_by=$2
        FROM candidates
        WHERE queue.id=candidates.id
        RETURNING queue.*
        """,
        BATCH_SIZE, worker_id,
    )

    if not tasks:
        return

    log.info(f"[dispatcher] Locked {len(tasks)} tasks (worker={worker_id})")
    for task in tasks:
        await _process_task(task, worker_id)


async def _queue_invitations() -> None:
    """Assign LinkedIn accounts to new leads and create invite queue rows."""
    campaigns = await fetch_all("SELECT * FROM campaigns WHERE status='active'")

    for campaign in campaigns:
        if not _in_active_hours(campaign):
            continue

        # Leads needing invites
        leads = await fetch_all(
            """
            SELECT * FROM leads
            WHERE campaign_id=$1
              AND invited_at IS NULL
              AND linkedin_account_id IS NULL
              AND status='active'
            ORDER BY id
            LIMIT 100
            """,
            campaign["id"],
        )
        if not leads:
            continue

        # Available accounts for this campaign
        accounts = await fetch_all(
            """
            SELECT la.* FROM linkedin_accounts la
            JOIN campaign_linkedin_accounts cla ON cla.account_id=la.id
            WHERE cla.campaign_id=$1 AND la.is_active=TRUE
            ORDER BY la.id
            """,
            campaign["id"],
        )
        if not accounts:
            continue

        # Today's invite counts per account
        tz = campaign.get("timezone") or "UTC"
        counts_rows = await fetch_all(
            """
            SELECT l.linkedin_account_id, COUNT(*) AS cnt
            FROM queue q JOIN leads l ON l.id=q.lead_id
            WHERE q.channel='linkedin_invite'
              AND q.campaign_id=$1
              AND q.status IN ('queued','locked','sent')
              AND q.scheduled_at >= DATE_TRUNC('day', NOW() AT TIME ZONE $2)
            GROUP BY l.linkedin_account_id
            """,
            campaign["id"], tz,
        )
        counts = {str(r["linkedin_account_id"]): r["cnt"] for r in counts_rows}

        # Invite step (step_order=0)
        invite_step = await fetch_one(
            "SELECT id FROM sequence_steps WHERE campaign_id=$1 AND step_order=0 LIMIT 1",
            campaign["id"],
        )

        for lead in leads:
            # Pick account with fewest invites today that's under cap
            chosen = None
            for acct in sorted(accounts, key=lambda a: counts.get(str(a["id"]), 0)):
                if counts.get(str(acct["id"]), 0) < acct["daily_invite_cap"]:
                    chosen = acct
                    break
            if not chosen:
                break  # all accounts at cap

            # Atomic assign
            result = await fetch_one(
                """
                UPDATE leads SET linkedin_account_id=$1
                WHERE id=$2 AND linkedin_account_id IS NULL
                RETURNING id
                """,
                chosen["id"], lead["id"],
            )
            if not result:
                continue  # race — another worker got it

            counts[str(chosen["id"])] = counts.get(str(chosen["id"]), 0) + 1

            await execute(
                """
                INSERT INTO queue
                    (campaign_id, lead_id, step_id, channel, status, scheduled_at, payload)
                VALUES ($1, $2, $3, 'linkedin_invite', 'queued', NOW(), '{}')
                ON CONFLICT DO NOTHING
                """,
                campaign["id"], lead["id"],
                invite_step["id"] if invite_step else None,
            )
            log.info(f"[invitations] Lead {lead['id']} queued for invite via account {chosen['name']}")


async def _check_acceptances() -> None:
    """Detect accepted LinkedIn connections and trigger sequence scheduling."""
    pending = await fetch_all(
        """
        SELECT l.*, la.unipile_id AS unipile_account_id
        FROM leads l
        JOIN linkedin_accounts la ON la.id=l.linkedin_account_id
        WHERE l.invited_at IS NOT NULL
          AND l.accepted_at IS NULL
          AND l.status='active'
        ORDER BY l.invited_at ASC
        LIMIT 100
        """,
    )

    for lead in pending:
        try:
            profile = await linkedin.get_profile(
                _public_id(lead["linkedin_url"]),
                lead["unipile_account_id"],
            )
            if profile.get("network_distance") != "FIRST_DEGREE":
                continue

            # Atomic claim
            result = await fetch_one(
                "UPDATE leads SET accepted_at=NOW() WHERE id=$1 AND accepted_at IS NULL RETURNING id",
                lead["id"],
            )
            if not result:
                continue  # race

            await _log_event(lead["id"], lead["campaign_id"], "invite_accepted", "linkedin_invite")
            await sequencer.schedule_sequence(str(lead["id"]))
            log.info(f"[acceptances] Lead {lead['id']} accepted — sequence scheduled")

        except Exception as e:
            log.warning(f"[acceptances] Lead {lead['id']} error: {e}")
