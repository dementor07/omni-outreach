import csv
import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, field_validator

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one
from app.services.lead_sources.base import RawLead

log = logging.getLogger(__name__)

router = APIRouter()


class LeadImport(BaseModel):
    linkedin_url: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    headline: str | None = None
    company: str | None = None
    source: str = "manual"

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v and ("linkedin.com/" not in v):
            raise ValueError("Must be a valid LinkedIn URL (https://...linkedin.com/...)")
        if v and not v.startswith("https://"):
            v = f"https://www.linkedin.com/in/{v.lstrip('/')}"
        return v or None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v and ("@" not in v or "." not in v.split("@")[-1]):
            raise ValueError("Invalid email format")
        return v or None

    def requires_identifier(self) -> bool:
        """At least one of linkedin_url, email, or phone must be present."""
        return bool(self.linkedin_url or self.email or self.phone)


@router.post("", status_code=201)
async def create_lead(
    campaign_id: str,
    body: LeadImport,
    user_id: str = Depends(get_current_user),
):
    """Add a single lead manually. Routes through upsert_lead so blacklist +
    daily cap + dedupe + email verification + cool-off all apply."""
    from app.services.lead_gen import upsert_lead

    if not body.requires_identifier():
        raise HTTPException(status_code=422, detail="At least one of linkedin_url or email is required")

    raw = RawLead(
        first_name=body.first_name or "",
        last_name=body.last_name or "",
        linkedin_url=body.linkedin_url,
        email=body.email,
        phone=body.phone,
        location=body.location,
        headline=body.headline or "",
        company=body.company or "",
    )
    inserted = await upsert_lead(campaign_id, raw, body.source or "manual")
    if not inserted:
        raise HTTPException(
            status_code=409,
            detail="Lead already exists or was rejected by intake gate (blacklist / dedupe / cap)",
        )
    lead = await fetch_one(
        "SELECT id FROM leads WHERE campaign_id=$1 AND (linkedin_url=$2 OR (linkedin_url IS NULL AND email=$3))",
        campaign_id,
        raw.linkedin_url,
        raw.email,
    )
    return {"id": str(lead["id"]) if lead else None, "status": "created"}


@router.get("")
async def list_leads(
    campaign_id: str,
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
    status: str | None = None,
    user_id: str = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    conditions = ["campaign_id=$1"]
    params: list = [campaign_id]
    idx = 2

    if status:
        conditions.append(f"status=${idx}")
        params.append(status)
        idx += 1

    if search:
        conditions.append(
            f"(first_name ILIKE ${idx} OR last_name ILIKE ${idx} OR company ILIKE ${idx} OR email ILIKE ${idx} OR headline ILIKE ${idx})"
        )
        params.append(f"%{search}%")
        idx += 1

    where = " AND ".join(conditions)
    rows = await fetch_all(
        f"SELECT * FROM leads WHERE {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
        *params,
        page_size,
        offset,
    )
    total = await fetch_one(f"SELECT COUNT(*) AS cnt FROM leads WHERE {where}", *params)
    return {"leads": rows, "total": total["cnt"], "page": page, "page_size": page_size}


@router.get("/{lead_id:uuid}")
async def get_lead(lead_id: str, user_id: str = Depends(get_current_user)):
    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    events = await fetch_all(
        "SELECT event_type, channel, meta, occurred_at FROM events WHERE lead_id=$1 ORDER BY occurred_at ASC",
        lead_id,
    )
    return {**lead, "timeline": events}


@router.post("/import")
async def import_leads(
    campaign_id: str,
    leads: list[LeadImport],
    user_id: str = Depends(get_current_user),
):
    """JSON batch import — routes through lead_gen.upsert_lead so blacklist +
    daily cap + dedupe gates apply uniformly."""
    from app.services.lead_gen import upsert_lead  # avoid circular import

    imported = 0
    skipped = 0
    blacklisted = 0
    for lead in leads:
        if not (lead.linkedin_url or lead.email or lead.phone):
            skipped += 1
            continue
        raw = RawLead(
            first_name=lead.first_name or "",
            last_name=lead.last_name or "",
            linkedin_url=lead.linkedin_url,
            email=lead.email,
            phone=lead.phone,
            location=lead.location,
            headline=lead.headline or "",
            company=lead.company or "",
        )
        inserted = await upsert_lead(campaign_id, raw, lead.source or "manual")
        if inserted:
            imported += 1
        else:
            skipped += 1
    return {"imported": imported, "skipped": skipped, "blacklisted": blacklisted}


# Column aliases accepted in CSV headers (case-insensitive, strip whitespace)
_COL_ALIASES: dict[str, str] = {
    "linkedin_url": "linkedin_url",
    "linkedin url": "linkedin_url",
    "linkedinurl": "linkedin_url",
    "profile_url": "linkedin_url",
    "profile url": "linkedin_url",
    "email": "email",
    "email address": "email",
    "first_name": "first_name",
    "first name": "first_name",
    "firstname": "first_name",
    "last_name": "last_name",
    "last name": "last_name",
    "lastname": "last_name",
    "surname": "last_name",
    "headline": "headline",
    "title": "headline",
    "job_title": "headline",
    "job title": "headline",
    "company": "company",
    "company_name": "company",
    "company name": "company",
    "organization": "company",
    "phone": "phone",
    "phone_number": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "mobile_number": "phone",
    "location": "location",
    "city": "location",
    "country": "location",
    "region": "location",
}


@router.post("/csv-upload")
async def csv_upload(
    campaign_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """Upload a CSV file of leads into a campaign.

    Accepts flexible column names (see _COL_ALIASES). Requires at least one of
    linkedin_url or email per row. Routes each row through lead_gen.upsert_lead
    so blacklist + daily cap + dedupe all apply.

    Returns: {imported, skipped, invalid, errors: [str]}
    """
    from app.services.lead_gen import upsert_lead

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    raw_bytes = await file.read()
    # Limit to 10 MB
    if len(raw_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV file exceeds 10 MB limit")

    try:
        text = raw_bytes.decode("utf-8-sig")  # strips BOM if present
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    # Map raw header names → canonical field names
    header_map: dict[str, str] = {}
    for raw_col in reader.fieldnames:
        canonical = _COL_ALIASES.get(raw_col.strip().lower())
        if canonical:
            header_map[raw_col] = canonical

    imported = 0
    skipped = 0
    invalid = 0
    errors: list[str] = []

    for row_num, row in enumerate(reader, start=2):  # row 1 is header
        mapped: dict[str, str] = {}
        for raw_col, canonical in header_map.items():
            val = (row.get(raw_col) or "").strip()
            if val:
                mapped[canonical] = val

        linkedin_url = mapped.get("linkedin_url")
        email = mapped.get("email")
        phone = mapped.get("phone")

        if not linkedin_url and not email and not phone:
            invalid += 1
            if len(errors) < 20:
                errors.append(f"Row {row_num}: at least one of linkedin_url, email, or phone is required")
            continue

        # Basic LinkedIn URL normalisation
        if linkedin_url and "linkedin.com/" not in linkedin_url:
            invalid += 1
            if len(errors) < 20:
                errors.append(f"Row {row_num}: invalid linkedin_url '{linkedin_url}'")
            continue

        raw_lead = RawLead(
            first_name=mapped.get("first_name", ""),
            last_name=mapped.get("last_name", ""),
            linkedin_url=linkedin_url,
            email=email,
            phone=mapped.get("phone"),
            location=mapped.get("location"),
            headline=mapped.get("headline", ""),
            company=mapped.get("company", ""),
        )

        try:
            inserted = await upsert_lead(campaign_id, raw_lead, "csv_upload")
            if inserted:
                imported += 1
            else:
                skipped += 1
        except Exception as exc:
            log.warning("[csv_upload] row %d upsert error: %s", row_num, exc)
            invalid += 1
            if len(errors) < 20:
                errors.append(f"Row {row_num}: {exc}")

    log.info(
        "[csv_upload] campaign=%s imported=%d skipped=%d invalid=%d",
        campaign_id,
        imported,
        skipped,
        invalid,
    )
    return {"imported": imported, "skipped": skipped, "invalid": invalid, "errors": errors}


@router.get("/export")
async def export_leads(
    campaign_id: str,
    user_id: str = Depends(get_current_user),
):
    """Export all leads for a campaign as a CSV file."""
    leads = await fetch_all(
        "SELECT * FROM leads WHERE campaign_id=$1 ORDER BY created_at ASC",
        campaign_id,
    )

    output = io.StringIO()
    if not leads:
        return {"detail": "No leads to export"}

    # Use first lead's keys as headers, excluding sensitive/internal fields
    headers = [
        k
        for k in leads[0].keys()
        if k not in ("linkedin_account_id", "instagram_account_id", "telegram_account_id", "current_node_id")
    ]
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for lead in leads:
        # Flatten extra_data or other JSON if needed, for now just cast to string
        row = {k: lead[k] for k in headers}
        writer.writerow(row)

    from fastapi.responses import StreamingResponse

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=leads_{campaign_id}.csv"},
    )


@router.delete("/{lead_id:uuid}", status_code=204)
async def stop_lead(lead_id: str, user_id: str = Depends(get_current_user)):
    lead = await fetch_one("SELECT id FROM leads WHERE id=$1", lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await execute("UPDATE leads SET status='stopped', stopped_at=NOW() WHERE id=$1", lead_id)
    await execute(
        "UPDATE queue SET status='skipped' WHERE lead_id=$1 AND status IN ('queued','locked')",
        lead_id,
    )


class BulkAction(BaseModel):
    lead_ids: list[str]
    action: str  # "stop", "requeue", "delete", "move_campaign", "add_tag"
    target_campaign_id: str | None = None
    tag: str | None = None


@router.post("/bulk")
async def bulk_lead_action(body: BulkAction, user_id: str = Depends(get_current_user)):
    """Perform bulk operations on multiple leads."""
    if not body.lead_ids:
        raise HTTPException(400, "No leads selected")

    affected = 0
    if body.action == "stop":
        for lid in body.lead_ids:
            await execute("UPDATE leads SET status='stopped', stopped_at=NOW() WHERE id=$1", lid)
            await execute("UPDATE queue SET status='skipped' WHERE lead_id=$1 AND status IN ('queued','locked')", lid)
            affected += 1

    elif body.action == "requeue":
        for lid in body.lead_ids:
            await execute("UPDATE leads SET status='active', stopped_at=NULL WHERE id=$1", lid)
            affected += 1

    elif body.action == "delete":
        for lid in body.lead_ids:
            await execute("DELETE FROM queue WHERE lead_id=$1", lid)
            await execute("DELETE FROM events WHERE lead_id=$1", lid)
            await execute("DELETE FROM leads WHERE id=$1", lid)
            affected += 1

    elif body.action == "move_campaign":
        if not body.target_campaign_id:
            raise HTTPException(400, "target_campaign_id required for move_campaign")
        for lid in body.lead_ids:
            await execute("UPDATE leads SET campaign_id=$1 WHERE id=$2", body.target_campaign_id, lid)
            affected += 1

    elif body.action == "add_tag":
        if not body.tag:
            raise HTTPException(400, "tag is required for add_tag action")
        for lid in body.lead_ids:
            await execute(
                "UPDATE leads SET tags = array_append(tags, $1) WHERE id=$2 AND NOT ($1 = ANY(tags))",
                body.tag,
                lid,
            )
            affected += 1

    else:
        raise HTTPException(400, f"Unknown action: {body.action}")

    return {"affected": affected, "action": body.action}
