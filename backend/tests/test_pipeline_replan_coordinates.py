from services.pipeline_replan_service import _normalize_polyline_order


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
