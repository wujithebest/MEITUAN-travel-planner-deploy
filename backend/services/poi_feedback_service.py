from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

LIKE_WEIGHT = 8.0
DISLIKE_WEIGHT = -16.0
DELETE_WEIGHT = -10.0
HALF_LIFE_DAYS = 30.0
MIN_FEEDBACK_SCORE = -30.0
MAX_FEEDBACK_SCORE = 20.0


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _decay(timestamp: Any, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    days = max(0.0, (now - _parse_time(timestamp)).total_seconds() / 86400)
    return 0.5 ** (days / HALF_LIFE_DAYS)


def _matches(record: dict[str, Any], poi_id: str = "", poi_name: str = "") -> bool:
    record_id = str(record.get("poi_id") or record.get("gaode_poi_id") or "").strip()
    record_name = str(record.get("poi_name") or record.get("name") or "").strip().lower()
    if poi_id and record_id and record_id == poi_id:
        return True
    return bool(poi_name and record_name and record_name == poi_name.strip().lower())


def calculate_feedback_score(
    records: dict[str, list[dict[str, Any]]] | Any,
    poi_id: str = "",
    poi_name: str = "",
    now: datetime | None = None,
) -> float:
    """Return a bounded score adjustment for a specific POI."""
    if records is None:
        return 0.0
    if not isinstance(records, dict):
        records = {
            "poi_likes": getattr(records, "poi_likes", []),
            "poi_dislikes": getattr(records, "poi_dislikes", []),
            "poi_removes": getattr(records, "poi_removes", []),
        }

    total = 0.0
    for field, weight in (
        ("poi_likes", LIKE_WEIGHT),
        ("poi_dislikes", DISLIKE_WEIGHT),
        ("poi_removes", DELETE_WEIGHT),
    ):
        for record in records.get(field, []) or []:
            if not isinstance(record, dict) or not _matches(record, poi_id, poi_name):
                continue
            count = float(record.get("hit_count") or 1)
            total += weight * count * _decay(record.get("timestamp"), now)

    return round(max(MIN_FEEDBACK_SCORE, min(MAX_FEEDBACK_SCORE, total)), 2)


def get_profile_feedback_records(user_profile: Any) -> dict[str, list[dict[str, Any]]]:
    return {
        "poi_likes": list(getattr(user_profile, "poi_likes", []) or []),
        "poi_dislikes": list(getattr(user_profile, "poi_dislikes", []) or []),
        "poi_removes": list(getattr(user_profile, "poi_removes", []) or []),
    }


def is_strong_negative_feedback(records: dict[str, list[dict[str, Any]]], poi_id: str = "", poi_name: str = "") -> bool:
    score = calculate_feedback_score(records, poi_id=poi_id, poi_name=poi_name)
    return score <= DISLIKE_WEIGHT * 0.75


async def record_poi_preference(
    user_id: str,
    poi_name: str,
    action: str,
    poi_id: str = "",
    poi_type: str = "",
    route_id: str | None = None,
    timestamp: int | float | str | None = None,
) -> dict[str, Any]:
    """Persist a POI interaction into the user's preference document.

    Unknown or guest users are accepted but not persisted, so guest mode can keep
    working without a token while logged-in users get durable personalization.
    """
    normalized_action = "remove" if action == "delete" else action
    field = {
        "like": "poi_likes",
        "add": "poi_likes",
        "dislike": "poi_dislikes",
        "remove": "poi_removes",
    }.get(normalized_action)
    if not field:
        raise ValueError(f"无效的 action: {action}")

    if user_id:
        from models.mongodb import UserMongoDB

        user = await UserMongoDB.get_by_id(user_id)
    else:
        user = None
    if not user:
        return {"success": True, "persisted": False, "message": "guest preference accepted"}

    prefs = user.get("preferences", {}) or {}
    if not isinstance(prefs, dict):
        prefs = {}
    records = prefs.get(field, []) or []
    event_time = _parse_time(timestamp).isoformat() if timestamp is not None else datetime.utcnow().isoformat()

    existing = None
    for record in records:
        if not isinstance(record, dict):
            continue
        if _matches(record, poi_id=poi_id, poi_name=poi_name):
            existing = record
            break

    if existing:
        existing["hit_count"] = int(existing.get("hit_count") or 1) + 1
        existing["timestamp"] = event_time
        existing["action"] = normalized_action
        existing["route_id"] = route_id
    else:
        records.append({
            "poi_id": poi_id,
            "poi_name": poi_name,
            "poi_type": poi_type,
            "action": normalized_action,
            "route_id": route_id,
            "timestamp": event_time,
            "hit_count": 1,
        })

    prefs[field] = records
    await UserMongoDB.update_preferences(user_id, prefs)
    return {"success": True, "persisted": True, "field": field, "records": records}
