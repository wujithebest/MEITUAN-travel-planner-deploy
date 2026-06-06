"""
路线规划路由 - 上海专用
POST /api/route/generate - 生成路线（上海内规划）
POST /api/route/optimize - 优化路线
GET /api/route/{route_id} - 获取路线
POST /api/route/poi/disambiguate - POI消歧

新流程：多地点生成 → 真实路线规划 → 沿途发现 → 重规划
"""

import logging
import uuid
from fastapi import APIRouter
from models.route import RouteResponse, DailyRoute, RoutePoint, EnroutePOI, RouteOptimizeRequest, DisambiguateRequest
from models.base import TransportMode, ApiResponse, POI, LocationInput
from models.llm import LLMParseResult, ParsedLocation, IntentModel
from services.llm_parser import get_llm_parser
from services.intent_planner import get_intent_planner
from services.gaode_service import get_gaode_service
from services.route_planner import get_route_planner
from services.enroute_discovery import get_enroute_discovery
from services.route_replanner import get_route_replanner
from config import get_settings
from exceptions import OutOfShanghaiError, POINotFoundError, RoutePlanningError

logger = logging.getLogger(__name__)

# 上海坐标范围常量
SHANGHAI_LNG_MIN = 120
SHANGHAI_LNG_MAX = 122
SHANGHAI_LAT_MIN = 30
SHANGHAI_LAT_MAX = 32

router = APIRouter(prefix="/api/route", tags=["路线规划"])

# 内存存储路线（生产环境应使用数据库）
_route_store: dict[str, RouteResponse] = {}

def generate_route_id() -> str:
    """生成唯一的路线ID"""
    return f"route_{uuid.uuid4().hex[:8]}"

@router.post("/generate", response_model=ApiResponse, summary="生成旅行路线")  # type: ignore[misc]
async def generate_route(input_data: LocationInput):  # type: ignore[misc]
    """
    根据自然语言输入生成旅行路线
     新闭环流程：
    1. LLM/意图解析 → 确保≥5个地点
    2. 第一次真实路线规划（plan_real_route）
    3. 沿途POI发现（enroute_discovery，基于步骤2的polyline）
    4. 路线重规划（replan_with_enroute）
    5. 天气查询 + 大众点评评论爬取（对main+enroute全部POI批量调用）
    6. 组装DailyRoute + map_config
    """
    try:
        # ========== Step 1: LLM解析自然语言 ==========
        logger.info("=" * 50)
        logger.info("Step 1: LLM解析自然语言")
        llm_parser = get_llm_parser()
        parse_result = await llm_parser.parse_travel_request(input_data.text)
        
        # 检查歧义
        if parse_result.is_ambiguous:
            return ApiResponse(
                success=True,
                data={
                    "is_ambiguous": True,
                    "ambiguity_details": parse_result.ambiguity_details,
                    "message": "存在歧义地点，请确认"
                },
                message="存在歧义地点，请确认后重新提交"
            )
        
        route_id = generate_route_id()
        
        # 获取主POI列表
        main_pois: list[POI] = []
        main_poi_names: list[str] = []
        
        if parse_result.plan_mode == "intent" and parse_result.intent:
            # ========== 意图模式 ==========
            logger.info(f"意图模式处理: {parse_result.intent.area}, {parse_result.intent.days}天")
            
            intent_planner = get_intent_planner()
            try:
                waypoints = await intent_planner.plan_by_intent(parse_result.intent)
                
                # 提取POI列表
                for wp in waypoints:
                    poi = wp.poi.model_copy()
                    main_pois.append(poi)
                    main_poi_names.append(poi.name)
                    
                logger.info(f"意图规划完成: {len(main_pois)}个主POI")
            except ValueError as e:
                return ApiResponse(
                    success=False,
                    data=None,
                    message=str(e),
                    code="INSUFFICIENT_POI"
                )
        else:
            # ========== 精确模式 ==========
            logger.info("精确模式处理")
            
            gaode_service = get_gaode_service()
            
            # 匹配origin
            if parse_result.origin:
                try:
                    origin_poi = await gaode_service.match_poi(
                        name=parse_result.origin.name,
                        city_hint="上海"
                    )
                    main_pois.append(origin_poi)
                    main_poi_names.append(origin_poi.name)
                except Exception as e:
                    logger.warning(f"匹配origin失败: {e}")
            
            # 匹配waypoints
            for loc in parse_result.waypoints:
                try:
                    poi = await gaode_service.match_poi(
                        name=loc.name,
                        city_hint="上海"
                    )
                    main_pois.append(poi)
                    main_poi_names.append(poi.name)
                except Exception as e:
                    logger.warning(f"匹配waypoint失败: {loc.name}, {e}")
            
            # 匹配destination
            if parse_result.destination:
                try:
                    dest_poi = await gaode_service.match_poi(
                        name=parse_result.destination.name,
                        city_hint="上海"
                    )
                    
                    # 避免重复
                    if dest_poi.name not in main_poi_names:
                        main_pois.append(dest_poi)
                        main_poi_names.append(dest_poi.name)
                except Exception as e:
                    logger.warning(f"匹配destination失败: {e}")
            
            # 确保至少5个POI
            if len(main_pois) < 5:
                logger.info(f"精确模式POI不足5个，尝试补充: 当前{len(main_pois)}个")
                intent_planner = get_intent_planner()
                main_pois = await intent_planner.expand_pois(main_pois, target_count=5)
                main_poi_names = [p.name for p in main_pois]
                
            logger.info(f"精确模式POI匹配完成: {len(main_pois)}个主POI")
        
        # ========== Step 1.5: Bug 3 修复 - 坐标范围校验 ==========
        logger.info("=" * 50)
        logger.info("Step 1.5: 坐标范围校验（上海范围）")
        
        for poi in main_pois:
            if poi.location and "," in poi.location:
                try:
                    lng, lat = map(float, poi.location.split(","))
                    if not (SHANGHAI_LNG_MIN < lng < SHANGHAI_LNG_MAX and SHANGHAI_LAT_MIN < lat < SHANGHAI_LAT_MAX):
                        error_msg = f"坐标异常: {poi.name}({lng},{lat})不在上海范围内"
                        logger.error(error_msg)
                        return ApiResponse(
                            success=False,
                            data=None,
                            message=error_msg,
                            code="COORDINATE_OUT_OF_RANGE"
                        )
                except (ValueError, IndexError) as e:
                    error_msg = f"坐标解析失败: {poi.name} 位置格式异常 '{poi.location}'"
                    logger.error(error_msg)
                    return ApiResponse(
                        success=False,
                        data=None,
                        message=error_msg,
                        code="COORDINATE_PARSE_ERROR"
                    )
            else:
                error_msg = f"坐标缺失: {poi.name} 无位置信息"
                logger.error(error_msg)
                return ApiResponse(
                    success=False,
                    data=None,
                    message=error_msg,
                    code="COORDINATE_MISSING"
                )
                
        logger.info(f"坐标校验通过: {len(main_pois)} 个POI均在上海范围内")
        
        # ========== Step 2: 第一次真实路线规划 ==========
        logger.info("=" * 50)
        logger.info("Step 2: 第一次真实路线规划")
        
        route_planner = get_route_planner()
        first_route_result = await route_planner.plan_real_route(
            points=main_pois,
            transport_mode=input_data.transport_mode
        )
        
        logger.info(
            f"第一次路线规划完成: "
            f"distance={first_route_result.distance}m, "
            f"duration={first_route_result.duration}s, "
            f"polyline长度={len(first_route_result.polyline)}"
        )
        
        # ========== Step 3: 沿途POI发现 ==========
        logger.info("=" * 50)
        logger.info("Step 3: 沿途POI发现")
        
        enroute_discovery = get_enroute_discovery()
        enroute_pois: list[EnroutePOI] = []
        
        if first_route_result.polyline:
            try:
                enroute_pois = await enroute_discovery.discover_enroute_pois(
                    polyline=first_route_result.polyline,
                    main_pois=main_poi_names,
                    max_results=6
                )
                
                logger.info(f"沿途POI发现完成: {len(enroute_pois)}个")
            except Exception as e:
                logger.warning(f"沿途POI发现失败: {e}")
                enroute_pois = []
        else:
            logger.warning("无polyline，跳过沿途POI发现")
        
        # ========== Step 4: 路线重规划 ==========
        logger.info("=" * 50)
        logger.info("Step 4: 路线重规划")
        
        route_replanner = get_route_replanner()
        final_route_points, final_route_result = await route_replanner.replan_with_enroute(
            main_points=main_pois,
            enroute_pois=enroute_pois,
            transport_mode=input_data.transport_mode,
            polyline=first_route_result.polyline
        )
        
        route_iterations = 2 if enroute_pois else 1
        
        logger.info(
            f"路线重规划完成: "
            f"总POI数={len(final_route_points)}, "
            f"distance={final_route_result.distance}m, "
            f"duration={final_route_result.duration}s, "
            f"iterations={route_iterations}"
        )
        
        # ========== Step 5: 天气查询 ==========
        logger.info("=" * 50)
        logger.info("Step 5: 天气查询")
        
        weather_forecast = []
        if input_data.consider_weather:
            try:
                from services.realtime_service import get_realtime_service
                realtime_service = get_realtime_service()
                weather_forecast = await realtime_service.get_weather_forecast(
                    city="上海",
                    days=input_data.days or 3
                )
            except Exception as e:
                logger.warning(f"天气查询失败: {e}")
        
        # ========== Step 5.5: 批量获取主POI评论 ==========
        logger.info("=" * 50)
        logger.info("Step 5.5: 批量获取主POI评论")
        
        # 暂时注释掉评论获取，避免依赖问题
        logger.info(f"主POI评论获取跳过: {len(main_pois)}个POI")
        # 注释掉以下行，因为POI模型没有reviews字段
        # for poi in main_pois:
        #     poi.reviews = []
        
        # 同样为沿途POI获取评论 - 暂时注释掉
        if enroute_pois:
            logger.info(f"沿途POI评论获取跳过: {len(enroute_pois)}个POI")
            # 注释掉以下行，因为POI模型没有reviews字段
            # for poi in enroute_pois:
            #     poi.reviews = []
        
        # ========== Step 6: 组装响应 ==========
        logger.info("=" * 50)
        logger.info("Step 6: 组装响应")
        
        # 按天分片
        days = input_data.days or 1
        daily_routes = _split_into_daily_routes(
            route_points=final_route_points,
            days=days,
            start_date=input_data.start_date,
            weather_forecast=weather_forecast
        )
        
        # 构建RouteResponse
        route_response = RouteResponse(
            route_id=route_id,
            origin=main_pois[0] if main_pois else None,
            destination=main_pois[-1] if len(main_pois) > 1 else None,
            waypoints=main_pois[1:-1] if len(main_pois) > 2 else [],
            main_pois=main_pois,
            daily_routes=daily_routes,
            total_distance=final_route_result.distance,
            total_duration=final_route_result.duration,
            transport_mode=input_data.transport_mode,
            weather_forecast=weather_forecast,
            traffic_segments=final_route_result.traffic_segments,
            overall_traffic=final_route_result.overall_traffic,
            enroute_pois=enroute_pois,
            route_iterations=route_iterations,
            polyline=final_route_result.polyline,
            plan_mode=parse_result.plan_mode or "precise",
            recommended_reason=_generate_recommended_reason(parse_result, main_pois, enroute_pois),
            intent=parse_result.intent
        )
        
        # 存储路线
        _route_store[route_id] = route_response
        
        logger.info("=" * 50)
        logger.info("路线生成完成!")
        
        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(route_response.model_dump(mode='json'), default=str)),
            message="路线生成成功"
        )
    except OutOfShanghaiError as e:
        logger.warning(f"外地地点: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=str(e),
            code="OUT_OF_SHANGHAI"
        )
    except POINotFoundError as e:
        logger.warning(f"POI未找到（上海市内）: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=str(e),
            code="POI_NOT_FOUND"
        )
    except RoutePlanningError as e:
        logger.error(f"路线规划失败: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=str(e),
            code="ROUTE_ERROR"
        )
    except Exception as e:
        logger.exception(f"路线生成异常: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"路线生成失败: {str(e)}",
            code="INTERNAL_ERROR"
        )

def _split_into_daily_routes(
    route_points: list[RoutePoint],
    days: int,
    start_date,
    weather_forecast: list
) -> list:
    """
    将路线点按天分片
    """
    from models.route import DailyRoute
    
    if days <= 0:
        days = 1
    
    # 每天分配的POI数量
    pois_per_day = max(1, len(route_points) // days)
    
    daily_routes = []
    
    for day in range(days):
        start_idx = day * pois_per_day
        end_idx = start_idx + pois_per_day if day < days - 1 else len(route_points)
        
        day_points = route_points[start_idx:end_idx]
        
        # 计算当天总距离和时长
        total_distance = sum(p.distance_from_prev for p in day_points)
        total_duration = sum(p.duration_from_prev for p in day_points)
        total_transport = sum(p.duration_from_prev for p in day_points)
        
        # 获取当天天气
        weather_tip = ""
        if weather_forecast and day < len(weather_forecast):
            w = weather_forecast[day]
            if w.weather_tip:
                weather_tip = w.weather_tip
        
        daily_route = DailyRoute(
            day=day + 1,
            date=str(start_date) if start_date else None,
            points=day_points,
            total_distance=total_distance,
            total_duration=total_duration,
            total_transport_duration=total_transport,
            weather_tip=weather_tip,
            smoothness_score=_calculate_smoothness(day_points)
        )
        
        daily_routes.append(daily_route)
    
    return daily_routes

def _calculate_smoothness(points: list[RoutePoint]) -> float:
    """
    计算流畅度评分（1-10）
    """
    if not points:
        return 5.0
    
    # 基于距离和时长的合理性评分
    score = 8.0  # 基础分
    
    for point in points:
        # 距离过长扣分
        if point.distance_from_prev > 10000:  # 10km
            score -= 0.5
        # 时长过长扣分
        if point.duration_from_prev > 1800:  # 30分钟
            score -= 0.3
    
    return max(1.0, min(10.0, score))

def _generate_recommended_reason(
    parse_result: LLMParseResult,
    main_pois: list[POI],
    enroute_pois: list[EnroutePOI]
) -> str:
    """
    生成推荐理由
    """
    poi_names = [p.name for p in main_pois[:3]]
    main_str = "、".join(poi_names)
    
    if parse_result.plan_mode == "intent" and parse_result.intent:
        return (
            f"根据您的需求，为您推荐『{parse_result.intent.area}』"
            f"{parse_result.intent.theme or '精选'}行程，"
            f"包含{len(main_pois)}个精华景点（{main_str}等）"
            f"{f'，另有{len(enroute_pois)}个沿途发现的好去处' if enroute_pois else ''}"
        )
    else:
        return (
            f"为您规划了包含{len(main_pois)}个地点的行程（{main_str}等）"
            f"{f'，沿途还发现了{len(enroute_pois)}个值得一去的地方' if enroute_pois else ''}"
        )

@router.post("/optimize", response_model=ApiResponse, summary="优化路线")
async def optimize_route(request: RouteOptimizeRequest):
    """优化已有路线"""
    try:
        route = _route_store.get(request.route_id)
        if not route:
            return ApiResponse(
                success=False,
                data=None,
                message=f"路线不存在: {request.route_id}",
                code="NOT_FOUND"
            )

        from services.route_optimizer import RouteOptimizer
        optimizer = RouteOptimizer(max_hours_per_day=request.max_hours_per_day)

        all_pois = []
        if route.origin:
            all_pois.append(route.origin)
        all_pois.extend(route.waypoints)
        if route.destination:
            all_pois.append(route.destination)

        if request.optimize_by == "distance" or request.optimize_by == "smoothness":
            optimized = optimizer.optimize_order(all_pois, route.transport_mode)
        else:
            optimized = all_pois

        # 重新分片
        daily_routes = optimizer.split_by_days(
            pois=optimized,
            transport_mode=route.transport_mode,
            start_date=route.daily_routes[0].date if route.daily_routes else None,
            days=len(route.daily_routes),
            weather_info=route.weather_forecast
        )

        route.daily_routes = daily_routes
        route.total_distance = sum(d.total_distance for d in daily_routes)
        route.total_duration = sum(d.total_duration for d in daily_routes)
        _route_store[route.route_id] = route

        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(route.model_dump(), default=str)),
            message="路线优化成功"
        )

    except Exception as e:
        logger.exception(f"路线优化异常: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"路线优化失败: {str(e)}",
            code="OPTIMIZE_ERROR"
        )

@router.get("/{route_id}", response_model=ApiResponse, summary="获取路线详情")
async def get_route(route_id: str):
    """获取路线详情"""
    route = _route_store.get(route_id)
    if not route:
        return ApiResponse(
            success=False,
            data=None,
            message=f"路线不存在: {route_id}",
            code="NOT_FOUND"
        )

    return ApiResponse(
        success=True,
        data=json.loads(json.dumps(route.model_dump(), default=str)),
        message="获取成功"
    )

@router.post("/poi/disambiguate", response_model=ApiResponse, summary="POI消歧")
async def disambiguate_poi(request: DisambiguateRequest):
    """
    处理POI歧义选择
    用户从歧义选项中选择一个POI
    """
    try:
        gaode_service = get_gaode_service()
        
        # 重新搜索获取选项
        pois_data = await gaode_service.place_text(
            keywords=request.poi_name,
            offset=10
        )

        selected_poi = None
        for poi_data in pois_data:
            if poi_data.get("id") == request.selected_id:
                selected_poi = POI(
                    id=poi_data.get("id", ""),
                    name=poi_data.get("name", ""),
                    address=poi_data.get("address", ""),
                    location=poi_data.get("location", ""),
                    city=poi_data.get("cityname", ""),
                    district=poi_data.get("district", ""),
                    type=poi_data.get("type", ""),
                    rating=float(poi_data.get("biz_ext", {}).get("rating", 0) or 0),
                    open_time=poi_data.get("open_info"),
                    close_time=poi_data.get("close_info"),
                    ambiguity=False,
                    duration_minutes=60,
                    metro_hint=""
                    # reviews=[]  # 注释掉，因为POI模型没有reviews字段
                )
                break

        if not selected_poi:
            return ApiResponse(
                success=False,
                data=None,
                message="未找到选中的POI",
                code="POI_NOT_FOUND"
            )

        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(selected_poi.model_dump(), default=str)),
            message="POI消歧成功"
        )

    except Exception as e:
        logger.exception(f"POI消歧异常: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"POI消歧失败: {str(e)}",
            code="DISAMBIGUATE_ERROR"
        )
