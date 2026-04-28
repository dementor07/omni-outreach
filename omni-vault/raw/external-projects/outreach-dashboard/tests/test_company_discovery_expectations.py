"""
TDD tests driven from user expectations, not from the current implementation.

The expectation (verbatim from the user):
  "If I give it a link like say slack.com with target titles, it should return
  profiles which match those targets."

These tests pin that expectation. They should fail if the pipeline returns
profiles that don't match the given titles, or returns nothing when the
underlying search clearly found matching profiles.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Dashboard import bootstrap ────────────────────────────────────────────────
DASHBOARD_ROOT = str(Path(__file__).parent.parent)
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

# Heavy deps mocked so importing the service doesn't hit the network / filesystem.
sys.modules.setdefault("db", MagicMock())
sys.modules.setdefault("gspread", MagicMock())
sys.modules.setdefault("dotenv", MagicMock(load_dotenv=MagicMock()))
sys.modules.setdefault("google", MagicMock())
sys.modules.setdefault("google.oauth2", MagicMock())
sys.modules.setdefault("google.oauth2.service_account", MagicMock(Credentials=MagicMock()))
sys.modules.setdefault(
    "lead_screener",
    MagicMock(screen_lead=MagicMock(return_value=("ACCEPT", "mock"))),
)
sys.modules.pop("company_discovery_service", None)

import company_discovery_service as cds  # noqa: E402


# ── Fixtures: shapes of profile payloads the search layer would plausibly return
def _slack_people_payload():
    """Realistic-enough shape of what Serper/Unipile search layer returns for Slack."""
    return [
        {
            "first_name": "Lidiane",
            "last_name": "Jones",
            "headline": "CEO at Slack",
            "location": "San Francisco Bay Area",
            "linkedin_url": "https://www.linkedin.com/in/lidianejones",
            "company_name": "slack",
            "industry": "Software Development",
            "provider_id": "",
        },
        {
            "first_name": "Kelly",
            "last_name": "Watkins",
            "headline": "Chief Marketing Officer at Slack",
            "location": "San Francisco, CA",
            "linkedin_url": "https://www.linkedin.com/in/kellywatkins",
            "company_name": "slack",
            "industry": "Software Development",
            "provider_id": "",
        },
        {
            "first_name": "Ali",
            "last_name": "Rayl",
            "headline": "VP Customer Experience at Slack",
            "location": "San Francisco, CA",
            "linkedin_url": "https://www.linkedin.com/in/alirayl",
            "company_name": "slack",
            "industry": "Software Development",
            "provider_id": "",
        },
        {
            "first_name": "Jake",
            "last_name": "Martinez",
            "headline": "Senior Software Engineer at Slack",
            "location": "Remote",
            "linkedin_url": "https://www.linkedin.com/in/jakemartinez-eng",
            "company_name": "slack",
            "industry": "Software Development",
            "provider_id": "",
        },
    ]


# ═════════════════════════════════════════════════════════════════════════════
#  Expectation 1: given a LinkedIn company URL and a title list,
#  the pipeline returns profiles — and they all match the targets.
# ═════════════════════════════════════════════════════════════════════════════

def test_returns_profiles_for_slack_when_given_company_url():
    """If I paste a Slack URL + ['CEO','CMO'], the pipeline MUST return at least one profile."""
    with patch.object(cds, "_search_decision_makers", return_value=_slack_people_payload()), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/slack",
            titles="CEO, CMO",
            campaign_id=None,
        )

    assert out["stats"]["companies"] == 1, "one company in = one company counted"
    assert out["stats"]["candidates"] >= 1, "discovery must surface at least one candidate"
    accepted = [r for r in out["rows"] if r["verdict"] == "ACCEPT"]
    assert accepted, "at least one returned profile must be ACCEPTED for CEO/CMO at Slack"


def test_accepted_profiles_match_the_target_titles():
    """Every ACCEPTED row's headline must be a plausible match for one of the target titles.

    This is the core user expectation: filter returns profiles which match those targets.
    A row accepted via the keyword path should have one of the target titles (or a close
    synonym) visible in the headline after normalization.
    """
    target_titles = ["CEO", "CMO"]
    with patch.object(cds, "_search_decision_makers", return_value=_slack_people_payload()), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/slack",
            titles=", ".join(target_titles),
            campaign_id=None,
        )

    accepted = [r for r in out["rows"] if r["verdict"] == "ACCEPT"]
    assert accepted, "preconditions: we expect ACCEPTs for this fixture"

    for row in accepted:
        headline = (row["headline"] or "").lower()
        matches_any = any(
            _title_plausibly_in_headline(title, headline) for title in target_titles
        )
        assert matches_any, (
            f"ACCEPTED row has headline {row['headline']!r} but it does not match any "
            f"target title in {target_titles}. The filter is letting non-matching profiles through."
        )


def test_engineers_are_not_accepted_when_targeting_ceo_cmo():
    """Negative expectation: if I ask for CEO/CMO, an engineer must NOT be ACCEPTed.

    Keyword path: 'Senior Software Engineer at Slack' has no title overlap with CEO/CMO,
    so the engineer row must not appear in accepted output.
    """
    with patch.object(cds, "_search_decision_makers", return_value=_slack_people_payload()), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"), \
         patch.object(cds, "_llm_title_screen", return_value=("REJECT", "not a target title")):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/slack",
            titles="CEO, CMO",
        )

    accepted_urls = {r["linkedin_url"] for r in out["rows"] if r["verdict"] == "ACCEPT"}
    assert "https://www.linkedin.com/in/jakemartinez-eng" not in accepted_urls, (
        "engineer profile was ACCEPTED even though target titles were CEO/CMO"
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Expectation 2: input accepted as-is — user gives a URL, system doesn't fail.
# ═════════════════════════════════════════════════════════════════════════════

def test_accepts_company_url_with_trailing_path():
    """Real-world paste: linkedin.com/company/<slug>/about should still work."""
    with patch.object(cds, "_search_decision_makers", return_value=_slack_people_payload()), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/slack/about",
            titles="CEO",
        )
    assert out["stats"]["companies"] == 1, "trailing /about should not break parsing"


def test_accepts_bare_slack_dot_com_style_input_gracefully():
    """User expectation: if they hand in a non-LinkedIn URL like 'slack.com',
    the system should NOT crash — it should either skip it cleanly or accept it.
    The literal user example was 'a link like say slack.com'.
    """
    with patch.object(cds, "_search_decision_makers", return_value=_slack_people_payload()), \
         patch.object(cds, "_resolve_company_from_website", return_value={"slug": "slack", "linkedin_url": "https://www.linkedin.com/company/slack"}):
        out = cds.run_discovery(
            company_urls="slack.com",
            titles="CEO",
        )
    # Must not raise, must return a well-formed stats dict.
    assert "stats" in out
    assert "rows" in out
    assert isinstance(out["rows"], list)


# ═════════════════════════════════════════════════════════════════════════════
#  Expectation 4 (core user request): input is a REGULAR WEBSITE, not LinkedIn.
#  The pipeline resolves website → LinkedIn company page → decision-maker profiles.
# ═════════════════════════════════════════════════════════════════════════════

def test_website_url_resolves_to_linkedin_company_then_finds_profiles():
    """End-to-end expectation:
    User pastes 'slack.com' (a regular website URL, not linkedin.com/company/...).
    Pipeline must:
      1. Resolve that website to a LinkedIn company page, and
      2. Find decision-maker profiles at that company, and
      3. Filter by target titles.
    """
    resolved = {"slug": "slack", "linkedin_url": "https://www.linkedin.com/company/slack"}
    with patch.object(cds, "_resolve_company_from_website", return_value=resolved) as resolver, \
         patch.object(cds, "_search_decision_makers", return_value=_slack_people_payload()) as searcher, \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://slack.com",
            titles="CEO, CMO",
        )

    # The website URL must have been fed into the resolver step.
    assert resolver.called, "pipeline must resolve website URLs to LinkedIn companies"
    resolver_input = resolver.call_args.args[0] if resolver.call_args.args else resolver.call_args.kwargs.get("raw_url", "")
    assert "slack.com" in resolver_input

    # After resolution, the decision-maker search must see the resolved slug.
    assert searcher.called, "pipeline must actually look for profiles after resolving"
    searched_company = searcher.call_args.args[0] if searcher.call_args.args else searcher.call_args.kwargs["company"]
    assert searched_company["company_name"] == "slack"

    # And profiles must be returned with verdicts.
    assert out["stats"]["companies"] == 1
    assert out["stats"]["candidates"] >= 1
    assert any(r["verdict"] == "ACCEPT" for r in out["rows"])


def test_mixed_inputs_website_and_linkedin_url_both_work():
    """User pastes a mix: one website URL and one LinkedIn company URL.
    Both must surface profiles.
    """
    def fake_resolver(raw_url: str):
        if "linkedin.com/company/" in raw_url:
            # already LinkedIn, no lookup needed
            return None
        if "slack.com" in raw_url:
            return {"slug": "slack", "linkedin_url": "https://www.linkedin.com/company/slack"}
        return None

    with patch.object(cds, "_resolve_company_from_website", side_effect=fake_resolver), \
         patch.object(cds, "_search_decision_makers", return_value=_slack_people_payload()), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://slack.com\nhttps://www.linkedin.com/company/slack",
            titles="CEO",
        )

    # Two inputs but both resolve to the same slug → should dedupe to 1 company,
    # OR count 2 if dedup is by input. Either way, at least 1 company must be processed.
    assert out["stats"]["companies"] >= 1
    assert out["stats"]["candidates"] >= 1


def test_website_that_cannot_be_resolved_is_skipped_not_crashed():
    """Random URL that can't be mapped to a LinkedIn company should be skipped cleanly."""
    with patch.object(cds, "_resolve_company_from_website", return_value=None), \
         patch.object(cds, "_search_decision_makers", return_value=[]):
        out = cds.run_discovery(
            company_urls="https://some-obscure-site-that-nobody-knows.example",
            titles="CEO",
        )
    # Must not crash. Must return well-formed output.
    assert "stats" in out
    assert "rows" in out
    # And if nothing resolved, no profiles.
    assert out["stats"]["candidates"] == 0


def test_titles_can_be_comma_or_newline_separated():
    """User shouldn't have to care about the exact delimiter."""
    with patch.object(cds, "_search_decision_makers", return_value=_slack_people_payload()), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out_comma = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/slack",
            titles="CEO, CMO",
        )
        out_newline = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/slack",
            titles="CEO\nCMO",
        )
    assert out_comma["stats"]["accepted"] == out_newline["stats"]["accepted"], (
        "delimiter shouldn't change the accepted count"
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Expectation 3: abbreviations work — CMO == Chief Marketing Officer.
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "target,headline",
    [
        ("CMO", "Chief Marketing Officer at Slack"),
        ("CEO", "Chief Executive Officer at Slack"),
        ("VP Marketing", "Vice President of Marketing at Slack"),
        ("Chief Marketing Officer", "CMO at Slack"),
    ],
)
def test_abbreviations_match_their_expansions(target, headline):
    """User types 'CMO'; a profile with 'Chief Marketing Officer' in the headline must match (and vice versa)."""
    single_profile = [{
        "first_name": "Pat",
        "last_name": "Tester",
        "headline": headline,
        "location": "",
        "linkedin_url": "https://www.linkedin.com/in/pat-tester",
        "company_name": "slack",
        "industry": "",
        "provider_id": "",
    }]
    with patch.object(cds, "_search_decision_makers", return_value=single_profile), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/slack",
            titles=target,
        )

    assert out["stats"]["accepted"] == 1, (
        f"target={target!r} vs headline={headline!r} should match — abbreviation handling is broken"
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═════════════════════════════════════════════════════════════════════════════

def test_returns_more_than_five_profiles_when_company_has_many():
    """User expectation (verbatim): 'we find all associated members so we can actually
    find the right people.' A hard cap of 5 means we miss real decision-makers.

    If the search layer can produce 30 plausible candidates, the pipeline must
    return them all (subject to a sane upper bound, but not 5).
    """
    many_profiles = [
        {
            "first_name": f"Person{i}",
            "last_name": "Test",
            "headline": f"VP Marketing at Acme #{i}",
            "location": "",
            "linkedin_url": f"https://www.linkedin.com/in/person-{i}",
            "company_name": "acme",
            "industry": "",
            "provider_id": "",
        }
        for i in range(30)
    ]

    with patch.object(cds, "_search_decision_makers", return_value=many_profiles), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/acme",
            titles="VP Marketing",
        )

    assert out["stats"]["candidates"] >= 25, (
        f"Pipeline returned only {out['stats']['candidates']} candidates "
        f"out of 30 plausible — the artificial cap is hiding real decision-makers."
    )


def test_only_returns_people_actually_at_the_target_company():
    """User expectation: 'I mean associated members cause the profiles seems unrelated'.

    A profile must NOT be returned if their headline indicates they work at a
    different company. Serper alone can't enforce this — the pipeline has to.
    """
    company_slug = "tiny-spec-inc"
    profiles_from_search = [
        # Actually at the target company:
        {"first_name": "Real", "last_name": "Employee", "headline": "CEO at Tiny Speck",
         "linkedin_url": "https://www.linkedin.com/in/real-employee", "location": "",
         "company_name": company_slug, "industry": "", "provider_id": ""},
        # Mentioned the company but works elsewhere — must be filtered out:
        {"first_name": "Aaron", "last_name": "Frost", "headline": "CEO of HeroDevs (ex-Tiny Speck)",
         "linkedin_url": "https://www.linkedin.com/in/aaronfrost", "location": "",
         "company_name": company_slug, "industry": "", "provider_id": ""},
        {"first_name": "Sally", "last_name": "Bunnell", "headline": "Founder & CEO of NaviSavi",
         "linkedin_url": "https://www.linkedin.com/in/sallybunnell", "location": "",
         "company_name": company_slug, "industry": "", "provider_id": ""},
    ]

    with patch.object(cds, "_search_decision_makers", return_value=profiles_from_search), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls=f"https://www.linkedin.com/company/{company_slug}",
            titles="CEO",
        )

    accepted_urls = {r["linkedin_url"] for r in out["rows"] if r["verdict"] == "ACCEPT"}
    assert "https://www.linkedin.com/in/aaronfrost" not in accepted_urls, (
        "Aaron Frost works at HeroDevs, not Tiny Speck — pipeline must not surface him as a Tiny Speck lead"
    )
    assert "https://www.linkedin.com/in/sallybunnell" not in accepted_urls, (
        "Sally Bunnell works at NaviSavi — pipeline must not surface her as a Tiny Speck lead"
    )


@pytest.mark.parametrize(
    "headline",
    [
        # Keyword 'CTO' appears but only as a description of past roles, not current Stripe role.
        "Payments @ Stripe | 2x founder | 3x startup CTO",
        # 'Stripe şirketinde CTO' — Turkish for 'CTO at Stripe company'; the real Stripe CTO is
        # David Singleton, not this person. The 'Stripe' here looks like a self-description hack.
        # We can't perfectly verify, but the filter should at least require the title token to be
        # near the company anchor, not just floating in the headline somewhere.
    ],
)
def test_keyword_filter_does_not_accept_when_title_is_listed_as_past_role(headline):
    """Keyword 'CTO' / 'CMO' etc must not green-light a profile when the matched
    title is clearly tied to a PAST role in a multi-role headline like
    'Payments @ Stripe | 2x founder | 3x startup CTO'.

    The user expectation: only return current decision-makers at the target company.
    """
    profile = {
        "first_name": "Ryan", "last_name": "Wilson",
        "headline": headline,
        "linkedin_url": "https://www.linkedin.com/in/ryanmwilson",
        "company_name": "stripe", "industry": "", "location": "", "provider_id": "",
    }
    with patch.object(cds, "_search_decision_makers", return_value=[profile]), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/stripe",
            titles="CEO, CMO, CTO, VP Engineering, Head of Marketing",
        )
    accepted = [r for r in out["rows"] if r["verdict"] == "ACCEPT" and r["match_method"] == "keyword"]
    assert not accepted, (
        f"keyword filter accepted {headline!r} as a current CTO at Stripe; "
        "the title is listed as a previous startup role, not a current Stripe title"
    )


def test_keyword_filter_accepts_when_title_is_clearly_the_current_role():
    """Sanity check: a clean current-role headline like 'Head of Growth Marketing at Stripe'
    must still be accepted by the keyword path.
    """
    profile = {
        "first_name": "Seth", "last_name": "Berman",
        "headline": "Head of Growth Marketing at Stripe",
        "linkedin_url": "https://www.linkedin.com/in/sethberman",
        "company_name": "stripe", "industry": "", "location": "", "provider_id": "",
    }
    with patch.object(cds, "_search_decision_makers", return_value=[profile]), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/stripe",
            titles="CEO, CMO, CTO, VP Engineering, Head of Marketing",
        )
    accepted = [r for r in out["rows"] if r["verdict"] == "ACCEPT"]
    assert accepted, "clean current-role headline should still be accepted"


def test_llm_screen_accepts_clearly_senior_roles_outside_literal_title_list():
    """User expectation (implicit from review): clearly-senior people at the target
    company should pass screening even if their exact title isn't in the input list.

    'Head of Startups at Stripe' should ACCEPT when targeting senior decision-makers
    even if 'Head of Startups' isn't literally in the input titles list.
    The LLM prompt must accept seniority-equivalent roles, not just literal matches.
    """
    profile = {
        "first_name": "Brent", "last_name": "Dance",
        "headline": "Head of Startups at Stripe",
        "linkedin_url": "https://www.linkedin.com/in/brentdance",
        "company_name": "stripe", "industry": "", "location": "", "provider_id": "",
    }
    # Force the keyword path to miss so the LLM is what decides.
    captured_prompt: dict[str, str] = {}

    def fake_screen(lead, prompt):
        captured_prompt["p"] = prompt
        return ("ACCEPT", "senior-equivalent role at the company")

    with patch.object(cds, "_search_decision_makers", return_value=[profile]), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"), \
         patch.object(cds, "_keyword_title_filter", return_value=("none", None)), \
         patch.object(cds, "_env", side_effect=lambda k, d="": "stub" if k == "ANTHROPIC_API_KEY" else d), \
         patch.object(cds, "screen_lead", side_effect=fake_screen):
        out = cds.run_discovery(
            company_urls="https://www.linkedin.com/company/stripe",
            titles="CEO, CMO, CTO, VP Engineering",
        )

    assert captured_prompt, "LLM screen must run when keyword path misses"
    prompt = captured_prompt["p"].lower()
    assert any(word in prompt for word in ["senior", "equivalent", "head of", "director"]), (
        f"LLM prompt should explicitly allow senior-equivalent roles "
        f"(Head of X / Director / VP / etc) — got prompt: {captured_prompt['p']!r}"
    )


def test_unipile_runs_one_search_per_title_for_leadership_coverage():
    """User expectation: the pipeline must actually surface leadership, not just
    whatever LinkedIn puts first. A single `"CEO OR CMO OR ..."` bundled query
    biases toward ICs because `OR` is a soft preference.

    So: run one Unipile search PER target title (each query's first page is
    leadership-biased for THAT role), then union the results.

    This test pins the contract — one Unipile POST per title.
    """
    post_calls: list[dict] = []

    class _SearchResp:
        status_code = 200
        def raise_for_status(self_inner): pass
        def json(self_inner):
            return {"items": [], "cursor": None}

    def fake_post(url, params=None, headers=None, json=None, timeout=None):
        post_calls.append({"url": url, "body": dict(json or {})})
        return _SearchResp()

    def fake_get(url, params=None, headers=None, timeout=None):
        class _R:
            status_code = 200
            def raise_for_status(self_inner): pass
            def json(self_inner): return {"id": "2135371", "name": "Stripe"}
        return _R()

    with patch.object(cds, "_env", side_effect=lambda k, d="": {"UNIPILE_API_KEY":"k","UNIPILE_BASE":"http://t"}.get(k,d)), \
         patch.object(cds.requests, "post", side_effect=fake_post), \
         patch.object(cds.requests, "get", side_effect=fake_get):
        cds._search_unipile_profiles({"company_name":"stripe"}, ["CEO","CMO","CTO"], "acct-1")

    # At least one POST per title (some titles may paginate further; we just need >= titles).
    search_bodies = [c["body"] for c in post_calls if "search" in c["url"].lower()]
    keywords_used = {b.get("keywords","") for b in search_bodies}
    # Each target title should have been used as a standalone search — not bundled with OR.
    assert "CEO" in keywords_used or "ceo" in {k.lower() for k in keywords_used}, (
        f"expected a Unipile search with keywords='CEO' as a standalone query; "
        f"saw keywords={keywords_used}"
    )
    assert "CMO" in keywords_used or "cmo" in {k.lower() for k in keywords_used}, (
        f"expected a Unipile search with keywords='CMO' as a standalone query; "
        f"saw keywords={keywords_used}"
    )
    # The bundled-OR shape is what we want to AVOID.
    assert not any(" OR " in (k or "") for k in keywords_used), (
        f"Unipile search must NOT bundle all titles with OR (that biases toward ICs); "
        f"got keywords={keywords_used}"
    )


def test_unipile_search_uses_company_id_filter_not_slug():
    """Unipile's classic API requires a numeric company ID in the 'company' field
    (an array of digit-strings), not a slug in 'current_company'. The wrong shape
    silently returns unrelated profiles, which is why discovery counts were so low.

    The pipeline must:
      1. Resolve the slug to a numeric LinkedIn company ID.
      2. Pass that ID via 'company': ['<id>'] in the search body.
    """
    captured = {}

    class _Resp:
        status_code = 200
        def raise_for_status(self_inner): pass
        def json(self_inner):
            return {"items": [{
                "name": "Real Employee", "public_identifier": "real-employee",
                "headline": "VP Engineering at Stripe", "id": "x",
            }]}

    def fake_post(url, params=None, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return _Resp()

    def fake_get(url, params=None, headers=None, timeout=None):
        # Company resolver: slug -> {id: '2135371'}
        class _R:
            status_code = 200
            def raise_for_status(self_inner): pass
            def json(self_inner): return {"id": "2135371", "name": "Stripe"}
        return _R()

    with patch.object(cds, "_env", side_effect=lambda k, d="": {"UNIPILE_API_KEY": "k", "UNIPILE_BASE": "http://test"}.get(k, d)), \
         patch.object(cds.requests, "post", side_effect=fake_post), \
         patch.object(cds.requests, "get", side_effect=fake_get):
        results = cds._search_unipile_profiles(
            {"company_name": "stripe"}, ["CEO"], "acct-1"
        )

    assert results, "Unipile returned items but parser dropped them"
    body = captured.get("body", {})
    # The right field is 'company', not 'current_company'.
    assert "company" in body, f"search body must include 'company' field; got {list(body.keys())}"
    assert "current_company" not in body, "stop sending 'current_company' — Unipile classic ignores it"
    # And the value must be the numeric ID, not the slug.
    assert body["company"] == ["2135371"], (
        f"company filter must be numeric ID array, got {body['company']!r}"
    )


def test_brand_from_input_domain_counts_as_employment_verification():
    """User-reported failure mode (real screenshot): paste 'slack.com', resolver picks
    'tiny-spec-inc' (Slack's parent), then employment filter drops everyone because
    no real Slack employee has 'tiny-spec' in their headline.

    Fix: when the user pasted slack.com, the BRAND 'slack' from the input must also
    be considered a valid current-employment marker — not just the resolved slug.
    """
    company_slug = "tiny-spec-inc"
    profiles = [
        # Real current Slack employee — headline says 'Slack', not 'tiny-spec-inc'.
        {"first_name": "Real", "last_name": "Employee", "headline": "VP of Engineering at Slack",
         "linkedin_url": "https://www.linkedin.com/in/real-slack", "location": "",
         "company_name": company_slug, "industry": "", "provider_id": ""},
        # Unrelated person mentioning Slack as a tool, not employer.
        {"first_name": "Some", "last_name": "Random", "headline": "Loves using Slack at work",
         "linkedin_url": "https://www.linkedin.com/in/some-random", "location": "",
         "company_name": company_slug, "industry": "", "provider_id": ""},
    ]

    # Force the resolver to map slack.com -> tiny-spec-inc, then check verification works.
    with patch.object(cds, "_resolve_company_from_website",
                      return_value={"slug": company_slug,
                                    "linkedin_url": f"https://www.linkedin.com/company/{company_slug}"}), \
         patch.object(cds, "_search_decision_makers", return_value=profiles), \
         patch.object(cds, "_get_unipile_account", return_value="acct-test"):
        out = cds.run_discovery(
            company_urls="https://slack.com",
            titles="VP Engineering",
        )

    accepted_urls = {r["linkedin_url"] for r in out["rows"] if r["verdict"] == "ACCEPT"}
    assert "https://www.linkedin.com/in/real-slack" in accepted_urls, (
        "real Slack employee was filtered out because brand 'slack' from input domain "
        "wasn't used as a verification phrase"
    )


def test_serper_result_with_role_only_in_snippet_is_not_lost():
    """User-reported failure mode (real Serper output for tiny-spec-inc):

    Serper returns:
      title:   'Aaron Frost - HeroDevs | LinkedIn'   (no role in title)
      snippet: 'Aaron Frost (aka Frosty) is the CEO of HeroDevs...'

    The pipeline must NOT throw away that profile. The headline it surfaces
    should contain something role-bearing — otherwise the title filter has
    nothing to work with and EVERYONE gets rejected, which is what the user
    saw on screen ("0 accepted / 5 rejected").
    """
    fake_serper_organic = [
        {
            "title": "Aaron Frost - HeroDevs | LinkedIn",
            "link": "https://www.linkedin.com/in/aaronfrost",
            "snippet": "Aaron Frost (aka Frosty) is the CEO of HeroDevs, a team of true open source software...",
        }
    ]

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self_inner): return {"organic": fake_serper_organic}

    with patch.object(cds.requests, "post", return_value=_Resp()):
        results = cds._search_serper_profiles("tiny-spec-inc", "CEO", "fake-key")

    assert results, "Serper returned a profile but the parser dropped it"
    headline = (results[0].get("headline") or "").lower()
    # The role 'ceo' is in the snippet — it must end up somewhere we can match against.
    assert "ceo" in headline or "chief executive" in headline, (
        f"profile parsed but headline doesn't contain the role from the snippet. "
        f"headline={results[0].get('headline')!r} — title filter will reject this."
    )


def _title_plausibly_in_headline(title: str, headline: str) -> bool:
    """Lightweight check independent of the service's internal normalizer.

    This is intentionally implemented in the test file (and NOT via the service's
    `_normalize_title`), so that if the service changes its normalization we still
    pin the externally-observable expectation: the returned profile's headline
    contains the target title or an obvious synonym.
    """
    t = title.strip().lower()
    h = headline.strip().lower()
    synonyms = {
        "ceo": ["chief executive officer"],
        "cmo": ["chief marketing officer"],
        "cgo": ["chief growth officer"],
        "cro": ["chief revenue officer"],
        "coo": ["chief operating officer"],
        "cto": ["chief technology officer"],
        "cfo": ["chief financial officer"],
        "cpo": ["chief product officer"],
        "cxo": ["chief experience officer"],
        "vp": ["vice president"],
    }
    candidates = [t] + synonyms.get(t, [])
    # Also check that the headline's abbreviation expansion matches the title verbatim.
    for abbrev, expansions in synonyms.items():
        if abbrev in h.split():
            candidates.extend(expansions)
    return any(c in h or h in c for c in candidates)
