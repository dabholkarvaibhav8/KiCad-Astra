"""Strict model schema; routing endpoints are real pad UUIDs, never invented coordinates."""

from __future__ import annotations

import json
import math

from jsonschema import Draft202012Validator


class PlanFormatError(ValueError):
    pass


def obj(properties):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


TEXT = {"type": "string"}
PLACEMENT_SCHEMA = obj(
    {
        "reference": TEXT,
        "x_mm": {"type": "number"},
        "y_mm": {"type": "number"},
        "rotation_deg": {"type": "number"},
        "side": {"type": "string", "enum": ["front", "back"]},
        "reason": TEXT,
    }
)
CONNECTION_SCHEMA = obj(
    {
        "net": TEXT,
        "from_pad_id": TEXT,
        "to_pad_id": TEXT,
        "layers": {"type": "array", "items": TEXT, "minItems": 1, "maxItems": 8},
        "reason": TEXT,
    }
)
PLAN_JSON_SCHEMA = obj(
    {
        "schema_version": {"type": "integer", "enum": [2]},
        "summary": TEXT,
        "findings": {
            "type": "array",
            "maxItems": 100,
            "items": obj(
                {
                    "severity": {"type": "string", "enum": ["info", "warning", "error"]},
                    "message": TEXT,
                    "references": {"type": "array", "items": TEXT},
                }
            ),
        },
        "placements": {"type": "array", "items": PLACEMENT_SCHEMA, "maxItems": 500},
        "connections": {"type": "array", "items": CONNECTION_SCHEMA, "maxItems": 100},
        "unresolved": {"type": "array", "items": TEXT, "maxItems": 100},
    }
)
VALIDATOR = Draft202012Validator(PLAN_JSON_SCHEMA)


def empty_plan(summary=""):
    return {
        "schema_version": 2,
        "summary": summary,
        "findings": [],
        "placements": [],
        "connections": [],
        "unresolved": [],
    }


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanFormatError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def extract_json(text):
    if len(text) > 2_000_000:
        raise PlanFormatError("Plan exceeds the 2 MB limit.")
    candidate = text.strip()
    fence = chr(96) * 3
    if candidate.startswith(fence):
        lines = candidate.splitlines()
        if lines[-1].strip() != fence:
            raise PlanFormatError("Incomplete JSON code fence.")
        candidate = "\n".join(lines[1:-1])

    def reject(token):
        raise PlanFormatError(f"Non-finite JSON value: {token}")

    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            reject(token)
        return value

    try:
        result = json.loads(
            candidate,
            object_pairs_hook=_unique_pairs,
            parse_constant=reject,
            parse_float=finite_float,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise PlanFormatError(f"Invalid plan JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise PlanFormatError("A plan must be a JSON object.")
    return result


def normalize_plan(plan, mode=None):
    errors = list(VALIDATOR.iter_errors(plan))
    if errors:
        first = errors[0]
        path = ".".join(map(str, first.absolute_path)) or "plan"
        raise PlanFormatError(f"{path}: {first.message}")
    for p in plan["placements"]:
        if any(not math.isfinite(p[k]) for k in ("x_mm", "y_mm", "rotation_deg")):
            raise PlanFormatError("Placement contains non-finite coordinates.")
    if mode not in (None, "review", "placement", "routing"):
        raise PlanFormatError(f"Unknown mode: {mode}")
    if (
        (mode == "review" and (plan["placements"] or plan["connections"]))
        or (mode == "placement" and plan["connections"])
        or (mode == "routing" and plan["placements"])
    ):
        raise PlanFormatError(f"Actions are not permitted in {mode} mode.")
    if plan["placements"] and plan["connections"]:
        raise PlanFormatError("Approve placement first, then capture the board and plan routing.")
    return json.loads(json.dumps(plan, allow_nan=False))
