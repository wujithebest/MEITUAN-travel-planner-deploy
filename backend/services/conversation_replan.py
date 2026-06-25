"""v17: 多轮对话路线修改决策层 — 判断用户是开新路线还是修改旧路线"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


class PointOperation(BaseModel):
    action: Literal["add", "remove", "replace"] = "remove"
    target_name: str | None = None
    new_name: str | None = None


class ConversationRouteDecision(BaseModel):
    mode: Literal["new_plan", "refine_current", "point_edit", "answer_only", "unsupported"] = "new_plan"
    confidence: float = 0.0
    latest_user_intent_summary: str = ""
    changed_fields: list[dict[str, Any]] = Field(default_factory=list)
    earliest_step: Literal["step1", "step2", "step3", "step4", "local_replan"] = "step1"
    intent_patch: dict[str, Any] = Field(default_factory=dict)
    include_constraints: dict[str, Any] = Field(default_factory=dict)
    exclude_constraints: dict[str, Any] = Field(default_factory=dict)
    point_operations: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ""


# ── fast-path rules ──

_NEW_CITY_TOKENS = ("杭州", "北京", "南京", "苏州", "无锡", "广州", "深圳", "成都", "重庆", "西安", "武汉",
                     "长沙", "三亚", "青岛", "厦门", "昆明", "大理", "丽江", "桂林", "张家界")

_CLEAR_NEW_PLAN_TOKENS = ("明天", "后天", "下周", "周末", "下个月", "过年", "国庆", "五一", "端午",
                           "三天", "四天", "五天", "一周", "一个星期", "半个月")

_CONTINUATION_TOKENS = ("其他不变", "其他安排不变", "其余不变", "保持不变", "在原来基础上",
                         "在刚才基础上", "刚才的", "不变的", "别动其他的", "就把")

_EXPLICIT_REPLACE_TOKENS = ("换成", "替换成", "替换为", "改成", "改为")

_EXPLICIT_REMOVE_TOKENS = ("不要", "不想去", "不去", "去掉", "删除", "删掉", "别安排", "跳过", "也不想去")

_EXPLICIT_ADD_TOKENS = ("加一个", "增加", "加上", "再加", "还想去", "我还想去", "也想去")


def classify_conversation_route_change_fast(
    user_request: str,
    route_context: dict[str, Any] | None,
) -> ConversationRouteDecision | None:
    """Fast-path rule-based classification; returns None if uncertain → fallback to LLM"""
    text = user_request.strip()
    has_route = bool(route_context and route_context.get("points"))

    # New city → definitely new plan
    for city in _NEW_CITY_TOKENS:
        if city in text:
            return ConversationRouteDecision(
                mode="new_plan", confidence=0.95,
                latest_user_intent_summary=text,
                earliest_step="step1",
                reason=f"explicit new city: {city}",
            )

    # Without route context → new plan
    if not has_route:
        return ConversationRouteDecision(
            mode="new_plan", confidence=0.90,
            latest_user_intent_summary=text,
            earliest_step="step1",
            reason="no route context available",
        )

    # Clear date + planning intent without continuation → new plan
    has_date = any(t in text for t in _CLEAR_NEW_PLAN_TOKENS)
    has_continuation = any(t in text for t in _CONTINUATION_TOKENS)
    has_edit_word = any(w in text for w in _EXPLICIT_REPLACE_TOKENS + _EXPLICIT_REMOVE_TOKENS + _EXPLICIT_ADD_TOKENS)
    if has_date and not has_continuation and not has_edit_word:
        return ConversationRouteDecision(
            mode="new_plan", confidence=0.85,
            latest_user_intent_summary=text,
            earliest_step="step1",
            reason="explicit date + planning intent without continuation",
        )

    # Point edit detection
    point_names = route_context.get("point_names", []) if route_context else []
    ops: list[dict[str, Any]] = []

    for word in _EXPLICIT_REPLACE_TOKENS:
        if word in text:
            left, right = text.split(word, 1)
            left = re.sub(r"^(把|将|请把|帮我把)", "", left).strip()
            target = _match_any(left, point_names) or left.strip()
            new_name = _clean_name(right)
            if target and new_name:
                ops.append({"action": "replace", "target_name": target, "new_name": new_name})

    if not ops:
        for word in _EXPLICIT_REMOVE_TOKENS:
            if word in text:
                target = _match_any(text, point_names) or _clean_name(text)
                if target:
                    ops.append({"action": "remove", "target_name": target})

    if not ops:
        for word in _EXPLICIT_ADD_TOKENS:
            if word in text:
                new_name = _clean_name(text.split(word, 1)[1])
                if new_name:
                    ops.append({"action": "add", "new_name": new_name})

    if ops and has_continuation:
        return ConversationRouteDecision(
            mode="point_edit", confidence=0.88,
            latest_user_intent_summary=text,
            earliest_step="local_replan",
            point_operations=ops,
            reason=f"explicit point edit with continuation: {ops}",
        )

    if ops and not has_date:
        has_more_edits = _has_field_edits(text)
        if not has_more_edits:
            return ConversationRouteDecision(
                mode="point_edit", confidence=0.80,
                latest_user_intent_summary=text,
                earliest_step="local_replan",
                point_operations=ops,
                reason=f"explicit point edit: {ops}",
            )

    if has_continuation:
        return ConversationRouteDecision(
            mode="refine_current", confidence=0.75,
            latest_user_intent_summary=text,
            earliest_step="step2",
            reason="continuation detected, likely refine",
            include_constraints={"other_arrangements_unchanged": True},
        )

    return None


def _match_any(text: str, names: list[str]) -> str | None:
    for name in sorted(names, key=len, reverse=True):
        if name and name in text:
            return name
    return None


def _clean_name(text: str) -> str:
    text = re.sub(r"[，。,.!?！？；;、\s]+$", "", text.strip())
    text = re.sub(r"^(一个|一下|去|到|成|为)", "", text)
    text = re.sub(r"(吧|呀|呢|可以吗|行吗|其他安排不变|其余不变|别的地方|其他地方)$", "", text).strip()
    return text


def _has_field_edits(text: str) -> bool:
    field_words = ("预算", "人均", "交通", "打车", "公交", "地铁", "步行", "骑行",
                    "上午", "下午", "晚上", "出发", "时间", "改成", "换成")
    return any(w in text for w in field_words)
