from arq.connections import RedisSettings


async def dispatch_queue(ctx):
    """Main dispatcher task — runs every 30s."""
    from app.services.dispatcher import run_once
    await run_once()


class WorkerSettings:
    redis_settings = RedisSettings(host="redis")
    cron_jobs = []
    functions = [dispatch_queue]
    job_timeout = 300
