"""
高德地图API服务
封装地点搜索、地理编码、路线规划等功能
支持缓存、超时控制、分段规划
"""

import logging
from typing import Optional
import httpx
from cachetools import TTLCache

from config import get_settings, DISTRICT_ADMCODES
from models.base import POI, POIPhoto, POIChild, TransportMode, WeatherInfo
from exceptions import GaodeAPIError, POINotFoundError, RoutePlanningError, OutOfShanghaiError

logger = logging.getLogger(__name__)

# 上海行政区划代码
SHANGHAI_ADMCODE = "310000"

# 上海坐标范围常量
SHANGHAI_LNG_MIN = 120
SHANGHAI_LNG_MAX = 122
SHANGHAI_LAT_MIN = 30
SHANGHAI_LAT_MAX = 32

# POI缓存：24小时过期，最多1000条
_poi_cache: TTLCache = TTLCache(maxsize=1000, ttl=86400)
# 路线缓存：30分钟过期，最多200条
_route_cache: TTLCache = TTLCache(maxsize=200, ttl=1800)



def _safe_str(value) -> Optional[str]:
    """
    安全转换为字符串
    处理高德API可能返回空列表[]的情况
    """
    if value is None:
        return None
    if isinstance(value, list):
        # 空列表返回None
        if len(value) == 0:
            return None
        # 非空列表用分号连接
        return ";".join(str(x) for x in value if x)
    if isinstance(value, str):
        return value.strip() if value.strip() else None
    # 其他类型转换为字符串
    return str(value) if value else None


class GaodeService:
    """高德地图API服务封装"""

    def __init__(self):
        self.settings = get_settings()
        self.key = self.settings.gaode_key
        self.base_url = "https://restapi.amap.com/v3"
        self.timeout = 10.0

    async def place_text(
        self,
        keywords: str,
        city: str = "",
        citylimit: bool = False,
        offset: int = 10,
        page: int = 1,
        district: str = ""
    ) -> list[dict]:
        """
        地点文本搜索（POI搜索）
        city 非空且 citylimit=True 时才限定城市范围
        """
        url = f"{self.base_url}/place/text"
        params = {
            "key": self.key,
            "keywords": keywords,
            "city": city,
            "offset": offset,
            "page": page,
            "extensions": "all",
            "output": "JSON"
        }
        if city and citylimit:
            params["citylimit"] = "true"
        if district and district in DISTRICT_ADMCODES:
            params["adcode"] = DISTRICT_ADMCODES[district]
        elif district:
            params["city"] = district

        logger.info(f"高德POI搜索: keywords={keywords}, city={city or '全国'}, citylimit={citylimit}, district={district}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1":
            error_msg = data.get("info", "未知错误")
            logger.error(f"高德POI搜索失败: {error_msg}")
            raise GaodeAPIError(f"POI搜索失败: {error_msg}")

        return data.get("pois", [])

    async def geocode(self, address: str, city: str = "") -> dict:
        """
        地理编码（地址转坐标）
        city 为空时全国搜索
        """
        url = f"{self.base_url}/geocode/geo"
        params = {
            "key": self.key,
            "address": address,
            "city": city,
            "output": "JSON"
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1" or not data.get("geocodes"):
            raise GaodeAPIError(f"地理编码失败: {address}")

        return data["geocodes"][0]

    async def regeocode(self, location: str) -> dict:
        """逆地理编码（坐标转地址）"""
        url = f"{self.base_url}/geocode/regeo"
        params = {
            "key": self.key,
            "location": location,
            "output": "JSON"
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1":
            raise GaodeAPIError(f"逆地理编码失败: {location}")

        return data.get("regeocode", {})

    async def direction_driving(
        self,
        origin: str,
        destination: str,
        waypoints: str = "",
        strategy: int = 0
    ) -> dict:
        """驾车路线规划"""
        url = f"{self.base_url}/direction/driving"
        params = {
            "key": self.key,
            "origin": origin,
            "destination": destination,
            "strategy": strategy,
            "extensions": "all",
            "output": "JSON"
        }
        if waypoints:
            params["waypoints"] = waypoints

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1":
            error_msg = data.get("info", "未知错误")
            raise RoutePlanningError(f"驾车路线规划失败: {error_msg}")

        return data

    async def direction_walking(self, origin: str, destination: str) -> dict:
        """步行路线规划"""
        url = f"{self.base_url}/direction/walking"
        params = {
            "key": self.key,
            "origin": origin,
            "destination": destination,
            "output": "JSON"
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1":
            raise RoutePlanningError(f"步行路线规划失败: {data.get('info', '未知错误')}")

        return data

    async def direction_transit(
        self, origin: str, destination: str,
        city: str = "上海", cityd: str = "", strategy: int = 0
    ) -> dict:
        """
        公交路线规划 - 仅上海
        强制city="上海"
        """
        url = f"{self.base_url}/direction/transit/integrated"
        params = {
            "key": self.key,
            "origin": origin,
            "destination": destination,
            "city": "上海",  # 强制上海
            "strategy": strategy,  # strategy=10使用实时路况
            "output": "JSON"
        }
        if cityd:
            params["cityd"] = cityd

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1":
            raise RoutePlanningError(f"公交路线规划失败: {data.get('info', '未知错误')}")

        return data

    async def match_poi(self, name: str, city_hint: str = "", district: str = "") -> POI:
        """
        匹配最佳POI，打分排序返回最佳结果
        无结果抛POINotFoundError
        """
        city = city_hint if city_hint and city_hint not in ("上海", "shanghai", "SH") else ""
        cache_key = f"{name}:{district or city or '全国'}"
        if cache_key in _poi_cache:
            logger.info(f"POI缓存命中: {cache_key}")
            return _poi_cache[cache_key]

        pois_data = await self.place_text(keywords=name, city=city, district=district, citylimit=bool(city))

        if not pois_data:
            raise POINotFoundError(f"{name}")

        # 打分排序
        scored_pois = []
        for poi_data in pois_data:
            score = self._score_poi(poi_data, name, city_hint)
            scored_pois.append((score, poi_data))

        scored_pois.sort(key=lambda x: x[0], reverse=True)

        best_poi_data = None
        for score, poi_data in scored_pois:
            location = poi_data.get("location", "")
            if location:
                best_poi_data = poi_data
                logger.info(f"找到POI: {poi_data.get('name')} 坐标={location}")
                break
            else:
                logger.warning(f"跳过非上海坐标的POI: {poi_data.get('name')} 坐标={location}")
        
        # 如果没有找到上海范围内的POI
        if best_poi_data is None:
            error_msg = f"未在上海范围内找到匹配的POI: {name}"
            logger.error(error_msg)
            raise POINotFoundError(error_msg)

        # 处理不同类型的 open_time 值
        raw_open_time = best_poi_data.get("biz_ext", {}).get("open_time", None)
        processed_open_time = self._process_open_time(raw_open_time)
        
        # 提取区域信息
        poi_area = best_poi_data.get("adname", best_poi_data.get("district", ""))
        # 清理区域名称（去除"区"后缀用于匹配）
        district_name = ""
        for d in DISTRICT_ADMCODES.keys():
            if d.replace("区", "") in poi_area or poi_area in d:
                district_name = d
                break

        # Bug 2 修复：防御处理 address 字段
        raw_address = best_poi_data.get("address", "")
        if isinstance(raw_address, list):
            address = ";".join(str(x) for x in raw_address) if raw_address else None
        else:
            address = str(raw_address) if raw_address else None
        
        # 解析扩展字段
        biz_ext = best_poi_data.get("biz_ext", {})
        raw_photos = best_poi_data.get("photos", [])
        
        # 使用 _safe_str 处理可能为空列表的字段
        poi = POI(
            id=best_poi_data.get("id", ""),
            name=best_poi_data.get("name", ""),
            address=address,
            location=best_poi_data.get("location", ""),
            city=best_poi_data.get("cityname", city_hint or ""),
            district=district_name,
            type=best_poi_data.get("type", ""),
            rating=float(biz_ext.get("rating", 0) or 0),
            open_time=processed_open_time,
            duration_minutes=self._estimate_duration(best_poi_data.get("type", "")),
            metro_hint=self._extract_metro_hint(str(raw_address)) if raw_address else "",
            # 扩展字段 - 使用 _safe_str 处理可能为列表的字段
            photos=self._parse_photos(raw_photos),
            price=self._parse_price(biz_ext, best_poi_data),
            tel=_safe_str(best_poi_data.get("tel")),
            website=_safe_str(best_poi_data.get("website")),
            biz_type=_safe_str(best_poi_data.get("biz_type")),
            tag=best_poi_data.get("tag", []),
            indoor=self._check_indoor(best_poi_data.get("type", "")),
            navi_poiid=_safe_str(best_poi_data.get("navi_poiid")),
            entr_location=_safe_str(best_poi_data.get("entr_location")),
            exit_location=_safe_str(best_poi_data.get("exit_location")),
            groupbuynum=self._safe_int(best_poi_data.get("groupbuynum")),
            discountnum=self._safe_int(best_poi_data.get("discountnum")),
            event=_safe_str(best_poi_data.get("event")),
            children=self._parse_children(best_poi_data.get("children", []))
        )

        # 歧义检测：前两名分数接近
        if len(scored_pois) >= 2 and scored_pois[0][0] - scored_pois[1][0] < 0.1:
            poi.ambiguity = True

        _poi_cache[cache_key] = poi
        logger.info(f"POI匹配成功 (上海): {name} -> {poi.name} ({poi.district or '上海'})")
        return poi

    def _extract_metro_hint(self, address: str) -> str:
        """从地址中提取地铁站信息（简化版）"""
        # 常见上海地铁站关键词
        metro_keywords = ["地铁", "轨道交通", "station"]
        for keyword in metro_keywords:
            if keyword in address:
                # 简单提取
                parts = address.split(keyword)
                if len(parts) > 1:
                    return parts[1].strip()[:20]
        return ""

    def _score_poi(self, poi_data: dict, query_name: str, city_hint: str = "上海") -> float:
        """为POI打分 - 上海专用"""
        score = 0.0
        poi_name = poi_data.get("name", "")

        if query_name in poi_name or poi_name in query_name:
            score += 0.4
        elif any(c in poi_name for c in query_name):
            score += 0.2

        # 上海城市匹配（固定为上海）
        poi_city = poi_data.get("cityname", "") or poi_data.get("adname", "")
        if "上海" in poi_city or not poi_city:  # 上海或不显示城市都加分
            score += 0.3

        rating = float(poi_data.get("biz_ext", {}).get("rating", 0) or 0)
        score += min(rating / 5.0 * 0.2, 0.2)

        poi_type = poi_data.get("type", "")
        tourism_keywords = ["风景名胜", "旅游景点", "公园", "博物馆", "寺庙", "景区"]
        if any(kw in poi_type for kw in tourism_keywords):
            score += 0.1

        return score

    def _estimate_duration(self, poi_type: str) -> int:
        """根据POI类型估算游览时长（分钟）"""
        duration_map = {
            "风景名胜": 180,
            "旅游景点": 120,
            "公园广场": 90,
            "博物馆": 120,
            "寺庙": 60,
            "购物中心": 120,
            "餐厅": 60,
            "酒店": 0,
        }
        for key, duration in duration_map.items():
            if key in poi_type:
                return duration
        return 60

    def _process_open_time(self, open_time_value):
        """
        处理高德API返回的open_time字段，支持多种数据类型
        将非字符串类型转换为合适的格式或None
        """
        if not open_time_value:
            return None
        
        # 如果是空列表，返回None
        if isinstance(open_time_value, list) and len(open_time_value) == 0:
            return None
        
        # 如果是列表，用分号连接
        if isinstance(open_time_value, list):
            return ";".join(str(x) for x in open_time_value if x)
            
        # 如果是字符串，直接返回
        if isinstance(open_time_value, str):
            return open_time_value.strip() if open_time_value.strip() else None
            
        # 对于其他类型（数字、字典等），返回None
        return None
    
    def _parse_photos(self, raw_photos: list) -> list[POIPhoto]:
        """解析照片列表，最多返回5张"""
        photos = []
        if not raw_photos or not isinstance(raw_photos, list):
            return photos
        
        for p in raw_photos[:5]:  # 最多5张
            if isinstance(p, dict) and p.get("url"):
                # 使用 _safe_str 处理 title 可能是空列表的情况
                photos.append(POIPhoto(
                    title=_safe_str(p.get("title")),
                    url=p.get("url")
                ))
        return photos
    
    def _parse_price(self, biz_ext: dict, raw_data: dict) -> str | None:
        """解析价格信息"""
        # 优先从biz_ext获取
        cost = biz_ext.get("cost") or biz_ext.get("price")
        if cost:
            # 如果是数字，格式化为人均
            try:
                cost_num = float(cost)
                if cost_num > 0:
                    return f"¥{int(cost_num)}/人"
            except (ValueError, TypeError):
                pass
            # 如果是字符串直接返回
            if isinstance(cost, str) and cost.strip():
                return cost.strip()
        
        # 从顶层获取
        price = raw_data.get("price")
        if price:
            if isinstance(price, (int, float)) and price > 0:
                return f"¥{int(price)}/人"
            elif isinstance(price, str) and price.strip():
                return price.strip()
        
        return None
    
    def _parse_children(self, raw_children: list) -> list[POIChild]:
        """解析子POI列表"""
        children = []
        if not raw_children or not isinstance(raw_children, list):
            return children
        
        for child in raw_children:
            if isinstance(child, dict):
                children.append(POIChild(
                    id=child.get("id", ""),
                    name=child.get("name", ""),
                    location=child.get("location", ""),
                    address=child.get("address"),
                    type=child.get("type", ""),
                    rating=self._safe_float(child.get("biz_ext", {}).get("rating") if isinstance(child.get("biz_ext"), dict) else None)
                ))
        return children
    
    def _check_indoor(self, poi_type: str) -> bool | None:
        """根据POI类型判断是否室内"""
        indoor_keywords = ["室内", "商场", "购物中心", "博物馆", "美术馆", "图书馆", "餐厅", "酒店", "影院", "剧院"]
        outdoor_keywords = ["公园", "景区", "山", "湖", "海", "岛", "古镇", "寺庙", "教堂", "广场"]
        
        for kw in indoor_keywords:
            if kw in poi_type:
                return True
        for kw in outdoor_keywords:
            if kw in poi_type:
                return False
        return None
    
    def _safe_int(self, value) -> int | None:
        """安全转换为整数"""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    
    def _safe_float(self, value) -> float | None:
        """安全转换为浮点数"""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    async def plan_route(
        self,
        points: list[POI],
        transport_mode: TransportMode,
        consider_weather: bool = False,
        weather_info: Optional[list[WeatherInfo]] = None
    ) -> dict:
        """
        规划路线
        超15个分段规划
        返回distance/duration/polyline/steps/traffic_segments/overall_traffic/weather_tip
        """
        if len(points) < 2:
            raise RoutePlanningError("路线规划至少需要2个点")

        if len(points) > 15:
            logger.info(f"POI数量{len(points)}超过15个，分段规划")
            return await self._plan_route_segmented(points, transport_mode)

        origin = points[0].location
        destination = points[-1].location
        waypoints_str = ";".join(p.location for p in points[1:-1]) if len(points) > 2 else ""

        cache_key = f"{origin}:{destination}:{waypoints_str}:{transport_mode.value}"
        if cache_key in _route_cache:
            logger.info("路线缓存命中")
            return _route_cache[cache_key]

        try:
            if transport_mode == TransportMode.DRIVING:
                result = await self.direction_driving(
                    origin, destination,
                    waypoints=waypoints_str,
                    strategy=10
                )
            elif transport_mode == TransportMode.WALKING:
                result = await self.direction_walking(origin, destination)
            elif transport_mode == TransportMode.TRANSIT:
                result = await self.direction_transit(origin, destination, "上海")  # 强制上海
            else:
                result = await self.direction_driving(origin, destination, waypoints_str)
        except RoutePlanningError:
            raise
        except Exception as e:
            logger.error(f"路线规划异常: {str(e)}")
            raise RoutePlanningError(f"路线规划失败: {str(e)}")

        route_data = self._parse_route_result(result, transport_mode)

        if consider_weather and weather_info:
            route_data["weather_tip"] = self._generate_weather_tip(weather_info)

        _route_cache[cache_key] = route_data
        return route_data

    async def _plan_route_segmented(
        self, points: list[POI], transport_mode: TransportMode
    ) -> dict:
        """分段规划路线（超过15个点时）"""
        total_distance = 0
        total_duration = 0
        all_steps = []
        all_polylines = []
        segments_count = 0

        chunk_size = 14
        for i in range(0, len(points) - 1, chunk_size):
            chunk = points[i:i + chunk_size + 1]
            if len(chunk) < 2:
                continue

            origin = chunk[0].location
            destination = chunk[-1].location
            waypoints_str = ";".join(p.location for p in chunk[1:-1]) if len(chunk) > 2 else ""

            try:
                if transport_mode == TransportMode.DRIVING:
                    result = await self.direction_driving(origin, destination, waypoints_str, strategy=10)
                elif transport_mode == TransportMode.WALKING:
                    result = await self.direction_walking(origin, destination)
                else:
                    result = await self.direction_driving(origin, destination, waypoints_str)

                segment_data = self._parse_route_result(result, transport_mode)
                total_distance += segment_data.get("distance", 0)
                total_duration += segment_data.get("duration", 0)
                all_steps.extend(segment_data.get("steps", []))
                all_polylines.extend(segment_data.get("polylines", []))
                segments_count += 1
            except Exception as e:
                logger.warning(f"分段规划失败[{i}:{i+chunk_size}]: {str(e)}")
                continue

        return {
            "distance": total_distance,
            "duration": total_duration,
            "polylines": all_polylines,
            "steps": all_steps,
            "segments": segments_count,
            "traffic_segments": [],
            "overall_traffic": "畅通",
            "weather_tip": ""
        }

    def _parse_route_result(self, result: dict, transport_mode: TransportMode) -> dict:
        """解析高德API返回的路线结果"""
        route = result.get("route", {})

        if transport_mode == TransportMode.TRANSIT:
            transits = route.get("transits", [])
            if not transits:
                return {"distance": 0, "duration": 0, "polylines": [], "steps": [], "traffic_segments": [], "overall_traffic": "畅通", "weather_tip": ""}
            best = transits[0]
            steps = []
            for segment in best.get("segments", []):
                for bus_step in segment.get("bus", {}).get("buslines", []):
                    instruction = bus_step.get("instruction", "")
                    if instruction:
                        steps.append(instruction)
            return {
                "distance": int(best.get("distance", 0)),
                "duration": int(best.get("duration", 0)),
                "polylines": [],
                "steps": steps,
                "traffic_segments": [],
                "overall_traffic": "畅通",
                "weather_tip": ""
            }

        paths = route.get("paths", [])
        if not paths:
            return {"distance": 0, "duration": 0, "polylines": [], "steps": [], "traffic_segments": [], "overall_traffic": "畅通", "weather_tip": ""}

        best_path = paths[0]
        steps = [s.get("instruction", "") for s in best_path.get("steps", []) if s.get("instruction")]

        # 解析交通拥堵信息
        traffic_segments = self._parse_traffic_segments(best_path.get("tmcs", []))

        polyline = best_path.get("polyline", "")

        return {
            "distance": int(best_path.get("distance", 0)),
            "duration": int(best_path.get("duration", 0)),
            "polylines": [polyline] if polyline else [],
            "steps": steps,
            "traffic_segments": traffic_segments,
            "overall_traffic": self._determine_overall_traffic(traffic_segments),
            "weather_tip": ""
        }

    def _parse_traffic_segments(self, tmcs: list) -> list:
        """
        解析交通拥堵段信息
        每个step提取最差的status（0未知/1畅通/2缓行/3拥堵/4严重拥堵）
        返回: list[{start_index, end_index, status, road_name}]
        """
        from models.route import TrafficSegment
        
        segments = []
        current_segment = None
        
        for i, tmc in enumerate(tmcs):
            status_code = tmc.get("tmc_status", "0")
            try:
                status_int = int(status_code)
            except (ValueError, TypeError):
                status_int = 0
            
            # 状态映射到英文
            status_map = {
                0: "smooth",     # 未知 -> 畅通
                1: "smooth",     # 畅通
                2: "slow",       # 缓行
                3: "congested",  # 拥堵
                4: "blocked"     # 严重拥堵
            }
            
            status_name = status_map.get(status_int, "smooth")
            road_name = tmc.get("road_name", "") or f"路段{i+1}"
            
            # 如果是第一个段或状态变化，开始新段
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
                # 延续当前段
                current_segment.end_index = i
        
        # 添加最后一段
        if current_segment:
            segments.append(current_segment)
        
        return segments

    def _determine_overall_traffic(self, traffic_segments: list) -> str:
        """
        确定整体交通状况
        取所有segment最差值：畅通/缓行/拥堵/严重拥堵
        """
        from models.route import TrafficSegment
        
        if not traffic_segments:
            return "smooth"
        
        # 优先级：严重拥堵 > 拥堵 > 缓行 > 畅通
        priority_order = ["blocked", "congested", "slow", "smooth"]
        
        worst_status = "smooth"
        for segment in traffic_segments:
            if segment.status in priority_order:
                status_idx = priority_order.index(segment.status)
                worst_idx = priority_order.index(worst_status)
                if status_idx < worst_idx:
                    worst_status = segment.status
        
        return worst_status

    def _generate_weather_tip(self, weather_info: list[WeatherInfo]) -> str:
        """根据天气信息生成出行提示"""
        tips = []
        for w in weather_info:
            if w.is_rainy:
                tips.append(f"{w.date}有雨，建议携带雨具，优先安排室内活动")
            if w.is_high_temp:
                tips.append(f"{w.date}高温{w.temp_high}℃，注意防暑降温，减少户外活动")
            if w.is_strong_wind:
                tips.append(f"{w.date}风力{w.wind_level}级，注意安全，取消高空项目")
        return "; ".join(tips) if tips else "天气适宜出行"


    async def place_around(
        self,
        location: str,
        radius: int = 3000,
        types: str = "",
        offset: int = 10,
        page: int = 1
    ) -> list[dict]:
        """
        周边搜索POI - 仅上海
        
        Args:
            location: 中心点坐标 "lng,lat"
            radius: 搜索半径（米）
            types: POI类型代码，多个用|分隔
            offset: 每页记录数
            page: 页码
            
        Returns:
            list[dict]: POI列表
        """
        url = f"{self.base_url}/place/around"
        params = {
            "key": self.key,
            "location": location,
            "radius": radius,
            "offset": offset,
            "page": page,
            "extensions": "all",
            "output": "JSON"
        }
        if types:
            params["types"] = types

        logger.info(f"高德周边搜索 (上海): location={location}, radius={radius}, types={types}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1":
            error_msg = data.get("info", "未知错误")
            logger.error(f"高德周边搜索失败: {error_msg}")
            raise GaodeAPIError(f"周边搜索失败: {error_msg}")

        return data.get("pois", [])

    async def get_real_polyline(
        self,
        origin: str,
        destination: str,
        waypoints: str = ""
    ) -> str:
        """
        获取真实道路polyline坐标
        
        强制获取道路级坐标，非直线
        
        Args:
            origin: 起点坐标 "lng,lat"
            destination: 终点坐标 "lng,lat"
            waypoints: 途经点坐标 "lng1,lat1;lng2,lat2;..."
            
        Returns:
            str: polyline编码字符串
        """
        url = f"{self.base_url}/direction/driving"
        params = {
            "key": self.key,
            "origin": origin,
            "destination": destination,
            "strategy": 10,
            "extensions": "all",
            "output": "JSON"
        }
        if waypoints:
            params["waypoints"] = waypoints
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        
        if data.get("status") != "1":
            error_msg = data.get("info", "未知错误")
            raise RoutePlanningError(f"获取polyline失败: {error_msg}")
        
        route = data.get("route", {})
        paths = route.get("paths", [])
        
        if not paths:
            raise RoutePlanningError("获取polyline无结果")
        
        return paths[0].get("polyline", "")


_gaode_service: Optional[GaodeService] = None


def get_gaode_service() -> GaodeService:
    """获取高德服务单例"""
    global _gaode_service
    if _gaode_service is None:
        _gaode_service = GaodeService()
    return _gaode_service
