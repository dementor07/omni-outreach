"""Declarative HTTP node helper.

Lets a Python-only author add a REST integration without writing Rust. You
provide a manifest and a ``build_request(ctx) -> HttpRequest`` function; this
helper wires the ``execute`` that hands the request to the generic ``http_call``
worker handler (see ``backend-rust/src/handlers/http_call.rs``) and registers
the node.

The secret (API key) is **never** put in the node config or the request. The
node declares ``auth={"mode": "bearer"}`` (or ``api_key_header``); the worker
redeems the key from the connection's credential bundle at call time.

Example (a Serper-style search source)::

    from app.nodes.http_node import HttpRequest, http_source_node

    class SerperConfig(BaseModel):
        connection_name: str = Field(description="Serper connection")
        query: str = Field(min_length=1)
        num: int = Field(10, ge=1, le=100)

    def build_request(ctx):
        cfg = SerperConfig(**ctx.config)
        return HttpRequest(
            method="POST",
            url="https://google.serper.dev/search",
            auth={"mode": "api_key_header", "header": "X-API-KEY"},
            body={"q": cfg.query, "num": cfg.num},
            result_path="organic",  # response.organic[] -> default, [] -> empty
        )

    http_source_node(
        type="source.serper",
        summary="Search Google via Serper and pull result pages as leads",
        config_schema=SerperConfig,
        build_request=build_request,
        icon="search",
    )
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


@dataclass
class HttpRequest:
    """A declarative HTTP request the generic worker handler will execute."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    body: Any = None
    # auth: {} | {"mode":"none"} | {"mode":"bearer"} |
    #       {"mode":"api_key_header","header":"X-API-KEY","prefix":""}
    auth: dict[str, Any] = field(default_factory=lambda: {"mode": "none"})
    # Dotted path into the JSON response that holds the result set. When it
    # resolves to a non-empty array/object the node takes "default"; empty
    # or missing takes "empty". Omit to always take "default" on 2xx.
    result_path: str | None = None

    def to_payload(self) -> dict[str, Any]:
        req: dict[str, Any] = {
            "method": self.method,
            "url": self.url,
            "auth": self.auth,
        }
        if self.headers:
            req["headers"] = self.headers
        if self.query:
            req["query"] = self.query
        if self.body is not None:
            req["body"] = self.body
        if self.result_path:
            req["response"] = {"result_path": self.result_path}
        return {"request": req}


BuildRequestFn = Callable[[NodeContext], HttpRequest]


def _make_execute(build_request: BuildRequestFn, config_schema: type[BaseModel]):
    async def execute(ctx: NodeContext) -> NodeResult:
        # Validate config up front so a misconfigured node fails clearly in the
        # control plane rather than as an opaque worker error.
        config_schema(**ctx.config)
        req = build_request(ctx)
        correlation_id = ctx.correlation_id or str(uuid.uuid4())
        # The node emits a command for the generic http_call handler. The
        # orchestrator turns this into an ActionCommand with channel="http_call"
        # and the worker performs the request; the chosen handle comes back via
        # metadata.next_handle.
        events = [
            {
                "event_type": "http_call.requested",
                "entity_type": "workflow",
                "entity_id": ctx.workflow_id,
                "payload": {
                    "channel": "http_call",
                    "correlation_id": correlation_id,
                    **req.to_payload(),
                },
            }
        ]
        return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})

    return execute


def http_node(
    *,
    type: str,
    category: NodeCategory,
    summary: str,
    config_schema: type[BaseModel],
    build_request: BuildRequestFn,
    output_handles: tuple[NodeHandle, ...] = (
        NodeHandle("default", "Request succeeded"),
        NodeHandle("empty", "Request returned no results"),
        NodeHandle("on_error", "Request failed"),
    ),
    capabilities: tuple[str, ...] = (),
    icon: str = "globe",
) -> None:
    """Register a declarative HTTP node. Side effect is always NETWORK."""
    manifest = NodeManifest(
        type=type,
        category=category,
        summary=summary,
        config_schema=config_schema,
        output_handles=output_handles,
        capabilities=capabilities,
        side_effect=SideEffect.NETWORK,
        icon=icon,
    )
    register(manifest, _make_execute(build_request, config_schema))


def http_source_node(
    *,
    type: str,
    summary: str,
    config_schema: type[BaseModel],
    build_request: BuildRequestFn,
    capabilities: tuple[str, ...] = (),
    icon: str = "globe",
) -> None:
    """Convenience for SOURCE-category declarative HTTP nodes."""
    http_node(
        type=type,
        category=NodeCategory.SOURCE,
        summary=summary,
        config_schema=config_schema,
        build_request=build_request,
        output_handles=(
            NodeHandle("default", "1+ results matched"),
            NodeHandle("empty", "search returned nothing"),
            NodeHandle("on_error", "provider call failed"),
        ),
        capabilities=capabilities,
        icon=icon,
    )
