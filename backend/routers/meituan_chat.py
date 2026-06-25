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
from services.api_client import gaode_text_search
from services.pipeline_replan_service import apply_pipeline_replan
from services.conversation_replan import (
    classify_conversation_route_change,
    classify_conversation_route_change_fast,
    classify_planning_dispatch,
    _detect_plan_mode_from_text,
    _planning_dispatch_fast_fallback,
    PlanningDispatchDecision,
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

    return {"action": "normal", "target_name": None, "new_name": None, "reason": "no edit rule matched"}


async def _resolve_poi_for_chat_edit(name: str, city: str = "上海") -> dict | None:
    items = await gaode_text_search(name, city=city, show_fields="business,photos")
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


async def _try_chat_edit_replan(
    user_request: str,
    route_context: RouteContextSchema | None,
    user_profile,
) -> bool:
    edit = _classify_chat_edit(user_request, route_context)
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
        new_poi = await _resolve_poi_for_chat_edit(edit["new_name"], city=city)
        if not new_poi:
            return False
        operations.append({"action": "add", "poi_id": new_poi.get("poi_id") or new_poi["name"], "poi": new_poi})

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
    await emit_done(
        map_paths=[],
        full_plan={
            "summary": summary,
            "city": "上海",
            "duration": "",
            "time_budget": 0,
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
            }
            dispatch_decision = None
            plan_mode_for_step1 = "auto"
            step1_request = user_request  # v18: 默认原样传入，refine_current 分支可覆写
            if route_context and route_context.points:
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
                    edited = await _try_chat_edit_replan(user_request, route_context, user_profile)
                    if edited:
                        return
                elif dispatch_decision.conversation_mode == "refine_current":
                    print(f"[DEBUG dispatch] decision: refine_current → enriching request with old context")
                    effective_request = user_request
                    if dispatch_decision.include_constraints:
                        parts = [user_request]
                        for k, v in dispatch_decision.include_constraints.items():
                            if v and str(v).strip():
                                parts.append(f"保持{k}={v}")
                        if dispatch_decision.intent_patch:
                            patch_str = json.dumps(dispatch_decision.intent_patch, ensure_ascii=False)
                            parts.append(f"其他不变，按以下参数调整：{patch_str}")
                        effective_request = "；".join(parts)
                    step1_request = effective_request
                    print(f"[DEBUG dispatch] refined effective_request={effective_request[:120]}")
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
            # v6 planned fast path: 精准规划模式跳过 step2 宏观搜索，直接走 planned 专用短链路
            is_planned_mode = (
                getattr(parsed_intent, 'plan_mode', 'exploratory') == 'planned'
                and getattr(parsed_intent, 'planned_waypoints', [])
            )
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
    resolved_wps, candidate_map = await resolve_planned_waypoints_with_candidates(
        waypoints,
        start_location,
        city,
        home_location=home_loc if home_loc.get('lat') else None,
        budget_threshold=planned_budget_threshold,
    )
    resolved_count = sum(1 for wp in resolved_wps if wp.resolved_location)
    print(f"[DEBUG planned_fast] budget_threshold={planned_budget_threshold} request_budget={getattr(parsed_intent, 'budget_per_capita', None)}")
    print(f"[DEBUG planned_fast] resolved_wps={[(wp.resolved_name or wp.search_keyword, wp.category) for wp in resolved_wps]} num_candidates={sum(len(v) for v in candidate_map.values())}")

    if resolved_count == 0:
        raise ZeroOutputError("未能找到任何途经点，请检查您的需求描述或扩大搜索范围")

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
