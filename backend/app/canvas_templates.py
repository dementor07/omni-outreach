"""Starter campaign templates — the cold-start fix.

A brand-new "New campaign" used to drop the operator onto a blank canvas; the
working pipelines are 8-node graphs nobody would guess. A template is a named,
ready-to-run graph the create flow can instantiate in one call so a new user
gets a working campaign (which they then tweak) instead of an empty page.

A template is pure data: nodes carry a stable local ``key`` (so edges can
reference them before real UUIDs exist) + node_type + position + config; edges
reference source/target by ``key`` + handle. The router assigns fresh UUIDs at
instantiation and persists via the same path as the bulk graph save.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TemplateNode:
    key: str
    node_type: str
    position_x: float
    position_y: float
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateEdge:
    source: str  # source node key
    target: str  # target node key
    source_handle: str = "default"
    target_handle: str = "in"


@dataclass(frozen=True)
class CampaignTemplate:
    id: str
    name: str
    summary: str
    nodes: tuple[TemplateNode, ...]
    edges: tuple[TemplateEdge, ...]


# The decision-maker titles the agency pipeline hunts for once each agency is
# resolved. Shared by the source node and the people-discovery node.
_AGENCY_TITLES = ["Founder", "CEO", "Co-Founder", "Managing Director", "Growth Head"]


# Auto-Pilot: Agency Mining — the "Inception Loop" starter. Discovers B2B
# lead-gen agencies (keyless, via free SearXNG), resolves + dedups each, finds
# the founder, verifies, and creates a contact. It seeds the part that runs
# TODAY with zero setup — discovery → CRM. The operator then wires the outbound
# sequence (AI screen + email/LinkedIn) onto the create_contact node with their
# own Anthropic/SMTP/Unipile connections; those nodes need a per-workspace
# connection a template can't supply, so leaving them out keeps the starter
# honestly runnable instead of pre-filling placeholders that 500 on run.
_AGENCY_MINING = CampaignTemplate(
    id="agency-mining",
    name="Auto-Pilot: Agency Mining",
    summary="Discover B2B lead-gen agencies (free, keyless), find their founders, verify, and add to the CRM. Wire your outbound sequence onto the result.",
    nodes=(
        TemplateNode("src", "source.searxng", 0, 200, {
            "query": "site:clutch.co lead generation agency",
            "titles": list(_AGENCY_TITLES),
            "max_results": 25,
            "companies_key": "companies",
        }),
        TemplateNode("loop_co", "flow.for_each", 320, 200, {
            "items_key": "companies", "item_field": "item", "max_items": 25,
        }),
        TemplateNode("resolve", "crm.resolve_company", 640, 200, {"item_field": "item"}),
        TemplateNode("people", "source.searxng_people", 960, 200, {
            "company_field": "item",
            "titles": list(_AGENCY_TITLES),
            "max_per_company": 3,
            "people_key": "people",
        }),
        TemplateNode("loop_ppl", "flow.for_each", 1280, 200, {
            "items_key": "people", "item_field": "item", "max_items": 5,
        }),
        TemplateNode("verify", "condition.verify_person", 1600, 200, {"pass_threshold": 40}),
        TemplateNode("contact", "crm.create_contact", 1920, 200, {}),
    ),
    edges=(
        TemplateEdge("src", "loop_co", "default"),
        TemplateEdge("loop_co", "resolve", "each"),
        # resolve_company emits new/known/rejected (not "default"). Both new and
        # known proceed to people-discovery; rejected drops (no edge).
        TemplateEdge("resolve", "people", "new"),
        TemplateEdge("resolve", "people", "known"),
        TemplateEdge("people", "loop_ppl", "default"),
        TemplateEdge("loop_ppl", "verify", "each"),
        # verify_person emits verified/rejected; rejected drops (no edge).
        TemplateEdge("verify", "contact", "verified"),
    ),
)


# ── Omnichannel Outbound (email + LinkedIn, event-driven) ─────────────────────
#
# A faithful build of the "OMNICHANNEL OUTBOUND CAMPAIGN JOURNEY" spec: one
# prospect, multiple signals, next-best-action. Email #1 goes out day 0; the
# lead then BRANCHES on the engagement signal:
#
#   clicked   -> send the LinkedIn connect request immediately (hot signal)
#   opened    -> wait, then send the LinkedIn connect request (warm signal)
#   (no open) -> wait longer, send Email #2 (nurture)
#
# The LinkedIn invite uses await_acceptance choreography: once accepted, wait
# then send a LinkedIn DM referencing the connection. A reply on EITHER channel
# stops automation and raises a hot-lead alert (assign to sales). This is the
# observable behavior of the diagram built on nodes we have today.
#
# Honest scope note: the diagram also shows email BOUNCED and DELIVERED events
# and an ML "next best action engine". We emit open/click events (real) and
# branch deterministically on them; bounced/delivered event nodes and a learned
# decision engine are NOT wired here (we don't have those event producers yet) —
# so this template covers the open/click/accept/reply signals, not bounce.
#
# Channel nodes need per-workspace connections (SMTP/Unipile) the template can't
# supply, so connection_name is left blank: the operator fills theirs on the
# canvas before running. The graph is complete and editable; it just needs the
# operator's own sending accounts wired in, exactly like the agency starter.
_EMAIL_SUBJECT = "Quick question, {{contact.first_name}}"
_EMAIL_BODY_1 = "<p>Hi {{contact.first_name}},</p><p>Saw {{contact.company}} and wanted to reach out — worth a quick chat?</p>"
_EMAIL_BODY_2 = "<p>Hi {{contact.first_name}},</p><p>Following up in case my first note got buried. Open to a 15-min call?</p>"
_LI_INVITE = "Hi {{contact.first_name}} — came across {{contact.company}} and would love to connect."
_LI_DM = "Thanks for connecting, {{contact.first_name}}! I reached out over email too — happy to share how we help teams like {{contact.company}}."

_OMNICHANNEL = CampaignTemplate(
    id="omnichannel-outbound",
    name="Omnichannel Outbound (Email + LinkedIn)",
    summary=(
        "Event-driven email + LinkedIn journey: Email #1 -> branch on click/open "
        "-> LinkedIn connect -> (on accept) LinkedIn DM, with a reply on either "
        "channel stopping automation and alerting sales. Fill in your SMTP + "
        "Unipile connections on the canvas, then run."
    ),
    nodes=(
        # Day 0: first email.
        TemplateNode("email1", "channel.email", 0, 300, {
            "connection_name": "",
            "subject_template": _EMAIL_SUBJECT,
            "body_template": _EMAIL_BODY_1,
        }),
        # Engagement decision CHAIN after the send. The runtime advances a lead
        # down ONE edge per handle, so we chain the listeners rather than fan the
        # 'sent' handle out three ways (which is an ambiguous route): first check
        # for a click (hottest), then on its timeout check for an open, then on
        # that timeout check whether they replied — each a single-edge hop.
        TemplateNode("ev_click", "event.link_clicked", 340, 120, {"timeout_hours": 72}),
        TemplateNode("ev_open", "event.email_opened", 340, 320, {"timeout_hours": 48}),
        TemplateNode("ev_reply1", "condition.replied", 340, 520, {"window_days": 14}),
        # Clicked = hottest -> LinkedIn connect immediately.
        TemplateNode("li_connect_hot", "channel.linkedin", 680, 120, {
            "connection_name": "", "mode": "invite",
            "message_template": _LI_INVITE, "await_acceptance": True,
            "accept_timeout_hours": 168,
        }),
        # Opened = warm -> short wait then LinkedIn connect.
        TemplateNode("wait_open", "flow.delay", 680, 320, {"amount": 1, "unit": "days"}),
        TemplateNode("li_connect_warm", "channel.linkedin", 1020, 320, {
            "connection_name": "", "mode": "invite",
            "message_template": _LI_INVITE, "await_acceptance": True,
            "accept_timeout_hours": 168,
        }),
        # No engagement -> wait then Email #2 (nurture).
        TemplateNode("wait_nurture", "flow.delay", 680, 520, {"amount": 2, "unit": "days"}),
        TemplateNode("email2", "channel.email", 1020, 520, {
            "connection_name": "",
            "subject_template": "Re: " + _EMAIL_SUBJECT,
            "body_template": _EMAIL_BODY_2,
        }),
        # After a connection is accepted (either invite path), DM referencing it.
        TemplateNode("wait_dm", "flow.delay", 1360, 200, {"amount": 12, "unit": "hours"}),
        TemplateNode("li_dm", "channel.linkedin", 1700, 200, {
            "connection_name": "", "mode": "dm", "message_template": _LI_DM,
        }),
        # Bounce branch (MAILGUN-001): a hard bounce = the email address is dead,
        # so switch channels — find the person on LinkedIn and connect there.
        # Requires a Mailgun connection (only Mailgun emits a bounce webhook); over
        # SMTP a permanent send-failure routes on the email node's on_error instead.
        TemplateNode("ev_bounce", "event.email_bounced", 340, -80, {"timeout_hours": 24}),
        # find_li needs a LinkFinder connection the template can't supply; it's
        # seeded with the conventional connection name "linkfinder" so the config
        # is valid — the operator points it at their real LinkFinder connection
        # (or renames one to "linkfinder") before running the bounce branch.
        TemplateNode("find_li", "linkfinder.name_to_linkedin", 680, -80, {"connection_name": "linkfinder"}),
        TemplateNode("li_connect_bounce", "channel.linkedin", 1020, -80, {
            "connection_name": "", "mode": "invite",
            "message_template": _LI_INVITE, "await_acceptance": True,
            "accept_timeout_hours": 168,
        }),
        # Terminal: a reply anywhere -> hot-lead alert (assign to sales) + end.
        TemplateNode("hot_alert", "crm.hot_lead_alert", 1360, 520, {
            "reason": "Replied on an outbound channel — hand to sales.",
        }),
        TemplateNode("end_sales", "flow.end", 1700, 520, {"reason": "assigned_to_sales"}),
        TemplateNode("end_nurture", "flow.end", 2040, 200, {"reason": "sequence_complete"}),
    ),
    edges=(
        # Email #1 sent -> FIRST watch for a hard bounce (the most decisive
        # signal: a dead address means switch channels). No bounce within the
        # window -> proceed to the engagement chain.
        TemplateEdge("email1", "ev_bounce", "sent"),
        # Bounced -> find them on LinkedIn -> connect there instead.
        TemplateEdge("ev_bounce", "find_li", "bounced"),
        TemplateEdge("find_li", "li_connect_bounce", "default"),
        TemplateEdge("li_connect_bounce", "wait_dm", "sent"),
        # No bounce (presumed deliverable) -> check for a click.
        TemplateEdge("ev_bounce", "ev_click", "timeout"),
        # Clicked = hottest -> LinkedIn connect immediately.
        TemplateEdge("ev_click", "li_connect_hot", "clicked"),
        # No click in the window -> check for an open.
        TemplateEdge("ev_click", "ev_open", "timeout"),
        # Opened = warm -> short wait -> LinkedIn connect.
        TemplateEdge("ev_open", "wait_open", "opened"),
        TemplateEdge("wait_open", "li_connect_warm", "default"),
        # No open either -> check whether they replied at all.
        TemplateEdge("ev_open", "ev_reply1", "timeout"),
        # Replied -> straight to sales. Otherwise -> nurture with Email #2.
        TemplateEdge("ev_reply1", "hot_alert", "true"),
        TemplateEdge("ev_reply1", "wait_nurture", "false"),
        TemplateEdge("wait_nurture", "email2", "default"),
        # Invite accepted (both paths) -> wait -> DM. await_acceptance advances the
        # lead on the invite's 'sent' handle only after the accept webhook fires.
        TemplateEdge("li_connect_hot", "wait_dm", "sent"),
        TemplateEdge("li_connect_warm", "wait_dm", "sent"),
        TemplateEdge("wait_dm", "li_dm", "default"),
        TemplateEdge("li_dm", "end_nurture", "sent"),
        # Hot-lead alert -> end (assigned to sales).
        TemplateEdge("hot_alert", "end_sales", "default"),
    ),
)


TEMPLATES: dict[str, CampaignTemplate] = {t.id: t for t in (_AGENCY_MINING, _OMNICHANNEL)}


def list_templates() -> list[dict[str, str]]:
    """Lightweight catalog for the New-campaign picker."""
    return [{"id": t.id, "name": t.name, "summary": t.summary} for t in TEMPLATES.values()]
