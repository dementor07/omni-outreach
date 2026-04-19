"""Smoke tests — health and auth endpoints."""

import pytest
import httpx


@pytest.mark.asyncio
async def test_health(client: httpx.AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_register_and_login(client: httpx.AsyncClient):
    payload = {"email": "ci@test.dev", "password": "StrongP@ss123"}
    resp = await client.post("/auth/register", json=payload)
    assert resp.status_code in (200, 201, 409)  # 409 if already exists

    resp = await client.post("/auth/login", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_unauthenticated_campaigns(client: httpx.AsyncClient):
    resp = await client.get("/campaigns")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_unauthenticated_leads(client: httpx.AsyncClient):
    resp = await client.get("/leads")
    assert resp.status_code in (401, 403)
