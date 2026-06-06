from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

import math

from services.api_client import gaode_place_detail, gaode_text_search
from services.alternative_service import generate_alternative_pool
from services.poi_photo_service import resolve_poi_photo
from services.poi_feedback_service import record_poi_preference


# Fallback image URLs that should never be used as POI photos
_FALLBACK_URLS = {"/images/shanghai.jpg", "https://images.unsplash.com/photo-1508804185872-d7badad00f7d"}


def _haversine_distance(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Calculate distance in meters between two coordinates using Haversine formula."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _names_match(name1: str, name2: str) -> bool:
    """Check if two POI names likely refer to the same place."""
    if not name1 or not name2:
        return False
    n1 = name1.strip()
    n2 = name2.strip()
    if n1 == n2:
        return True
    # One contains the other
    if n1 in n2 or n2 in n1:
        return True
    # After removing common suffixes like (Shanghai)
    for suffix in ["（上海）", "(上海)", "（", "("]:
        n1 = n1.split(suffix)[0].strip()
        n2 = n2.split(suffix)[0].strip()
    return n1 == n2


def _is_fallback_image(url: str, source: str = "") -> bool:
    """Check if a photo URL or source indicates a fallback/default image."""
    if source == "fallback":
        return True
    if not url:
        return False
    url_lower = url.lower()
    if any(fb in url_lower for fb in _FALLBACK_URLS):
        return True
    if "unsplash.com/photo-1508804185872" in url_lower:
        return True
    return False


router = APIRouter(prefix="/api/v1", tags=["v1-poi-feedback"])


class PreferenceRequest(BaseModel):
    user_id: str = Field("", description="User id")
    poi_id: str = Field("", description="Stable POI id")
    poi_name: str = Field(..., description="POI name")
    action: Literal["like", "dislike", "delete", "remove"] = Field(..., description="Interaction action")
    route_id: str | None = None
    timestamp: int | float | str | None = None
    poi_type: str = ""


class ReplaceRouteRequest(BaseModel):
    old_poi_id: str
    new_poi_id: str
    user_id: str = ""
    route_version: str | None = None


def _parse_lnglat(location: str) -> tuple[float, float] | None:
    if not location:
        return None
    try:
        lng_raw, lat_raw = location.split(",", 1)
        return float(lng_raw), float(lat_raw)
    except Exception:
        return None


def _distance_score(raw: dict[str, Any], target: tuple[float, float] | None) -> float:
    if not target:
        return 0.0
    loc = raw.get("location") or {}
    try:
        lng = float(loc.get("lng"))
        lat = float(loc.get("lat"))
    except Exception:
        return 999.0
    return abs(lng - target[0]) + abs(lat - target[1])


def _first_photo_url(raw: dict[str, Any] | None) -> str:
    if not raw:
        return ""
    photos = raw.get("photos") or []
    if isinstance(photos, list):
        for photo in photos:
            if isinstance(photo, dict) and (photo.get("url") or photo.get("contentUrl")):
                return str(photo.get("url") or photo.get("contentUrl"))
    return str(raw.get("photo_url") or "")


async def _format_poi_detail(
    raw: dict[str, Any] | None,
    fallback_name: str = "",
    fallback_category: str = "",
) -> dict[str, Any] | None:
    if not raw:
        return None
    poi_id = str(raw.get("id") or raw.get("gaode_poi_id") or "")
    name = str(raw.get("name") or fallback_name or "")
    photo_url = _first_photo_url(raw)
    photo_source = "gaode" if photo_url else ""
    # Strip fallback/default images from the raw data
    if photo_url and _is_fallback_image(photo_url, photo_source):
        photo_url = ""
        photo_source = ""
    if not photo_url and name:
        photo = await resolve_poi_photo(
            poi_id=poi_id,
            poi_name=name,
            location=raw.get("location") or {},
            category=str(raw.get("typecode") or fallback_category or ""),
        )
        photo_url = photo.get("photo_url", "")
        photo_source = photo.get("photo_source", "")
    # Final safety: never return fallback images
    if _is_fallback_image(photo_url, photo_source):
        photo_url = ""
        photo_source = ""
    return {
        "poi_id": poi_id,
        "gaode_poi_id": poi_id,
        "name": name,
        "location": raw.get("location") or {},
        "address": raw.get("address") or "",
        "rating": raw.get("rating"),
        "gaode_rating": raw.get("rating"),
        "avg_cost": (raw.get("biz_ext") or {}).get("cost") if isinstance(raw.get("biz_ext"), dict) else None,
        "photo_url": photo_url,
        "photo_source": photo_source,
        "typecode": raw.get("typecode") or "",
        "category": raw.get("typecode") or fallback_category or "",
    }


@router.post("/user/preference")
async def record_user_preference(req: PreferenceRequest) -> dict[str, Any]:
    try:
        return await record_poi_preference(
            user_id=req.user_id,
            poi_id=req.poi_id,
            poi_name=req.poi_name,
            poi_type=req.poi_type,
            action=req.action,
            route_id=req.route_id,
            timestamp=req.timestamp or datetime.utcnow().timestamp(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/user/preferences/batch")
async def record_user_preferences_batch(items: list[PreferenceRequest]) -> dict[str, Any]:
    results = []
    for item in items:
        results.append(await record_user_preference(item))
    return {"success": True, "count": len(results), "results": results}


@router.get("/pois/detail")
async def get_poi_detail(
    poi_id: str = Query("", description="Gaode POI id if available"),
    poi_name: str = Query("", description="POI name fallback"),
    location: str = Query("", description="lng,lat fallback"),
    category: str = Query("", description="category or typecode fallback"),
) -> dict[str, Any]:
    """Return real POI fields used to restore old guest favorites.

    Validates that the poi_id query result actually matches the requested
    poi_name and location, to prevent wrong POI images from being returned
    when an incorrect or reused poi_id is passed.
    """
    target = _parse_lnglat(location)
    raw_detail: dict[str, Any] | None = None
    stable_id = bool(poi_id) and ":" not in poi_id and "," not in poi_id

    if stable_id:
        raw_detail = await gaode_place_detail(poi_id, show_fields="business,photos")
        # Validate: the result must match the requested name or location
        if raw_detail and poi_name:
            detail_name = str(raw_detail.get("name") or "")
            detail_loc = raw_detail.get("location") or {}
            if not _names_match(detail_name, poi_name) and target:
                try:
                    detail_lng = float(detail_loc.get("lng", 0))
                    detail_lat = float(detail_loc.get("lat", 0))
                    dist = _haversine_distance(detail_lng, detail_lat, target[0], target[1])
                    if dist > 500:
                        # POI ID result does not match — discard and fall back to text search
                        raw_detail = None
                except (ValueError, TypeError):
                    raw_detail = None

    if not raw_detail and poi_name:
        matches = await gaode_text_search(poi_name, city="上海", show_fields="business,photos")
        if matches:
            # Filter: prefer results whose name matches the request
            if target:
                close_matches = []
                for item in matches:
                    item_loc = item.get("location") or {}
                    try:
                        item_lng = float(item_loc.get("lng", 0))
                        item_lat = float(item_loc.get("lat", 0))
                        dist = _haversine_distance(item_lng, item_lat, target[0], target[1])
                        if dist <= 500:
                            close_matches.append(item)
                    except (ValueError, TypeError):
                        pass
                pool = close_matches or matches
            else:
                pool = matches
            exact = [item for item in pool if item.get("name") == poi_name]
            pool = exact or pool
            raw_detail = sorted(pool, key=lambda item: _distance_score(item, target))[0]

    detail = await _format_poi_detail(raw_detail, fallback_name=poi_name, fallback_category=category)
    return {"success": bool(detail), "data": detail}


@router.get("/pois/{poi_id}/alternatives")
async def get_poi_alternatives(
    poi_id: str,
    user_id: str = Query("", description="User id"),
    limit: int = Query(5, ge=1, le=20),
    poi_name: str = Query("", description="Target POI name fallback"),
    location: str = Query("", description="Target location as lng,lat fallback"),
    category: str = Query("", description="Target category or typecode fallback"),
) -> dict[str, Any]:
    alternatives = await generate_alternative_pool(
        poi_id=poi_id,
        user_id=user_id,
        limit=limit,
        poi_name=poi_name,
        location=location,
        category=category,
    )
    return {"alternatives": alternatives}


@router.delete("/routes/{route_id}/pois/{poi_id}")
async def delete_route_poi(
    route_id: str,
    poi_id: str,
    user_id: str = Query(""),
    poi_name: str = Query(""),
    poi_type: str = Query(""),
) -> dict[str, Any]:
    if poi_name:
        await record_poi_preference(
            user_id=user_id,
            poi_id=poi_id,
            poi_name=poi_name,
            poi_type=poi_type,
            action="delete",
            route_id=route_id,
        )
    return {"success": True, "route_id": route_id, "poi_id": poi_id, "recalculate_required": True}


@router.post("/routes/{route_id}/replace")
async def replace_route_poi(route_id: str, req: ReplaceRouteRequest) -> dict[str, Any]:
    return {
        "success": True,
        "route_id": route_id,
        "old_poi_id": req.old_poi_id,
        "new_poi_id": req.new_poi_id,
        "recalculate_required": True,
    }
