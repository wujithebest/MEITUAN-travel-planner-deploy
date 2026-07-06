import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_schema import ParsedIntent
from services.step1_intent import _apply_casual_rest_intent


def test_casual_rest_final_lock_preserves_area_and_removes_abstract_query() -> None:
    parsed = ParsedIntent(
        duration="a quarter day",
        poi_query_type="poi_category",
        category_id=None,
        primary_query="随意自在的地方坐着",
        activity_facet="casual_rest_stop",
        search_area_label="清华大学",
        search_area_location={"lat": 40.003213, "lng": 116.326936},
        proximity_requested=True,
        required_features=["sittable", "casual_atmosphere"],
        search_keywords=["北京 随意自在的地方坐着"],
        other_constraints=["随意", "不排队", "不用预约", "不走远"],
        micro_excluded_terms=["网红", "排队", "预约", "私人会所"],
    )

    _apply_casual_rest_intent(
        parsed,
        "北京市",
        "我不想打扮，在清华周围找个随意自在的地方坐着",
    )

    assert parsed.poi_query_type == "theme_route"
    assert parsed.primary_query == ""
    assert parsed.activity_facet == "rest_stop"
    assert parsed.rest_stop_requested is True
    assert parsed.search_area_label == "清华大学"
    assert parsed.search_area_location == {"lat": 40.003213, "lng": 116.326936}
    assert parsed.required_features == ["sittable"]
    assert "casual_atmosphere" in parsed.preferred_features
    assert all("随意自在的地方坐着" not in keyword for keyword in parsed.search_keywords)
    assert all(keyword.startswith("清华大学附近 ") for keyword in parsed.search_keywords)
    assert parsed.micro_excluded_terms == []
    assert "不排队" not in parsed.other_constraints
    assert "不用预约" not in parsed.other_constraints
    assert "不走远" not in parsed.other_constraints


def test_casual_rest_keeps_explicit_negative_preference() -> None:
    parsed = ParsedIntent(
        duration="a quarter day",
        micro_excluded_terms=["网红", "排队", "预约"],
    )

    _apply_casual_rest_intent(
        parsed,
        "北京市",
        "附近找个不用预约、不想排队的地方坐坐，不要网红店",
    )

    assert "网红" in parsed.micro_excluded_terms
    assert "排队" in parsed.micro_excluded_terms
    assert "预约" in parsed.micro_excluded_terms
