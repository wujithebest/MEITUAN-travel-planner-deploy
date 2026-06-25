"""v18: 多轮对话路线修改决策层 — 统一调度：LLM 一次性判断 conversation_mode + target_plan_mode"""

from __future__ import annotations

import asyncio
import json
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


class PlanningDispatchDecision(BaseModel):
    """v18: 统一调度决策 — LLM 一次性判断 conversation_mode + target_plan_mode"""
    conversation_mode: Literal["new_plan", "refine_current", "point_edit", "answer_only", "unsupported"] = "new_plan"
    target_plan_mode: Literal["exploratory", "planned"] = "exploratory"
    previous_plan_mode: str | None = None
    mode_changed: bool = False
    confidence: float = 0.0
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


_CONVERSATION_SYSTEM_PROMPT = """你是多轮路线规划对话的意图分类器。根据用户的当前输入和已有路线上下文，
判断用户意图是：
- new_plan：开始一个全新的路线规划（新城市、新日期、新完整路线请求）
- refine_current：修改当前路线的属性（预算、时间、主题、交通、餐饮偏好等），保留旧路线结构
- point_edit：仅增删替换个别route point（"去掉A""换成B""加一个C"）
- answer_only：只是询问信息，不需要重新规划路线
- unsupported：无法判断

输出严格的JSON格式：
{
  "mode": "new_plan | refine_current | point_edit | answer_only | unsupported",
  "confidence": 0.0,
  "latest_user_intent_summary": "一句话概括用户最新意图",
  "changed_fields": [{"field":"预算/时间/主题/交通/餐饮/POI名称/区域", "old_value":"...", "new_value":"...", "earliest_step":"step1/step2/step3/step4/local_replan"}],
  "earliest_step": "step1 | step2 | step3 | step4 | local_replan",
  "intent_patch": {},
  "include_constraints": {},
  "exclude_constraints": {},
  "point_operations": [{"action":"add|remove|replace", "target_name":"", "new_name":""}],
  "reason": "分类依据简述"
}

规则：
1. 新城市（如杭州、北京）、新日期（下周、周末）、两天以上且没有"其他不变"词的→new_plan
2. "其他不变""保持路线""在刚才基础上"配合预算/时间/主题/交通/偏好修改→refine_current
3. 仅增删替换个别POI名称→point_edit
4. 新旧冲突时，用户最新输入优先
5. 不确定时不要误判为point_edit，应走refine_current或new_plan"""


_PLANNING_DISPATCH_SYSTEM_PROMPT = """你是多轮路线规划对话的统一调度分类器。根据用户的当前输入和已有路线上下文，
一次性判断两个维度：
1. conversation_mode：用户对当前路线的操作意图
2. target_plan_mode：本轮应走 exploratory（自由探索）还是 planned（精准规划）pipeline

conversation_mode 定义：
- new_plan：开始一个全新的路线规划（新城市、新日期、新完整路线请求，或新旧 plan_mode 冲突）
- refine_current：修改当前路线的属性（预算、时间、主题、交通、餐饮偏好等），保留旧路线结构
- point_edit：仅增删替换个别 route point（"去掉A""换成B""加一个C"）
- answer_only：只是询问信息，不需要重新规划路线
- unsupported：无法判断

target_plan_mode 定义：
- **planned**：用户明确给出顺序任务（先X再Y然后Z）、指定途经点、通勤链条（下班/回家链路）、买东西再吃饭、按时间段安排上午/下午/晚上。关键词："先...再...""然后""接着""顺便""下班""回家路上""顺路""上午/下午/晚上"
- **exploratory**：用户只给主题、氛围、区域、泛游玩需求。如"上海文艺路线""历史文化路线""外滩附近随便逛逛""周末想出去玩玩"

规则：
1. 新城市（如杭州、北京）、新日期（下周、周末）、两天以上且没有"其他不变"词的→conversation_mode=new_plan
2. "其他不变""保持路线""在刚才基础上"配合预算/时间/主题/交通/偏好修改→conversation_mode=refine_current
3. 仅增删替换个别POI名称（"把A换成B""去掉C""加一个D"）→conversation_mode=point_edit
4. ⚠️ 模式冲突：如果已有路线且 previous_plan_mode 与 target_plan_mode 不同，除非是明确单点 add/remove/replace，否则 conversation_mode 应为 new_plan
5. 点位编辑只用于"删 A / 加 B / 把 A 换成 B"
6. schema 修改如预算、交通、主题、排除项、时间调整→conversation_mode=refine_current
7. 新旧冲突时，用户最新输入优先
8. 不确定时不要误判为 point_edit，应走 refine_current 或 new_plan

输出严格的JSON格式：
{
  "conversation_mode": "new_plan | refine_current | point_edit | answer_only | unsupported",
  "target_plan_mode": "exploratory | planned",
  "confidence": 0.0,
  "earliest_step": "step1 | step2 | step3 | step4 | local_replan",
  "intent_patch": {},
  "include_constraints": {},
  "exclude_constraints": {},
  "point_operations": [{"action":"add|remove|replace", "target_name":"", "new_name":""}],
  "reason": "分类依据简述"
}

注意：
- previous_plan_mode 已在 route_context 中提供，用于判断 mode_changed
- 不要输出 previous_plan_mode 或 mode_changed 字段（由代码计算）
- conversation_mode 和 target_plan_mode 是独立的两个维度，不要混淆"""


# ── plan_mode text heuristic ──

def _detect_plan_mode_from_text(text: str) -> str:
    """Simple heuristic for first-message plan_mode detection (no LLM needed)."""
    planned_signals = [
        "先", "再", "然后", "接着", "顺便", "最后",
        "上午", "下午", "晚上", "中午",
        "下班", "回家路上", "顺路", "通勤",
        "买点", "理个", "去个", "坐一会儿",
    ]
    exploratory_signals = [
        "随便逛逛", "逛逛", "走走", "溜达",
        "文艺", "路线", "周末出游", "出去玩",
    ]
    planned_score = sum(1 for s in planned_signals if s in text)
    exploratory_score = sum(1 for s in exploratory_signals if s in text)
    return "planned" if planned_score > exploratory_score else "exploratory"


# ── fast fallback for planning dispatch ──

def _planning_dispatch_fast_fallback(
    user_request: str,
    route_context: dict[str, Any] | None,
    previous_plan_mode: str | None,
) -> "PlanningDispatchDecision | None":
    """Wraps classify_conversation_route_change_fast() and adds target_plan_mode."""
    fast = classify_conversation_route_change_fast(user_request, route_context)
    if fast is None:
        return None
    target_pm = previous_plan_mode or _detect_plan_mode_from_text(user_request)
    return PlanningDispatchDecision(
        conversation_mode=fast.mode,
        target_plan_mode=target_pm,  # type: ignore[arg-type]
        previous_plan_mode=previous_plan_mode,
        mode_changed=previous_plan_mode is not None and target_pm != previous_plan_mode,
        confidence=fast.confidence,
        earliest_step=fast.earliest_step,
        intent_patch=fast.intent_patch,
        include_constraints=fast.include_constraints,
        exclude_constraints=fast.exclude_constraints,
        point_operations=fast.point_operations,
        reason=fast.reason,
    )


# ── unified dispatch (LLM-first) ──

async def classify_planning_dispatch(
    user_request: str,
    route_context: dict[str, Any] | None,
) -> PlanningDispatchDecision | None:
    """LLM-based unified dispatch: judges BOTH conversation_mode AND target_plan_mode in one call.

    Falls back to fast rules on LLM failure.
    """
    # Extract previous_plan_mode from context
    previous_plan_mode = None
    if route_context:
        prev = route_context.get("previous_intent") or {}
        previous_plan_mode = (
            prev.get("plan_mode")
            or (route_context.get("previous_complete_plan") or {}).get("plan_mode")
        )

    # No route context (first message): rule-based plan_mode detection
    if not route_context or not route_context.get("points"):
        fast = classify_conversation_route_change_fast(user_request, None)
        target_pm = _detect_plan_mode_from_text(user_request)
        return PlanningDispatchDecision(
            conversation_mode="new_plan",
            target_plan_mode=target_pm,  # type: ignore[arg-type]
            previous_plan_mode=None,
            mode_changed=False,
            confidence=0.85,
            earliest_step="step1",
            reason="no route context; auto-detected plan_mode",
        )

    # Has route context: build compact context JSON and call LLM
    point_names = route_context.get("point_names", [])[:20]
    compact: dict[str, Any] = {}
    for p in (route_context.get("points", []) or [])[:30]:
        compact[p.get("name", "")] = {
            "kind": p.get("kind", ""),
            "day": p.get("day", 1),
            "display_slot": p.get("display_slot", ""),
            "typecode": p.get("typecode", ""),
        }

    context_json = json.dumps({
        "point_names": point_names,
        "candidate_names": route_context.get("candidate_names", [])[:20],
        "recent_messages": route_context.get("recent_user_messages", [])[-3:],
        "previous_messages": route_context.get("previous_user_messages", [])[-3:],
        "points_summary": compact,
        "segments_count": len(route_context.get("segments", []) or []),
        "previous_plan_mode": previous_plan_mode,
    }, ensure_ascii=False, default=str)

    messages = [
        {"role": "system", "content": _PLANNING_DISPATCH_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"<route_context>{context_json}</route_context>\n"
            f"<user_input>{user_request}</user_input>"
        )},
    ]

    try:
        from .api_client import call_llm

        decision = await asyncio.wait_for(
            call_llm(
                response_model=PlanningDispatchDecision,
                messages=messages,
                max_tokens=600,
                temperature=0.2,
                max_retries=1,
            ),
            timeout=15.0,
        )
        # Fill in fields computed by caller, not LLM
        decision.previous_plan_mode = previous_plan_mode
        decision.mode_changed = (
            previous_plan_mode is not None
            and decision.target_plan_mode != previous_plan_mode
        )
        print(
            f"[DEBUG dispatch] classifier=llm conversation_mode={decision.conversation_mode} "
            f"target_plan_mode={decision.target_plan_mode} "
            f"previous_plan_mode={decision.previous_plan_mode} "
            f"mode_changed={decision.mode_changed} "
            f"confidence={decision.confidence} earliest_step={decision.earliest_step} "
            f"reason={decision.reason}"
        )
        return decision
    except Exception as exc:
        print(f"[WARNING dispatch] llm classifier failed: {exc}; fallback to fast rules")
        return _planning_dispatch_fast_fallback(user_request, route_context, previous_plan_mode)


# ── backward-compatible wrapper ──

async def classify_conversation_route_change(
    user_request: str,
    route_context: dict[str, Any] | None,
) -> ConversationRouteDecision | None:
    """Backward-compatible wrapper. Delegates to classify_planning_dispatch()."""
    dispatch = await classify_planning_dispatch(user_request, route_context)
    if dispatch is None:
        return None
    return ConversationRouteDecision(
        mode=dispatch.conversation_mode,
        confidence=dispatch.confidence,
        earliest_step=dispatch.earliest_step,
        intent_patch=dispatch.intent_patch,
        include_constraints=dispatch.include_constraints,
        exclude_constraints=dispatch.exclude_constraints,
        point_operations=dispatch.point_operations,
        reason=dispatch.reason,
    )
