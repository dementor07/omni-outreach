from arq import create_pool
from arq.connections import RedisSettings

from app.worker.tasks import WorkerSettings


async def main():
    await create_pool(RedisSettings())
    print("Worker started")


if __name__ == "__main__":
    import arq
    arq.run_worker(WorkerSettings)
