"""Regression coverage for POIs that were displayed without a complete route."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import step3_micro


def _point(name: str, lat: float, lng: float, **extra):
    return {
        "name": name,
        "kind": "anchor_internal",
        "day": 1,
        "location": {"lat": lat, "lng": lng},
        "typecode": "080100",
        "indoor_map": "1",
        "is_waypoint": True,
        "is_display_poi": True,
        **extra,
    }


def test_explicit_full_day_route_connects_every_selected_poi(monkeypatch):
    intent = SimpleNamespace(
        time_budget=1.0,
        duration="a full day",
        fixed_pois=[SimpleNamespace(name="示例景区")],
        plan_mode="planned",
        theme_profile=None,
        theme_label=None,
        micro_poi_keywords=[],
        theme_keywords=[],
    )
    points = [
        {
            "name": "出发地",
            "kind": "start",
            "day": 1,
            "location": {"lat": 39.9000, "lng": 116.3900},
            "is_waypoint": True,
            "is_display_poi": True,
        },
        # Deliberately close and indoor-tagged: the old building/waypoint
        # compression reduced these five visible POIs to one or two segments.
        _point("景区入口", 39.9001, 116.3901),
        _point("展馆甲", 39.9002, 116.3902),
        _point("展馆乙", 39.9003, 116.3903),
        _point("中心广场", 39.9004, 116.3904),
        _point("景区出口", 39.9005, 116.3905),
    ]

    async def fake_route(_intent, _transport, a, b):
        return {
            "transport": "步行",
            "duration_min": 3,
            "distance_km": 0.1,
            "polyline": [
                [a["location"]["lat"], a["location"]["lng"]],
                [b["location"]["lat"], b["location"]["lng"]],
            ],
        }

    monkeypatch.setattr(step3_micro, "_route_between", fake_route)

    segments, annotations = asyncio.run(
        step3_micro._build_segments(intent, "步行", points)
    )

    assert len(segments) == len(points) - 1
    connected_names = {segments[0].from_poi} | {seg.to_poi for seg in segments}
    assert connected_names == {p["name"] for p in points}
    assert all(annotations[p["name"]]["is_waypoint"] for p in points)


def test_supplement_is_inserted_only_once_without_explicit_exit():
    points = [
        {
            "name": "出发地",
            "kind": "start",
            "day": 1,
            "location": {"lat": 39.9, "lng": 116.39},
            "is_waypoint": True,
            "is_display_poi": True,
        },
        _point("主地点甲", 39.901, 116.391),
        _point("补充地点", 39.902, 116.392, supplement_recall=True),
        _point("主地点乙", 39.903, 116.393),
    ]

    reordered = step3_micro._reorder_by_proximity(points)
    names = [p["name"] for p in reordered]

    assert len(names) == len(set(names))
    assert names.count("补充地点") == 1


def test_multi_area_timeline_does_not_return_to_lunch_after_afternoon(monkeypatch):
    intent = SimpleNamespace(
        time_budget=1.0,
        duration="a full day",
        fixed_pois=[SimpleNamespace(name="王府井步行街"), SimpleNamespace(name="国贸")],
        plan_mode="planned",
        theme_profile=None,
        theme_label=None,
        micro_poi_keywords=[],
        theme_keywords=[],
        planned_waypoints=[
            SimpleNamespace(name="王府井步行街", resolved_name=None, time_slot="morning"),
            SimpleNamespace(name="国贸", resolved_name=None, time_slot="afternoon"),
            SimpleNamespace(name=None, resolved_name=None, time_slot="dinner"),
        ],
    )
    points = [
        {
            "name": "出发地",
            "kind": "start",
            "day": 1,
            "location": {"lat": 39.90, "lng": 116.30},
            "is_waypoint": True,
        },
        _point("王府井上午点", 39.91, 116.41, parent_anchor="王府井步行街"),
        {
            **_point("王府井午餐", 39.911, 116.411, parent_anchor="王府井步行街"),
            "kind": "meal",
            "display_slot": "lunch",
        },
        _point("国贸下午点", 39.912, 116.46, parent_anchor="国贸"),
        {
            **_point("国贸晚餐", 39.913, 116.461, parent_anchor="国贸"),
            "kind": "meal",
            "display_slot": "dinner",
        },
    ]

    points = step3_micro._apply_planned_time_slots(points, intent)
    reordered = step3_micro._reorder_by_proximity(points, intent)
    assert [p["name"] for p in reordered] == [p["name"] for p in points]
    assert reordered[1]["display_slot"] == "morning"
    assert reordered[3]["display_slot"] == "afternoon"

    async def fake_route(_intent, _transport, a, b):
        return {
            "transport": "步行",
            "duration_min": 3,
            "distance_km": 0.1,
            "polyline": [
                [a["location"]["lat"], a["location"]["lng"]],
                [b["location"]["lat"], b["location"]["lng"]],
            ],
        }

    monkeypatch.setattr(step3_micro, "_route_between", fake_route)
    segments, _ = asyncio.run(step3_micro._build_segments(intent, "步行", reordered))
    chain = [segments[0].from_poi, *[seg.to_poi for seg in segments]]

    assert chain == [p["name"] for p in points]
    assert ("国贸下午点", "王府井午餐") not in {
        (seg.from_poi, seg.to_poi) for seg in segments
    }
