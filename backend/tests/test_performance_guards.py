import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_schema import ExtractedPlace, FixedPoi, ParsedIntent
from services import api_client, step1_intent, step2_macro


def test_fixed_pois_override_home_city_and_use_local_start(monkeypatch) -> None:
    async def fake_search(name: str, city: str = "", **kwargs):
        locations = {
            "南京路步行街": {"lat": 31.234, "lng": 121.475},
            "陆家嘴": {"lat": 31.239, "lng": 121.499},
        }
        return [{
            "name": name,
            "location": locations[name],
            "typecode": "110000",
            "cityname": "上海市",
            "pname": "上海市",
        }]

    async def fake_status(*args, **kwargs):
        return None

    monkeypatch.setattr(step1_intent, "gaode_text_search", fake_search)
    monkeypatch.setattr(step1_intent, "emit_status", fake_status)

    parsed = ParsedIntent(
        duration="a full day",
        fixed_pois=[FixedPoi(name="南京路步行街"), FixedPoi(name="陆家嘴")],
        original_location={"lat": 39.996548, "lng": 116.3328, "label": "清华大学(东南门)"},
        resolved_city="北京市",
    )

    asyncio.run(step1_intent._fixed_budget(parsed, "北京市", "上午南京路，下午陆家嘴"))

    assert parsed.resolved_city == "上海市"
    assert parsed.original_location["label"] == "南京路步行街附近"
    assert parsed.original_location["lat"] == 31.234


def test_route_timeout_degrades_to_haversine_estimate(monkeypatch) -> None:
    async def slow_route(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {"duration_min": 1}

    monkeypatch.setattr(step2_macro, "_route_from_origin", slow_route)
    parsed = ParsedIntent(
        duration="a quarter day",
        original_location={"lat": 39.99, "lng": 116.33},
    )
    place = ExtractedPlace(
        name="测试公园",
        time_capacity="quarter_day",
        typecode="110101",
        location={"lat": 40.00, "lng": 116.34},
        gaode_poi_id="test-park",
    )

    result = asyncio.run(
        step2_macro._route_from_origin_bounded(
            parsed, place, "北京市", timeout_seconds=0.001,
        )
    )

    assert result is not None
    assert result["degraded"] is True
    assert result["polyline_source"] == "haversine_estimate"
    assert result["duration_min"] >= 5


def test_malformed_route_result_degrades_to_haversine_estimate(monkeypatch) -> None:
    async def malformed_route(*args, **kwargs):
        return "unexpected route payload"

    monkeypatch.setattr(step2_macro, "_route_from_origin", malformed_route)
    parsed = ParsedIntent(
        duration="a quarter day",
        original_location={"lat": 39.99, "lng": 116.33},
    )
    place = ExtractedPlace(
        name="测试饭馆",
        time_capacity="quarter_day",
        typecode="050000",
        location={"lat": 40.00, "lng": 116.34},
        gaode_poi_id="test-restaurant",
    )

    result = asyncio.run(
        step2_macro._route_from_origin_bounded(
            parsed, place, "北京市", timeout_seconds=0.1,
        )
    )

    assert result is not None
    assert result["degraded"] is True
    assert result["polyline_source"] == "haversine_estimate"
    assert step2_macro._route_duration_minutes("unexpected route payload") is None


def test_gaode_non_object_response_is_reported_as_external_api_error() -> None:
    with pytest.raises(api_client.ExternalAPIError, match="返回格式异常"):
        api_client._check_gaode_response("unexpected response", "周边搜索")
