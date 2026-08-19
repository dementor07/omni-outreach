"""POOL-SERIALIZE-001 — assigning seats to a campaign returned 500 on success.

update_workflow_pool runs inside `async with acquire()` so it can hold a
transaction, which means conn.fetch hands back asyncpg Records rather than the
dicts app.db.fetch_all produces. Pydantic v2 rejects a Record, and because the
return statement sits OUTSIDE the transaction block the pool was already
committed — the UI saw a 500 for a change that had in fact been saved.

Observed live 2026-08-18 while cloning Campaign 2: seats landed in
omni_campaign_sending_accounts, the endpoint reported HTTP 500.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "backend/app/routers/canvas.py").read_text(encoding="utf-8")


def test_pool_update_dicts_its_records_before_validating():
    body = SRC.split("async def update_workflow_pool")[1].split("\n@router")[0]
    assert "SendingAccountOut.model_validate(dict(r))" in body
    assert "SendingAccountOut.model_validate(r)" not in body


def test_the_pool_write_still_happens_in_a_transaction():
    """The commit-then-serialize ordering is why the bug was silent; keep the
    transaction, just stop crashing after it."""
    body = SRC.split("async def update_workflow_pool")[1].split("\n@router")[0]
    assert "async with conn.transaction():" in body
    assert "DELETE FROM omni_campaign_sending_accounts" in body
