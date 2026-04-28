"""
archive_scraper_uc_full.py
Stealth Product Hunt Launch Archive scraper using undetected-chromedriver + Selenium.
Extracts product details (name, URL, description, tags, votes) and saves to CSV.
"""

import os
import time
import traceback
import pandas as pd
import undetected_chromedriver as uc

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# === CONFIG ===
START_URL = "https://www.producthunt.com/"
USER_DATA_DIR = r"D:/Work/chrome_profile"
WAIT_LONG = 30
WAIT_VERY_LONG = 60
SCROLL_PAUSE = 3

OUTPUT_CSV = "output1.csv"
PRODUCT_LIMIT = 500   # 👈 EDIT THIS VALUE AS NEEDED

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

# === UTILS ===
def wait_for_element_clickable(driver, locator, timeout=WAIT_LONG):
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable(locator)
    )

def wait_for_elements_present(driver, locator, timeout=WAIT_LONG):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located(locator)
    )

def scroll_to_load_all(driver, pause_time=SCROLL_PAUSE, max_empty_scrolls=3):
    empty_scrolls = 0
    last_count = 0

    while True:
        cards = driver.find_elements(By.CSS_SELECTOR, "section[data-test^='post-item-']")
        count = len(cards)

        if count == last_count:
            empty_scrolls += 1
        else:
            empty_scrolls = 0
            last_count = count

        if empty_scrolls >= max_empty_scrolls:
            break

        if cards:
            ActionChains(driver).move_to_element(cards[-1]).perform()

        time.sleep(pause_time)

# === MAIN ===
def main():
    driver = None
    all_products = []

    try:
        driver = build_driver()
        print("Driver launched. Opening Product Hunt...")
        driver.get(START_URL)
        time.sleep(2)

        # Launches
        launches = wait_for_element_clickable(
            driver,
            (By.XPATH, "//a[contains(normalize-space(.),'Launches')]"),
            WAIT_VERY_LONG
        )
        launches.click()
        time.sleep(2)

        # Launch Archive
        try:
            archive = wait_for_element_clickable(
                driver,
                (
                    By.XPATH,
                    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'archive')]"
                ),
                10,
            )
            archive.click()
            time.sleep(3)
        except TimeoutException:
            print("Launch Archive link not found — continuing.")

        # Navigate to ALL tab
        all_url = driver.find_element(
            By.XPATH, "//a[contains(@href, '/all')]"
        ).get_attribute("href")
        driver.get(all_url)
        print(f"Navigated to ALL tab: {all_url}")
        time.sleep(3)

        print("Scrolling to load all products...")
        scroll_to_load_all(driver)
        print("All products loaded.")

        product_cards = wait_for_elements_present(
            driver,
            (By.CSS_SELECTOR, "section[data-test^='post-item-']"),
            WAIT_VERY_LONG
        )
        print(f"Found {len(product_cards)} cards.")

        for card in product_cards:
            if len(all_products) >= PRODUCT_LIMIT:
                print(f"\nReached product limit: {PRODUCT_LIMIT}")
                break

            try:
                product_links = card.find_elements(By.CSS_SELECTOR, "a[href^='/products/']")
                if not product_links:
                    continue

                name_elem = card.find_element(
                    By.CSS_SELECTOR,
                    "span[data-test^='post-name-'] a"
                )
                product_name = name_elem.text.strip()
                product_url = name_elem.get_attribute("href")

                if product_url.startswith("/"):
                    product_url = "https://www.producthunt.com" + product_url

                try:
                    description = card.find_element(
                        By.CSS_SELECTOR,
                        "span.text-16.text-secondary"
                    ).text.strip()
                except:
                    description = ""

                try:
                    tags = [
                        t.text.strip()
                        for t in card.find_elements(By.CSS_SELECTOR, "a[href^='/topics/']")
                    ]
                except:
                    tags = []

                try:
                    vote_button = card.find_element(
                        By.CSS_SELECTOR,
                        "button[data-test='vote-button']"
                    )
                    raw_text = vote_button.text.strip()
                    votes = "".join(ch for ch in raw_text if ch.isdigit()) or "0"
                except:
                    votes = "0"

                all_products.append({
                    "Title": product_name,
                    "URL": product_url,
                    "Description": description,
                    "Tags": ", ".join(tags),
                    "Votes": votes
                })

                print(f"{len(all_products)}. {product_name} | Votes: {votes}")

            except StaleElementReferenceException:
                continue
            except Exception as e:
                print("Error extracting card:", e)

        if not all_products:
            print("⚠️ No products extracted — DOM may have changed.")
            return

        pd.DataFrame(all_products).to_csv(OUTPUT_CSV, index=False)
        print(f"\nScraping complete. Saved {len(all_products)} products to '{OUTPUT_CSV}'.")

    except Exception as exc:
        print("ERROR:", exc)
        traceback.print_exc()

    finally:
        if driver:
            print("Driver still running (close manually).")

if __name__ == "__main__":
    main()
