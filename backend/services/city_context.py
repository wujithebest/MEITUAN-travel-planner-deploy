from __future__ import annotations

import re
from typing import Any

from .api_client import gaode_reverse_geocode
from .theme_profile_matcher import normalize_city_name


CITY_NAME_RE = re.compile(r"([一-龥]{2,12}市)")
DIRECT_MUNICIPALITIES = ("北京", "上海", "天津", "重庆")

# v27: Coordinate bounding boxes for major Chinese cities.
# Used as a fast fallback when reverse geocode fails and permanent_city is stale.
_CITY_COORD_RANGES: list[tuple[str, float, float, float, float]] = [
    ("北京市", 39.4, 41.1, 115.4, 117.6),
    ("上海市", 30.6, 31.9, 120.8, 122.2),
    ("深圳市", 22.4, 23.6, 113.6, 114.8),
    ("广州市", 22.8, 24.0, 112.9, 114.2),
    ("天津市", 38.5, 40.3, 116.6, 118.1),
    ("重庆市", 28.1, 32.2, 105.2, 110.4),
    ("杭州市", 29.8, 30.6, 119.6, 120.9),
    ("成都市", 30.0, 31.5, 103.6, 104.9),
    ("武汉市", 29.9, 31.4, 113.6, 115.1),
    ("南京市", 31.1, 32.6, 118.3, 119.4),
    ("西安市", 33.4, 34.8, 107.4, 109.8),
    ("苏州市", 30.8, 32.0, 120.4, 121.5),
    ("长沙市", 27.8, 28.7, 112.5, 114.3),
    ("青岛市", 35.8, 37.2, 119.5, 121.2),
    ("厦门市", 24.2, 24.9, 117.9, 118.5),
    ("昆明市", 24.3, 26.6, 102.1, 103.7),
    ("三亚市", 18.0, 18.5, 109.0, 109.9),
]


def infer_city_from_coord(lat: float, lng: float) -> str:
    """Infer city name from lat/lng coordinate using bounding box ranges.

    Returns empty string if no match found.  This is a fast, offline fallback
    when reverse geocode is unavailable and permanent_city may be stale.
    """
    for city_name, lat_min, lat_max, lng_min, lng_max in _CITY_COORD_RANGES:
        if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
            return normalize_city_name(city_name)
    return ""


def city_from_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for municipality in DIRECT_MUNICIPALITIES:
        if municipality in text:
            return normalize_city_name(municipality)
    match = CITY_NAME_RE.search(text)
    return normalize_city_name(match.group(1)) if match else ""


def _location_param(location: dict[str, Any] | None) -> str:
    if not isinstance(location, dict):
        return ""
    lat = location.get("lat")
    lng = location.get("lng")
    if lat is None or lng is None:
        return ""
    return f"{lng},{lat}"


async def resolve_departure_city(user_profile: Any, fallback: str = "上海市") -> str:
    """Resolve one authoritative city from the configured route departure.

    v27 priority order:
    1. home_location.city / cityname (structured field)
    2. home_location.label → city_from_text extraction
    3. home_location.lat/lng → infer_city_from_coord (coordinate range)
    4. home_location.lat/lng → gaode_reverse_geocode when the range is unknown
    5. permanent_city[0]
    6. safe fallback

    When home_location coordinates infer a city that differs from permanent_city,
    the coordinate-inferred city wins.  This prevents stale Shanghai permanent_city
    from overriding a Beijing home_location.
    """
    home_location = getattr(user_profile, "home_location", None) or {}
    _home_lat = None
    _home_lng = None
    if isinstance(home_location, dict):
        _home_lat = home_location.get("lat")
        _home_lng = home_location.get("lng")

        # 1. Structured city field
        structured_city = normalize_city_name(
            home_location.get("city") or home_location.get("cityname") or ""
        )
        if structured_city:
            return structured_city

        # 2. Label-based city extraction
        label_city = city_from_text(home_location.get("label"))
        if label_city:
            return label_city

    # 3. Use an unambiguous coordinate range before making a network request.
    # This avoids repeated reverse-geocoding for known city coordinates.
    _coord_city = ""
    if _home_lat is not None and _home_lng is not None:
        _coord_city = infer_city_from_coord(float(_home_lat), float(_home_lng))

    permanent_city = list(getattr(user_profile, "permanent_city", []) or [])
    _perm_city = normalize_city_name(permanent_city[0] if permanent_city else "")
    if _coord_city:
        if _perm_city and _coord_city != _perm_city:
            print(
                f"[CityResolveAudit] source=home_coord_fast_path "
                f"inferred_city={_coord_city} stale_permanent_city={_perm_city} action=override"
            )
        return _coord_city

    # 4. Reverse geocode only when structured data and coordinate inference
    # cannot determine the city.
    if isinstance(home_location, dict):
        location = _location_param(home_location)
        if location:
            try:
                address = await gaode_reverse_geocode(location)
            except Exception as exc:
                print(f"[WARN city_context] reverse geocode failed: {exc}")
                address = None
            if address:
                city_value = address.get("city")
                if isinstance(city_value, list):
                    city_value = city_value[0] if city_value else ""
                resolved = normalize_city_name(
                    city_value or address.get("province") or ""
                )
                if resolved:
                    return resolved

    # 5. Permanent city fallback (only when no coordinate is available)
    if _perm_city:
        return _perm_city

    return normalize_city_name(fallback)


def apply_resolved_city(user_profile: Any, city: str) -> None:
    normalized = normalize_city_name(city)
    if not normalized:
        return
    old = list(getattr(user_profile, "permanent_city", []) or [])
    district = old[1] if len(old) > 1 else ""
    user_profile.permanent_city = [normalized, district] if district else [normalized]

    home_location = getattr(user_profile, "home_location", None)
    if isinstance(home_location, dict):
        home_location["city"] = normalized
