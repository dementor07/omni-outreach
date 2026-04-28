# 🧠 Product Hunt Scraper Suite (v2.0 – Stable)

A **fully automated Product Hunt data extraction pipeline** built using  
`Selenium` + `undetected-chromedriver`.

This project reliably scrapes **Product Hunt launches, products, makers, and maker social links**, and runs end-to-end via a **single command**.

> ✅ **v2.0-stable** focuses on Windows stability, Unicode-safe execution, and a reliable multi-stage pipeline.

---

## ⚠️ Important Update (Jan 2026)

This project was significantly updated to fix real-world stability issues:

- Fixed **Unicode / charmap crashes on Windows**
- Made **subprocess execution UTF-8 safe**
- Resolved **Chrome GPU / display blur issues**
- Stabilized the full end-to-end scraping pipeline

👉 Use **`producthunt_scraper.py`** to run the complete pipeline.

---

## 📁 Project Structure

```
producthunt_scraper/
├── archive_scraper.py          # Stage 1 - Scrapes Product Hunt archive (ALL tab)
├── product_scraper.py          # Stage 2 - Extracts product website & makers
├── profile_scraper.py          # Stage 3 - Extracts maker social links
├── converter_to_leads.py       # Converts final CSV & pushes leads to Google Sheets
├── producthunt_scraper.py      # Main runner (replaces old run_all.py)
├── requirements.txt            # Dependencies
└── README.md                   # Documentation
```

---

## 🚀 Pipeline Overview

### Stage 1 — `archive_scraper.py`
- Scrapes Product Hunt **Launch Archive / All** tab.
- Extracts:
  - Title  
  - Product URL  
  - Description  
  - Tags  
  - Votes  
- Output:  
  ```
  output1.csv
  ```

---

### Stage 2 — `product_scraper.py`
- Reads from `output1.csv`.
- Visits each **product page**.
- Extracts:
  - Company website
  - Top makers (Name + Profile URL, up to 7)
- **Preserves all original columns**.
- Output:
  ```
  output2.csv
  ```

---

### Stage 3 — `profile_scraper.py`
- Reads from `output2.csv`.
- Visits each **maker profile**.
- Extracts links **only from the “Links” section**:
  - Website
  - LinkedIn
  - Twitter / X
  - GitHub
  - YouTube
  - Instagram
  - Blog
  - Facebook
  - Telegram
- Inserts social columns immediately after each `MakerX_Link`.
- Output:
  ```
  output_final_<timestamp>.csv
  ```

---

### Stage 4 — `converter_to_leads.py`
- Reads the final enriched CSV.
- Filters and formats lead data.
- Pushes valid leads to **Google Sheets**.

---

## 🖥️ Usage

### ▶️ Run the full pipeline
```
python producthunt_scraper.py
```

---

## 🏷️ Versioning

- **Current stable release:** `v2.0-stable`

---

## 🤝 Author

**Niraj Nale**  
Built for **Omniagentic AI**
