"""Plan reality validator — ensures the final itinerary matches the user's primary intent.

Runs AFTER Step3 assembles the route. Checks invariants that cannot be verified at
the single-POI level (e.g. meal takeover, hidden primary target, free_explore abuse).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanRealityResult:
    valid: bool
    primary_intent_coverage: float       # fraction of waypoints matching primary intent
    primary_waypoint_count: int           # waypoints that match primary intent
    unrelated_waypoint_count: int         # waypoints with no identity/theme evidence
    visible_waypoint_count: int           # waypoints with is_display_poi=True
    meal_waypoint_count: int              # waypoints that are restaurants
    meal_takeover: bool                   # meal is the only visible waypoint
    hidden_primary_target: bool           # primary target exists but is free_explore/hidden
    route_complete: bool                  # route segments exist for primary target
    violations: list[str] = field(default_factory=list)


def validate_plan_reality(
    parsed_intent: Any,
    route_points: list[dict[str, Any]],
    selected_anchors: list[dict[str, Any]] | None = None,
    route_segments: list[dict[str, Any]] | None = None,
) -> PlanRealityResult:
    """Validate that the final plan actually serves the user's primary intent."""

    violations: list[str] = []
    poi_query_type: str = getattr(parsed_intent, "poi_query_type", "") or ""
    primary_query: str = getattr(parsed_intent, "primary_query", "") or ""
    primary_required: list[str] = list(
        getattr(parsed_intent, "primary_required_terms", []) or []
    )
    explicit_meal: bool = bool(getattr(parsed_intent, "explicit_meal_intent", False))

    from .poi_relevance import score_poi_against_intent

    points = route_points or []
    segments = route_segments or []

    # ── Count waypoints ──
    primary_count = 0
    unrelated_count = 0
    visible_count = 0
    meal_count = 0
    hidden_primary = False
    primary_anchors: list[str] = []

    for pt in points:
        name = str(pt.get("name", "") or "")
        kind = str(pt.get("kind", "") or "")
        is_display = pt.get("is_display_poi", False) or pt.get("display_order") is not None
        typecode = str(pt.get("typecode", "") or "")
        is_meal = typecode.startswith("05") or kind in ("meal", "restaurant")

        if is_display:
            visible_count += 1
        if is_meal:
            meal_count += 1

        # Check if this point matches primary intent
        evidence = score_poi_against_intent(
            poi=pt,
            parsed_intent=parsed_intent,
            matched_query=primary_query,
        )

        if evidence.accepted:
            primary_count += 1
            primary_anchors.append(name)
        elif not is_meal and not evidence.identity_term_hits and not evidence.theme_term_hits:
            unrelated_count += 1

        # Check for hidden primary: free_explore that matches intent
        if evidence.accepted and not is_display and kind in ("free_explore", "hint"):
            hidden_primary = True
            violations.append(f"primary_target_hidden_as_{kind}: {name}")

    # ── Check invariants ──
    if poi_query_type in ("named_poi", "poi_category"):
        if primary_count == 0:
            violations.append("no_primary_waypoint_found")
        if hidden_primary:
            violations.append("primary_target_marked_free_explore_or_hint")

    # Meal takeover
    meal_takeover = (
        meal_count > 0 and visible_count > 0 and meal_count >= visible_count
        and not explicit_meal
    )
    if meal_takeover:
        violations.append("meal_takeover: restaurant is the only visible waypoint")

    # Route segments must include primary target
    primary_in_segments = False
    segment_names: set[str] = set()
    for seg in segments:
        segment_names.add(str(seg.get("from_poi", "") or ""))
        segment_names.add(str(seg.get("to_poi", "") or ""))
    for name in primary_anchors:
        if name in segment_names:
            primary_in_segments = True
            break

    route_complete = primary_in_segments or (len(primary_anchors) == 0)

    # ── Theme route minimums ──
    if poi_query_type == "theme_route":
        time_budget = float(getattr(parsed_intent, "time_budget", 1.0) or 1.0)
        if time_budget <= 0.25 and primary_count < 1:
            violations.append("quarter_day_theme_needs_1_related")
        elif 0.25 < time_budget <= 0.5 and primary_count < 2:
            violations.append("half_day_theme_needs_2_related")
        elif time_budget > 0.5 and primary_count < 3:
            violations.append("full_day_theme_needs_3_related")

    return PlanRealityResult(
        valid=len(violations) == 0,
        primary_intent_coverage=(
            primary_count / max(visible_count, 1) if visible_count > 0 else 0.0
        ),
        primary_waypoint_count=primary_count,
        unrelated_waypoint_count=unrelated_count,
        visible_waypoint_count=visible_count,
        meal_waypoint_count=meal_count,
        meal_takeover=meal_takeover,
        hidden_primary_target=hidden_primary,
        route_complete=route_complete,
        violations=violations,
    )


def plan_reality_audit_log(result: PlanRealityResult, primary_query: str = "") -> str:
    return (
        f"[PlanRealityAudit] "
        f"primary_query={primary_query!r} "
        f"primary_waypoint_count={result.primary_waypoint_count} "
        f"visible_waypoint_count={result.visible_waypoint_count} "
        f"meal_waypoint_count={result.meal_waypoint_count} "
        f"meal_takeover={result.meal_takeover} "
        f"hidden_primary_target={result.hidden_primary_target} "
        f"violations={result.violations} "
        f"valid={result.valid}"
    )
