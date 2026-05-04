"""Shared helpers for lead-source providers."""
from __future__ import annotations

import re


def is_linkedin_profile(url: str) -> bool:
    return bool(re.search(r"linkedin\.com/in/", url))


def clean_role(title: str, company_name: str) -> str:
    if not title:
        return ""
    title = re.sub(re.escape(company_name), "", title, flags=re.IGNORECASE)
    for sep in ["|", "-", ",", "•", "–"]:
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            if parts:
                title = parts[0]
                break
    keywords = ["CEO", "Founder", "CTO", "CMO", "Marketing", "Director", "Manager", "VP", "Chief", "Head"]
    if any(k.lower() in title.lower() for k in keywords):
        return title.strip()
    return ""
