"""Fixed-route snapshot integrity tests."""
from __future__ import annotations

from services.fixed_route_service import ALLOWED_FIXTURE_IDS, get_fixed_route


def test_all_fixed_routes_are_real_snapshots() -> None:
    assert len(ALLOWED_FIXTURE_IDS) == 6
    for fixture_id in ALLOWED_FIXTURE_IDS:
        fixture = get_fixed_route(fixture_id)
        assert fixture is not None, fixture_id
        assert fixture["origin"]["label"] == "恒基伟业大厦"
        assert fixture["route_data"]["points"]
        assert fixture["route_data"]["segments"]
        assert fixture["map_route_data"]["markers"]
        assert fixture["map_route_data"]["polylines"]
        assert fixture["panel_days"]
        assert fixture["summary"]["poi_count"] > 0


def test_fixed_route_rejects_unknown_fixture() -> None:
    assert get_fixed_route("../../etc/passwd") is None
    assert get_fixed_route("not-a-fixed-route") is None
