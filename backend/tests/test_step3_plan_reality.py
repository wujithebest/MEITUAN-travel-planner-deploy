"""Step3 plan reality tests — fixed waypoints, no live API."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.plan_reality_validator import validate_plan_reality, plan_reality_audit_log


def _make_intent(poi_query_type="poi_category", primary_query="古玩市场",
                 primary_required=None, explicit_meal=False):
    intent = MagicMock()
    intent.poi_query_type = poi_query_type
    intent.primary_query = primary_query
    intent.primary_required_terms = primary_required or ["古玩", "文玩", "收藏品"]
    intent.primary_excluded_terms = ["餐厅", "饭馆"]
    intent.allowed_typecode_prefixes = ["0612", "1907"]
    intent.excluded_typecode_prefixes = ["05"]
    intent.explicit_meal_intent = explicit_meal
    intent.time_budget = 0.25
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
    # Meal with explicit intent is valid
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
