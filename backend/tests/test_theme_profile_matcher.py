"""Tests for theme_profile_matcher — exact activity terms, ranking, resolution."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.theme_profile_matcher import (
    rank_theme_profiles,
    resolve_theme_profile,
    term_matches,
    audit_theme_profile_library,
    get_all_theme_profiles,
)


def test_term_matches_chinese_contains():
    assert term_matches("明天去玩剧本杀", "剧本杀") is True
    assert term_matches("想去密室逃脱玩", "密室逃脱") is True
    assert term_matches("剧本杀两字", "剧本") is True
    assert term_matches("剧本杀", "桌游剧本杀") is False  # no reverse contain


def test_term_matches_empty():
    assert term_matches("", "剧本杀") is False
    assert term_matches("剧本杀", "") is False


def test_unique_exact_activity_script_kill():
    """'剧本杀' should force sports_recreation via rule_exact."""
    decision = resolve_theme_profile(llm_profile=None, raw_text="明天去玩剧本杀")
    assert decision.profile_id == "sports_recreation"
    assert decision.source == "rule_exact"
    assert decision.reason == "unique_exact_activity_term"
    assert decision.confidence == 1.0


def test_unique_exact_activity_escape_room():
    decision = resolve_theme_profile(llm_profile=None, raw_text="去密室逃脱")
    assert decision.profile_id == "sports_recreation"
    assert decision.source == "rule_exact"


def test_unique_exact_activity_board_game_shop():
    decision = resolve_theme_profile(llm_profile=None, raw_text="找一家最近的剧本杀店")
    assert decision.profile_id == "sports_recreation"
    assert decision.source == "rule_exact"


def test_unique_exact_activity_old_cinema():
    decision = resolve_theme_profile(llm_profile=None, raw_text="想去老电影院")
    assert decision.profile_id == "film_location_media"
    assert decision.source == "rule_exact"


def test_unique_exact_activity_film_archive():
    decision = resolve_theme_profile(llm_profile=None, raw_text="参观电影资料馆")
    assert decision.profile_id == "film_location_media"
    assert decision.source == "rule_exact"


def test_exact_overrides_llm():
    """LLM says film_location_media, but exact term should force sports_recreation."""
    decision = resolve_theme_profile(
        llm_profile="film_location_media",
        raw_text="明天去玩剧本杀",
    )
    assert decision.profile_id == "sports_recreation"
    assert decision.source == "rule_exact"


def test_role_play_not_exact():
    """'角色扮演' must NOT trigger rule_exact — it's a generic term."""
    decision = resolve_theme_profile(llm_profile=None, raw_text="想体验角色扮演")
    assert decision.source != "rule_exact"


def test_no_theme_fallback():
    """No clear theme → None."""
    decision = resolve_theme_profile(llm_profile=None, raw_text="周末随便逛逛，找点有意思的")
    assert decision.profile_id is None
    assert decision.source == "generic_fallback"


def test_auxiliary_cannot_trigger_exact():
    """auxiliary text must NOT trigger exact_activity match."""
    decision = resolve_theme_profile(
        llm_profile=None,
        raw_text="周末出去玩",
        auxiliary_text="电影 摄影 角色扮演 影视取景地",
    )
    # raw_text has no exact term, so no rule_exact
    assert decision.source != "rule_exact"


def test_rank_stable_sorting():
    """Same input → same output order."""
    r1 = rank_theme_profiles(raw_text="户外运动 骑行")
    r2 = rank_theme_profiles(raw_text="户外运动 骑行")
    ids1 = tuple(c.profile_id for c in r1)
    ids2 = tuple(c.profile_id for c in r2)
    assert ids1 == ids2


def test_rank_returns_candidates():
    candidates = rank_theme_profiles(raw_text="文艺 美术馆")
    assert len(candidates) > 0
    top = candidates[0]
    assert top.score > 0
    assert len(top.matched_terms) > 0


def test_llm_ambiguous_selects_top3():
    """LLM picks a valid top-3 candidate in ambiguous case."""
    candidates = rank_theme_profiles(raw_text="想体验角色扮演")
    top3_ids = {c.profile_id for c in candidates[:3]}
    if candidates and candidates[0].score >= 8 and candidates[0].score < 20:
        # If ambiguous, LLM choosing top3 should work
        for pid in list(top3_ids)[:1]:
            decision = resolve_theme_profile(
                llm_profile=pid,
                raw_text="想体验角色扮演",
            )
            if decision.source == "llm_ambiguous":
                assert decision.profile_id == pid
                assert decision.confidence == 0.65


def test_llm_not_in_top3_fallback():
    """LLM not in top 3 → generic_fallback."""
    decision = resolve_theme_profile(
        llm_profile="religion_prayer",
        raw_text="周末随便逛逛",
    )
    assert decision.source == "generic_fallback"


# ── Audit tests ──


def test_audit_no_duplicate_exact_terms():
    issues = audit_theme_profile_library()
    dupes = [i for i in issues if i["type"] == "duplicate_exact_activity_term"]
    assert len(dupes) == 0, f"Duplicate exact activity terms found: {dupes}"


def test_audit_no_forbidden_exact_terms():
    issues = audit_theme_profile_library()
    forbidden = [i for i in issues if i["type"] == "forbidden_exact_term"]
    assert len(forbidden) == 0, f"Forbidden exact terms found: {forbidden}"


def test_audit_no_required_excluded_conflict():
    issues = audit_theme_profile_library()
    conflicts = [i for i in issues if i["type"] == "required_excluded_conflict"]
    assert len(conflicts) == 0, f"Required/excluded conflicts: {conflicts}"


def test_audit_no_missing_labels():
    issues = audit_theme_profile_library()
    missing = [i for i in issues if i["type"] == "missing_label"]
    assert len(missing) == 0, f"Missing labels: {missing}"
