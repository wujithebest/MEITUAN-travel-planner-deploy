import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.conversation_replan import decision_from_step1_intent
from services.data_schema import ParsedIntent
from services.step1_intent import _normalize_unified_routing_fields


def _intent(**overrides):
    data = {
        "duration": "a half day",
        "plan_mode": "exploratory",
        "conversation_mode": "new_plan",
        "earliest_step": "step1",
    }
    data.update(overrides)
    return ParsedIntent(**data)


def test_first_turn_cannot_be_routed_as_an_edit():
    decision = decision_from_step1_intent(
        _intent(conversation_mode="point_edit", point_operations=[{"action": "remove"}]),
        {"points": []},
    )

    assert decision.conversation_mode == "new_plan"
    assert decision.target_plan_mode == "exploratory"


def test_step1_point_edit_keeps_llm_operation_contract():
    decision = decision_from_step1_intent(
        _intent(
            conversation_mode="point_edit",
            plan_mode="planned",
            earliest_step="local_replan",
            dispatch_confidence=0.93,
            point_operations=[
                {"action": "replace", "target_name": "景山公园", "new_name": "北海公园"}
            ],
        ),
        {"points": [{"name": "景山公园"}], "previous_intent": {"plan_mode": "planned"}},
    )

    assert decision.conversation_mode == "point_edit"
    assert decision.target_plan_mode == "planned"
    assert decision.earliest_step == "local_replan"
    assert decision.point_operations[0]["new_name"] == "北海公园"


def test_step1_refine_preserves_structured_constraints():
    decision = decision_from_step1_intent(
        _intent(
            conversation_mode="refine_current",
            include_constraints={"keep_existing_route": True},
            exclude_constraints={"excluded_categories": ["cafe"]},
            intent_patch={"meal_replacement": True, "new_food_keywords": ["川菜"]},
        ),
        {"points": [{"name": "北海公园"}]},
    )

    assert decision.conversation_mode == "refine_current"
    assert decision.include_constraints["keep_existing_route"] is True
    assert decision.exclude_constraints["excluded_categories"] == ["cafe"]
    assert decision.intent_patch["new_food_keywords"] == ["川菜"]


def test_invalid_llm_plan_mode_recovers_previous_executable_mode():
    parsed = _normalize_unified_routing_fields(
        _intent(conversation_mode="refine_current", plan_mode="refine_current"),
        {"previous_intent": {"plan_mode": "planned"}},
    )

    assert parsed.conversation_mode == "refine_current"
    assert parsed.plan_mode == "planned"


def test_refine_restores_previous_executable_mode_when_llm_regresses():
    parsed = _normalize_unified_routing_fields(
        _intent(conversation_mode="refine_current", plan_mode="exploratory"),
        {"previous_intent": {"plan_mode": "planned"}},
    )

    assert parsed.conversation_mode == "refine_current"
    assert parsed.plan_mode == "planned"


def test_unified_category_operations_are_normalized_for_existing_editor():
    decision = decision_from_step1_intent(
        _intent(
            conversation_mode="point_edit",
            point_operations=[
                {"action": "remove", "category": "cafe", "name": "地球咖啡"},
                {"action": "add", "category": "visit", "value": "书店"},
            ],
        ),
        {"points": [{"name": "地球咖啡"}]},
    )

    remove_operation, add_operation = decision.point_operations
    assert remove_operation["target_category"] == "cafe"
    assert "咖啡馆" in remove_operation["target_terms"]
    assert add_operation["new_name"] == "书店"
