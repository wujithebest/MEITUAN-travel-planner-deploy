import asyncio

from services import step2_macro
from services.data_schema import ExtractedPlace, ParsedIntent


def test_optional_bocha_failure_skips_followup_theme_recall(monkeypatch):
    place = ExtractedPlace(
        name="测试公园",
        location={"lat": 39.9, "lng": 116.4},
        typecode="110101",
        time_capacity="quarter_day",
        gaode_poi_id="test-park",
    )
    state = {"available": True, "failure": ""}

    async def failing_bocha(*args, **kwargs):
        raise RuntimeError("transport failure")

    async def unexpected_bocha(*args, **kwargs):
        raise AssertionError("theme recall must not call Bocha after optional enrichment failed")

    monkeypatch.setattr(step2_macro, "bocha_search_batch", failing_bocha)
    enriched = asyncio.run(step2_macro._enrich_places([place], "北京市", state))
    assert enriched == [place]
    assert state["available"] is False

    monkeypatch.setattr(step2_macro, "bocha_search_batch", unexpected_bocha)
    parsed = ParsedIntent(duration="a half day", theme_profile="art_photo")
    recalled = asyncio.run(step2_macro._theme_recall_places(parsed, None, "北京市", state))
    assert recalled == []


def test_macro_search_deduplicates_identical_requests(monkeypatch):
    parsed = ParsedIntent(
        duration="a half day",
        time_budget=0.5,
        original_location={"lat": 39.9, "lng": 116.4},
        search_keywords=["城市公园", "城市公园"],
    )
    captured = []

    async def fake_batch(requests):
        captured.extend(requests)
        return [[] for _ in requests]

    monkeypatch.setattr(step2_macro, "gaode_around_search_batch", fake_batch)
    places = asyncio.run(step2_macro._search_macro_places(parsed))

    assert places == []
    assert len(captured) == 1
    assert captured[0]["keywords"] == "城市公园"
