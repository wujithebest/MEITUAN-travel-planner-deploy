"""Regression coverage for nearby souvenir requests with sparse child POIs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_schema import ParsedIntent, SubAnchor
from services.step3_micro import _fill_segment


def test_souvenir_anchor_stays_visible_when_micro_search_degrades_to_free():
    intent = ParsedIntent.model_construct(
        poi_query_type="theme_route",
        activity_facet="souvenir_shopping",
        souvenir_requested=True,
        required_features=[],
        lawn_rest_requested=False,
    )
    anchor = SubAnchor(
        parent_name="吴裕泰茶庄(五道口购物中心店)",
        name="吴裕泰茶庄(五道口购物中心店)",
        location={"lat": 39.992004, "lng": 116.33938},
        typecode="061200",
        category="购物服务",
        internal_pois=[],
        degradation_level="free",
    )

    points = _fill_segment(
        {"sub_anchor": anchor, "degradation": "free", "hint": ""},
        meal_poi_name=None,
        start_location={"lat": 39.996548, "lng": 116.3328},
        time_budget_min=120,
        day_index=1,
        used_names=set(),
        parsed_intent=intent,
    )

    assert len(points) == 1
    assert points[0]["name"] == anchor.name
    assert points[0]["kind"] == "shopping"
    assert points[0]["category"] == "souvenir"
    assert points[0]["is_display_poi"] is True
    assert points[0]["is_waypoint"] is True
    assert points[0]["souvenir_anchor_fallback"] is True

