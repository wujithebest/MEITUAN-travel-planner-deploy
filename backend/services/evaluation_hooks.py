"""Low-overhead, opt-in evaluation tracing for dynamic route benchmark runs.

The hook keeps only JSON-safe data in a ContextVar. It never writes files and is
inactive for normal requests. The external evaluation runner persists the trace
returned in the terminal SSE event.
"""

from __future__ import annotations

import contextvars
import dataclasses
import time
from typing import Any


_trace_var: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "route_evaluation_trace", default=None
)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if dataclasses.is_dataclass(value):
        return _json_safe(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _safe_id(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum() or ch in ("-", "_"))[:96]


def start_evaluation_trace(
    *,
    enabled: bool,
    run_id: str = "",
    case_id: str = "",
) -> contextvars.Token | None:
    if not enabled:
        return None
    trace = {
        "schema_version": 1,
        "run_id": _safe_id(run_id),
        "case_id": _safe_id(case_id),
        "started_monotonic": time.monotonic(),
        "events": [],
        "stages": [],
        "intent": {},
        "dispatch": {},
        "plan_reality": [],
        "terminal": {},
    }
    return _trace_var.set(trace)


def reset_evaluation_trace(token: contextvars.Token | None) -> None:
    if token is not None:
        _trace_var.reset(token)


def is_evaluation_enabled() -> bool:
    return _trace_var.get() is not None


def record_event(name: str, **details: Any) -> None:
    trace = _trace_var.get()
    if trace is None:
        return
    trace["events"].append({
        "name": str(name),
        "elapsed_ms": int((time.monotonic() - trace["started_monotonic"]) * 1000),
        "details": _json_safe(details),
    })


def stage_started(name: str) -> float | None:
    if not is_evaluation_enabled():
        return None
    return time.monotonic()


def stage_finished(name: str, started_at: float | None, **details: Any) -> None:
    trace = _trace_var.get()
    if trace is None or started_at is None:
        return
    trace["stages"].append({
        "name": str(name),
        "duration_ms": int((time.monotonic() - started_at) * 1000),
        "details": _json_safe(details),
    })


def record_intent(parsed_intent: Any) -> None:
    trace = _trace_var.get()
    if trace is None or parsed_intent is None:
        return
    fixed_pois = getattr(parsed_intent, "fixed_pois", []) or []
    trace["intent"] = _json_safe({
        "resolved_city": getattr(parsed_intent, "resolved_city", ""),
        "duration": getattr(parsed_intent, "duration", ""),
        "plan_mode": getattr(parsed_intent, "plan_mode", ""),
        "fixed_pois": [getattr(item, "name", str(item)) for item in fixed_pois],
        "raw_keywords": getattr(parsed_intent, "raw_keywords", []),
        "search_keywords": getattr(parsed_intent, "search_keywords", []),
        "food_pref_keywords": getattr(parsed_intent, "food_pref_keywords", []),
        "meal_search_keywords": getattr(parsed_intent, "meal_search_keywords", []),
        "budget_per_capita": getattr(parsed_intent, "budget_per_capita", None),
        "transport_hint": getattr(parsed_intent, "transport_hint", ""),
        "evening_requested": getattr(parsed_intent, "evening_requested", False),
        "theme_profile": getattr(parsed_intent, "theme_profile", ""),
        "theme_label": getattr(parsed_intent, "theme_label", ""),
        "activity_facet": getattr(parsed_intent, "activity_facet", ""),
        "required_features": getattr(parsed_intent, "required_features", []),
        "preferred_features": getattr(parsed_intent, "preferred_features", []),
        "proximity_requested": getattr(parsed_intent, "proximity_requested", False),
        "search_area_label": getattr(parsed_intent, "search_area_label", ""),
        "delete_list": getattr(parsed_intent, "delete_list", []),
        "excluded_areas": getattr(parsed_intent, "excluded_areas", []),
    })


def record_dispatch(decision: Any) -> None:
    trace = _trace_var.get()
    if trace is None or decision is None:
        return
    trace["dispatch"] = _json_safe({
        "conversation_mode": getattr(decision, "conversation_mode", ""),
        "target_plan_mode": getattr(decision, "target_plan_mode", ""),
        "earliest_step": getattr(decision, "earliest_step", ""),
        "confidence": getattr(decision, "confidence", None),
        "intent_patch": getattr(decision, "intent_patch", {}),
        "include_constraints": getattr(decision, "include_constraints", {}),
        "exclude_constraints": getattr(decision, "exclude_constraints", {}),
        "point_operations": getattr(decision, "point_operations", []),
        "reason": getattr(decision, "reason", ""),
    })


def record_plan_reality(result: Any) -> None:
    trace = _trace_var.get()
    if trace is None or result is None:
        return
    trace["plan_reality"].append(_json_safe({
        "valid": getattr(result, "valid", False),
        "primary_intent_coverage": getattr(result, "primary_intent_coverage", 0.0),
        "primary_waypoint_count": getattr(result, "primary_waypoint_count", 0),
        "visible_waypoint_count": getattr(result, "visible_waypoint_count", 0),
        "meal_takeover": getattr(result, "meal_takeover", False),
        "hidden_primary_target": getattr(result, "hidden_primary_target", False),
        "route_complete": getattr(result, "route_complete", False),
        "violations": getattr(result, "violations", []),
    }))


def record_terminal(outcome: str, **details: Any) -> None:
    trace = _trace_var.get()
    if trace is None:
        return
    trace["terminal"] = {
        "outcome": str(outcome),
        "elapsed_ms": int((time.monotonic() - trace["started_monotonic"]) * 1000),
        "details": _json_safe(details),
    }


def get_evaluation_trace_payload() -> dict[str, Any] | None:
    trace = _trace_var.get()
    if trace is None:
        return None
    payload = _json_safe(trace)
    payload.pop("started_monotonic", None)
    return payload
