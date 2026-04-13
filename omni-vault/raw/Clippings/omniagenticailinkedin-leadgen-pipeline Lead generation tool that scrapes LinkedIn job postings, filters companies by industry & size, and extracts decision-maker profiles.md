---
title: "omniagenticai/linkedin-leadgen-pipeline: Lead generation tool that scrapes LinkedIn job postings, filters companies by industry & size, and extracts decision-maker profiles."
source: "https://github.com/omniagenticai/linkedin-leadgen-pipeline/blob/main/README.md"
author:
published:
created: 2026-04-13
description: "Lead generation tool that scrapes LinkedIn job postings, filters companies by industry & size, and extracts decision-maker profiles. - omniagenticai/linkedin-leadgen-pipeline"
tags:
  - "clippings"
---
## 🚀 Automated LinkedIn Contacts Extraction from Job Postings

---

## 📌 Overview

This project automates the extraction of **decision-maker contacts from LinkedIn** based on **LinkedIn job postings**.

The pipeline:\\

1. Scrapes raw job data using an **Apify Actor**.\\
2. Filters companies by **industry** and **employee size**.\\
3. Scrapes **targeted contacts** only for relevant companies → saving SERPER credits.

Designed for **lead generation, sales prospecting, and recruitment intelligence**.

---

## 🎯 Business Objective

✔ Focus on **IT Services & Software Development** companies.  
✔ Restrict to **11--200 employees** (SMEs/startups).  
✔ Target **decision-makers** (CEO, Founder, Marketing Heads, Directors).  
✔ Minimize wasted SERPER API credits.  
✔ Deliver a **clean, structured dataset** of companies & contacts.

---

## 🛠️ Tech Stack

Component Tool/Library

---

**Web Scraping** Apify, Playwright **Data Handling** Pandas, JSON, CSV **Search API** SERPER API **Automation** Python scripts (modular pipeline) **Storage** JSON & CSV (Google Sheets-ready)

---

## 🔄 Workflow Pipeline

```
flowchart TD
    A[Scrape Jobs Apify Actor] --> B[Industry Filter industry_filter.py]
    B --> C[Fetch Company Size fetch_company_size.py]
    C --> D[Size Filter size_filter.py]
    D --> E[Fetch Contacts linkedin_contacts_scraper.py]
    E --> F[Final Dataset linkedin_contacts_final_contacts.csv]
```

---

## 📂 Script Documentation

---

Script Purpose Input Output

---

**`industry_filter.py`** Keep only IT `dataset_linkedin-jobs-scraper.json` `dataset_linkedin-jobs-scraper_filtered.json` Services & Software  
Dev companies

**`fetch_company_size.py`** Scrape LinkedIn Filtered JSON `linkedin_contacts_final_size.csv` company size (via  
Playwright)

**`size_filter.py`** Keep only 11--200 `linkedin_contacts_final_size.csv` `linkedin_contacts_final_size_filtered.csv` employee companies

## linkedin\_contacts\_scraper.py Fetch Size-filtered CSV linkedin\_contacts\_final\_contacts.csv decision-maker profiles via SERPER API

---

## 📊 Final Deliverables

✔ `linkedin_contacts_final_contacts.csv` → curated list of companies & contacts with:\\

- Company Name\\
- LinkedIn Company URL\\
- Job URL (from job posting)\\
- Sector\\
- Company Size\\
- Up to **4 decision-maker contacts** (Name, Role, LinkedIn URL)

---

## ⚡ Installation & Setup

1. **Clone the repo**
	```
	git clone https://github.com/your-repo/linkedin-contacts-extractor.git
	cd linkedin-contacts-extractor
	```
2. **Install dependencies**
	```
	pip install -r requirements.txt
	```
3. **Set environment variables** in `.env`:
	```
	LINKEDIN_SESSION_COOKIE=your_linkedin_li_at_cookie
	SERPER_KEY=your_serper_api_key
	```
4. **Run the pipeline**
	```
	python industry_filter.py
	python fetch_company_size.py
	python size_filter.py
	python linkedin_contacts_scraper.py
	```
5. **Check outputs** in:
	- `linkedin_contacts_final_size.csv` \\
		- `linkedin_contacts_final_size_filtered.csv` \\
		- `linkedin_contacts_final_contacts.csv`

---

## 📌 Notes

- 🌍 **API Quotas**: SERPER API credits are consumed only **after filtering**, minimizing wastage.\\
- 🔑 **LinkedIn Cookie**: Requires valid `li_at` cookie for company size scraping.\\
- 🛡️ **Traceability**: Intermediate files (`filtered.json`, `size.csv`, etc.) are saved for debugging & audits.

---

## 👤 Author

**Niraj Vijaysinh Nale**  
🔹 Python Automation | Data Extraction | Lead Generation

📧 Contact: *[nirajnale333@gmail.com](mailto:nirajnale333@gmail.com)*  
💼 LinkedIn: *[https://www.linkedin.com/in/nirajnale](https://www.linkedin.com/in/nirajnale)*