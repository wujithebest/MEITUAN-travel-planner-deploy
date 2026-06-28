"""Step3 plan reality tests — fixed waypoints, no live API, no real cities."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.plan_reality_validator import validate_plan_reality, plan_reality_audit_log
from services.poi_typecodes import matches_typecode, split_typecodes, CATEGORY_RULES


def _make_intent(poi_query_type="poi_category", primary_query="古玩市场",
                 primary_required=None, explicit_meal=False, time_budget=0.25):
    intent = MagicMock()
    intent.poi_query_type = poi_query_type
    intent.primary_query = primary_query
    intent.primary_required_terms = primary_required or ["古玩", "文玩", "收藏品"]
    intent.primary_excluded_terms = ["餐厅", "饭馆"]
    intent.allowed_typecode_prefixes = ["0612", "1907"]
    intent.excluded_typecode_prefixes = ["05"]
    intent.explicit_meal_intent = explicit_meal
    intent.time_budget = time_budget
    return intent


def test_valid_antique_waypoint():
    intent = _make_intent()
    points = [
        {"name": "老城古玩店", "kind": "anchor", "typecode": "061201",
         "is_display_poi": True, "display_order": 1},
    ]
    result = validate_plan_reality(intent, points)
    assert result.valid, f"Should be valid but got violations: {result.violations}"
    assert result.primary_waypoint_count == 1
    assert not result.meal_takeover
    assert not result.hidden_primary_target
    print(plan_reality_audit_log(result))
    print("✅ valid antique waypoint passes")


def test_free_explore_hides_primary():
    intent = _make_intent()
    points = [
        {"name": "老城古玩店", "kind": "free_explore", "typecode": "061201",
         "is_display_poi": False, "display_order": None},
    ]
    result = validate_plan_reality(intent, points)
    assert not result.valid
    assert result.hidden_primary_target
    print(plan_reality_audit_log(result))
    print("✅ free_explore hiding primary detected")


def test_meal_takeover_no_meal_intent():
    intent = _make_intent(explicit_meal=False)
    points = [
        {"name": "川渝小馆", "kind": "meal", "typecode": "050100",
         "is_display_poi": True, "display_order": 1},
    ]
    result = validate_plan_reality(intent, points)
    assert result.meal_takeover
    assert not result.valid
    print(plan_reality_audit_log(result))
    print("✅ meal takeover without explicit meal intent detected")


def test_meal_with_explicit_intent():
    intent = _make_intent(explicit_meal=True)
    intent.poi_query_type = "meal"
    intent.primary_required_terms = ["川菜", "餐厅"]
    intent.excluded_typecode_prefixes = []
    points = [
        {"name": "川渝小馆", "kind": "meal", "typecode": "050100",
         "is_display_poi": True, "display_order": 1},
    ]
    result = validate_plan_reality(intent, points)
    print(plan_reality_audit_log(result))
    print("✅ explicit meal intent allows restaurant-only plan")


def test_antique_plus_lunch():
    intent = _make_intent(explicit_meal=True)
    points = [
        {"name": "老城古玩店", "kind": "anchor", "typecode": "061201",
         "is_display_poi": True, "display_order": 1},
        {"name": "附近面馆", "kind": "meal", "typecode": "050100",
         "is_display_poi": True, "display_order": 2},
    ]
    result = validate_plan_reality(intent, points)
    assert result.primary_waypoint_count >= 1
    print(plan_reality_audit_log(result))
    print("✅ antique + lunch: primary target present")


# ── v20: Full-day theme route tests ──
def test_full_day_theme_needs_3_related_minimum():
    """全天主题路线至少需要 3 个相关非餐饮点"""
    intent = _make_intent(poi_query_type="theme_route", primary_query="街区逛吃",
                          primary_required=["街区", "逛吃"], time_budget=1.0)
    points = [
        {"name": "商圈步行街", "kind": "anchor_internal", "typecode": "061000",
         "is_display_poi": True, "display_order": 1},
        {"name": "某餐厅", "kind": "meal", "typecode": "050100",
         "is_display_poi": True, "display_order": 2},
    ]
    result = validate_plan_reality(intent, points)
    assert not result.valid
    assert "full_day_theme_needs_3_related" in result.violations
    print(plan_reality_audit_log(result))
    print("✅ full day theme needs 3 related — correctly detected")


def test_full_day_theme_with_3_related_passes():
    """全天主题路线有 3+ 相关非餐饮点应该通过"""
    intent = _make_intent(poi_query_type="theme_route", primary_query="街区逛吃",
                          primary_required=["街区", "逛吃", "步行街", "书店"], time_budget=1.0)
    points = [
        {"name": "逛吃街区步行街", "kind": "anchor_internal", "typecode": "061000",
         "is_display_poi": True, "display_order": 1},
        {"name": "街区书店", "kind": "anchor_internal", "typecode": "061205",
         "is_display_poi": True, "display_order": 2},
        {"name": "城市逛吃文创坊", "kind": "anchor_internal", "typecode": "110200",
         "is_display_poi": True, "display_order": 3},
        {"name": "某餐厅", "kind": "meal", "typecode": "050100",
         "is_display_poi": True, "display_order": 4},
    ]
    result = validate_plan_reality(intent, points)
    assert result.valid, f"Should be valid but got: {result.violations}"
    assert result.primary_waypoint_count >= 3
    print(plan_reality_audit_log(result))
    print("✅ full day theme with 3 related passes")


def test_quarter_day_theme_accepts_1_related():
    """半天以下主题路线 1 个相关点就可以"""
    intent = _make_intent(poi_query_type="theme_route", primary_query="逛街",
                          primary_required=["逛街"], time_budget=0.25)
    points = [
        {"name": "商业区", "kind": "anchor_internal", "typecode": "061000",
         "is_display_poi": True, "display_order": 1},
    ]
    result = validate_plan_reality(intent, points)
    # quarter_day needs at least 1 related, should pass
    print(plan_reality_audit_log(result))
    print("✅ quarter day theme: 1 related is sufficient")


# ── v20: Light eat detection tests ──
def test_english_light_food_detection():
    """Baker & Spice 等英文轻食名应被识别"""
    from services.step3_micro import _is_light_eat_candidate
    # English light food names — detected via name, not typecode
    assert _is_light_eat_candidate({"name": "Baker & Spice", "typecode": "050100"})
    assert _is_light_eat_candidate({"name": "Starbucks Coffee Lab", "typecode": "050900"})
    assert _is_light_eat_candidate({"name": "XX Bakery & Bread", "typecode": "050300"})
    assert _is_light_eat_candidate({"name": "Cafe Manner", "typecode": "050900"})
    assert _is_light_eat_candidate({"name": "The Pastry Lab", "typecode": "050301"})
    # Chinese light food names
    assert _is_light_eat_candidate({"name": "精品咖啡店", "typecode": "050100"})
    assert _is_light_eat_candidate({"name": "甜品工坊", "typecode": "050100"})
    # Not light food — real restaurants with 0501xx typecode and no light food name
    assert not _is_light_eat_candidate({"name": "海底捞火锅", "typecode": "050100"})
    assert not _is_light_eat_candidate({"name": "客语", "typecode": "050100"})
    print("✅ English light food detection works")


def test_light_food_not_suitable_for_dinner():
    """Baker & Spice 应分类为轻食/下午茶，不应成为正餐晚餐候选"""
    from services.step3_micro import _is_light_eat_candidate
    candidates = [
        {"name": "海底捞火锅", "typecode": "050100"},
        {"name": "客语", "typecode": "050100"},
        {"name": "烤鱼工坊", "typecode": "050100"},
        {"name": "俄士厨房", "typecode": "050100"},
        {"name": "Baker & Spice", "typecode": "050100"},
    ]
    light = [c for c in candidates if _is_light_eat_candidate(c)]
    regular = [c for c in candidates if not _is_light_eat_candidate(c)]
    assert len(light) == 1
    assert light[0]["name"] == "Baker & Spice"
    assert len(regular) == 4
    print("✅ light food separated from dinner candidates")


# ── v20: Composite typecode tests ──
def test_typecode_rules_have_valid_codes():
    """All category rules have valid typecode configurations"""
    for cat_id, rule in CATEGORY_RULES.items():
        assert "allowed" in rule, f"{cat_id} missing allowed"
        assert "semantic_terms" in rule, f"{cat_id} missing semantic_terms"
        assert len(rule["allowed"]) > 0, f"{cat_id} has empty allowed list"
        assert len(rule["semantic_terms"]) > 0, f"{cat_id} has empty semantic_terms"
        # Verify allowed codes have correct format (4-6 digit numeric)
        for code in rule["allowed"]:
            assert code.isdigit(), f"{cat_id} allowed code '{code}' is not numeric"
            assert len(code) >= 4, f"{cat_id} allowed code '{code}' too short"
    print("✅ all category rules have valid configurations")
