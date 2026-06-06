"""
意图处理器模块
实现各种意图的具体处理逻辑

每个处理器必须返回 PipelineResponse，确保响应非空
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from services.intent_pipeline import (
    IntentResult, 
    PipelineResponse, 
    ResponseStatus,
    IntentType,
    FALLBACK_TEMPLATES
)
from services.route_planner import RoutePlanner
from services.gaode_service import GaodeService
from services.dianping_service import DianpingService
from services.route_dto import (
    convert_to_frontend_route, 
    build_points_from_segments,
    build_gaode_route_json,
)

logger = logging.getLogger(__name__)

# 服务实例
route_planner = RoutePlanner()
gaode_service = GaodeService()
dianping_service = DianpingService()


async def handle_travel_planning(
    trace_id: str,
    user_input: str,
    intent_result: IntentResult,
    context: dict
) -> PipelineResponse:
    """
    处理旅行规划意图 - 集成完整路线规划流程
    
    示例输入："规划北京3日游"
    """
    logger.info(f"[TravelPlanning] 开始处理: trace_id={trace_id}")
    
    entities = intent_result.entities
    destination = entities.get("destination", "上海")
    days = entities.get("days", 3)
    themes = entities.get("themes", [])
    budget = entities.get("budget_level", "中等")
    
    try:
        # ========== 调用完整的路线规划流水线 ==========
        from services.step1_intent import run_step1
        from services.step2_macro import run_step2
        from services.step3_micro import run_step3
        from services.step4_output import run_step4
        from services.utils import PipelineLogger, emit_status, push_output, emit_done
        
        # 创建 PipelineLogger 用于捕获输出
        logger_instance = PipelineLogger()
        
        # Step 1: 意图解析
        await emit_status("正在解析您的旅行需求...")
        parsed_intent = await run_step1(
            user_input=user_input,
            area=destination,
            days=days,
            themes=themes,
            budget=budget,
        )
        
        # Step 2: 宏观规划（锚点选择）
        await emit_status("正在规划行程框架...")
        complete_plan = await run_step2(parsed_intent, logger_instance)
        
        # Step 3: 微观规划（详细路线）- 返回结构化数据
        await emit_status("正在生成详细路线...")
        micro_pois, route_segments, map_path, hints, waypoint_annotations = await run_step3(
            parsed_intent, complete_plan, logger_instance
        )
        
        # 收集地图文件路径
        map_paths = []
        if map_path:
            # map_path 格式: "Day1: ./services/maps/route_xxx_day1.html; Day2: ..."
            for part in map_path.split(";"):
                part = part.strip()
                if ":" in part:
                    path = part.split(":", 1)[1].strip()
                    map_paths.append(path)
        
        # 从 route_segments 构建 points（用于前端显示）
        points = build_points_from_segments(route_segments, waypoint_annotations)
        
        # Step 4: 生成文本输出
        await emit_status("正在生成行程方案...")
        
        # 收集文本输出
        text_parts = []
        
        # 生成摘要
        from services.step4_output import _all_anchors, _origin_label, _duration_desc
        anchors = _all_anchors(complete_plan)
        first_anchor = anchors[0].name if anchors else "出发点"
        last_anchor = anchors[-1].name if anchors else first_anchor
        origin = _origin_label(parsed_intent)
        meal_suffix = "，含餐饮推荐" if any(item.is_meal for item in micro_pois) else ""
        
        if first_anchor == last_anchor:
            summary = f"为您规划了{_duration_desc(parsed_intent)}的{complete_plan.city}之旅，从{origin}出发，以{first_anchor}为核心{meal_suffix}。"
        else:
            summary = f"为您规划了{_duration_desc(parsed_intent)}的{complete_plan.city}之旅，从{origin}出发，串联{first_anchor}到{last_anchor}{meal_suffix}。"
        
        text_parts.append(summary)
        
        # 生成每日详情
        from services.step4_output import _day_detail, _segment_lookup
        for day in complete_plan.day_plans:
            day_detail = _day_detail(day, parsed_intent, micro_pois, route_segments, hints, waypoint_annotations)
            text_parts.append(day_detail)
        
        # 添加推荐理由
        for anchor in anchors:
            text_parts.append(f"· {anchor.name}：{anchor.recommend_reason}")
        
        # 添加地图路径
        if map_path:
            text_parts.append(f"完整路线地图已按天生成，点击查看：{map_path}")
        
        text_summary = "\n".join(text_parts)
        
        # ========== 转换为前端可用的结构化数据 ==========
        # 旧版 DTO（兼容）
        route_response = convert_to_frontend_route(
            points=points,
            route_segments=route_segments,
            hints=hints,
            waypoint_annotations=waypoint_annotations,
            text_summary=text_summary,
            map_paths=map_paths,
        )
        
        # 新版高德地图 JSON 格式
        gaode_route = build_gaode_route_json(
            points=points,
            route_segments=route_segments,
            hints=hints,
            waypoint_annotations=waypoint_annotations,
            text_summary=text_summary,
            map_paths=map_paths,
            complete_plan=complete_plan,
        )
        
        # 构建响应内容（简化版文本）
        content = f"🎉 已为您规划好{destination}{days}日游路线！\n\n"
        content += f"📍 目的地：{destination}\n"
        content += f"📅 天数：{days}天\n"
        
        if themes:
            content += f"🏷️ 主题：{'、'.join(themes)}\n"
        
        content += f"\n{text_summary}\n\n"
        content += "点击「查看详细路线」可查看完整安排，或继续讨论调整 😊"
        
        # 构建完整响应数据
        response_data = {
            "text": text_summary,
            "route": route_response.route.dict() if route_response.route else None,
            "gaode_route": gaode_route.dict(),  # 高德地图 JSON 数据
            "has_route": route_response.has_route,
            "total_days": route_response.total_days,
            "map_paths": route_response.map_paths,
        }
        
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.SUCCESS,
            content=content,
            data=response_data,
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=intent_result.confidence
        )
        
    except Exception as e:
        logger.error(f"[TravelPlanning] 处理失败: {e}", exc_info=True)
        
        # 返回失败响应（兜底模板会在流水线中填充）
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.FAILED,
            content="",  # 空内容会触发兜底模板
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=intent_result.confidence,
            error_message=str(e)
        )


async def handle_route_generation(
    trace_id: str,
    user_input: str,
    intent_result: IntentResult,
    context: dict
) -> PipelineResponse:
    """
    处理路线生成意图
    
    示例输入："生成上海到杭州的路线"
    """
    logger.info(f"[RouteGeneration] 开始处理: trace_id={trace_id}")
    
    entities = intent_result.entities
    origin = entities.get("origin", "")
    destination = entities.get("destination", "")
    
    try:
        # 调用高德地图服务获取路线
        if origin and destination:
            route_data = await gaode_service.get_route(origin, destination)
        else:
            route_data = {"summary": "路线信息", "distance": "未知", "duration": "未知"}
        
        content = f"🗺️ 路线生成成功！\n\n"
        
        if origin and destination:
            content += f"📍 从 {origin} 到 {destination}\n"
            content += f"🚗 距离：{route_data.get('distance', '未知')}\n"
            content += f"⏱️ 预计时间：{route_data.get('duration', '未知')}\n\n"
        
        content += f"{route_data.get('summary', '')}"
        
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.SUCCESS,
            content=content,
            data=route_data,
            intent_type=IntentType.ROUTE_GENERATION,
            confidence=intent_result.confidence
        )
        
    except Exception as e:
        logger.error(f"[RouteGeneration] 处理失败: {e}", exc_info=True)
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.FAILED,
            content="",
            intent_type=IntentType.ROUTE_GENERATION,
            confidence=intent_result.confidence,
            error_message=str(e)
        )


async def handle_poi_query(
    trace_id: str,
    user_input: str,
    intent_result: IntentResult,
    context: dict
) -> PipelineResponse:
    """
    处理地点查询意图
    
    示例输入："上海迪士尼门票多少钱"
    """
    logger.info(f"[POIQuery] 开始处理: trace_id={trace_id}")
    
    entities = intent_result.entities
    poi_name = entities.get("poi_name", "")
    location = entities.get("location", "上海")
    
    try:
        # 调用大众点评服务查询POI信息
        if poi_name:
            poi_info = await dianping_service.search_poi(poi_name, location)
        else:
            poi_info = {"name": "未知地点", "summary": "未找到相关信息"}
        
        content = f"📍 {poi_info.get('name', poi_name)}\n\n"
        
        if poi_info.get('rating'):
            content += f"⭐ 评分：{poi_info['rating']}\n"
        if poi_info.get('price'):
            content += f"💰 人均：{poi_info['price']}\n"
        if poi_info.get('address'):
            content += f"📍 地址：{poi_info['address']}\n"
        if poi_info.get('open_time'):
            content += f"🕐 开放时间：{poi_info['open_time']}\n"
        
        content += f"\n{poi_info.get('summary', '')}"
        
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.SUCCESS,
            content=content,
            data=poi_info,
            intent_type=IntentType.POI_QUERY,
            confidence=intent_result.confidence
        )
        
    except Exception as e:
        logger.error(f"[POIQuery] 处理失败: {e}", exc_info=True)
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.FAILED,
            content="",
            intent_type=IntentType.POI_QUERY,
            confidence=intent_result.confidence,
            error_message=str(e)
        )


async def handle_weather_query(
    trace_id: str,
    user_input: str,
    intent_result: IntentResult,
    context: dict
) -> PipelineResponse:
    """
    处理天气查询意图
    
    示例输入："上海明天天气怎么样"
    """
    logger.info(f"[WeatherQuery] 开始处理: trace_id={trace_id}")
    
    entities = intent_result.entities
    location = entities.get("location", "上海")
    date = entities.get("date", "明天")
    
    try:
        # 模拟天气查询（实际项目中调用天气API）
        weather_info = await _simulate_weather_query(location, date)
        
        content = f"🌤️ {location} {date}天气\n\n"
        content += f"🌡️ 温度：{weather_info.get('temperature', '未知')}\n"
        content += f"☁️ 天气：{weather_info.get('condition', '未知')}\n"
        content += f"💨 风力：{weather_info.get('wind', '未知')}\n"
        content += f"💧 湿度：{weather_info.get('humidity', '未知')}\n\n"
        
        if weather_info.get('clothing_advice'):
            content += f"👔 穿衣建议：{weather_info['clothing_advice']}\n"
        if weather_info.get('travel_advice'):
            content += f"🚗 出行建议：{weather_info['travel_advice']}"
        
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.SUCCESS,
            content=content,
            data=weather_info,
            intent_type=IntentType.WEATHER_QUERY,
            confidence=intent_result.confidence
        )
        
    except Exception as e:
        logger.error(f"[WeatherQuery] 处理失败: {e}", exc_info=True)
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.FAILED,
            content="",
            intent_type=IntentType.WEATHER_QUERY,
            confidence=intent_result.confidence,
            error_message=str(e)
        )


async def handle_chat_message(
    trace_id: str,
    user_input: str,
    intent_result: IntentResult,
    context: dict
) -> PipelineResponse:
    """
    处理普通聊天消息
    
    示例输入："你好"、"谢谢"
    """
    logger.info(f"[ChatMessage] 开始处理: trace_id={trace_id}")
    
    # 简单的聊天回复
    greetings = ["你好", "嗨", "hello", "hi"]
    thanks = ["谢谢", "感谢", "thank"]
    
    content = ""
    
    if any(g in user_input.lower() for g in greetings):
        content = "你好！我是旅行助手小游 😊 有什么旅行相关的问题可以问我～"
    elif any(t in user_input.lower() for t in thanks):
        content = "不客气！很高兴能帮到你 😊 有其他问题随时问我～"
    else:
        content = "收到你的消息！如果你有旅行规划、路线查询或景点推荐的需求，随时告诉我～"
    
    return PipelineResponse(
        trace_id=trace_id,
        status=ResponseStatus.SUCCESS,
        content=content,
        intent_type=IntentType.CHAT_MESSAGE,
        confidence=intent_result.confidence
    )


# ==================== 模拟服务函数 ====================

async def _simulate_route_generation(route_request: dict) -> dict:
    """模拟路线生成（实际项目中替换为真实服务调用）"""
    # 模拟异步处理
    await asyncio.sleep(0.5)
    
    destination = route_request.get("area", "上海")
    days = route_request.get("days", 3)
    themes = route_request.get("theme", "")
    
    # 生成模拟数据
    highlights = []
    if "美食" in themes or "美食" in str(route_request):
        highlights.append("品尝地道本帮菜和街头小吃")
    if "历史" in themes:
        highlights.append("探访外滩万国建筑群")
    if "文艺" in themes:
        highlights.append("漫步田子坊艺术街区")
    
    if not highlights:
        highlights = [
            f"游览{destination}标志性景点",
            "体验当地特色文化",
            "品尝地道美食"
        ]
    
    return {
        "id": f"route_{datetime.now().timestamp()}",
        "name": f"{destination}{days}日游",
        "destination": destination,
        "days": days,
        "summary": f"精心规划的{days}天{destination}之旅，涵盖热门景点和特色体验",
        "highlights": highlights,
        "pois": [],
        "status": "draft"
    }


async def _simulate_weather_query(location: str, date: str) -> dict:
    """模拟天气查询（实际项目中替换为真实API调用）"""
    # 模拟异步处理
    await asyncio.sleep(0.3)
    
    # 返回模拟天气数据
    return {
        "location": location,
        "date": date,
        "temperature": "18-25°C",
        "condition": "多云转晴",
        "wind": "东南风3-4级",
        "humidity": "65%",
        "clothing_advice": "建议穿轻薄外套，早晚温差较大",
        "travel_advice": "天气适宜出行，注意防晒"
    }
