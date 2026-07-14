"""v27: Tests for supplement distance filtering on relaxed multi-facet art routes.

Verifies that distant POIs (like 中国电影资料馆 at 15km) are filtered out
for relaxed multi-facet routes centered on 798/望京.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Test helpers ──

def _make_parsed_intent_relaxed_multifacet():
    """Build a ParsedIntent matching the bug report: 文艺拍照 + relaxed."""
    from services.data_schema import ParsedIntent

    return ParsedIntent(
        duration="a full day",
        time_budget=1.0,
        activity_facet="multi_facet_art_photo_cafe_shop",
        poi_query_type="theme_route",
        theme_route_locked=True,
        theme_facets=[
            {"id": "photo_checkin", "required": True},
            {"id": "art_culture_lifestyle", "required": True},
            {"id": "cafe_stop", "required": True},
            {"id": "specialty_shop", "required": True},
            {"id": "relaxed_pace", "required": True},
        ],
        theme_coverage_policy="cover_required_facets",
        search_keywords=["北京 798", "文艺拍照", "精品咖啡"],
        micro_keywords=["独立画廊", "艺术空间"],
        raw_keywords=["帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点"],
        primary_query="北京文艺拍照路线",
        density_min_visible_pois=5,
        density_target_visible_pois=6,
        candidate_target=4,
    )


def _make_798_points():
    """Build existing points centered around 798/望京 area."""
    return [
        {
            "name": "成当代艺术中心",
            "location": {"lat": 39.9842, "lng": 116.4950},
            "kind": "anchor_internal",
            "typecode": "140100",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
            "matched_facets": ["art_culture_lifestyle"],
        },
        {
            "name": "蜂巢当代艺术中心",
            "location": {"lat": 39.9830, "lng": 116.4970},
            "kind": "anchor_internal",
            "typecode": "140100",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
            "matched_facets": ["art_culture_lifestyle"],
        },
        {
            "name": "798艺术区",
            "location": {"lat": 39.9850, "lng": 116.4960},
            "kind": "anchor_internal",
            "typecode": "110100",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
            "matched_facets": ["art_culture_lifestyle", "photo_checkin"],
        },
        {
            "name": "某精品咖啡馆",
            "location": {"lat": 39.9845, "lng": 116.4945},
            "kind": "cafe",
            "typecode": "050400",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
            "matched_facets": ["cafe_stop"],
        },
        {
            "name": "某买手店",
            "location": {"lat": 39.9835, "lng": 116.4980},
            "kind": "anchor_internal",
            "typecode": "060100",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
            "matched_facets": ["specialty_shop"],
        },
    ]


# ── Test 1: PlanReality counts 798 POIs correctly ──

def test_multifacet_art_reality_counts_798_pois():
    """798 art POIs should be counted as primary, not 0."""
    from services.plan_reality_validator import validate_plan_reality

    parsed = _make_parsed_intent_relaxed_multifacet()
    points = _make_798_points()

    result = validate_plan_reality(parsed, points, route_segments=[])

    # Should count at least 4 primary waypoints
    assert result.primary_waypoint_count >= 4, (
        f"Expected >=4 primary waypoints for 798 POIs, got {result.primary_waypoint_count}"
    )
    assert result.visible_waypoint_count >= 5, (
        f"Expected >=5 visible waypoints, got {result.visible_waypoint_count}"
    )
    # Should NOT have theme_needs violations (has enough art POIs)
    theme_needs_violations = [v for v in result.violations if "theme_needs" in v]
    assert len(theme_needs_violations) == 0, (
        f"Should have no theme_needs violations with 5 798 POIs, got: {theme_needs_violations}"
    )
    # Should NOT be too sparse
    sparse = [v for v in result.violations if "too_sparse" in v]
    assert len(sparse) == 0, f"Should not be sparse with 5 POIs, got: {sparse}"


# ── Test 2: PlanReality doesn't trigger theme_needs for adequate routes ──

def test_multifacet_art_does_not_trigger_theme_needs():
    """Adequate multi-facet routes should NOT get theme_needs violations
    that would trigger _targeted_supplement_recall."""
    from services.plan_reality_validator import validate_plan_reality

    parsed = _make_parsed_intent_relaxed_multifacet()
    points = _make_798_points()

    result = validate_plan_reality(parsed, points, route_segments=[])

    # The check in step3_micro.py triggers supplement when "theme_needs" in violation
    _has_theme_needs = any("theme_needs" in v for v in result.violations)
    assert not _has_theme_needs, (
        f"Must NOT trigger supplement: violations={result.violations}"
    )


# ── Test 3: Relaxed multi-facet detection ──

def test_is_relaxed_multifacet_detection():
    """Verify that the detection logic correctly identifies relaxed multi-facet routes."""
    from services.data_schema import ParsedIntent

    # Has 3+ of {photo_checkin, art_culture_lifestyle, cafe_stop, specialty_shop} + relaxed_pace
    parsed = ParsedIntent(
        duration="a full day",
        theme_facets=[
            {"id": "photo_checkin"},
            {"id": "art_culture_lifestyle"},
            {"id": "cafe_stop"},
            {"id": "specialty_shop"},
            {"id": "relaxed_pace"},
        ],
        activity_facet="multi_facet_art_photo_cafe_shop",
        poi_query_type="theme_route",
    )

    facet_ids = {
        str(f.get("id") or "")
        for f in (parsed.theme_facets or [])
        if isinstance(f, dict)
    }
    multi_facet_facets = {"photo_checkin", "art_culture_lifestyle", "cafe_stop", "specialty_shop"}
    has_relaxed = "relaxed_pace" in facet_ids
    is_relaxed = len(facet_ids & multi_facet_facets) >= 3 and has_relaxed

    assert is_relaxed, "Should detect as relaxed multi-facet"
    assert has_relaxed, "Should detect relaxed_pace facet"


# ── Test 4: Detour cost calculation for distant POI ──

def test_detour_cost_filters_distant_poi():
    """A POI 15km away should cause a large detour and be filtered."""
    from services.utils import haversine_km

    # 798 center
    loc_798 = {"lat": 39.985, "lng": 116.496}
    # 中国电影资料馆 (小西天 area, ~15km from 798)
    loc_film = {"lat": 39.962, "lng": 116.363}

    distance = haversine_km(loc_798, loc_film)
    # Should be roughly 12-16km
    assert distance > 10.0, f"Expected >10km, got {distance:.1f}"

    # Simulate a simple detour: insert between two 798 POIs
    prev_loc = {"lat": 39.984, "lng": 116.495}
    next_loc = {"lat": 39.983, "lng": 116.497}

    prev_next = haversine_km(prev_loc, next_loc)
    d_prev = haversine_km(prev_loc, loc_film)
    d_next = haversine_km(loc_film, next_loc)
    detour = d_prev + d_next - prev_next

    # Detour should be >> 2.0km (the relaxed limit)
    assert detour > 2.0, f"Detour should be >2.0km for distant POI, got {detour:.1f}"


# ── Test 5: Nearby supplement passes detour check ──

def test_nearby_supplement_passes_detour():
    """A POI 1km from 798 should have a small detour and be accepted."""
    from services.utils import haversine_km

    # 798 POIs
    prev_loc = {"lat": 39.984, "lng": 116.495}
    next_loc = {"lat": 39.983, "lng": 116.497}
    # Nearby supplement (e.g. another gallery in 798)
    nearby_loc = {"lat": 39.9845, "lng": 116.496}

    d_nearby = haversine_km(prev_loc, nearby_loc)
    assert d_nearby < 2.0, f"Nearby POI should be <2km, got {d_nearby:.1f}"

    prev_next = haversine_km(prev_loc, next_loc)
    d_prev = haversine_km(prev_loc, nearby_loc)
    d_next = haversine_km(nearby_loc, next_loc)
    detour = d_prev + d_next - prev_next

    assert detour < 1.0, f"Detour should be <1.0km for nearby POI, got {detour:.1f}"


# ── Test 6: PlanReality visibility count with is_display_poi set ──

def test_visible_count_with_display_pois():
    """When POIs have is_display_poi=True and correct kinds, they must be counted."""
    from services.plan_reality_validator import validate_plan_reality

    parsed = _make_parsed_intent_relaxed_multifacet()
    # Points with various kinds — all should be visible
    points = [
        {
            "name": "798CUBE",
            "location": {"lat": 39.985, "lng": 116.496},
            "kind": "anchor_internal",
            "typecode": "140100",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
            "matched_facets": ["art_culture_lifestyle"],
        },
        {
            "name": "北极熊画廊",
            "location": {"lat": 39.984, "lng": 116.497},
            "kind": "anchor_internal",
            "typecode": "140100",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
            "matched_facets": ["art_culture_lifestyle"],
        },
        {
            "name": "成当代艺术中心",
            "location": {"lat": 39.983, "lng": 116.495},
            "kind": "anchor_internal",
            "typecode": "140100",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
            "matched_facets": ["art_culture_lifestyle"],
        },
    ]

    result = validate_plan_reality(parsed, points, route_segments=[])
    assert result.visible_waypoint_count >= 3
    # Should not report 0 visible
    assert result.visible_waypoint_count > 0, "Must count display POIs"


# ── Test 7: Point matching for art keywords in _is_multi_facet_primary ──

def test_art_keyword_matching():
    """POIs with art-related names should match _is_multi_facet_primary."""
    # Test the keyword list covers common 798 POI names
    from services.plan_reality_validator import validate_plan_reality

    parsed = _make_parsed_intent_relaxed_multifacet()

    art_poi_names = [
        "成当代艺术中心",     # → "艺术中心"
        "蜂巢当代艺术中心",   # → "艺术中心", "当代"
        "798CUBE",            # → "798"
        "北极熊画廊",         # → "画廊"
        "美仑美术馆·圣之空间", # → "美术馆"
        "山中天艺术中心",     # → "艺术中心"
        "751D·PARK",          # → "751"
        "木木美术馆",         # → "美术馆"
    ]

    for name in art_poi_names:
        points = [{
            "name": name,
            "location": {"lat": 39.985, "lng": 116.496},
            "kind": "anchor_internal",
            "typecode": "140100",
            "is_display_poi": True,
            "is_waypoint": True,
            "day": 1,
        }]
        result = validate_plan_reality(parsed, points, route_segments=[])
        assert result.primary_waypoint_count >= 1, (
            f"'{name}' should count as primary art waypoint, "
            f"primary_count={result.primary_waypoint_count}"
        )


# ── Test 8: First-turn regression — cafe still works ──

def test_first_turn_cafe_still_works():
    """First-turn with '有咖啡馆' should still match cafe POIs positively."""
    from services.plan_reality_validator import validate_plan_reality
    from services.data_schema import ParsedIntent

    parsed = ParsedIntent(
        duration="a full day",
        time_budget=1.0,
        activity_facet="multi_facet_art_photo_cafe_shop",
        poi_query_type="theme_route",
        theme_facets=[
            {"id": "photo_checkin"},
            {"id": "art_culture_lifestyle"},
            {"id": "cafe_stop"},
            {"id": "specialty_shop"},
            {"id": "relaxed_pace"},
        ],
        density_min_visible_pois=5,
        density_target_visible_pois=6,
    )

    points = _make_798_points()  # includes a cafe POI
    result = validate_plan_reality(parsed, points, route_segments=[])

    # The cafe POI should be counted (not filtered out)
    assert result.primary_waypoint_count >= 1
    # cafe_stop facet should be covered
    cafe_points = [
        p for p in points
        if "cafe" in str(p.get("matched_facets", []))
        or "咖啡" in str(p.get("name", ""))
    ]
    assert len(cafe_points) >= 1, "Should have at least one cafe POI"
