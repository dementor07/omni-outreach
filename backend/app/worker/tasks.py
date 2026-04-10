import logging
from arq.connections import RedisSettings
from arq.cron import cron

from app.services import dispatcher

log = logging.getLogger(__name__)


async def dispatch_queue(ctx: dict) -> None:
    worker_id = f"arq-{ctx.get('job_id', '0')}"
    await dispatcher.run_once(worker_id=worker_id)
    await dispatcher._queue_invitations()


async def check_acceptances(ctx: dict) -> None:
    await dispatcher._check_acceptances()


async def startup(ctx: dict) -> None:
    from app.config import settings
    from app.db import init_pool
    dsn = settings.get_asyncpg_dsn()
    await init_pool(dsn)
    log.info("[worker] DB pool initialized")


async def shutdown(ctx: dict) -> None:
    from app.db import close_pool
    await close_pool()


class WorkerSettings:
    redis_settings = RedisSettings(host="redis")
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs = [
        cron(dispatch_queue, second={0, 30}),
        cron(check_acceptances, minute=set(range(0, 60, 5))),
    ]
    max_jobs = 1
    job_timeout = 300
