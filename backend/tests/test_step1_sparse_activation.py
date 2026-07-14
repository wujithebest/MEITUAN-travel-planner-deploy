import asyncio
import datetime as dt

import pytest

from services import step1_intent
from services.data_schema import PlannedWaypoint


def _compact(*waypoints: PlannedWaypoint) -> step1_intent.CompactStep1Intent:
    return step1_intent.CompactStep1Intent(
        raw_keywords=[wp.search_keyword or wp.name for wp in waypoints],
        search_keywords=[wp.search_keyword or wp.name for wp in waypoints],
        planned_waypoints=list(waypoints),
    )


def _waypoint(keyword: str, category: str) -> PlannedWaypoint:
    return PlannedWaypoint(
        type="placeholder",
        search_keyword=keyword,
        category=category,
        stay_minutes=30,
    )


@pytest.mark.parametrize(
    "text",
    [
        "附近找一家饭馆",
        "待会儿找一家餐厅，再找一家奶茶店",
        "下班后在附近买点水果，再找个地方简单吃晚饭",
        "现在附近找一家电玩店",
    ],
)
def test_compact_gate_accepts_simple_local_first_turns(text):
    assert step1_intent._is_compact_step1_candidate(text) is True


def test_compact_gate_accepts_router_empty_context_for_first_turn():
    assert step1_intent._is_compact_step1_candidate("附近找一家饭馆", {"points": []}) is True


@pytest.mark.parametrize(
    "text,context",
    [
        ("帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点", None),
        ("想去天安门和故宫附近转转，中午吃顿地道的北京菜，下午去景山公园看日落", None),
        ("下午推荐一条北京文艺路线，晚饭想吃点清淡的，吃完去河边走走，最后找个拍夜景的地方", None),
        ("不想去咖啡馆了，改成书店", {"points": [{"name": "地球咖啡"}]}),
        ("<conversation_context><latest_user_input>附近找饭馆</latest_user_input></conversation_context>", None),
    ],
)
def test_compact_gate_rejects_complex_or_contextual_requests(text, context):
    assert step1_intent._is_compact_step1_candidate(text, context) is False


def test_compact_contract_requires_all_ordered_targets():
    parsed = _compact(_waypoint("餐厅", "meal"))
    assert step1_intent._compact_intent_is_executable(parsed, "附近找餐厅，再找一家咖啡店") is False


def test_sparse_stage_uses_compact_llm_for_valid_local_contract(monkeypatch):
    compact = _compact(_waypoint("餐厅", "meal"), _waypoint("奶茶店", "cafe"))

    async def fake_compact(*args, **kwargs):
        return compact

    async def unexpected_full(*args, **kwargs):
        raise AssertionError("valid compact response must not call the full Step1 LLM")

    monkeypatch.setattr(step1_intent, "_llm_parse_compact", fake_compact)
    monkeypatch.setattr(step1_intent, "_llm_parse", unexpected_full)

    parsed, source = asyncio.run(
        step1_intent.parse_step1_llm_stage(
            "附近找一家餐厅，再找一家奶茶店",
            dt.datetime.now(),
        )
    )

    assert source == "compact_llm"
    assert parsed.plan_mode == "planned"
    assert [(wp.search_keyword, wp.category) for wp in parsed.planned_waypoints] == [
        ("餐厅", "meal"),
        ("奶茶店", "cafe"),
    ]


def test_sparse_stage_falls_back_to_full_llm_on_invalid_compact_contract(monkeypatch):
    invalid = _compact(_waypoint("餐厅", "meal"))
    expected = step1_intent.ParsedIntent(
        duration="a quarter day",
        plan_mode="planned",
        planned_waypoints=[_waypoint("餐厅", "meal"), _waypoint("咖啡店", "cafe")],
    )

    async def fake_compact(*args, **kwargs):
        return invalid

    async def fake_full(*args, **kwargs):
        return expected

    monkeypatch.setattr(step1_intent, "_llm_parse_compact", fake_compact)
    monkeypatch.setattr(step1_intent, "_llm_parse", fake_full)

    parsed, source = asyncio.run(
        step1_intent.parse_step1_llm_stage(
            "附近找一家餐厅，再找一家咖啡店",
            dt.datetime.now(),
        )
    )

    assert source == "full_llm"
    assert len(parsed.planned_waypoints) == 2
