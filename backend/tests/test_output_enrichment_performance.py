from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import poi_photo_service, reason_generator


def _intent() -> SimpleNamespace:
    return SimpleNamespace(
        raw_keywords=["拍照", "文艺路线", "咖啡馆"],
        food_pref_keywords=[],
        other_constraints=["节奏轻松"],
        plan_mode="exploratory",
        primary_query="",
        theme_profile="art_culture_lifestyle",
        duration="a full day",
        budget_per_capita=100,
        transport_hint="步行",
        proximity_requested=False,
        search_area_label="",
    )


def _display_points() -> list[dict]:
    return [
        {
            "poi_id": "art-1",
            "name": "测试艺术空间",
            "kind": "anchor_internal",
            "category": "art",
            "typecode": "140200",
            "display_slot": "morning",
            "is_display_poi": True,
            "is_waypoint": True,
            "matched_facets": ["photo_checkin", "art_culture_lifestyle"],
            "matched_keywords": ["拍照", "文艺路线"],
        },
        {
            "poi_id": "cafe-1",
            "name": "测试咖啡馆",
            "kind": "cafe",
            "category": "cafe",
            "typecode": "050400",
            "display_slot": "afternoon",
            "is_display_poi": True,
            "is_waypoint": True,
            "matched_facets": ["cafe_stop"],
            "matched_keywords": ["咖啡馆", "节奏轻松"],
        },
    ]


def test_reason_timeout_keeps_route_and_poi_reason_fields(monkeypatch) -> None:
    async def fail_llm(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(reason_generator, "call_llm", fail_llm)
    points = _display_points()
    result = asyncio.run(
        reason_generator.generate_exploratory_reasons(
            points, _intent(), SimpleNamespace(), city="北京市", user_request="文艺拍照咖啡路线",
        )
    )

    assert all(point["recommend_reason"] for point in result)
    assert all(point["short_recommend_reason"] for point in result)
    assert all(point["_route_recommend_reason"] for point in result)
    assert "咖啡馆" in result[1]["recommend_reason"]


def test_photo_enrichment_is_bounded_parallel_not_global_serial(monkeypatch) -> None:
    async def slow_detail(poi_id: str, **_kwargs):
        await asyncio.sleep(0.08)
        return {"photos": [{"url": f"https://img.example/{poi_id}.jpg"}]}

    poi_photo_service._photo_cache.clear()
    poi_photo_service._photo_inflight.clear()
    poi_photo_service._photo_semaphore = None
    monkeypatch.setattr(poi_photo_service, "gaode_place_detail", slow_detail)

    points = [
        {"poi_id": f"poi-{index}", "gaode_poi_id": f"poi-{index}", "name": f"地点{index}", "kind": "visit"}
        for index in range(3)
    ]
    started = time.monotonic()
    result = asyncio.run(poi_photo_service.enrich_points_with_photos(points, city="北京市"))
    elapsed = time.monotonic() - started

    assert elapsed < 0.18
    assert [point["photo_source"] for point in result] == ["gaode", "gaode", "gaode"]


def test_photo_lookup_is_deduplicated_for_same_poi(monkeypatch) -> None:
    calls = 0

    async def detail_once(poi_id: str, **_kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"photos": [{"url": f"https://img.example/{poi_id}.jpg"}]}

    poi_photo_service._photo_cache.clear()
    poi_photo_service._photo_inflight.clear()
    poi_photo_service._photo_semaphore = None
    monkeypatch.setattr(poi_photo_service, "gaode_place_detail", detail_once)

    async def run() -> list[dict]:
        return await asyncio.gather(*[
            poi_photo_service.resolve_poi_photo(poi_id="same", poi_name="同一地点")
            for _ in range(3)
        ])

    result = asyncio.run(run())
    assert calls == 1
    assert all(item["photo_url"] == "https://img.example/same.jpg" for item in result)
