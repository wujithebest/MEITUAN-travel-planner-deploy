"""Plan reality validator — ensures the final itinerary matches the user's primary intent.

Runs AFTER Step3 assembles the route. Checks invariants that cannot be verified at
the single-POI level (e.g. meal takeover, hidden primary target, free_explore abuse).
"""

from __future__ import annotations

import re
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


_THEME_TERM_STOPWORDS = {
    "北京", "北京市", "攻略", "推荐", "路线", "打卡", "拍照", "游玩",
    "一整天", "一日游", "半日游", "附近", "周边", "休闲",
}


def _theme_evidence_profile(parsed_intent: Any) -> dict[str, list[str]] | None:
    """Build deterministic relevance terms for generic theme routes.

    Step1 may not select an official theme_profile for a named park request, but
    its raw/search/micro keywords still contain reliable evidence such as 公园、
    湿地、自然.  The reality validator must use that evidence instead of
    treating every generated waypoint as unrelated.
    """
    values: list[str] = []
    allowed_typecodes: list[str] = []
    excluded_terms: list[str] = []

    # Prefer the official theme profile when Step1 resolved one.  This keeps
    # route validation aligned with macro/micro recall instead of requiring a
    # POI name to literally contain an abstract phrase such as “亲子互动”.
    profile_id = getattr(parsed_intent, "theme_profile", None)
    if isinstance(profile_id, str) and profile_id:
        from .theme_profiles import build_effective_theme_profile

        profile = build_effective_theme_profile(parsed_intent)
        if profile.get("active"):
            for field_name in (
                "destination_anchor_terms",
                "allowed_name_terms",
                "required_terms",
                "micro_poi_keywords",
            ):
                values.extend(str(item or "") for item in (profile.get(field_name, []) or []))
            allowed_typecodes.extend(
                str(item or "")
                for item in (
                    list(profile.get("allowed_typecode_prefixes", []) or [])
                    + list(profile.get("typecode_prefixes", []) or [])
                )
            )
            excluded_terms.extend(
                str(item or "") for item in (profile.get("excluded_terms", []) or [])
            )
    for field_name in (
        "primary_required_terms",
        "theme_keywords",
        "micro_poi_keywords",
        "micro_keywords",
        "raw_keywords",
        "search_keywords",
    ):
        values.extend(str(item or "") for item in (getattr(parsed_intent, field_name, []) or []))

    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in re.split(r"[\s,，、/|;；]+", value):
            clean = token.strip()
            if len(clean) < 2 or clean in _THEME_TERM_STOPWORDS or clean in seen:
                continue
            seen.add(clean)
            terms.append(clean)

    if not terms and not allowed_typecodes:
        return None
    return {
        "required_terms": terms[:48],
        "allowed_typecode_prefixes": list(dict.fromkeys(filter(None, allowed_typecodes))),
        "excluded_terms": list(dict.fromkeys(filter(None, excluded_terms))),
    }


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
    theme_evidence = _theme_evidence_profile(parsed_intent) if poi_query_type == "theme_route" else None

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
        is_display = (
            kind not in ("start", "hint", "free_explore", "route_only", "traffic", "empty")
            and (
                pt.get("is_display_poi", False)
                or pt.get("display_order") is not None
                or pt.get("is_waypoint") is True
            )
        )
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
            theme_profile=theme_evidence,
            matched_query=primary_query,
        )

        if evidence.accepted and is_display:
            # v20: Only count visible display POIs as primary waypoints
            # Search area names and hidden points don't count
            primary_count += 1
            primary_anchors.append(name)
        elif evidence.accepted and not is_display and kind in ("free_explore", "hint"):
            # A valid primary target that's been hidden — this is a violation
            hidden_primary = True
            violations.append(f"primary_target_hidden_as_{kind}: {name}")
        elif not is_meal and not evidence.identity_term_hits and not evidence.theme_term_hits:
            unrelated_count += 1

    # ── Check invariants ──
    if poi_query_type in ("named_poi", "poi_category"):
        if primary_count == 0:
            violations.append("no_primary_waypoint_found")
        if hidden_primary:
            violations.append("primary_target_marked_free_explore_or_hint")

    # v20: Check that all user-specified fixed POIs are present in route_points
    _user_fixed_names = {
        fp.name for fp in (getattr(parsed_intent, "fixed_pois", []) or [])
    }
    # Also check selected_anchors for fixed/primary_target markers
    if selected_anchors:
        for sa in selected_anchors:
            if sa.get("fixed") or sa.get("primary_target") or sa.get("explicitly_named_by_user"):
                _user_fixed_names.add(str(sa.get("name", "") or ""))
    # Check each user-specified fixed POI is a visible waypoint
    _point_names = {str(p.get("name", "") or "") for p in points}
    _visible_point_names = {
        str(p.get("name", "") or "") for p in points
        if p.get("is_display_poi") or p.get("is_waypoint") or p.get("display_order") is not None
    }
    for fname in _user_fixed_names:
        if not fname:
            continue
        # Must exist in points
        if fname not in _point_names:
            violations.append(f"required_fixed_anchor_missing: {fname}")
        # Must be visible (not hidden/free_explore/hint)
        elif fname not in _visible_point_names:
            violations.append(f"required_fixed_anchor_hidden: {fname}")
        # Must not be free_explore/hint
        else:
            for pt in points:
                if str(pt.get("name", "") or "") == fname:
                    kind = str(pt.get("kind", "") or "")
                    if kind in ("free_explore", "hint", "route_only"):
                        violations.append(f"required_fixed_anchor_bad_kind: {fname} is {kind}")
                    break

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

    # v20: visible_waypoint_count=0 should never be valid
    if visible_count == 0:
        violations.append("no_visible_waypoints")

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
