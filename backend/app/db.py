from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from redis import asyncio as aioredis

_pool: asyncpg.Pool | None = None
redis_client: aioredis.Redis | None = None


async def init_pool(dsn: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, ssl=False)

async def init_redis(url: str = "redis://redis:6379") -> None:
    global redis_client
    redis_client = aioredis.from_url(url, decode_responses=True)

async def close_pool() -> None:
    if _pool:
        await _pool.close()

async def close_redis() -> None:
    if redis_client:
        await redis_client.aclose()


@asynccontextmanager
async def acquire() -> AsyncGenerator[asyncpg.Connection, None]:
    async with _pool.acquire() as conn:
        yield conn


async def fetch_all(query: str, *args) -> list[dict]:
    async with acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]


async def fetch_one(query: str, *args) -> dict | None:
    async with acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None


async def execute(query: str, *args) -> str:
    async with acquire() as conn:
        return await conn.execute(query, *args)
