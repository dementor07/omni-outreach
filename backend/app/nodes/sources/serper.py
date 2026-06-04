"""Serper (google.serper.dev) search source — a Rust-free REST integration.

Proof that a side-effecting source node can ship as a single Python file using
the declarative ``http_node`` helper: no Rust handler, no ChannelType edit. The
generic ``http_call`` worker performs the request and maps the response.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.nodes import NodeContext
from app.nodes.http_node import HttpRequest, http_source_node


class SerperSourceConfig(BaseModel):
    connection_name: str = Field(description="Serper connection (Settings -> Integrations)")
    query: str = Field(min_length=1, description="Search query, e.g. 'VP Engineering fintech London'")
    num: int = Field(10, ge=1, le=100, description="Max results to pull per run")
    gl: str | None = Field(None, description="Country code, e.g. 'us', 'gb'")


def build_request(ctx: NodeContext) -> HttpRequest:
    cfg = SerperSourceConfig(**ctx.config)
    body: dict = {"q": cfg.query, "num": cfg.num}
    if cfg.gl:
        body["gl"] = cfg.gl
    return HttpRequest(
        method="POST",
        url="https://google.serper.dev/search",
        auth={"mode": "api_key_header", "header": "X-API-KEY"},
        body=body,
        result_path="organic",  # response.organic[] -> default, [] -> empty
    )


http_source_node(
    type="source.serper",
    summary="Search Google via Serper and pull result pages as leads",
    config_schema=SerperSourceConfig,
    build_request=build_request,
    capabilities=("connection:serper",),
    icon="search",
)                   

