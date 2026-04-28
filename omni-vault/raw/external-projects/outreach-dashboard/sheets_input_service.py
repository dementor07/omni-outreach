import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

from db import fetch_one
from lead_screener import screen_lead

load_dotenv()


def _service_account_file() -> str:
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not path:
        fallback = Path(__file__).parent.parent / "outreach_automation" / "google_service_account.json"
        if fallback.exists():
            path = str(fallback)
    if not path:
        raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON")
    return path


@lru_cache(maxsize=1)
def _gspread_client():
    creds = Credentials.from_service_account_file(
        _service_account_file(),
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(creds)


def _campaign_sheet_config(campaign_id: str) -> dict[str, Any]:
    row = fetch_one(
        """
        SELECT campaign_id, leads_sheet_id, leads_tab, manual_messages_sheet_id, manual_messages_tab
        FROM campaign_sheets
        WHERE campaign_id = %s
        """,
        (campaign_id,),
    )
    if not row:
        raise RuntimeError(f"No campaign_sheets row found for {campaign_id}")
    return dict(row)


def _open_worksheet(sheet_id: str, tab_name: str):
    ss = _gspread_client().open_by_key(sheet_id)
    return ss.worksheet(tab_name)


def _norm(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def normalize_linkedin_url(url: str) -> str:
    if not url:
        return ""
    url = str(url).strip()
    url = url.split("?")[0].rstrip("/")
    if "linkedin.com/in/" in url.lower():
        slug = url.split("linkedin.com/in/")[-1]
        return f"https://www.linkedin.com/in/{slug}".lower()
    return url.lower()


def _worksheet_headers(ws) -> list[str]:
    return ws.row_values(1)


def _header_index(headers: list[str], target: str) -> int | None:
    for idx, h in enumerate(headers):
        if _norm(h) == _norm(target):
            return idx
    return None


def _existing_values_by_header(ws, header_name: str) -> set[str]:
    headers = _worksheet_headers(ws)
    idx = _header_index(headers, header_name)
    if idx is None:
        return set()
    col_no = idx + 1
    values = ws.col_values(col_no)[1:]  # skip header
    if _norm(header_name) == "linkedin_url":
        return {normalize_linkedin_url(v) for v in values if v and v.strip()}
    return {v.strip() for v in values if v and v.strip()}


def _build_row(headers: list[str], row: dict[str, Any]) -> list[str]:
    normalized = {_norm(k): ("" if v is None else str(v)) for k, v in row.items()}

    if "name" not in normalized:
        fn = normalized.get("first_name", "").strip()
        ln = normalized.get("last_name", "").strip()
        full_name = (fn + " " + ln).strip()
        if full_name:
            normalized["name"] = full_name

    aliases = {
        "manual_message": ["message", "manual_message_text"],
    }
    for canonical, keys in aliases.items():
        if canonical in normalized:
            continue
        for key in keys:
            if key in normalized and normalized[key]:
                normalized[canonical] = normalized[key]
                break

    output = []
    for h in headers:
        output.append(normalized.get(_norm(h), ""))
    return output


def _lead_exists_in_db(campaign_id: str, linkedin_url: str) -> bool:
    normalized_url = normalize_linkedin_url(linkedin_url)
    row = fetch_one(
        """
        SELECT 1
        FROM (
            SELECT linkedin_url FROM leads WHERE campaign_id = %s
            UNION ALL
            SELECT linkedin_url FROM lead_full_stats WHERE campaign_id = %s
        ) x
        WHERE LOWER(REGEXP_REPLACE(SPLIT_PART(linkedin_url, '?', 1), '/+$', '')) = %s
        LIMIT 1
        """,
        (campaign_id, campaign_id, normalized_url),
    )
    return bool(row)


def _get_working_account_id(campaign_id: str) -> str:
    """Return an active linkedin account_id assigned to this campaign."""
    row = fetch_one(
        """
        SELECT cla.account_id
        FROM campaign_linkedin_accounts cla
        JOIN linkedin_accounts la ON la.account_id = cla.account_id
        WHERE cla.campaign_id = %s
          AND COALESCE(cla.status, 'active') = 'active'
        ORDER BY la.active_campaign_count ASC, cla.account_id ASC
        LIMIT 1
        """,
        (campaign_id,),
    )
    return row["account_id"] if row else ""


def _enrich_from_unipile(campaign_id: str, linkedin_url: str, row: dict) -> dict:
    """Fetch Unipile profile and merge headline, connections_count, follower_count, location into row.

    Raises RuntimeError if Unipile is misconfigured or returns an error — callers must handle this
    so screening never runs against a bare URL with no profile data.
    """
    slug = linkedin_url.split("linkedin.com/in/")[-1].rstrip("/")
    if not slug:
        raise RuntimeError(f"Could not extract slug from URL: {linkedin_url}")

    base = os.getenv("UNIPILE_BASE", "").rstrip("/")
    key = os.getenv("UNIPILE_API_KEY", "")
    if not base or not key:
        raise RuntimeError("UNIPILE_BASE or UNIPILE_API_KEY not configured")

    account_id = _get_working_account_id(campaign_id)
    if not account_id:
        raise RuntimeError(f"No working Unipile account found in DB for {campaign_id}")

    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{base}/api/v1/users/{slug}",
                headers={"X-API-KEY": key, "accept": "application/json"},
                params={"account_id": account_id},
                timeout=20,
            )
            if not resp.ok:
                raise RuntimeError(f"Unipile profile fetch failed: {resp.status_code} {resp.text[:200]}")
            break
        except requests.exceptions.RequestException as e:
            last_exc = e
            print(f"[enrich] attempt {attempt+1}/3 failed for {slug}: {e}", flush=True)
    else:
        raise RuntimeError(f"Unipile enrichment failed after 3 attempts: {last_exc}")

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


def _get_screening_prompt(campaign_id: str) -> str:
    """Load screening prompt — DB is primary, Drive is fallback."""
    # DB first
    row = fetch_one(
        "SELECT body FROM linkedin_templates WHERE campaign_id = %s AND template_key = 'screening_prompt' LIMIT 1",
        (campaign_id,),
    )
    if row and row.get("body", "").strip():
        return row["body"].strip()
    # Drive fallback
    import drive_config_service
    try:
        return drive_config_service.read_prompt(campaign_id, "screening_prompt") or ""
    except Exception:
        return ""


def append_leads(campaign_id: str, rows: list[dict[str, Any]], force_accept: bool = False, skip_sheet_dupes: bool = False) -> dict[str, Any]:
    cfg = _campaign_sheet_config(campaign_id)
    ws = _open_worksheet(cfg["leads_sheet_id"], cfg["leads_tab"])
    headers = _worksheet_headers(ws)
    existing_urls = _existing_values_by_header(ws, "linkedin_url")

    screening_prompt = _get_screening_prompt(campaign_id) if not force_accept else ""

    appended = 0
    skipped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    force_accepted: list[dict[str, Any]] = []
    batch: list[list[str]] = []
    batch_screening: list[tuple[str, str]] = []  # (verdict, reason) per batch row

    status_idx = _header_index(headers, "screening_status")
    reason_idx = _header_index(headers, "screening_reason")

    for idx, row in enumerate(rows):
        url = normalize_linkedin_url(row.get("linkedin_url", ""))
        if not url:
            skipped.append({"index": idx, "reason": "missing_linkedin_url"})
            continue
        if not skip_sheet_dupes and url in existing_urls:
            skipped.append({"index": idx, "reason": "duplicate_in_sheet", "linkedin_url": url})
            continue
        if _lead_exists_in_db(campaign_id, url):
            skipped.append({"index": idx, "reason": "duplicate_in_db", "linkedin_url": url})
            continue

        if force_accept:
            force_accepted.append({
                "index": idx,
                "linkedin_url": url,
                "first_name": row.get("first_name", ""),
            })
            batch_screening.append(("FORCE_ACCEPT", "manually force-accepted"))
        elif screening_prompt:
            try:
                enriched_row = _enrich_from_unipile(campaign_id, url, row)
            except (RuntimeError, requests.exceptions.RequestException) as e:
                skipped.append({"index": idx, "reason": "unipile_enrichment_failed",
                                "linkedin_url": url, "error": str(e)})
                continue
            verdict, reason = screen_lead(enriched_row, screening_prompt)
            if verdict == "REJECT":
                rejected.append({
                    "index": idx,
                    "linkedin_url": url,
                    "first_name": row.get("first_name", ""),
                    "screening_reason": reason,
                })
                skipped.append({"index": idx, "reason": "screening_rejected",
                                "linkedin_url": url, "screening_reason": reason})
                continue
            else:
                accepted.append({
                    "index": idx,
                    "linkedin_url": url,
                    "first_name": row.get("first_name", ""),
                    "screening_reason": reason,
                })
                batch_screening.append((verdict, reason))
        else:
            accepted.append({
                "index": idx,
                "linkedin_url": url,
                "first_name": row.get("first_name", ""),
                "screening_reason": "",
            })
            batch_screening.append(("", ""))

        row_with_normalized_url = dict(row)
        row_with_normalized_url["linkedin_url"] = url
        batch.append(_build_row(headers, row_with_normalized_url))
        existing_urls.add(url)

    if batch:
        # Find the row number of the first new row before appending
        first_new_row = len(ws.col_values(1)) + 1
        ws.append_rows(batch, value_input_option="RAW")
        appended = len(batch)

        # Write screening results back if columns exist
        if (status_idx is not None or reason_idx is not None) and batch_screening:
            sheet_updates = []
            for i, (verdict, reason) in enumerate(batch_screening):
                row_no = first_new_row + i
                if status_idx is not None and verdict:
                    col = chr(65 + status_idx)
                    sheet_updates.append({"range": f"{col}{row_no}", "values": [[verdict]]})
                if reason_idx is not None and reason:
                    col = chr(65 + reason_idx)
                    sheet_updates.append({"range": f"{col}{row_no}", "values": [[reason]]})
            if sheet_updates:
                ws.batch_update(sheet_updates)

    return {"appended": appended, "skipped": skipped, "rejected": rejected, "accepted": accepted, "force_accepted": force_accepted}


def rescreen_rejected(campaign_id: str, urls: list[str]) -> dict[str, Any]:
    """Re-screen specific URLs, skipping the sheet-duplicate check.

    Use this for leads that were previously rejected and never written to the sheet.
    Screens each URL fresh and appends accepted ones to the sheet as normal.
    """
    rows = [{"linkedin_url": u} for u in urls if u]
    return append_leads(campaign_id, rows, force_accept=False, skip_sheet_dupes=True)


def _lead_known_for_manual(campaign_id: str, linkedin_url: str) -> bool:
    return _lead_exists_in_db(campaign_id, linkedin_url)


def append_manual_messages(campaign_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = _campaign_sheet_config(campaign_id)
    ws = _open_worksheet(cfg["manual_messages_sheet_id"], cfg["manual_messages_tab"])
    headers = _worksheet_headers(ws)

    existing_pairs: set[tuple[str, str]] = set()
    try:
        for record in ws.get_all_records():
            normalized = {_norm(k): ("" if v is None else str(v).strip()) for k, v in record.items()}
            u = normalize_linkedin_url(normalized.get("linkedin_url", ""))
            m = normalized.get("manual_message") or normalized.get("message") or ""
            if u and m:
                existing_pairs.add((u, m))
    except Exception:
        existing_pairs = set()

    appended = 0
    skipped: list[dict[str, Any]] = []
    batch: list[list[str]] = []

    for idx, row in enumerate(rows):
        url = normalize_linkedin_url(row.get("linkedin_url", ""))
        msg = str(row.get("manual_message") or row.get("message") or "").strip()
        if not url or not msg:
            skipped.append({"index": idx, "reason": "missing_linkedin_url_or_message"})
            continue
        if not _lead_known_for_manual(campaign_id, url):
            skipped.append({"index": idx, "reason": "lead_not_found_in_db", "linkedin_url": url})
            continue
        if (url, msg) in existing_pairs:
            skipped.append({"index": idx, "reason": "duplicate_in_sheet", "linkedin_url": url})
            continue

        batch.append(_build_row(headers, row))
        existing_pairs.add((url, msg))

    if batch:
        ws.append_rows(batch, value_input_option="RAW")
        appended = len(batch)

    return {"appended": appended, "skipped": skipped}


def preview_sheet_headers(campaign_id: str) -> dict[str, Any]:
    cfg = _campaign_sheet_config(campaign_id)
    leads_ws = _open_worksheet(cfg["leads_sheet_id"], cfg["leads_tab"])
    manual_ws = _open_worksheet(cfg["manual_messages_sheet_id"], cfg["manual_messages_tab"])
    return {
        "leads_headers": _worksheet_headers(leads_ws),
        "manual_headers": _worksheet_headers(manual_ws),
    }
