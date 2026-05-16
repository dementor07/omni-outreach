import logging
import os
from datetime import UTC, datetime

from arq.connections import RedisSettings
from arq.cron import cron

from app.services import dispatcher
from app.services.optimization import run_optimization

log = logging.getLogger(__name__)

_redis_password = os.environ.get("REDIS_PASSWORD", "changeme") or None


async def dispatch_queue(ctx: dict) -> None:
    worker_id = f"arq-{ctx.get('job_id', '0')}"
    await dispatcher.run_once(worker_id=worker_id)
    await dispatcher._queue_invitations()


async def check_acceptances(ctx: dict) -> None:
    await dispatcher._check_acceptances()


async def optimize_splits(ctx: dict) -> None:
    await run_optimization()


async def cron_reply_intent_timeout(ctx: dict) -> None:
    from app.services.sequencer import check_reply_intent_timeouts
    await check_reply_intent_timeouts()


async def cron_lead_gen(ctx: dict) -> None:
    """Fires any enabled lead_gen_configs whose cron_schedule is due."""
    try:
        from croniter import croniter
    except ImportError:
        log.warning("[worker] croniter not installed — skipping cron_lead_gen")
        return

    from app.db import fetch_all
    from app.services.lead_gen import run_lead_gen

    rows = await fetch_all(
        """
        SELECT id, campaign_id, cron_schedule, last_run_at
        FROM lead_gen_configs
        WHERE cron_schedule IS NOT NULL AND is_enabled = TRUE
        """
    )
    now = datetime.now(UTC)
    for row in rows:
        schedule = row["cron_schedule"]
        if not croniter.is_valid(schedule):
            log.warning(f"[worker] Invalid cron '{schedule}' on config {row['id']}")
            continue
        base = row["last_run_at"] or now.replace(year=now.year - 1)
        itr = croniter(schedule, base)
        next_fire = itr.get_next(datetime)
        if next_fire <= now:
            log.info(f"[worker] Firing scheduled lead gen for config {row['id']}")
            try:
                await run_lead_gen(str(row["campaign_id"]), str(row["id"]), triggered_by="schedule")
            except Exception as e:
                log.error(f"[worker] Scheduled lead gen {row['id']} failed: {e}", exc_info=True)


async def startup(ctx: dict) -> None:
    from app.config import settings
    from app.db import init_pool, init_redis
    dsn = settings.get_asyncpg_dsn()
    await init_pool(dsn)
    await init_redis(settings.get_redis_url())
    log.info("[worker] SOTA Maintenance Worker initialized")


async def shutdown(ctx: dict) -> None:
    from app.db import close_pool, close_redis
    await close_pool()
    await close_redis()


class WorkerSettings:
    redis_settings = RedisSettings(host="redis", password=_redis_password)
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs = [
        # Maintenance only. Delivery and Progression are now handled by Rust/Flink.
        cron(optimize_splits, minute=set(range(0, 60, 10))),
        cron(cron_reply_intent_timeout, minute={0, 30}),
    ]
    max_jobs = 1
    job_timeout = 300
