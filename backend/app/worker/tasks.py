import logging
import os
from arq.connections import RedisSettings
from arq.cron import cron

from app.services import dispatcher
from app.services.optimization import run_optimization
from app.worker.stream_processor import process_stream_events

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


async def startup(ctx: dict) -> None:
    from app.config import settings
    from app.db import init_pool, init_redis
    dsn = settings.get_asyncpg_dsn()
    await init_pool(dsn)
    await init_redis(settings.get_redis_url())
    log.info("[worker] DB pool and Redis initialized")


async def shutdown(ctx: dict) -> None:
    from app.db import close_pool, close_redis
    await close_pool()
    await close_redis()


class WorkerSettings:
    redis_settings = RedisSettings(host="redis", password=_redis_password)
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs = [
        cron(dispatch_queue, second={0, 30}),
        cron(check_acceptances, minute=set(range(0, 60, 5))),
        cron(process_stream_events, second=set(range(0, 60, 5))),
        cron(optimize_splits, minute=set(range(0, 60, 10))),
    ]
    max_jobs = 1
    job_timeout = 300
