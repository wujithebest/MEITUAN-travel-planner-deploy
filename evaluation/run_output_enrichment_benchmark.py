"""Exercise dynamic SSE output without changing fixture or frontend contracts.

Usage:
    python evaluation/run_output_enrichment_benchmark.py planned
    python evaluation/run_output_enrichment_benchmark.py exploratory
"""

from __future__ import annotations

import json
import sys
import time

import httpx


CASES = {
    "planned": "待会儿找一家餐馆，吃完饭再找一下咖啡店，帮我规划一下路线",
    "milk_tea": "附近找一家餐厅，再找一家奶茶店",
    "exploratory": "北京适合拍照的文艺路线推荐，有咖啡馆和特色小店，节奏轻松一些。",
}

GUEST_PROFILE = {
    "nickname": "性能验证游客",
    "activity_pref_tag": ["美食探店", "艺术展览", "摄影打卡"],
    "food_pref_tag": [],
    "permanent_city": ["北京市", "朝阳区"],
    "permanent_city_coord": {"lat": 40.008561, "lng": 116.48788},
    "home_location": {
        "lat": 40.008561,
        "lng": 116.48788,
        "label": "北京恒基伟业大厦",
        "city": "北京市",
        "district": "朝阳区",
    },
    "budget_per_capita": 100,
}


def _sse_complete(case_name: str) -> dict:
    payload = {
        "message": CASES[case_name],
        "user_id": f"output-enrichment-benchmark-{case_name}",
        "plan_mode": "auto",
        "guest_profile": GUEST_PROFILE,
        "client_timezone": "Asia/Shanghai",
    }
    started = time.perf_counter()
    event = ""
    complete: dict | None = None
    with httpx.Client(timeout=httpx.Timeout(370.0, connect=10.0)) as client:
        with client.stream(
            "POST",
            "http://localhost:8000/api/meituan/chat/stream",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event == "complete":
                    complete = json.loads(line[6:])
                    break
    if complete is None:
        raise RuntimeError("SSE stream ended without a complete event")
    complete["wall_clock_ms"] = round((time.perf_counter() - started) * 1000)
    return complete


def _summary(payload: dict) -> dict:
    content = payload.get("content", {}) if isinstance(payload, dict) else {}
    route_data = content.get("route_data", {}) if isinstance(content, dict) else {}
    points = route_data.get("points", []) if isinstance(route_data, dict) else []
    display = [
        point for point in points
        if isinstance(point, dict)
        and point.get("kind") not in {"start", "origin", "hint", "free_explore", "route_only"}
        and point.get("is_waypoint", True) is not False
    ]
    segments = route_data.get("segments", []) if isinstance(route_data, dict) else []
    return {
        "wall_clock_ms": payload.get("wall_clock_ms"),
        "stats": payload.get("stats", {}),
        "display_poi_count": len(display),
        "photo_count": sum(bool(point.get("photo_url")) for point in display),
        "poi_reason_count": sum(bool(point.get("recommend_reason")) for point in display),
        "route_reason_present": bool(route_data.get("route_recommend_reason")) or any(
            bool(point.get("route_recommend_reason")) for point in display
        ),
        "segment_count": len(segments) if isinstance(segments, list) else 0,
        "polyline_segment_count": sum(
            bool(segment.get("polyline")) for segment in segments if isinstance(segment, dict)
        ) if isinstance(segments, list) else 0,
        "poi_names": [str(point.get("name", "")) for point in display],
    }


if __name__ == "__main__":
    case = sys.argv[1] if len(sys.argv) > 1 else "planned"
    if case not in CASES:
        raise SystemExit(f"Unknown case: {case}. Choose one of: {', '.join(CASES)}")
    print(json.dumps(_summary(_sse_complete(case)), ensure_ascii=False, indent=2))
