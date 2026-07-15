import asyncio

from services import api_client


def test_around_batch_deduplicates_identical_requests(monkeypatch):
    calls = []

    async def fake_search(**kwargs):
        calls.append(kwargs)
        return [{"id": "poi-1", "name": "测试地点"}]

    monkeypatch.setattr(api_client, "gaode_around_search", fake_search)

    request = {
        "location": "116.40,39.90",
        "keywords": "咖啡馆",
        "radius": 1500,
        "types": "050400",
        "show_fields": "biz_ext",
        "offset": 20,
    }
    results = asyncio.run(api_client.gaode_around_search_batch([request, dict(request)]))

    assert len(calls) == 1
    assert len(results) == 2
    assert results[0] == results[1]


def test_request_cache_reuses_search_and_isolates_result_mutation(monkeypatch):
    calls = []

    async def fake_search(**kwargs):
        calls.append(kwargs)
        return [{"id": "poi-1", "name": "测试地点"}]

    monkeypatch.setattr(api_client, "_gaode_around_search_uncached", fake_search)
    token = api_client.begin_request_search_cache()
    try:
        async def run():
            first = await api_client.gaode_around_search(
                "116.40,39.90", "咖啡馆", radius=1500, types="050400"
            )
            first[0]["temporary_marker"] = True
            second = await api_client.gaode_around_search(
                "116.40, 39.90", "  咖啡馆  ", radius=1500, types="050400"
            )
            return second

        second = asyncio.run(run())
    finally:
        api_client.end_request_search_cache(token)

    assert len(calls) == 1
    assert "temporary_marker" not in second[0]
