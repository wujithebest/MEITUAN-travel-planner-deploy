from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from services.api_client import gaode_driving_route
from services.step4_output import _route_cache


def _same_point(p: dict[str, Any], op: dict[str, Any]) -> bool:
    pid = str(p.get("poi_id", ""))
    gid = str(p.get("gaode_poi_id", ""))
    pname = str(p.get("name", ""))
    op_id = str(op.get("poi_id", ""))

    if pid and pid == op_id:
        return True
    if op.get("gaode_poi_id") and gid == str(op.get("gaode_poi_id")):
        return True
    if op.get("poi_name") and pname == str(op.get("poi_name")):
        return True
    if ":" in op_id and pname == op_id.split(":")[0]:
        return True
    # v18: after_poi fields for add insertion
    if op.get("after_poi_id") and pid == str(op.get("after_poi_id")):
        return True
    if op.get("after_poi_name") and pname == str(op.get("after_poi_name")):
        return True
    if op.get("after_poi_location"):
        ploc = str(p.get("location", ""))
        if isinstance(ploc, dict):
            ploc = f"{ploc.get('lng',0)},{ploc.get('lat',0)}"
        if ploc and ploc == str(op.get("after_poi_location")):
            return True
    return False


def _normalize_loc(loc: Any) -> dict[str, float]:
    if isinstance(loc, dict):
        return {"lng": float(loc.get("lng", 0) or 0), "lat": float(loc.get("lat", 0) or 0)}
    if isinstance(loc, str) and "," in loc:
        lng, lat = loc.split(",", 1)
        return {"lng": float(lng), "lat": float(lat)}
    return {"lng": 0.0, "lat": 0.0}


def _normalize_new_poi(new_poi: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    base = base or {}
    loc = _normalize_loc(new_poi.get("location") or new_poi.get("lnglat") or base.get("location"))
    return {
        **base,
        "poi_id": new_poi.get("poi_id") or new_poi.get("gaode_poi_id") or base.get("poi_id") or str(uuid.uuid4()),
        "gaode_poi_id": new_poi.get("gaode_poi_id") or new_poi.get("poi_id") or base.get("gaode_poi_id") or "",
        "name": new_poi.get("name") or base.get("name") or "",
        "location": loc,
        "typecode": new_poi.get("typecode") or base.get("typecode") or "",
        "category": new_poi.get("category") or new_poi.get("typecode") or base.get("category") or "",
        "address": new_poi.get("address") or base.get("address") or "",
        "rating": new_poi.get("rating", base.get("rating")),
        "avg_cost": new_poi.get("avg_cost", base.get("avg_cost")),
        "photo_url": new_poi.get("photo_url") or base.get("photo_url") or "",
        "photo_source": new_poi.get("photo_source") or base.get("photo_source") or "",
        "kind": new_poi.get("kind") or base.get("kind") or "anchor_internal",
        "is_waypoint": True,
        "is_display_poi": True,
        "day": int(new_poi.get("day") or base.get("day") or 1),
        "display_slot": new_poi.get("display_slot") or base.get("display_slot") or "",
    }


def _insert_add_point(points: list[dict[str, Any]], new_point: dict[str, Any], op: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not points:
        return [new_point]

    target_day = int(new_point.get("day") or 1)
    insert_idx = len(points)
    op = op or {}

    # v18: 优先查找 after_poi_* 指定位置
    after_id = op.get("after_poi_id")
    after_name = op.get("after_poi_name")
    after_loc = op.get("after_poi_location")
    if after_id or after_name or after_loc:
        for i, pt in enumerate(points):
            if after_id and str(pt.get("poi_id", "") or pt.get("gaode_poi_id", "")) == str(after_id):
                insert_idx = i + 1
                break
            if after_name and str(pt.get("name", "")) == str(after_name):
                insert_idx = i + 1
                break
            if after_loc:
                ploc = str(pt.get("location", ""))
                if isinstance(ploc, dict):
                    ploc = f"{ploc.get('lng',0)},{ploc.get('lat',0)}"
                if ploc and ploc == str(after_loc):
                    insert_idx = i + 1
                    break
    else:
        # fallback: insert before dinner or at end of same day
        for i, pt in enumerate(points):
            if int(pt.get("day", 1) or 1) == target_day and pt.get("kind") == "meal" and pt.get("display_slot") == "dinner":
                insert_idx = i
                break
        else:
            same_day_indices = [
                i for i, pt in enumerate(points)
                if int(pt.get("day", 1) or 1) == target_day and pt.get("kind") not in ("hint",)
            ]
            if same_day_indices:
                insert_idx = same_day_indices[-1] + 1

    return points[:insert_idx] + [new_point] + points[insert_idx:]


async def apply_pipeline_replan(
    points: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    route_id: str | None = None,
) -> dict[str, Any]:
    next_points = [dict(p) for p in points]

    for op in operations:
        action = op.get("action")

        if action == "remove":
            next_points = [p for p in next_points if not _same_point(p, op)]

        elif action == "replace":
            new_poi = op.get("poi") or {}
            for i, p in enumerate(next_points):
                if _same_point(p, op):
                    next_points[i] = _normalize_new_poi(new_poi, p)
                    break

        elif action == "add":
            new_poi = op.get("poi") or {}
            next_points = _insert_add_point(next_points, _normalize_new_poi(new_poi), op)

    next_points = [p for p in next_points if p.get("kind") != "hint"]

    if not next_points:
        raise ValueError("操作后路线无剩余 POI")

    # v18: 重新按当前列表顺序编号 route_order / display_order
    disp_idx = 1
    for idx, pt in enumerate(next_points, start=1):
        pt["route_order"] = idx
        if pt.get("is_waypoint", True) and pt.get("kind") not in ("hint",):
            pt["display_order"] = disp_idx
            disp_idx += 1
        elif pt.get("display_order") is not None:
            pt["display_order"] = None

    day_waypoints: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for pt in next_points:
        if pt.get("is_waypoint", True) and pt.get("kind") != "hint":
            day_waypoints[int(pt.get("day", 1) or 1)].append(pt)

    new_segments: list[dict[str, Any]] = []
    for day, waypoints in sorted(day_waypoints.items()):
        # v18: 保持当前列表顺序，不再按旧 route_order 排序
        waypoints = list(waypoints)
        for i in range(len(waypoints) - 1):
            from_pt = waypoints[i]
            to_pt = waypoints[i + 1]
            loc_from = _normalize_loc(from_pt.get("location"))
            loc_to = _normalize_loc(to_pt.get("location"))
            origin = f"{loc_from['lng']},{loc_from['lat']}"
            destination = f"{loc_to['lng']},{loc_to['lat']}"

            segment = {
                "from_poi": from_pt.get("name", ""),
                "to_poi": to_pt.get("name", ""),
                "day_index": day,
                "transport": "自驾",
                "duration_min": 0,
                "distance_km": 0,
                "polyline": [],
                "period": to_pt.get("display_slot") or from_pt.get("display_slot") or "",
                "degraded": False,
                "polyline_source": "",
                "route_error": "",
            }
            try:
                route = await gaode_driving_route(origin, destination)
                if route and route.get("polyline"):
                    segment["polyline"] = [[c[1], c[0]] for c in route["polyline"]]
                    segment["duration_min"] = route.get("duration_min", 0)
                    segment["distance_km"] = route.get("distance_km", 0)
                else:
                    segment["degraded"] = True
                    segment["polyline_source"] = "route_api_failed"
                    segment["route_error"] = "真实路线获取失败，已降级显示"
            except Exception as exc:
                segment["degraded"] = True
                segment["polyline_source"] = "route_api_failed"
                segment["route_error"] = str(exc)
            new_segments.append(segment)

    new_route_id = route_id or str(uuid.uuid4())
    _route_cache[new_route_id] = {"points": next_points, "segments": new_segments}
    return {"route": {"points": next_points, "segments": new_segments}, "route_id": new_route_id}
