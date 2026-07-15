from types import SimpleNamespace

from services.step1_intent import _normalize_mixed_theme_route_intent
from services.step2_macro import _is_meal_macro_keyword, _is_theme_meal_constraint_only


def test_theme_route_wins_over_meal_primary_query():
    meal_constraints = [{"meal": "dinner", "keywords": ["川菜"]}]
    parsed = SimpleNamespace(
        theme_profile="urban_renewal_brand_consumption",
        poi_query_type="poi_category",
        primary_query="川菜",
        category_id="restaurant",
        allowed_typecode_prefixes=["050000"],
        must_recall_target=True,
        explicit_meal_intent=True,
        meal_constraints=meal_constraints,
        food_pref_keywords=["川菜"],
        meal_search_keywords=["川菜 餐厅"],
        theme_required=False,
    )

    result = _normalize_mixed_theme_route_intent(
        parsed,
        "推荐一个工业风一日游路线，晚餐要吃川菜",
    )

    assert result.poi_query_type == "theme_route"
    assert result.primary_query == ""
    assert result.category_id is None
    assert result.allowed_typecode_prefixes == []
    assert result.must_recall_target is False
    assert result.theme_required is True
    assert result.meal_constraints == meal_constraints


def test_theme_macro_search_excludes_meal_keywords_only():
    parsed = SimpleNamespace(
        poi_query_type="theme_route",
        theme_profile="future_tech_ai",
        primary_query="",
        explicit_meal_intent=True,
        meal_search_keywords=["川菜 餐厅"],
        food_pref_keywords=["川菜"],
    )

    assert _is_theme_meal_constraint_only(parsed)
    assert _is_meal_macro_keyword("北京 川菜", parsed)
    assert _is_meal_macro_keyword("北京 川菜 餐厅", parsed)
    assert not _is_meal_macro_keyword("北京 数字艺术馆", parsed)


def test_non_meal_primary_target_is_preserved():
    parsed = SimpleNamespace(
        theme_profile="future_tech_ai",
        poi_query_type="poi_category",
        primary_query="科技馆",
        category_id="science_museum",
        allowed_typecode_prefixes=["140600"],
        must_recall_target=True,
        explicit_meal_intent=True,
        meal_constraints=[{"meal": "dinner", "keywords": ["川菜"]}],
        food_pref_keywords=["川菜"],
        meal_search_keywords=["川菜 餐厅"],
        theme_required=False,
    )

    result = _normalize_mixed_theme_route_intent(
        parsed,
        "推荐一个科技馆路线，晚餐要吃川菜",
    )

    assert result.poi_query_type == "poi_category"
    assert result.primary_query == "科技馆"
    assert result.category_id == "science_museum"
