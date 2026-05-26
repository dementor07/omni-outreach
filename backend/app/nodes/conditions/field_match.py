"""Branch on a lead field — equals, contains, regex, gt/lt, in-list."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class FieldMatchConfig(BaseModel):
    field_path: str = Field(min_length=1, description="Dotted path on the lead context (e.g. 'contact.company', 'custom_fields.icp_score')")
    operator: Literal["equals", "not_equals", "contains", "regex", "gt", "lt", "in", "not_in", "is_null", "is_not_null"] = "equals"
    value: Any = Field(None, description="Comparison value; not used for is_null / is_not_null")


MANIFEST = NodeManifest(
    type="condition.field_match",
    category=NodeCategory.CONDITION,
    summary="Branch the workflow based on a field comparison",
    config_schema=FieldMatchConfig,
    output_handles=(
        NodeHandle("true", "Condition matched"),
        NodeHandle("false", "Condition did not match"),
    ),
    side_effect=SideEffect.READ,
    icon="git-branch",
)


def _resolve(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _matches(actual: Any, op: str, expected: Any) -> bool:
    if op == "is_null":
        return actual is None
    if op == "is_not_null":
        return actual is not None
    if actual is None:
        return False
    if op == "equals":
        return actual == expected
    if op == "not_equals":
        return actual != expected
    if op == "contains":
        return isinstance(actual, str) and isinstance(expected, str) and expected in actual
    if op == "regex":
        return isinstance(actual, str) and isinstance(expected, str) and re.search(expected, actual) is not None
    if op == "gt":
        try:
            return float(actual) > float(expected)
        except (TypeError, ValueError):
            return False
    if op == "lt":
        try:
            return float(actual) < float(expected)
        except (TypeError, ValueError):
            return False
    if op == "in":
        return isinstance(expected, list) and actual in expected
    if op == "not_in":
        return isinstance(expected, list) and actual not in expected
    return False


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = FieldMatchConfig(**ctx.config)
    actual = _resolve(ctx.lead, cfg.field_path)
    matched = _matches(actual, cfg.operator, cfg.value)
    return NodeResult(
        handle="true" if matched else "false",
        telemetry={"field_path": cfg.field_path, "operator": cfg.operator, "matched": matched},
    )


register(MANIFEST, execute)
