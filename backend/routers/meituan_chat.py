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
import sys
import os

logger = logging.getLogger(__name__)

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


class ChatRequest(BaseModel):
    message: str
    user_id: str = "default"
    plan_mode: str = "exploratory"  # exploratory 或 planned
    guest_profile: GuestProfileSchema | None = None
    client_sent_at: str | None = None
    client_timezone: str | None = None


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


async def _run_pipeline_stream(
    user_request: str,
    user_id: str,
    plan_mode: str,
    guest_profile: GuestProfileSchema | None = None,
    client_sent_at: str | None = None,
    client_timezone: str | None = None,
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

    # 先初始化 SSE 队列
    queue = asyncio.Queue()
    init_sse_queue(queue)

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

            # Step 1: 意图识别
            await emit_status("正在解析您的出行意图...")
            # [DEBUG-跨时段] 打印实际收到的 user_request
            print(f"[DEBUG meituan_chat] received user_request={user_request[:120]}")
            parsed_intent = await run_step1(
                user_request, user_profile, current_time, logger_obj, plan_mode=plan_mode
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

    # 从队列中读取并 yield SSE 格式消息
    while True:
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=120)
            
            # 检查是否是结束标记
            if msg is None:
                break
            
            # 检查是否已经是 SSE 格式（以 "event:" 开头）
            if msg.startswith("event:"):
                # 已经是 SSE 格式，直接 yield
                yield msg
                
                # 如果是 done 事件，结束循环
                if msg.startswith("event: done"):
                    break
            else:
                # 旧格式，转换为 SSE result 事件
                output_lines.append(msg)
                data = json.dumps({"msg": msg}, ensure_ascii=False)
                yield f"event: {SSE_EVENT_RESULT}\ndata: {data}\n\n"
            
        except asyncio.TimeoutError:
            timeout_msg = "[ROUTE_PLANNER]: 响应超时，API 可能无响应，已输出部分结果"
            output_lines.append(timeout_msg)
            data = json.dumps({"msg": timeout_msg}, ensure_ascii=False)
            yield f"event: {SSE_EVENT_RESULT}\ndata: {data}\n\n"
            break
        except Exception as e:
            logger.error(f"[MeituanChat] 流式输出错误: {e}", exc_info=True)
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"event: {SSE_EVENT_ERROR}\ndata: {error_data}\n\n"
            break

    # 等待收集器完成
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
    home_loc_fb = getattr(user_profile, 'home_location', None) or {}
    device_loc_fb = getattr(user_profile, 'current_device_location', None) or {}
    fb_lat = device_loc_fb.get('lat') or home_loc_fb.get('lat') or 31.2809
    fb_lng = device_loc_fb.get('lng') or home_loc_fb.get('lng') or 121.5011
    fb_label = device_loc_fb.get('label') or home_loc_fb.get('label') or '当前设备位置'

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
    resolved_wps, candidate_map = await resolve_planned_waypoints_with_candidates(
        waypoints, start_location, city, home_location=home_loc if home_loc.get('lat') else None
    )
    resolved_count = sum(1 for wp in resolved_wps if wp.resolved_location)
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
        complete_plan = CompletePlan(
            time_budget=0.5,
            fixed_budget=0.0,
            remaining_budget=0.5,
            day_plans=[],
            city=city,
            transport=getattr(parsed_intent, 'transport_hint', '公共交通') or '公共交通',
            budget_threshold=getattr(user_profile, 'budget_per_capita', 100.0) * 1.5,
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
            "[ROUTE_PLANNER]: 请选择规划模式：\n"
            "[ROUTE_PLANNER]:   1 - 自由探索（系统推荐路线）\n"
            "[ROUTE_PLANNER]:   2 - 连续决策（指定途经点，逐步规划）\n"
            "[ROUTE_PLANNER]: 请输入模式编号（默认1）："
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
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    
    # 原有 pipeline 逻辑
    return StreamingResponse(
        _run_pipeline_stream(req.message, req.user_id, req.plan_mode, req.guest_profile, req.client_sent_at, req.client_timezone),
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
