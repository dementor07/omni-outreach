"""Resume the marketing-agency run from a known Apify dataset.

The previous run's 10-minute poll cap timed out, but the Apify actor was still
producing data. This script skips Apify entirely, fetches the dataset directly
(or reads cached JSON), and runs steps 2-5 (filter, screen, search, screen) to
completion. Output: C:/Users/navij/Downloads/marketing-agencies.html
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

SCRAPER_DIR = Path(r"C:\Users\navij\Downloads\scraper\scraper")
sys.path.insert(0, str(SCRAPER_DIR))
load_dotenv(SCRAPER_DIR / ".env")

import claude_client  # noqa: E402
import filters as scraper_filters  # noqa: E402
import serper_client  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("resume")

DATASET_ID = "gnep4OAmjzsMfbsg8"  # from the timed-out run
RUN_ID = "kO5gY11FQ7eiJ4Gxx"

TARGET_COMPANIES = 10
TITLES = ["Founder", "Co-Founder", "Co Founder", "CEO", "Managing Director", "Owner"]
MAX_PEOPLE_PER_COMPANY = 3
EMP_MIN, EMP_MAX = 11, 50

COMPANY_SCREEN_PROMPT = """\
You are screening companies for a B2B outbound campaign targeting small Indian
marketing agencies.

ACCEPT only if the company is:
  - A marketing / advertising / branding / performance marketing / digital
    marketing agency, OR a creative studio that primarily provides marketing
    services to clients
  - Independent (not a subsidiary of a holding company like WPP, Publicis,
    Dentsu, Omnicom, IPG, Havas)
  - Small (clearly a single small/mid-sized firm, not a multinational)
  - Plausibly based in India

REJECT if the company is:
  - An MNC, large enterprise, conglomerate, or publicly listed
  - An in-house marketing team at a non-marketing company
  - A SaaS product company (even if marketing-related, e.g. martech vendor)
  - A staffing/recruitment firm
  - A consultancy that does marketing only as a side practice
"""

PERSON_SCREEN_PROMPT = """\
You are screening LinkedIn profiles for decision-makers at small marketing
agencies in India.

ACCEPT only if the headline clearly indicates the person is one of:
  - Founder / Co-Founder / Owner / Proprietor / Partner
  - CEO / Managing Director (MD)

The role must be at the named agency (not a previous employer). Profiles where
the title is unclear, or shows the person is an employee (manager, lead, head
of <function>, account director, etc.) MUST be rejected.
"""

CACHE_PATH = Path.home() / "Downloads" / f"apify_{RUN_ID}.json"


def fetch_dataset() -> list[dict]:
    """Pull all items from the Apify dataset. Wait if it's still running."""
    key = os.environ["APIFY_API_KEY"]
    base = "https://api.apify.com/v2"

    # Wait for the run to actually finish (status SUCCEEDED/FAILED/...).
    for i in range(180):  # up to 30 more min
        r = requests.get(
            f"{base}/acts/curious_coder~linkedin-jobs-scraper/runs/{RUN_ID}?token={key}",
            timeout=15,
        )
        status = r.json().get("data", {}).get("status", "")
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            log.info("[apify] run terminal: %s after %d checks", status, i + 1)
            break
        if i % 6 == 0:
            log.info("[apify] still %s (check %d)", status, i + 1)
        time.sleep(10)

    log.info("[apify] fetching dataset %s", DATASET_ID)
    r = requests.get(
        f"{base}/datasets/{DATASET_ID}/items?token={key}&limit=1000",
        timeout=60,
    )
    r.raise_for_status()
    items = r.json()
    log.info("[apify] %d items", len(items))
    CACHE_PATH.write_text(json.dumps(items), encoding="utf-8")
    return items


def keep_size_11_50(companies: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for c in companies:
        cnt = c.get("employee_count")
        if isinstance(cnt, int):
            if EMP_MIN <= cnt <= EMP_MAX:
                kept.append(c)
            else:
                log.info("[size] x '%s' employee_count=%s", c["company_name"], cnt)
            continue
        emp_min, emp_max = scraper_filters._parse_employee_range(str(c.get("raw_size") or ""))
        if emp_min is None:
            log.info("[size] x '%s' size unknown (strict)", c["company_name"])
            continue
        eff_max = emp_max if emp_max is not None else emp_min
        eff_min = emp_min
        if eff_max < EMP_MIN or eff_min > EMP_MAX:
            log.info("[size] x '%s' range %s-%s outside band", c["company_name"], eff_min, eff_max)
            continue
        kept.append(c)
    return kept


def main() -> int:
    api_claude = os.environ["ANTHROPIC_API_KEY"]
    api_serper = os.environ["SERPER_KEY"]
    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    if CACHE_PATH.exists():
        log.info("[apify] using cache %s", CACHE_PATH)
        listings = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    else:
        listings = fetch_dataset()

    log.info("step 2 | extract + dedup companies")
    companies = scraper_filters.extract_companies(listings)
    companies = scraper_filters.blocklist_filter(companies)
    log.info("[extract] %d unique non-blocklisted companies", len(companies))

    log.info("step 3 | strict 11-50 employees")
    companies = keep_size_11_50(companies)
    log.info("[size] %d in band", len(companies))
    if not companies:
        log.error("no companies survived size filter")
        return 1

    log.info("step 4 | Claude marketing-agency screen on %d companies", len(companies))
    accepted: list[dict] = []
    for c in companies:
        if len(accepted) >= 30:  # cap company screens for cost
            break
        try:
            verdict, reason = claude_client.screen_company(
                company_name=c["company_name"],
                sector=c.get("sector", ""),
                screening_prompt=COMPANY_SCREEN_PROMPT,
                api_key=api_claude,
                model=model,
            )
        except claude_client.ClaudeError as e:
            log.warning("[claude_company] %s: %s", c["company_name"], e)
            continue
        if verdict == "ACCEPT":
            c["claude_company_reason"] = reason
            accepted.append(c)
    log.info("[claude] %d passed marketing-agency screen", len(accepted))

    log.info("step 5 | Serper + Claude person screen until %d companies have a decision-maker",
             TARGET_COMPANIES)
    final: list[dict] = []
    seen_urls: set[str] = set()
    for c in accepted:
        if len(final) >= TARGET_COMPANIES:
            break
        try:
            profiles = serper_client.search_profiles(
                company_name=c["company_name"],
                roles=TITLES,
                api_key=api_serper,
                max_per_company=MAX_PEOPLE_PER_COMPANY,
            )
        except Exception as e:
            log.warning("[serper] %s: %s", c["company_name"], e)
            continue

        accepted_people: list[dict] = []
        for p in profiles:
            url = p.get("linkedin_url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                verdict, reason = claude_client.screen_person(
                    profile=p,
                    company_name=c["company_name"],
                    screening_prompt=PERSON_SCREEN_PROMPT,
                    api_key=api_claude,
                    model=model,
                )
            except claude_client.ClaudeError as e:
                log.warning("[claude_person] %s: %s", url, e)
                continue
            if verdict == "ACCEPT":
                p["claude_person_reason"] = reason
                accepted_people.append(p)

        if accepted_people:
            final.append({"company": c, "people": accepted_people})
            log.info("[ok] %d/%d | %s -> %d people",
                     len(final), TARGET_COMPANIES, c["company_name"], len(accepted_people))

    out_path = Path.home() / "Downloads" / "marketing-agencies.html"
    write_html(out_path, final)
    log.info("done: %d companies, %d people -> %s",
             len(final), sum(len(x["people"]) for x in final), out_path)
    return 0


def write_html(path: Path, final: list[dict]) -> None:
    rows: list[str] = []
    for idx, item in enumerate(final, 1):
        c = item["company"]
        for p in item["people"]:
            name = f"{p.get('first_name','')} {p.get('last_name','')}".strip() or "(unknown)"
            rows.append(f"""
            <tr>
              <td class="idx">{idx}</td>
              <td><strong>{esc(c.get('company_name',''))}</strong><br>
                  <span class="meta">{esc(c.get('sector',''))} | {esc(str(c.get('employee_count') or c.get('raw_size','')))}</span><br>
                  <a class="meta" href="{esc(c.get('company_url',''))}" target="_blank">company on linkedin</a></td>
              <td>{esc(name)}</td>
              <td>{esc(p.get('headline',''))}</td>
              <td><a href="{esc(p.get('linkedin_url',''))}" target="_blank">{esc(p.get('linkedin_url',''))}</a></td>
              <td class="reason">{esc(p.get('claude_person_reason',''))}</td>
            </tr>""")
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Indian marketing agencies (11-50) + decision-makers</title>
<style>
  body {{ font: 14px/1.45 system-ui, sans-serif; background:#0f172a; color:#e2e8f0; margin:24px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; color:#5eead4; }}
  .sub {{ color:#94a3b8; font-size: 13px; margin-bottom: 18px; }}
  table {{ border-collapse: collapse; width: 100%; background:#1e293b; }}
  th, td {{ border-bottom: 1px solid #334155; padding: 10px 12px; vertical-align: top; text-align: left; }}
  th {{ background:#0f172a; color:#5eead4; font-weight: 600; position: sticky; top: 0; }}
  td.idx {{ color:#94a3b8; width: 32px; }}
  .meta {{ color:#94a3b8; font-size: 12px; }}
  .reason {{ color:#cbd5e1; font-size: 12px; max-width: 280px; }}
  a {{ color:#7dd3fc; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
<h1>Indian marketing agencies | 11-50 employees | active hiring</h1>
<div class="sub">{len(final)} companies | {sum(len(x['people']) for x in final)} decision-makers | sources: LinkedIn jobs (Apify) + Google (Serper) + screening (Claude)</div>
<table>
  <thead><tr>
    <th>#</th><th>Company</th><th>Name</th><th>Headline</th><th>LinkedIn</th><th>Why accepted</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""
    path.write_text(html, encoding="utf-8")


def esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":
    sys.exit(main())
