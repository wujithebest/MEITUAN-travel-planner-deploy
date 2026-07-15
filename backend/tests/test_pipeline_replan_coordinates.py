from services.pipeline_replan_service import (
    _insert_add_point,
    _is_curated_fixed_route_candidate,
    _normalize_polyline_order,
)


def test_normalize_polyline_keeps_api_client_lat_lng_contract():
    raw = [[31.282555, 121.502421], [31.246961, 121.497665]]
    normalized = _normalize_polyline_order(
        raw,
        {"lng": 121.50225, "lat": 31.282587},
        {"lng": 121.497835, "lat": 31.246664},
    )
    assert normalized == raw


def test_normalize_polyline_converts_provider_lng_lat_to_lat_lng():
    raw = [[121.502421, 31.282555], [121.497665, 31.246961]]
    normalized = _normalize_polyline_order(
        raw,
        {"lng": 121.50225, "lat": 31.282587},
        {"lng": 121.497835, "lat": 31.246664},
    )
    assert normalized == [[31.282555, 121.502421], [31.246961, 121.497665]]


def test_curated_fixed_route_candidate_can_overlap_parent_anchor_location():
    points = [{
        "poi_id": "fixed-798艺术区",
        "name": "798艺术区",
        "location": "116.4958,39.9848",
    }]
    candidate = {
        "poi_id": "B0FFF37KNR",
        "name": "Cup Gallery(酒仙桥店)",
        "location": {"lng": 116.49582, "lat": 39.984762},
    }

    result = _insert_add_point(
        points,
        candidate,
        allow_curated_candidate_overlap=True,
    )

    assert [point["name"] for point in result] == ["798艺术区", "Cup Gallery(酒仙桥店)"]


def test_regular_nearby_duplicate_still_skips_add():
    points = [{
        "poi_id": "fixed-798艺术区",
        "name": "798艺术区",
        "location": "116.4958,39.9848",
    }]
    candidate = {
        "poi_id": "B0FFF37KNR",
        "name": "Cup Gallery(酒仙桥店)",
        "location": {"lng": 116.49582, "lat": 39.984762},
    }

    result = _insert_add_point(points, candidate)

    assert result == points


def test_fixed_route_candidate_is_recognized_without_frontend_metadata():
    assert _is_curated_fixed_route_candidate(
        "fixed-literary-photo-cafe-hengji-v1",
        {"poi_id": "B0FFF37KNR", "name": "Cup Gallery(酒仙桥店)"},
    )
    assert not _is_curated_fixed_route_candidate(
        "another-route",
        {"poi_id": "B0FFF37KNR", "name": "Cup Gallery(酒仙桥店)"},
    )
