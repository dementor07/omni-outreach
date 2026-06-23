"""lead_identity / lead_stage — the human label + pipeline stage shown on the
Leads view. Pure functions; no DB.

REGRESSION LEAD-IDENTITY-001: a source-batch lead (the run-lead a source wrote its
discovered companies into) used to fall through every branch to "Unresolved lead",
so 1,362 completed company-stage roots rendered as garbage on the Leads page even
though their companies fanned out fine. It must read as the meaningful entity it is.
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.execution.lead_columns import lead_identity, lead_stage  # noqa: E402


def test_source_batch_lead_reads_as_companies_not_unresolved():
    cf = {"companies": [{"company_name": "A"}, {"company_name": "B"}, {"company_name": "C"}]}
    assert lead_identity(cf, None, "x") == "Source batch · 3 companies"
    assert lead_stage(cf, False) == "source"  # identity matches the stage


def test_source_batch_singular_grammar():
    assert lead_identity({"companies": [{"x": 1}]}, None, "x") == "Source batch · 1 company"


def test_empty_companies_list_is_not_a_batch():
    # an empty list is not a meaningful batch — keep the existing fallback chain.
    assert lead_identity({"companies": []}, None, "x") == "Unresolved lead"


def test_existing_identity_branches_unchanged():
    # contact name wins
    assert lead_identity({}, {"first_name": "Joe", "last_name": "H"}, "x") == "Joe H"
    # person row from serper_people
    assert lead_identity({"item": {"name": "Jane Doe"}}, None, "x") == "Jane Doe"
    # single company item
    assert lead_identity({"item": {"company_name": "Acme"}}, None, "x") == "Acme"
    # root run-lead carrying source config
    assert lead_identity({"keyword": "devs"}, None, "x") == "Campaign run"
    # genuinely empty
    assert lead_identity({}, None, "x") == "Unresolved lead"


def test_company_item_beats_company_batch():
    # a lead that has BOTH an item (its own resolved company) and a stale companies
    # list should read as its item company, not the batch — item branch comes first.
    cf = {"item": {"company_name": "Acme"}, "companies": [{"x": 1}, {"y": 2}]}
    assert lead_identity(cf, None, "x") == "Acme"
