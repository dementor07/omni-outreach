"""UNIPILE-FULL — new nodes register + emit correct intents; wire contract holds.

Pure/mocked (no live Unipile calls). Covers:
  * every new node registers and emits its ``.requested`` intent;
  * the Python ChannelType value == the Rust #[serde(rename)] (table test) AND
    each has an as_str arm + a dispatch arm in mod.rs — the LinkedIn-invite wire
    contract, verified end to end so the muscle never sees Unknown;
  * the per-lead ACTION channels are in the send-gate set (_OUTBOUND_SEND_CHANNELS);
  * unipile_client builds correct URLs/headers.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.core.events import ChannelType  # noqa: E402
from app.execution.commands import NODE_CHANNEL  # noqa: E402
from app.nodes import NodeContext, discover, get, manifests  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# node_type -> (ChannelType, expected .requested intent, minimal config)
_NEW_NODES = {
    "source.linkedin_search": (
        ChannelType.LINKEDIN_SEARCH,
        "source.linkedin_search.requested",
        {"connection_name": "u", "unipile_account_id": "a", "keywords": "growth"},
    ),
    "enrich.linkedin_company": (
        ChannelType.LINKEDIN_COMPANY_PROFILE,
        "enrich.linkedin_company.requested",
        {"connection_name": "u", "unipile_account_id": "a"},
    ),
    "enrich.linkedin_member": (
        ChannelType.LINKEDIN_MEMBER_PROFILE,
        "enrich.linkedin_member.requested",
        {"connection_name": "u", "unipile_account_id": "a"},
    ),
    "channel.linkedin_react_post": (
        ChannelType.LINKEDIN_REACT_POST,
        "channel.linkedin_react_post.requested",
        {"connection_name": "u", "unipile_account_id": "a"},
    ),
    "channel.linkedin_comment_post": (
        ChannelType.LINKEDIN_COMMENT_POST,
        "channel.linkedin_comment_post.requested",
        {"connection_name": "u", "unipile_account_id": "a", "comment_template": "hi {first_name}"},
    ),
    "channel.linkedin_endorse": (
        ChannelType.LINKEDIN_ENDORSE,
        "channel.linkedin_endorse.requested",
        {"connection_name": "u", "unipile_account_id": "a"},
    ),
    "channel.linkedin_follow": (
        ChannelType.LINKEDIN_FOLLOW,
        "channel.linkedin_follow.requested",
        {"connection_name": "u", "unipile_account_id": "a"},
    ),
    "channel.message_react": (
        ChannelType.MESSAGE_REACT,
        "channel.message_react.requested",
        {"connection_name": "u", "unipile_account_id": "a"},
    ),
    "channel.invite_cancel": (
        ChannelType.INVITE_CANCEL,
        "channel.invite_cancel.requested",
        {"connection_name": "u", "unipile_account_id": "a"},
    ),
}

# The 6 per-lead ACTION channels that MUST pass the send gate in a campaign.
_ACTION_CHANNELS = {
    "channel.linkedin_react_post", "channel.linkedin_comment_post",
    "channel.linkedin_endorse", "channel.linkedin_follow",
    "channel.message_react", "channel.invite_cancel",
}


def test_all_new_nodes_register():
    discover()
    registered = {m.type for m in manifests()}
    for node_type in _NEW_NODES:
        assert node_type in registered, node_type


@pytest.mark.parametrize("node_type", list(_NEW_NODES))
def test_new_node_routes_and_emits_intent(node_type):
    discover()
    channel, intent, config = _NEW_NODES[node_type]
    # NODE_CHANNEL routes it to the right muscle channel.
    assert NODE_CHANNEL.get(node_type) == channel, node_type
    _, execute = get(node_type)
    ctx = NodeContext(
        workspace_id="ws", workflow_id="wf", node_id="n1",
        config=config, lead={"id": "lead-1", "custom_fields": {}}, correlation_id="corr",
    )
    result = _run(execute(ctx))
    assert result.error is None, node_type
    assert result.events, node_type
    assert result.events[0]["event_type"] == intent, node_type


# ── Wire contract: Python value == Rust rename + as_str + dispatch arm ─────────
_WIRE = {
    ChannelType.LINKEDIN_SEARCH: ("LinkedinSearch", "linkedin_search",
                                  "linkedin_search::handle_linkedin_search"),
    ChannelType.LINKEDIN_COMPANY_PROFILE: ("LinkedinCompanyProfile", "linkedin_company_profile",
                                           "unipile::handle_linkedin_company_profile"),
    ChannelType.LINKEDIN_MEMBER_PROFILE: ("LinkedinMemberProfile", "linkedin_member_profile",
                                          "unipile::handle_linkedin_member_profile"),
    ChannelType.LINKEDIN_REACT_POST: ("LinkedinReactPost", "linkedin_react_post",
                                      "unipile::handle_linkedin_react_post"),
    ChannelType.LINKEDIN_COMMENT_POST: ("LinkedinCommentPost", "linkedin_comment_post",
                                        "unipile::handle_linkedin_comment_post"),
    ChannelType.LINKEDIN_ENDORSE: ("LinkedinEndorse", "linkedin_endorse",
                                   "unipile::handle_linkedin_endorse"),
    ChannelType.LINKEDIN_FOLLOW: ("LinkedinFollow", "linkedin_follow",
                                  "unipile::handle_linkedin_follow"),
    ChannelType.MESSAGE_REACT: ("MessageReact", "message_react",
                                "unipile::handle_message_react"),
    ChannelType.INVITE_CANCEL: ("InviteCancel", "invite_cancel",
                                "unipile::handle_invite_cancel"),
}


def test_wire_contract_python_value_matches_rust():
    models_rs = (REPO / "backend-rust/src/models.rs").read_text(encoding="utf-8")
    mod_rs = (REPO / "backend-rust/src/handlers/mod.rs").read_text(encoding="utf-8")
    for channel, (variant, rename, dispatch) in _WIRE.items():
        # Python enum value IS the on-wire string.
        assert channel.value == rename, channel
        # Rust: #[serde(rename = "...")] + the variant + the as_str arm.
        assert f'rename = "{rename}"' in models_rs, rename
        assert f"{variant}," in models_rs, variant
        assert f'ChannelType::{variant} => "{rename}"' in models_rs, variant
        # Rust: a dispatch arm routing to the handler.
        assert f"ChannelType::{variant} => {dispatch}(command).await" in mod_rs, variant


def test_action_channels_pass_send_gate():
    """The 6 per-lead ACTION channels are in _OUTBOUND_SEND_CHANNELS so a campaign
    fire routes them through _gate_send (DNC/dedupe/rate) — a real side effect must
    not bypass the send gate (security requirement)."""
    from app.execution.transition_worker import _OUTBOUND_SEND_CHANNELS

    for node_type in _ACTION_CHANNELS:
        assert node_type in _OUTBOUND_SEND_CHANNELS, node_type
    # Enrichment reads + the search source are NOT sends — they must NOT be gated.
    for non_send in ("source.linkedin_search", "enrich.linkedin_company", "enrich.linkedin_member"):
        assert non_send not in _OUTBOUND_SEND_CHANNELS, non_send


# ── unipile_client URL/header construction (mocked httpx, no live calls) ────────
def test_unipile_client_builds_urls_and_headers():
    from app.services.unipile_client import UnipileClient

    client = UnipileClient("KEY", "https://api6.unipile.com:13670/")
    assert client._base == "https://api6.unipile.com:13670"
    assert client._url("accounts") == "https://api6.unipile.com:13670/api/v1/accounts"
    assert client._url("/linkedin/search") == "https://api6.unipile.com:13670/api/v1/linkedin/search"


@pytest.mark.asyncio
async def test_unipile_client_get_sends_api_key_header(monkeypatch):
    """A GET carries X-API-KEY and hits {base}/api/v1/{path}; no live network."""
    from app.services import unipile_client as uc

    captured = {}

    class _Resp:
        status_code = 200
        content = b"{}"

        def json(self):
            return {"ok": True}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, params=None, json=None, headers=None):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(uc.httpx, "AsyncClient", _Client)
    client = uc.UnipileClient("SECRET", "https://api.unipile.com")
    result = await client.list_accounts()
    assert result == {"ok": True}
    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.unipile.com/api/v1/accounts"
    assert captured["headers"]["X-API-KEY"] == "SECRET"
