"""Company filter — the three pure pre-LLM gates from the scraper pipeline,
collapsed into one condition node:

    1. blocklist:    drop if company name contains any blocklist substring
    2. size:         drop if employee_count > max_employees (fail-open on unknown)
    3. description:  drop if JD contains enterprise signals

Pure: no I/O, no API calls. Runs per company against the element the upstream
``flow.for_each`` (or the source node) put on the lead's custom_fields under
``company_field``.

Ported from scraper/filters.py:179-345.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


DEFAULT_BLOCKLIST: tuple[str, ...] = (
    "amazon", "google", "meta", "microsoft", "apple", "ibm", "oracle", "sap",
    "salesforce", "adobe", "cisco", "intel", "accenture", "deloitte", "mckinsey",
    "tcs", "tata consultancy", "infosys", "wipro", "hcl", "tech mahindra",
    "cognizant", "capgemini", "adani", "reliance", "hdfc", "icici",
    "axis bank", "sbi", "bajaj", "mahindra", "birla", "larsen",
    "swiggy", "zomato", "paytm", "razorpay", "byju", "byjus", "flipkart",
    "meesho", "zepto", "ola", "uber", "airbnb",
    "marriott", "hilton", "hyatt", "h&m", "zara", "uniqlo",
)


DEFAULT_JD_REJECT_KEYWORDS: tuple[str, ...] = (
    "10,000+ employees", "10000+ employees",
    "fortune 500", "fortune500",
    "multinational", "listed company", "global leader",
    "nse:", "bse:", "nyse:", "nasdaq:",
    "conglomerate", "100,000 employees", "50,000 employees",
    "publicly traded", "stock exchange",
)


class CompanyFilterConfig(BaseModel):
    company_field: str = Field(
        "item",
        description="custom_fields key holding the company dict to evaluate "
        "(default 'item' — what flow.for_each writes per child)",
    )
    max_employees: int = Field(500, ge=1, description="Reject companies above this headcount")
    blocklist: list[str] | None = Field(
        None,
        description="Override the default enterprise name blocklist (lowercase substrings)",
    )
    reject_keywords: list[str] | None = Field(
        None,
        description="Override the default JD enterprise-signal keywords",
    )


MANIFEST = NodeManifest(
    type="condition.company_filter",
    category=NodeCategory.CONDITION,
    summary="Pre-LLM company gates: blocklist + size + JD enterprise signals",
    config_schema=CompanyFilterConfig,
    output_handles=(
        NodeHandle("default", "Company survived all gates"),
        NodeHandle("rejected", "Blocked by name, size, or JD keyword"),
    ),
    side_effect=SideEffect.READ,
    icon="filter",
)


def _parse_employee_range(raw: str) -> tuple[int | None, int | None]:
    """Fallback parser for legacy actor strings like '11-50', '10K+', '5,000'."""
    if not raw or raw.strip().lower() in ("", "none", "n/a", "null"):
        return None, None
    raw = raw.replace(",", "").replace(" employees", "").strip()

    def _to_int(s: str) -> int:
        s = s.strip().upper()
        if "K" in s:
            return int(float(s.replace("K", "")) * 1_000)
        if "M" in s:
            return int(float(s.replace("M", "")) * 1_000_000)
        return int(float(s))

    if "+" in raw:
        m = re.search(r"([\d.]+[KkMm]?)", raw)
        return (_to_int(m.group(1)), None) if m else (None, None)
    if "-" in raw:
        parts = raw.split("-", 1)
        try:
            return _to_int(parts[0]), _to_int(parts[1])
        except (ValueError, IndexError):
            return None, None
    try:
        n = _to_int(raw)
        return n, n
    except (ValueError, TypeError):
        return None, None


def _blocklisted(name: str, blocklist: tuple[str, ...]) -> str | None:
    """First matching blocklist entry, or None."""
    lower = name.lower()
    return next((b for b in blocklist if b in lower), None)


def _too_big(company: dict[str, Any], max_employees: int) -> int | None:
    """Returns the effective employee count if the company exceeds the cap, else None.
    Fail-open: unknown size -> None (keep the company)."""
    count = company.get("employee_count")
    if isinstance(count, int):
        return count if count > max_employees else None
    emp_min, emp_max = _parse_employee_range(str(company.get("raw_size") or ""))
    if emp_min is None:
        return None  # unknown -> keep
    effective = emp_max if emp_max is not None else emp_min
    return effective if effective > max_employees else None


def _jd_signal(description: str, keywords: tuple[str, ...]) -> str | None:
    """First matching enterprise-signal keyword in the JD, or None."""
    lower = (description or "").lower()
    return next((k for k in keywords if k in lower), None)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = CompanyFilterConfig(**ctx.config)
    company = (ctx.lead.get("custom_fields") or {}).get(cfg.company_field) or {}
    if not isinstance(company, dict) or not company.get("company_name"):
        return NodeResult(handle="rejected", telemetry={"reason": "no_company"})

    blocklist = tuple(s.lower() for s in (cfg.blocklist or DEFAULT_BLOCKLIST))
    keywords = tuple(s.lower() for s in (cfg.reject_keywords or DEFAULT_JD_REJECT_KEYWORDS))
    name = company["company_name"]

    if hit := _blocklisted(name, blocklist):
        return NodeResult(handle="rejected", telemetry={"reason": "blocklist", "matched": hit})
    if (over := _too_big(company, cfg.max_employees)) is not None:
        return NodeResult(handle="rejected", telemetry={"reason": "too_big", "employees": over})
    if hit := _jd_signal(str(company.get("description") or ""), keywords):
        return NodeResult(handle="rejected", telemetry={"reason": "jd_signal", "matched": hit})

    return NodeResult(handle="default", telemetry={"company": name})


register(MANIFEST, execute)
