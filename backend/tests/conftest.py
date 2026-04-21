"""Pytest fixtures for Omni Outreach backend tests."""

import asyncio
import os
from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI

# Point at test DB before importing app
os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://outreach:testpass@localhost:5432/outreach_test",
)
os.environ.setdefault("REDIS_PASSWORD", "")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def app() -> FastAPI:
    from app.main import app as _app
    return _app


@pytest.fixture(autouse=True)
async def _init_db_pool() -> AsyncGenerator[None, None]:
    """CI runs the tests without invoking the FastAPI lifespan, so the
    global asyncpg pool and Redis client never get initialised. Do it here.

    Must be function-scoped because pytest-asyncio gives each test a fresh
    event loop; an asyncpg pool bound to a prior loop raises
    "attached to a different loop"."""
    from app import db

    await db.init_pool(os.environ["DATABASE_URL"])
    try:
        await db.init_redis("redis://localhost:6379")
    except Exception:
        db.redis_client = None
    yield
    try:
        await db.close_pool()
    except Exception:
        pass
    try:
        await db.close_redis()
    except Exception:
        pass
    db._pool = None
    db.redis_client = None


@pytest.fixture()
async def client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
