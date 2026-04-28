"""
profile_scraper.py
Open each maker's profile from output2.csv
Extract links ONLY from the "Links" section (LinkedIn, YouTube, Website, etc.)
Save results in a new CSV with added columns immediately after each maker's Link.
"""

import os
import time
import traceback
import pandas as pd
import undetected_chromedriver as uc
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# === CONFIG ===
INPUT_CSV = "output2.csv"
USER_DATA_DIR = r"D:/Work/chrome_profile"
WAIT_SHORT = 5
WAIT_LONG = 15
MAX_RETRIES = 3
ROW_LIMIT = 2000

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_CSV = f"output_final_{timestamp}.csv"

# === DRIVER (FIXED: NO DISPLAY BLUR) ===
def build_driver():
    options = uc.ChromeOptions()

    if USER_DATA_DIR:
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        options.add_argument(f"--user-data-dir={USER_DATA_DIR}")

    # 🔧 DISPLAY / GPU FIXES (CRITICAL)
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1280,800")

    options.add_argument("--disable-blink-features=AutomationControlled")

    return uc.Chrome(options=options)

def extract_links_from_section(driver, profile_url):
    social_links = {}

    for attempt in range(MAX_RETRIES):
        try:
            driver.get(profile_url)
            WebDriverWait(driver, WAIT_LONG).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, "a"))
            )
            time.sleep(1.5)

            try:
                links_section = driver.find_element(
                    By.XPATH,
                    "//h2[text()='Links']/following-sibling::div"
                )
            except Exception:
                return {}

            links = links_section.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href")
                if not href:
                    continue

                href_lower = href.lower()
                if "linkedin.com" in href_lower:
                    social_links["Linkedin"] = href
                elif "twitter.com" in href_lower or "x.com" in href_lower:
                    social_links["Twitter"] = href
                elif "github.com" in href_lower:
                    social_links["GitHub"] = href
                elif "youtube.com" in href_lower or "youtu.be" in href_lower:
                    social_links["YouTube"] = href
                elif "instagram.com" in href_lower:
                    social_links["Instagram"] = href
                elif any(x in href_lower for x in ["medium.com", "blog", "substack.com"]):
                    social_links["Blog"] = href
                elif "facebook.com" in href_lower:
                    social_links["Facebook"] = href
                elif "t.me" in href_lower or "telegram.me" in href_lower:
                    social_links["Telegram"] = href
                elif "producthunt.com" not in href_lower and href_lower.startswith("http"):
                    if "Website" not in social_links:
                        social_links["Website"] = href

            break

        except Exception:
            time.sleep(2)
            continue

    return social_links

# === MAIN ===
def main():
    df = pd.read_csv(INPUT_CSV)
    print(f"Loaded {len(df)} products from '{INPUT_CSV}'")

    df = df.head(ROW_LIMIT)
    print(f"Processing only first {len(df)} products for now.\n")

    driver = None
    all_data = []

    try:
        driver = build_driver()
        print("Driver launched.\n")

        for idx, row in df.iterrows():
            print(f"[{idx+1}/{len(df)}] Processing product: {row['Title']}")
            row_data = row.to_dict()

            maker_columns = [col for col in df.columns if "_Name" in col]

            for maker_col in maker_columns:
                maker_index = maker_col.replace("Maker", "").replace("_Name", "")
                link_col = f"Maker{maker_index}_Link"
                profile_url = row.get(link_col, "")

                if pd.isna(profile_url) or not profile_url.startswith("http"):
                    continue

                social_links = extract_links_from_section(driver, profile_url)

                for platform in [
                    "Website", "Linkedin", "Twitter", "GitHub",
                    "YouTube", "Instagram", "Blog", "Facebook", "Telegram"
                ]:
                    row_data[f"Maker{maker_index}_{platform}"] = social_links.get(platform, "")

            all_data.append(row_data)

        df_out = pd.DataFrame(all_data)

        original_cols = list(df.columns)
        social_platforms = [
            "Website", "Linkedin", "Twitter", "GitHub",
            "YouTube", "Instagram", "Blog", "Facebook", "Telegram"
        ]

        final_cols = []
        for col in original_cols:
            final_cols.append(col)
            if "_Link" in col:
                maker_index = col.replace("Maker", "").replace("_Link", "")
                for platform in social_platforms:
                    social_col = f"Maker{maker_index}_{platform}"
                    if social_col in df_out.columns:
                        final_cols.append(social_col)

        for col in df_out.columns:
            if col not in final_cols:
                final_cols.append(col)

        df_out = df_out[final_cols]
        df_out.to_csv(OUTPUT_CSV, index=False)

        print(f"\n✅ Scraping complete. Saved {len(df_out)} products to '{OUTPUT_CSV}'")

    except Exception as exc:
        print("ERROR:", exc)
        traceback.print_exc()

    finally:
        if driver:
            print("Driver still running (close manually).")

if __name__ == "__main__":
    main()
