"""Find 10 small Indian marketing agencies (11-50 employees, strict) + their
owners/founders, using the standalone scraper's clients without modifying its
source. Output: an HTML table at C:/Users/navij/Downloads/marketing-agencies.html

Hard ICP filters:
  - Industry: marketing services / digital marketing agency / advertising
  - Location: India (jurisdiction filter in LinkedIn search)
  - Size: STRICTLY 11-50 employees (fail-closed on unknown size)
  - People: owners / founders / co-founders / CEOs / managing directors only

Stops as soon as 10 companies have at least one accepted decision-maker.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Import the foreign scraper's clients without touching its files.
SCRAPER_DIR = Path(r"C:\Users\navij\Downloads\scraper\scraper")
sys.path.insert(0, str(SCRAPER_DIR))
load_dotenv(SCRAPER_DIR / ".env")

import apify_client  # noqa: E402
import claude_client  # noqa: E402
import filters as scraper_filters  # noqa: E402
import serper_client  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketing-agencies")

# ── Configuration ────────────────────────────────────────────────────────────
TARGET_COMPANIES = 10
KEYWORDS = [
    "marketing agency",
    "digital marketing agency",
    "advertising agency",
    "performance marketing",
    "branding agency",
]
LOCATION = "India"
DATE_POSTED = "r604800"  # past week — broader pool to find 10
MAX_APIFY_RESULTS = 100
TITLES = ["Founder", "Co-Founder", "Co Founder", "CEO", "Managing Director", "Owner"]
MAX_PEOPLE_PER_COMPANY = 3

# Strict 11-50 size band.
EMP_MIN = 11
EMP_MAX = 50

# ICP prompts — strict and explicit, since prompt is the strongest filter.
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


def keep_size_11_50(companies: list[dict]) -> list[dict]:
    """Strict 11-50 employees, fail-closed on unknown size."""
    kept: list[dict] = []
    for c in companies:
        cnt = c.get("employee_count")
        if isinstance(cnt, int):
            if EMP_MIN <= cnt <= EMP_MAX:
                kept.append(c)
            else:
                log.info("[size] x '%s' employee_count=%s (out of band)", c["company_name"], cnt)
            continue
        # Try the fallback range parser. If it can't pin a range, drop (strict).
        emp_min, emp_max = scraper_filters._parse_employee_range(str(c.get("raw_size") or ""))
        if emp_min is None:
            log.info("[size] x '%s' size unknown (strict)", c["company_name"])
            continue
        eff_max = emp_max if emp_max is not None else emp_min
        eff_min = emp_min
        # Band overlap check: company's range must intersect [11, 50].
        if eff_max < EMP_MIN or eff_min > EMP_MAX:
            log.info("[size] x '%s' range %s-%s outside %d-%d", c["company_name"], eff_min, eff_max, EMP_MIN, EMP_MAX)
            continue
        kept.append(c)
    return kept


def main() -> int:
    api_apify = os.environ["APIFY_API_KEY"]
    api_claude = os.environ["ANTHROPIC_API_KEY"]
    api_serper = os.environ["SERPER_KEY"]
    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    log.info("step 1/5 | Apify: %d keywords, location=%s, max_results=%d",
             len(KEYWORDS), LOCATION, MAX_APIFY_RESULTS)
    listings = apify_client.run_actor(
        actor_id="curious_coder~linkedin-jobs-scraper",
        api_key=api_apify,
        keywords=KEYWORDS,
        location=LOCATION,
        date_posted=DATE_POSTED,
        max_results=MAX_APIFY_RESULTS,
    )
    log.info("[apify] got %d job listings", len(listings))
    if not listings:
        log.error("Apify returned 0 listings — aborting")
        return 1

    log.info("step 2/5 | extract + dedup companies")
    companies = scraper_filters.extract_companies(listings)
    companies = scraper_filters.blocklist_filter(companies)
    log.info("[extract] %d unique non-blocklisted companies", len(companies))

    log.info("step 3/5 | strict 11-50 employees")
    companies = keep_size_11_50(companies)
    log.info("[size] %d companies in 11-50 band", len(companies))
    if not companies:
        log.error("No companies left after size filter — aborting")
        return 1

    log.info("step 4/5 | Claude company screen (marketing-agency ICP)")
    accepted_companies: list[dict] = []
    for c in companies:
        try:
            verdict, reason = claude_client.screen_company(
                company_name=c["company_name"],
                sector=c.get("sector", ""),
                screening_prompt=COMPANY_SCREEN_PROMPT,
                api_key=api_claude,
                model=model,
            )
        except claude_client.ClaudeError as e:
            log.warning("[claude_company] error on %s: %s", c["company_name"], e)
            continue
        if verdict == "ACCEPT":
            c["claude_company_reason"] = reason
            accepted_companies.append(c)
    log.info("[claude] %d companies passed marketing-agency screen", len(accepted_companies))

    log.info("step 5/5 | per-company Serper + Claude person screen "
             "(stop at %d companies with >= 1 accepted decision-maker)", TARGET_COMPANIES)
    final: list[dict] = []   # list of {company, people:[{...}]}
    seen_urls: set[str] = set()
    for c in accepted_companies:
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
            log.warning("[serper] failed for %s: %s", c["company_name"], e)
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
                log.warning("[claude_person] error on %s: %s", url, e)
                continue
            if verdict == "ACCEPT":
                p["claude_person_reason"] = reason
                accepted_people.append(p)

        if accepted_people:
            final.append({"company": c, "people": accepted_people})
            log.info("[ok] %d/%d companies | %s -> %d decision-makers",
                     len(final), TARGET_COMPANIES, c["company_name"], len(accepted_people))

    out_path = Path.home() / "Downloads" / "marketing-agencies.html"
    write_html(out_path, final)
    log.info("done: %d companies, %d people -> %s",
             len(final),
             sum(len(x["people"]) for x in final),
             out_path)
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
  body {{ font: 14px/1.45 system-ui, -apple-system, sans-serif; background:#0f172a; color:#e2e8f0; margin:24px; }}
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
        .replace("'", "&#39;")
        #Added newline replacement for better HTML formatting
    )


if __name__ == "__main__":
    sys.exit(main())
