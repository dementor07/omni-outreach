"""
enrich_and_filter_leads.py

1. Reads normalized leads from producthunt_leads.csv
2. Enriches each lead using Unipile LinkedIn profile API
3. Uses LLM to decide if the lead is a business-relevant decision maker
4. Writes filtered_leads.csv

NO Google Sheets push here (single responsibility).
"""

import pandas as pd
import requests
import json
import time
import random
import os
import sys
from openai import OpenAI

# ==========================
# UTF-8 SAFETY
# ==========================
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ==========================
# FILE CONFIG
# ==========================
INPUT_FILE = "producthunt_leads.csv"
OUTPUT_FILE = "filtered_leads.csv"

# ==========================
# UNIPILE CONFIG
# ==========================
UNIPILE_BASE_URL = "https://api10.unipile.com:14090"
UNIPILE_API_KEY = os.getenv("UNIPILE_API_KEY")
UNIPILE_ACCOUNT_ID = "18jMOXm8SrOxwWP8dXfw3Q"

# ==========================
# LLM CONFIG
# ==========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0

llm_client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
# UNIPILE FETCH
# ==========================
def fetch_linkedin_profile(slug):
    """
    Fetch LinkedIn profile from Unipile using public identifier (slug).
    Returns JSON dict or None.
    """
    url = f"{UNIPILE_BASE_URL}/api/v1/users/{slug}"
    headers = {
        "accept": "application/json",
        "X-API-KEY": UNIPILE_API_KEY
    }
    params = {
        "account_id": UNIPILE_ACCOUNT_ID
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            print(f"      ❌ Unipile error {response.status_code}: {response.text}")
            return None
        return response.json()
    except Exception:
        return None


# ==========================
# LLM DECISION
# ==========================
def llm_decide(headline, product_name, website):
    """
    Decide whether the lead is worth contacting.
    Returns dict with decision + reason.
    """

    prompt = f"""
You are filtering B2B outreach leads.

ACCEPT if the person is:
- Founder, Co-Founder, CEO, CTO (startup context)
- CMO, VP Marketing, Head of Marketing, Director of Marketing
- Growth Lead or Product Marketing leader

REJECT if the person is:
- Software Engineer, Developer, QA
- HR, Recruiter, Talent
- Student or Intern
- Individual contributor with no decision authority

Profile Information:
Headline: {headline}
Website: {website}
Product: {product_name}

Respond ONLY in JSON:
{{
  "decision": "accept" or "reject",
  "reason": "short reason"
}}
"""

    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.choices[0].message.content.strip()

        # ✅ ONLY REQUIRED FIX: robust JSON extraction
        start = content.find("{")
        end = content.rfind("}") + 1
        if start == -1 or end == -1:
            raise ValueError("No JSON object found in LLM response")

        json_str = content[start:end]
        return json.loads(json_str)

    except Exception:
        return {"decision": "reject", "reason": "LLM failure or invalid response"}


# ==========================
# MAIN
# ==========================
def main():
    df = pd.read_csv(INPUT_FILE)
    print(f"Loaded {len(df)} leads from {INPUT_FILE}")

    accepted_rows = []

    for idx, row in df.iterrows():
        slug = row["slug"]
        print(f"[{idx+1}/{len(df)}] Enriching: {slug}")

        profile = fetch_linkedin_profile(slug)

        # Rate-limit safety (VERY IMPORTANT)
        time.sleep(random.uniform(1.5, 3.0))

        if not profile:
            print("   ⚠️  Unipile profile fetch failed")
            continue

        headline = profile.get("headline", "")
        websites = profile.get("websites", [])
        website = websites[0] if websites else ""

        decision = llm_decide(
            headline=headline,
            product_name=row["product_name"],
            website=website
        )

        status = decision.get("decision", "reject")
        reason = decision.get("reason", "")

        if status == "accept":
            print(f"   ✅ ACCEPTED | {headline} | {reason}")
            accepted_rows.append({
                **row.to_dict(),
                "headline": headline,
                "website": website,
                "decision": "accept",
                "reason": reason
            })
        else:
            print(f"   ❌ REJECTED | {headline} | {reason}")

        # Small pause for LLM rate safety
        time.sleep(random.uniform(0.2, 0.4))

    out_df = pd.DataFrame(accepted_rows)
    out_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    print(f"\n✅ {len(out_df)} leads accepted and saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
