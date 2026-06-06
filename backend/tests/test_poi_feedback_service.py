import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.poi_feedback_service import calculate_feedback_score


def test_feedback_weights_are_directional():
    now = datetime(2026, 6, 3, tzinfo=timezone.utc)
    records = {
        "poi_likes": [{"poi_id": "p1", "poi_name": "A", "timestamp": now.isoformat(), "hit_count": 1}],
        "poi_dislikes": [{"poi_id": "p2", "poi_name": "B", "timestamp": now.isoformat(), "hit_count": 1}],
        "poi_removes": [{"poi_id": "p3", "poi_name": "C", "timestamp": now.isoformat(), "hit_count": 1}],
    }

    liked = calculate_feedback_score(records, poi_id="p1", poi_name="A", now=now)
    neutral = calculate_feedback_score(records, poi_id="p0", poi_name="Z", now=now)
    deleted = calculate_feedback_score(records, poi_id="p3", poi_name="C", now=now)
    disliked = calculate_feedback_score(records, poi_id="p2", poi_name="B", now=now)

    assert liked > neutral > deleted > disliked


def test_feedback_time_decay_halves_after_30_days():
    now = datetime(2026, 6, 3, tzinfo=timezone.utc)
    records = {
        "poi_likes": [
            {"poi_id": "p1", "poi_name": "A", "timestamp": (now - timedelta(days=30)).isoformat(), "hit_count": 1}
        ],
        "poi_dislikes": [],
        "poi_removes": [],
    }

    assert calculate_feedback_score(records, poi_id="p1", poi_name="A", now=now) == 4.0
