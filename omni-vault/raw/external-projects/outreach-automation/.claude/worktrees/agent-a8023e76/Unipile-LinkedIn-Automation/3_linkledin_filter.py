import pandas as pd
import requests
import time
import os
import re

# ==========================================================
# 🔧 Load Config
# ==========================================================
import json

with open("config.json", "r") as f:
    CONFIG = json.load(f)

API_BASE_URL = CONFIG["BASE_URL"]
API_KEY = CONFIG["API_KEY"]
ACCOUNT_ID = CONFIG["ACCOUNT_ID"]

SAVE_INTERVAL = 10
ROW_LIMIT = 10
API_DELAY = 0.5

# ==========================================================
# 🧱 Utility: Headers
# ==========================================================
def base_headers():
    return {
        "accept": "application/json",
        "X-API-KEY": API_KEY
    }

# ==========================================================
# 🔎 Helpers: Estimators & detectors
# ==========================================================
def estimate_experience_from_text(text: str) -> int:
    if not text:
        return 0

    m = re.search(r"(\d{1,2})\s*\+?\s*(?:years|yrs|Years|Years Experience|Years experience)", text)
    if m:
        try:
            return int(m.group(1))
        except:
            pass

    text_l = text.lower()
    senior_keywords = ["founder", "co-founder", "ceo", "managing director", "md", "director", "head", "lead", "cofounder", "cto", "cxo", "vp", "vice president", "owner", "president", "partner"]
    mid_keywords = ["manager", "associate", "engineer", "consultant", "product", "architect", "analyst"]
    junior_keywords = ["intern", "student", "trainee", "junior"]

    if any(k in text_l for k in senior_keywords):
        return 5
    if any(k in text_l for k in mid_keywords):
        return 3
    if any(k in text_l for k in junior_keywords):
        return 0

    return 2

def detect_company_profile(data: dict) -> bool:
    first = data.get("first_name")
    last = data.get("last_name")
    headline = (data.get("headline") or "").lower()

    org_indicators = [
        "company", "inc", "llp", "ltd", "pvt ltd", "pvt. ltd",
        "limited", "startup", "solutions", "technologies", "systems", "agency"
    ]

    if not first and not last:
        return True

    if any(ind in headline for ind in org_indicators):
        if len(headline.split()) <= 4:
            return True

    return False

def extract_country_from_location(raw_location: str) -> str:
    if not raw_location:
        return ""
    parts = [p.strip() for p in raw_location.split(",") if p.strip()]
    return parts[-1] if parts else ""

# ==========================================================
# 1️⃣ Fetch LinkedIn Profile Details
# ==========================================================
def fetch_profile_details(linkedin_url: str):
    try:
        identifier = linkedin_url.rstrip("/").split("/")[-1]
        identifier = identifier.split("?")[0].strip()

        url = f"{API_BASE_URL}/users/{identifier}?account_id={ACCOUNT_ID}"
        response = requests.get(url, headers=base_headers(), timeout=20)
        response.raise_for_status()
        data = response.json()

        raw_location = data.get("location", "") or ""
        country = extract_country_from_location(raw_location)

        if not country:
            country = data.get("primary_locale", {}).get("country", "")

        role = data.get("headline", "") or ""
        followers = data.get("follower_count", 0)
        experience_years = estimate_experience_from_text(role)
        is_company = detect_company_profile(data)

        return {
            "country": country,
            "role": role,
            "followers": followers,
            "experience_year_years": experience_years,
            "experience_years": experience_years,
            "is_company": is_company,
            "error_404": False
        }

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            print(f"[404] Profile not found: {linkedin_url}")
            return {"error_404": True}
        print(f"[API ERROR] {linkedin_url}: {e} -> {getattr(e.response, 'text', '')}")
        return {"error_404": True}

    except Exception as e:
        print(f"[FETCH ERROR] {linkedin_url}: {e}")
        return {"error_404": True}

# ==========================================================
# 2️⃣ Filter Logic
# ==========================================================
def apply_filters(profile):
    excluded_countries = [
        "Pakistan", "Bangladesh", "Nepal", "Myanmar",
        "Sri Lanka", "Vietnam", "Nigeria"
    ]

    if profile.get("error_404"):
        return False, "404 Error"

    if profile.get("is_company"):
        return False, "Company page"

    country_val = (profile.get("country") or "").strip()
    if any(country_val.lower() == exc.lower() for exc in excluded_countries):
        return False, f"Country excluded ({country_val})"

    role_text = (profile.get("role") or "").lower()
    if not any(k in role_text for k in ["founder", "co-founder", "cofounder", "ceo", "managing director", "managing", "director"]):
        return False, f"Invalid role ({profile.get('role')})"

    if profile.get("experience_years", 0) < 2:
        return False, f"Insufficient experience ({profile.get('experience_years')} years)"

    if profile.get("followers", 0) < 205:
        return False, f"Followers below threshold ({profile.get('followers')})"

    return True, "All criteria passed"

# ==========================================================
# 3️⃣ Process Members
# ==========================================================
def process_members(input_csv="member_slugs_ready.csv", output_csv="filtered_members.csv"):
    df = pd.read_csv(input_csv)
    total_rows = len(df)

    if ROW_LIMIT:
        df = df.head(ROW_LIMIT)

    results = []
    partial_file = "filtered_members_partial.csv"

    print(f"[START] Processing {len(df)} members (of {total_rows}) from {input_csv}")

    for idx, row in df.iterrows():
        linkedin_url = str(row["LinkedIn_URL"]).strip()
        name = str(row.get("Name", "")).strip()

        print(f"\n[{idx+1}/{len(df)}] Checking: {name} - {linkedin_url}")

        profile = fetch_profile_details(linkedin_url)
        passed, reason = apply_filters(profile)

        results.append({
            "Country": profile.get("country"),
            "Role": profile.get("role"),
            "Followers": profile.get("followers"),
            "Experience": profile.get("experience_years"),
            "Status": "Accepted" if passed else "Rejected",
            "Reason": reason
        })

        if (idx + 1) % SAVE_INTERVAL == 0:
            temp_df = pd.DataFrame(results)
            temp_df.to_csv(partial_file, index=False)
            print(f"[AUTO-SAVE] Progress saved at row {idx+1} → {partial_file}")

        time.sleep(API_DELAY)

    final_results = []
    for original, filtered in zip(df.to_dict(orient="records"), results):
        merged = {**original, **filtered}
        final_results.append(merged)

    output_df = pd.DataFrame(final_results)

    accepted_df = output_df[output_df["Status"] == "Accepted"]
    rejected_df = output_df[output_df["Status"] == "Rejected"]

    accepted_df.to_csv("filtered_members_accepted.csv", index=False)
    rejected_df.to_csv("filtered_members_rejected.csv", index=False)

    print("\n✅ Filtering complete.")
    print(f"✔ Accepted saved to: filtered_members_accepted.csv ({len(accepted_df)})")
    print(f"✔ Rejected saved to: filtered_members_rejected.csv ({len(rejected_df)})")

    if os.path.exists(partial_file):
        os.remove(partial_file)
        print("[CLEANUP] Partial file removed.")

# ==========================================================
# 🚀 Main Execution
# ==========================================================
if __name__ == "__main__":
    process_members()
