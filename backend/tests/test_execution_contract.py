"""Regression tests for the generic explicit-action execution contract."""

from __future__ import annotations

from types import SimpleNamespace

from services.data_schema import ParsedIntent, PlannedWaypoint
from services.step1_intent import _apply_explicit_execution_contract, _ensure_explicit_visible_facet_coverage
from services.step3_planned import _fixed_poi_name_matches, _planned_semantic_score


def _meal_waypoint(keyword: str) -> PlannedWaypoint:
    return PlannedWaypoint(
        type="placeholder",
        search_keyword=keyword,
        category="meal",
        search_keywords=[keyword],
        required_terms=[keyword],
    )


def _intent(**kwargs) -> ParsedIntent:
    return ParsedIntent(duration="a quarter day", **kwargs)


def test_explicit_contract_keeps_ordered_actions_planned():
    intent = _intent(
        plan_mode="exploratory",
        food_pref_keywords=["烤鸭"],
        planned_waypoints=[
            PlannedWaypoint(type="fixed", name="北海公园", category="visit"),
            _meal_waypoint("烤鸭"),
            PlannedWaypoint(type="fixed", name="三里河公园", category="visit"),
        ],
    )
    applied = _apply_explicit_execution_contract(
        intent,
        "先去北海公园走走，中午吃顿烤鸭，下午去三里河公园。",
        list(intent.planned_waypoints),
    )

    assert applied
    assert intent.plan_mode == "planned"
    assert intent.execution_contract_required is True
    assert [wp.name or wp.search_keyword for wp in intent.planned_waypoints] == ["北海公园", "烤鸭", "三里河公园"]
    assert intent.planned_waypoints[1].must_match_terms is True


def test_explicit_contract_converts_walk_to_non_sports_search():
    intent = _intent(
        planned_waypoints=[
            _meal_waypoint("餐厅"),
            PlannedWaypoint(type="placeholder", search_keyword="散步", category="visit"),
        ],
    )
    applied = _apply_explicit_execution_contract(
        intent,
        "待会儿去附近吃饭，吃完再散步。",
        list(intent.planned_waypoints),
    )

    assert applied
    walk = intent.planned_waypoints[1]
    assert walk.search_keyword == "公园"
    assert walk.must_match_terms is True
    assert "健身" in walk.excluded_terms


def test_explicit_contract_rejects_unrelated_meal_substitution():
    waypoint = _meal_waypoint("烤鸭")
    waypoint.must_match_terms = True
    center = {"lat": 39.9, "lng": 116.4}

    assert _planned_semantic_score(
        waypoint,
        {"name": "老吉堂上海本帮菜", "typecode": "050107", "location": center},
        center,
    ) is None
    assert _planned_semantic_score(
        waypoint,
        {"name": "便宜坊烤鸭店", "typecode": "050100", "location": center},
        center,
    ) is not None


def test_explicit_contract_accepts_cuisine_aliases_without_dropping_the_food_constraint():
    intent = _intent(food_pref_keywords=["北京菜"])
    assert _apply_explicit_execution_contract(
        intent,
        "中午吃顿地道的北京菜，下午再去公园。",
        [
            _meal_waypoint("地道北京菜"),
            PlannedWaypoint(type="placeholder", search_keyword="公园", category="visit"),
        ],
    )
    meal = next(item for item in intent.planned_waypoints if item.category == "meal")
    assert "京味" in meal.required_terms
    assert _planned_semantic_score(
        meal,
        {"name": "老北京炸酱面", "typecode": "050100", "location": {"lat": 39.9, "lng": 116.4}},
        {"lat": 39.9, "lng": 116.4},
    ) is not None


def test_explicit_contract_uses_a_real_restaurant_for_generic_dinner():
    intent = _intent(planned_waypoints=[
        PlannedWaypoint(type="placeholder", search_keyword="水果店", category="purchase"),
        _meal_waypoint("晚饭"),
    ])
    assert _apply_explicit_execution_contract(
        intent,
        "先买点水果，晚饭再找一家餐厅。",
        list(intent.planned_waypoints),
    )
    meal = next(item for item in intent.planned_waypoints if item.category == "meal")
    assert meal.search_keyword == "餐厅"
    assert "餐厅" in meal.required_terms


def test_explicit_contract_derives_photo_then_cafe_generically():
    intent = _intent(plan_mode="exploratory")
    assert _apply_explicit_execution_contract(
        intent,
        "下午想找个适合拍照的地方，再喝杯咖啡。",
        [],
    )
    assert [item.search_keyword for item in intent.planned_waypoints] == ["拍照打卡", "咖啡"]


def test_explicit_contract_keeps_any_place_like_stroll_anchor_and_relaxes_later_walk():
    intent = _intent(food_pref_keywords=["北京菜"])
    assert _apply_explicit_execution_contract(
        intent,
        "周末想去颐和园逛逛，中午在附近吃饭，下午继续轻松走走。",
        [
            PlannedWaypoint(type="placeholder", search_keyword="颐和园附近转转", category="area_stroll", search_center_name="周末想去颐和园逛逛"),
            _meal_waypoint("北京菜"),
            PlannedWaypoint(type="fixed", name="继续轻松", category="visit"),
        ],
    )
    assert [item.name or item.search_keyword for item in intent.planned_waypoints] == ["颐和园", "餐厅", "公园"]


def test_fixed_poi_requires_identity_match_instead_of_first_text_result():
    assert _fixed_poi_name_matches("颐和园", "颐和园东宫门")
    assert not _fixed_poi_name_matches("颐和园", "玉东郊野公园")


def test_explicit_photo_and_cafe_keep_two_required_visible_facets():
    intent = _intent(plan_mode="exploratory")
    _ensure_explicit_visible_facet_coverage(intent, "周末想拍照、喝咖啡，节奏轻松一点。")
    required = {item["id"] for item in intent.theme_facets if item.get("required")}
    assert {"art_culture_lifestyle", "cafe_stop"}.issubset(required)
    assert intent.plan_mode == "exploratory"


def test_broad_theme_without_order_stays_exploratory():
    intent = _intent(planned_waypoints=[
        PlannedWaypoint(type="placeholder", search_keyword="咖啡", category="cafe"),
        PlannedWaypoint(type="placeholder", search_keyword="特色小店", category="visit"),
    ])
    assert not _apply_explicit_execution_contract(
        intent,
        "帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点。",
        list(intent.planned_waypoints),
    )
    assert intent.execution_contract_required is False
