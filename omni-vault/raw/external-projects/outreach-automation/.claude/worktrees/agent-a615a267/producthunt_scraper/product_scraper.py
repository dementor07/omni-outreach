"""
product_scraper.py
Scrape Product Hunt product pages to extract:
- Company website (from Overview page)
- Makers (from Team tab), max 7
- Prefer makers with keywords; if less than 5, fill with others

Uses undetected-chromedriver + Selenium.
"""

import os
import time
import traceback
import pandas as pd
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# === CONFIG ===
INPUT_CSV = "output1.csv"
OUTPUT_CSV = "output2.csv"
USER_DATA_DIR = r"D:/Work/chrome_profile"
WAIT_LONG = 30

ROW_LIMIT = 1000   # 👈 EDIT THIS VALUE AS NEEDED

# === KEYWORDS ===
KEYWORDS = ["Founder", "Co-Founder", "CEO", "CTO", "Product Head", "Marketing", "Sales"]

# === FUNCTIONS ===
def clean_url(url):
    url = url.strip()
    while url.startswith("https://www.producthunt.comhttps://www.producthunt.com"):
        url = url.replace("https://www.producthunt.com", "", 1)
        url = "https://www.producthunt.com" + url
    return url

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

def wait_for_elements(driver, by_locator, timeout=WAIT_LONG):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located(by_locator)
    )

def wait_for_clickable(driver, by_locator, timeout=WAIT_LONG):
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable(by_locator)
    )

def get_company_website(driver):
    try:
        sections = driver.find_elements(By.CSS_SELECTOR, "div[data-sentry-component='Status']")
        for sec in sections:
            header = sec.find_element(By.CSS_SELECTOR, "div.text-lg.font-semibold")
            if "Company Info" in header.text:
                links = sec.find_elements(By.TAG_NAME, "a")
                for a in links:
                    href = a.get_attribute("href")
                    text = a.text.strip()
                    if href and "producthunt.com" not in href and not href.startswith("/") and text:
                        return href
    except Exception:
        return None
    return None

# === MAKERS SCRAPER (UNCHANGED) ===
def scrape_makers(driver):
    makers_data = []
    fallback_candidates = []

    try:
        maker_cards = wait_for_elements(
            driver,
            (By.CSS_SELECTOR, "section[data-test^='maker-card-']"),
            timeout=WAIT_LONG
        )

        for card in maker_cards:
            if len(makers_data) >= 7:
                break

            try:
                name_el = card.find_element(
                    By.CSS_SELECTOR,
                    "a.text-16.font-semibold.text-gray-900"
                )
                name = name_el.text.strip()
                profile_url = name_el.get_attribute("href")

                if profile_url.startswith("/"):
                    profile_url = "https://www.producthunt.com" + profile_url

                role = ""
                try:
                    role_el = card.find_element(
                        By.CSS_SELECTOR,
                        "a.text-14.text-gray-700"
                    )
                    role = role_el.text.strip()
                except:
                    pass

                maker = {"name": name, "link": profile_url}

                if any(k.lower() in role.lower() for k in KEYWORDS):
                    makers_data.append(maker)
                else:
                    fallback_candidates.append(maker)

            except Exception:
                continue

        if len(makers_data) < 5:
            needed = 5 - len(makers_data)
            makers_data.extend(fallback_candidates[:needed])

        makers_data = makers_data[:7]

    except TimeoutException:
        pass

    return makers_data

# === MAIN ===
def main():
    df = pd.read_csv(INPUT_CSV)
    print(f"Loaded {len(df)} products from '{INPUT_CSV}'")

    df = df.head(ROW_LIMIT)
    print(f"Processing only first {len(df)} rows\n")

    df["URL"] = df["URL"].apply(clean_url)
    all_data = []

    driver = None
    try:
        driver = build_driver()
        print("Driver launched.\n")

        for idx, row in df.iterrows():
            product_url = row["URL"]
            print(f"[{idx+1}/{len(df)}] Scraping: {product_url}")

            try:
                driver.get(product_url)
                time.sleep(2)

                website = get_company_website(driver)
                print(f"  Website found: {website}" if website else "  No website found.")

                try:
                    team_tab = wait_for_clickable(
                        driver,
                        (By.CSS_SELECTOR, "a[data-test='product-navigation-item-team']")
                    )
                    driver.execute_script("arguments[0].click();", team_tab)
                    time.sleep(2)
                    print("  Team tab opened.")
                except TimeoutException:
                    print("  ⚠️ Team tab not found, skipping makers.")
                    all_data.append({
                        "Title": row["Title"],
                        "URL": product_url,
                        "Website": website
                    })
                    continue

                makers = scrape_makers(driver)
                maker_entry = {}
                for i, m in enumerate(makers, start=1):
                    maker_entry[f"Maker{i}_Name"] = m["name"]
                    maker_entry[f"Maker{i}_Link"] = m["link"]

                print(f"  Found {len(makers)} makers.")

                all_data.append({
                    "Title": row["Title"],
                    "URL": product_url,
                    "Website": website,
                    **maker_entry
                })

            except WebDriverException as e:
                print("Error scraping product page:", e)
                continue

        df_new = pd.DataFrame(all_data)
        df_merged = pd.merge(df, df_new, on=["Title", "URL"], how="left")
        df_merged.to_csv(OUTPUT_CSV, index=False)
        print(f"\n✅ Scraping complete. Saved merged data to '{OUTPUT_CSV}'")

    except Exception as exc:
        print("ERROR:", exc)
        traceback.print_exc()

    finally:
        if driver:
            print("Driver still running (close manually).")

if __name__ == "__main__":
    main()
