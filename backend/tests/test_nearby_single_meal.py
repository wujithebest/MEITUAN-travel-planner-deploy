"""v28: Tests for nearby single meal request detection and planning.

Verifies:
- "在附近找一家餐厅" → nearby_single_meal_request=True, plan_mode=planned
- "在附近找一家饭馆" → same fast path
- "待会儿去附近逛逛，找一家好吃的，再散散步" → NOT misclassified
- ParsedIntent field existence, round-trip through dict, and Pydantic safety
"""
from __future__ import annotations

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── step1_intent detector tests ──

def test_nearby_single_meal_restaurant_detected():
    """'在附近找一家餐厅' should trigger nearby_single_meal_request."""
    from services.step1_intent import _is_nearby_single_meal_request
    assert _is_nearby_single_meal_request("在附近找一家餐厅") is True


def test_nearby_single_meal_fanguan_detected():
    """'在附近找一家饭馆' should trigger nearby_single_meal_request."""
    from services.step1_intent import _is_nearby_single_meal_request
    assert _is_nearby_single_meal_request("在附近找一家饭馆") is True


def test_nearby_single_meal_nearby_fandian():
    """'在附近找一家饭店' should trigger."""
    from services.step1_intent import _is_nearby_single_meal_request
    assert _is_nearby_single_meal_request("在附近找一家饭店") is True


def test_nearby_single_meal_zhoubian_canting():
    """'周边找一家餐馆' should trigger."""
    from services.step1_intent import _is_nearby_single_meal_request
    assert _is_nearby_single_meal_request("周边找一家餐馆") is True


def test_exploration_not_misclassified():
    """'待会儿去附近逛逛，找一家好吃的，再散散步' should NOT be nearby_single_meal."""
    from services.step1_intent import _is_nearby_single_meal_request
    text = "待会儿去附近逛逛，找一家好吃的，再散散步"
    assert _is_nearby_single_meal_request(text) is False


def test_route_not_misclassified():
    """'帮我规划一条路线' should NOT be nearby_single_meal."""
    from services.step1_intent import _is_nearby_single_meal_request
    assert _is_nearby_single_meal_request("帮我规划一条路线") is False


def test_exploration_then_meal_not_misclassified():
    """'先去附近逛逛然后再去吃饭' should NOT be nearby_single_meal."""
    from services.step1_intent import _is_nearby_single_meal_request
    assert _is_nearby_single_meal_request("先去附近逛逛然后再去吃饭") is False


def test_various_nearby_meal_phrasings():
    """Multiple natural phrasings should all be detected."""
    from services.step1_intent import _is_nearby_single_meal_request

    positive_cases = [
        "在附近找一家餐厅",
        "在附近找一家饭馆",
        "附近有什么好吃的餐厅",
        "周边找个饭店吃饭",
        "旁边有餐馆吗",
        "就近找个地方吃饭",
        "附近哪里有吃饭的地方",
        "帮我找一家附近的餐厅",
    ]
    for text in positive_cases:
        assert _is_nearby_single_meal_request(text) is True, (
            f"'{text}' should be detected as nearby_single_meal"
        )

    negative_cases = [
        "待会儿去附近逛逛，找一家好吃的，再散散步",
        "帮我规划一条文艺路线",
        "先去附近转转，然后吃饭",
        "在附近找个咖啡馆坐坐",
        "附近走走散步",
        "推荐一条路线",
        "去附近逛逛然后找一家好吃的",
    ]
    for text in negative_cases:
        assert _is_nearby_single_meal_request(text) is False, (
            f"'{text}' should NOT be detected as nearby_single_meal"
        )


# ── ParsedIntent field tests ──

def test_parsed_intent_has_nearby_single_meal_field():
    """ParsedIntent must declare nearby_single_meal_request as a formal field."""
    from services.data_schema import ParsedIntent

    p = ParsedIntent(duration="a half day")
    assert hasattr(p, "nearby_single_meal_request"), (
        "ParsedIntent missing field nearby_single_meal_request"
    )
    assert p.nearby_single_meal_request is False, (
        "default should be False"
    )


def test_parsed_intent_can_set_nearby_single_meal():
    """Direct attribute assignment must work without setattr."""
    from services.data_schema import ParsedIntent

    p = ParsedIntent(duration="a half day")
    p.nearby_single_meal_request = True
    assert p.nearby_single_meal_request is True


def test_parsed_intent_nearby_single_meal_constructor():
    """nearby_single_meal_request must be accepted in constructor."""
    from services.data_schema import ParsedIntent

    p = ParsedIntent(duration="a half day", nearby_single_meal_request=True)
    assert p.nearby_single_meal_request is True

    p2 = ParsedIntent(duration="a half day", nearby_single_meal_request=False)
    assert p2.nearby_single_meal_request is False


# ── Waypoint injection simulation tests ──

def test_nearby_single_meal_waypoint_has_meal_category():
    """The injected waypoint must have category='meal'."""
    from services.step1_intent import _build_nearby_single_meal_waypoint

    wp = _build_nearby_single_meal_waypoint("在附近找一家餐厅")
    assert wp.category == "meal", f"expected 'meal', got {wp.category!r}"
    assert wp.search_keyword == "餐厅"
    assert any(
        kw in wp.search_keywords
        for kw in ["餐厅", "饭馆", "餐馆", "饭店"]
    )


def test_nearby_multi_stop_local_request_detected():
    from services.step1_intent import is_nearby_multi_stop_local_request

    assert is_nearby_multi_stop_local_request("附近找一下饭馆，再找一家咖啡店") is True


def test_nearby_multi_stop_preserves_llm_ordered_waypoints_without_destination_rules():
    from services.data_schema import ParsedIntent
    from services.data_schema import PlannedWaypoint
    from services.step1_intent import (
        _reconcile_nearby_multi_stop_contract,
        is_nearby_multi_stop_local_request,
    )

    text = "附近找一家餐厅，再找一家奶茶店"
    assert is_nearby_multi_stop_local_request(text) is True

    llm_waypoints = [
        PlannedWaypoint(type="placeholder", search_keyword="餐厅", category="meal"),
        PlannedWaypoint(type="placeholder", search_keyword="奶茶店", category="cafe"),
    ]
    parsed = ParsedIntent(duration="a quarter day", plan_mode="exploratory")
    assert _reconcile_nearby_multi_stop_contract(
        parsed, "exploratory", llm_waypoints,
    ) == "llm_waypoints"
    assert parsed.plan_mode == "planned"
    assert [wp.search_keyword for wp in parsed.planned_waypoints] == ["餐厅", "奶茶店"]

    assert is_nearby_multi_stop_local_request("附近找一家餐厅，再找一家电玩店") is True


def test_planned_search_prefers_explicit_keyword_over_broader_fallback(monkeypatch):
    from services.data_schema import PlannedWaypoint
    from services import step3_planned

    async def fake_around_search(*_args, **kwargs):
        keyword = kwargs["keywords"]
        if keyword == "小吃店":
            return [{"id": "snack", "name": "测试小吃店"}]
        if keyword == "餐饮":
            return [{"id": "broad", "name": "更近的泛餐饮店"}]
        return []

    monkeypatch.setattr(step3_planned, "gaode_around_search", fake_around_search)
    waypoint = PlannedWaypoint(
        type="placeholder", search_keyword="小吃店", category="meal",
        search_keywords=["小吃店", "餐饮"],
    )
    results = asyncio.run(step3_planned._search_planned_keywords_for_radius(
        wp=waypoint,
        current_center={"lat": 40.0, "lng": 116.4},
        search_keywords=["小吃店", "餐饮"],
        radius=500,
        search_radius=3000,
        category_types="050000",
        city="北京市",
    ))
    assert [item["id"] for item in results] == ["snack"]


def test_strict_nearby_text_fallback_keeps_city_radius_and_type_contract(monkeypatch):
    from services import api_client
    from services.utils import ExternalAPIError

    async def fail_around(*_args, **_kwargs):
        raise ExternalAPIError("TLS connect error")

    async def fallback_text(*_args, **kwargs):
        assert kwargs["city"] == "北京市"
        assert kwargs["city_limit"] is True
        return [
            {"name": "附近茶饮", "typecode": "050400", "location": {"lat": 40.0001, "lng": 116.4001}},
            {"name": "远处茶饮", "typecode": "050400", "location": {"lat": 40.05, "lng": 116.45}},
            {"name": "附近咖啡", "typecode": "050500", "location": {"lat": 40.0001, "lng": 116.4001}},
        ]

    monkeypatch.setattr(api_client.config, "GAODE_API_KEY", "test-key")
    monkeypatch.setattr(api_client, "_gaode_get_json", fail_around)
    monkeypatch.setattr(api_client, "gaode_text_search", fallback_text)

    results = asyncio.run(api_client.gaode_around_search(
        location="116.4,40.0",
        keywords="茶饮",
        radius=500,
        types="050400|050900|051000",
        fallback_city="北京市",
        strict_nearby_fallback=True,
    ))
    assert [item["name"] for item in results] == ["附近茶饮"]


def test_nearby_multi_stop_contract_requires_llm_waypoints_and_preserves_them():
    from services.data_schema import ParsedIntent, PlannedWaypoint
    from services.step1_intent import _reconcile_nearby_multi_stop_contract

    parsed = ParsedIntent(duration="a quarter day", plan_mode="exploratory")
    source = _reconcile_nearby_multi_stop_contract(
        parsed,
        "exploratory",
        [],
    )

    assert source == "llm_missing_waypoints"
    assert parsed.plan_mode == "exploratory"
    assert parsed.planned_waypoints == []

    llm_waypoints = [
        PlannedWaypoint(type="placeholder", search_keyword="餐厅", category="meal"),
        PlannedWaypoint(type="placeholder", search_keyword="电玩店", category="visit"),
    ]
    parsed_from_llm = ParsedIntent(duration="a quarter day", plan_mode="exploratory")
    assert _reconcile_nearby_multi_stop_contract(
        parsed_from_llm,
        "exploratory",
        llm_waypoints,
    ) == "llm_waypoints"
    assert [wp.search_keyword for wp in parsed_from_llm.planned_waypoints] == ["餐厅", "电玩店"]


def test_nearby_multi_stop_does_not_capture_food_stroll_exploration():
    from services.step1_intent import is_nearby_multi_stop_local_request

    assert is_nearby_multi_stop_local_request(
        "待会儿去附近逛逛，找一家饭馆，再找一家咖啡店后散散步"
    ) is False


def test_nearby_single_meal_no_pydantic_value_error_restaurant():
    """'在附近找一家餐厅' must not raise Pydantic ValueError on ParsedIntent construction."""
    from services.data_schema import ParsedIntent
    from services.step1_intent import (
        _is_nearby_single_meal_request,
        _build_nearby_single_meal_waypoint,
    )

    text = "在附近找一家餐厅"
    parsed = ParsedIntent(duration="a half day", plan_mode="planned")

    # Simulate the injection logic from step1_intent.py
    plan_mode = parsed.plan_mode
    if (
        plan_mode == "planned"
        and not parsed.planned_waypoints
        and _is_nearby_single_meal_request(text)
    ):
        parsed.planned_waypoints = [_build_nearby_single_meal_waypoint(text)]
        parsed.plan_mode = "planned"
        parsed.nearby_single_meal_request = True

    assert parsed.nearby_single_meal_request is True
    assert parsed.plan_mode == "planned"
    assert len(parsed.planned_waypoints) == 1
    assert parsed.planned_waypoints[0].category == "meal"


def test_nearby_single_meal_no_pydantic_value_error_fanguan():
    """'在附近找一家饭馆' must not raise Pydantic ValueError."""
    from services.data_schema import ParsedIntent
    from services.step1_intent import (
        _is_nearby_single_meal_request,
        _build_nearby_single_meal_waypoint,
    )

    text = "在附近找一家饭馆"
    parsed = ParsedIntent(duration="a half day", plan_mode="planned")

    plan_mode = parsed.plan_mode
    if (
        plan_mode == "planned"
        and not parsed.planned_waypoints
        and _is_nearby_single_meal_request(text)
    ):
        parsed.planned_waypoints = [_build_nearby_single_meal_waypoint(text)]
        parsed.plan_mode = "planned"
        parsed.nearby_single_meal_request = True

    assert parsed.nearby_single_meal_request is True
    assert parsed.plan_mode == "planned"
    assert len(parsed.planned_waypoints) == 1


def test_exploration_does_not_trigger_injection():
    """Exploration query must NOT trigger nearby_single_meal injection."""
    from services.data_schema import ParsedIntent
    from services.step1_intent import (
        _is_nearby_single_meal_request,
        _build_nearby_single_meal_waypoint,
    )

    text = "待会儿去附近逛逛，找一家好吃的，再散散步"
    parsed = ParsedIntent(duration="a half day", plan_mode="planned")

    plan_mode = parsed.plan_mode
    if (
        plan_mode == "planned"
        and not parsed.planned_waypoints
        and _is_nearby_single_meal_request(text)
    ):
        parsed.planned_waypoints = [_build_nearby_single_meal_waypoint(text)]
        parsed.plan_mode = "planned"
        parsed.nearby_single_meal_request = True

    # Should NOT have triggered injection
    assert parsed.nearby_single_meal_request is False
    assert len(parsed.planned_waypoints) == 0


# ── Serialization round-trip tests (simulating _extract_intent_data / _restore) ──

_INTENT_DATA_KEYS = [
    "duration", "start_time", "raw_keywords", "search_keywords",
    "fixed_pois", "food_pref_keywords", "budget_per_capita",
    "transport_hint", "evening_requested", "nearby_single_meal_request",
]


def _simulate_extract_intent_data(parsed_intent):
    """Simulate what _extract_intent_data does (without importing routers)."""
    if not parsed_intent:
        return {}
    data = {
        "duration": getattr(parsed_intent, 'duration', ''),
        "start_time": (
            parsed_intent.start_time.isoformat()
            if getattr(parsed_intent, 'start_time', None) else None
        ),
        "raw_keywords": getattr(parsed_intent, 'raw_keywords', []),
        "search_keywords": getattr(parsed_intent, 'search_keywords', []),
        "fixed_pois": [],
        "food_pref_keywords": getattr(parsed_intent, 'food_pref_keywords', []),
        "budget_per_capita": getattr(parsed_intent, 'budget_per_capita', None),
        "transport_hint": getattr(parsed_intent, 'transport_hint', '公共交通'),
        "evening_requested": getattr(parsed_intent, 'evening_requested', False),
        "nearby_single_meal_request":
            getattr(parsed_intent, "nearby_single_meal_request", False),
    }
    for fp in getattr(parsed_intent, 'fixed_pois', []):
        data["fixed_pois"].append({"name": fp.name, "user_time_budget": fp.user_time_budget})
    return data


def _simulate_restore_from_context(intent_data):
    """Simulate what _restore_parsed_intent_from_context does (without importing routers)."""
    from services.data_schema import ParsedIntent

    if not isinstance(intent_data, dict) or not intent_data:
        return None
    data = dict(intent_data)
    data.setdefault("duration", "a full day")
    data.setdefault("raw_keywords", [])
    data.setdefault("search_keywords", [])
    data.setdefault("micro_keywords", [])
    data.setdefault("food_pref_keywords", [])
    data.setdefault("meal_search_keywords", [])
    data.setdefault("fixed_pois", [])
    data.setdefault("other_constraints", [])
    data.setdefault("meal_constraints", [])
    data.setdefault("poi_query_type", data.get("poi_query_type") or "theme_route")
    data.setdefault("primary_query", data.get("primary_query") or "")
    data.setdefault("plan_mode", data.get("plan_mode") or "exploratory")
    data.setdefault("nearby_single_meal_request", False)
    return ParsedIntent(**data)


def test_extract_intent_data_includes_nearby_single_meal():
    """Simulated _extract_intent_data must serialize nearby_single_meal_request."""
    from services.data_schema import ParsedIntent

    p = ParsedIntent(duration="a half day", nearby_single_meal_request=True)
    data = _simulate_extract_intent_data(p)
    assert "nearby_single_meal_request" in data, (
        "nearby_single_meal_request missing from intent_data"
    )
    assert data["nearby_single_meal_request"] is True


def test_restore_intent_preserves_nearby_single_meal():
    """Simulated _restore must preserve nearby_single_meal_request when present."""
    intent_data = {
        "duration": "a half day",
        "plan_mode": "planned",
        "nearby_single_meal_request": True,
    }
    restored = _simulate_restore_from_context(intent_data)
    assert restored is not None, "restore returned None"
    assert restored.nearby_single_meal_request is True


def test_restore_intent_defaults_nearby_single_meal():
    """Simulated _restore must default to False when absent."""
    intent_data = {
        "duration": "a full day",
        "plan_mode": "exploratory",
    }
    restored = _simulate_restore_from_context(intent_data)
    assert restored is not None, "restore returned None"
    assert restored.nearby_single_meal_request is False, (
        "should default to False when absent"
    )


def test_restore_intent_round_trip_preserves_field():
    """Full round-trip: ParsedIntent → dict → ParsedIntent preserves field."""
    from services.data_schema import ParsedIntent

    p = ParsedIntent(
        duration="a half day",
        plan_mode="planned",
        nearby_single_meal_request=True,
        planned_waypoints=[],
    )
    data = _simulate_extract_intent_data(p)
    # The real _extract_intent_data does NOT serialize plan_mode, so inject it
    # for a realistic round-trip (the calling code adds plan_mode separately)
    data["plan_mode"] = "planned"
    restored = _simulate_restore_from_context(data)
    assert restored is not None
    assert restored.nearby_single_meal_request is True
    assert restored.plan_mode == "planned"


# ── Fixed route non-interference test ──

def test_fixed_route_queries_not_detected_as_nearby_meal():
    """Fixed route queries should not trigger nearby_single_meal_request."""
    from services.step1_intent import _is_nearby_single_meal_request

    fixed_route_queries = [
        "帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店",
        "天安门故宫一日游",
        "北海公园烤鸭三里河",
        "下午文艺路线晚饭河边夜景",
    ]
    for text in fixed_route_queries:
        assert _is_nearby_single_meal_request(text) is False, (
            f"Fixed route query '{text}' should NOT be detected as nearby meal"
        )
