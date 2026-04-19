"""Pytest fixtures for Omni Outreach backend tests."""

import os
import asyncio
from typing import AsyncGenerator

import pytest
import httpx
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


@pytest.fixture()
async def client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
