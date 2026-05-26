"""Pluggable node registry.

A node is a single capability operators wire into the canvas: a lead source
(``sources/csv.py``), an AI step (``ai/compose.py``), an outbound channel
(``channels/email.py``), a condition (``conditions/replied.py``), a flow
primitive (``flow/delay.py``), or a CRM mutation (``crm/create_deal.py``).

Every node module exports two symbols at module scope:

  - ``MANIFEST`` — a ``NodeManifest`` describing the node's contract
  - ``execute(ctx) -> NodeResult`` — the implementation

Adding a new integration is one file. The registry auto-discovers every
module under ``app/nodes/<category>/`` and registers it. No router edits.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)


class NodeCategory(StrEnum):
    SOURCE = "source"
    ENRICH = "enrich"
    AI = "ai"
    CHANNEL = "channel"
    CONDITION = "condition"
    FLOW = "flow"
    CRM = "crm"
    SINK = "sink"
    TRANSFORM = "transform"


class SideEffect(StrEnum):
    READ = "read"
    NETWORK = "network"
    MUTATE = "mutate"


@dataclass(frozen=True)
class NodeHandle:
    """A named output edge a node can emit on."""

    name: str
    description: str = ""


@dataclass(frozen=True)
class NodeManifest:
    """The contract a node advertises to the canvas and the runtime."""

    type: str
    category: NodeCategory
    summary: str
    config_schema: type[BaseModel]
    output_handles: tuple[NodeHandle, ...] = (NodeHandle("default"),)
    capabilities: tuple[str, ...] = ()
    side_effect: SideEffect = SideEffect.READ
    icon: str = ""

    def to_openapi(self) -> dict[str, Any]:
        """Render as a JSON-serialisable manifest for ``GET /nodes``."""
        return {
            "type": self.type,
            "category": self.category.value,
            "summary": self.summary,
            "config_schema": self.config_schema.model_json_schema(),
            "output_handles": [{"name": h.name, "description": h.description} for h in self.output_handles],
            "capabilities": list(self.capabilities),
            "side_effect": self.side_effect.value,
            "icon": self.icon,
        }


@dataclass
class NodeContext:
    """Runtime context handed to ``execute``."""

    workspace_id: str
    workflow_id: str | None
    node_id: str | None
    config: dict[str, Any]
    lead: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass
class NodeResult:
    """What ``execute`` returns. ``handle`` selects the outgoing edge."""

    handle: str = "default"
    events: list[dict[str, Any]] = field(default_factory=list)
    telemetry: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


NodeExecuteFn = Callable[[NodeContext], Awaitable[NodeResult]]


_REGISTRY: dict[str, tuple[NodeManifest, NodeExecuteFn]] = {}


def register(manifest: NodeManifest, execute_fn: NodeExecuteFn) -> None:
    """Called by every node module at import time."""
    if manifest.type in _REGISTRY:
        raise RuntimeError(f"duplicate node type: {manifest.type}")
    _REGISTRY[manifest.type] = (manifest, execute_fn)


def get(node_type: str) -> tuple[NodeManifest, NodeExecuteFn]:
    if node_type not in _REGISTRY:
        raise KeyError(f"unknown node type: {node_type}")
    return _REGISTRY[node_type]


def manifests() -> list[NodeManifest]:
    return [m for m, _ in _REGISTRY.values()]


def discover() -> None:
    """Auto-import every module under ``app/nodes/<category>/`` so each one
    has a chance to call ``register()``. Called once at app startup."""
    import app.nodes as pkg

    for _finder, name, _ispkg in pkgutil.walk_packages(pkg.__path__, prefix="app.nodes."):
        if name == "app.nodes":
            continue
        try:
            importlib.import_module(name)
        except Exception as e:  # noqa: BLE001
            log.exception("[nodes] failed to import %s: %s", name, e)
    log.info("[nodes] registry loaded: %d nodes", len(_REGISTRY))
