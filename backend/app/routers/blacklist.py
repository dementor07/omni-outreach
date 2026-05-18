from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

router = APIRouter()


class BlacklistEntry(BaseModel):
    entry_type: str  # "email", "domain", "linkedin_url", "company"
    value: str
    reason: str = ""


class BlacklistBulk(BaseModel):
    entries: list[BlacklistEntry]


@router.get("")
async def list_blacklist(
    entry_type: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    user_id: str = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: list = []
    idx = 1

    if entry_type:
        conditions.append(f"entry_type=${idx}")
        params.append(entry_type)
        idx += 1

    if search:
        conditions.append(f"value ILIKE ${idx}")
        params.append(f"%{search}%")
        idx += 1

    where = " AND ".join(conditions)
    offset = (page - 1) * page_size
    rows = await fetch_all(
        f"SELECT * FROM blacklists WHERE {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
        *params,
        page_size,
        offset,
    )
    total = await fetch_one(f"SELECT COUNT(*) AS cnt FROM blacklists WHERE {where}", *params)
    return {"entries": rows, "total": total["cnt"], "page": page, "page_size": page_size}


@router.post("")
async def add_blacklist_entry(
    entry: BlacklistEntry,
    user_id: str = Depends(get_current_user),
):
    existing = await fetch_one(
        "SELECT id FROM blacklists WHERE entry_type=$1 AND value=$2",
        entry.entry_type,
        entry.value.strip().lower(),
    )
    if existing:
        raise HTTPException(400, "Entry already blacklisted")
    row = await fetch_one(
        "INSERT INTO blacklists (entry_type, value, reason) VALUES ($1, $2, $3) RETURNING *",
        entry.entry_type,
        entry.value.strip().lower(),
        entry.reason,
    )
    return row


@router.post("/bulk")
async def add_blacklist_bulk(
    payload: BlacklistBulk,
    user_id: str = Depends(get_current_user),
):
    added = 0
    skipped = 0
    for entry in payload.entries:
        existing = await fetch_one(
            "SELECT id FROM blacklists WHERE entry_type=$1 AND value=$2",
            entry.entry_type,
            entry.value.strip().lower(),
        )
        if existing:
            skipped += 1
            continue
        await execute(
            "INSERT INTO blacklists (entry_type, value, reason) VALUES ($1, $2, $3)",
            entry.entry_type,
            entry.value.strip().lower(),
            entry.reason,
        )
        added += 1
    return {"added": added, "skipped": skipped}


@router.delete("/{entry_id}")
async def remove_blacklist_entry(
    entry_id: str,
    user_id: str = Depends(get_current_user),
):
    await execute("DELETE FROM blacklists WHERE id=$1", entry_id)
    return {"ok": True}


async def is_blacklisted(value: str, entry_type: str = "email") -> bool:
    """Check if a value is blacklisted. Also checks domain for emails."""
    row = await fetch_one(
        "SELECT id FROM blacklists WHERE entry_type=$1 AND value=$2",
        entry_type,
        value.strip().lower(),
    )
    if row:
        return True
    # For emails, also check domain
    if entry_type == "email" and "@" in value:
        domain = value.split("@")[1].lower()
        row = await fetch_one(
            "SELECT id FROM blacklists WHERE entry_type='domain' AND value=$1",
            domain,
        )
        return row is not None
    return False
