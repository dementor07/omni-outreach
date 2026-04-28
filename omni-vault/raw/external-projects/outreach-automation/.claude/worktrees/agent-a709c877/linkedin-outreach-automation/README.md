# 🚀 LinkedIn Outreach Automation System

> **A production-grade, state-driven LinkedIn outreach automation system**  
> built with PostgreSQL, Google Sheets, Google Drive, and the Unipile API.

This project represents **real internship-grade production work**, not a demo script.  
It automates the complete LinkedIn outreach lifecycle with a **database-first, failure-tolerant architecture** and is designed to run continuously on a Linux server.

---

## 📌 What This Automation Does

This system automates **end-to-end LinkedIn outreach**, including:

1. Lead ingestion from Google Sheets  
2. Multi-account LinkedIn connection invitations  
3. Acceptance tracking using LinkedIn network state  
4. First message automation (only after acceptance)  
5. Time-based follow-up sequencing  
6. Inbound reply detection and auto-stop  
7. Google Sheets mirroring for visibility  
8. PostgreSQL as the **single source of truth**  

---

## 🧠 Core Design Philosophy

This is **not a simple script**.  
It is a **state-machine–driven automation engine**.

| Layer | Responsibility |
|------|---------------|
| **PostgreSQL** | Source of truth (authoritative state) |
| **Automation Logic** | State transitions & business rules |
| **Google Sheets** | Human-readable mirror (best-effort) |
| **Google Drive** | Runtime config & message templates |
| **Unipile API** | LinkedIn communication provider |

> ⚠️ Google Sheets failures never stop automation  
> ✅ Database integrity is always preserved  

---

## ✨ Key Features (Detailed)

### 🔹 Lead Ingestion
- Reads leads from a Google Sheet
- Normalizes LinkedIn URLs
- Global deduplication via database
- UUID-based lead identity

### 🔹 Invitation Engine
- Supports multiple LinkedIn accounts
- Per-account daily invite limits
- Human-like randomized delays
- Detects already-connected profiles
- Safe retry & skip behavior

### 🔹 Acceptance Detection
- Polls LinkedIn connection status
- Updates DB as source of truth
- Reconciles accepted leads into Sheets

### 🔹 First Message Automation
- Sends first message **only after acceptance**
- Prevents LinkedIn policy violations
- Message templates loaded from Google Drive
- Profile-based personalization

### 🔹 Follow-Up Sequencing
- Time-based follow-ups (e.g. Day 3 / 6 / 9)
- Stops automatically after final follow-up
- Skips leads with inbound replies

### 🔹 Inbound Reply Guard
- Detects replies in LinkedIn chats
- Immediately halts automation per lead
- Prevents spam and duplicate messaging

### 🔹 Recovery & Backfill
- Database → Google Sheets reconciliation
- One-time backfill supported
- Fully idempotent (safe to re-run)

---

## 🗂️ Project Structure

> ⚠️ All files live in **one single folder**  
> (`linkedin-outreach-automation/`)

```
linkedin-outreach-automation/
├── acceptance_checker.py
├── backfill_sheet.py
├── config.py
├── config_override.json.example
├── conversation_guard.py
├── db.py
├── drive_config_loader.py
├── drive_message_loader.py
├── first_message_service.py
├── followup_service.py
├── google_sheets_service.py
├── invitation_service.py
├── lead_ingestion.py
├── logger.py
├── runner.py
├── schema.py
├── unipile_client.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## ⚙️ Installation & Setup (Linux / Server)

### 1️⃣ Clone Repository
```bash
git clone https://github.com/<your-username>/linkedin-outreach-automation.git
cd linkedin-outreach-automation
```

### 2️⃣ Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3️⃣ Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 🗄️ Database Setup

Create PostgreSQL database:

```sql
CREATE DATABASE linkedin_automation;
```

The system automatically:
- Creates required tables
- Adds missing columns safely
- Is restart-safe and idempotent

---

## 🔐 Environment Configuration

Create `.env` from template:

```bash
cp .env.example .env
```

Configure:
- PostgreSQL credentials
- Unipile API key
- LinkedIn account IDs

> ⚠️ Never commit `.env` or service account files

---

## ☁️ Google Integration

### Google Service Account
Add `google_service_account.json` locally (not committed).

Used for:
- Google Sheets read/write
- Google Drive access

### Google Drive
Used for:
- Runtime config (`config_override.json`)
- Message templates (`message_1.txt`, `followup_*.txt`)

This allows live changes **without redeploying code**.

---

## ▶️ Running the Automation

Start the automation loop:

```bash
python runner.py
```

The system:
- Runs continuously
- Sleeps between cycles
- Resumes safely after restart

---

## 🔁 Automation Flow

```
Ingest Leads
   ↓
Send Invites
   ↓
Check Acceptance
   ↓
Send First Message
   ↓
Send Follow-ups
   ↓
Detect Inbound Replies
```

Each step is:
- Restart-safe
- Idempotent
- Database-driven

---

## 🗃️ Database as Source of Truth

All automation state is stored in PostgreSQL:
- Invite timestamps
- Acceptance state
- Message & follow-up state
- Stop conditions

Google Sheets is **only a mirror**, never a dependency.

---

## 🛡️ Failure Handling & Safety

- Google Sheets quota issues → automation continues
- Server restarts → state resumes
- Partial failures → no data corruption
- Backfill script recovers missed sheet updates

---

## 👨‍💻 Author

**Niraj Vijaysinh Nale**  
B.Tech Robotics & Automation  
Backend Systems • Automation • Applied AI  

This project is part of **niraj-deliverables** and reflects **real production automation work**.

---

## 🏁 Final Notes

This system is built to:
- Run 24/7 on a server
- Respect LinkedIn platform constraints
- Remain auditable and recoverable
- Scale across multiple accounts

**Designed for real-world constraints, not demos.**
