"""
v28: Fixed route service — reads pre-generated route JSON from disk.
No LLM, no Amap, no pipeline execution.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FIXED_ROUTES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixed_routes"

# Whitelist — only these fixture IDs are allowed (prevents path traversal)
ALLOWED_FIXTURE_IDS = {
    "literary-photo-cafe",
    "tiananmen-forbidden-city-jingshan",
    "nearby-food-walk",
    "spicy-compatible-restaurant",
    "literary-river-night-view",
    "beihai-roast-duck-sanlihe",
}


def get_fixed_route(fixture_id: str) -> dict | None:
    """Read a fixed route fixture from disk. Returns None if not found."""
    if fixture_id not in ALLOWED_FIXTURE_IDS:
        return None

    filepath = FIXED_ROUTES_DIR / f"{fixture_id}.json"
    if not filepath.is_file():
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[FixedRouteService] failed to read {fixture_id}: {exc}")
        return None

    # Validate the full snapshot so an empty placeholder can never be served.
    route_data = data.get("route_data") or {}
    map_route_data = data.get("map_route_data") or {}
    if (
        not data.get("route_id")
        or data.get("origin", {}).get("label") != "恒基伟业大厦"
        or not route_data.get("points")
        or not route_data.get("segments")
        or not map_route_data.get("markers")
        or not map_route_data.get("polylines")
        or not data.get("panel_days")
    ):
        print(f"[FixedRouteService] {fixture_id}: incomplete fixed snapshot")
        return None

    return data


def get_all_fixture_ids() -> list[str]:
    return sorted(ALLOWED_FIXTURE_IDS)
