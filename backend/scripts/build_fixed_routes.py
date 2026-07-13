"""Build the six immutable demo route snapshots.

The generated JSON files are served read-only by the fixed-route endpoint.
This script is intentionally offline and deterministic: clicking a demo case
must never run the normal LLM/POI pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "fixed_routes"
ORIGIN = {
    "label": "北京恒基伟业大厦",
    "city": "北京市",
    "lat": 40.008744,
    "lng": 116.488462,
}


def point(
    name: str,
    lng: float,
    lat: float,
    *,
    kind: str = "anchor",
    slot: str = "morning",
    address: str = "北京市",
    category: str = "风景名胜",
    typecode: str = "110000",
    rating: float | None = 4.5,
    reason: str = "与本次路线主题匹配",
) -> dict[str, Any]:
    return {
        "poi_id": f"fixed-{name}",
        "gaode_poi_id": f"fixed-{name}",
        "name": name,
        "location": f"{lng},{lat}",
        "kind": kind,
        "category": category,
        "typecode": typecode,
        "address": address,
        "rating": rating,
        "day": 1,
        "display_slot": slot,
        "is_waypoint": True,
        "is_display_poi": True,
        "display_order": 0,
        "route_order": 0,
        "recommend_reason": reason,
        "matched_keywords": [],
        "tags": [],
        "parent_anchor": "",
        "visit_duration_min": 60,
    }


def build_snapshot(
    fixture_id: str,
    prompt_text: str,
    title: str,
    points: list[dict[str, Any]],
    keywords: list[str],
) -> dict[str, Any]:
    for idx, item in enumerate(points):
        item["display_order"] = idx if item["kind"] != "start" else 0
        item["route_order"] = idx
        item["matched_keywords"] = keywords if item["kind"] != "start" else []
        item["tags"] = keywords if item["kind"] != "start" else []

    segments: list[dict[str, Any]] = []
    for idx, (source, target) in enumerate(zip(points, points[1:]), start=1):
        source_lng, source_lat = map(float, source["location"].split(","))
        target_lng, target_lat = map(float, target["location"].split(","))
        distance = round(max(0.25, ((target_lng - source_lng) ** 2 + (target_lat - source_lat) ** 2) ** 0.5 * 92), 2)
        segments.append({
            "segment_order": idx,
            "day_index": 1,
            "from_poi": source["name"],
            "to_poi": target["name"],
            "transport": "驾车",
            "duration_min": max(4, int(distance * 4.5)),
            "distance_km": distance,
            "polyline": f"{source['location']};{target['location']}",
            "polyline_source": "fixed_snapshot",
            "period": target.get("display_slot", "morning"),
            "display_slot": target.get("display_slot", "morning"),
            "color": "#E67E22" if idx % 2 else "#2980B9",
        })

    markers = []
    for item in points:
        markers.append({
            "poi_id": item["poi_id"],
            "gaode_poi_id": item["gaode_poi_id"],
            "name": item["name"],
            "location": item["location"],
            "type": "start" if item["kind"] == "start" else ("meal" if item["kind"] == "meal" else "waypoint"),
            "kind": item["kind"],
            "day_index": 1,
            "display_order": item["display_order"],
            "is_display_poi": True,
            "address": item["address"],
            "category": item["category"],
            "rating": item["rating"],
            "matched_keywords": item["matched_keywords"],
            "tags": item["tags"],
        })

    panel_slots: dict[str, list[dict[str, Any]]] = {}
    for item in points:
        panel_slots.setdefault(item["display_slot"], []).append({
            "order": item["display_order"],
            "name": item["name"],
            "kind": item["kind"],
            "day_index": 1,
            "slot": item["display_slot"],
            "location": item["location"],
            "is_start": item["kind"] == "start",
            "transport_text": "起点" if item["kind"] == "start" else "驾车",
            "recommend_reason": item["recommend_reason"],
            "address": item["address"],
            "rating": item["rating"],
            "poi_id": item["poi_id"],
            "gaode_poi_id": item["gaode_poi_id"],
            "typecode": item["typecode"],
            "category": item["category"],
            "matched_keywords": item["matched_keywords"],
            "tags": item["tags"],
        })

    slot_meta = {
        "morning": ("上午", "09:00-12:00"),
        "lunch": ("午餐", "12:00-13:30"),
        "afternoon": ("下午", "13:30-18:00"),
        "dinner": ("晚餐", "18:00-19:30"),
        "evening": ("夜间", "19:30-21:00"),
    }
    panel_days = [{
        "day_index": 1,
        "slots": [
            {
                "type": slot,
                "label": slot_meta.get(slot, (slot, ""))[0],
                "time_range": slot_meta.get(slot, (slot, ""))[1],
                "pois": pois,
                "recommend_reason": "、".join(keywords),
            }
            for slot, pois in panel_slots.items()
        ],
    }]

    poi_details = {
        item["poi_id"]: {
            "poi_id": item["poi_id"],
            "gaode_poi_id": item["gaode_poi_id"],
            "name": item["name"],
            "location": item["location"],
            "address": item["address"],
            "category": item["category"],
            "typecode": item["typecode"],
            "rating": item["rating"],
            "recommend_reason": item["recommend_reason"],
            "matched_keywords": item["matched_keywords"],
            "tags": item["tags"],
        }
        for item in points
    }

    candidate_points = [
        {"name": f"{keywords[0]}备选点{idx}", "kind": "candidate", "matched_keywords": keywords}
        for idx in range(1, 5)
    ]
    assistant_message = f"【{title}】\n\n已从北京恒基伟业大厦出发，为你加载预先生成的固定路线。\n命中：{'｜'.join(keywords)}\n路线共 {len(points) - 1} 个游览点，按顺路顺序编排。"

    return {
        "id": fixture_id,
        "prompt": prompt_text,
        "title": title,
        "origin": ORIGIN,
        "route_id": f"fixed-{fixture_id}-hengji-v1",
        "assistant_message": assistant_message,
        "route_data": {
            "route_id": f"fixed-{fixture_id}-hengji-v1",
            "points": points,
            "segments": segments,
            "candidate_points": candidate_points,
            "route_recommend_reason": "、".join(keywords),
            "plan_mode": "fixed",
            "total_days": 1,
        },
        "map_route_data": {
            "markers": markers,
            "polylines": segments,
            "center": [ORIGIN["lng"], ORIGIN["lat"]],
        },
        "panel_days": panel_days,
        "complete_plan": {
            "city": "北京市",
            "duration": "a full day",
            "time_budget": 1.0,
            "plan_mode": "fixed",
            "request_text": prompt_text,
            "parsed_intent": {"raw_text": prompt_text, "city": "北京市"},
        },
        "poi_details": poi_details,
        "summary": {
            "poi_count": len(points) - 1,
            "candidate_count": len(candidate_points),
            "distance": round(sum(s["distance_km"] for s in segments), 2),
            "duration": sum(s["duration_min"] for s in segments),
            "origin": ORIGIN["label"],
        },
    }


ROUTES = [
    ("literary-photo-cafe", "帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点", "北京文艺拍照咖啡路线", [
        point(ORIGIN["label"], ORIGIN["lng"], ORIGIN["lat"], kind="start", slot="morning", category="起点", typecode=""),
        point("望京公园", 116.4930, 40.0020, reason="适合拍照、文艺路线、节奏轻松"),
        point("798艺术区", 116.4958, 39.9848, reason="适合拍照、文艺路线"),
        point("地球咖啡馆", 116.4972, 39.9836, kind="meal", slot="lunch", category="餐饮", typecode="050000", reason="咖啡馆、特色小店"),
        point("草场地艺术区", 116.5125, 39.9880, slot="afternoon", reason="文艺路线、适合拍照"),
        point("北京798小店街", 116.4980, 39.9819, slot="afternoon", category="购物", typecode="060000", reason="特色小店、节奏轻松"),
        point("将府公园", 116.5150, 39.9860, slot="evening", reason="适合拍照、节奏轻松"),
    ], ["咖啡", "拍照", "文艺路线", "咖啡馆", "特色小店", "节奏轻松"]),
    ("tiananmen-forbidden-city-jingshan", "想去天安门和故宫附近转转，中午吃顿地道的北京菜，下午去景山公园看日落", "北京天安门故宫景山一日游", [
        point(ORIGIN["label"], ORIGIN["lng"], ORIGIN["lat"], kind="start", slot="morning", category="起点", typecode=""),
        point("天安门广场", 116.3975, 39.9037, reason="天安门、附近、顺路"),
        point("故宫博物院-午门", 116.3970, 39.9163, reason="故宫、附近、顺路"),
        point("地道北京菜餐厅", 116.3962, 39.9210, kind="meal", slot="lunch", category="餐饮", typecode="050000", reason="地道北京菜、午餐"),
        point("景山公园", 116.3968, 39.9256, slot="afternoon", reason="景山公园、下午、看日落"),
        point("景山公园-万春亭", 116.3965, 39.9272, slot="afternoon", reason="看日落、景山公园"),
        point("北海公园东门", 116.3932, 39.9250, slot="evening", reason="附近、顺路"),
    ], ["景山公园", "天安门", "故宫", "地道北京菜", "附近", "看日落"]),
    ("nearby-food-walk", "待会儿去附近逛逛，找一家好吃的，再散散步。", "北京恒基伟业大厦附近逛吃散步", [
        point(ORIGIN["label"], ORIGIN["lng"], ORIGIN["lat"], kind="start", slot="morning", category="起点", typecode=""),
        point("北小河公园", 116.4870, 40.0160, reason="附近、逛逛、散步"),
        point("望京SOHO", 116.4800, 40.0010, reason="附近、逛逛"),
        point("望京好吃餐厅", 116.4748, 40.0018, kind="meal", slot="lunch", category="餐饮", typecode="050000", reason="附近、好吃的"),
        point("望京公园", 116.4930, 40.0020, slot="afternoon", reason="附近、散散步"),
        point("望京小街", 116.4755, 40.0060, slot="afternoon", category="购物", typecode="060000", reason="附近、逛逛"),
        point("北小河沿岸步道", 116.4860, 40.0145, slot="evening", reason="附近、散散步"),
    ], ["附近", "逛逛", "好吃的", "散散步"]),
    ("spicy-compatible-restaurant", "明天朋友来北京找我，我不吃辣但他想吃川菜，帮我找一家两边都能接受的餐厅，吃完想在附近散散步", "北京附近口味兼容短途游", [
        point(ORIGIN["label"], ORIGIN["lng"], ORIGIN["lat"], kind="start", slot="morning", category="起点", typecode=""),
        point("和牛家食堂", 116.4745, 40.0018, kind="meal", slot="lunch", category="餐饮", typecode="050000", reason="不吃辣与川菜口味兼容"),
        point("人民公社", 116.4755, 40.0030, slot="afternoon", category="餐饮", typecode="050000", reason="附近餐厅备选"),
        point("望京SOHO", 116.4800, 40.0010, slot="afternoon", reason="餐后附近散步"),
        point("望京公园", 116.4930, 40.0020, slot="afternoon", reason="餐后附近散步"),
        point("北小河公园", 116.4870, 40.0160, slot="evening", reason="附近散步"),
        point("北小河沿岸步道", 116.4860, 40.0145, slot="evening", reason="餐后散散步"),
    ], ["口味兼容", "川菜", "不吃辣", "餐厅", "附近散步"]),
    ("literary-river-night-view", "下午推荐一条北京文艺路线，晚饭想吃点清淡的，吃完去河边走走，最后找个拍夜景的地方", "北京文艺河边夜景路线", [
        point(ORIGIN["label"], ORIGIN["lng"], ORIGIN["lat"], kind="start", slot="afternoon", category="起点", typecode=""),
        point("798艺术区", 116.4958, 39.9848, slot="afternoon", reason="北京文艺路线、适合拍照"),
        point("将府公园", 116.5150, 39.9860, slot="afternoon", reason="文艺路线、轻松"),
        point("清淡晚餐餐厅", 116.5060, 39.9930, kind="meal", slot="dinner", category="餐饮", typecode="050000", reason="晚饭、清淡"),
        point("亮马河国际风情水岸", 116.4660, 39.9500, slot="evening", reason="河边散步"),
        point("蓝色港湾", 116.4690, 39.9505, slot="evening", reason="河边散步、文艺"),
        point("亮马河夜景观景点", 116.4615, 39.9480, slot="evening", reason="拍夜景"),
    ], ["文艺路线", "清淡", "河边散步", "夜景", "拍照"]),
    ("beihai-roast-duck-sanlihe", "帮我规划一条路线，先去北海公园走走，中午吃顿烤鸭，下午去三里河公园。", "北京北海公园烤鸭三里河公园一日游", [
        point(ORIGIN["label"], ORIGIN["lng"], ORIGIN["lat"], kind="start", slot="morning", category="起点", typecode=""),
        point("北海公园-白塔", 116.3910, 39.9250, reason="北海公园、先去走走"),
        point("北海公园-九龙壁", 116.3865, 39.9255, reason="北海公园、顺路"),
        point("北海附近烤鸭店", 116.3950, 39.9205, kind="meal", slot="lunch", category="餐饮", typecode="050000", reason="中午、烤鸭"),
        point("天桥艺术中心", 116.3975, 39.8910, slot="afternoon", reason="前往三里河公园途中"),
        point("三里河公园", 116.3895, 39.8845, slot="afternoon", reason="下午、三里河公园"),
        point("三里河公园水岸步道", 116.3910, 39.8835, slot="evening", reason="三里河公园、散步"),
    ], ["北海公园", "烤鸭", "三里河公园", "先后顺序", "顺路"]),
]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for fixture_id, prompt_text, title, points, keywords in ROUTES:
        snapshot = build_snapshot(fixture_id, prompt_text, title, points, keywords)
        filepath = OUTPUT_DIR / f"{fixture_id}.json"
        filepath.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {filepath} ({len(points) - 1} POIs, {len(snapshot['route_data']['segments'])} segments)")


if __name__ == "__main__":
    main()
