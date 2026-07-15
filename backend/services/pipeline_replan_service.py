from __future__ import annotations

import math
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


def _normalize_loc_safe(loc: Any) -> dict[str, float] | None:
    """Safe version for duplicate detection — returns None on invalid input."""
    try:
        return _normalize_loc(loc)
    except (ValueError, TypeError):
        return None

def _normalize_loc(loc: Any) -> dict[str, float]:
    """v20: Strict validation — reject 0,0, NaN, out-of-range coordinates."""
    if isinstance(loc, dict):
        lng = float(loc.get("lng", loc.get("longitude", 0)) or 0)
        lat = float(loc.get("lat", loc.get("latitude", 0)) or 0)
    elif isinstance(loc, str) and "," in loc:
        lng_str, lat_str = loc.split(",", 1)
        lng = float(lng_str); lat = float(lat_str)
    else:
        raise ValueError(f"Unsupported location format: {loc!r}")

    if lng == 0.0 and lat == 0.0:
        raise ValueError(f"Invalid coordinates (0,0): {loc!r}")
    if not (-180 <= lng <= 180) or not (-90 <= lat <= 90):
        raise ValueError(f"Coordinates out of range: lng={lng} lat={lat}")
    if not (math.isfinite(lng) and math.isfinite(lat)):
        raise ValueError(f"Non-finite coordinates: lng={lng} lat={lat}")

    return {"lng": lng, "lat": lat}


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


def _is_curated_fixed_route_candidate(route_id: str | None, new_poi: dict[str, Any]) -> bool:
    """Recognize restored candidates even when the frontend omits metadata."""
    if route_id != "fixed-literary-photo-cafe-hengji-v1":
        return False
    if str(new_poi.get("candidate_source") or "") == "fixed_route_restored":
        return True

    candidate_id = str(
        new_poi.get("poi_id") or new_poi.get("gaode_poi_id") or ""
    ).strip()
    candidate_name = str(new_poi.get("name") or "").strip()
    if not candidate_id and not candidate_name:
        return False

    try:
        from services.fixed_route_service import get_fixed_route

        snapshot = get_fixed_route("literary-photo-cafe") or {}
        candidates = (snapshot.get("route_data") or {}).get("candidate_points") or []
    except Exception as exc:  # pragma: no cover - defensive fallback for mutations
        print(f"[PipelineMutationAudit] fixed candidate lookup unavailable: {exc}")
        return False

    for candidate in candidates:
        known_id = str(
            candidate.get("poi_id") or candidate.get("gaode_poi_id") or ""
        ).strip()
        known_name = str(candidate.get("name") or "").strip()
        if candidate_id and known_id and candidate_id == known_id:
            return True
        if candidate_name and known_name and candidate_name == known_name:
            return True
    return False


def _normalize_polyline_order(
    raw: list[list[float]], loc_from: dict[str, float], loc_to: dict[str, float]
) -> list[list[float]]:
    """Auto-detect the provider order and normalize to backend [lat,lng].

    Uses endpoint distance matching: if swapping produces coordinates closer to the
    known POI locations, the raw data is in [lat,lng] order and must be swapped.
    """
    if not raw or len(raw) < 2:
        return []
    f0, f1 = float(loc_from.get("lng", 0)), float(loc_from.get("lat", 0))
    t0, t1 = float(loc_to.get("lng", 0)), float(loc_to.get("lat", 0))

    # Distance from first raw point to from_location in both orderings
    r0, r1 = raw[0][0], raw[0][1]
    d_as_lnglat = ((r0 - f0) * 111.32 * abs(math.cos(math.radians((f1 + r1) / 2)))) ** 2 + ((r1 - f1) * 111.32) ** 2
    d_as_latlng = ((r1 - f0) * 111.32 * abs(math.cos(math.radians((f1 + r0) / 2)))) ** 2 + ((r0 - f1) * 111.32) ** 2

    if d_as_latlng < d_as_lnglat:
        return [[float(a), float(b)] for a, b in raw]
    return [[float(b), float(a)] for a, b in raw]


def _latlng_distance_m(point: list[float], location: dict[str, float]) -> float:
    """Distance from a [lat,lng] point to a normalized POI location."""
    lat1, lng1 = math.radians(point[0]), math.radians(point[1])
    lat2, lng2 = math.radians(location["lat"]), math.radians(location["lng"])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def _insert_add_point(
    points: list[dict[str, Any]],
    new_point: dict[str, Any],
    op: dict[str, Any] | None = None,
    *,
    allow_curated_candidate_overlap: bool = False,
) -> list[dict[str, Any]]:
    if not points:
        return [new_point]

    # v20: Duplicate detection — prevent adding the same POI twice
    new_pid = str(new_point.get("poi_id") or new_point.get("gaode_poi_id", ""))
    new_name = str(new_point.get("name", "")).strip()
    new_loc = _normalize_loc_safe(new_point.get("location"))
    for pt in points:
        existing_pid = str(pt.get("poi_id") or pt.get("gaode_poi_id", ""))
        if new_pid and existing_pid and new_pid == existing_pid:
            print(f"[PipelineMutationAudit] duplicate poi_id={new_pid} — skipping add")
            return points  # already present
        if new_name and str(pt.get("name", "")).strip() == new_name:
            print(f"[PipelineMutationAudit] duplicate name={new_name} — skipping add")
            return points
        if new_loc:
            existing_loc = _normalize_loc_safe(pt.get("location"))
            if (
                existing_loc
                and abs(new_loc["lat"] - existing_loc["lat"]) < 0.0001
                and abs(new_loc["lng"] - existing_loc["lng"]) < 0.0001
                and not allow_curated_candidate_overlap
            ):
                print(f"[PipelineMutationAudit] duplicate location ({new_loc['lng']},{new_loc['lat']}) — skipping add")
                return points
            if (
                existing_loc
                and abs(new_loc["lat"] - existing_loc["lat"]) < 0.0001
                and abs(new_loc["lng"] - existing_loc["lng"]) < 0.0001
                and allow_curated_candidate_overlap
            ):
                print(
                    f"[PipelineMutationAudit] curated candidate overlap allowed "
                    f"({new_loc['lng']},{new_loc['lat']})"
                )

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
    existing_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    import time as _time
    _t0 = _time.monotonic()
    next_points = [dict(p) for p in points]
    audit_log: list[dict[str, Any]] = []

    # ── Track which indices were mutated ──
    mutated_indices: set[int] = set()

    for op in operations:
        action = op.get("action")
        pre_count = len(next_points)

        if action == "remove":
            found_idx = -1
            for i, p in enumerate(next_points):
                if _same_point(p, op):
                    found_idx = i
                    break
            if found_idx >= 0:
                mutated_indices.add(found_idx)
                next_points.pop(found_idx)
            audit_log.append({
                "action": action, "requested_target": op.get("poi_id") or op.get("poi_name"),
                "applied": found_idx >= 0, "before_point_count": pre_count, "after_point_count": len(next_points),
                "failure_reason": "" if found_idx >= 0 else "target_not_found",
            })

        elif action == "replace":
            new_poi = op.get("poi") or {}
            found = False
            for i, p in enumerate(next_points):
                if _same_point(p, op):
                    next_points[i] = _normalize_new_poi(new_poi, p)
                    mutated_indices.add(i)
                    found = True
                    break
            audit_log.append({
                "action": action, "requested_target": op.get("poi_id") or op.get("poi_name"),
                "applied": found, "before_point_count": pre_count, "after_point_count": len(next_points),
                "failure_reason": "" if found else "target_not_found",
            })

        elif action == "add":
            new_poi = op.get("poi") or {}
            prev_len = len(next_points)
            allow_curated_candidate_overlap = _is_curated_fixed_route_candidate(route_id, new_poi)
            next_points = _insert_add_point(
                next_points,
                _normalize_new_poi(new_poi),
                op,
                allow_curated_candidate_overlap=allow_curated_candidate_overlap,
            )
            if len(next_points) > prev_len:
                # Mark the inserted index
                for i, p in enumerate(next_points):
                    if p.get("name") == new_poi.get("name") or p.get("poi_id") == new_poi.get("poi_id"):
                        mutated_indices.add(i)
                        break
            audit_log.append({
                "action": action, "requested_target": new_poi.get("name") or op.get("poi_id"),
                "applied": len(next_points) > prev_len, "before_point_count": prev_len, "after_point_count": len(next_points),
                "failure_reason": "" if len(next_points) > prev_len else "insert_failed",
            })

    for entry in audit_log:
        print(
            f"[PipelineMutationAudit] route_id={route_id or 'none'} "
            f"action={entry['action']} applied={entry['applied']} "
            f"target={entry['requested_target']} "
            f"before={entry['before_point_count']} after={entry['after_point_count']} "
            f"failure_reason={entry['failure_reason']}"
        )

    next_points = [p for p in next_points if p.get("kind") != "hint"]
    if not next_points:
        raise ValueError("操作后路线无剩余 POI")

    # Re-number order
    disp_idx = 1
    for idx, pt in enumerate(next_points, start=1):
        pt["route_order"] = idx
        if pt.get("is_waypoint", True) and pt.get("kind") not in ("hint",):
            pt["display_order"] = disp_idx
            disp_idx += 1
        elif pt.get("display_order") is not None:
            pt["display_order"] = None

    # Group by day
    day_waypoints: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for pt in next_points:
        if pt.get("is_waypoint", True) and pt.get("kind") != "hint":
            day_waypoints[int(pt.get("day", 1) or 1)].append(pt)

    # ── v22: Only recalculate affected segments ──
    # Build a set of (from_name, to_name) pairs that are 'affected' by mutations.
    # A segment is affected if either endpoint index is in mutated_indices, or if
    # the segment's endpoints don't exist in the old segments (due to add/remove).
    affected_pairs: set[tuple[str, str]] = set()
    for day, waypoints in sorted(day_waypoints.items()):
        waypoints = list(waypoints)
        for i in range(len(waypoints) - 1):
            fn = waypoints[i].get("name", "")
            tn = waypoints[i + 1].get("name", "")
            is_affected = False
            # Check if this segment connects to/from a mutated point
            for j in range(i, i + 2):
                if j in mutated_indices:
                    is_affected = True
                    break
            # Also mark as affected if we can't find a matching old segment
            if not is_affected and existing_segments:
                found_old = any(
                    s.get("from_poi") == fn and s.get("to_poi") == tn
                    for s in existing_segments
                )
                if not found_old:
                    is_affected = True
            if is_affected:
                affected_pairs.add((fn, tn))

    new_segments: list[dict[str, Any]] = []
    affected_count = 0
    reused_count = 0

    for day, waypoints in sorted(day_waypoints.items()):
        waypoints = list(waypoints)
        for i in range(len(waypoints) - 1):
            from_pt = waypoints[i]
            to_pt = waypoints[i + 1]
            fn = from_pt.get("name", "")
            tn = to_pt.get("name", "")
            needs_recalc = (fn, tn) in affected_pairs

            if not needs_recalc and existing_segments:
                # Try to reuse existing segment
                reused = None
                for s in existing_segments:
                    if s.get("from_poi") == fn and s.get("to_poi") == tn:
                        reused = dict(s)
                        break
                if reused:
                    new_segments.append(reused)
                    reused_count += 1
                    continue

            # ── Must recalculate this segment ──
            affected_count += 1
            loc_from = _normalize_loc(from_pt.get("location"))
            loc_to = _normalize_loc(to_pt.get("location"))
            origin = f"{loc_from['lng']},{loc_from['lat']}"
            destination = f"{loc_to['lng']},{loc_to['lat']}"

            segment = {
                "from_poi": fn, "to_poi": tn, "day_index": day,
                "transport": "自驾", "duration_min": 0, "distance_km": 0,
                "polyline": [], "period": to_pt.get("display_slot") or from_pt.get("display_slot") or "",
                "degraded": False, "polyline_source": "", "route_error": "",
            }
            try:
                route = await gaode_driving_route(origin, destination)
                if route and route.get("polyline"):
                    _raw = route["polyline"]
                    _norm_pl = _normalize_polyline_order(_raw, loc_from, loc_to)
                    _first = _norm_pl[0] if _norm_pl else None
                    _last = _norm_pl[-1] if _norm_pl else None
                    _first_distance = _latlng_distance_m(_first, loc_from) if _first else float("inf")
                    _last_distance = _latlng_distance_m(_last, loc_to) if _last else float("inf")
                    _first_ok = bool(_first and -90 <= _first[0] <= 90 and -180 <= _first[1] <= 180 and math.isfinite(_first[0]) and math.isfinite(_first[1]) and _first_distance <= 2000)
                    _last_ok = bool(_last and -90 <= _last[0] <= 90 and -180 <= _last[1] <= 180 and math.isfinite(_last[0]) and math.isfinite(_last[1]) and _last_distance <= 2000)
                    if _first_ok and _last_ok:
                        segment["polyline"] = _norm_pl
                    else:
                        segment["degraded"] = True
                        segment["polyline_source"] = "invalid_coordinates"
                        segment["route_error"] = "polyline coordinates out of valid range"
                        segment["polyline"] = []
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

    _elapsed = (_time.monotonic() - _t0) * 1000
    print(
        f"[PipelineReplan] affected_segments={affected_count} "
        f"reused_segments={reused_count} "
        f"elapsed_ms={_elapsed:.0f} "
        f"total_segments={len(new_segments)}"
    )

    new_route_id = route_id or str(uuid.uuid4())
    _route_cache[new_route_id] = {"points": next_points, "segments": new_segments}
    return {
        "route": {"points": next_points, "segments": new_segments},
        "route_id": new_route_id,
        "mutation_audit": audit_log,
    }
