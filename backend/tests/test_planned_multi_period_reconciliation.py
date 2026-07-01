import asyncio
from types import SimpleNamespace

from services import step1_intent
from services.data_schema import FixedPoi
from services.step1_intent import (
    _extract_timed_planned_waypoints,
    _fallback_planned_waypoints_from_request,
    _fixed_budget,
)


REQUEST = "上午去南京路步行街逛逛，下午想去陆家嘴，晚上找个好吃的地方"


def _summary(waypoints):
    return [
        (
            waypoint.type,
            waypoint.name,
            waypoint.search_keyword,
            waypoint.category,
            waypoint.time_slot,
            waypoint.search_center_name,
        )
        for waypoint in waypoints
    ]


def test_timed_route_preserves_named_stops_and_normalizes_generic_meal():
    assert _summary(_extract_timed_planned_waypoints(REQUEST)) == [
        ("fixed", "南京路步行街", "南京路步行街", "visit", "morning", None),
        ("fixed", "陆家嘴", "陆家嘴", "visit", "afternoon", None),
        ("placeholder", None, "餐厅", "meal", "dinner", "陆家嘴"),
    ]


def test_rule_hints_are_complete_even_when_generic_fallback_is_disabled():
    waypoints = _fallback_planned_waypoints_from_request(REQUEST, include_generic=False)

    assert _summary(waypoints) == _summary(_extract_timed_planned_waypoints(REQUEST))
    assert all("好吃的地方" not in (waypoint.search_keyword or "") for waypoint in waypoints)


def test_fixed_budget_receives_request_for_area_stroll_expansion(monkeypatch):
    async def fake_search(*_args, **_kwargs):
        return [{"location": {"lat": 31.2359, "lng": 121.4795}, "typecode": "060000"}]

    async def fake_emit_status(*_args, **_kwargs):
        return None

    monkeypatch.setattr(step1_intent, "gaode_text_search", fake_search)
    monkeypatch.setattr(step1_intent, "emit_status", fake_emit_status)
    parsed = SimpleNamespace(fixed_pois=[FixedPoi(name="南京路步行街")])

    asyncio.run(_fixed_budget(parsed, "上海市", REQUEST))

    assert parsed.fixed_pois[0].expansion_required is True
    assert parsed.fixed_pois[0].activity_facet == "shopping_stroll"
