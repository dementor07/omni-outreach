# automation/lead_ingestion.py

import os
import uuid
import requests
from pathlib import Path

import config
from google_sheets_service import fetch_leads, get_worksheet
from db import lead_exists, insert_new_lead, append_timeline_event


def _enrich_from_unipile(linkedin_url: str, row: dict) -> dict:
    """
    Fetch LinkedIn profile from Unipile and merge headline, connections_count,
    follower_count, location into the row dict.

    Raises RuntimeError if Unipile is misconfigured or returns an error — callers must handle
    this so screening never runs against a bare URL with no profile data.
    """
    slug = linkedin_url.split("linkedin.com/in/")[-1].rstrip("/")
    if not slug:
        raise RuntimeError(f"Could not extract slug from URL: {linkedin_url}")

    base = config.cfg("UNIPILE_BASE")
    key = config.cfg("UNIPILE_API_KEY")
    if not base or not key:
        raise RuntimeError("UNIPILE_BASE or UNIPILE_API_KEY not configured")

    accounts_raw = config.cfg("ACCOUNTS", "")
    if isinstance(accounts_raw, list):
        all_accounts = [a.strip() for a in accounts_raw if a.strip()]
    else:
        all_accounts = [a.strip() for a in str(accounts_raw).split(",") if a.strip()]
    if not all_accounts:
        raise RuntimeError(f"No Unipile accounts configured for campaign {config.get_campaign_id()}")
    account_id = all_accounts[0]

    resp = requests.get(
        f"{base}/api/v1/users/{slug}",
        headers={"X-API-KEY": key, "accept": "application/json"},
        params={"account_id": account_id},
        timeout=20,
    )
    if not resp.ok:
        raise RuntimeError(f"Unipile profile fetch failed: {resp.status_code} {resp.text[:200]}")

    profile = resp.json()
    enriched = dict(row)
    if profile.get("headline"):
        enriched["headline"] = profile["headline"]
    if profile.get("first_name") and not enriched.get("first_name"):
        enriched["first_name"] = profile["first_name"]
    if profile.get("last_name") and not enriched.get("last_name"):
        enriched["last_name"] = profile["last_name"]
    if profile.get("connections_count") is not None:
        enriched["connections_count"] = profile["connections_count"]
    if profile.get("follower_count") is not None:
        enriched["follower_count"] = profile["follower_count"]
    if profile.get("location"):
        enriched["location"] = profile["location"]
    websites = profile.get("websites") or []
    if websites and not enriched.get("website"):
        enriched["website"] = websites[0]
    return enriched


def normalize_linkedin_url(url: str) -> str:
    """
    Normalize LinkedIn URLs for global deduplication.
    """
    if not url:
        return ""

    url = url.strip()
    url = url.split("?")[0].rstrip("/")

    if "linkedin.com/in/" in url:
        slug = url.split("linkedin.com/in/")[-1]
        return f"https://www.linkedin.com/in/{slug}"

    return url


def _load_screening_prompt(campaign_id: str) -> str:
    """Load screening_prompt.txt from the local campaign folder (synced from Drive)."""
    try:
        path = Path(__file__).parent / "campaigns" / campaign_id / "prompts" / "screening_prompt.txt"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _ensure_screening_columns(ws, headers: list[str]) -> tuple[int, int]:
    """Ensure screening_status and screening_reason columns exist. Returns their 1-based col indices."""
    status_col = None
    reason_col = None
    for i, h in enumerate(headers):
        if h.strip().lower() == "screening_status":
            status_col = i + 1
        if h.strip().lower() == "screening_reason":
            reason_col = i + 1

    if status_col is None:
        ws.update_cell(1, len(headers) + 1, "screening_status")
        status_col = len(headers) + 1
        headers.append("screening_status")
    if reason_col is None:
        ws.update_cell(1, len(headers) + 1, "screening_reason")
        reason_col = len(headers) + 1
        headers.append("screening_reason")
    return status_col, reason_col


def ingest_leads():
    import sys

    print("\n[ingestion] Reading leads from Google Sheet...", flush=True)

    sheet_id = config.cfg("LEADS_SHEET_ID")
    tab_name = config.cfg("LEADS_TAB_NAME")
    campaign_id = config.get_campaign_id()

    ws = get_worksheet(sheet_id, tab_name)
    expected_headers = ws.row_values(1)
    all_records = ws.get_all_records(expected_headers=expected_headers)

    if not all_records:
        print("[ingestion] No rows found.", flush=True)
        return

    screening_prompt = _load_screening_prompt(campaign_id)
    if screening_prompt:
        print(f"[ingestion] Screening enabled for {campaign_id}", flush=True)
        try:
            # Import screener — lives in dashboard repo, try relative path
            dashboard_path = Path(__file__).parent.parent / "outreach-dashboard"
            if str(dashboard_path) not in sys.path:
                sys.path.insert(0, str(dashboard_path))
            from lead_screener import screen_lead
        except ImportError:
            print("[ingestion] WARNING: lead_screener not found — screening disabled", flush=True)
            screening_prompt = ""
            screen_lead = None
    else:
        screen_lead = None

    headers = ws.row_values(1)
    if screening_prompt:
        status_col, reason_col = _ensure_screening_columns(ws, headers)

    added = 0
    skipped = 0
    rejected = 0
    global_dedup = str(config.cfg("GLOBAL_DEDUP", "false")).lower() == "true"

    for row_idx, row in enumerate(all_records, start=2):  # start=2: row 1 is header
        linkedin_url = (
            row.get("LinkedIn_URL")
            or row.get("linkedin_url")
            or ""
        )

        linkedin_url = normalize_linkedin_url(linkedin_url)

        if not linkedin_url:
            skipped += 1
            continue

        # 🔒 Deduplication (global or per-campaign based on campaign config)
        if lead_exists(linkedin_url, campaign_id, global_dedup=global_dedup):
            skipped += 1
            continue

        # 🔍 LLM screening (if enabled)
        if screening_prompt and screen_lead:
            # Skip rows already screened
            existing_status = str(row.get("screening_status", "")).strip().upper()
            if existing_status in ("ACCEPT", "REJECT"):
                if existing_status == "REJECT":
                    skipped += 1
                    continue
            else:
                try:
                    enriched_row = _enrich_from_unipile(linkedin_url, row)
                except RuntimeError as e:
                    print(f"[ingestion] ERROR: Unipile enrichment failed for {linkedin_url}: {e}", flush=True)
                    skipped += 1
                    continue
                verdict, reason = screen_lead(enriched_row, screening_prompt)
                try:
                    ws.update_cell(row_idx, status_col, verdict)
                    ws.update_cell(row_idx, reason_col, reason)
                except Exception as e:
                    print(f"[ingestion] WARNING: could not write screening result: {e}", flush=True)
                if verdict == "REJECT":
                    print(f"[ingestion] ✗ Rejected → {linkedin_url} ({reason})", flush=True)
                    rejected += 1
                    skipped += 1
                    continue

        # ✅ product context (safe + optional)
        product_name = (row.get("product_name") or "").strip()
        product_url = (row.get("product_url") or "").strip()

        lead_id = str(uuid.uuid4())

        insert_new_lead(
            lead_id=lead_id,
            linkedin_url=linkedin_url,
            campaign_id=campaign_id,
            product_name=product_name,
            product_url=product_url,
        )

        append_timeline_event(
            lead_id=lead_id,
            campaign_id=campaign_id,
            event_type="lead_ingested",
        )

        print(f"[ingestion] + Added → {linkedin_url}", flush=True)
        added += 1

    print(f"[ingestion] Completed | Added={added} | Rejected={rejected} | Skipped={skipped}\n", flush=True)


if __name__ == "__main__":
    ingest_leads()
