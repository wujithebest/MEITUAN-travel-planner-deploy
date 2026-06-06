"""
真实路线规划服务 - 基于高德道路级路线规划
替代原简单规划，使用真实道路API获取道路级坐标
"""

import logging
import math
import traceback
from typing import Optional
import httpx

from config import get_settings
from models.base import POI, TransportMode
from models.route import RoutePoint, TrafficSegment
from exceptions import RoutePlanningError

logger = logging.getLogger(__name__)

# 步行模式限制常量
WALKING_MAX_DISTANCE_KM = 30  # 步行最大距离 30km
WALKING_MAX_WAYPOINTS = 5     # 步行最大途经点数

# 上海坐标范围常量
SHANGHAI_LNG_MIN = 120
SHANGHAI_LNG_MAX = 122
SHANGHAI_LAT_MIN = 30
SHANGHAI_LAT_MAX = 32


def _haversine_distance_km(loc1: str, loc2: str) -> float:
    """计算两点间距离（千米）"""
    if not loc1 or not loc2:
        return float("inf")
    try:
        lng1, lat1 = map(float, loc1.split(","))
        lng2, lat2 = map(float, loc2.split(","))
    except Exception:
        return float("inf")
    
    R = 6371  # 地球半径（千米）
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def _calculate_bounding_box_max_distance(points: list[POI]) -> float:
    """
    计算所有POI包围盒的最大跨度（千米）
    返回任意两点间的最大直线距离
    """
    if len(points) < 2:
        return 0.0
    
    max_distance = 0.0
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            dist = _haversine_distance_km(points[i].location, points[j].location)
            if dist > max_distance:
                max_distance = dist
    
    return max_distance


class RouteResult:
    """路线规划结果"""
    def __init__(
        self,
        polyline: str = "",
        distance: float = 0.0,
        duration: int = 0,
        steps: list[str] = None,
        traffic_segments: list[TrafficSegment] = None,
        overall_traffic: str = "smooth"
    ):
        self.polyline = polyline
        self.distance = distance
        self.duration = duration
        self.steps = steps or []
        self.traffic_segments = traffic_segments or []
        self.overall_traffic = overall_traffic


class RoutePlanner:
    """真实路线规划器 - 基于高德道路级API"""
    
    def __init__(self):
        self.settings = get_settings()
        self.key = self.settings.gaode_key
        self.base_url = "https://restapi.amap.com/v3"
        self.timeout = 15.0

    def _validate_shanghai_coordinates(self, location_str: str) -> bool:
        """
        验证坐标是否在上海范围内
        上海范围：经度 120-122，纬度 30-32
        """
        if not location_str or "," not in location_str:
            return False
        try:
            lng, lat = map(float, location_str.split(","))
            return SHANGHAI_LNG_MIN < lng < SHANGHAI_LNG_MAX and SHANGHAI_LAT_MIN < lat < SHANGHAI_LAT_MAX
        except (ValueError, IndexError):
            return False

    async def plan_real_route(
        self,
        points: list[POI],
        transport_mode: TransportMode
    ) -> RouteResult:
        """
        规划真实道路路线
        
        Bug 3 修复：
        - 规划前校验所有 POI 坐标必须在上海范围内（120<lng<122, 30<lat<32）
        - 任一坐标异常立即终止并返回友好错误
        
        Bug 4 修复：
        - 计算所有 POI 两两之间的最大直线距离
        - 若最大距离 >30km 或 waypoints 数量 >5，且当前 mode="walking"，自动降级为 "driving"
        - 驾车请求附加 extensions=all，确保返回 polyline
        - 若 walking API 返回 OVER_DIRECTION_RANGE，自动重试 driving 模式
        
        Args:
            points: POI列表（按顺序）
            transport_mode: 交通方式
            
        Returns:
            RouteResult: 包含真实polyline、steps、距离、时长的结果
            
        Raises:
            RoutePlanningError: 路线规划失败
        """
        logger.info(f"[RoutePlanner] 开始执行, 参数: points_count={len(points)}, mode={transport_mode.value}")
        
        if len(points) < 2:
            logger.error(f"[RoutePlanner] 点数不足: {len(points)}")
            raise RoutePlanningError("路线规划至少需要2个点")
        
        # Bug 3 修复：规划前坐标 Sanity Check
        logger.info(f"[RoutePlanner] Step 1: 坐标校验")
        for p in points:
            if not self._validate_shanghai_coordinates(p.location):
                logger.error(f"[RoutePlanner] 坐标异常: {p.name}({p.location})")
                raise RoutePlanningError(f"坐标异常: {p.name}({p.location})不在上海范围内")
        logger.info(f"[RoutePlanner] Step 1完成: 坐标校验通过")
        
        origin = points[0].location
        destination = points[-1].location
        waypoints_count = len(points) - 2
        
        logger.info(f"[RoutePlanner] origin={origin}, destination={destination}, waypoints_count={waypoints_count}")
        
        # Bug 4 修复：长距离自动切换交通方式
        max_distance_km = _calculate_bounding_box_max_distance(points)
        original_mode = transport_mode
        
        if transport_mode == TransportMode.WALKING:
            if max_distance_km > WALKING_MAX_DISTANCE_KM or waypoints_count > WALKING_MAX_WAYPOINTS:
                logger.info(f"[RoutePlanner] 行程距离较远（最大跨度 {max_distance_km:.1f}km，途经点 {waypoints_count} 个），已自动切换为驾车模式")
                transport_mode = TransportMode.DRIVING
        
        # 构建waypoints字符串（高德最多支持16个途经点）
        waypoints_str = ""
        if len(points) > 2:
            intermediate_points = points[1:-1][:16]  # 最多16个途经点
            waypoints_str = ";".join(p.location for p in intermediate_points)
        
        logger.info(f"[RoutePlanner] Step 2: 调用高德API, mode={transport_mode.value}")
        
        try:
            if transport_mode == TransportMode.DRIVING:
                result = await self._plan_driving(origin, destination, waypoints_str)
            elif transport_mode == TransportMode.WALKING:
                try:
                    result = await self._plan_walking(origin, destination, waypoints_str)
                except RoutePlanningError as e:
                    error_msg = str(e)
                    if "OVER_DIRECTION_RANGE" in error_msg or "距离超限" in error_msg:
                        logger.info(f"[RoutePlanner] 步行模式返回超限错误，自动重试驾车模式: {e}")
                        result = await self._plan_driving(origin, destination, waypoints_str)
                    else:
                        raise
            elif transport_mode == TransportMode.TRANSIT:
                result = await self._plan_transit(origin, destination)
            else:
                result = await self._plan_driving(origin, destination, waypoints_str)
            
            logger.info(f"[RoutePlanner] 执行完成, 结果: distance={result.distance}m, duration={result.duration}s, polyline_length={len(result.polyline)}")
            return result
            
        except RoutePlanningError:
            raise
        except Exception as e:
            logger.error(f"[RoutePlanner] 路线规划异常: {str(e)}, 堆栈: {traceback.format_exc()}")
            raise RoutePlanningError(f"路线规划失败: {str(e)}")

    async def _plan_driving(
        self,
        origin: str,
        destination: str,
        waypoints: str = ""
    ) -> RouteResult:
        """驾车路线规划 - 获取真实道路坐标"""
        logger.info(f"[RoutePlanner] _plan_driving开始, origin={origin}, destination={destination}")
        url = f"{self.base_url}/direction/driving"
        params = {
            "key": self.key,
            "origin": origin,
            "destination": destination,
            "strategy": 10,  # 使用实时路况
            "extensions": "all",
            "output": "JSON"
        }
        if waypoints:
            params["waypoints"] = waypoints
            logger.info(f"[RoutePlanner] waypoints={waypoints}")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"[RoutePlanner] 发送驾车路线请求到高德API")
                response = await client.get(url, params=params)
                logger.info(f"[RoutePlanner] 高德响应状态: {response.status_code}")
                response.raise_for_status()
                data = response.json()
            
            logger.info(f"[RoutePlanner] 高德响应: status={data.get('status')}, info={data.get('info')}")
            
            if data.get("status") != "1":
                error_msg = data.get("info", "未知错误")
                logger.error(f"[RoutePlanner] 驾车路线规划失败: {error_msg}")
                raise RoutePlanningError(f"驾车路线规划失败: {error_msg}")
            
            route = data.get("route", {})
            paths = route.get("paths", [])
            
            logger.info(f"[RoutePlanner] 路径数: {len(paths)}")
            
            if not paths:
                logger.error(f"[RoutePlanner] 驾车路线规划无结果")
                raise RoutePlanningError("驾车路线规划无结果")
            
            # 取第一条路线（最优）
            best_path = paths[0]
            
            # 解析polyline
            polyline = best_path.get("polyline", "")
            logger.info(f"[RoutePlanner] polyline长度: {len(polyline) if polyline else 0}")
            
            # 如果polyline为空，尝试从steps中拼接
            if not polyline or len(polyline) < 10:
                logger.warning(f"[RoutePlanner] 高德API返回polyline为空，尝试从steps中拼接")
                steps_data = best_path.get("steps", [])
                polylines = []
                for step in steps_data:
                    step_polyline = step.get("polyline", "")
                    if step_polyline:
                        polylines.append(step_polyline)
                
                if polylines:
                    polyline = ";".join(polylines)
                    logger.info(f"[RoutePlanner] 从steps拼接polyline成功，长度: {len(polyline)}")
                else:
                    logger.error(f"[RoutePlanner] 高德未返回路线坐标")
                    raise RoutePlanningError("高德未返回路线坐标，请减少途经点或更换交通方式")
            
            # 解析步骤
            steps = []
            for step in best_path.get("steps", []):
                instruction = step.get("instruction", "")
                road_name = step.get("road", "")
                distance = step.get("distance", 0)
                if instruction:
                    steps.append(f"{instruction}（{road_name}，{distance}米）" if road_name else instruction)
            
            # 解析交通拥堵段
            traffic_segments = self._parse_traffic_segments(best_path.get("tmcs", []))
            
            result = RouteResult(
                polyline=polyline,
                distance=float(best_path.get("distance", 0)),
                duration=int(best_path.get("duration", 0)),
                steps=steps,
                traffic_segments=traffic_segments,
                overall_traffic=self._determine_overall_traffic(traffic_segments)
            )
            
            logger.info(f"[RoutePlanner] _plan_driving完成: distance={result.distance}m, duration={result.duration}s")
            return result
            
        except RoutePlanningError:
            raise
        except Exception as e:
            logger.error(f"[RoutePlanner] _plan_driving异常: {str(e)}, 堆栈: {traceback.format_exc()}")
            raise RoutePlanningError(f"驾车路线规划失败: {str(e)}")

    async def _plan_walking(self, origin: str, destination: str, waypoints: str = "") -> RouteResult:
        """步行路线规划"""
        logger.info(f"[RoutePlanner] _plan_walking开始, origin={origin}, destination={destination}")
        
        # 高德步行API可能不支持waypoints参数，采用分段规划
        if waypoints:
            logger.info(f"[RoutePlanner] 步行路线使用分段规划，途经点: {waypoints}")
            return await self._plan_walking_with_waypoints(origin, waypoints)
        
        url = f"{self.base_url}/direction/walking"
        params = {
            "key": self.key,
            "origin": origin,
            "destination": destination,
            "output": "JSON",
            "extensions": "all"  # 添加extensions=all确保返回polyline
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"[RoutePlanner] 发送步行路线请求到高德API")
                response = await client.get(url, params=params)
                logger.info(f"[RoutePlanner] 高德响应状态: {response.status_code}")
                response.raise_for_status()
                data = response.json()
            
            logger.info(f"[RoutePlanner] 高德响应: status={data.get('status')}, info={data.get('info')}")
            
            if data.get("status") != "1":
                error_msg = data.get("info", "未知错误")
                logger.error(f"[RoutePlanner] 步行路线规划失败: {error_msg}")
                raise RoutePlanningError(f"步行路线规划失败: {error_msg}")
            
            route = data.get("route", {})
            paths = route.get("paths", [])
            
            logger.info(f"[RoutePlanner] 路径数: {len(paths)}")
            
            if not paths:
                logger.error(f"[RoutePlanner] 步行路线规划无结果")
                raise RoutePlanningError("步行路线规划无结果")
            
            best_path = paths[0]
            
            # 增强的polyline兜底逻辑
            polyline = self._extract_polyline_from_response(best_path)
            
            steps = []
            for step in best_path.get("steps", []):
                instruction = step.get("instruction", "")
                if instruction:
                    steps.append(instruction)
            
            result = RouteResult(
                polyline=polyline,
                distance=float(best_path.get("distance", 0)),
                duration=int(best_path.get("duration", 0)),
                steps=steps,
                traffic_segments=[],
                overall_traffic="smooth"
            )
            
            logger.info(f"[RoutePlanner] _plan_walking完成: distance={result.distance}m, duration={result.duration}s")
            return result
            
        except RoutePlanningError:
            raise
        except Exception as e:
            logger.error(f"[RoutePlanner] _plan_walking异常: {str(e)}, 堆栈: {traceback.format_exc()}")
            raise RoutePlanningError(f"步行路线规划失败: {str(e)}")

    async def _plan_walking_with_waypoints(self, origin: str, waypoints_str: str) -> RouteResult:
        """使用分段方式规划步行路线（支持waypoints）"""
        waypoints_list = waypoints_str.split(";")
        all_steps = []
        total_distance = 0
        total_duration = 0
        
        current_origin = origin
        polylines = []
        
        for i, waypoint in enumerate(waypoints_list):
            logger.info(f"步行分段规划: {i+1}/{len(waypoints_list)}, {current_origin} -> {waypoint}")
            
            try:
                result = await self._plan_walking(current_origin, waypoint, "")
                
                all_steps.extend(result.steps)
                total_distance += result.distance
                total_duration += result.duration
                if result.polyline:
                    polylines.append(result.polyline)
                    
                current_origin = waypoint
                
            except Exception as e:
                logger.warning(f"步行分段 {i+1} 失败: {e}")
                continue
        
        # 合并所有polyline
        final_polyline = ";".join(polylines) if polylines else ""
        
        return RouteResult(
            polyline=final_polyline,
            distance=total_distance,
            duration=total_duration,
            steps=all_steps,
            traffic_segments=[],
            overall_traffic="smooth"
        )

    def _extract_polyline_from_response(self, path_data: dict) -> str:
        """
        从响应中提取polyline
        
        修复：严格校验polyline有效性，禁止降级为直线连接
        """
        polyline = path_data.get("polyline", "")
        
        # 优先使用总polyline
        if polyline and len(polyline) >= 10:
            # 验证格式：应包含分号分隔的多个坐标点
            parts = polyline.split(";")
            if len(parts) >= 2:
                logger.info(f"[RoutePlanner] 使用总polyline，包含 {len(parts)} 个坐标段")
                return polyline
            else:
                logger.warning(f"[RoutePlanner] 总polyline格式异常，只有 {len(parts)} 段")
        
        # 如果总polyline无效，从steps拼接
        logger.warning("[RoutePlanner] 总polyline无效，尝试从steps拼接")
        steps_data = path_data.get("steps", [])
        polylines = []
        for step in steps_data:
            step_polyline = step.get("polyline", "")
            if step_polyline and len(step_polyline) > 5:
                polylines.append(step_polyline)
        
        if polylines:
            polyline = ";".join(polylines)
            logger.info(f"[RoutePlanner] 从steps拼接polyline成功，长度: {len(polyline)}")
            return polyline
        
        # 最终兜底：抛出异常，禁止降级为直线
        logger.error("[RoutePlanner] 高德未返回有效polyline，无法生成真实道路路线")
        raise RoutePlanningError("高德未返回有效路线坐标，请检查API参数或减少途经点")

    async def _plan_transit(self, origin: str, destination: str) -> RouteResult:
        """公交路线规划"""
        url = f"{self.base_url}/direction/transit/integrated"
        params = {
            "key": self.key,
            "origin": origin,
            "destination": destination,
            "city": "上海",
            "strategy": 0,
            "output": "JSON"
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        
        if data.get("status") != "1":
            raise RoutePlanningError(f"公交路线规划失败: {data.get('info', '未知错误')}")
        
        route = data.get("route", {})
        transits = route.get("transits", [])
        
        if not transits:
            raise RoutePlanningError("公交路线规划无结果")
        
        best = transits[0]
        
        steps = []
        for segment in best.get("segments", []):
            # 步行段
            walking = segment.get("walking", {})
            if walking:
                for step in walking.get("steps", []):
                    instruction = step.get("instruction", "")
                    if instruction:
                        steps.append(instruction)
            
            # 公交段
            bus = segment.get("bus", {})
            buslines = bus.get("buslines", [])
            for busline in buslines:
                name = busline.get("name", "")
                departure = busline.get("departure_stop", {}).get("name", "")
                arrival = busline.get("arrival_stop", {}).get("name", "")
                steps.append(f"乘坐{name}，从{departure}到{arrival}")
        
        return RouteResult(
            polyline="",  # 公交路线通常没有连续polyline
            distance=float(best.get("distance", 0)),
            duration=int(best.get("duration", 0)),
            steps=steps,
            traffic_segments=[],
            overall_traffic="smooth"
        )

    def _parse_traffic_segments(self, tmcs: list) -> list[TrafficSegment]:
        """解析交通拥堵段"""
        segments = []
        current_segment = None
        
        for i, tmc in enumerate(tmcs):
            status_code = tmc.get("tmc_status", "0")
            try:
                status_int = int(status_code)
            except (ValueError, TypeError):
                status_int = 0
            
            status_map = {
                0: "smooth",
                1: "smooth",
                2: "slow",
                3: "congested",
                4: "blocked"
            }
            
            status_name = status_map.get(status_int, "smooth")
            road_name = tmc.get("road_name", "") or f"路段{i+1}"
            
            if current_segment is None or current_segment.status != status_name:
                if current_segment:
                    segments.append(current_segment)
                
                current_segment = TrafficSegment(
                    start_index=i,
                    end_index=i,
                    status=status_name,
                    road_name=road_name
                )
            else:
                current_segment.end_index = i
        
        if current_segment:
            segments.append(current_segment)
        
        return segments

    def _determine_overall_traffic(self, traffic_segments: list) -> str:
        """确定整体交通状况"""
        if not traffic_segments:
            return "smooth"
        
        priority_order = ["blocked", "congested", "slow", "smooth"]
        worst_status = "smooth"
        
        for segment in traffic_segments:
            if segment.status in priority_order:
                status_idx = priority_order.index(segment.status)
                worst_idx = priority_order.index(worst_status)
                if status_idx < worst_idx:
                    worst_status = segment.status
        
        return worst_status


# 单例
_route_planner: Optional[RoutePlanner] = None


def get_route_planner() -> RoutePlanner:
    """获取路线规划器单例"""
    global _route_planner
    if _route_planner is None:
        _route_planner = RoutePlanner()
    return _route_planner
