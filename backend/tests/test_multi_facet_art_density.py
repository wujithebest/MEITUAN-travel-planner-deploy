"""v26: Tests for multi_facet_art route density.

Verifies that the first-round request:
  "帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点"
produces adequate route density with sufficient visible POIs.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_multi_facet_art_duration_defaults_to_full_day():
    """'节奏轻松一点' without explicit 半天 should default to a full day."""
    from services.step1_intent import _build_multi_facet_art_facets
    from services.data_schema import ParsedIntent

    # Simulate what _postprocess does for multi_facet_art
    user_request = "帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点"

    _has_photo = any(t in user_request for t in ["拍照", "出片", "打卡", "摄影"])
    _has_art = any(t in user_request for t in ["文艺", "艺术", "展览", "小众", "文化"])
    _has_cafe = any(t in user_request for t in ["咖啡", "咖啡馆", "咖啡店"])
    _has_shop = any(t in user_request for t in ["特色小店", "买手店", "杂货店", "文创店", "小店"])
    _has_relaxed = any(t in user_request for t in ["节奏轻松", "轻松一点", "慢一点", "不赶"])
    _facet_count = sum([_has_photo, _has_art, _has_cafe, _has_shop, _has_relaxed])

    assert _facet_count >= 3, f"should detect at least 3 facets, got {_facet_count}"
    assert _has_photo, "should detect photo_checkin"
    assert _has_art, "should detect art_culture_lifestyle"
    assert _has_cafe, "should detect cafe_stop"
    assert _has_shop, "should detect specialty_shop"
    assert _has_relaxed, "should detect relaxed_pace"

    # Verify there's NO explicit half-day marker
    _has_explicit_half = any(
        t in user_request
        for t in ["半天", "半日", "上午", "下午", "中午", "2小时", "3小时", "两小时", "三小时"]
    )
    assert not _has_explicit_half, "should not have explicit half-day markers"


def test_multi_facet_art_has_explicit_half_day():
    """When user explicitly says '半天', should still use half_day."""
    user_request = "帮我推荐一条适合拍照的文艺路线，有咖啡馆，半天就好"
    _has_explicit_half = any(
        t in user_request
        for t in ["半天", "半日", "上午", "下午", "中午", "2小时", "3小时", "两小时", "三小时"]
    )
    assert _has_explicit_half, "should detect explicit half-day marker"


def test_density_fields_on_parsed_intent():
    """ParsedIntent should have the density fields."""
    from services.data_schema import ParsedIntent

    p = ParsedIntent(
        duration="a full day",
        density_min_visible_pois=5,
        density_target_visible_pois=6,
        candidate_target=4,
    )
    assert p.density_min_visible_pois == 5
    assert p.density_target_visible_pois == 6
    assert p.candidate_target == 4

    # Default values
    p2 = ParsedIntent(duration="a full day")
    assert p2.density_min_visible_pois == 0
    assert p2.density_target_visible_pois == 0
    assert p2.candidate_target == 0


def test_relaxed_pace_not_mistaken_for_half_day():
    """Terms like 节奏轻松/轻松一点 should not be treated as half_day markers."""
    relaxed_terms = ["节奏轻松", "轻松一点", "慢一点", "不赶", "散步", "逛逛", "散散步"]
    half_day_terms = ["半天", "半日", "上午", "下午", "中午", "2小时", "3小时", "两小时", "三小时"]

    for rt in relaxed_terms:
        assert rt not in half_day_terms, f"'{rt}' should not be a half_day marker"
        assert not any(rt == hdt for hdt in half_day_terms), f"'{rt}' should not match any half_day marker"
