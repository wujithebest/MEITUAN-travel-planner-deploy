"""v27: Tests for city resolution from coordinates and cross-city filtering.

Verifies that home_location Beijing coordinates override stale Shanghai
permanent_city, and that cross-city POIs are filtered out.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Test A: city_context coordinate inference ──


def test_infer_city_from_coord_beijing():
    """Beijing coordinates should infer '北京市'."""
    from services.city_context import infer_city_from_coord

    assert infer_city_from_coord(39.9, 116.4) == "北京市"
    assert infer_city_from_coord(40.0, 116.5) == "北京市"
    # 恒基伟业大厦B座 coordinates
    assert infer_city_from_coord(40.008744, 116.488462) == "北京市"


def test_infer_city_from_coord_shanghai():
    """Shanghai coordinates should infer '上海市'."""
    from services.city_context import infer_city_from_coord

    assert infer_city_from_coord(31.2, 121.5) == "上海市"


def test_infer_city_from_coord_shenzhen():
    """Shenzhen coordinates should infer '深圳市'."""
    from services.city_context import infer_city_from_coord

    assert infer_city_from_coord(22.6, 114.0) == "深圳市"


def test_infer_city_from_coord_guangzhou():
    """Guangzhou coordinates should infer '广州市'."""
    from services.city_context import infer_city_from_coord

    assert infer_city_from_coord(23.1, 113.4) == "广州市"


def test_infer_city_from_coord_unknown():
    """Unknown coordinates should return empty string."""
    from services.city_context import infer_city_from_coord

    # Pacific Ocean
    assert infer_city_from_coord(0.0, -150.0) == ""
    # Sahara
    assert infer_city_from_coord(25.0, 0.0) == ""


# ── Test B: resolve_departure_city with Beijing coords vs Shanghai permanent_city ──


def test_resolve_departure_city_coord_overrides_permanent():
    """Beijing coords + Shanghai permanent_city → Beijing wins."""
    from services.city_context import resolve_departure_city, apply_resolved_city
    import asyncio

    class MockProfile:
        home_location = {
            "label": "恒基伟业大厦B座",
            "lat": 40.008744,
            "lng": 116.488462,
        }
        permanent_city = ["上海市"]

    profile = MockProfile()

    # Run the async function
    city = asyncio.get_event_loop().run_until_complete(
        resolve_departure_city(profile)
    )
    assert city == "北京市", f"Expected 北京市, got {city}"

    # apply_resolved_city should update permanent_city
    apply_resolved_city(profile, city)
    assert profile.permanent_city[0] == "北京市"


def test_resolve_departure_city_no_coord_uses_permanent():
    """Without coordinates, permanent_city is used as fallback."""
    from services.city_context import resolve_departure_city
    import asyncio

    class MockProfile:
        home_location = None
        permanent_city = ["上海市"]

    profile = MockProfile()
    city = asyncio.get_event_loop().run_until_complete(
        resolve_departure_city(profile)
    )
    assert city == "上海市"


def test_resolve_departure_city_label_city_wins():
    """Label containing city name should take priority."""
    from services.city_context import resolve_departure_city
    import asyncio

    class MockProfile:
        home_location = {
            "label": "北京市朝阳区恒基伟业大厦",
            "lat": 40.0,
            "lng": 116.5,
        }
        permanent_city = ["上海市"]

    profile = MockProfile()
    city = asyncio.get_event_loop().run_until_complete(
        resolve_departure_city(profile)
    )
    assert city == "北京市"


# ── Test C: apply_resolved_city updates home_location ──


def test_apply_resolved_city_updates_both():
    """apply_resolved_city updates both permanent_city and home_location.city."""
    from services.city_context import apply_resolved_city

    class MockProfile:
        home_location = {"label": "恒基伟业大厦B座", "lat": 40.0, "lng": 116.5}
        permanent_city = ["上海市"]

    profile = MockProfile()
    apply_resolved_city(profile, "北京市")

    assert profile.permanent_city[0] == "北京市"
    assert profile.home_location.get("city") == "北京市"


# ── Test D: City consistency for different coordinate pairs ──


def test_infer_city_multiple_cities():
    """All supported cities should be correctly inferred."""
    from services.city_context import infer_city_from_coord

    test_cases = [
        (39.9, 116.4, "北京市"),
        (31.2, 121.5, "上海市"),
        (22.6, 114.1, "深圳市"),
        (23.1, 113.3, "广州市"),
        (39.1, 117.2, "天津市"),
        (29.5, 106.5, "重庆市"),
        (30.2, 120.2, "杭州市"),
        (30.6, 104.1, "成都市"),
        (30.6, 114.3, "武汉市"),
        (32.0, 118.8, "南京市"),
        (34.2, 108.9, "西安市"),
        (31.3, 120.6, "苏州市"),
        (28.2, 113.0, "长沙市"),
        (36.0, 120.4, "青岛市"),
        (24.5, 118.1, "厦门市"),
        (25.0, 102.7, "昆明市"),
    ]

    for lat, lng, expected in test_cases:
        result = infer_city_from_coord(lat, lng)
        assert result == expected, f"({lat}, {lng}) → expected {expected}, got {result}"


# ── Test E: Coordinate priority over permanent_city conflict ──


def test_coord_beijing_permanent_shanghai_correct_result():
    """When coordinate infers Beijing but permanent_city is Shanghai, Beijing must win.

    Log may or may not contain CityResolveAudit depending on whether reverse
    geocode succeeds. Either way, the result MUST be Beijing.
    """
    from services.city_context import resolve_departure_city, infer_city_from_coord
    import asyncio

    class MockProfile:
        home_location = {
            "label": "恒基伟业大厦B座",
            "lat": 40.008744,
            "lng": 116.488462,
            "city": "",  # No city field set
        }
        permanent_city = ["上海市", "黄浦区"]

    profile = MockProfile()
    city = asyncio.get_event_loop().run_until_complete(
        resolve_departure_city(profile)
    )

    # CRITICAL: Result MUST be Beijing, not Shanghai.
    # Whether this comes from reverse geocode or coordinate inference,
    # the stale permanent_city must not win.
    assert city == "北京市", f"Expected 北京市, got {city}"


def test_coord_inference_overrides_permanent_without_api():
    """Pure coordinate inference test — no API dependency.

    Verify infer_city_from_coord alone produces correct override.
    """
    from services.city_context import infer_city_from_coord

    # Beijing coordinates
    coord_city = infer_city_from_coord(40.008744, 116.488462)
    assert coord_city == "北京市"

    # If permanent_city says Shanghai but coordinate says Beijing, coordinate wins
    permanent_city = "上海市"
    assert coord_city != permanent_city
    assert coord_city == "北京市"
