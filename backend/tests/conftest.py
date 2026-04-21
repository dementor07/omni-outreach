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


@pytest.fixture(scope="session", autouse=True)
async def _init_db_pool() -> AsyncGenerator[None, None]:
    """CI runs without the FastAPI lifespan, so initialise the DB pool here.
    Redis is stubbed because CI Redis is available but the app doesn't
    require it during these smoke tests."""
    from app import db

    dsn = os.environ["DATABASE_URL"]
    await db.init_pool(dsn)
    redis_url = "redis://localhost:6379"
    try:
        await db.init_redis(redis_url)
    except Exception:
        pass
    yield
    try:
        await db.close_pool()
    except Exception:
        pass
    try:
        await db.close_redis()
    except Exception:
        pass


@pytest.fixture()
async def client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
