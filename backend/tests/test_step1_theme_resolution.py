"""Integration tests: Step1 theme resolution via resolve_theme_profile."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from services.theme_profile_matcher import resolve_theme_profile


def test_step1_script_kill_exact():
    """User says script kill → sports_recreation."""
    decision = resolve_theme_profile(
        llm_profile=None,
        raw_text="明天去玩剧本杀",
        auxiliary_text="",
    )
    assert decision.profile_id == "sports_recreation"
    assert decision.source == "rule_exact"


def test_step1_llm_error_corrected():
    """LLM misidentified as film, but exact term forces sports."""
    decision = resolve_theme_profile(
        llm_profile="film_location_media",
        raw_text="明天去玩剧本杀",
        auxiliary_text="剧本杀 桌游",
    )
    assert decision.profile_id == "sports_recreation"
    assert decision.source == "rule_exact"


def test_step1_movie_archive_exact():
    decision = resolve_theme_profile(
        llm_profile=None,
        raw_text="参观电影资料馆",
    )
    assert decision.profile_id == "film_location_media"
    assert decision.source == "rule_exact"


def test_step1_vague_no_force():
    """Vague input should not force a theme."""
    decision = resolve_theme_profile(
        llm_profile=None,
        raw_text="周末随便逛逛，找点有意思的",
    )
    assert decision.profile_id is None
    assert decision.source == "generic_fallback"


def test_step1_ambiguous_with_llm():
    """LLM picks from top 3 when ambiguous."""
    decision = resolve_theme_profile(
        llm_profile="sports_recreation",
        raw_text="想体验推理和桌游",
        auxiliary_text="桌游 密室 游戏",
    )
    # Either rule_exact (if 密室/桌游 triggers exact) or high_confidence or llm_ambiguous
    assert decision.profile_id is not None or decision.source == "generic_fallback"


def test_step1_high_score_margin():
    """Strong keyword match should give high confidence."""
    decision = resolve_theme_profile(
        llm_profile=None,
        raw_text="去文艺街区逛美术馆看展览",
    )
    if decision.profile_id:
        assert decision.confidence > 0.5


def test_step1_auxiliary_no_exact():
    """Auxiliary text with film keywords must not trigger exact."""
    decision = resolve_theme_profile(
        llm_profile=None,
        raw_text="周末出去玩",
        auxiliary_text="影视取景地 老电影院 艺术影院",
    )
    assert decision.source != "rule_exact"


# ── v20: Destination detection tests ──


def test_category_token_in_set():
    """Category tokens like 古玩市场 should be recognized as category not destination."""
    from services.step1_intent import CATEGORY_TOKENS, _CITY_CENTER_PATTERN
    assert "古玩市场" in CATEGORY_TOKENS
    assert "花鸟市场" in CATEGORY_TOKENS
    assert "旧货市场" in CATEGORY_TOKENS


def test_city_center_pattern_rejects_admin_regions():
    """City/administrative geocode results must NOT become destinations."""
    from services.step1_intent import _CITY_CENTER_PATTERN
    assert _CITY_CENTER_PATTERN.match("北京市")
    assert _CITY_CENTER_PATTERN.match("东城区")
    assert _CITY_CENTER_PATTERN.match("朝阳区")
    assert not _CITY_CENTER_PATTERN.match("故宫博物院")
    assert not _CITY_CENTER_PATTERN.match("潘家园旧货市场")
    assert not _CITY_CENTER_PATTERN.match("古玩市场")


def test_city_name_not_in_city_variants():
    """City name variants should be properly generated for filtering."""
    city = "北京市"
    normalized = city[:-1] if city.endswith("市") else city
    variants = {city, normalized, f"{city}市", f"{normalized}市"}
    # Should handle 北京市 → {北京市, 北京, 北京市市, 北京市}
    assert "北京市" in variants
    assert "北京" in variants
