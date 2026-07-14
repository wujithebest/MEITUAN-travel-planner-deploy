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
    mode: Literal["new_plan", "refine_current", "point_edit", "answer_only", "unsupported", "follow_up"] = "new_plan"
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
    conversation_mode: Literal["new_plan", "refine_current", "point_edit", "answer_only", "unsupported", "follow_up"] = "new_plan"
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


def decision_from_step1_intent(intent: Any, route_context: dict[str, Any] | None) -> PlanningDispatchDecision:
    """Adapt the unified Step1 response to the existing router contract.

    Normal requests never run the rule classifier before this point.  The small
    checks here are structural guards only: a first turn cannot edit a missing
    route, and downstream code only accepts the two executable plan modes.
    """
    has_route = bool(route_context and route_context.get("points"))
    mode = str(getattr(intent, "conversation_mode", "new_plan") or "new_plan")
    if not has_route and mode not in {"answer_only", "unsupported"}:
        mode = "new_plan"
    if mode not in {"new_plan", "refine_current", "point_edit", "answer_only", "unsupported", "follow_up"}:
        mode = "new_plan"

    plan_mode = str(getattr(intent, "plan_mode", "exploratory") or "exploratory")
    target_plan_mode = "planned" if plan_mode == "planned" else "exploratory"
    earliest_step = str(getattr(intent, "earliest_step", "step1") or "step1")
    if earliest_step not in {"step1", "step2", "step3", "step4", "local_replan"}:
        earliest_step = "step1"

    previous_intent = (route_context or {}).get("previous_intent") or {}
    previous_plan_mode = previous_intent.get("plan_mode") or (
        ((route_context or {}).get("previous_complete_plan") or {}).get("plan_mode")
    )
    normalized_operations: list[dict[str, Any]] = []
    for raw_operation in list(getattr(intent, "point_operations", []) or []):
        if not isinstance(raw_operation, dict):
            continue
        operation = dict(raw_operation)
        action = str(operation.get("action", "") or "")
        if action == "remove" and (
            operation.get("type") == "category"
            or (
                operation.get("category") in _CATEGORY_EXCLUSION_MAP
                and not operation.get("target_name")
            )
        ):
            operation["action"] = "remove_category"
            operation["target_category"] = (
                operation.get("value") or operation.get("category") or ""
            )
            action = "remove_category"
        if action == "remove_category":
            category = str(operation.get("target_category") or operation.get("category") or "")
            category_info = next(
                (
                    info for info in _CATEGORY_EXCLUSION_MAP.values()
                    if info.get("category_id") == category
                ),
                {},
            )
            operation["target_category"] = category
            operation["target_terms"] = operation.get("target_terms") or list(
                category_info.get("aliases", []) + category_info.get("negative_terms", [])
            )
            operation["target_typecodes"] = operation.get("target_typecodes") or list(
                category_info.get("typecodes", [])
            )
        elif action == "add":
            operation["new_name"] = (
                operation.get("new_name")
                or operation.get("search_keyword")
                or operation.get("name")
                or operation.get("value")
                or ""
            )
        elif action in {"remove", "replace"}:
            operation["target_name"] = operation.get("target_name") or operation.get("target") or ""
            if action == "replace":
                operation["new_name"] = (
                    operation.get("new_name")
                    or operation.get("search_keyword")
                    or operation.get("value")
                    or ""
                )
        normalized_operations.append(operation)

    return PlanningDispatchDecision(
        conversation_mode=mode,
        target_plan_mode=target_plan_mode,
        previous_plan_mode=previous_plan_mode,
        mode_changed=bool(previous_plan_mode and previous_plan_mode != target_plan_mode),
        confidence=float(getattr(intent, "dispatch_confidence", 0.0) or 0.0),
        earliest_step=earliest_step,
        intent_patch=dict(getattr(intent, "intent_patch", {}) or {}),
        include_constraints=dict(getattr(intent, "include_constraints", {}) or {}),
        exclude_constraints=dict(getattr(intent, "exclude_constraints", {}) or {}),
        point_operations=normalized_operations,
        reason=str(getattr(intent, "dispatch_reason", "") or "step1 unified routing"),
    )


# ── fast-path rules ──

_NEW_CITY_TOKENS = ("杭州", "北京", "南京", "苏州", "无锡", "广州", "深圳", "成都", "重庆", "西安", "武汉",
                     "长沙", "三亚", "青岛", "厦门", "昆明", "大理", "丽江", "桂林", "张家界")

_CLEAR_NEW_PLAN_TOKENS = ("明天", "后天", "下周", "周末", "下个月", "过年", "国庆", "五一", "端午",
                           "三天", "四天", "五天", "一周", "一个星期", "半个月")

_CONTINUATION_TOKENS = ("其他不变", "其他安排不变", "其余不变", "保持不变", "在原来基础上",
                         "在刚才基础上", "刚才的", "不变的", "别动其他的", "就把")

# ── v24: meal preference replacement detection ──

_FOOD_INDICATOR_CHARS = (
    "菜", "烤", "肉", "鱼", "虾", "鸡", "鸭", "牛", "羊", "猪",
    "面", "饭", "锅", "汤", "粉", "串", "烧", "炒", "蒸", "煮",
    "卤", "熏", "腊", "拌", "涮", "煲", "炖", "焖", "焗", "煨",
    "丸", "饺", "包", "饼", "糕", "酥", "卷", "排", "翅", "腿",
    "柳", "扒", "焗", "烩", "焐", "熘", "爆", "氽", "炝", "煸",
    "酱", "卤", "腌", "酥", "脆", "辣", "麻", "鲜", "香",
)

_POI_INDICATOR_CHARS = (
    "公园", "山", "街", "路", "广场", "塔", "寺", "庙", "宫", "殿",
    "园", "湖", "海", "河", "江", "桥", "馆", "院", "堂", "楼",
    "阁", "亭", "廊", "门", "墙", "林", "岛", "滩", "湾", "港",
)

_FOOD_CUISINE_MAP: dict[str, list[str]] = {
    "烤鸭": ["烤鸭", "北京菜", "京菜"],
    "川菜": ["川菜", "四川菜", "川菜 餐厅"],
    "四川菜": ["川菜", "四川菜", "川菜 餐厅"],
    "粤菜": ["粤菜", "广东菜", "粤菜 餐厅"],
    "广东菜": ["粤菜", "广东菜"],
    "火锅": ["火锅", "涮肉"],
    "涮羊肉": ["涮羊肉", "火锅", "羊肉"],
    "日料": ["日料", "日本料理", "寿司"],
    "日本料理": ["日料", "日本料理", "寿司"],
    "本帮菜": ["本帮菜", "上海菜", "江浙菜"],
    "上海菜": ["本帮菜", "上海菜", "江浙菜"],
    "湘菜": ["湘菜", "湖南菜"],
    "东北菜": ["东北菜", "锅包肉", "地三鲜"],
    "烧烤": ["烧烤", "烤串", "烤肉"],
    "西餐": ["西餐", "牛排", "西餐厅"],
    "牛排": ["牛排", "西餐", "西餐厅"],
    "海鲜": ["海鲜", "海鲜餐厅"],
    "素食": ["素食", "素菜", "斋菜"],
    "清真": ["清真", "清真菜", "回民菜"],
    "简餐": ["简餐", "快餐", "便餐"],
    "小吃": ["小吃", "特色小吃"],
    "面": ["面馆", "拉面", "面条"],
    "汉堡": ["汉堡", "西式快餐", "快餐"],
    "披萨": ["披萨", "西餐", "意餐"],
    "泰国菜": ["泰国菜", "泰餐", "东南亚菜"],
    "越南菜": ["越南菜", "越南粉", "东南亚菜"],
    "韩国菜": ["韩国菜", "韩餐", "韩国料理"],
    "西北菜": ["西北菜", "兰州", "羊肉"],
}

_FULL_MEAL_ROUTE_SIGNALS = (
    "美食路线", "美食之旅", "美食一日游", "美食游",
    "专门去吃", "专门去", "一趟美食", "美食探店",
    "重新安排", "重新规划", "新路线",
)

_MEAL_SLOT_INDICATORS = {
    "lunch": ("午餐", "午饭", "中午", "中饭", "午间"),
    "dinner": ("晚餐", "晚饭", "晚上吃", "晚间", "晚饭吃"),
    "breakfast": ("早餐", "早饭", "早点"),
}

_MEAL_REFINE_NEW_PLAN_SIGNALS = ("明天", "后天", "下周", "周末", "重新", "新路线", "两天", "三天")


def _is_food_term(term: str) -> bool:
    """Check if a term refers to food/cuisine (not a POI name)."""
    if not term or len(term) > 12:
        return False
    if any(c in term for c in _POI_INDICATOR_CHARS):
        return False
    if any(c in term for c in _FOOD_INDICATOR_CHARS):
        return True
    # Check cuisine map
    for key in _FOOD_CUISINE_MAP:
        if key in term or term in key:
            return True
    return len(term) <= 4


def _clean_food_term(term: str) -> str:
    """Clean a food term extracted from user text."""
    term = re.sub(r"[，。,.!?！？；;、\s]+$", "", term.strip())
    term = re.sub(r"^(了|的|个|一|吃|要|是|把|将)", "", term).strip()
    term = re.sub(r"(吧|呀|呢|可以吗|行吗|了|的)$", "", term).strip()
    return term


def _meal_slot_from_refine_text(text: str) -> str:
    """Extract meal slot from text."""
    for slot, indicators in _MEAL_SLOT_INDICATORS.items():
        if any(t in text for t in indicators):
            return slot
    if "晚" in text:
        return "dinner"
    if "午" in text or "中午" in text:
        return "lunch"
    if "早" in text:
        return "breakfast"
    return "lunch"


def _expand_food_keywords(food: str) -> list[str]:
    """Expand a food term into search keywords."""
    if not food:
        return []
    food_clean = food.strip()
    for key, val in _FOOD_CUISINE_MAP.items():
        if key in food_clean or food_clean in key:
            return list(dict.fromkeys(val))
    # Generic expansion
    return list(dict.fromkeys([food_clean + " 餐厅", food_clean]))


def _looks_like_full_meal_route_request(text: str) -> bool:
    """Check if text looks like a full meal-focused route request, not just a meal replacement."""
    return any(t in text for t in _FULL_MEAL_ROUTE_SIGNALS)


def _is_meal_preference_refine(text: str) -> dict | None:
    """Detect meal preference replacement patterns on existing route.

    Recognizes patterns like:
    - 不想吃烤鸭，想吃川菜
    - 不吃烤鸭了，换成川菜
    - 烤鸭不要了，改成涮羊肉
    - 午餐不吃A，想吃B
    - 晚饭换成B
    - 不想吃A。想吃B

    Returns dict with detection info, or None if not a meal preference refine.
    """
    text = text.strip()

    # Must not contain new-plan signals
    if any(t in text for t in _MEAL_REFINE_NEW_PLAN_SIGNALS):
        return None

    # Must not contain new city
    for city in _NEW_CITY_TOKENS:
        if city in text:
            return None

    # Must not be a full meal route request
    if _looks_like_full_meal_route_request(text):
        return None

    # Must contain food-related signals
    has_food_signal = any(t in text for t in [
        "吃", "菜", "饭", "餐", "烤", "涮", "火锅", "炒菜",
        "面", "粉", "串", "烧", "蒸", "煮", "卤", "煲",
    ])
    if not has_food_signal:
        return None

    old_food = None
    new_food = None
    slot = None

    # Pattern 1: "不想吃X。想吃Y" / "不想吃X，想吃Y"
    m = re.search(r"不想吃(.+?)[。，,;；\s]*想?吃(.+)", text)
    if m:
        old_food = _clean_food_term(m.group(1))
        new_food = _clean_food_term(m.group(2))

    # Pattern 2: "不吃X了，换成Y" / "X不要了，改成Y" / "X不要了。想吃Y"
    if not (old_food and new_food):
        m = re.search(r"(?:不吃|别吃|不要)(.+?)(?:了)?[。，,;；\s]*(?:[换改]成|想?吃)(.+)", text)
        if m:
            old_food = _clean_food_term(m.group(1))
            new_food = _clean_food_term(m.group(2))

    # Pattern 3: "X换成Y" / "X改成Y" — single clause, both must be food terms
    if not (old_food and new_food):
        m = re.search(r"(.{1,10})[换改]成(.{1,10})", text)
        if m:
            cand_old = _clean_food_term(m.group(1))
            cand_new = _clean_food_term(m.group(2))
            # Both must be food terms; exclude "公园→什刹海" type replacements
            if cand_old and cand_new and _is_food_term(cand_old) and _is_food_term(cand_new):
                old_food = cand_old
                new_food = cand_new

    # Pattern 4: "(午餐|晚饭)不吃X，想吃Y" with slot
    if not (old_food and new_food):
        m = re.search(r"(午餐|午饭|晚餐|晚饭|中午|早餐|早饭)?\s*(?:不想吃|不吃|别吃|不要)(.+?)[，,;；\s]*想?吃(.+)", text)
        if m:
            slot = _meal_slot_from_refine_text(m.group(1) or text)
            old_food = _clean_food_term(m.group(2))
            new_food = _clean_food_term(m.group(3))

    # Pattern 5: "X不要了。想吃Y" (period-separated)
    if not (old_food and new_food):
        m = re.search(r"(.{1,10})不要了[。，,;；\s]*想?吃(.+)", text)
        if m:
            cand_old = _clean_food_term(m.group(1))
            cand_new = _clean_food_term(m.group(2))
            if cand_old and cand_new and _is_food_term(cand_old):
                old_food = cand_old
                new_food = cand_new

    # Pattern 6: "(午餐|晚饭)换成Y" (no old food specified)
    if not new_food:
        m = re.search(r"(午餐|午饭|晚餐|晚饭|中午|早餐|早饭)?\s*[换改]成(.+)", text)
        if m:
            new_food = _clean_food_term(m.group(2))
            slot = _meal_slot_from_refine_text(m.group(1) or text)
            if new_food and _is_food_term(new_food):
                old_food = None

    if not new_food:
        return None

    # Map to keywords
    new_keywords = _expand_food_keywords(new_food)
    old_keywords = _expand_food_keywords(old_food) if old_food else []

    if not slot:
        slot = _meal_slot_from_refine_text(text)

    # Extract budget if present
    budget_match = re.search(r"人均(\d+)", text)
    budget = int(budget_match.group(1)) if budget_match else None

    return {
        "detected": True,
        "old_food_keywords": old_keywords,
        "new_food_keywords": new_keywords,
        "old_food_raw": old_food,
        "new_food_raw": new_food,
        "meal_slot": slot,
        "budget_per_capita": budget,
    }

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

    # v24: Meal preference replacement detection — must run before other fast rules
    _meal_refine = _is_meal_preference_refine(text)
    if _meal_refine and has_route:
        _keep_names = [p.get("name", "") for p in (route_context.get("points") or [])[:8]
                       if p.get("kind") not in ("meal", "start", "hint", "free_explore", "candidate")]
        print(
            f"[MealRefineAudit] detected=true "
            f"old_food={_meal_refine.get('old_food_raw')} "
            f"new_food={_meal_refine.get('new_food_raw')} "
            f"slot={_meal_refine.get('meal_slot')} "
            f"keep_points={'|'.join(_keep_names[:5])}"
        )
        return ConversationRouteDecision(
            mode="refine_current", confidence=0.92,
            latest_user_intent_summary=text,
            earliest_step="local_replan",
            intent_patch={
                "meal_replacement": True,
                "old_food_keywords": _meal_refine.get("old_food_keywords", []),
                "new_food_keywords": _meal_refine.get("new_food_keywords", []),
                "meal_slot": _meal_refine.get("meal_slot", "lunch"),
                "keep_existing_route": True,
                "budget_per_capita": _meal_refine.get("budget_per_capita"),
            },
            include_constraints={
                "other_arrangements_unchanged": True,
                "keep_route_points": True,
            },
            reason=f"meal preference replacement: {_meal_refine.get('old_food_raw', '?')} → {_meal_refine.get('new_food_raw', '?')}",
        )

    # v21: Standalone nearby — check BEFORE _resolve_nearby_reference so bare
    # queries like "找一家附近的餐馆" never touch the previous route's points.
    if has_route and _is_standalone_nearby(text):
        print(
            "[NearbyDispatchAudit] standalone_nearby=true "
            "skip_previous_destination=true reason=no_explicit_route_reference"
        )
        return ConversationRouteDecision(
            mode="new_plan", confidence=0.88,
            latest_user_intent_summary=text,
            earliest_step="step1",
            reason="standalone nearby request, not route continuation",
        )

    # v21: Resolve "附近" context: previous_destination vs standalone
    _nearby_ref = _resolve_nearby_reference(text, route_context) if has_route else None
    print(f"[DEBUG nearby_ref] result={_nearby_ref.get('source') if _nearby_ref else 'None'} label={_nearby_ref.get('label') if _nearby_ref else ''}")
    if _nearby_ref and _nearby_ref.get("source") == "previous_destination":
        # Contextual nearby: "附近" refers to previous destination → follow_up
        return ConversationRouteDecision(
            mode="follow_up", confidence=_nearby_ref.get("confidence", 0.90),
            latest_user_intent_summary=text,
            earliest_step="step1",
            reason=f"contextual nearby lookup at previous_destination={_nearby_ref.get('label')}",
            include_constraints={"contextual_search_center": _nearby_ref},
        )

    # v21: Resolve point references before edit detection
    _resolved_ref = _resolve_point_references(text, route_context)
    _resolved_text = text
    if _resolved_ref:
        _resolved_text = text.replace(
            re.search(r"(第二个|换一个|不要这个|那里|那个)", text).group(1), _resolved_ref
        ) if re.search(r"(第二个|换一个|不要这个|那里|那个)", text) else text
        print(f"[DEBUG point_ref] resolved: '{text[:60]}' → target='{_resolved_ref}'")

    # Detect continuation: must have explicit route-referencing words
    _has_continuation = any(t in text for t in [
        "加到当前路线", "加到路线", "路上顺便", "再增加",
        "在刚才路线", "上个路线", "当前路线", "刚才路线", "沿.*路线",
        "把.*删", "把.*换", "把.*替", "替换", "删除",
    ])
    # v21: Route continuation patterns — "晚上去图书馆", "下午再去公园" etc.
    _time_slot_prefix = re.search(r"^(晚上|傍晚|下午|中午|夜里|夜间|接着|然后|再|最后)", text)
    _has_category_only = bool(re.search(r"(去|找个|找一家|逛|看看)(图书馆|公园|咖啡馆|博物馆|书店|餐厅|商场|夜景)", text))
    if _time_slot_prefix and _has_category_only:
        _has_continuation = True

    if re.search(r"(?:加到|路上|沿途|删|换|替|刚才|当前)", text):
        _has_continuation = True

    _has_shopping_new = any(t in text for t in ["伴手礼", "特产", "文创", "礼物", "纪念品",
                                                  "买点", "买个", "带回去"])
    _has_nearby = any(t in text for t in ["附近", "周边", "离我近", "就近"])
    if _has_nearby and _has_shopping_new and has_route and not _has_continuation:
        return ConversationRouteDecision(
            mode="new_plan", confidence=0.88,
            latest_user_intent_summary=text,
            earliest_step="step1",
            reason="standalone nearby shopping request, not route continuation",
        )

    # Clear date + planning intent without continuation → new plan
    has_date = any(t in text for t in _CLEAR_NEW_PLAN_TOKENS)
    has_edit_word = any(w in text for w in _EXPLICIT_REPLACE_TOKENS + _EXPLICIT_REMOVE_TOKENS + _EXPLICIT_ADD_TOKENS)
    if has_date and not _has_continuation and not has_edit_word:
        return ConversationRouteDecision(
            mode="new_plan", confidence=0.85,
            latest_user_intent_summary=text,
            earliest_step="step1",
            reason="explicit date + planning intent without continuation",
        )

    # v26+v27: Category-level exclusion detection — MUST run BEFORE point edit detection.
    # "不想去咖啡馆了。修改下路线" → remove_category:cafe, not point_edit with bad target_name.
    _cat_exclusion = _detect_category_exclusion(text, source="dispatch")
    if _cat_exclusion and has_route:
        print(
            f"[CategoryExclusionAudit] source=dispatch matched=true "
            f"category={_cat_exclusion['category_id']} action=remove_category "
            f"text={text[:80]}"
        )
        return ConversationRouteDecision(
            mode="point_edit", confidence=0.95,
            latest_user_intent_summary=text,
            earliest_step="local_replan",
            point_operations=[{
                "action": "remove_category",
                "target_name": "",
                "target_category": _cat_exclusion["category_id"],
                "target_terms": _cat_exclusion["target_terms"],
                "target_typecodes": _cat_exclusion["target_typecodes"],
            }],
            exclude_constraints={
                "excluded_categories": [_cat_exclusion["category_id"]],
                "excluded_terms": _cat_exclusion["target_terms"],
                "excluded_typecodes": _cat_exclusion["target_typecodes"],
                "preserve_previous_intent": True,
            },
            reason=f"category-level exclusion: {_cat_exclusion['category_id']} (raw={_cat_exclusion['raw_target']})",
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

    if ops and _has_continuation:
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

    # v21: Feature/facility change without explicit edit → need full re-parse
    if _has_field_edits(text) and has_route:
        return ConversationRouteDecision(
            mode="refine_current", confidence=0.78,
            latest_user_intent_summary=text,
            earliest_step="step1",
            reason="feature/facility change detected, need full re-parse",
        )

    if _has_continuation:
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


# v21: Point reference resolution — resolve "第二个", "那里", "换一个", etc.
def _resolve_point_references(
    text: str,
    route_context: dict[str, Any] | None,
    last_recommendation: str = "",
) -> str | None:
    """Resolve positional/situational references to actual POI names.
    Returns the resolved POI name, or None if no reference detected.
    """
    if not route_context or not route_context.get("points"):
        return None
    points = route_context.get("points", [])
    point_names = [p.get("name", "") for p in points if p.get("name")]
    if not point_names:
        return None

    # "第二个" → display_order=2
    m = re.search(r"第([一二三四五六七八九\d]+)个", text)
    if m:
        ord_num = m.group(1)
        ord_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        idx = ord_map.get(ord_num, int(ord_num) if ord_num.isdigit() else 0) - 1
        if 0 <= idx < len(points):
            return points[idx].get("name", "")
        return None

    # "换一个" / "不要这个" → last_recommendation
    if any(w in text for w in ["换一个", "不要这个", "这个不要", "换一家"]):
        if last_recommendation:
            return last_recommendation

    # "那里" / "那个" → previous turn explicit location
    if any(w in text for w in ["那里", "那个地方", "那儿"]):
        prev_intent = route_context.get("previous_intent") or {}
        prev_target = (prev_intent.get("primary_query") or
                       prev_intent.get("resolved_destination_name") or "")
        if prev_target:
            return prev_target

    return None


# v21: Detect standalone nearby requests that should NOT inherit route
def _normalize_route_location(value: Any) -> dict[str, float] | None:
    """Normalize a route-context location to {lng, lat} or None.

    Handles dict (with lng/lat or longitude/latitude), "lng,lat" string,
    [lng, lat] list, and invalid/empty values — always safe, never crashes.
    """
    if isinstance(value, dict):
        lng = value.get("lng", value.get("longitude"))
        lat = value.get("lat", value.get("latitude"))
    elif isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 2:
            return None
        lng, lat = parts
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        lng, lat = value
    else:
        return None

    try:
        lng_value = float(lng)
        lat_value = float(lat)
    except (TypeError, ValueError):
        return None

    if not (-180 <= lng_value <= 180 and -90 <= lat_value <= 90):
        return None
    return {"lng": lng_value, "lat": lat_value}


def _is_standalone_nearby(text: str) -> bool:
    """Return True if this is a standalone nearby request with no explicit route reference.

    '找一家附近的餐馆' → standalone (new task)
    '那里附近找一家餐馆' → NOT standalone (contextual reference to previous route)
    """
    _has_nearby = any(t in text for t in ["附近", "周边", "离我近", "就近", "周围"])
    _has_continuation = any(t in text for t in [
        "加到当前路线", "加到路线", "路上顺便", "沿途", "再增加",
        "替换", "在刚才路线", "上个路线", "当前路线", "刚才路线",
        "把.*删", "把.*换", "把.*替",
    ])
    _has_context_reference = any(t in text for t in [
        "那里", "那儿", "那边", "那附近", "刚才那里", "刚才那边",
        "上一个地方附近", "刚才推荐的地方附近", "那家店旁边",
    ])
    return _has_nearby and not _has_continuation and not _has_context_reference


# v21: Resolve "附近" reference in multi-turn context
def _resolve_nearby_reference(
    current_text: str,
    route_context: dict[str, Any] | None,
) -> dict | None:
    """Resolve '附近' to previous_destination when temporal/spatial continuity exists.

    Returns contextual search center dict or None if no continuity.
    All access to route_context fields is type-checked — never calls .get() on
    non-dict values (handles str locations like "lng,lat" from Gaode).
    """
    if not route_context or not route_context.get("points"):
        return None

    # Must contain "附近" without explicit location
    _has_nearby = any(t in current_text for t in ["附近", "周边", "离我近", "就近", "周围"])
    if not _has_nearby:
        return None

    # v21: Expand "那附近/那里/那边" as explicit contextual reference
    _has_demonstrative = any(t in current_text for t in [
        "那附近", "那里附近", "那边", "那儿附近",
        "刚才那附近", "刚才那里", "上一个地方附近",
        "刚才推荐的地方附近", "那家店旁边",
    ])
    if _has_demonstrative:
        # Direct contextual reference — boost confidence
        pass  # continue to resolve previous destination

    # v22: Fresh-start "待会儿/现在" nearby request → standalone, not follow_up
    _fresh_start = any(t in current_text for t in [
        "待会儿", "现在", "等会儿", "一会儿", "等下",
    ])
    _has_direct_me = any(t in current_text for t in [
        "我现在在", "我在", "我附近", "当前位置", "这附近", "这边",
    ])
    if not _has_demonstrative and (_fresh_start or _has_direct_me):
        print(
            f"[NearbyDispatchAudit] standalone_nearby=true source=home_location "
            f"skip_previous_destination=true fresh_start={_fresh_start}"
        )
        return None

    # Must NOT contain explicit new location (unless demonstrative)
    if not _has_demonstrative:
        if _has_direct_me:
            return None

    # Must NOT be new topic with different temporal scope
    _new_temporal = any(t in current_text for t in [
        "下周", "下个月", "周末", "后天", "另一天",
    ])

    # Check temporal continuity: both turns have same temporal marker
    prev_intent = route_context.get("previous_intent") or {}
    # Safe: ensure prev_intent is a dict
    prev_intent = prev_intent if isinstance(prev_intent, dict) else {}
    prev_req = (route_context.get("previous_user_messages") or [])[-1] if route_context.get("previous_user_messages") else ""
    if not prev_req:
        prev_req = str(prev_intent.get("raw_keywords", "") or "")

    _same_temporal = False
    _temporal_markers = ["明天", "今天", "后天", "周末"]
    for tm in _temporal_markers:
        if tm in current_text and tm in prev_req:
            _same_temporal = True
            break

    # If no temporal markers in either, also consider it continuous
    _no_temporal_in_either = not any(tm in current_text for tm in _temporal_markers) and \
                              not any(tm in prev_req for tm in _temporal_markers)

    if _new_temporal:
        return None
    # v21: Demonstrative references ("那附近") skip temporal check — explicit context ref
    if not _has_demonstrative and not (_same_temporal or _no_temporal_in_either):
        return None  # different temporal context → standalone

    # Find previous destination or search area (safe: prev_intent is always a dict)
    _dest = (prev_intent.get("search_area_label") or
             prev_intent.get("resolved_destination_name") or
             prev_intent.get("destination") or "")
    _dest_loc = _normalize_route_location(
        prev_intent.get("search_area_location") or prev_intent.get("original_location")
    )

    if not _dest or not _dest_loc:
        # Try to find destination from route points
        raw_points = route_context.get("points", [])
        points = [p for p in raw_points if isinstance(p, dict)] if isinstance(raw_points, list) else []
        for pt in points:
            if pt.get("kind") == "destination" or pt.get("role") == "destination":
                _candidate_dest = pt.get("name", "")
                _candidate_loc = _normalize_route_location(pt.get("location"))
                if _candidate_loc and _candidate_dest:
                    _dest = str(_candidate_dest)
                    _dest_loc = _candidate_loc
                    break
        if not _dest or not _dest_loc:
            # Last non-start POI with valid location
            for pt in reversed(points):
                if pt.get("kind") not in ("start",) and pt.get("name"):
                    _candidate_loc2 = _normalize_route_location(pt.get("location"))
                    if _candidate_loc2:
                        _dest = str(pt.get("name", ""))
                        _dest_loc = _candidate_loc2
                        break

    if not _dest or not _dest_loc:
        print(f"[DEBUG nearby_ref] no valid destination: dest={_dest} loc={_dest_loc}")
        return None

    print(f"[DEBUG nearby_ref] resolved: source=previous_destination label={_dest} same_temporal={_same_temporal}")
    return {
        "source": "previous_destination",
        "label": _dest,
        "location": _dest_loc,
        "confidence": 0.92 if _same_temporal else 0.75,
        "reason": f"temporal continuity ({'same markers' if _same_temporal else 'no markers'}), previous destination={_dest}",
    }


def _has_field_edits(text: str) -> bool:
    field_words = ("预算", "人均", "交通", "打车", "公交", "地铁", "步行", "骑行",
                    "上午", "下午", "晚上", "出发", "时间", "改成", "换成")
    # v21: Restroom/toilet utility — never answer_only, always utility lookup
    _restroom_kws = ("厕所", "卫生间", "洗手间", "公厕", "上厕所", "WC", "wc", "如厕")
    if any(kw in text for kw in _restroom_kws):
        return True
    # v21: Feature/facility changes require full re-parse and re-search
    feature_add_words = (
        "有露台", "露台", "开放露台", "户外露台", "rooftop", "terrace",
        "有草坪", "草坪", "草地", "能坐", "可以坐", "能躺着",
        "能看夜景", "夜景", "看城市", "观景台",
        "安静", "不被打扰", "独处", "个人待",
    )
    if any(w in text for w in feature_add_words):
        return True
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
    """v20: Distinguish scheduled exploration from closed task chains.

    Time words (上午/下午/晚上) are scheduling signals, NOT planned-mode proof.
    Only hard task chains (买东西→理发→回家) force planned mode.
    """
    # Normalize frequent spoken task verbs before counting.  Step1's planned
    # waypoint parser already performs the same normalization; dispatch must
    # agree with it or the planned parser and its rule hints are never enabled.
    normalized_text = str(text or "")
    for source, target in {
        "理个发": "理发",
        "剪个头": "剪发",
        "剪头发": "剪发",
        "做头发": "美发",
        "洗剪吹": "理发",
    }.items():
        normalized_text = normalized_text.replace(source, target)

    # Signals that indicate open-ended exploration (always → exploratory)
    exploration_signals = [
        "逛逛", "逛街", "逛", "随便逛", "走走", "溜达", "散步",
        "游览", "看看", "看", "玩", "拍照", "打卡", "citywalk",
    ]
    # Hard task-chain verbs → planned
    task_chain_signals = [
        "买", "取", "送", "办事", "理发", "回家", "下班",
        "顺路", "接人", "通勤",
    ]
    # Strict sequence connectors (only relevant when paired with task verbs)
    sequence_signals = ["先", "再", "然后", "接着", "最后"]

    has_exploration = any(s in normalized_text for s in exploration_signals)
    has_tasks = any(s in normalized_text for s in task_chain_signals)

    # Rule 1: exploration always wins over pure scheduling
    if has_exploration:
        return "exploratory"
    # Rule 2: task verbs or strong sequence chain → planned
    if has_tasks:
        seq_count = sum(1 for s in sequence_signals if s in normalized_text)
        task_count = sum(1 for s in task_chain_signals if s in normalized_text)
        if task_count + seq_count >= 2:
            return "planned"
    # Rule 2b: pure "先X再Y最后Z" with no exploration → planned
    seq_count = sum(1 for s in sequence_signals if s in normalized_text)
    if seq_count >= 2 and not has_exploration:
        return "planned"
    # Rule 3: default to exploratory (safest — won't skip Step2)
    return "exploratory"


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


# ── v24: meal preference detection flag ──

def is_meal_preference_refine_decision(decision: "PlanningDispatchDecision | ConversationRouteDecision | None") -> bool:
    """Check if a dispatch decision is a meal preference replacement."""
    if decision is None:
        return False
    patch = getattr(decision, "intent_patch", None) or {}
    return bool(patch.get("meal_replacement", False))


# ── v26: category-level exclusion detection ──

# Mapping from user-facing category words → internal category_id + search terms + typecodes
_CATEGORY_EXCLUSION_MAP: dict[str, dict] = {
    "cafe": {
        "category_id": "cafe",
        "aliases": ["咖啡馆", "咖啡店", "咖啡厅", "咖啡", "coffee", "cafe", "café"],
        "typecodes": ["050400", "050500"],
        "negative_terms": ["瑞幸", "星巴克", "manner", "Manner", "Costa", "costa", "Seesaw",
                           "M Stand", "Tim Hortons", "皮爷", "peets", "%Arabica"],
    },
    "specialty_shop": {
        "category_id": "specialty_shop",
        "aliases": ["特色小店", "买手店", "文创店", "杂货店", "生活方式集合店", "集合店"],
        "typecodes": ["060100", "060900", "061000", "080300"],
        "negative_terms": [],
    },
    "restaurant": {
        "category_id": "restaurant",
        "aliases": ["餐厅", "饭店", "吃饭", "正餐", "餐馆", "饭馆", "食府", "酒楼"],
        "typecodes": ["050100", "050200", "050300"],
        "negative_terms": [],
    },
    "bar": {
        "category_id": "bar",
        "aliases": ["酒吧", "清吧", "pub", "bar", "酒馆", "精酿"],
        "typecodes": ["080304", "080300"],
        "negative_terms": [],
    },
    "bookstore": {
        "category_id": "bookstore",
        "aliases": ["书店", "独立书店", "书局", "书吧"],
        "typecodes": ["060400"],
        "negative_terms": [],
    },
}

# Trigger words that signal the user wants to REMOVE a category
_CATEGORY_REMOVE_TRIGGERS = [
    "不想去", "不想要", "不要去", "不要", "别去", "别安排", "别要",
    "去掉", "删除", "删掉", "跳过", "略过", "不去", "免了",
    "不要了", "不想要了", "不想去了", "不安排", "不喝", "不想喝",
    # pattern: "X就不要了" / "X去掉" / "不安排X了" / "不喝X了" / "不想喝X了"
]

# v27: Strong negation triggers that ALWAYS indicate category removal intent
_STRONG_CATEGORY_NEGATION_TRIGGERS = [
    "不想去", "不想要", "不要去", "别去", "别安排", "不去",
    "不要了", "不想要了", "不想去了", "不安排", "不喝", "不想喝",
    "去掉", "删除", "删掉", "跳过",
]

# v26: compiled negation patterns for category exclusion
_CATEGORY_NEGATION_RE = re.compile(
    r"(?:"
    + "|".join(re.escape(t) for t in _CATEGORY_REMOVE_TRIGGERS)
    + r")\s*(.+?)(?:了|吧|呀|呢|吗|哦)?\s*(?:[，,。；;]|修改下路线|修改路线|调整下|调整路线|$)"
)


def _detect_category_exclusion(text: str, source: str = "fast") -> dict | None:
    """Detect category-level exclusion patterns like '不想去咖啡馆了'.

    Returns a dict with category_id, target_terms, target_typecodes, raw_target
    if a known category is being negated.  Returns None otherwise.

    This is DIFFERENT from _is_meal_preference_refine which handles cuisine
    replacement ('不想吃烤鸭→想吃川菜').  Category exclusion removes an entire
    POI class without specifying a replacement.

    v27: Now accepts a `source` parameter for audit logging. Detection is
    strengthened to handle trailing edit phrases like "帮我把路线改一下".
    """
    text = text.strip()

    # Must contain a negation trigger
    has_trigger = any(t in text for t in _CATEGORY_REMOVE_TRIGGERS)
    if not has_trigger:
        return None

    # Must NOT be a meal preference replacement (those have food terms + "吃")
    if any(t in text for t in ["想吃", "换成", "改成", "换为"]):
        return None

    # v27: Also reject if "吃" + food chars dominate — meal, not category
    _has_eat = "吃" in text
    _has_food_term = any(
        c in text for c in ["烤鸭", "川菜", "火锅", "涮肉", "粤菜", "湘菜",
                            "日料", "西餐", "海鲜", "素食", "清真", "面馆"]
    )
    if _has_eat and _has_food_term:
        return None

    # Try to match against known categories
    text_lower = text.lower()
    for cat_key, cat_info in _CATEGORY_EXCLUSION_MAP.items():
        # Check if any alias appears in the text near a negation trigger
        for alias in cat_info["aliases"]:
            if alias.lower() in text_lower:
                # Build full target terms: aliases + negative_terms
                target_terms = list(dict.fromkeys(
                    cat_info["aliases"] + cat_info["negative_terms"]
                ))
                result = {
                    "category_id": cat_info["category_id"],
                    "target_terms": target_terms,
                    "target_typecodes": list(cat_info["typecodes"]),
                    "raw_target": alias,
                }
                print(
                    f"[CategoryExclusionAudit] source={source} matched=true "
                    f"category={cat_info['category_id']} action=remove_category "
                    f"text={text[:80]}"
                )
                return result

    # v27: No explicit category alias found, but strong negation trigger present
    # — log the miss for debugging
    _strong = any(t in text for t in _STRONG_CATEGORY_NEGATION_TRIGGERS)
    if _strong:
        print(
            f"[CategoryExclusionAudit] source={source} matched=false "
            f"text={text[:80]} reason=strong_trigger_no_category_match"
        )
    return None


def is_category_exclusion_decision(decision: "ConversationRouteDecision | PlanningDispatchDecision | None") -> bool:
    """Check whether a dispatch decision represents a category-level exclusion."""
    if decision is None:
        return False
    ops = getattr(decision, "point_operations", None) or []
    for op in ops:
        if isinstance(op, dict) and op.get("action") in ("remove_category",):
            return True
    return False


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
