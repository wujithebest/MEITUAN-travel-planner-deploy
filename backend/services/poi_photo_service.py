from __future__ import annotations

import asyncio
from typing import Any

from .api_client import bocha_image_search, gaode_place_detail, gaode_text_search


# Fallback image has been removed per requirement: POIs without real images should show "暂无图片"
# No default placeholder image should be used
_photo_cache: dict[str, dict[str, str]] = {}
_photo_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _photo_lock
    if _photo_lock is None:
        _photo_lock = asyncio.Lock()
    return _photo_lock


def _cache_key(poi_id: str = "", poi_name: str = "", location: dict[str, Any] | None = None) -> str:
    if poi_id:
        return f"id:{poi_id}"
    loc = location or {}
    return f"name:{poi_name}:{loc.get('lng')}:{loc.get('lat')}"


def _first_photo_url(poi: dict[str, Any] | None) -> str:
    if not poi:
        return ""
    photos = poi.get("photos") or []
    if isinstance(photos, list):
        for photo in photos:
            if isinstance(photo, dict) and photo.get("url"):
                return str(photo["url"])
    photo_url = poi.get("photo_url")
    return str(photo_url) if photo_url else ""


def _looks_usable_image_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    lowered = url.lower()
    # Must start with http:// or https:// (not local / paths like /images/shanghai.jpg)
    if not lowered.startswith(("http://", "https://")):
        return False
    # Exclude known fallback/placeholder/icon images
    blocked_tokens = [
        "logo", "icon", "avatar",
        "/images/shanghai.jpg",
        "unsplash.com/photo-1508804185872",
    ]
    if any(token in lowered for token in blocked_tokens):
        return False
    return True


async def resolve_poi_photo(
    poi_id: str = "",
    poi_name: str = "",
    location: dict[str, Any] | None = None,
    category: str = "",
) -> dict[str, str]:
    """Resolve a display photo for a POI, preferring Gaode and falling back to Bocha."""
    key = _cache_key(poi_id, poi_name, location)
    cached = _photo_cache.get(key)
    if cached:
        return cached

    async with _get_lock():
        cached = _photo_cache.get(key)
        if cached:
            return cached

        # 1. Gaode detail by POI id.
        if poi_id:
            detail = await gaode_place_detail(poi_id, show_fields="business,photos")
            url = _first_photo_url(detail)
            if _looks_usable_image_url(url):
                result = {"photo_url": url, "photo_source": "gaode"}
                _photo_cache[key] = result
                return result

        # 2. Gaode text search with photos, useful when route points only have name.
        if poi_name:
            try:
                matches = await gaode_text_search(poi_name, city="上海", show_fields="business,photos")
            except Exception:
                matches = []
            for match in matches:
                url = _first_photo_url(match)
                if _looks_usable_image_url(url):
                    result = {"photo_url": url, "photo_source": "gaode"}
                    _photo_cache[key] = result
                    return result

        # 3. Bocha image fallback.
        if poi_name:
            query = f"{poi_name} 上海 {category or '景点'} 图片"
            try:
                for url in await bocha_image_search(query, count=5):
                    if _looks_usable_image_url(url):
                        result = {"photo_url": url, "photo_source": "bocha"}
                        _photo_cache[key] = result
                        return result
            except Exception:
                pass

        # No real image found — return empty. Do NOT use any fallback placeholder.
        result = {"photo_url": "", "photo_source": ""}
        _photo_cache[key] = result
        return result


async def enrich_points_with_photos(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    async def _one(point: dict[str, Any]) -> dict[str, Any]:
        # Strip any existing fallback/default image URLs from the point
        existing_photo = point.get("photo_url", "")
        existing_source = point.get("photo_source", "")
        if existing_photo and not _looks_usable_image_url(str(existing_photo)):
            point["photo_url"] = ""
            point["photo_source"] = ""
        elif existing_photo:
            # Has a usable photo already, keep it
            point.setdefault("photo_source", existing_source or "gaode")
            return point
        if point.get("kind") in {"start", "hint", "free_explore"}:
            return point
        photo = await resolve_poi_photo(
            poi_id=str(point.get("gaode_poi_id") or point.get("poi_id") or ""),
            poi_name=str(point.get("name") or ""),
            location=point.get("location") or {},
            category=str(point.get("category") or point.get("typecode") or ""),
        )
        # Only apply if a real photo was found
        if photo.get("photo_url") and photo.get("photo_source"):
            point.update(photo)
        return point

    return await asyncio.gather(*[_one(dict(point)) for point in points])
