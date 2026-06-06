from __future__ import annotations

from typing import Any

from .api_client import gaode_around_search, gaode_place_detail, parse_coord_location
from .config import GAODE_SHOW_FIELDS
from .poi_feedback_service import calculate_feedback_score
from .poi_photo_service import enrich_points_with_photos
from .utils import coord_to_param, haversine_km


BLUE_THEME = "#3B82F6"
DEFAULT_LIMIT = 5
DEFAULT_RADIUS_M = 500
COMPLEMENTARY_TYPES = {
    "050": "050000|050500|060000|060100",
    "060": "060000|060100|050500|110000",
    "110": "110000|110100|110200|050500",
    "080": "080000|080500|080600|050500",
}


def _normalize_location(location: Any) -> dict[str, float] | None:
    if isinstance(location, dict):
        lat = location.get("lat")
        lng = location.get("lng")
        if lat is not None and lng is not None:
            return {"lat": float(lat), "lng": float(lng)}
    if isinstance(location, str):
        return parse_coord_location(location)
    return None


def _target_from_id_payload(poi_id: str, poi_name: str = "", location: str = "", category: str = "") -> dict[str, Any]:
    loc = _normalize_location(location)
    return {
        "poi_id": poi_id,
        "gaode_poi_id": poi_id if ":" not in poi_id else "",
        "name": poi_name,
        "location": loc,
        "category": category,
        "typecode": category,
    }


async def resolve_target_poi(
    poi_id: str,
    poi_name: str = "",
    location: str = "",
    category: str = "",
) -> dict[str, Any]:
    target = _target_from_id_payload(poi_id, poi_name=poi_name, location=location, category=category)
    if target.get("location") and target.get("name"):
        return target

    detail = await gaode_place_detail(poi_id, show_fields="business,photos") if poi_id and ":" not in poi_id else None
    if detail:
        detail_loc = _normalize_location(detail.get("location"))
        return {
            "poi_id": detail.get("id") or poi_id,
            "gaode_poi_id": detail.get("id") or poi_id,
            "name": detail.get("name") or poi_name,
            "location": detail_loc or target.get("location"),
            "category": category or detail.get("typecode", ""),
            "typecode": detail.get("typecode") or category,
            "address": detail.get("address", ""),
            "rating": detail.get("rating"),
            "avg_cost": detail.get("avg_cost"),
            "photo_url": detail.get("photo_url", ""),
            "photo_source": "gaode" if detail.get("photo_url") else "",
        }
    return target


async def _feedback_records(user_id: str) -> dict[str, list[dict[str, Any]]]:
    if not user_id:
        return {"poi_likes": [], "poi_dislikes": [], "poi_removes": []}
    from models.mongodb import UserMongoDB

    user = await UserMongoDB.get_by_id(user_id)
    prefs = (user or {}).get("preferences", {}) or {}
    return {
        "poi_likes": list(prefs.get("poi_likes", []) or []),
        "poi_dislikes": list(prefs.get("poi_dislikes", []) or []),
        "poi_removes": list(prefs.get("poi_removes", []) or []),
    }


def _types_for_target(typecode: str) -> str:
    prefix6 = (typecode or "")[:6]
    if prefix6:
        return prefix6
    prefix3 = (typecode or "")[:3]
    return COMPLEMENTARY_TYPES.get(prefix3, "")


def _distance_score(target: dict[str, Any], candidate: dict[str, Any]) -> float:
    distance_km = haversine_km(target.get("location"), candidate.get("location"))
    return max(0.0, 1.0 - min(distance_km * 1000, DEFAULT_RADIUS_M) / DEFAULT_RADIUS_M)


def _category_score(target_type: str, candidate_type: str) -> float:
    if not target_type or not candidate_type:
        return 0.45
    if candidate_type[:6] == target_type[:6]:
        return 1.0
    if candidate_type[:3] == target_type[:3]:
        return 0.75
    return 0.35


def _popularity_score(candidate: dict[str, Any]) -> float:
    rating = candidate.get("rating") or candidate.get("gaode_rating") or 0
    try:
        return min(max(float(rating), 0.0), 5.0) / 5.0
    except (TypeError, ValueError):
        return 0.55


async def generate_alternative_pool(
    poi_id: str,
    user_id: str = "",
    limit: int = DEFAULT_LIMIT,
    poi_name: str = "",
    location: str = "",
    category: str = "",
    radius_m: int = DEFAULT_RADIUS_M,
) -> list[dict[str, Any]]:
    target = await resolve_target_poi(poi_id, poi_name=poi_name, location=location, category=category)
    target_loc = target.get("location")
    if not target_loc:
        return []

    target_type = target.get("typecode") or target.get("category") or category
    keywords = target.get("name") or poi_name or ""
    types = _types_for_target(target_type)
    candidates = await gaode_around_search(
        location=coord_to_param(target_loc),
        keywords=keywords,
        radius=radius_m,
        types=types,
        show_fields=GAODE_SHOW_FIELDS,
        offset=max(limit * 3, 12),
    )
    if len(candidates) < limit and types:
        candidates.extend(await gaode_around_search(
            location=coord_to_param(target_loc),
            keywords="",
            radius=radius_m,
            types=COMPLEMENTARY_TYPES.get((target_type or "")[:3], types),
            show_fields=GAODE_SHOW_FIELDS,
            offset=max(limit * 3, 12),
        ))

    records = await _feedback_records(user_id)
    seen: set[str] = {str(poi_id)}
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        cid = str(candidate.get("id") or candidate.get("gaode_poi_id") or "")
        cname = str(candidate.get("name") or "")
        if not cname or cid in seen or cname == target.get("name"):
            continue
        seen.add(cid)
        feedback = calculate_feedback_score(records, poi_id=cid, poi_name=cname)
        if feedback <= -20:
            continue
        score = (
            35 * _distance_score(target, candidate)
            + 25 * _category_score(str(target_type), str(candidate.get("typecode") or ""))
            + 25 * _popularity_score(candidate)
            + feedback
        )
        ranked.append({
            "poi_id": cid or f"{cname}:{coord_to_param(candidate.get('location'))}",
            "gaode_poi_id": cid,
            "name": cname,
            "category": candidate.get("typecode", ""),
            "typecode": candidate.get("typecode", ""),
            "lnglat": [
                float(candidate.get("location", {}).get("lng", 0)),
                float(candidate.get("location", {}).get("lat", 0)),
            ],
            "location": candidate.get("location"),
            "address": candidate.get("address", ""),
            "rating": candidate.get("rating") or candidate.get("gaode_rating"),
            "avg_cost": candidate.get("avg_cost"),
            "theme_color": BLUE_THEME,
            "score": round(score, 2),
            "photo_url": candidate.get("photo_url", ""),
            "photo_source": "gaode" if candidate.get("photo_url") else "",
        })

    ranked.sort(key=lambda item: item["score"], reverse=True)
    enriched = await enrich_points_with_photos(ranked[:limit])
    return enriched
