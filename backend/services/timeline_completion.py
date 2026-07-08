"""
v21: Timeline completion — auto-insert meals and gap-filling activities.
All pipeline modes call complete_route_timeline() before _build_segments().
"""
from __future__ import annotations
from typing import Any
from .day_slots import MEAL_WINDOWS
from .utils import haversine_km, normalize_location, coord_to_param


MEAL_VISIT_MINUTES = {"breakfast": 30, "lunch": 60, "dinner": 75}
MEAL_OVERLAP_MIN = 0.5  # hours overlap with meal window

# Gap-filling thresholds
GAP_MIN_MINUTES = 30       # below this, don't fill
GAP_LIGHT_MAX = 60         # light entertainment
GAP_STANDARD_MAX = 120     # standard entertainment
GAP_LARGE_MIN = 120        # large entertainment/culture

# Entertainment categories by gap size
LIGHT_GAP_KEYWORDS = ["书店", "文创店", "观景点", "公园", "街区散步"]
STANDARD_GAP_KEYWORDS = ["美术馆", "博物馆", "商业街", "游戏厅", "运动体验馆", "特色街区"]


async def complete_route_timeline(
    route_points: list[dict],
    parsed_intent: Any,
    user_profile: Any,
    city: str = "",
) -> list[dict]:
    """Auto-insert meals and gap-filling activities into the route timeline.

    Called after final POIs are determined, deduplicated, and spatially ordered,
    but BEFORE _build_segments() generates the final route polylines.
    """
    if not route_points or len(route_points) < 2:
        return route_points

    # ── 1. Build timeline ──
    timeline = _build_timeline(route_points, parsed_intent)

    # ── 2. Detect meals needed ──
    meals_needed = _detect_meals_needed(timeline, parsed_intent)

    # ── 3. Insert meals ──
    if meals_needed:
        timeline, route_points = await _insert_meals(
            timeline, route_points, meals_needed, parsed_intent, user_profile, city
        )

    # ── 4. Detect gaps ──
    gaps = _detect_time_gaps(timeline)

    # ── 5. Insert gap activities ──
    if gaps:
        route_points = await _insert_gap_activities(
            route_points, gaps, parsed_intent, user_profile, city
        )

    # ── 6. Renumber display_order ──
    _renumber_display_order(route_points)

    return route_points


def _build_timeline(points: list[dict], parsed_intent: Any) -> list[dict]:
    """Build estimated arrival/departure timeline from route points."""
    timeline = []
    start_time = getattr(parsed_intent, "start_time", None)
    if start_time is None:
        import datetime as dt
        start_time = dt.datetime.now()
    current_hour = start_time.hour + start_time.minute / 60

    for i, pt in enumerate(points):
        visit = pt.get("visit_min") or pt.get("stay_minutes") or 60
        travel = 15  # default estimate
        if i > 0:
            prev = points[i-1]
            ploc = prev.get("location", {})
            cloc = pt.get("location", {})
            if ploc.get("lat") and cloc.get("lat"):
                dist = haversine_km(ploc, cloc)
                travel = max(3, min(40, round(dist / 4.5 * 60)))
        arrival = current_hour
        departure = current_hour + visit / 60
        timeline.append({
            "day": pt.get("day", 1),
            "name": pt.get("name", "?"),
            "kind": pt.get("kind", ""),
            "arrival_hour": round(arrival, 2),
            "departure_hour": round(departure, 2),
            "visit_min": visit,
            "travel_from_prev_min": travel if i > 0 else 0,
            "fixed_by_user": pt.get("kind") not in ("auto_meal", "auto_gap"),
            "index": i,
        })
        current_hour = departure + travel / 60
    return timeline


def _detect_meals_needed(timeline: list[dict], parsed_intent: Any) -> list[str]:
    """Detect which meal slots need a POI inserted."""
    needed = []
    has_existing_meals = any(t.get("kind") == "meal" or t.get("display_slot") in ("lunch", "dinner", "breakfast")
                            for t in timeline)

    if has_existing_meals:
        return []  # Don't duplicate meals

    route_start = timeline[0]["arrival_hour"] if timeline else 9
    route_end = timeline[-1]["departure_hour"] if timeline else 18

    for meal, (ws, we) in MEAL_WINDOWS.items():
        if meal == "breakfast" and route_start > 8.5:
            continue
        overlap = max(0.0, min(route_end, we) - max(route_start, ws))
        if overlap >= MEAL_OVERLAP_MIN:
            needed.append(meal)
    return needed


async def _insert_meals(
    timeline: list[dict],
    points: list[dict],
    meals_needed: list[str],
    parsed_intent: Any,
    user_profile: Any,
    city: str,
) -> tuple[list[dict], list[dict]]:
    """Insert meal POIs by searching near the route corridor."""
    from .api_client import gaode_around_search_batch
    from .utils import haversine_km

    result = list(points)
    for meal in meals_needed:
        ws = MEAL_WINDOWS[meal][0]
        we = MEAL_WINDOWS[meal][1]
        # Find insertion point: first POI whose arrival is after the meal window starts
        insert_idx = len(result)
        for i, pt in enumerate(result[1:], 1):  # skip start
            t = [t for t in timeline if t["index"] == i-1]
            if t and t[0]["departure_hour"] >= ws - 0.5:
                insert_idx = i
                break

        if insert_idx >= len(result):
            continue

        # Search near the insertion point
        prev_pt = result[insert_idx - 1] if insert_idx > 0 else result[0]
        next_pt = result[insert_idx] if insert_idx < len(result) else result[-1]
        search_loc = prev_pt.get("location") or next_pt.get("location")

        if not search_loc or not search_loc.get("lat"):
            continue

        meal_kw = "餐厅"
        try:
            req = {"location": coord_to_param(search_loc), "keywords": meal_kw,
                   "radius": 1000, "offset": 10}
            batch = await gaode_around_search_batch([req])
            raws = batch[0] if batch else []
            for raw in raws[:5]:
                tc = str(raw.get("typecode", "") or "")
                if tc.startswith("05"):
                    _loc = normalize_location(raw.get("location"))
                    if not _loc:
                        print(f"[TimelineAudit] meal candidate skipped (no valid coord): {raw.get('name', '?')}")
                        continue
                    _name = str(raw.get("name", "餐厅"))
                    # Dedupe by name
                    if any(p.get("name") == _name for p in result):
                        continue
                    meal_pt = {
                        "name": _name,
                        "location": _loc,
                        "kind": "meal",
                        "category": "meal",
                        "display_slot": meal,
                        "auto_inserted": True,
                        "auto_insert_reason": "meal_window",
                        "is_waypoint": True,
                        "is_display_poi": True,
                        "visit_min": MEAL_VISIT_MINUTES.get(meal, 60),
                        "day": prev_pt.get("day", 1),
                        "typecode": tc,
                    }
                    result.insert(insert_idx, meal_pt)
                    print(f"[TimelineAudit] inserted {meal}: {meal_pt['name']} at idx={insert_idx}")
                    break
        except Exception as exc:
            print(f"[TimelineAudit] meal search failed for {meal}: {exc}")

    # Rebuild timeline
    new_timeline = _build_timeline(result, parsed_intent)
    return new_timeline, result


def _detect_time_gaps(timeline: list[dict]) -> list[dict]:
    """Detect usable time gaps between consecutive fixed activities."""
    gaps = []
    for i in range(len(timeline) - 1):
        current = timeline[i]
        next_t = timeline[i + 1]
        # Only insert between fixed (non-auto) points
        if current.get("auto_inserted") or next_t.get("auto_inserted"):
            continue
        travel = current.get("travel_from_prev_min", 15)
        available = next_t["arrival_hour"] - current["departure_hour"]
        available_min = round(available * 60) - 10  # safety buffer
        if available_min > GAP_MIN_MINUTES:
            gaps.append({
                "after_index": i,
                "after_name": current["name"],
                "before_name": next_t["name"],
                "available_minutes": available_min,
                "day": current.get("day", 1),
            })
    return gaps


async def _insert_gap_activities(
    points: list[dict],
    gaps: list[dict],
    parsed_intent: Any,
    user_profile: Any,
    city: str,
) -> list[dict]:
    """Insert entertainment POIs into detected time gaps."""
    from .api_client import gaode_around_search_batch
    from .utils import coord_to_param

    result = list(points)
    inserted_count = 0
    max_auto_per_day = 3

    for gap in gaps:
        if inserted_count >= max_auto_per_day:
            break
        gap_min = gap["available_minutes"]
        if gap_min < 45:
            kws = LIGHT_GAP_KEYWORDS
            visit = 30
        elif gap_min < 120:
            kws = STANDARD_GAP_KEYWORDS
            visit = 50
        else:
            kws = STANDARD_GAP_KEYWORDS
            visit = 90

        after_idx = gap["after_index"]
        if after_idx + 1 >= len(result):
            continue
        search_loc = result[after_idx].get("location") or result[after_idx + 1].get("location")
        if not search_loc or not search_loc.get("lat"):
            continue

        for kw in kws[:3]:
            try:
                req = {"location": coord_to_param(search_loc), "keywords": kw,
                       "radius": 800, "offset": 8}
                batch = await gaode_around_search_batch([req])
                raws = batch[0] if batch else []
                for raw in raws[:5]:
                    _g_loc = normalize_location(raw.get("location"))
                    if not _g_loc:
                        continue
                    _g_name = str(raw.get("name", kw))
                    if any(p.get("name") == _g_name for p in result):
                        continue
                    gap_pt = {
                        "name": str(raw.get("name", kw)),
                        "location": _g_loc,
                        "kind": "gap_activity",
                        "category": "entertainment",
                        "display_slot": "afternoon",
                        "auto_inserted": True,
                        "auto_insert_reason": "time_gap",
                        "gap_minutes": gap_min,
                        "is_waypoint": True,
                        "is_display_poi": True,
                        "visit_min": min(visit, gap_min - 10),
                        "day": gap.get("day", 1),
                        "typecode": str(raw.get("typecode", "") or ""),
                    }
                    result.insert(after_idx + 1, gap_pt)
                    inserted_count += 1
                    print(f"[TimelineAudit] gap_inserted: {gap_pt['name']} gap={gap_min}m")
                    break
                break
            except Exception as exc:
                print(f"[TimelineAudit] gap search failed kw={kw}: {exc}")

    return result


def _renumber_display_order(points: list[dict]) -> None:
    """Renumber display_order for all display POIs."""
    order = 0
    for pt in points:
        if pt.get("kind") == "start":
            pt["display_order"] = 0
        elif pt.get("is_display_poi") or pt.get("is_waypoint"):
            order += 1
            pt["display_order"] = order
