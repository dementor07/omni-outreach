"""Audit test registry — the binding between a finding and the test(s) that prove it.

The control server (``audit/server.py``) reads this registry to know, for a given
test name, how to run it and which finding ids its result should be written back
onto. A finding goes green (FIXED) only when its bound test actually passes — the
dashboard is a proof ledger, not a checklist.

A test ``kind`` decides how the server executes it:

  - ``unit``  : a pytest node id under ``audit/tests/`` — runs in-process, no stack.
  - ``trace`` : a pytest node id that drives a real run and inspects the trace
                tool / DB — needs the local ephemeral stack up.
  - ``e2e``   : a Playwright spec (frontend -> API -> bus -> DB) — needs the stack
                up AND the frontend served. Heaviest.

Keep this file declarative. The actual assertions live in the test modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuditTest:
    name: str
    kind: str  # "unit" | "trace" | "e2e"
    target: str  # pytest node id, or playwright spec path
    finding_ids: tuple[str, ...]  # which findings this test proves
    summary: str
    needs_stack: bool = False
    needs_frontend: bool = False
    artifacts: tuple[str, ...] = field(default_factory=tuple)


# ── The registry ──────────────────────────────────────────────────────────────
# Start small (vertical slice). Each entry, once green, lets the matching finding
# flip to FIXED with real evidence behind it.

REGISTRY: dict[str, AuditTest] = {
    "contract_node_routing": AuditTest(
        name="contract_node_routing",
        kind="unit",
        target="audit/tests/test_contract_routing.py::test_every_palette_node_is_reachable",
        finding_ids=("CONTRACT-001", "NODE-001", "CONTRACT-004", "SCHEMA-DEADWRITE-001"),
        summary=(
            "Every side-effecting node in the registry must be routable: its "
            "MANIFEST.type is in NODE_CHANNEL (-> a muscle channel) OR it is a "
            "non-event-emitting flow/condition node advanced locally. A node that "
            "emits an intent but has no channel stalls the lead silently."
        ),
        needs_stack=False,
    ),
}


def get(name: str) -> AuditTest | None:
    return REGISTRY.get(name)


def for_finding(finding_id: str) -> list[AuditTest]:
    return [t for t in REGISTRY.values() if finding_id in t.finding_ids]


def all_tests() -> list[AuditTest]:
    return list(REGISTRY.values())
