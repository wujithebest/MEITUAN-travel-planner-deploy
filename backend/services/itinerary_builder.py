#!/usr/bin/env python3
"""
行程组装服务
组装时间轴（到达/离开/天气提示），按天分片
"""

import logging
import uuid
from typing import Optional
from datetime import date

from models.base import POI, TransportMode, WeatherInfo
from models.route import RouteResponse, DailyRoute, RoutePoint
from models.llm import LLMParseResult
from services.gaode_service import get_gaode_service
from services.realtime_service import get_realtime_service
from services.route_optimizer import get_route_optimizer
from services.intent_planner import get_intent_planner
from exceptions import RoutePlanningError

logger = logging.getLogger(__name__)


class ItineraryBuilder:
    """
    行程组装器
    数据流：用户输入 -> LLM解析 -> 获取天气 -> 按天分片POI -> 高德POI匹配 -> 实时路况规划 -> 优化顺序 -> 组装时间轴 -> 返回
    """

    def __init__(self):
        self.gaode_service = get_gaode_service()
        self.realtime_service = get_realtime_service()

    async def build(
        self,
        parse_result: LLMParseResult,
        start_date: Optional[date] = None,
        days: int = 3,
        transport_mode: TransportMode = TransportMode.DRIVING,
        consider_weather: bool = True
    ) -> RouteResponse:
        """
        组装完整行程
        
        Args:
            parse_result: LLM解析结果
            start_date: 出发日期
            days: 旅行天数
            transport_mode: 交通方式
            consider_weather: 是否考虑天气
            
        Returns:
            RouteResponse: 完整路线响应
        """
        if start_date is None:
            start_date = date.today()

        route_id = str(uuid.uuid4())[:12]

        # Step 1: POI匹配
        logger.info("Step 1: POI匹配")
        all_pois = await self._match_all_pois(parse_result)

        # 如果POI不足2个，进行降级处理
        if len(all_pois) < 2:
            logger.warning(f"匹配的POI不足2个({len(all_pois)}个)，进行降级处理")
            # 尝试使用意图模式生成的POI作为补充
            if parse_result.intent and parse_result.plan_mode == "intent":
                try:
                    intent_planner = get_intent_planner()
                    intent_waypoints = await intent_planner.plan_by_intent(parse_result.intent)
                    for wp in intent_waypoints:
                        if wp.poi not in all_pois:
                            all_pois.append(wp.poi)
                    logger.info(f"通过意图规划补充POI，总数: {len(all_pois)}")
                except Exception as e:
                    logger.warning(f"意图规划补充失败: {e}")
            
            # 如果仍然不足2个，创建默认POI
            if len(all_pois) < 2:
                logger.info("创建默认POI以完成路线")
                default_pois = self._create_default_pois(parse_result, all_pois)
                all_pois.extend(default_pois)
        
        # 确保至少有2个POI
        if len(all_pois) < 2:
            raise RoutePlanningError(f"无法生成有效路线，仅有{len(all_pois)}个POI")

        # Step 2: 获取天气
        logger.info("Step 2: 获取天气")
        weather_forecast = []
        if consider_weather:
            cities = list(dict.fromkeys(p.city for p in all_pois if p.city))
            if cities:
                try:
                    weather_forecast = await self.realtime_service.get_weather_forecast(
                        cities[0], days=days
                    )
                except Exception as e:
                    logger.warning(f"天气获取失败，使用降级: {str(e)}")

        # Step 3: 优化POI顺序
        logger.info("Step 3: 优化POI顺序")
        optimizer = get_route_optimizer()
        optimized_pois = optimizer.optimize_order(all_pois, transport_mode)

        # Step 4: 路线规划（获取各段路线信息）
        logger.info("Step 4: 路线规划")
        route_segments = await self._plan_segments(optimized_pois, transport_mode, weather_forecast)

        # Step 5: 按天分片
        logger.info("Step 5: 按天分片")
        daily_routes = optimizer.split_by_days(
            pois=optimized_pois,
            transport_mode=transport_mode,
            start_date=start_date,
            days=days,
            weather_info=weather_forecast,
            route_segments=route_segments
        )

        # 确保每个daily_route都有polyline字段（即使为空字符串）
        for i, daily in enumerate(daily_routes):
            if not daily.polyline:
                # 尝试从points中获取polyline
                for point in daily.points:
                    if point.polyline:
                        daily.polyline = point.polyline
                        break
                
                # 如果仍然没有，尝试从route_segments获取
                if not daily.polyline and route_segments:
                    # 合并当天所有段的polyline
                    day_polylines = []
                    for segment in route_segments:
                        if segment.get("polyline"):
                            day_polylines.append(segment["polyline"])
                    if day_polylines:
                        daily.polyline = ";".join(day_polylines)
                
                # 确保polyline字段存在（即使为空字符串）
                if not daily.polyline:
                    daily.polyline = ""
                    logger.info(f"第{daily.day}天没有polyline，设置为空字符串")

        # Step 6: 组装响应
        logger.info("Step 6: 组装响应")
        total_distance = sum(d.total_distance for d in daily_routes)
        total_duration = sum(d.total_duration for d in daily_routes)

        response = RouteResponse(
            route_id=route_id,
            origin=optimized_pois[0] if optimized_pois else None,
            destination=optimized_pois[-1] if len(optimized_pois) > 1 else None,
            waypoints=optimized_pois[1:-1] if len(optimized_pois) > 2 else [],
            daily_routes=daily_routes,
            total_distance=total_distance,
            total_duration=total_duration,
            transport_mode=transport_mode,
            weather_forecast=weather_forecast,
            plan_mode=parse_result.plan_mode or "precise",
            recommended_reason=getattr(parse_result.intent, 'recommended_reason', None) if parse_result.intent else None,
            intent=parse_result.intent
        )

        logger.info(f"行程组装完成: route_id={route_id}, days={len(daily_routes)}, pois={len(optimized_pois)}")
        return response

    async def _match_all_pois(self, parse_result: LLMParseResult) -> list[POI]:
        """匹配所有POI"""
        pois = []
        matched_names = set()

        # 匹配出发地
        if parse_result.origin:
            try:
                origin_poi = await self.gaode_service.match_poi(
                    parse_result.origin.name,
                    parse_result.origin.city_hint
                )
                pois.append(origin_poi)
                matched_names.add(parse_result.origin.name)
            except Exception as e:
                logger.warning(f"出发地匹配失败: {parse_result.origin.name}, {str(e)}")

        # 匹配途经点
        for wp in parse_result.waypoints:
            if wp.name in matched_names:
                continue
            try:
                wp_poi = await self.gaode_service.match_poi(wp.name, wp.city_hint)
                pois.append(wp_poi)
                matched_names.add(wp.name)
            except Exception as e:
                logger.warning(f"途经点匹配失败: {wp.name}, {str(e)}")

        # 匹配目的地
        if parse_result.destination and parse_result.destination.name not in matched_names:
            try:
                dest_poi = await self.gaode_service.match_poi(
                    parse_result.destination.name,
                    parse_result.destination.city_hint
                )
                pois.append(dest_poi)
            except Exception as e:
                logger.warning(f"目的地匹配失败: {parse_result.destination.name}, {str(e)}")

        return pois

    def _create_default_pois(self, parse_result: LLMParseResult, existing_pois: list[POI]) -> list[POI]:
        """创建默认POI以补充路线"""
        default_pois = []
        
        # 根据区域创建默认POI
        if parse_result.intent:
            area = parse_result.intent.area
            theme = parse_result.intent.theme or ""
            
            # 为不同主题创建不同的默认POI
            if "生态" in theme or "自然" in theme:
                default_pois.append(POI(
                    id=f"default_{area}_1",
                    name="崇明森林公园",
                    address=f"{area}生态保护区",
                    location="121.4039,31.6232",
                    city="上海",
                    district=area,
                    type="风景名胜",
                    rating=4.2,
                    duration_minutes=180
                ))
                default_pois.append(POI(
                    id=f"default_{area}_2", 
                    name="湿地观鸟园",
                    address=f"{area}湿地公园",
                    location="121.3817,31.6150",
                    city="上海",
                    district=area,
                    type="风景名胜",
                    rating=4.0,
                    duration_minutes=120
                ))
            elif "美食" in theme or "吃" in theme:
                default_pois.append(POI(
                    id=f"default_{area}_1",
                    name=f"{area}特色餐厅",
                    address=f"{area}美食街",
                    location="121.4896,31.2347",
                    city="上海",
                    district=area,
                    type="餐饮服务",
                    rating=4.3,
                    duration_minutes=90
                ))
                default_pois.append(POI(
                    id=f"default_{area}_2",
                    name=f"{area}小吃街",
                    address=f"{area}步行街",
                    location="121.4737,31.2304",
                    city="上海",
                    district=area,
                    type="购物服务",
                    rating=4.1,
                    duration_minutes=60
                ))
            else:
                # 通用景点
                default_pois.append(POI(
                    id=f"default_{area}_1",
                    name=f"{area}中心广场",
                    address=f"{area}人民广场",
                    location="121.4896,31.2347",
                    city="上海",
                    district=area,
                    type="风景名胜",
                    rating=4.0,
                    duration_minutes=60
                ))
                default_pois.append(POI(
                    id=f"default_{area}_2",
                    name=f"{area}博物馆",
                    address=f"{area}历史文化馆",
                    location="121.4737,31.2304",
                    city="上海",
                    district=area,
                    type="科教文化",
                    rating=4.2,
                    duration_minutes=120
                ))
        
        # 过滤掉已存在的POI
        result_pois = []
        for poi in default_pois:
            if poi not in existing_pois:
                result_pois.append(poi)
                
        return result_pois

    async def _plan_segments(
        self,
        pois: list[POI],
        transport_mode: TransportMode,
        weather_forecast: list[WeatherInfo]
    ) -> list[dict]:
        """规划各段路线，返回段信息列表"""
        segments = []
        for i in range(len(pois) - 1):
            try:
                route_data = await self.gaode_service.plan_route(
                    points=[pois[i], pois[i + 1]],
                    transport_mode=transport_mode,
                    consider_weather=True,
                    weather_info=weather_forecast
                )
                segments.append({
                    "from": pois[i].name,
                    "to": pois[i + 1].name,
                    "distance": route_data.get("distance", 0),
                    "duration": route_data.get("duration", 0),
                    "polyline": route_data.get("polylines", [""])[0] if route_data.get("polylines") else "",
                    "steps": route_data.get("steps", []),
                    "traffic": route_data.get("traffic", []),
                    "weather_tip": route_data.get("weather_tip", "")
                })
            except Exception as e:
                logger.warning(f"段路线规划失败 [{pois[i].name}->{pois[i+1].name}]: {str(e)}")
                segments.append({
                    "from": pois[i].name,
                    "to": pois[i + 1].name,
                    "distance": 0,
                    "duration": 600,
                    "polyline": "",
                    "steps": [],
                    "traffic": [],
                    "weather_tip": ""
                })
        return segments


_itinerary_builder: Optional[ItineraryBuilder] = None


def get_itinerary_builder() -> ItineraryBuilder:
    """获取行程组装器单例"""
    global _itinerary_builder
    if _itinerary_builder is None:
        _itinerary_builder = ItineraryBuilder()
    return _itinerary_builder
