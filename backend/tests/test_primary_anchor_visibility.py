"""Regression tests for area-category parsing and Step3 target visibility."""

import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_schema import SubAnchor
from services import api_client
from services.plan_reality_validator import validate_plan_reality
from services.step1_intent import _parse_area_category_modifier
from services.step3_micro import _fill_segment


def _mall_intent() -> SimpleNamespace:
    return SimpleNamespace(
        poi_query_type="poi_category",
        primary_query="商场",
        primary_required_terms=["购物中心", "商场", "商业广场"],
        primary_excluded_terms=["停车场", "写字楼"],
        allowed_typecode_prefixes=["060100", "060101", "060102"],
        excluded_typecode_prefixes=["050000", "110000"],
        explicit_meal_intent=False,
        time_budget=0.25,
        duration="a quarter day",
    )


def _sub_anchor(level: str, internal_pois: list[dict] | None = None) -> SubAnchor:
    return SubAnchor(
        parent_name="悠唐购物中心1期",
        name="悠唐购物中心1期",
        location={"lat": 39.921, "lng": 116.443},
        time_budget_min=120,
        capacity="quarter_day",
        internal_pois=internal_pois or [],
        degradation_level=level,
    )


def test_area_category_parser_removes_action_words() -> None:
    compact = _parse_area_category_modifier("朝阳区找商场")
    full_day = _parse_area_category_modifier("明天去朝阳区的商场玩一天")

    assert compact is not None
    assert compact["search_area_label"] == "朝阳区"
    assert compact["primary_query"] == "商场"
    assert compact["category_id"] == "shopping_mall"
    assert full_day is not None
    assert full_day["primary_query"] == "商场"


def test_free_direct_category_anchor_stays_visible() -> None:
    intent = _mall_intent()
    points = _fill_segment(
        {
            "sub_anchor": _sub_anchor("free"),
            "degradation": "free",
            "hint": "到达该区域后适合自由探索，无需固定路线",
        },
        meal_poi_name=None,
        start_location={"lat": 39.927, "lng": 116.420},
        time_budget_min=120,
        day_index=1,
        parsed_intent=intent,
    )

    assert len(points) == 1
    assert points[0]["name"] == "悠唐购物中心1期"
    assert points[0]["kind"] == "anchor_internal"
    assert points[0]["is_display_poi"] is True
    assert points[0]["is_waypoint"] is True
    assert validate_plan_reality(intent, points).valid


def test_normal_direct_category_keeps_anchor_before_internals() -> None:
    intent = _mall_intent()
    internal = [
        {
            "name": "内部展览空间",
            "location": {"lat": 39.9212, "lng": 116.4432},
            "typecode": "140000",
        }
    ]
    points = _fill_segment(
        {
            "sub_anchor": _sub_anchor("normal", internal),
            "degradation": "normal",
            "backbone": internal,
            "hint": "",
        },
        meal_poi_name=None,
        start_location={"lat": 39.927, "lng": 116.420},
        time_budget_min=120,
        day_index=1,
        parsed_intent=intent,
    )

    assert [point["name"] for point in points] == ["悠唐购物中心1期"]
    assert points[0]["primary_target"] is True
    assert points[0]["is_display_poi"] is True
    assert validate_plan_reality(intent, points).primary_waypoint_count >= 1


def test_theme_waypoints_are_visible_before_step4_display_order() -> None:
    intent = SimpleNamespace(
        poi_query_type="theme_route",
        primary_query="",
        primary_required_terms=[],
        primary_excluded_terms=[],
        allowed_typecode_prefixes=[],
        excluded_typecode_prefixes=[],
        explicit_meal_intent=False,
        time_budget=1.0,
        micro_keywords=["公园 漫步", "自然 景观", "城市绿地 休闲"],
        micro_poi_keywords=[],
        theme_keywords=[],
        raw_keywords=["公园"],
        search_keywords=["北京 城市公园"],
    )
    points = [
        {"name": "起点", "kind": "start", "is_waypoint": True},
        {"name": "南苑森林湿地公园1期", "kind": "anchor_internal", "typecode": "110101", "is_waypoint": True},
        {"name": "南苑森林湿地公园2期", "kind": "anchor_internal", "typecode": "110101", "is_waypoint": True},
        {"name": "和义农场湿地公园", "kind": "anchor_internal", "typecode": "110101", "is_waypoint": True},
    ]

    result = validate_plan_reality(intent, points)

    assert result.valid, result.violations
    assert result.visible_waypoint_count == 3
    assert result.primary_waypoint_count == 3


def test_required_fixed_anchor_missing_detected() -> None:
    """用户指定的南苑公园缺失应被检出"""
    intent = SimpleNamespace(
        poi_query_type="theme_route",
        primary_query="",
        primary_required_terms=[],
        primary_excluded_terms=[],
        allowed_typecode_prefixes=[],
        excluded_typecode_prefixes=[],
        explicit_meal_intent=False,
        time_budget=1.0,
        fixed_pois=[SimpleNamespace(name="南苑公园")],
    )
    points = [
        {"name": "起点", "kind": "start", "is_waypoint": True},
        {"name": "南苑森林湿地公园", "kind": "anchor_internal", "typecode": "110101", "is_waypoint": True, "is_display_poi": True},
        {"name": "和义农场湿地公园", "kind": "anchor_internal", "typecode": "110101", "is_waypoint": True, "is_display_poi": True},
    ]
    result = validate_plan_reality(intent, points)
    assert not result.valid, "Should detect missing fixed anchor"
    assert any("南苑公园" in v for v in result.violations), f"Violations: {result.violations}"
    print(f"✅ fixed_anchor_missing detected: {result.violations}")


def test_required_fixed_anchor_present_passes() -> None:
    """用户指定的南苑公园在route_points中应通过验证"""
    intent = SimpleNamespace(
        poi_query_type="theme_route",
        primary_query="",
        primary_required_terms=[],
        primary_excluded_terms=[],
        allowed_typecode_prefixes=[],
        excluded_typecode_prefixes=[],
        explicit_meal_intent=False,
        time_budget=1.0,
        fixed_pois=[SimpleNamespace(name="南苑公园")],
        micro_keywords=["公园 漫步", "自然 景观", "城市绿地 休闲"],
        micro_poi_keywords=[],
        theme_keywords=[],
        raw_keywords=["公园"],
        search_keywords=["北京 城市公园"],
    )
    points = [
        {"name": "起点", "kind": "start", "is_waypoint": True},
        {"name": "南苑森林湿地公园", "kind": "anchor_internal", "typecode": "110101", "is_waypoint": True, "is_display_poi": True},
        {"name": "南苑公园", "kind": "primary_anchor", "typecode": "110101", "is_waypoint": True, "is_display_poi": True,
         "primary_target": True, "fixed": True},
        {"name": "和义农场湿地公园", "kind": "anchor_internal", "typecode": "110101", "is_waypoint": True, "is_display_poi": True},
    ]
    result = validate_plan_reality(intent, points)
    assert result.valid, f"Should pass but got: {result.violations}"
    print(f"✅ fixed anchor present: valid={result.valid}")


def test_gaode_text_search_can_hard_limit_city(monkeypatch) -> None:
    captured: dict = {}

    async def fake_get_json(_label, _url, params):
        captured.update(params)
        return {"pois": []}

    monkeypatch.setattr(api_client.config, "GAODE_API_KEY", "test-key")
    monkeypatch.setattr(api_client, "_gaode_get_json", fake_get_json)

    asyncio.run(api_client.gaode_text_search("公园", city="北京市", city_limit=True))

    assert captured["city"] == "北京市"
    assert captured["citylimit"] == "true"
