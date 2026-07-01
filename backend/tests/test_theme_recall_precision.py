"""Regression tests for city-scoped theme recall and POI relevance gates."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.step3_micro import _is_micro_poi_compatible
from services.city_context import resolve_departure_city
from services.mock_profile import build_profile_from_guest
from services.theme_profile_matcher import (
    build_theme_recall_queries,
    canonicalize_search_keywords,
    get_theme_profile,
    poi_has_competing_theme,
    score_poi_against_theme,
)
from services.theme_profiles import OFFICIAL_THEME_PROFILES
from services.step3_micro import _resolve_micro_poi_policy, _micro_poi_theme_score


def test_search_keywords_use_one_authoritative_city():
    keywords = canonicalize_search_keywords(
        ["北京 文艺街区", "上海 艺术展览", "独立书店", "北京市 创意园区"],
        "北京市",
    )
    assert keywords == [
        "北京 文艺街区",
        "北京 艺术展览",
        "北京 独立书店",
        "北京 创意园区",
    ]


def test_non_municipality_city_suffix_is_canonicalized():
    assert canonicalize_search_keywords(
        ["广州市 文艺街区", "美术馆"],
        "广州市",
    ) == ["广州 文艺街区", "广州 美术馆"]


def test_guest_departure_keeps_structured_city_metadata():
    profile = build_profile_from_guest({
        "home_location": {
            "label": "故宫博物院-神武门",
            "lat": 39.922305,
            "lng": 116.396786,
            "city": "北京市",
            "adcode": "110101",
        },
        "activity_pref_tag": [],
        "food_pref_tag": [],
    })
    assert profile.home_location["city"] == "北京市"
    assert profile.home_location["adcode"] == "110101"
    assert asyncio.run(resolve_departure_city(profile)) == "北京市"


def test_theme_recall_queries_use_generic_terms_only():
    profile = get_theme_profile("art_culture_lifestyle")
    queries = build_theme_recall_queries(profile, "北京市", limit=3)
    assert queries
    assert all(query.startswith("北京 ") for query in queries)
    forbidden_concrete_pois = {"M50", "武康路", "田子坊", "思南公馆", "愚园路"}
    assert not any(term in query for query in queries for term in forbidden_concrete_pois)


def test_legacy_profile_does_not_keep_city_specific_recall_queries():
    profile = OFFICIAL_THEME_PROFILES["art_culture_lifestyle"]
    assert not profile.get("recall_queries")


def test_art_theme_rejects_zoo_identity_and_accepts_art_identity():
    profile = get_theme_profile("art_culture_lifestyle")
    zoo = {
        "name": "北京动物园",
        "address": "西直门外大街",
        "typecode": "110102",
        "category": "风景名胜",
    }
    museum = {
        "name": "中国美术馆",
        "address": "五四大街",
        "typecode": "140100",
        "category": "美术馆",
    }
    zoo_evidence = score_poi_against_theme(zoo, profile, "北京文艺路线也介绍了北京动物园")
    museum_evidence = score_poi_against_theme(museum, profile)
    assert zoo_evidence.accepted is False
    assert zoo_evidence.score == 0
    assert museum_evidence.accepted is True
    assert "美术馆" in museum_evidence.positive_hits


def test_zoo_is_a_competing_theme_for_art_route():
    zoo_internal = {
        "name": "北京动物园-亚运熊猫馆",
        "address": "北京动物园内",
        "typecode": "110102",
        "category": "动物园",
    }
    assert poi_has_competing_theme(zoo_internal, "art_culture_lifestyle") is True


def test_step3_rejects_competing_zoo_poi_from_art_route():
    policy = {
        "active": True,
        "profile_id": "art_culture_lifestyle",
        "preferred_name_terms": ("艺术", "展览", "美术馆", "书店", "画廊"),
        "micro_keywords": ("美术馆", "独立书店", "艺术展览"),
        "excluded_terms": (),
        "generic_penalty_terms": (),
        "preferred_type_prefixes": set(),
        "excluded_typecode_prefixes": set(),
        "reject_unrequested_sports": True,
    }
    zoo_internal = {
        "name": "北京动物园-鸣禽馆",
        "address": "北京动物园内",
        "typecode": "110102",
        "category": "动物园",
    }
    art_exhibition = {
        "name": "如是莫高·敦煌艺术大展",
        "address": "北京展览馆",
        "typecode": "140100",
        "category": "艺术展览",
    }
    assert _is_micro_poi_compatible(zoo_internal, policy) is False
    assert _is_micro_poi_compatible(art_exhibition, policy) is True


def test_family_micro_policy_scores_real_family_destinations():
    class Intent:
        theme_profile = "family_child_friendly"
        theme_confidence = 1.0
        time_budget = 1.0
        micro_poi_keywords = []
        micro_keywords = []
        micro_required_terms = []
        micro_excluded_terms = []
        micro_diversity_hint = []
        search_keywords = []
        raw_keywords = []
        food_pref_keywords = []
        meal_search_keywords = []
        other_constraints = []

    policy = _resolve_micro_poi_policy(Intent())

    assert _micro_poi_theme_score({
        "name": "北京海洋馆", "typecode": "110104", "category": "水族馆"
    }, policy) > 0
    assert _micro_poi_theme_score({
        "name": "北京科学中心", "typecode": "140100", "category": "科技馆"
    }, policy) > 0


def test_production_theme_library_has_no_migrated_shanghai_pois():
    migrated_examples = {
        "M50创意园", "莫干山路50号", "武康路", "田子坊", "思南公馆",
        "豫园", "城隍庙", "四行仓库抗战纪念馆", "上海船厂1862",
    }
    for profile_id in ("art_culture_lifestyle", "history_heritage"):
        profile = get_theme_profile(profile_id)
        serialized = str(profile)
        assert not any(term in serialized for term in migrated_examples)
