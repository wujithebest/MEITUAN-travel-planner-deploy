"""Regression tests for waypoint-local X-near-Y search centers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_schema import PlannedWaypoint
from services.step1_intent import (
    _bind_planned_waypoint_search_centers,
    _duration_from_request,
    _fallback_planned_waypoints_from_request,
    _meal_constraints_from_request,
)


REQUEST = "明早去故宫，明天中午去天坛公园，明天晚上去首都医科大学旁边的饭馆吃饭"


def test_local_reference_binds_to_meal_waypoint_only():
    waypoints = [
        PlannedWaypoint(type="fixed", name="故宫", category="visit"),
        PlannedWaypoint(type="fixed", name="天坛公园", category="visit"),
        PlannedWaypoint(type="placeholder", search_keyword="餐厅", category="meal"),
    ]
    _bind_planned_waypoint_search_centers(waypoints, REQUEST)
    assert waypoints[0].search_center_name is None
    assert waypoints[1].search_center_name is None
    assert waypoints[2].search_center_name == "首都医科大学"
    assert waypoints[2].time_slot == "dinner"


def test_fallback_waypoint_preserves_local_reference():
    waypoints = _fallback_planned_waypoints_from_request(REQUEST)
    meals = [wp for wp in waypoints if wp.category == "meal"]
    assert meals
    assert meals[-1].search_center_name == "首都医科大学"
    assert meals[-1].time_slot == "dinner"


def test_request_is_full_day_and_evening_meal_is_dinner():
    assert _duration_from_request(REQUEST) == "a full day"
    constraints = _meal_constraints_from_request(REQUEST)
    assert any(item["meal"] == "dinner" for item in constraints)
    assert all(item.get("fixed_poi_name") != "首都医科大学旁边的饭馆" for item in constraints)
