"""
美团 AI 对话路由 - 流式版本
调用 backend/services/ 中的 pipeline 处理用户对话
支持 SSE 流式输出规划进度，使用不同的 event 类型区分消息
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import datetime as dt
import logging
import json
import re
import sys
import os
import time

logger = logging.getLogger(__name__)

SSE_HEARTBEAT_SECONDS = float(os.getenv("SSE_HEARTBEAT_SECONDS", "15"))
SSE_STREAM_MAX_SECONDS = float(os.getenv("SSE_STREAM_MAX_SECONDS", "240"))

router = APIRouter(prefix="/api/meituan", tags=["美团AI对话"])


class GuestProfileSchema(BaseModel):
    """游客画像（前端传入）"""
    nickname: str = "游客"
    gender: str = "男"
    age: int = 30
    activity_pref_tag: list[str] = []
    food_pref_tag: list[str] = []
    permanent_city: list[str] = []
    permanent_city_coord: dict = {}
    current_device_location: dict | None = None
    home_location: dict | None = None
    budget_per_capita: float = 100.0


class RouteContextSchema(BaseModel):
    route_id: str | None = None
    point_names: list[str] = []
    candidate_names: list[str] = []
    points: list[dict] = []
    segments: list[dict] = []
    exclusions: list[str] = []
    recent_user_messages: list[str] = []
    # v17: 多轮对话上下文
    context_source: str | None = None
    previous_user_messages: list[str] = []
    previous_intent: dict | None = None
    previous_complete_plan: dict | None = None
    current_route_compact: dict | None = None
    # v21: 待补充意图 — 澄清阶段保留的partial intent
    pending_intent: dict | None = None
    # v21: 上一轮 pipeline 状态标记
    previous_pipeline_status: str = ""   # "completed" | "failed" | "clarification_needed" | ""


class ChatRequest(BaseModel):
    message: str
    user_id: str = "default"
    plan_mode: str = "auto"  # v18: "auto" — 后端 LLM 自动判断 exploratory/planned，不信任前端
    guest_profile: GuestProfileSchema | None = None
    client_sent_at: str | None = None
    client_timezone: str | None = None
    route_context: RouteContextSchema | None = None


class ChatResponse(BaseModel):
    reply: str
    route: dict
    intent: dict


def _extract_route_data(complete_plan, micro_pois, route_segments):
    """从 pipeline 输出中提取路线数据"""
    route_data = {
        "polyline": "",
        "pois": [],
        "days": 0,
        "day_plans": [],
        "anchors": [],
        "polylines": [],
        "summary": "",
    }

    if not complete_plan:
        return route_data

    # 提取天数
    route_data["days"] = len(complete_plan.day_plans) if complete_plan.day_plans else 0

    # 提取每日计划
    if complete_plan.day_plans:
        for day in complete_plan.day_plans:
            day_info = {
                "day_index": day.day_index,
                "anchors": [],
                "meal_slots": day.meal_slots,
            }
            for anchor in day.anchors:
                anchor_info = {
                    "name": anchor.name,
                    "recommend_reason": getattr(anchor, 'recommend_reason', ''),
                    "location": anchor.location,
                    "typecode": getattr(anchor, 'typecode', ''),
                    "final_score": getattr(anchor, 'final_score', 0),
                }
                day_info["anchors"].append(anchor_info)
                route_data["anchors"].append(anchor_info)
            route_data["day_plans"].append(day_info)

    # 提取 POI 信息
    for poi in micro_pois:
        poi_info = {
            "name": poi.name,
            "location": poi.location,
            "typecode": poi.typecode,
            "is_meal": poi.is_meal,
            "parent_anchor": poi.parent_anchor,
            "gaode_rating": poi.gaode_rating,
            "avg_cost": poi.avg_cost,
        }
        route_data["pois"].append(poi_info)

    # 提取 polyline
    for segment in route_segments:
        if segment.polyline:
            route_data["polylines"].append({
                "day_index": segment.day_index,
                "from_poi": segment.from_poi,
                "to_poi": segment.to_poi,
                "polyline": segment.polyline,
                "transport": segment.transport,
                "duration_min": segment.duration_min,
                "distance_km": segment.distance_km,
            })

    # 生成摘要
    if route_data["anchors"]:
        anchor_names = [a["name"] for a in route_data["anchors"]]
        route_data["summary"] = (
            f"为您规划了{route_data['days']}天的行程，"
            f"包含{len(anchor_names)}个景点：{'、'.join(anchor_names[:5])}"
        )

    return route_data


def _extract_intent_data(parsed_intent):
    """从意图解析结果中提取数据"""
    if not parsed_intent:
        return {}

    intent_data = {
        "duration": getattr(parsed_intent, 'duration', ''),
        "start_time": (
            parsed_intent.start_time.isoformat()
            if getattr(parsed_intent, 'start_time', None) else None
        ),
        "raw_keywords": getattr(parsed_intent, 'raw_keywords', []),
        "search_keywords": getattr(parsed_intent, 'search_keywords', []),
        "fixed_pois": [],
        "food_pref_keywords": getattr(parsed_intent, 'food_pref_keywords', []),
        "budget_per_capita": getattr(parsed_intent, 'budget_per_capita', None),
        "transport_hint": getattr(parsed_intent, 'transport_hint', '公共交通'),
        "evening_requested": getattr(parsed_intent, 'evening_requested', False),
    }

    for fp in getattr(parsed_intent, 'fixed_pois', []):
        intent_data["fixed_pois"].append({
            "name": fp.name,
            "user_time_budget": fp.user_time_budget,
        })

    return intent_data


# 导入 backend/services 中的模块
from services.utils import (
    PipelineLogger,
    ZeroOutputError,
    emit_status,
    push_output,
    emit_result,
    emit_done,
    emit_error,
    init_sse_queue,
    get_sse_queue,
    reset_pipeline_stats,
    SSE_EVENT_STATUS,
    SSE_EVENT_RESULT,
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
)
from services.data_schema import CompletePlan, MicroPOI, RouteSegment
from services.mock_profile import get_mock_profile, build_profile_from_guest
from services.step1_intent import run_step1
from services.step2_macro import run_step2
from services.step3_micro import run_step3
from services.step4_output import run_step4
from services.api_client import gaode_text_search, gaode_around_search, gaode_around_search_batch
from services.pipeline_replan_service import apply_pipeline_replan
from services.poi_typecodes import (
    category_for_query,
    get_search_keywords,
    get_typecodes_for_planned,
    validate_poi_category,
)
from services.conversation_replan import (
    classify_conversation_route_change,
    classify_conversation_route_change_fast,
    classify_planning_dispatch,
    _detect_plan_mode_from_text,
    _planning_dispatch_fast_fallback,
    PlanningDispatchDecision,
)
from services.conversation_clarification import (
    clarification_reply,
    merge_pending_clarification,
)

# ═══ v11: 聊天编辑意图分类 ═══

_EDIT_ADD_WORDS = (
    "加一个", "增加", "加上", "再加", "再安排",
    "还想去", "我还想去", "也想去", "另外想去",
    "顺便去", "顺便加", "再去"
)
_EDIT_REMOVE_WORDS = ("不想去", "不要", "不去了", "去掉", "删除", "删掉", "别安排", "跳过")
_EDIT_REPLACE_WORDS = ("替换成", "替换为", "换成", "改成")


def _clean_place_name(text: str) -> str:
    text = re.sub(r"[，。,.!?！？；;、\s]+$", "", text.strip())
    text = re.sub(r"^(一个|一下|去|到|成|为)", "", text)
    text = re.sub(r"(吧|呀|呢|可以吗|行吗|其他安排不变|其余不变|别的地方|其他地方)$", "", text).strip()
    return text


def _match_route_point(text: str, names: list[str]) -> str | None:
    for name in sorted([n for n in names if n], key=len, reverse=True):
        if name in text or text in name:
            return name
    return None


def _looks_like_full_planning_request(text: str) -> bool:
    """检测完整的多时段/多活动新规划请求"""
    time_words = ("上午", "中午", "下午", "晚上", "午饭", "午餐", "晚饭", "晚餐", "早餐")
    date_words = ("今天", "明天", "后天", "周末", "下周", "一天", "两天", "三天", "一整天", "半天")
    plan_words = ("规划", "路线", "安排", "逛逛", "游览", "玩", "吃饭", "吃个", "找个", "推荐")
    connectors = ("，", ",", "。", "；", ";", "然后", "再", "接着", "顺便")

    time_count = sum(1 for w in time_words if w in text)
    has_date = any(w in text for w in date_words)
    has_plan = any(w in text for w in plan_words)
    has_connector = any(w in text for w in connectors)

    if time_count >= 2:
        return True
    if has_date and has_plan:
        return True
    if has_connector and has_plan and len(text) >= 18:
        return True
    return False


def _has_explicit_edit_intent(text: str) -> bool:
    """检测用户是否明确表达了对当前路线的编辑意图"""
    explicit_words = (
        "当前路线", "这条路线", "刚才", "上一条", "原路线",
        "其他安排不变", "其余不变", "保持不变",
        "替换成", "替换为", "换成", "改成",
        "不想去", "不要", "不去了", "去掉", "删除", "删掉", "别安排", "跳过",
        "加一个", "增加", "加上", "再加", "再安排", "还想去", "我还想去",
        "也想去", "另外想去", "顺便去", "顺便加", "再去"
    )
    return any(w in text for w in explicit_words)


def _is_concrete_place_name(name: str) -> bool:
    if not name:
        return False
    bad_words = ("路线", "规划", "安排", "地方", "好吃", "吃饭", "午饭", "晚饭", "上午", "下午", "晚上", "然后", "顺便")
    return not any(w in name for w in bad_words)


def _extract_add_place_after(text: str, word: str) -> str:
    tail = text.split(word, 1)[1].strip()
    tail = re.split(r"[，,。；;、]|然后|接着|晚上|下午|上午|中午|午饭|晚饭|午餐|晚餐", tail, maxsplit=1)[0]
    return _clean_place_name(tail)


_CONTINUATION_SLOT_PREFIXES = {
    "上午": "morning",
    "中午": "noon",
    "下午": "afternoon",
    "傍晚": "evening",
    "晚上": "evening",
    "今晚": "evening",
    "夜里": "evening",
    "夜间": "evening",
}


def _extract_temporal_append(text: str) -> tuple[str, str] | None:
    """识别已有路线后的自然语言续程，如“晚上去电影院”。"""
    match = re.match(
        r"^(上午|中午|下午|傍晚|晚上|今晚|夜里|夜间)"
        r"(?:再|接着|然后|最后|还)?(?:想)?"
        r"(?:去|到|逛|看|找个|找一家|安排|吃)"
        r"(.{1,30})$",
        text.strip(),
    )
    if not match:
        return None
    target = _clean_place_name(match.group(2))
    target = re.sub(r"(?:走走|逛逛|看看|转转|玩玩|一下)$", "", target).strip()
    if not target or not _is_concrete_place_name(target):
        return None
    return target, _CONTINUATION_SLOT_PREFIXES[match.group(1)]


def _continuation_endpoint(route_context: RouteContextSchema | None) -> dict | None:
    """返回当前路线最后一个真实游玩点，续程不得重新使用家庭起点。"""
    if not route_context:
        return None
    candidates = [
        point for point in route_context.points
        if point.get("kind") not in ("start", "hint")
        and point.get("is_waypoint", True)
        and point.get("location")
    ]
    return candidates[-1] if candidates else None


def _classify_chat_edit(user_request: str, route_context: RouteContextSchema | None) -> dict:
    text = user_request.strip()
    point_names = route_context.point_names if route_context else []
    has_route = bool(route_context and route_context.points)

    # v12: 完整规划请求保护 — 有历史路线但当前是完整新规划
    if has_route and _looks_like_full_planning_request(text) and not _has_explicit_edit_intent(text):
        return {
            "action": "new_plan",
            "target_name": None,
            "new_name": None,
            "reason": "full planning request; skip chat edit"
        }

    new_plan_tokens = ("重新规划", "新路线", "下周", "明天", "后天", "周末", "两天", "三天", "杭州", "北京", "苏州")
    has_edit_word = any(w in text for w in _EDIT_ADD_WORDS + _EDIT_REMOVE_WORDS + _EDIT_REPLACE_WORDS) or "其他安排不变" in text
    if has_route and any(t in text for t in new_plan_tokens) and not has_edit_word:
        return {"action": "new_plan", "target_name": None, "new_name": None, "reason": "new plan signal without edit word"}

    for word in _EDIT_REPLACE_WORDS:
        if word in text:
            left, right = text.split(word, 1)
            left = re.sub(r"^(把|将|请把|帮我把)", "", left).strip()
            target = _match_route_point(left, point_names) or _clean_place_name(left)
            new_name = _clean_place_name(right)
            if target and new_name and new_name not in ("别的地方", "其他地方", "另一个", "换一个"):
                return {"action": "replace", "target_name": target, "new_name": new_name, "reason": f"matched replace word {word}"}
            if target:
                return {"action": "remove", "target_name": target, "new_name": None, "reason": f"replace without concrete new name {word}"}

    if any(w in text for w in _EDIT_REMOVE_WORDS):
        target = _match_route_point(text, point_names)
        if target:
            return {"action": "remove", "target_name": target, "new_name": None, "reason": "matched remove with route point"}
        return {"action": "normal", "target_name": None, "new_name": None, "reason": "remove word but no route target"}

    if has_route:
        for word in _EDIT_ADD_WORDS:
            if word in text:
                new_name = _extract_add_place_after(text, word)
                if new_name and _is_concrete_place_name(new_name):
                    return {"action": "add", "target_name": None, "new_name": new_name, "reason": f"matched add word {word}"}

        # v12: 弱 add — 短句"我想去X"且有路线上下文
        weak_add_match = re.match(r"^(?:我)?想去(.{1,20})$", text)
        if weak_add_match and not _looks_like_full_planning_request(text):
            new_name = _clean_place_name(weak_add_match.group(1))
            if new_name and _is_concrete_place_name(new_name):
                return {"action": "add", "target_name": None, "new_name": new_name, "reason": "short weak add"}

        # v23: 单个后续时段天然表示同一天续程，不要求用户必须说“再/接着”。
        temporal_append = _extract_temporal_append(text)
        if temporal_append:
            new_name, display_slot = temporal_append
            return {
                "action": "add",
                "target_name": None,
                "new_name": new_name,
                "display_slot": display_slot,
                "continuation": True,
                "reason": "temporal continuation on current route",
            }

    return {"action": "normal", "target_name": None, "new_name": None, "reason": "no edit rule matched"}


async def _resolve_poi_for_chat_edit(
    name: str,
    city: str = "上海",
    center: dict | None = None,
) -> dict | None:
    """解析新增点；类别型地点优先围绕上一站检索并严格校验类型。"""
    items: list[dict] = []
    category_id = category_for_query(name)
    if center and category_id:
        lng = center.get("lng", center.get("longitude"))
        lat = center.get("lat", center.get("latitude"))
        if lng is not None and lat is not None:
            location = f"{lng},{lat}"
            keywords = list(dict.fromkeys([name, *get_search_keywords(category_id)]))[:4]
            types = get_typecodes_for_planned(category_id)
            for radius in (3000, 5000, 10000):
                for keyword in keywords:
                    try:
                        nearby = await gaode_around_search(
                            location=location,
                            keywords=keyword,
                            radius=radius,
                            types=types,
                            show_fields="business,photos",
                            offset=10,
                            sortrule="distance",
                        )
                    except Exception as exc:
                        print(
                            f"[WARNING chat_edit] nearby lookup failed "
                            f"keyword={keyword} radius={radius}: {exc}"
                        )
                        continue
                    valid = [
                        poi for poi in nearby
                        if validate_poi_category(poi, category_id, require_two_evidence=True)[0]
                    ]
                    if valid:
                        items = valid
                        break
                if items:
                    break

    if not items:
        try:
            text_items = await gaode_text_search(
                name, city=city, show_fields="business,photos", city_limit=True
            )
        except Exception as exc:
            print(f"[WARNING chat_edit] city lookup failed name={name}: {exc}")
            text_items = []
        if category_id:
            text_items = [
                poi for poi in text_items
                if validate_poi_category(poi, category_id, require_two_evidence=True)[0]
            ]
        items = text_items
    if not items:
        return None
    poi = items[0]
    loc = poi.get("location")
    if isinstance(loc, str) and "," in loc:
        lng, lat = loc.split(",", 1)
        loc = {"lng": float(lng), "lat": float(lat)}
    return {
        "poi_id": poi.get("poi_id") or poi.get("id") or poi.get("gaode_poi_id"),
        "gaode_poi_id": poi.get("gaode_poi_id") or poi.get("id") or poi.get("poi_id"),
        "name": poi.get("name") or name,
        "location": loc,
        "typecode": poi.get("typecode", ""),
        "category": poi.get("category") or poi.get("typecode", ""),
        "address": poi.get("address", ""),
        "rating": poi.get("rating") or poi.get("gaode_rating"),
        "avg_cost": poi.get("avg_cost"),
        "kind": "anchor_internal",
        "is_waypoint": True,
        "is_display_poi": True,
    }


async def _emit_preserved_route(
    route_context: RouteContextSchema,
    user_profile,
    message: str,
) -> None:
    """编辑无法完成时保留当前路线，禁止降级成从家出发的新规划。"""
    from collections import defaultdict

    days_data: dict[int, list[dict]] = defaultdict(list)
    for point in route_context.points:
        days_data[int(point.get("day", 1) or 1)].append(point)
    days = []
    for day_idx in sorted(days_data):
        anchors = [
            {
                "name": point.get("name", ""),
                "recommend_reason": point.get("recommend_reason", ""),
                "location": point.get("location"),
            }
            for point in days_data[day_idx]
            if point.get("kind") not in ("start", "meal", "hint")
        ]
        days.append({"day_index": day_idx, "anchors": anchors, "meal_slots": []})

    previous_plan = route_context.previous_complete_plan or {}
    city = (
        user_profile.permanent_city[0]
        if getattr(user_profile, "permanent_city", None)
        else "上海"
    ) or "上海"
    route_data = {
        "route_id": route_context.route_id,
        "points": route_context.points,
        "segments": route_context.segments,
        "candidate_points": [],
        "plan_mode": previous_plan.get("plan_mode") or "chat_edit",
        "total_days": max(days_data.keys(), default=1),
        "display_granularity": "day",
    }
    await push_output(f"[ROUTE_PLANNER]: {message}")
    await emit_done(
        map_paths=[],
        full_plan={
            **previous_plan,
            "summary": message,
            "city": previous_plan.get("city") or city,
            "duration": previous_plan.get("duration") or "a full day",
            "time_budget": previous_plan.get("time_budget") or 1.0,
            "days": days,
        },
        route_data=route_data,
    )


async def _try_chat_edit_replan(
    user_request: str,
    route_context: RouteContextSchema | None,
    user_profile,
    point_operations: list[dict] | None = None,
) -> bool:
    edit = _classify_chat_edit(user_request, route_context)
    # 调度模型已识别出操作时，将其作为本地规则的确定性兜底。
    if edit["action"] == "normal" and point_operations:
        operation = point_operations[0]
        if operation.get("action") in ("add", "remove", "replace"):
            edit = {
                "action": operation.get("action"),
                "target_name": operation.get("target_name"),
                "new_name": operation.get("new_name"),
                "reason": "planning dispatch point operation fallback",
            }
            temporal_append = _extract_temporal_append(user_request)
            if temporal_append and edit["action"] == "add":
                edit["new_name"] = edit.get("new_name") or temporal_append[0]
                edit["display_slot"] = temporal_append[1]
                edit["continuation"] = True
    print(f"[DEBUG chat_edit] action={edit['action']} target={edit['target_name']} new={edit['new_name']} reason={edit['reason']}")

    if edit["action"] in ("normal", "new_plan"):
        return False
    if not route_context or not route_context.points:
        return False

    await emit_status("正在根据您的修改调整路线...")

    operations = []
    point_by_name = {str(p.get("name", "")): p for p in route_context.points}
    target_name = edit.get("target_name")
    target_point = point_by_name.get(target_name) if target_name else None

    if edit["action"] == "remove":
        if not target_point:
            return False
        operations.append({
            "action": "remove",
            "poi_id": target_point.get("poi_id") or target_point.get("gaode_poi_id") or f"{target_name}:{target_point.get('location')}",
            "gaode_poi_id": target_point.get("gaode_poi_id"),
            "poi_name": target_name,
        })

    elif edit["action"] == "replace":
        if not target_point or not edit.get("new_name"):
            return False
        city = (user_profile.permanent_city[0] if getattr(user_profile, "permanent_city", None) else "上海") or "上海"
        new_poi = await _resolve_poi_for_chat_edit(edit["new_name"], city=city)
        if not new_poi:
            return False
        new_poi["day"] = target_point.get("day", 1)
        new_poi["display_slot"] = target_point.get("display_slot", "")
        operations.append({
            "action": "replace",
            "poi_id": target_point.get("poi_id") or target_point.get("gaode_poi_id") or f"{target_name}:{target_point.get('location')}",
            "gaode_poi_id": target_point.get("gaode_poi_id"),
            "poi_name": target_name,
            "poi": new_poi,
        })

    elif edit["action"] == "add":
        if not edit.get("new_name"):
            return False
        city = (user_profile.permanent_city[0] if getattr(user_profile, "permanent_city", None) else "上海") or "上海"
        endpoint = _continuation_endpoint(route_context)
        center = endpoint.get("location") if endpoint else None
        new_poi = await _resolve_poi_for_chat_edit(edit["new_name"], city=city, center=center)
        if not new_poi:
            await _emit_preserved_route(
                route_context,
                user_profile,
                f"我保留了当前路线，但暂时没找到合适的{edit['new_name']}。"
                "可以告诉我具体名称，或让我扩大检索范围。",
            )
            print(
                f"[DEBUG chat_edit] append lookup failed; preserved_current_route=true "
                f"continuation_origin={(endpoint or {}).get('name', '')}"
            )
            return True
        if endpoint:
            new_poi["day"] = int(endpoint.get("day", 1) or 1)
        if edit.get("display_slot"):
            new_poi["display_slot"] = edit["display_slot"]
        operations.append({
            "action": "add",
            "poi_id": new_poi.get("poi_id") or new_poi["name"],
            "poi": new_poi,
            "after_poi_id": (endpoint or {}).get("poi_id") or (endpoint or {}).get("gaode_poi_id"),
            "after_poi_name": (endpoint or {}).get("name"),
        })
        print(
            f"[DEBUG chat_edit] continuation_origin={(endpoint or {}).get('name', '')} "
            f"new_poi={new_poi.get('name', '')} display_slot={new_poi.get('display_slot', '')}"
        )

    result = await apply_pipeline_replan(
        points=route_context.points,
        operations=operations,
        route_id=route_context.route_id,
    )
    route_data = {
        **result["route"],
        "route_id": result["route_id"],
        "candidate_points": [],
        "hints": {},
        "waypoint_annotations": {},
        "plan_mode": "chat_edit",
        "total_days": max([int(p.get("day", 1) or 1) for p in result["route"]["points"]] or [1]),
    }
    summary = "已根据您的要求调整路线。"
    if edit["action"] == "replace":
        summary = f"已将{edit['target_name']}替换为{edit['new_name']}，并重新计算路线。"
    elif edit["action"] == "add":
        summary = f"已为当前路线增加{edit['new_name']}，并重新计算路线。"
    elif edit["action"] == "remove":
        summary = f"已从当前路线移除{edit['target_name']}，并重新计算路线。"

    # v12: 从 result points 合成基本 days 结构，避免前端左栏完全无数据
    from collections import defaultdict
    result_points = result["route"].get("points", [])
    days_data: dict[int, list[dict]] = defaultdict(list)
    for p in result_points:
        days_data[int(p.get("day", 1) or 1)].append(p)
    days_list = []
    for day_idx in sorted(days_data):
        day_pts = days_data[day_idx]
        anchors = [{"name": p.get("name", ""), "recommend_reason": p.get("recommend_reason", ""),
                     "location": p.get("location")} for p in day_pts if p.get("kind") not in ("start", "meal", "hint")]
        meals = [{"name": p.get("name", ""), "meal": p.get("display_slot") or "",
                  "location": p.get("location")} for p in day_pts if p.get("kind") == "meal"]
        days_list.append({"day_index": day_idx, "anchors": anchors, "meal_slots": meals})
    route_data["display_granularity"] = "day"

    await push_output(f"[ROUTE_PLANNER]: {summary}")
    previous_plan = route_context.previous_complete_plan or {}
    city = (user_profile.permanent_city[0] if getattr(user_profile, "permanent_city", None) else "上海") or "上海"
    await emit_done(
        map_paths=[],
        full_plan={
            "summary": summary,
            "city": previous_plan.get("city") or city,
            "duration": previous_plan.get("duration") or "a full day",
            "time_budget": previous_plan.get("time_budget") or 1.0,
            "days": days_list,
        },
        route_data=route_data,
    )
    return True


async def _run_pipeline_stream(
    user_request: str,
    user_id: str,
    plan_mode: str,
    guest_profile: GuestProfileSchema | None = None,
    client_sent_at: str | None = None,
    client_timezone: str | None = None,
    route_context: RouteContextSchema | None = None,
):
    """
    运行美团 pipeline 并流式返回输出
    """
    output_lines = []
    complete_plan = None
    micro_pois = []
    route_segments = []
    parsed_intent = None
    map_file_path = ""

    # 先初始化 SSE 队列，重置资源统计
    queue = asyncio.Queue()
    init_sse_queue(queue)
    reset_pipeline_stats()

    async def _collector():
        """收集 pipeline 输出"""
        nonlocal complete_plan, micro_pois, route_segments, parsed_intent, map_file_path
        
        logger_obj = PipelineLogger()

        try:
            # v22: Destination-first clarification must happen before Step 1.
            # Step 1 post-processing may otherwise inject profile preferences
            # and turn a vague outing wish into an unrelated full route.
            _has_existing_route = bool(route_context and route_context.points)
            # A bare new outing wish remains underspecified even when an older
            # route is still present in the UI.  Do not let stale route context
            # bypass the destination question.
            _clarification = clarification_reply(user_request)
            if _clarification:
                print(
                    f"[DEBUG clarification] action=ask_destination "
                    f"user_request={user_request[:80]}"
                )
                result_data = json.dumps(
                    {
                        "type": "clarification",
                        "content": _clarification,
                        "reply": _clarification,
                        "missing_slot": "destination",
                    },
                    ensure_ascii=False,
                )
                await queue.put(f"event: {SSE_EVENT_RESULT}\ndata: {result_data}\n\n")
                done_data = json.dumps(
                    {"type": "done", "clarification": True},
                    ensure_ascii=False,
                )
                await queue.put(f"event: {SSE_EVENT_DONE}\ndata: {done_data}\n\n")
                return

            # 阶段1：发送进度状态消息
            await emit_status("正在加载用户信息...")

            if guest_profile:
                user_profile = build_profile_from_guest(guest_profile.model_dump())
                logger.info(f"[MeituanChat] 使用游客画像: nickname={user_profile.nickname}, age={user_profile.age}")
            else:
                user_profile = await get_mock_profile(user_id)
            # v6: 优先使用客户端发送时间，解决"待会儿"类表达被服务器时间误判的问题
            current_time = dt.datetime.now().astimezone()
            if client_sent_at:
                try:
                    parsed_client = dt.datetime.fromisoformat(client_sent_at)
                    if parsed_client.tzinfo is None:
                        parsed_client = parsed_client.replace(tzinfo=dt.timezone.utc)
                    target_tz = client_timezone or "Asia/Shanghai"
                    try:
                        import zoneinfo
                        tz = zoneinfo.ZoneInfo(target_tz)
                    except Exception:
                        tz = dt.timezone(dt.timedelta(hours=8))
                    current_time = parsed_client.astimezone(tz)
                except Exception:
                    pass
            print(f"[DEBUG meituan_chat] client_sent_at={client_sent_at} client_timezone={client_timezone} resolved_current_time={current_time}")

            # v18: 统一调度 — LLM 一次性判断 conversation_mode + target_plan_mode
            conv_ctx = {
                "point_names": route_context.point_names if route_context else [],
                "points": route_context.points if route_context else [],
                "candidate_names": route_context.candidate_names if route_context else [],
                "segments": route_context.segments if route_context else [],
                "recent_user_messages": route_context.recent_user_messages if route_context else [],
                "previous_user_messages": route_context.previous_user_messages if route_context else [],
                "previous_intent": route_context.previous_intent if route_context else None,
                "previous_complete_plan": route_context.previous_complete_plan if route_context else None,
                "pending_intent": route_context.pending_intent if route_context else None,
                "previous_pipeline_status": getattr(route_context, "previous_pipeline_status", "") if route_context else "",
            }
            dispatch_decision = None
            plan_mode_for_step1 = "auto"
            step1_request = user_request  # v18: 默认原样传入，refine_current 分支可覆写

            # v21: Merge pending_intent or recover pending_plan from previous_user_messages
            _pending = route_context.pending_intent if route_context else None
            _prev_msgs = route_context.previous_user_messages if route_context else []
            _can_recover_from_msgs = bool(_prev_msgs) and not _pending
            if _can_recover_from_msgs and route_context and not route_context.points:
                _pending = {"destination": "", "duration": "", "raw_keywords": []}
                # Try to recover destination/duration from previous messages
                _prev_text = " ".join(_prev_msgs)
                _city_match = re.search(r"(北京|上海|天津|重庆|广州|深圳|成都|武汉|南京|杭州)", _prev_text)
                if _city_match:
                    _pending["destination"] = _city_match.group(1)
                if "两天" in _prev_text or "两日" in _prev_text or "2天" in _prev_text:
                    _pending["duration"] = "two days"
                    _pending["time_budget"] = 2.0
                elif "一天" in _prev_text or "一日" in _prev_text or "1天" in _prev_text:
                    _pending["duration"] = "a full day"
                    _pending["time_budget"] = 1.0
                if _pending.get("destination") and _pending.get("duration"):
                    print(f"[DEBUG pending_plan] recovered from messages: {_pending}")

            if _pending and _pending.get("destination") and _pending.get("duration"):
                _pending_json = json.dumps(_pending, ensure_ascii=False)
                _prev_msgs_json = json.dumps(_prev_msgs, ensure_ascii=False)
                step1_request = (
                    "<pending_intent_context>\n"
                    "<previous_user_messages>\n"
                    f"{_prev_msgs_json}\n"
                    "</previous_user_messages>\n"
                    "<pending_intent>\n"
                    f"{_pending_json}\n"
                    "</pending_intent>\n"
                    "<latest_user_input>\n"
                    f"{user_request}\n"
                    "</latest_user_input>\n"
                    "</pending_intent_context>\n"
                    "<merge_instruction>\n"
                    "请合并 pending_intent 和 latest_user_input 为完整意图。\n"
                    "- latest_user_input 明确提到的字段覆盖历史值；\n"
                    "- 未提到的字段（destination/duration/time_budget）继承 pending_intent；\n"
                    "- 不得将历史字段重置为空或默认值；\n"
                    "- 信息仍不充分时设置 needs_clarification=true。\n"
                    "</merge_instruction>"
                )
                print(f"[DEBUG pending_intent] merged: dest={_pending.get('destination')} dur={_pending.get('duration')} from={'messages' if _can_recover_from_msgs else 'intent'}")

            if not _has_existing_route:
                step1_request = merge_pending_clarification(
                    user_request,
                    route_context.previous_user_messages if route_context else [],
                )
                if step1_request != user_request:
                    print(
                        f"[DEBUG clarification] action=resume_with_context "
                        f"step1_request={step1_request[:120]}"
                    )
            # v21: Also run dispatch when previous messages exist (failed previous turn)
            _has_prev_msgs = bool(route_context and route_context.previous_user_messages)
            if route_context and (route_context.points or _has_prev_msgs):
                # v21: Recover pending_plan from previous messages even if route failed
                if _has_prev_msgs and not route_context.points:
                    print(
                        f"[DEBUG dispatch] recovering pending_plan from previous_user_messages: "
                        f"count={len(route_context.previous_user_messages)} "
                        f"pending_intent={'yes' if getattr(route_context, 'pending_intent', None) else 'no'}"
                    )

                # v21: Run fast classifier FIRST for clear-cut cases.
                # Only fall back to LLM when fast returns None (ambiguous).
                fast_decision = classify_conversation_route_change_fast(user_request, conv_ctx)
                if fast_decision is not None and fast_decision.mode != "refine_current":
                    # Fast classifier has a clear signal → use it directly
                    dispatch_decision = _planning_dispatch_fast_fallback(user_request, conv_ctx, None)
                    if dispatch_decision is not None:
                        plan_mode_for_step1 = dispatch_decision.target_plan_mode or "auto"
                    print(
                        f"[DEBUG dispatch] classifier=fast "
                        f"conversation_mode={fast_decision.mode} "
                        f"confidence={fast_decision.confidence} "
                        f"reason={fast_decision.reason}"
                    )
                else:
                    try:
                        dispatch_decision = await classify_planning_dispatch(user_request, conv_ctx)
                        if dispatch_decision is not None:
                            plan_mode_for_step1 = dispatch_decision.target_plan_mode or "auto"
                            print(
                                f"[DEBUG dispatch] classifier=llm "
                                f"conversation_mode={dispatch_decision.conversation_mode} "
                                f"target_plan_mode={dispatch_decision.target_plan_mode} "
                                f"previous_plan_mode={dispatch_decision.previous_plan_mode} "
                                f"mode_changed={dispatch_decision.mode_changed} "
                                f"confidence={dispatch_decision.confidence} "
                                f"earliest_step={dispatch_decision.earliest_step} "
                                f"reason={dispatch_decision.reason}"
                            )
                    except Exception as exc:
                        print(f"[WARNING dispatch] llm classifier failed, fallback=fast: {exc}")
                        dispatch_decision = _planning_dispatch_fast_fallback(user_request, conv_ctx, None)
                        if dispatch_decision is not None:
                            plan_mode_for_step1 = dispatch_decision.target_plan_mode or "auto"
            else:
                # No route context: first message, just detect plan_mode from text
                target_pm = _detect_plan_mode_from_text(user_request)
                plan_mode_for_step1 = target_pm
                dispatch_decision = PlanningDispatchDecision(
                    conversation_mode="new_plan",
                    target_plan_mode=target_pm,
                    confidence=0.85,
                    earliest_step="step1",
                    reason="no route context, auto-detected",
                )
                print(
                    f"[DEBUG dispatch] classifier=heuristic conversation_mode=new_plan "
                    f"target_plan_mode={target_pm} previous_plan_mode=None mode_changed=False "
                    f"reason=no route context, auto-detected"
                )

            if dispatch_decision is not None:
                if dispatch_decision.conversation_mode == "new_plan":
                    print(f"[DEBUG dispatch] decision: new_plan → full pipeline")
                elif dispatch_decision.conversation_mode == "point_edit" and route_context and route_context.points:
                    print(f"[DEBUG dispatch] decision: point_edit ops={dispatch_decision.point_operations}")
                    edited = await _try_chat_edit_replan(
                        user_request,
                        route_context,
                        user_profile,
                        point_operations=dispatch_decision.point_operations,
                    )
                    if edited:
                        return
                elif dispatch_decision.conversation_mode == "follow_up":
                    # v21: follow_up — contextual nearby lookup at previous destination
                    _ctx_center = (dispatch_decision.include_constraints or {}).get("contextual_search_center", {})
                    if _ctx_center:
                        user_profile._contextual_search_center = _ctx_center
                        print(
                            f"[DEBUG dispatch] decision: follow_up → contextual nearby "
                            f"label={_ctx_center.get('label')} "
                            f"source={_ctx_center.get('source')} "
                            f"confidence={_ctx_center.get('confidence')}"
                        )
                    step1_request = user_request
                elif dispatch_decision.conversation_mode == "refine_current":
                    _earliest = dispatch_decision.earliest_step or "step1"
                    if _earliest in ("step3", "local_replan") and route_context and route_context.points:
                        # v21: Incremental refine — skip Step1+Step2, search around last route point
                        _last_pt = None
                        for _p in reversed(route_context.points):
                            if _p.get("kind") not in ("start", "hint", "free_explore", "candidate") and _p.get("location", {}).get("lat"):
                                _last_pt = _p
                                break
                        if _last_pt:
                            print(
                                f"[IncrementalRefine] mode=refine_current earliest_step={_earliest} "
                                f"search_center={_last_pt.get('name','')} skip_step1=true skip_step2=true"
                            )
                            await emit_status("正在为您补充附近推荐...")
                            micro_pois, route_segments, map_file_path, anchor_hints, waypoint_annotations, route_points, candidate_points, complete_plan = \
                                await _run_incremental_refine(
                                    parsed_intent, user_profile, complete_plan, logger_obj,
                                    last_point=_last_pt, user_request=user_request,
                                    route_context=route_context,
                                )
                    else:
                        # v21: Full refine_current — merge with previous intent
                        print(f"[DEBUG dispatch] decision: refine_current — merge with previous intent")
                        _prev_intent = conv_ctx.get("previous_intent") or {}
                        _intent_patch = dispatch_decision.intent_patch or {}
                        step1_request = (
                            "<conversation_context>\n"
                            "<previous_intent>\n"
                            f"{json.dumps(_prev_intent, ensure_ascii=False)}\n"
                            "</previous_intent>\n"
                            "<latest_user_input>\n"
                            f"{user_request}\n"
                            "</latest_user_input>\n"
                            "</conversation_context>\n"
                            "<merge_instruction>\n"
                            "请生成合并后的完整旅行意图。\n"
                            "- latest_user_input 明确提到的字段覆盖历史值；\n"
                            "- 未提到的字段继承 previous_intent；\n"
                            "- 不得将历史字段重置为空；\n"
                            "- 不得使用默认值覆盖有效历史值；\n"
                            "- 当前输入是偏好补充时，保留原目的地、时长和路线模式。\n"
                            "</merge_instruction>"
                        )
                        print(f"[DEBUG dispatch] refine_current merge context len={len(step1_request)}")
                elif dispatch_decision.conversation_mode == "answer_only":
                    print(f"[DEBUG dispatch] decision: answer_only — answering without replan")
                    await push_output(f"[ROUTE_PLANNER]: {dispatch_decision.reason or '这个问题不需要重新规划路线。'}")
                    await emit_done(map_paths=[], full_plan={}, route_data={})
                    return
                else:
                    pass

            # Step 1: 意图识别
            await emit_status("正在解析您的出行意图...")
            # [DEBUG-跨时段] 打印实际收到的 user_request
            print(f"[DEBUG meituan_chat] received step1_request={step1_request[:120]} "
                  f"plan_mode_for_step1={plan_mode_for_step1}")
            parsed_intent = await run_step1(
                step1_request, user_profile, current_time, logger_obj, plan_mode=plan_mode_for_step1
            )

            # Step 2: 宏观规划 + Step 3: 微观规划
            # v20: Guard — force exploratory if any anchor needs area expansion (步行街逛逛 etc.)
            _has_expansion = any(
                getattr(fp, "expansion_required", False)
                for fp in (getattr(parsed_intent, "fixed_pois", []) or [])
            )
            _has_area_stroll = any(
                getattr(fp, "activity_facet", "") == "shopping_stroll"
                for fp in (getattr(parsed_intent, "fixed_pois", []) or [])
            )
            if _has_expansion:
                parsed_intent.plan_mode = "exploratory"

            # v21: Utility lookup fast path — restroom/toilet nearby search
            _is_utility = getattr(parsed_intent, 'utility_lookup_requested', False)
            if _is_utility and getattr(parsed_intent, 'category_id', '') == 'restroom':
                print(f"[DEBUG meituan_chat] 进入实用设施快速通道 (restroom)")
                await emit_status("正在搜索附近公共厕所...")
                micro_pois, route_segments, map_path, anchor_hints, waypoint_annotations, route_points, candidate_points, complete_plan = \
                    await _run_utility_nearby_fast(parsed_intent, user_profile, complete_plan, logger_obj)
                # Build route_data and emit complete directly (skip step3/step4 for utility)
                _city = (user_profile.permanent_city[0] if user_profile.permanent_city else "")
                route_data = {
                    "points": route_points,
                    "segments": route_segments,
                    "hints": {}, "waypoint_annotations": waypoint_annotations,
                    "route_id": "", "candidate_points": candidate_points,
                    "plan_mode": "utility", "total_days": 1,
                    "display_granularity": "short",
                }
                await push_output("[ROUTE_PLANNER]: 已完成附近公共厕所查询")
                await emit_done(
                    map_paths=[],
                    full_plan={"summary": f"附近公共厕所查询", "city": _city, "duration": ""},
                    route_data=route_data,
                )
                return
            else:
                # v6 planned fast path: 精准规划模式跳过 step2 宏观搜索，直接走 planned 专用短链路
                # v21: corridor_requested also forces planned fast path
                _pm = getattr(parsed_intent, 'plan_mode', 'exploratory')
                _pws = getattr(parsed_intent, 'planned_waypoints', [])
                _is_corr = getattr(parsed_intent, 'corridor_requested', False)
                is_planned_mode = (_pm == 'planned' or _is_corr) and bool(_pws)
                print(f"[DEBUG dispatch] plan_mode_check plan_mode={_pm} pws={len(_pws)} is_planned={is_planned_mode} corridor={_is_corr}")
                if is_planned_mode:
                    print(f"[DEBUG meituan_chat] 进入精准规划快速通道，跳过 Step2 宏观搜索")
                    await emit_status("正在为您精准规划路线...")
                    # 调用 planned 专用快速流水线
                    micro_pois, route_segments, map_file_path, anchor_hints, waypoint_annotations, route_points, candidate_points, complete_plan = \
                        await _run_planned_pipeline_fast(parsed_intent, user_profile, complete_plan, logger_obj)
                else:
                    # ── 自由探索模式：完整 step2 + step3 ──
                    await emit_status("正在查询天气...")
                    await emit_status("正在查询目的地信息...")
                    complete_plan = await run_step2(
                        parsed_intent, user_profile, logger_obj
                    )

                    await emit_status("正在搜索周边好去处...")
                    await emit_status("正在补充目的地详情...")
                    result = await run_step3(parsed_intent, complete_plan, logger_obj)
                    # step3 返回: (micro_pois, route_segments, map_path, hints, waypoint_annotations, points, candidate_points)
                    micro_pois, route_segments, map_file_path, anchor_hints, waypoint_annotations, route_points, candidate_points = result

            # v20: Generate per-POI recommendation reasons via DeepSeek (all plan modes)
            # v21: Skip for utility AND planned mode — planned has deterministic reasons
            _is_planned = getattr(parsed_intent, 'plan_mode', '') == 'planned'
            if route_points and not getattr(parsed_intent, 'utility_lookup_requested', False) and not _is_planned:
                try:
                    from services.reason_generator import generate_exploratory_reasons
                    _city = getattr(parsed_intent, "resolved_city", "") or \
                            (user_profile.permanent_city[0] if user_profile.permanent_city else "")
                    route_points = await asyncio.wait_for(
                        generate_exploratory_reasons(
                            route_points=route_points,
                            parsed_intent=parsed_intent,
                            user_profile=user_profile,
                            city=_city,
                            user_request=user_request,
                        ),
                        timeout=10.0,
                    )
                except Exception as _re:
                    print(f"[ReasonGen] generation failed (non-blocking): {_re}")

            # Step 4: 生成输出
            # 注意：run_step4 内部会发送 "正在生成行程方案..."、"路线规划完成！" 和 emit_done
            # 所以这里不需要重复发送这些消息
            await run_step4(
                parsed_intent, complete_plan, micro_pois, route_segments,
                map_file_path, logger_obj, anchor_hints, waypoint_annotations,
                route_points=route_points,  # 传递路线点用于前端验证
                candidate_points=candidate_points,  # v6: 传递候选 POI 点
            )

        except ZeroOutputError as exc:
            await emit_error(str(exc))
            await push_output(f"[ROUTE_PLANNER]: {str(exc)}")
        except Exception as exc:
            error_msg = f"路线规划暂时失败：{exc}"
            await emit_error(error_msg)
            await push_output(f"[ROUTE_PLANNER]: {error_msg}")
            logger.error(f"[MeituanChat] Pipeline 错误: {exc}", exc_info=True)

    # 启动收集器
    collector_task = asyncio.create_task(_collector())

    # 从队列中读取并 yield SSE 格式消息（带 heartbeat 和超时保护）
    stream_started_at = time.monotonic()

    try:
        while True:
            # 全局超时保护
            if time.monotonic() - stream_started_at > SSE_STREAM_MAX_SECONDS:
                timeout_data = json.dumps(
                    {"error": "路线规划响应超时，请稍后重试"},
                    ensure_ascii=False,
                )
                yield f"event: {SSE_EVENT_ERROR}\ndata: {timeout_data}\n\n"
                break

            try:
                msg = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                # 超时后检查收集器是否已完成
                if collector_task.done():
                    break
                # 发送 heartbeat 注释（SSE 前端/代理自动忽略）
                yield ": heartbeat\n\n"
                continue

            if msg is None:
                break

            if msg.startswith("event:"):
                yield msg

                # complete / done / error 都是终止事件
                # emit_done() 实际发送 event: complete，必须在此结束 SSE
                if (
                    msg.startswith("event: complete")
                    or msg.startswith("event: done")
                    or msg.startswith("event: error")
                ):
                    break
            else:
                output_lines.append(msg)
                data = json.dumps({"msg": msg}, ensure_ascii=False)
                yield f"event: {SSE_EVENT_RESULT}\ndata: {data}\n\n"

    except Exception as e:
        logger.error(f"[MeituanChat] 流式输出错误: {e}", exc_info=True)
        error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
        yield f"event: {SSE_EVENT_ERROR}\ndata: {error_data}\n\n"

    finally:
        if not collector_task.done():
            collector_task.cancel()
        await asyncio.gather(collector_task, return_exceptions=True)


async def _run_utility_nearby_fast(
    parsed_intent,
    user_profile,
    complete_plan,
    logger_obj,
) -> tuple[list, list, str, dict, dict, list, list, object]:
    """v21: Utility nearby fast path — restroom/toilet lookup.

    Skips tourist route planning entirely. Does progressive radius Amap around search.
    """
    from services.api_client import gaode_around_search_batch, gaode_walking_route
    from services.utils import coord_to_param, haversine_km, emit_status

    # Determine search center — priority: explicit_area > contextual_center > device > home
    _search_area_loc = getattr(parsed_intent, "search_area_location", None)
    _ctx_center = getattr(user_profile, "_contextual_search_center", None) or {}
    _device_loc = getattr(user_profile, "current_device_location", None)
    _home_loc = getattr(user_profile, "home_location", None)
    if _search_area_loc and _search_area_loc.get("lat"):
        _origin = _search_area_loc
        _loc_source = "explicit_search_area"
    elif _ctx_center.get("location", {}).get("lat"):
        _origin = _ctx_center["location"]
        _loc_source = f"contextual_search_center:{_ctx_center.get('label','')}"
    elif _device_loc and _device_loc.get("lat"):
        _origin = _device_loc
        _loc_source = "current_device"
    elif _home_loc and _home_loc.get("lat"):
        _origin = _home_loc
        _loc_source = "home_location"
    else:
        _origin = parsed_intent.original_location if parsed_intent.original_location else None
        _loc_source = "fallback"
    if not _origin or not _origin.get("lat"):
        raise ZeroOutputError("无法获取您的位置，请开启定位后重试。")
    print(f"[DEBUG utility] location_source={_loc_source} loc=({_origin.get('lat','')},{_origin.get('lng','')})")

    city = (user_profile.permanent_city[0] if user_profile.permanent_city else "")

    # Progressive radius search
    _radii = [300, 500, 1000, 2000]
    _restroom_kws = ["公共厕所", "公厕", "卫生间", "洗手间"]
    _allowed_tc = ["200300", "200301", "200302"]
    EXCLUDE_TERMS = ["施工", "暂停", "关闭", "内部", "员工", "住客", "小区", "办公"]

    found_raws = []
    for radius in _radii:
        if found_raws:
            break
        for kw in _restroom_kws:
            if len(found_raws) >= 5:
                break
            try:
                _req = {"location": coord_to_param(_origin), "keywords": kw,
                        "radius": radius, "offset": 20}
                _batch = await gaode_around_search_batch([_req])
                _raws = _batch[0] if _batch else []
                for r in _raws:
                    _name = str(r.get("name", ""))
                    _tc = str(r.get("typecode", "") or "")
                    if not any(_tc.startswith(tc) for tc in _allowed_tc):
                        continue
                    if any(t in _name for t in EXCLUDE_TERMS):
                        continue
                    # Dedupe by name
                    if _name in {str(fr.get("name","")) for fr in found_raws}:
                        continue
                    found_raws.append(r)
                print(f"[DEBUG utility] radius={radius}m kw={kw} raw={len(_raws)} tc_pass={len(found_raws)}")
            except Exception as exc:
                print(f"[WARN utility] search failed r={radius}m kw={kw}: {exc}")

    if not found_raws:
        raise ZeroOutputError(
            "附近2公里内暂未找到可核实为公开可用的卫生间。"
            "可以尝试前往最近的商场、公园游客中心或地铁站服务台询问。"
        )

    # Build route points
    route_points = []
    start_pt = {
        "poi_id": f"start:{_origin.get('lng')},{_origin.get('lat')}",
        "gaode_poi_id": "",
        "name": "当前位置" if _loc_source == "current_device" else (_origin.get("label", "出发地") or "出发地"),
        "location": {"lat": _origin["lat"], "lng": _origin["lng"]},
        "kind": "start", "day": 1, "typecode": "", "category": "",
        "address": "", "rating": None, "gaode_rating": None, "avg_cost": None,
        "photo_url": "", "photo_source": "", "parent_anchor": "", "sub_anchor_name": "",
        "recommend_reason": "", "is_waypoint": True, "is_passthrough": False,
        "walk_from_route_min": 0, "route_annotation": "",
        "route_order": 1, "display_order": 0, "display_slot": "short_trip",
        "is_display_poi": True, "display_label": "起点",
    }
    route_points.append(start_pt)

    candidate_points = []
    best = found_raws[0]
    best_loc_raw = best.get("location")
    best_loc = None
    if isinstance(best_loc_raw, str) and "," in best_loc_raw:
        p = best_loc_raw.split(",")
        best_loc = {"lat": float(p[1]), "lng": float(p[0])}
    elif isinstance(best_loc_raw, dict):
        best_loc = {"lat": float(best_loc_raw.get("lat", 0)), "lng": float(best_loc_raw.get("lng", 0))}

    _dist_km = haversine_km(_origin, best_loc) if best_loc else 0
    _walk_min = round(_dist_km * 15, 1)  # ~4km/h walking

    main_pt = {
        "poi_id": best.get("id", "") or best.get("uid", "") or str(best.get("name", "")),
        "gaode_poi_id": best.get("id", "") or best.get("uid", ""),
        "name": best.get("name", "公共厕所"),
        "location": best_loc or _origin,
        "kind": "utility", "day": 1,
        "typecode": best.get("typecode", "200300"),
        "category": "restroom",
        "address": best.get("address", ""),
        "rating": best.get("rating"),
        "gaode_rating": best.get("rating"),
        "avg_cost": None,
        "photo_url": "", "photo_source": "",
        "parent_anchor": "", "sub_anchor_name": "",
        "recommend_reason": f"步行约{_walk_min:.0f}分钟，公共卫生间",
        "is_waypoint": True, "is_passthrough": False,
        "walk_from_route_min": 0, "route_annotation": "",
        "route_order": 2, "display_order": 1, "display_slot": "short_trip",
        "is_display_poi": True, "display_label": "",
        "temporary_utility_route": True,
    }
    route_points.append(main_pt)

    # Candidates
    for i, r in enumerate(found_raws[1:5]):
        rl = r.get("location")
        rloc = None
        if isinstance(rl, str) and "," in rl:
            pp = rl.split(",")
            rloc = {"lat": float(pp[1]), "lng": float(pp[0])}
        elif isinstance(rl, dict):
            rloc = {"lat": float(rl.get("lat", 0)), "lng": float(rl.get("lng", 0))}
        candidate_points.append({
            "name": r.get("name", ""), "location": rloc,
            "kind": "candidate", "candidate_source": "utility_nearby",
            "poi_id": r.get("id", ""), "gaode_poi_id": r.get("id", ""),
            "typecode": r.get("typecode", ""), "category": "restroom",
            "address": r.get("address", ""), "rating": r.get("rating"),
            "day": 1, "theme_score": 0.0,
        })

    # Build walking route — non-blocking, use estimate on failure
    route_segments = []
    _walk = None
    try:
        _walk = await gaode_walking_route(coord_to_param(_origin), coord_to_param(best_loc))
    except Exception as _w_e:
        print(f"[WARN utility] walking route failed (using estimate): {_w_e}")
    try:
        route_segments.append({
            "from_poi": start_pt["name"], "to_poi": best.get("name", ""),
            "day_index": 1, "transport": "步行",
            "duration_min": (_walk or {}).get("duration_min", _walk_min),
            "distance_km": (_walk or {}).get("distance_km", _dist_km),
            "polyline": (_walk or {}).get("polyline", []),
            "period": "short_trip", "color": "#2980B9", "is_dashed": False,
            "segment_order": 1, "from_order": 1, "to_order": 2,
            "from_display_order": 0, "to_display_order": 1,
            "degraded": _walk is None, "polyline_source": "" if _walk else "route_api_failed",
            "route_error": "" if _walk else "real_route_unavailable",
            "transport_options": [],
        })
    except Exception as _seg_exc:
        print(f"[WARN utility] segment construction failed: {_seg_exc}")
        route_segments.append({
            "from_poi": start_pt["name"], "to_poi": best.get("name", ""),
            "day_index": 1, "transport": "步行",
            "duration_min": _walk_min, "distance_km": _dist_km,
            "polyline": [], "period": "short_trip", "color": "#2980B9", "is_dashed": False,
            "segment_order": 1, "from_order": 1, "to_order": 2,
            "from_display_order": 0, "to_display_order": 1,
            "degraded": True, "polyline_source": "route_api_failed", "route_error": "real_route_unavailable",
            "transport_options": [],
        })

    # Build minimal complete_plan
    if not complete_plan:
        from services.data_schema import CompletePlan, DayPlan
        complete_plan = CompletePlan(
            time_budget=0.0, fixed_budget=0.0, remaining_budget=0.0,
            day_plans=[DayPlan(day_index=1, anchors=[], meal_slots=[])],
            city=city, transport="步行",
        )

    print(f"[DEBUG utility] done: main={best.get('name','')} dist={_dist_km:.1f}km walk={_walk_min:.0f}min candidates={len(candidate_points)}")
    return [], route_segments, "", {}, {}, route_points, candidate_points, complete_plan


async def _run_incremental_refine(
    parsed_intent,
    user_profile,
    complete_plan,
    logger_obj,
    last_point: dict,
    user_request: str = "",
    route_context=None,
) -> tuple:
    """v21: Incremental refine — skip Step1+Step2, search around last route point only.
    Appends a new waypoint (meal/coffee/snack) near the last route endpoint.
    Time-bounded: max 25s total, 5s per API call.
    """
    from services.api_client import gaode_around_search_batch, gaode_walking_route
    from services.utils import coord_to_param, haversine_km
    import time as _time
    _start = _time.monotonic()

    _origin = last_point.get("location", {})
    _origin_name = last_point.get("name", "上一站")
    # v21: Normalize meal keywords + set explicit_meal_intent
    _task_kw = (getattr(parsed_intent, "primary_query", "") or
                " ".join(getattr(parsed_intent, "search_keywords", [])[:2]) or "餐厅")
    if "饭馆" in _task_kw:
        _task_kw = _task_kw.replace("饭馆", "餐厅")
    parsed_intent.explicit_meal_intent = True
    # v21: "适合拍照" → sorting preference only, not new theme
    parsed_intent.photo_preference = "适合拍照" in user_request if user_request else False
    if not _origin.get("lat"):
        _origin = getattr(parsed_intent, "original_location", None) or {}
    if not _origin.get("lat"):
        return [], [], "", {}, {}, [], [], complete_plan

    _radii = [500, 1000, 2000, 3000]
    _kws = getattr(parsed_intent, "search_keywords", []) or [_task_kw]
    _found_raw = None
    for _r in _radii:
        if _time.monotonic() - _start > 20:
            break
        if _found_raw:
            break
        for _kw in _kws[:3]:
            if _time.monotonic() - _start > 20 or _found_raw:
                break
            try:
                _req = {"location": coord_to_param(_origin), "keywords": _kw,
                        "radius": _r, "offset": 10}
                _batch = await gaode_around_search_batch([_req])
                for _raw in (_batch[0] if _batch else []):
                    _tc = str(_raw.get("typecode", "") or "")
                    if _tc.startswith("05"):  # restaurant/food
                        _found_raw = _raw
                        break
            except Exception as _exc:
                print(f"[IncrementalRefine] search r={_r}m kw={_kw}: {_exc}")

    if not _found_raw:
        await emit_error("当前路线已保留，但附近小吃/餐厅检索暂时超时，请稍后重试")
        return [], [], "", {}, {}, [], [], complete_plan

    _name = str(_found_raw.get("name", "餐厅"))
    _loc_raw = _found_raw.get("location")
    _loc = {}
    if isinstance(_loc_raw, str) and "," in _loc_raw:
        _p = _loc_raw.split(",")
        _loc = {"lat": float(_p[1]), "lng": float(_p[0])}
    elif isinstance(_loc_raw, dict):
        _loc = {"lat": float(_loc_raw.get("lat", 0)), "lng": float(_loc_raw.get("lng", 0))}
    _elapsed = (_time.monotonic() - _start) * 1000

    # Build route points: preserve existing + append new
    _existing_points = route_context.points if route_context else []
    route_points = list(_existing_points)
    _new_order = max((p.get("display_order") or 0 for p in route_points), default=0) + 1
    _new_pt = {
        "poi_id": _found_raw.get("id", "") or _found_raw.get("uid", ""),
        "gaode_poi_id": _found_raw.get("id", "") or _found_raw.get("uid", ""),
        "name": _name,
        "location": _loc,
        "kind": "meal",
        "day": 1,
        "typecode": _found_raw.get("typecode", ""),
        "category": "meal",
        "address": _found_raw.get("address", ""),
        "rating": _found_raw.get("rating"),
        "is_waypoint": True,
        "is_display_poi": True,
        "display_order": _new_order,
        "display_slot": "",
        "is_passthrough": False,
        "photo_url": "",
    }
    route_points.append(_new_pt)

    # Build segment: origin → new POI
    route_segments = route_context.segments if route_context else []
    try:
        _walk = None
        try:
            _walk = await gaode_walking_route(coord_to_param(_origin), coord_to_param(_loc))
        except Exception as _w_exc:
            print(f"[WARN] walking route failed (using estimate): {_w_exc}")
        _dist_est = haversine_km(_origin, _loc) if _origin and _loc else 1.0
        _dur_est = round(_dist_est * 15, 1)  # ~4 km/h walking
        _seg = {
            "from_poi": _origin_name, "to_poi": _name,
            "day_index": 1, "transport": "步行",
            "duration_min": _walk.get("duration_min", 5),
            "distance_km": _walk.get("distance_km", 0.5),
            "polyline": _walk.get("polyline", []),
            "degraded": False, "segment_order": len(route_segments) + 1,
            "is_dashed": False, "period": "",
        }
        route_segments.append(_seg)
    except Exception:
        pass

    print(
        f"[IncrementalRefineDone] "
        f"selected_poi={_name} "
        f"elapsed_ms={_elapsed:.0f} "
        f"terminal_event=complete"
    )
    return [], route_segments, "", {}, {}, route_points, [], complete_plan


async def _run_planned_pipeline_fast(
    parsed_intent,
    user_profile,
    complete_plan,
    logger_obj,
) -> tuple[list, list, str, dict, dict, list, list, object]:
    """v6: 精准规划快速流水线 — 跳过 step2 宏观搜索，直接基于 planned_waypoints 构建路线

    短链路：
    1. 递进解析 planned_waypoints（带候选 POI）
    2. 构建 route_points（主 POI，带完整 info）
    3. 构建 candidate_points（备选 POI）
    4. _build_segments 生成路线段
    5. 返回标准 8 元组（含 complete_plan）

    Returns:
        (micro_pois, route_segments, map_path, anchor_hints, waypoint_annotations, route_points, candidate_points, complete_plan)
    """
    from services.step3_planned import (
        resolve_planned_waypoints,
        resolve_planned_waypoints_with_candidates,
        build_planned_route_points_rich,
        build_planned_candidate_points,
    )
    from services.step3_micro import _build_segments
    from services.step3_planned import estimate_planned_duration_min
    from services.api_client import gaode_walking_route

    waypoints = getattr(parsed_intent, 'planned_waypoints', [])
    if not waypoints:
        raise ZeroOutputError("精准规划模式下未能解析到途经点")

    city = (user_profile.permanent_city[0] if (user_profile.permanent_city and user_profile.permanent_city[0]) else "")
    raw_start_location = getattr(parsed_intent, 'original_location', None) or {}
    # v18: 统一使用 home_location 作为路线出发地
    home_loc_fb = getattr(user_profile, 'home_location', None) or {}
    fb_lat = raw_start_location.get('lat') or home_loc_fb.get('lat') or 31.2809
    fb_lng = raw_start_location.get('lng') or home_loc_fb.get('lng') or 121.5011
    fb_label = raw_start_location.get('label') or home_loc_fb.get('label') or '同济大学四平路校区'

    start_lng = raw_start_location.get('lng') or fb_lng
    start_lat = raw_start_location.get('lat') or fb_lat
    start_name = "起点·" + (raw_start_location.get('label') or fb_label)

    start_location = {
        'lng': float(start_lng),
        'lat': float(start_lat),
        'label': start_name,
    }

    # v6: 获取真实 home_location
    home_loc = getattr(user_profile, 'home_location', None) or {}
    if not home_loc or (not home_loc.get('lat') and not home_loc.get('lng')):
        print("[WARNING planned_fast] home_location 未在 user_profile 中配置")

    # 1. 递进解析 waypoints（带候选 POI）
    await emit_status("正在搜索您的目标地点...")
    planned_budget_threshold = (
        parsed_intent.budget_per_capita
        if getattr(parsed_intent, 'budget_per_capita', None) is not None
        else getattr(user_profile, 'budget_per_capita', 100.0) * 1.5
    )
    # v20: Pass search area context for planned waypoint resolution
    _search_area_loc = getattr(parsed_intent, "search_area_location", None)
    _search_area_label = getattr(parsed_intent, "search_area_label", "") or ""

    _is_corridor = bool(getattr(parsed_intent, "corridor_requested", False))
    if _is_corridor:
        # v21: Corridor task — resolve destination first, then corridor search
        import re as _re
        from services.api_client import gaode_text_search, gaode_driving_route
        from services.utils import coord_to_param
        _dest_wp = None
        _task_wp = None
        for wp in waypoints:
            if getattr(wp, "role", "") == "destination" or wp.category == "destination":
                _dest_wp = wp
            elif getattr(wp, "corridor_search", False) or getattr(wp, "placement", "") == "before_destination":
                _task_wp = wp
        if not _dest_wp or not _task_wp:
            _dest_wp = waypoints[-1] if len(waypoints) >= 2 else waypoints[0]
            _task_wp = waypoints[0] if len(waypoints) >= 2 else None

        # Resolve destination
        _dest_name = getattr(_dest_wp, "name", "") or getattr(_dest_wp, "search_keyword", "") or ""
        _dest_loc = None
        try:
            _dest_pois = await gaode_text_search(_dest_name, city=city)
            if _dest_pois:
                _best = _dest_pois[0]
                _raw_loc = _best.get("location")
                if isinstance(_raw_loc, str) and "," in _raw_loc:
                    _p = _raw_loc.split(",")
                    _dest_loc = {"lat": float(_p[1]), "lng": float(_p[0]), "label": _best.get("name", _dest_name)}
                elif isinstance(_raw_loc, dict):
                    _dest_loc = {"lat": float(_raw_loc.get("lat", 0)), "lng": float(_raw_loc.get("lng", 0)), "label": _best.get("name", _dest_name)}
            if _dest_loc and _dest_loc.get("lat"):
                _dest_wp.resolved_location = _dest_loc
                _dest_wp.resolved_name = _dest_loc.get("label", _dest_name)
                print(f"[DEBUG corridor] destination resolved: {_dest_name} → {_dest_wp.resolved_name} loc=({_dest_loc['lat']},{_dest_loc['lng']})")
        except Exception as exc:
            print(f"[WARN corridor] destination resolution failed for '{_dest_name}': {exc}")

        # Resolve corridor task via around-search near the route polyline
        _task_kw = getattr(_task_wp, "search_keyword", "") or ""
        _task_cat = getattr(_task_wp, "category", "") or ""
        _task_req_terms = getattr(_task_wp, "required_terms", []) or []
        _task_excl_terms = getattr(_task_wp, "excluded_terms", []) or []
        _is_meal_task = (_task_cat == "meal")
        _task_loc = None
        _task_name = ""
        if _dest_loc and _task_kw:
            try:
                # Get base route to find corridor search points
                _base_route = await gaode_driving_route(
                    coord_to_param(start_location), coord_to_param(_dest_loc)
                )
                _steps = _base_route.get("steps", []) or []
                _mid_idx = len(_steps) // 2 if _steps else 0
                _mid_pt = _steps[_mid_idx].get("location", start_location) if _steps else start_location
                _search_pts = [_steps[len(_steps)//3].get("location", start_location) if len(_steps) >= 3 else start_location,
                              _mid_pt,
                              _steps[2*len(_steps)//3].get("location", _dest_loc) if len(_steps) >= 3 else _dest_loc]
                _corridor_widths = [300, 600, 1000]
                # v21: Additional widths + destination-area fallback for meal tasks
                if _is_meal_task:
                    _corridor_widths = [300, 600, 1000, 1500]
                _found_task = None
                for _width in _corridor_widths:
                    if _found_task:
                        break
                    for _pt in _search_pts:
                        if _found_task:
                            break
                        try:
                            _req = {"location": coord_to_param(_pt), "keywords": _task_kw,
                                    "radius": _width, "show_fields": "business,photos", "offset": 15}
                            _batch = await gaode_around_search_batch([_req])
                            _raws = _batch[0] if _batch else []
                            for _r in _raws:
                                _name = str(_r.get("name", ""))
                                _tc = str(_r.get("typecode", "") or "")
                                if _task_excl_terms and any(t in _name for t in _task_excl_terms):
                                    continue
                                if _task_req_terms and not any(t in _name for t in _task_req_terms):
                                    continue
                                # v21: For meal tasks, only accept 05xxxx (food), not 06xxxx (retail)
                                if _is_meal_task:
                                    if not _tc.startswith("05"):
                                        continue
                                else:
                                    if not (_tc.startswith("06") or _tc.startswith("05")):
                                        continue
                                _rl = _r.get("location")
                                if isinstance(_rl, str) and "," in _rl:
                                    _pp = _rl.split(",")
                                    _task_loc = {"lat": float(_pp[1]), "lng": float(_pp[0])}
                                elif isinstance(_rl, dict):
                                    _task_loc = {"lat": float(_rl.get("lat", 0)), "lng": float(_rl.get("lng", 0))}
                                _task_name = _name
                                _found_task = _r
                                break
                        except Exception as exc:
                            print(f"[WARN corridor] task search failed w={_width}m: {exc}")
                # v21: Destination-area fallback for meal tasks (1500m around dest)
                if not _found_task and _is_meal_task:
                    try:
                        _req = {"location": coord_to_param(_dest_loc), "keywords": _task_kw,
                                "radius": 1500, "show_fields": "business,photos", "offset": 15}
                        _batch = await gaode_around_search_batch([_req])
                        for _r in (_batch[0] if _batch else []):
                            _name = str(_r.get("name", ""))
                            _tc = str(_r.get("typecode", "") or "")
                            if _task_excl_terms and any(t in _name for t in _task_excl_terms):
                                continue
                            if not _tc.startswith("05"):
                                continue
                            _rl = _r.get("location")
                            if isinstance(_rl, str) and "," in _rl:
                                _pp = _rl.split(",")
                                _task_loc = {"lat": float(_pp[1]), "lng": float(_pp[0])}
                            elif isinstance(_rl, dict):
                                _task_loc = {"lat": float(_rl.get("lat", 0)), "lng": float(_rl.get("lng", 0))}
                            _task_name = _name
                            _found_task = _r
                            break
                    except Exception as exc:
                        print(f"[WARN corridor] dest-area meal fallback failed: {exc}")
                if _task_loc and _task_loc.get("lat"):
                    _task_wp.resolved_location = _task_loc
                    _task_wp.resolved_name = _task_name
                    _task_wp.resolved_poi = _found_task
                    print(f"[DEBUG corridor] task resolved: {_task_kw} → {_task_name} loc=({_task_loc['lat']},{_task_loc['lng']})")
            except Exception as exc:
                print(f"[WARN corridor] route/task resolution failed: {exc}")

        # Build resolved waypoints list
        resolved_wps = []
        candidate_map = {}
        for wp in waypoints:
            if getattr(wp, "resolved_location", None):
                resolved_wps.append(wp)
            elif getattr(wp, "type", "") == "placeholder" and (_is_meal_task or getattr(wp, "corridor_search", False)):
                # v21: Don't silently drop required corridor placeholder — error out
                print(f"[WARN corridor] REQUIRED placeholder '{getattr(wp, 'search_keyword', wp.name or '')}' NOT resolved!")
    else:
        resolved_wps, candidate_map = await resolve_planned_waypoints_with_candidates(
            waypoints,
            start_location,
            city,
            home_location=home_loc if home_loc.get('lat') else None,
            budget_threshold=planned_budget_threshold,
            search_area_location=_search_area_loc,
            search_area_label=_search_area_label,
        )
    resolved_count = sum(1 for wp in resolved_wps if wp.resolved_location)
    print(f"[DEBUG planned_fast] budget_threshold={planned_budget_threshold} request_budget={getattr(parsed_intent, 'budget_per_capita', None)}")
    print(f"[DEBUG planned_fast] resolved_wps={[(wp.resolved_name or wp.search_keyword, wp.category) for wp in resolved_wps]} num_candidates={sum(len(v) for v in candidate_map.values())}")

    if resolved_count == 0:
        _primary_q = getattr(parsed_intent, "primary_query", "") or ""
        _search_lbl = _search_area_label or "指定区域"
        _kw_list = [wp.search_keyword for wp in waypoints if wp.search_keyword]
        print(
            f"[DEBUG planned_zero_result] "
            f"search_area={_search_lbl} "
            f"primary_query={_primary_q} "
            f"keywords={_kw_list} "
            f"waypoint_count={len(waypoints)} "
        )
        raise ZeroOutputError(
            f"未在{_search_lbl}找到符合条件的{'、'.join(_kw_list[:3])}，"
            f"请修改区域或目标类型后重试。"
        )

    # 2. 判断时间标签
    current_time = getattr(parsed_intent, 'start_time', None)
    meal_label = _infer_meal_label_from_time(current_time) if current_time else ""

    # 3. 构建 route_points（主 POI，带完整 info）
    route_points = build_planned_route_points_rich(
        resolved_wps, start_location, start_name, day_index=1, meal_label=meal_label
    )

    # 4. 构建 candidate_points
    all_candidate_points = build_planned_candidate_points(
        candidate_map, resolved_wps, start_location
    )

    # 5. 构建 complete_plan（轻量，用于 step4）
    from services.data_schema import CompletePlan, DayPlan
    if not hasattr(complete_plan, 'day_plans') or not complete_plan:
        fallback_budget_threshold = (
            parsed_intent.budget_per_capita
            if getattr(parsed_intent, 'budget_per_capita', None) is not None
            else getattr(user_profile, 'budget_per_capita', 100.0) * 1.5
        )
        complete_plan = CompletePlan(
            time_budget=0.5,
            fixed_budget=0.0,
            remaining_budget=0.5,
            day_plans=[],
            city=city,
            transport=getattr(parsed_intent, 'transport_hint', '公共交通') or '公共交通',
            budget_threshold=fallback_budget_threshold,
            request_budget_per_capita=getattr(parsed_intent, 'budget_per_capita', None),
        )
    if not complete_plan.day_plans:
        complete_plan.day_plans = [DayPlan(day_index=1, anchors=[], meal_slots=[])]

    # 6. 生成 route_segments
    await emit_status("正在规划路线...")
    route_segments, waypoint_annotations = await _build_segments(
        parsed_intent, getattr(parsed_intent, 'transport_hint', '公共交通') or '公共交通', route_points
    )
    print(f"[DEBUG planned_fast] segments_count={len(route_segments)}")

    # 7. 地图渲染（简化：返回空字符串）
    map_file_path = ""

    # 8. 锚点提示（planned 模式无锚点）
    anchor_hints = {}

    # 9. 标记 route_points 的 plan_mode
    for pt in route_points:
        pt['plan_mode'] = 'planned'

    return [], route_segments, map_file_path, anchor_hints, waypoint_annotations, route_points, all_candidate_points, complete_plan


def _infer_meal_label_from_time(current_time) -> str:
    """根据当前时间推断餐饮标签"""
    if not current_time:
        return ""
    hour = current_time.hour + current_time.minute / 60.0
    if 5.0 <= hour < 10.5:
        return "breakfast"
    elif 10.5 <= hour < 14.0:
        return "lunch"
    elif 14.0 <= hour < 16.5:
        return "afternoon_tea"
    elif 16.5 <= hour < 21.5:
        return "dinner"
    elif 21.5 <= hour or hour < 2.0:
        return "night_snack"
    else:
        return "dinner"


@router.post("/chat/stream")
async def meituan_chat_stream(req: ChatRequest):
    """
    流式聊天接口
    使用 SSE 实时推送规划进度
    
    SSE 事件类型：
    - status: 进度消息（如"正在加载用户信息..."）
    - result: 最终结果（包含路线数据）
    - done: 完成标记
    - error: 错误消息
    """
    # 处理欢迎语请求
    if not req.message or req.message.strip() in ("", "__init__", "__welcome__"):
        welcome_text = (
            "[ROUTE_PLANNER]: 欢迎使用路线规划系统！\n"
            "[ROUTE_PLANNER]: 请描述您的出行需求，我会自动为您规划路线。\n"
            "[ROUTE_PLANNER]: 例如：周末想去外滩附近逛逛 / 下班后顺路买点水果再回家"
        )
        
        async def welcome_stream():
            # 模拟流式输出，逐行发送 status 事件
            lines = welcome_text.split('\n')
            for line in lines:
                data = json.dumps({"msg": line}, ensure_ascii=False)
                yield f"event: {SSE_EVENT_STATUS}\ndata: {data}\n\n"
                await asyncio.sleep(0.1)  # 模拟打字效果
            
            # 发送完成消息
            done_data = json.dumps({"reply": welcome_text}, ensure_ascii=False)
            yield f"event: {SSE_EVENT_DONE}\ndata: {done_data}\n\n"
        
        return StreamingResponse(
            welcome_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    
    # 原有 pipeline 逻辑
    return StreamingResponse(
        _run_pipeline_stream(
            req.message, req.user_id, req.plan_mode,
            req.guest_profile, req.client_sent_at, req.client_timezone,
            req.route_context,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "service": "meituan-chat",
    }
