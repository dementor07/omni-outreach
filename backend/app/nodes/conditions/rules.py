"""Human-readable multi-rule condition with all/any matching."""

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

Operator = Literal[
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "gt",
    "gte",
    "lt",
    "lte",
    "one_of",
    "not_one_of",
    "is_set",
    "is_not_set",
    "is_true",
    "is_false",
    "regex",
]


class ConditionRule(BaseModel):
    field: str = Field(min_length=1, description="Lead/contact field or custom_fields path")
    operator: Operator = "equals"
    value: Any = Field(default=None, description="Comparison value; comma-separated for one-of rules")


class RulesConditionConfig(BaseModel):
    match: Literal["all", "any"] = Field(
        "all",
        description="Require every rule to match, or at least one rule",
    )
    rules: list[ConditionRule] = Field(
        default_factory=list,
        description="Ordered, human-readable branching rules",
    )


MANIFEST = NodeManifest(
    type="condition.rules",
    category=NodeCategory.CONDITION,
    summary="Branch when all or any of several precise rules match",
    config_schema=RulesConditionConfig,
    output_handles=(
        NodeHandle("matched", "The configured rules matched"),
        NodeHandle("unmatched", "The configured rules did not match"),
    ),
    side_effect=SideEffect.READ,
    icon="list-checks",
    display_name="Rules",
    primary_fields=("match", "rules"),
)


def _resolve(lead: dict[str, Any], path: str) -> Any:
    parts = [part for part in path.strip().split(".") if part]
    if parts and parts[0] in {"lead", "contact"}:
        parts = parts[1:]
    cur: Any = lead
    for part in parts:
        if not isinstance(cur, dict):
            return None
        if part in cur:
            cur = cur[part]
            continue
        custom_fields = cur.get("custom_fields")
        if isinstance(custom_fields, dict) and part in custom_fields:
            cur = custom_fields[part]
            continue
        return None
    return cur


def _items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _text_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().casefold() == expected.strip().casefold()
    return actual == expected


def evaluate_rule(actual: Any, operator: Operator, expected: Any) -> bool:
    if operator == "is_set":
        return actual not in (None, "", [], {})
    if operator == "is_not_set":
        return actual in (None, "", [], {})
    if operator == "is_true":
        return actual is True
    if operator == "is_false":
        return actual is False
    if actual is None:
        return False
    if operator == "equals":
        return _text_equal(actual, expected)
    if operator == "not_equals":
        return not _text_equal(actual, expected)

    actual_text = str(actual)
    expected_text = str(expected or "")
    if operator == "contains":
        if isinstance(actual, list):
            return any(_text_equal(item, expected) for item in actual)
        return expected_text.casefold() in actual_text.casefold()
    if operator == "not_contains":
        return not evaluate_rule(actual, "contains", expected)
    if operator == "starts_with":
        return actual_text.casefold().startswith(expected_text.casefold())
    if operator == "ends_with":
        return actual_text.casefold().endswith(expected_text.casefold())
    if operator == "regex":
        try:
            return re.search(expected_text, actual_text) is not None
        except re.error:
            return False
    if operator in {"one_of", "not_one_of"}:
        matched = any(_text_equal(actual, item) for item in _items(expected))
        return matched if operator == "one_of" else not matched
    if operator in {"gt", "gte", "lt", "lte"}:
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[operator]
    return False


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = RulesConditionConfig(**ctx.config)
    if not cfg.rules:
        return NodeResult(error="CONDITION_RULES_REQUIRED")
    outcomes = [
        evaluate_rule(_resolve(ctx.lead, rule.field), rule.operator, rule.value)
        for rule in cfg.rules
    ]
    matched = all(outcomes) if cfg.match == "all" else any(outcomes)
    return NodeResult(
        handle="matched" if matched else "unmatched",
        telemetry={
            "match": cfg.match,
            "rule_count": len(cfg.rules),
            "matched_count": sum(outcomes),
            "matched": matched,
        },
    )


register(MANIFEST, execute)
