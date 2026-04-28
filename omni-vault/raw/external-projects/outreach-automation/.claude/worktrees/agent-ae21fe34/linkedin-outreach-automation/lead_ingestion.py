# automation/lead_ingestion.py

from schema import ensure_schema
import uuid

from config import (
    LEADS_SHEET_ID,
    LEADS_TAB_NAME,
)
from google_sheets_service import fetch_leads
from db import lead_exists, insert_new_lead


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


def ingest_leads():
    ensure_schema()

    print("\n[ingestion] Reading leads from Google Sheet...")

    rows = fetch_leads(LEADS_SHEET_ID, LEADS_TAB_NAME)

    if not rows:
        print("[ingestion] No rows found.")
        return

    added = 0
    skipped = 0

    for row in rows:
        linkedin_url = (
            row.get("LinkedIn_URL")
            or row.get("linkedin_url")
            or ""
        )

        linkedin_url = normalize_linkedin_url(linkedin_url)

        if not linkedin_url:
            skipped += 1
            continue

        # 🔒 Global deduplication
        if lead_exists(linkedin_url):
            skipped += 1
            continue

        # ✅ NEW: product context (safe + optional)
        product_name = (row.get("product_name") or "").strip()
        product_url = (row.get("product_url") or "").strip()

        lead_id = str(uuid.uuid4())

        insert_new_lead(
            lead_id=lead_id,
            linkedin_url=linkedin_url,
            product_name=product_name,
            product_url=product_url,
        )

        print(f"[ingestion] + Added → {linkedin_url}")
        added += 1

    print(f"[ingestion] Completed | Added={added} | Skipped={skipped}\n")


if __name__ == "__main__":
    ingest_leads()
