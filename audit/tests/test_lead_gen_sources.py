"""Lead-generation source contracts.

These tests are deliberately broad: every registered lead-gen source gets an
individual execution contract, then the runtime is checked for all-source
parallel starts, then the company-source family is wired into a stacked
company -> people -> enrichment -> contact graph.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.execution import run as workflow_runner  # noqa: E402
from app.nodes import NodeContext, discover, get, manifests  # noqa: E402
from app.nodes import NodeCategory  # noqa: E402
from app.nodes.sources import csv as csv_source  # noqa: E402
from app.nodes.sources import producthunt as producthunt_source  # noqa: E402
from app.nodes.sources import sheets as sheets_source  # noqa: E402
from app.services.graph_validation import validate_graph  # noqa: E402


ATS_PLATFORMS = [
    "greenhouse",
    "ashby",
    "smartrecruiters",
    "bamboohr",
    "workday",
    "icims",
    "lever",
    "workable",
    "recruitee",
    "personio",
    "rippling",
    "breezy",
]

DIRECT_CONTACT_SOURCES = ["source.csv", "source.sheets", "source.producthunt"]
PASSIVE_SOURCES = ["source.webhook_in"]
PEOPLE_SOURCES = [
    "source.serper_people",
    "source.searxng_people",
    "source.linkfinder_leads",
    "source.linkfinder_employees",
    "source.linkfinder_post_reactions",
    "source.linkedin_search",
    "source.apollo_people",
]
COMPANY_SOURCES = [
    "source.searxng",
    "source.serper_search",
    "source.naukri",
    "source.clutch",
    "source.apollo",
    "source.apollo_jobs",
    "source.indeed",
    "source.linkedin_jobs",
    *[f"source.{platform}" for platform in ATS_PLATFORMS],
]
EXPECTED_SOURCE_TYPES = sorted(DIRECT_CONTACT_SOURCES + PASSIVE_SOURCES + PEOPLE_SOURCES + COMPANY_SOURCES)


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "", body: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._body = body or {}

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeAsyncClient:
    csv_text = (
        "email,first_name,last_name,company,headline,phone\n"
        "pat@example.com,Pat,Lee,Acme,VP Growth,+15550101\n"
    )
    sheets_body = {
        "values": [
            ["Email", "First Name", "Last Name", "Company", "Title", "Phone"],
            ["sam@example.com", "Sam", "Rivera", "Globex", "Founder", "+15550202"],
        ]
    }
    producthunt_body = {
        "data": {
            "posts": {
                "edges": [
                    {
                        "node": {
                            "id": "post-1",
                            "name": "SignalFox",
                            "tagline": "Find buying signals",
                            "website": "https://signalfox.example",
                            "url": "https://producthunt.com/posts/signalfox",
                            "makers": [
                                {
                                    "id": "maker-1",
                                    "name": "Alex Maker",
                                    "username": "alexmaker",
                                    "twitterUsername": "alex_maker",
                                    "websiteUrl": "https://alex.example",
                                }
                            ],
                        }
                    }
                ]
            }
        }
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        if "sheets.googleapis.com" in url:
            return _FakeResponse(body=self.sheets_body)
        return _FakeResponse(text=self.csv_text)

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(body=self.producthunt_body)


def _ctx(node_type: str, config: dict[str, Any]) -> NodeContext:
    return NodeContext(
        workspace_id="workspace",
        workflow_id="workflow",
        node_id=node_type.replace(".", "-"),
        config=config,
        lead={
            "id": "lead-company",
            "custom_fields": {
                "item": {
                    "company_name": "Acme",
                    "sector": "B2B SaaS",
                    "website": "https://acme.example",
                }
            },
        },
        correlation_id="corr-leadgen-test",
    )


def _config_for(node_type: str, companies_key: str = "companies") -> dict[str, Any]:
    if node_type == "source.csv":
        return {"csv_url": "https://example.com/leads.csv"}
    if node_type == "source.sheets":
        return {"spreadsheet_id": "sheet123", "range": "Sheet1!A:Z"}
    if node_type == "source.producthunt":
        return {"max_posts": 1}
    if node_type == "source.webhook_in":
        return {
            "require_hmac": True,
            "field_map": {"email": "email", "company": "company"},
        }
    if node_type == "source.searxng":
        return {
            "query": "site:example.com agencies",
            "titles": ["Founder", "CEO"],
            "max_results": 3,
            "companies_key": companies_key,
        }
    if node_type == "source.serper_search":
        return {
            "connection_name": "serper-test",
            "query": "site:clutch.co lead generation agency",
            "titles": ["Founder", "CEO"],
            "max_results": 3,
            "companies_key": companies_key,
        }
    if node_type == "source.naukri":
        return {
            "keyword": "sales development representative",
            "location": "India",
            "max_pages": 1,
            "max_results": 3,
            "min_results": 0,
            "companies_key": companies_key,
        }
    if node_type == "source.clutch":
        return {
            "directory_url": "https://clutch.co/agencies/lead-generation",
            "titles": ["Founder", "CEO"],
            "max_results": 3,
            "companies_key": companies_key,
        }
    if node_type == "source.apollo":
        return {
            "connection_name": "apollo-test",
            "query": "B2B SaaS companies",
            "titles": ["Founder", "CEO"],
            "max_results": 3,
            "companies_key": companies_key,
        }
    if node_type == "source.indeed":
        return {
            "connection_name": "apify-test",
            "keywords": ["sales development representative"],
            "location": "New York",
            "country": "us",
            "max_results": 10,
            "min_results": 0,
            "companies_key": companies_key,
        }
    if node_type == "source.linkedin_jobs":
        return {
            "connection_name": "apify-test",
            "keywords": ["sales development representative"],
            "location": "India",
            "max_results": 3,
            "min_results": 0,
            "companies_key": companies_key,
        }
    if node_type in {f"source.{platform}" for platform in ATS_PLATFORMS}:
        return {"max_companies": 3, "companies_key": companies_key}
    if node_type == "source.serper_people":
        return {
            "connection_name": "serper-test",
            "company_field": "item",
            "titles": ["Founder", "CEO"],
            "max_per_company": 2,
            "people_key": "people",
        }
    if node_type == "source.searxng_people":
        return {
            "company_field": "item",
            "titles": ["Founder", "CEO"],
            "max_per_company": 2,
            "people_key": "people",
            "searxng_url": "http://searxng:8080",
        }
    if node_type == "source.linkfinder_leads":
        return {
            "connection_name": "linkfinder-test",
            "query": "founders in fintech",
            "fetch_count": 2,
            "people_key": "people",
        }
    if node_type == "source.linkfinder_employees":
        return {
            "connection_name": "linkfinder-test",
            "domain": "acme.example",
            "department": "sales",
            "seniority": "vp",
            "fetch_count": 2,
            "people_key": "people",
        }
    if node_type == "source.linkfinder_post_reactions":
        return {
            "connection_name": "linkfinder-test",
            "post_url": "https://www.linkedin.com/posts/acme_123",
            "people_key": "people",
        }
    if node_type == "source.linkedin_search":
        return {
            "connection_name": "unipile-test",
            "unipile_account_id": "acct-1",
            "keywords": "Head of Growth fintech",
            "fetch_count": 5,
            "people_key": "people",
        }
    if node_type == "source.apollo_people":
        return {
            "connection_name": "apollo-test",
            "person_titles": ["Head of Growth", "VP Sales"],
            "person_seniorities": ["director", "vp"],
            "organization_num_employees_ranges": ["11,50", "51,200"],
            "person_locations": ["United States"],
            "organization_locations": ["United States"],
            "q_keywords": "fintech",
            "page": 1,
            "per_page": 25,
            "people_key": "people",
        }
    if node_type == "source.apollo_jobs":
        return {
            "connection_name": "apollo-test",
            "organization_id": "org-123",
            "jobs_key": "job_postings",
        }
    raise AssertionError(f"missing test config for {node_type}")


def _event_type_for(node_type: str) -> str:
    if node_type in DIRECT_CONTACT_SOURCES:
        return "contact.created"
    if node_type in {f"source.{platform}" for platform in ATS_PLATFORMS}:
        return "source.ats.requested"
    return f"{node_type}.registered" if node_type == "source.webhook_in" else f"{node_type}.requested"


def _payload_keys_for(node_type: str) -> set[str]:
    if node_type in DIRECT_CONTACT_SOURCES:
        return {"source"}
    if node_type == "source.webhook_in":
        return {"node_id", "require_hmac", "field_map", "correlation_id"}
    if node_type in {f"source.{platform}" for platform in ATS_PLATFORMS}:
        return {"platform", "max_companies", "companies_key", "correlation_id"}
    if node_type in {"source.searxng", "source.serper_search", "source.apollo", "source.clutch"}:
        keys = {"titles", "max_results", "companies_key", "correlation_id"}
        if node_type in {"source.searxng", "source.serper_search", "source.apollo"}:
            keys.add("query")
        if node_type in {"source.serper_search", "source.apollo"}:
            keys.add("connection_name")
        if node_type == "source.clutch":
            keys.add("directory_url")
        return keys
    if node_type == "source.naukri":
        return {"keyword", "location", "max_pages", "max_results", "min_results", "companies_key", "correlation_id"}
    if node_type == "source.indeed":
        return {
            "connection_name",
            "actor_id",
            "keywords",
            "location",
            "country",
            "max_results",
            "min_results",
            "companies_key",
            "correlation_id",
        }
    if node_type == "source.linkedin_jobs":
        return {
            "connection_name",
            "actor_id",
            "keywords",
            "location",
            "date_posted",
            "max_results",
            "min_results",
            "companies_key",
            "correlation_id",
        }
    if node_type == "source.serper_people":
        return {
            "provider",
            "connection_name",
            "company_name",
            "industry",
            "titles",
            "max_per_company",
            "people_key",
            "correlation_id",
        }
    if node_type == "source.searxng_people":
        return {
            "provider",
            "searxng_url",
            "company_name",
            "industry",
            "titles",
            "max_per_company",
            "people_key",
            "correlation_id",
        }
    if node_type in {"source.linkfinder_leads", "source.linkfinder_employees", "source.linkfinder_post_reactions"}:
        return {
            "provider",
            "connection_name",
            "linkfinder_type",
            "input_data",
            "people_key",
            "correlation_id",
        } | ({"fetch_count"} if node_type != "source.linkfinder_post_reactions" else set())
    if node_type == "source.linkedin_search":
        return {
            "provider",
            "connection_name",
            "unipile_account_id",
            "keywords",
            "fetch_count",
            "people_key",
            "correlation_id",
        }
    if node_type == "source.apollo_people":
        return {
            "provider",
            "connection_name",
            "person_titles",
            "person_seniorities",
            "organization_num_employees_ranges",
            "person_locations",
            "organization_locations",
            "q_keywords",
            "page",
            "per_page",
            "people_key",
            "correlation_id",
        }
    if node_type == "source.apollo_jobs":
        return {
            "provider",
            "connection_name",
            "organization_id",
            "domain",
            "domain_field",
            "jobs_key",
            "correlation_id",
        }
    raise AssertionError(f"missing payload contract for {node_type}")


def test_every_expected_lead_gen_source_is_registered_once():
    discover()

    source_types = sorted(manifest.type for manifest in manifests() if manifest.category == NodeCategory.SOURCE)

    assert source_types == EXPECTED_SOURCE_TYPES
    assert len(source_types) == 31


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", EXPECTED_SOURCE_TYPES)
async def test_each_lead_gen_source_executes_its_safe_contract(monkeypatch: pytest.MonkeyPatch, node_type: str):
    monkeypatch.setattr(csv_source.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(sheets_source.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(producthunt_source.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(sheets_source, "_resolve_access_token", lambda workspace_id: _async_value("google-token"))
    monkeypatch.setattr(producthunt_source, "resolve_user_access_token", lambda: _async_value("ph-token"))
    discover()
    _, execute = get(node_type)

    result = await execute(_ctx(node_type, _config_for(node_type)))

    assert result.error is None
    assert result.handle == "default"
    assert result.events, node_type
    event = result.events[0]
    assert event["event_type"] == _event_type_for(node_type)
    payload = event["payload"]
    assert _payload_keys_for(node_type) <= set(payload), node_type
    if "correlation_id" in payload:
        assert payload["correlation_id"] == "corr-leadgen-test"
    if node_type in {f"source.{platform}" for platform in ATS_PLATFORMS}:
        assert payload["platform"] == node_type.removeprefix("source.")
    if node_type in DIRECT_CONTACT_SOURCES:
        assert payload["source"] == node_type.removeprefix("source.")


async def _async_value(value: str) -> str:
    return value


@pytest.mark.asyncio
async def test_all_lead_gen_sources_can_start_in_parallel_with_one_correlation(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, Any]] = []

    async def fake_seed_and_run(**kwargs: Any) -> workflow_runner.RunOutcome:
        calls.append(kwargs)
        return workflow_runner.RunOutcome(
            lead_id=f"lead-{len(calls)}",
            node_id=str(kwargs["start_node"]["id"]),
            node_type=str(kwargs["start_node"]["node_type"]),
            correlation_id=str(kwargs["correlation_id"]),
            handle="default",
            events_published=1,
        )

    monkeypatch.setattr(workflow_runner, "seed_and_run", fake_seed_and_run)
    roots = [
        {"id": f"source-{index}", "node_type": node_type, "config": _config_for(node_type)}
        for index, node_type in enumerate(EXPECTED_SOURCE_TYPES)
    ]

    outcomes = await workflow_runner.seed_and_run_many(
        workspace_id="workspace",
        workflow_id="workflow",
        start_nodes=roots,
        actor_user_id="actor",
    )

    assert len(outcomes) == len(EXPECTED_SOURCE_TYPES)
    assert len({call["correlation_id"] for call in calls}) == 1
    assert [call["run_source_count"] for call in calls] == [len(EXPECTED_SOURCE_TYPES)] * len(EXPECTED_SOURCE_TYPES)
    assert [call["run_source_index"] for call in calls] == list(range(len(EXPECTED_SOURCE_TYPES)))
    assert [call["start_node"]["node_type"] for call in calls] == EXPECTED_SOURCE_TYPES


def test_company_sources_can_stack_into_people_discovery_enrichment_and_contact_creation():
    discover()
    nodes: list[dict[str, Any]] = [
        {"id": "end-source-done", "node_type": "flow.end", "config": {"reason": "source_exhausted"}},
        {"id": "end-no-companies", "node_type": "flow.end", "config": {"reason": "no_companies"}},
        {"id": "end-no-people", "node_type": "flow.end", "config": {"reason": "no_people"}},
        {"id": "end-rejected", "node_type": "flow.end", "config": {"reason": "rejected"}},
        {"id": "end-contact-created", "node_type": "flow.end", "config": {"reason": "contact_created"}},
        {"id": "resolve-company", "node_type": "crm.resolve_company", "config": {"item_field": "item"}},
        {
            "id": "people-serper",
            "node_type": "source.serper_people",
            "config": _config_for("source.serper_people"),
        },
        {
            "id": "people-searxng",
            "node_type": "source.searxng_people",
            "config": _config_for("source.searxng_people"),
        },
        {
            "id": "people-loop",
            "node_type": "flow.for_each",
            "config": {"items_key": "people", "item_field": "item", "max_items": 5},
        },
        {
            "id": "verify-person",
            "node_type": "condition.verify_person",
            "config": {"pass_threshold": 40},
        },
        {
            "id": "enrich-proxycurl",
            "node_type": "ai.enrich",
            "config": {
                "enrich_source": "proxycurl",
                "connection_name": "proxycurl-test",
                "merge_policy": "fill_missing",
                "skip_if_complete": True,
            },
        },
        {
            "id": "enrich-hunter",
            "node_type": "ai.enrich",
            "config": {
                "enrich_source": "hunter",
                "connection_name": "hunter-test",
                "merge_policy": "fill_missing",
                "skip_if_complete": True,
            },
        },
        {"id": "create-contact", "node_type": "crm.create_contact", "config": {"source": "stacked-leadgen"}},
    ]
    edges: list[dict[str, Any]] = [
        {
            "id": "resolve-new-to-serper",
            "source_node_id": "resolve-company",
            "target_node_id": "people-serper",
            "source_handle": "new",
        },
        {
            "id": "resolve-known-to-serper",
            "source_node_id": "resolve-company",
            "target_node_id": "people-serper",
            "source_handle": "known",
        },
        {
            "id": "resolve-rejected",
            "source_node_id": "resolve-company",
            "target_node_id": "end-rejected",
            "source_handle": "rejected",
        },
        {
            "id": "serper-people-found",
            "source_node_id": "people-serper",
            "target_node_id": "people-loop",
            "source_handle": "default",
        },
        {
            "id": "serper-empty-fallback",
            "source_node_id": "people-serper",
            "target_node_id": "people-searxng",
            "source_handle": "empty",
        },
        {
            "id": "serper-error-fallback",
            "source_node_id": "people-serper",
            "target_node_id": "people-searxng",
            "source_handle": "on_error",
        },
        {
            "id": "searxng-people-found",
            "source_node_id": "people-searxng",
            "target_node_id": "people-loop",
            "source_handle": "default",
        },
        {
            "id": "searxng-empty",
            "source_node_id": "people-searxng",
            "target_node_id": "end-no-people",
            "source_handle": "empty",
        },
        {
            "id": "searxng-error",
            "source_node_id": "people-searxng",
            "target_node_id": "end-no-people",
            "source_handle": "on_error",
        },
        {
            "id": "people-each",
            "source_node_id": "people-loop",
            "target_node_id": "verify-person",
            "source_handle": "each",
        },
        {
            "id": "people-done",
            "source_node_id": "people-loop",
            "target_node_id": "end-source-done",
            "source_handle": "done",
        },
        {
            "id": "people-empty",
            "source_node_id": "people-loop",
            "target_node_id": "end-no-people",
            "source_handle": "empty",
        },
        {
            "id": "verified",
            "source_node_id": "verify-person",
            "target_node_id": "enrich-proxycurl",
            "source_handle": "verified",
        },
        {
            "id": "person-rejected",
            "source_node_id": "verify-person",
            "target_node_id": "end-rejected",
            "source_handle": "rejected",
        },
        {
            "id": "proxycurl-ok",
            "source_node_id": "enrich-proxycurl",
            "target_node_id": "enrich-hunter",
            "source_handle": "default",
        },
        {
            "id": "proxycurl-error",
            "source_node_id": "enrich-proxycurl",
            "target_node_id": "enrich-hunter",
            "source_handle": "on_error",
        },
        {
            "id": "hunter-ok",
            "source_node_id": "enrich-hunter",
            "target_node_id": "create-contact",
            "source_handle": "default",
        },
        {
            "id": "hunter-error",
            "source_node_id": "enrich-hunter",
            "target_node_id": "create-contact",
            "source_handle": "on_error",
        },
        {
            "id": "contact-created",
            "source_node_id": "create-contact",
            "target_node_id": "end-contact-created",
            "source_handle": "default",
        },
    ]

    for index, node_type in enumerate(COMPANY_SOURCES):
        source_id = f"company-source-{index}"
        loop_id = f"company-loop-{index}"
        companies_key = f"companies_{index}"
        nodes.append({"id": source_id, "node_type": node_type, "config": _config_for(node_type, companies_key)})
        nodes.append(
            {
                "id": loop_id,
                "node_type": "flow.for_each",
                "config": {"items_key": companies_key, "item_field": "item", "max_items": 3},
            }
        )
        edges.extend(
            [
                {
                    "id": f"{source_id}-default",
                    "source_node_id": source_id,
                    "target_node_id": loop_id,
                    "source_handle": "default",
                },
                {
                    "id": f"{source_id}-empty",
                    "source_node_id": source_id,
                    "target_node_id": "end-no-companies",
                    "source_handle": "empty",
                },
                {
                    "id": f"{loop_id}-each",
                    "source_node_id": loop_id,
                    "target_node_id": "resolve-company",
                    "source_handle": "each",
                },
                {
                    "id": f"{loop_id}-done",
                    "source_node_id": loop_id,
                    "target_node_id": "end-source-done",
                    "source_handle": "done",
                },
                {
                    "id": f"{loop_id}-empty",
                    "source_node_id": loop_id,
                    "target_node_id": "end-no-companies",
                    "source_handle": "empty",
                },
            ]
        )

    result = validate_graph(nodes, edges)

    assert result["valid_for_run"], result["issues"]
    assert not [issue for issue in result["issues"] if issue["severity"] == "error"]
    assert any(issue["code"] == "MULTI_SOURCE_START" for issue in result["issues"])
