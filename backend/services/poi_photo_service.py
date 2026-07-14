from __future__ import annotations

import asyncio
import time
from typing import Any

from . import config
from .api_client import bocha_image_search, gaode_place_detail, gaode_text_search


# Fallback image has been removed per requirement: POIs without real images should show "暂无图片"
# No default placeholder image should be used
_photo_cache: dict[str, dict[str, str]] = {}
_photo_inflight: dict[str, asyncio.Task[dict[str, str]]] = {}
_photo_inflight_lock: asyncio.Lock | None = None
_photo_semaphore: asyncio.Semaphore | None = None
_bocha_image_disabled_until = 0.0


def _get_inflight_lock() -> asyncio.Lock:
    global _photo_inflight_lock
    if _photo_inflight_lock is None:
        _photo_inflight_lock = asyncio.Lock()
    return _photo_inflight_lock


def _get_photo_semaphore() -> asyncio.Semaphore:
    global _photo_semaphore
    if _photo_semaphore is None:
        _photo_semaphore = asyncio.Semaphore(config.POI_PHOTO_MAX_CONCURRENCY)
    return _photo_semaphore


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


def _is_transport_failure(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in (
        "tls", "ssl", "connection reset", "unexpected eof", "timed out", "curl: (35)",
    ))


async def _resolve_poi_photo_uncached(
    poi_id: str = "",
    poi_name: str = "",
    location: dict[str, Any] | None = None,
    category: str = "",
    city: str = "",
) -> dict[str, str]:
    """Resolve one uncached photo while allowing unrelated POIs to overlap."""
    global _bocha_image_disabled_until
    _search_city = city or "上海"  # v21: use provided city, not hardcoded Shanghai
    key = _cache_key(poi_id, poi_name, location)
    async with _get_photo_semaphore():
        # 1. Gaode detail by POI id.
        if poi_id:
            try:
                detail = await gaode_place_detail(poi_id, show_fields="business,photos")
            except Exception:
                detail = {}
            url = _first_photo_url(detail)
            if _looks_usable_image_url(url):
                result = {"photo_url": url, "photo_source": "gaode"}
                _photo_cache[key] = result
                return result

        # 2. Gaode text search with photos, useful when route points only have name.
        if poi_name:
            try:
                matches = await gaode_text_search(poi_name, city=_search_city, show_fields="business,photos")
            except Exception:
                matches = []
            for match in matches:
                url = _first_photo_url(match)
                if _looks_usable_image_url(url):
                    result = {"photo_url": url, "photo_source": "gaode"}
                    _photo_cache[key] = result
                    return result

        # 3. Bocha image fallback. A confirmed transport outage cannot add an
        # image, so skip repeat attempts for this optional source briefly.
        if poi_name and time.monotonic() >= _bocha_image_disabled_until:
            try:
                query = f"{poi_name} 上海 {category or '景点'} 图片"
                for url in await bocha_image_search(query, count=5):
                    if _looks_usable_image_url(url):
                        result = {"photo_url": url, "photo_source": "bocha"}
                        _photo_cache[key] = result
                        return result
            except Exception as exc:
                if _is_transport_failure(exc):
                    _bocha_image_disabled_until = time.monotonic() + 300.0

    # No real image found — return empty. Do NOT use any fallback placeholder.
    result = {"photo_url": "", "photo_source": ""}
    _photo_cache[key] = result
    return result


async def resolve_poi_photo(
    poi_id: str = "",
    poi_name: str = "",
    location: dict[str, Any] | None = None,
    category: str = "",
    city: str = "",
) -> dict[str, str]:
    """Resolve a display photo with per-POI de-duplication, not a global lock."""
    key = _cache_key(poi_id, poi_name, location)
    cached = _photo_cache.get(key)
    if cached is not None:
        return cached

    async with _get_inflight_lock():
        task = _photo_inflight.get(key)
        if task is None:
            task = asyncio.create_task(
                _resolve_poi_photo_uncached(poi_id, poi_name, location, category, city)
            )
            _photo_inflight[key] = task

    try:
        return await asyncio.shield(task)
    finally:
        if task.done():
            async with _get_inflight_lock():
                if _photo_inflight.get(key) is task:
                    _photo_inflight.pop(key, None)


async def enrich_points_with_photos(points: list[dict[str, Any]], city: str = "") -> list[dict[str, Any]]:
    _photo_city = city or ""
    async def _one(point: dict[str, Any]) -> dict[str, Any]:
        existing_photo = point.get("photo_url", "")
        existing_source = point.get("photo_source", "")
        if existing_photo and not _looks_usable_image_url(str(existing_photo)):
            point["photo_url"] = ""
            point["photo_source"] = ""
        elif existing_photo:
            point.setdefault("photo_source", existing_source or "gaode")
            return point
        if point.get("kind") in {"start", "hint", "free_explore"}:
            return point
        photo = await resolve_poi_photo(
            poi_id=str(point.get("gaode_poi_id") or point.get("poi_id") or ""),
            poi_name=str(point.get("name") or ""),
            location=point.get("location") or {},
            category=str(point.get("category") or point.get("typecode") or ""),
            city=_photo_city,
        )
        # Only apply if a real photo was found
        if photo.get("photo_url") and photo.get("photo_source"):
            point.update(photo)
        return point

    return await asyncio.gather(*[_one(dict(point)) for point in points])
