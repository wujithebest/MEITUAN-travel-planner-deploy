"""
路线优化服务 - 上海专用
按天分片、时间窗约束、流畅度评分
考虑上海地铁末班车（约22:30）和景点开放时间（如外滩全天、博物馆周一闭馆）
避免浦西浦东反复横跳
"""

import logging
from typing import Optional
from datetime import datetime, timedelta, date

from config import SHANGHAI_LAST_METRO_TIME, MUSEUM_CLOSED_DAY
from models.base import POI, TransportMode, WeatherInfo
from models.route import RoutePoint, DailyRoute

logger = logging.getLogger(__name__)

# 上海每日最大游览时间（8小时）
DEFAULT_MAX_HOURS_PER_DAY = 8.0

# 上海地铁末班车时间（22:30）
LAST_METRO_HOUR = 22
LAST_METRO_MINUTE = 30

# 浦西浦东区域标识（简化判断）
PUDONG_KEYWORDS = ["浦东", "陆家嘴", "张江", "金桥", "外高桥", "迪斯尼", "迪士尼", "川沙", "临港"]
PUXI_KEYWORDS = ["浦西", "外滩", "南京路", "人民广场", "静安", "黄浦", "徐汇", "长宁", "普陀", "虹口", "杨浦"]


class RouteOptimizer:
    """路线优化器 - 上海专用"""

    def __init__(self, max_hours_per_day: float = DEFAULT_MAX_HOURS_PER_DAY):
        self.max_hours_per_day = max_hours_per_day
        self.max_seconds_per_day = int(max_hours_per_day * 3600)
        # 餐时预留（分钟）
        self.meal_times = [
            {"name": "早餐", "start": 420, "duration": 45},   # 07:00-07:45
            {"name": "午餐", "start": 720, "duration": 60},   # 12:00-13:00
            {"name": "晚餐", "start": 1080, "duration": 60},  # 18:00-19:00
        ]

    def split_by_days(
        self,
        pois: list[POI],
        transport_mode: TransportMode,
        start_date: Optional[date] = None,
        days: int = 1,
        weather_info: Optional[list[WeatherInfo]] = None,
        route_segments: Optional[list[dict]] = None
    ) -> list[DailyRoute]:
        """
        按天分片POI列表
        每天不超过max_hours_per_day，自动预留餐时
        
        Args:
            pois: POI列表
            transport_mode: 交通方式
            start_date: 出发日期
            days: 总天数
            weather_info: 天气信息
            route_segments: 预计算的路线段信息
            
        Returns:
            list[DailyRoute]: 每日路线列表
        """
        if not pois:
            return []

        # 处理 start_date 可能是字符串的情况
        if start_date is None:
            start_date = date.today()
        elif isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)

        if days <= 0:
            days = 1

        daily_routes = []
        poi_index = 0
        current_time = 8 * 60  # 每天从8:00开始（用分钟表示）

        for day_num in range(1, days + 1):
            day_date = start_date + timedelta(days=day_num - 1)
            day_points: list[RoutePoint] = []
            day_seconds = 0
            day_transport_seconds = 0
            day_distance = 0.0

            # 获取当天天气
            day_weather = None
            if weather_info:
                # 将 day_date 转换为 date 对象（如果是字符串）
                if isinstance(day_date, str):
                    from datetime import date as date_type
                    day_date_obj = date_type.fromisoformat(day_date)
                else:
                    day_date_obj = day_date
                    
                for w in weather_info:
                    # 确保比较的是相同类型
                    w_date = w.forecast_date
                    if isinstance(w_date, str):
                        from datetime import date as date_type
                        w_date = date_type.fromisoformat(w_date)
                    if w_date == day_date_obj:
                        day_weather = w
                        break

            while poi_index < len(pois):
                poi = pois[poi_index]

                # 获取路线段信息
                segment = None
                if route_segments and poi_index > 0 and poi_index - 1 < len(route_segments):
                    segment = route_segments[poi_index - 1]

                transport_duration = segment.get("duration", 600) if segment else 600
                transport_distance = segment.get("distance", 0) if segment else 0
                stay_minutes = poi.duration_minutes

                # 天气调整：雨天优先室内（延长室内POI停留，跳过户外）
                if day_weather and day_weather.is_rainy:
                    if self._is_outdoor_poi(poi):
                        logger.info(f"雨天跳过户外POI: {poi.name}")
                        poi_index += 1
                        continue
                    elif self._is_indoor_poi(poi):
                        stay_minutes = int(stay_minutes * 1.2)  # 室内活动延长20%

                # 高温调整：减少户外活动时长（上海夏季>35°C）
                if day_weather and day_weather.is_high_temp:
                    if self._is_outdoor_poi(poi):
                        stay_minutes = int(stay_minutes * 0.7)
                        logger.info(f"高温调整: {poi.name} 停留时间减少至{stay_minutes}分钟")

                # 上海特殊规则：博物馆周一闭馆
                if self._is_museum_poi(poi) and day_date.weekday() == MUSEUM_CLOSED_DAY:
                    logger.info(f"周一闭馆: {poi.name}（博物馆周一闭馆）")
                    poi_index += 1
                    continue

                # 计算该POI的总耗时（交通 + 游览）
                total_poi_seconds = transport_duration + stay_minutes * 60

                # 检查是否超过每日上限
                if day_seconds + total_poi_seconds > self.max_seconds_per_day and day_points:
                    break  # 超过上限，留到明天

                # 计算到达时间
                arrival_minutes = current_time + transport_duration // 60

                # 上海地铁末班车限制（22:30）
                latest_return_time = LAST_METRO_HOUR * 60 + LAST_METRO_MINUTE
                if arrival_minutes > latest_return_time:
                    logger.info(f"超过末班车时间: {poi.name}，跳过")
                    poi_index += 1
                    continue

                # 检查时间窗：考虑开放时间
                if poi.open_time and not self._is_within_open_hours(arrival_minutes, poi.open_time):
                    # 如果还没开放，等待到开放时间
                    try:
                        open_minutes = self._parse_time_to_minutes(poi.open_time)
                        if open_minutes > arrival_minutes:
                            wait_minutes = open_minutes - arrival_minutes
                            arrival_minutes = open_minutes
                            total_poi_seconds += wait_minutes * 60
                    except (ValueError, IndexError, AttributeError, TypeError):
                        # 如果解析失败，跳过等待逻辑
                        pass

                # 餐时预留
                for meal in self.meal_times:
                    if current_time <= meal["start"] and arrival_minutes >= meal["start"]:
                        total_poi_seconds += meal["duration"] * 60
                        break

                # 创建路线点
                arrival_dt = datetime.combine(day_date, datetime.min.time()) + timedelta(minutes=arrival_minutes)
                departure_dt = arrival_dt + timedelta(minutes=stay_minutes)

                route_point = RoutePoint(
                    poi=poi,
                    arrival_time=arrival_dt,
                    departure_time=departure_dt,
                    stay_minutes=stay_minutes,
                    transport_from_prev=transport_mode,
                    distance_from_prev=transport_distance,
                    duration_from_prev=transport_duration,
                    polyline=segment.get("polyline", "") if segment else "",
                    steps=segment.get("steps", []) if segment else [],
                    weather=day_weather
                )

                day_points.append(route_point)
                day_seconds += total_poi_seconds
                day_transport_seconds += transport_duration
                day_distance += transport_distance
                current_time = arrival_minutes + stay_minutes
                poi_index += 1

            # 计算流畅度评分
            smoothness = self._calculate_smoothness(day_points, day_transport_seconds, day_seconds)

            daily_routes.append(DailyRoute(
                day=day_num,
                date=day_date.isoformat() if day_date else None,
                points=day_points,
                total_distance=day_distance,
                total_duration=day_seconds,
                total_transport_duration=day_transport_seconds,
                weather_tip=day_weather.weather_tip if day_weather else "",
                smoothness_score=smoothness
            ))

            # 重置当天时间
            current_time = 8 * 60

            if poi_index >= len(pois):
                break

        # 如果还有剩余POI但天数已满，追加到最后一天
        while poi_index < len(pois):
            logger.warning(f"POI超出计划天数: {pois[poi_index].name}")
            if daily_routes:
                last_day = daily_routes[-1]
                last_day.points.append(RoutePoint(poi=pois[poi_index]))
            poi_index += 1

        logger.info(f"路线分片完成: {len(daily_routes)}天, {len(pois)}个POI")
        return daily_routes

    def _is_outdoor_poi(self, poi: POI) -> bool:
        """判断是否为户外POI"""
        outdoor_types = ["风景名胜", "公园", "景区", "山", "湖", "海滩", "岛"]
        return any(t in poi.type for t in outdoor_types)

    def _is_indoor_poi(self, poi: POI) -> bool:
        """判断是否为室内POI"""
        indoor_types = ["博物馆", "购物中心", "室内", "剧院", "美术馆", "展览馆", "科技馆"]
        return any(t in poi.type for t in indoor_types)

    def _is_museum_poi(self, poi: POI) -> bool:
        """判断是否为博物馆（周一闭馆）"""
        museum_keywords = ["博物馆", "纪念馆", "陈列馆", "展览馆", "科技馆", "艺术馆"]
        return any(kw in poi.name or kw in poi.type for kw in museum_keywords)

    def _is_in_pudong(self, poi: POI) -> bool:
        """判断POI是否在浦东"""
        poi_text = f"{poi.name} {poi.address} {poi.district}"
        return any(kw in poi_text for kw in PUDONG_KEYWORDS)

    def _is_in_puxi(self, poi: POI) -> bool:
        """判断POI是否在浦西"""
        poi_text = f"{poi.name} {poi.address} {poi.district}"
        return any(kw in poi_text for kw in PUXI_KEYWORDS)

    def _calculate_cross_river_penalty(self, current_poi: POI, next_poi: POI) -> int:
        """
        计算浦西浦东跨江惩罚（分钟）
        避免一天内反复横跳黄浦江
        """
        current_pudong = self._is_in_pudong(current_poi)
        current_puxi = self._is_in_puxi(current_poi)
        next_pudong = self._is_in_pudong(next_poi)
        next_puxi = self._is_in_puxi(next_poi)

        # 跨江惩罚
        if (current_pudong and next_puxi) or (current_puxi and next_pudong):
            return 30  # 跨江增加30分钟
        return 0

    def _is_within_open_hours(self, arrival_minutes: int, open_time_value) -> bool:
        """检查是否在开放时间内"""
        # 处理不同类型的 open_time 值
        if not open_time_value:
            return True
        
        # 如果是列表且为空，也视为无开放时间
        if isinstance(open_time_value, list) and len(open_time_value) == 0:
            return True
            
        # 如果是字符串，尝试解析
        if isinstance(open_time_value, str):
            try:
                open_minutes = self._parse_time_to_minutes(open_time_value)
                return arrival_minutes >= open_minutes
            except (ValueError, IndexError, TypeError):
                # 如果解析失败，包括空列表等类型错误，默认为True
                return True
        else:
            # 对于其他类型（如数字、None等），默认为True
            return True

    def _parse_time_to_minutes(self, time_str: str) -> int:
        """将时间字符串转换为分钟数，如 '09:00' -> 540"""
        parts = time_str.strip().split("-")[0].split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def _calculate_smoothness(
        self,
        points: list[RoutePoint],
        transport_seconds: int,
        total_seconds: int
    ) -> float:
        """
        计算流畅度评分（1-10分）
        
        评分维度：
        - 回绕度：路线是否绕路（0-4分）
        - 交通占比：交通时间占总时间的比例（0-3分）
        - 时间分布均匀度（0-3分）
        """
        if not points or total_seconds == 0:
            return 5.0

        score = 10.0

        # 交通占比扣分（交通占比越高，流畅度越低）
        transport_ratio = transport_seconds / total_seconds if total_seconds > 0 else 0
        if transport_ratio > 0.5:
            score -= 3.0
        elif transport_ratio > 0.3:
            score -= 1.5

        # POI数量扣分（太多POI导致赶路感）
        if len(points) > 6:
            score -= 2.0
        elif len(points) > 4:
            score -= 0.5

        # 停留时长扣分（太短停留扣分）
        short_stays = sum(1 for p in points if p.stay_minutes < 30)
        score -= short_stays * 0.5

        return max(1.0, min(10.0, score))

    def optimize_order(
        self,
        points: list[POI],
        transport_mode: TransportMode
    ) -> list[POI]:
        """
        优化POI顺序（简化版最近邻算法）
        
        Args:
            points: POI列表
            transport_mode: 交通方式
            
        Returns:
            list[POI]: 优化后的POI列表
        """
        if len(points) <= 2:
            return points

        # 保持起点和终点不变，优化中间点
        origin = points[0]
        destination = points[-1]
        middle = points[1:-1]

        if not middle:
            return points

        # 最近邻贪心算法
        optimized = [origin]
        remaining = middle.copy()
        current = origin

        while remaining:
            nearest_idx = 0
            nearest_dist = float("inf")

            for i, poi in enumerate(remaining):
                dist = self._estimate_distance(current.location, poi.location)
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_idx = i

            optimized.append(remaining.pop(nearest_idx))
            current = optimized[-1]

        optimized.append(destination)
        return optimized

    def _estimate_distance(self, loc1: str, loc2: str) -> float:
        """估算两点间距离（简化版，使用Haversine公式）"""
        import math

        if not loc1 or not loc2:
            return 0.0

        try:
            lng1, lat1 = map(float, loc1.split(","))
            lng2, lat2 = map(float, loc2.split(","))

            # Haversine公式
            R = 6371000  # 地球半径（米）
            phi1 = math.radians(lat1)
            phi2 = math.radians(lat2)
            delta_phi = math.radians(lat2 - lat1)
            delta_lambda = math.radians(lng2 - lng1)

            a = (math.sin(delta_phi / 2) ** 2 +
                 math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

            return R * c
        except (ValueError, IndexError):
            return 0.0


_route_optimizer: Optional[RouteOptimizer] = None


def get_route_optimizer(max_hours_per_day: float = 8.0) -> RouteOptimizer:
    """获取路线优化器"""
    global _route_optimizer
    if _route_optimizer is None:
        _route_optimizer = RouteOptimizer(max_hours_per_day)
    return _route_optimizer
