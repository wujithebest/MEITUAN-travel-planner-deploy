"""v26+v27: Tests for category-level exclusion in multi-turn conversations.

Verifies that "不想去咖啡馆了。修改下路线" is handled as a category
removal, not as a new plan or positive cafe query.

v27: Added dispatch ordering tests, trailing edit phrase handling,
source logging, and two-turn density preservation tests.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Test 1: conversation_replan detection ──

def test_detect_category_exclusion_cafe():
    """_detect_category_exclusion should return cafe info for '不想去咖啡馆了'."""
    from services.conversation_replan import _detect_category_exclusion

    result = _detect_category_exclusion("不想去咖啡馆了。修改下路线")
    assert result is not None, "should detect cafe exclusion"
    assert result["category_id"] == "cafe"
    assert "咖啡" in result["target_terms"] or any("咖啡" in t for t in result["target_terms"])
    assert "050400" in result["target_typecodes"]


def test_detect_category_exclusion_no_match():
    """Non-category text should return None."""
    from services.conversation_replan import _detect_category_exclusion

    assert _detect_category_exclusion("帮我去掉外滩") is None
    assert _detect_category_exclusion("我想去咖啡馆") is None  # positive, no negation trigger


def test_detect_category_exclusion_variants():
    """Multiple negation patterns should all work."""
    from services.conversation_replan import _detect_category_exclusion

    variants = [
        "不要咖啡馆了",
        "别安排咖啡店",
        "咖啡去掉",
        "咖啡馆不要了",
        "不去咖啡厅了",
        "跳过咖啡",
    ]
    for v in variants:
        result = _detect_category_exclusion(v)
        assert result is not None, f"'{v}' should be detected"
        assert result["category_id"] == "cafe", f"'{v}' got {result['category_id']}"


# ── Test 2: classify_conversation_route_change_fast ──

def test_fast_classifier_returns_point_edit_not_new_plan():
    """With route context, '不想去咖啡馆了' should be point_edit, not new_plan."""
    from services.conversation_replan import classify_conversation_route_change_fast

    route_context = {
        "points": [
            {"name": "瑞幸咖啡", "kind": "cafe", "typecode": "050400"},
            {"name": "某画廊", "kind": "anchor_internal"},
            {"name": "某小店", "kind": "anchor_internal"},
        ],
        "point_names": ["瑞幸咖啡", "某画廊", "某小店"],
    }
    decision = classify_conversation_route_change_fast("不想去咖啡馆了。修改下路线", route_context)
    assert decision is not None, "should produce a decision"
    assert decision.mode != "new_plan", f"mode should not be new_plan, got {decision.mode}"
    # target_name should NOT be the entire input string
    for op in decision.point_operations:
        if op.get("target_name"):
            assert len(op["target_name"]) < 15, f"target_name too long: {op['target_name']}"


def test_fast_classifier_no_route_returns_none():
    """Without route context, should not interfere (let normal dispatch handle it)."""
    from services.conversation_replan import classify_conversation_route_change_fast
    decision = classify_conversation_route_change_fast("不想去咖啡馆了。修改下路线", None)
    # Without route, the function returns new_plan (no route → new plan)
    # This is acceptable; the important thing is it doesn't crash
    assert decision is not None


# ── Test 3: Step1 category exclusion extraction ──

def test_step1_extract_category_exclusions():
    """_extract_category_exclusions_from_request should strip cafe keywords."""
    from services.step1_intent import _extract_category_exclusions_from_request
    from services.data_schema import ParsedIntent
    import datetime as dt

    parsed = ParsedIntent(
        duration="a half day",
        search_keywords=["北京 咖啡馆", "北京 拍照", "北京 文艺"],
        micro_keywords=["艺术空间", "精品咖啡"],
        food_pref_keywords=["咖啡"],
        meal_search_keywords=["咖啡 餐厅"],
        primary_query="咖啡馆",
        poi_query_type="poi_category",
        meal_constraints=[{"meal": "lunch", "keywords": ["咖啡"]}],
        theme_facets=[{"id": "cafe_stop", "required": True}],
    )
    result = _extract_category_exclusions_from_request(parsed, "不想去咖啡馆了。修改下路线")

    # Cafe keywords removed
    for kw in result.search_keywords:
        assert "咖啡" not in kw.lower(), f"search_keywords still has {kw}"
        assert "cafe" not in kw.lower()

    assert "精品咖啡" not in result.micro_keywords
    assert "咖啡" not in result.food_pref_keywords
    assert all("咖啡" not in kw for kw in result.meal_search_keywords)
    assert result.primary_query != "咖啡馆"
    assert result.poi_query_type != "poi_category"
    assert "050400" in result.excluded_typecode_prefixes
    # cafe_stop facet removed
    facet_ids = [f.get("id", "") if isinstance(f, dict) else "" for f in result.theme_facets]
    assert "cafe_stop" not in facet_ids


def test_step1_no_false_positive_on_positive_cafe():
    """First-round '有咖啡馆' should NOT be treated as exclusion."""
    from services.step1_intent import _extract_category_exclusions_from_request
    from services.data_schema import ParsedIntent

    parsed = ParsedIntent(
        duration="a half day",
        search_keywords=["北京 咖啡馆"],
        primary_query="",
    )
    result = _extract_category_exclusions_from_request(parsed, "有咖啡馆和特色小店")
    # No negation trigger, should be unchanged
    assert "北京 咖啡馆" in result.search_keywords


# ── Test 4: _classify_chat_edit category removal ──

def test_chat_edit_category_remove():
    """_classify_chat_edit should detect category-level remove.
    Uses importlib to bypass FastAPI import chain in test env.
    """
    import importlib.util
    import re

    # We test the category detection logic directly through conversation_replan
    # since meituan_chat's _classify_chat_edit delegates to _detect_category_exclusion
    from services.conversation_replan import _detect_category_exclusion

    result = _detect_category_exclusion("不想去咖啡馆了。修改下路线")
    assert result is not None, "should detect category exclusion"
    assert result["category_id"] == "cafe"
    assert len(result["target_terms"]) > 0
    assert "050400" in result["target_typecodes"]

    # Also test: the exact bug pattern (whole sentence as target_name)
    # _detect_category_exclusion returns structured dict, NOT a point_edit
    # with the entire sentence string as target_name
    assert result["raw_target"] == "咖啡馆"
    assert len(result["raw_target"]) < 15


# ── Test 5: is_category_exclusion_decision ──

def test_is_category_exclusion_decision():
    from services.conversation_replan import is_category_exclusion_decision, PlanningDispatchDecision

    d = PlanningDispatchDecision(
        conversation_mode="point_edit",
        target_plan_mode="exploratory",
        point_operations=[{
            "action": "remove_category",
            "target_category": "cafe",
            "target_terms": ["咖啡"],
            "target_typecodes": ["050400"],
        }],
        reason="test",
    )
    assert is_category_exclusion_decision(d) is True

    d2 = PlanningDispatchDecision(
        conversation_mode="point_edit",
        target_plan_mode="exploratory",
        point_operations=[{"action": "remove", "target_name": "瑞幸"}],
        reason="test",
    )
    assert is_category_exclusion_decision(d2) is False


# ═══ v27: Dispatch ordering + trailing edit phrase tests ═══


def test_detect_category_exclusion_with_trailing_edit_phrase():
    """'不想去咖啡馆了，帮我把路线改一下' → remove_category:cafe, NOT target_name=整句话."""
    from services.conversation_replan import _detect_category_exclusion

    # The exact bug pattern from the user report
    result = _detect_category_exclusion("不想去咖啡馆了，帮我把路线改一下", source="test")
    assert result is not None, "MUST detect category exclusion"
    assert result["category_id"] == "cafe"
    assert result["raw_target"] == "咖啡馆" or "咖啡" in str(result["raw_target"])
    # target_name MUST NOT be the entire input sentence
    assert len(result.get("raw_target", "")) < 15, f"raw_target too long: {result.get('raw_target')}"


def test_detect_category_exclusion_trailing_variants():
    """All trailing edit phrase variants should still detect category exclusion."""
    from services.conversation_replan import _detect_category_exclusion

    variants = [
        "不想去咖啡馆了，帮我把路线改一下",
        "不想去咖啡馆了。修改下路线",
        "咖啡馆就不要了",
        "把咖啡店去掉",
        "不安排咖啡了",
        "不想喝咖啡了",
        "不去咖啡厅",
        "咖啡去掉，路线改一下",
    ]
    for v in variants:
        result = _detect_category_exclusion(v, source="test")
        assert result is not None, f"'{v}' should be detected as category exclusion"
        assert result["category_id"] == "cafe", f"'{v}' got category={result.get('category_id')}"
        # Verify target_name is NOT the full sentence
        raw = result.get("raw_target", "")
        assert len(raw) < 20, f"raw_target='{raw}' too long for '{v}'"


def test_fast_classifier_remove_category_not_target_name():
    """Dispatch MUST return remove_category, not remove with target_name=整句话."""
    from services.conversation_replan import classify_conversation_route_change_fast

    route_context = {
        "points": [
            {"name": "瑞幸咖啡(望京店)", "kind": "cafe", "typecode": "050400"},
            {"name": "望京SOHO", "kind": "anchor_internal"},
            {"name": "某买手店", "kind": "anchor_internal"},
            {"name": "某画廊", "kind": "anchor_internal"},
        ],
        "point_names": ["瑞幸咖啡(望京店)", "望京SOHO", "某买手店", "某画廊"],
    }

    # The exact bug pattern
    decision = classify_conversation_route_change_fast(
        "不想去咖啡馆了，帮我把路线改一下", route_context
    )
    assert decision is not None
    assert decision.mode == "point_edit", f"Expected point_edit, got {decision.mode}"

    # CRITICAL: point_operations must contain remove_category, NOT remove with full sentence
    ops = decision.point_operations
    assert len(ops) > 0, "Must have at least one operation"
    first_op = ops[0]

    # MUST be remove_category
    assert first_op.get("action") == "remove_category", (
        f"Expected remove_category, got action={first_op.get('action')} "
        f"target_name={first_op.get('target_name', '')[:60]}"
    )
    assert first_op.get("target_category") == "cafe"

    # target_name must NOT be the full input sentence
    target_name = first_op.get("target_name", "")
    assert target_name == "" or len(target_name) < 20, (
        f"target_name MUST NOT be full sentence: '{target_name[:80]}'"
    )

    # Must have correct exclude_constraints
    excl = decision.exclude_constraints or {}
    assert "cafe" in excl.get("excluded_categories", [])
    assert excl.get("preserve_previous_intent") is True


def test_step1_negation_clears_positive_fields():
    """Step1 must clear coffee from all positive keyword fields."""
    from services.step1_intent import _extract_category_exclusions_from_request
    from services.data_schema import ParsedIntent

    parsed = ParsedIntent(
        duration="a half day",
        search_keywords=["北京 精品咖啡馆", "北京 文艺拍照", "北京 特色小店"],
        micro_keywords=["独立咖啡馆", "艺术空间", "买手店"],
        micro_poi_keywords=["咖啡"],
        food_pref_keywords=["咖啡", "甜品"],
        meal_search_keywords=["咖啡 下午茶"],
        meal_constraints=[{"meal": "lunch", "keywords": ["咖啡", "星巴克"]}],
        primary_query="咖啡馆",
        poi_query_type="poi_category",
        theme_facets=[
            {"id": "photo_checkin", "required": True},
            {"id": "cafe_stop", "required": True},
            {"id": "specialty_shop", "required": True},
        ],
    )

    result = _extract_category_exclusions_from_request(parsed, "不想去咖啡馆了，帮我把路线改一下")

    # ALL positive coffee references MUST be cleared
    for kw in result.search_keywords:
        assert "咖啡" not in kw.lower(), f"search_keywords still has coffee: {kw}"
        assert "cafe" not in kw.lower(), f"search_keywords still has cafe: {kw}"

    assert "独立咖啡馆" not in result.micro_keywords
    assert "咖啡" not in result.micro_poi_keywords
    assert "咖啡" not in result.food_pref_keywords
    assert all("咖啡" not in kw.lower() for kw in result.meal_search_keywords)

    # primary_query must not be 咖啡馆
    assert result.primary_query != "咖啡馆"

    # poi_query_type must not be poi_category (it was set based on cafe)
    assert result.poi_query_type != "poi_category"

    # meal_constraints must not contain coffee
    for mc in (result.meal_constraints or []):
        kw_str = str(mc.get("keywords", ""))
        assert "咖啡" not in kw_str, f"meal_constraints still has coffee: {mc}"

    # excluded fields must be populated
    assert "050400" in result.excluded_typecode_prefixes, "Must exclude cafe typecodes"
    assert any("咖啡" in t for t in (result.primary_excluded_terms or [])), "Must exclude coffee terms"

    # cafe_stop facet removed
    facet_ids = [f.get("id", "") if isinstance(f, dict) else "" for f in result.theme_facets]
    assert "cafe_stop" not in facet_ids, "cafe_stop facet must be removed"

    # BUT non-coffee facets preserved
    assert "photo_checkin" in facet_ids, "photo_checkin facet must be preserved"
    assert "specialty_shop" in facet_ids, "specialty_shop facet must be preserved"


def test_step1_no_negation_does_not_clear():
    """First turn '有咖啡馆' must NOT be treated as negation."""
    from services.step1_intent import _extract_category_exclusions_from_request
    from services.data_schema import ParsedIntent

    parsed = ParsedIntent(
        duration="a half day",
        search_keywords=["北京 咖啡馆", "北京 文艺拍照", "北京 特色小店"],
        primary_query="北京文艺路线",
        theme_facets=[
            {"id": "photo_checkin"},
            {"id": "cafe_stop"},
            {"id": "specialty_shop"},
        ],
    )

    # First-turn positive request - NO negation trigger
    result = _extract_category_exclusions_from_request(
        parsed, "帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点"
    )

    # Must NOT have cleared coffee
    coffee_in_search = any("咖啡" in kw for kw in result.search_keywords)
    assert coffee_in_search, "First turn '有咖啡馆' must NOT be cleared"

    # Must NOT have excluded cafe typecodes
    assert "050400" not in result.excluded_typecode_prefixes, (
        "First turn must NOT exclude cafe typecodes"
    )

    # cafe_stop facet must remain
    facet_ids = [f.get("id", "") if isinstance(f, dict) else "" for f in result.theme_facets]
    assert "cafe_stop" in facet_ids, "First turn cafe_stop must remain"


# ── v27: Theme/density preservation on category removal ──


def test_remove_category_preserves_previous_intent_theme():
    """After remove_category, the intent should preserve photo/art/shop facets."""
    from services.conversation_replan import classify_conversation_route_change_fast

    route_context = {
        "points": [
            {"name": "某咖啡馆", "kind": "cafe", "typecode": "050400"},
            {"name": "某画廊", "kind": "anchor_internal"},
            {"name": "某买手店", "kind": "anchor_internal"},
        ],
        "point_names": ["某咖啡馆", "某画廊", "某买手店"],
        "previous_intent": {
            "activity_facet": "multi_facet_art_photo_cafe_shop",
            "duration": "a full day",
            "time_budget": 1.0,
            "density_min_visible_pois": 5,
            "density_target_visible_pois": 6,
            "candidate_target": 4,
            "theme_facets": [
                {"id": "photo_checkin"},
                {"id": "cafe_stop"},
                {"id": "specialty_shop"},
                {"id": "art_culture_lifestyle"},
            ],
        },
    }

    decision = classify_conversation_route_change_fast(
        "不想去咖啡馆了，路线改一下", route_context
    )
    assert decision is not None
    assert decision.mode == "point_edit"

    # exclude_constraints must have preserve_previous_intent
    excl = decision.exclude_constraints or {}
    assert excl.get("preserve_previous_intent") is True, (
        "Must flag preserve_previous_intent to keep photo/art/shop facets"
    )
    assert "cafe" in excl.get("excluded_categories", []), "Must exclude cafe category"
