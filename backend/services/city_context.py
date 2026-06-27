from __future__ import annotations

import re
from typing import Any

from .api_client import gaode_reverse_geocode
from .theme_profile_matcher import normalize_city_name


CITY_NAME_RE = re.compile(r"([一-龥]{2,12}市)")
DIRECT_MUNICIPALITIES = ("北京", "上海", "天津", "重庆")


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
    """Resolve one authoritative city from the configured route departure."""
    home_location = getattr(user_profile, "home_location", None) or {}
    if isinstance(home_location, dict):
        structured_city = normalize_city_name(
            home_location.get("city") or home_location.get("cityname") or ""
        )
        if structured_city:
            return structured_city

        label_city = city_from_text(home_location.get("label"))
        if label_city:
            return label_city

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

    permanent_city = list(getattr(user_profile, "permanent_city", []) or [])
    return normalize_city_name(permanent_city[0] if permanent_city else fallback)


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
