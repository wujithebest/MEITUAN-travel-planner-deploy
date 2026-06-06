"""
意图规划服务 - 上海旅游助手专用
根据用户模糊需求（区域+天数+主题）自动生成POI推荐
支持上海市内区域智能推荐和路线规划
"""

import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import date
import httpx

from config import get_settings
from models.base import POI
from models.route import RoutePoint
from services.gaode_service import get_gaode_service

logger = logging.getLogger(__name__)


class IntentModel:
    """意图模型"""
    def __init__(self, area: str, days: int = 1, theme: Optional[str] = None, 
                 preferences: Optional[str] = None, district_code: Optional[str] = None):
        self.area = area
        self.days = days
        self.theme = theme
        self.preferences = preferences
        self.district_code = district_code


class IntentPlanner:
    """意图规划器 - 根据区域、天数、主题生成POI推荐"""
    def __init__(self) -> None:
        self.settings = get_settings()
        self.gaode_service = get_gaode_service()
        # 高德API类型映射
        self.type_mapping = {
            "美食/吃": "050000",  # 餐饮服务
            "逛街/购物": "060000",  # 购物服务
            "景点/玩": "110000",  # 风景名胜
            "文化/博物馆": "140000",  # 科教文化
        }
        # 默认综合查询类型
        self.default_types = ["110000", "140000", "050000", "060000"]

    async def plan_by_intent(self, intent: IntentModel) -> List[RoutePoint]:
        """根据意图生成POI推荐"""
        logger.info(f"开始意图规划: {intent.area}, {intent.days}天, 主题: {intent.theme}")
        # 验证区域是否在上海
        if not await self._is_shanghai_area(intent.area):
            raise ValueError(f"暂不支持该区域，目前仅支持上海市内区域")
        # 获取POI数据
        pois = await self._fetch_pois_for_area(intent)
        if not pois:
            raise ValueError(f"该区域可推荐景点较少，建议扩大范围或换一主题")
        # 按热度排序并去重
        unique_pois = self._deduplicate_and_sort(pois)
        
        # 确保至少5个POI
        if len(unique_pois) < 5:
            logger.info(f"POI数量不足5个，尝试补充: 当前{len(unique_pois)}个")
            unique_pois = await self.expand_pois(unique_pois, target_count=5)
        
        # 如果用户输入仅1个区域，检索Top8热门POI，再按贪心聚类选5个
        if len(unique_pois) > 8:
            unique_pois = self._select_representative_pois(unique_pois, target_count=8)
        
        # 根据天数分配POI到每天
        daily_poi_groups = self._distribute_pois_by_days(unique_pois, intent.days, intent.theme)
        # 组装RoutePoint列表
        waypoints = []
        for i, (day_num, day_pois) in enumerate(daily_poi_groups.items()):
            for j, poi in enumerate(day_pois):
                # 计算停留时间
                stay_minutes = self._calculate_stay_time(poi, intent.theme)
                route_point = RoutePoint(
                    poi=poi,
                    arrival_time=None,
                    departure_time=None,
                    stay_minutes=stay_minutes,
                    transport_from_prev=None,
                    distance_from_prev=0,
                    duration_from_prev=0,
                    polyline="",
                    steps=[],
                    weather=None,
                    note=f"第{day_num}天推荐"
                )
                waypoints.append(route_point)
        logger.info(f"意图规划完成: 共推荐 {len(waypoints)} 个POI")
        return waypoints

    def _select_representative_pois(self, pois: List[POI], target_count: int = 8) -> List[POI]:
        """
        贪心聚类选择最具代表性的POI
        
        基于地理分布和评分，选择覆盖范围广且评分高的POI
        
        Args:
            pois: POI列表
            target_count: 目标数量
            
        Returns:
            List[POI]: 选中的POI列表
        """
        if len(pois) <= target_count:
            return pois
        
        import math
        
        def haversine_distance(loc1: str, loc2: str) -> float:
            """计算两点间距离（米）"""
            if not loc1 or not loc2:
                return float("inf")
            try:
                lng1, lat1 = map(float, loc1.split(","))
                lng2, lat2 = map(float, loc2.split(","))
            except Exception:
                return float("inf")
            
            R = 6371000
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            delta_phi = math.radians(lat2 - lat1)
            delta_lambda = math.radians(lng2 - lng1)
            
            a = (math.sin(delta_phi / 2) ** 2 +
                 math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            
            return R * c
        
        # 贪心选择：每次选择距离已选点最远且评分高的点
        selected = [pois[0]]  # 先选评分最高的
        remaining = pois[1:]
        
        while len(selected) < target_count and remaining:
            best_score = -1
            best_idx = 0
            
            for i, poi in enumerate(remaining):
                # 计算到已选点的最小距离
                min_dist = min(
                    haversine_distance(poi.location, s.location)
                    for s in selected
                )
                
                # 分数 = 距离权重 * 距离 + 评分权重 * 评分
                score = min_dist * 0.6 + (poi.rating or 0) * 1000 * 0.4
                
                if score > best_score:
                    best_score = score
                    best_idx = i
            
            selected.append(remaining.pop(best_idx))
        
        return selected

    async def _is_shanghai_area(self, area_name: str) -> bool:
        """验证区域是否在上海"""
        try:
            # 使用高德地理编码验证区域
            result = await self.gaode_service.geocode(
                address=area_name,
                city="上海"
            )
            
            # 防御式编程：确保result是字典类型
            if not isinstance(result, dict):
                logger.warning(f"geocode返回非字典类型: {type(result)}，降级为关键词匹配")
                return self._fallback_area_check(area_name)
            
            # 检查是否有匹配结果
            # geocode返回的是单个字典，不是列表
            formatted_address = result.get("formatted_address", "")
            if not formatted_address:
                return self._fallback_area_check(area_name)
                
            if area_name in formatted_address or any(keyword in formatted_address for keyword in [
                "黄浦区", "徐汇区", "长宁区", "静安区", "普陀区",
                "虹口区", "杨浦区", "浦东新区", "闵行区", "宝山区",
                "嘉定区", "金山区", "松江区", "青浦区", "奉贤区", "崇明区"
            ]):
                return True
            
            return self._fallback_area_check(area_name)
            
        except Exception as e:
            logger.warning(f"区域验证失败 {area_name}: {e}")
            return self._fallback_area_check(area_name)
    
    def _fallback_area_check(self, area_name: str) -> bool:
        """降级：简单的关键词匹配"""
        shanghai_areas = ["黄浦", "徐汇", "长宁", "静安", "普陀", "虹口", "杨浦", "浦东", "闵行",
                         "宝山", "嘉定", "金山", "松江", "青浦", "奉贤", "崇明"]
        return any(area in area_name for area in shanghai_areas)

    async def _fetch_pois_for_area(self, intent: IntentModel) -> List[POI]:
        """获取区域内的POI数据"""
        tasks = []
        # 任务1: 文本搜索（基于主题）
        if intent.theme:
            keywords = self._generate_search_keywords(intent.theme, intent.area)
            tasks.append(self._text_search(keywords, intent.area))
        # 任务2: 周边搜索（基于地理中心）
        center_location = await self._get_area_center(intent.area)
        if center_location:
            types = self._get_search_types(intent.theme)
            radius = self._get_search_radius(intent.area)
            tasks.append(self._around_search(center_location, radius, types, intent.area))
        # 并发执行所有搜索任务
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_pois = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"搜索任务失败: {result}")
                continue
            if result:
                all_pois.extend(result)
        return all_pois

    def _generate_search_keywords(self, theme: str, area: str) -> str:
        """生成搜索关键词"""
        theme_keywords = {
            "美食": ["餐厅", "小吃", "本帮菜", "火锅", "咖啡"],
            "购物": ["商场", "购物中心", "步行街", "免税店"],
            "景点": ["公园", "博物馆", "历史建筑", "文化"],
            "工业风": ["创意园", "老厂房", "艺术区", "设计"],
            "生态": ["湿地", "森林公园", "农场", "自然"],
            "文化": ["博物馆", "美术馆", "图书馆", "剧院"]
        }
        keywords = [theme]
        if theme in theme_keywords:
            keywords.extend(theme_keywords[theme])
        return " ".join(keywords)

    def _get_search_types(self, theme: Optional[str]) -> List[str]:
        """获取搜索类型"""
        if not theme:
            return self.default_types
        theme_lower = theme.lower()
        for key in self.type_mapping:
            if key.lower() in theme_lower:
                return [self.type_mapping[key]]
        return self.default_types

    def _get_search_radius(self, area: str) -> int:
        """获取搜索半径"""
        # 根据区域大小调整半径
        large_areas = ["浦东", "崇明", "闵行"]
        medium_areas = ["徐汇", "长宁", "静安", "普陀"]
        if any(area in large_area for large_area in large_areas):
            return 15000
        elif any(area in medium_area for medium_area in medium_areas):
            return 12000
        else:
            return 10000

    async def _get_area_center(self, area_name: str) -> Optional[str]:
        """获取区域中心坐标"""
        try:
            # 使用地理编码获取区域中心
            result = await self.gaode_service.geocode(
                address=area_name,
                city="上海"
            )
            
            # 防御式编程：确保正确处理不同类型的返回值
            if not result:
                logger.warning(f"geocode返回空结果: {area_name}")
                return None
            
            if isinstance(result, list):
                # geocode返回的是列表格式
                if len(result) == 0:
                    logger.warning(f"geocode返回空列表: {area_name}")
                    return None
                
                # 确保第一个元素是字典类型再调用get方法
                first_result = result[0]
                if isinstance(first_result, dict):
                    location_str = first_result.get("location", "")
                else:
                    # 如果第一个元素是字符串，直接返回
                    location_str = str(first_result)
                
                if location_str:
                    return location_str
                    
            elif isinstance(result, dict):
                # geocode返回的是单个字典格式
                location_str = result.get("location", "")
                if location_str:
                    return location_str
                    
            else:
                # 其他类型，尝试转换为字符串
                location_str = str(result)
                if location_str and location_str != "None":
                    return location_str
                    
            # 返回默认中心点（如区域行政中心）
            default_centers = {
                "杨浦": "121.5228,31.2746",
                "浦东": "121.5446,31.2294",
                "崇明": "121.4039,31.6232",
                "徐汇": "121.4365,31.1879",
                "长宁": "121.4148,31.2192",
                "静安": "121.4523,31.2296",
                "普陀": "121.4089,31.2486",
                "虹口": "121.4942,31.2648",
                "黄浦": "121.4896,31.2347",
                "闵行": "121.3817,31.1171",
                "宝山": "121.4886,31.4086",
                "嘉定": "121.2547,31.3769",
                "金山": "121.3425,30.7425",
                "松江": "121.2274,31.0307",
                "青浦": "121.1149,31.1522",
                "奉贤": "121.4634,30.9173"
            }
            return default_centers.get(area_name, "121.4896,31.2347")
        except Exception as e:
            logger.warning(f"获取区域中心失败 {area_name}: {e}")
            return None

    async def _text_search(self, keywords: str, area: str) -> List[POI]:
        """文本搜索POI"""
        try:
            poi_data = await self.gaode_service.place_text(
                keywords=keywords,
                city="上海",
                district=area,
                offset=20
            )
            return self._parse_poi_data(poi_data, area)
        except Exception as e:
            logger.error(f"文本搜索失败 {keywords}: {e}")
            return []

    async def _around_search(self, center: str, radius: int, types: List[str], area: str) -> List[POI]:
        """周边搜索POI"""
        try:
            type_str = "|".join(types)
            poi_data = await self.gaode_service.place_around(
                location=center,
                radius=radius,
                types=type_str,
                offset=20
            )
            return self._parse_poi_data(poi_data, area)
        except Exception as e:
            logger.error(f"周边搜索失败 center={center}: {e}")
            return []

    def _parse_poi_data(self, poi_data: List[Dict], area: str) -> List[POI]:
        """解析POI数据"""
        pois = []
        for data in poi_data:
            try:
                poi = POI(
                    id=data.get("id", ""),
                    name=data.get("name", ""),
                    address=data.get("address", ""),
                    location=data.get("location", ""),
                    city="上海",
                    district=area,
                    type=data.get("type", ""),
                    rating=float(data.get("biz_ext", {}).get("rating", 0) or 0),
                    open_time=data.get("open_time"),
                    close_time=data.get("close_time"),
                    ambiguity=False,
                    duration_minutes=60
                )
                pois.append(poi)
            except Exception as e:
                logger.warning(f"解析POI失败: {data.get('name', 'Unknown')}: {e}")
                continue
        return pois

    def _deduplicate_and_sort(self, pois: List[POI]) -> List[POI]:
        """去重并按热度排序"""
        seen = set()
        unique_pois = []
        for poi in pois:
            # 基于名称和位置去重
            key = f"{poi.name}_{poi.location}"
            if key not in seen:
                seen.add(key)
                unique_pois.append(poi)
        # 按热度排序（评分 * 评论数估算）
        def calculate_hotness(poi):
            rating = poi.rating or 0
            # 假设评论数与评分正相关，实际应用中应从API获取真实评论数
            review_count = max(1, int(float(rating) * 10))
            return float(rating) * review_count
        return sorted(unique_pois, key=calculate_hotness, reverse=True)[:50]

    async def expand_pois(self, existing_pois: List[POI], target_count: int = 5) -> List[POI]:
        """
        补充POI到目标数量
        
        基于已有地点的地理中心，调用高德周边搜索补充POI
        
        Args:
            existing_pois: 已有POI列表
            target_count: 目标数量（默认5个）
            
        Returns:
            List[POI]: 补充后的POI列表
        """
        if len(existing_pois) >= target_count:
            return existing_pois
        
        logger.info(f"需要补充POI: 当前{len(existing_pois)}个，目标{target_count}个")
        
        # 计算地理中心
        center = self._calculate_center(existing_pois)
        if not center:
            logger.warning("无法计算地理中心，无法补充POI")
            return existing_pois
        
        # 根据已有POI类型推断搜索类型
        search_types = self._infer_search_types(existing_pois)
        
        # 调用高德周边搜索
        try:
            poi_data = await self.gaode_service.place_around(
                location=center,
                radius=3000,
                types=search_types,
                offset=20
            )
            
            # 解析POI数据
            new_pois = self._parse_poi_data(poi_data, "")
            
            # 去重（基于名称）
            existing_names = {poi.name for poi in existing_pois}
            unique_new_pois = [p for p in new_pois if p.name not in existing_names]
            
            # 按距离+评分排序
            unique_new_pois.sort(key=lambda p: (p.rating or 0), reverse=True)
            
            # 补充到目标数量
            needed = target_count - len(existing_pois)
            expanded_pois = existing_pois + unique_new_pois[:needed]
            
            logger.info(f"POI补充完成: 从{len(existing_pois)}个扩展到{len(expanded_pois)}个")
            return expanded_pois
            
        except Exception as e:
            logger.warning(f"补充POI失败: {e}")
            return existing_pois

    def _calculate_center(self, pois: List[POI]) -> Optional[str]:
        """计算POI列表的地理中心"""
        if not pois:
            return None
        
        total_lng = 0.0
        total_lat = 0.0
        count = 0
        
        for poi in pois:
            if poi.location and "," in poi.location:
                try:
                    lng, lat = poi.location.split(",")
                    total_lng += float(lng)
                    total_lat += float(lat)
                    count += 1
                except Exception:
                    continue
        
        if count == 0:
            return None
        
        center_lng = total_lng / count
        center_lat = total_lat / count
        return f"{center_lng},{center_lat}"

    def _infer_search_types(self, pois: List[POI]) -> str:
        """根据已有POI类型推断搜索类型"""
        # 统计已有POI类型
        type_count = {}
        for poi in pois:
            if poi.type:
                if "风景名胜" in poi.type or "旅游景点" in poi.type:
                    type_count["景点"] = type_count.get("景点", 0) + 1
                elif "餐厅" in poi.type or "美食" in poi.type:
                    type_count["餐饮"] = type_count.get("餐饮", 0) + 1
                elif "购物" in poi.type or "商场" in poi.type:
                    type_count["购物"] = type_count.get("购物", 0) + 1
                elif "博物馆" in poi.type or "文化" in poi.type:
                    type_count["文化"] = type_count.get("文化", 0) + 1
        
        # 如果已有3个景点，补充餐饮/购物
        if type_count.get("景点", 0) >= 3:
            return "050000|060000"  # 餐饮+购物
        
        # 默认综合搜索
        return "110000|140000|050000|060000"  # 景点+文化+餐饮+购物

    def _distribute_pois_by_days(self, pois: List[POI], days: int, theme: Optional[str]) -> Dict[int, List[POI]]:
        """按天分配POI"""
        if days <= 0:
            days = 1
        # 每天容量：3-5个主要POI（含1-2个餐饮）
        daily_capacity = min(max(3, len(pois) // days), 5)
        # 分离餐饮和非餐饮POI
        food_pois = [p for p in pois if "餐厅" in p.name or "美食" in p.name or "小吃" in p.name]
        other_pois = [p for p in pois if p not in food_pois]
        daily_groups = {}
        poi_index = 0
        for day_num in range(1, days + 1):
            day_pois = []
            # 确保每天有餐饮（如果可用且主题包含美食）
            if theme and ("美食" in theme or "吃" in theme) and food_pois:
                # 选择评分最高的餐厅
                best_food = max(food_pois, key=lambda x: x.rating)
                day_pois.append(best_food)
                food_pois.remove(best_food)
            # 填充其他POI
            remaining_slots = daily_capacity - len(day_pois)
            for _ in range(min(remaining_slots, len(other_pois))):
                if poi_index < len(other_pois):
                    day_pois.append(other_pois[poi_index])
                    poi_index += 1
            # 如果没有足够的POI，重复使用前面的POI
            while len(day_pois) < daily_capacity and poi_index < len(other_pois):
                day_pois.append(other_pois[poi_index % len(other_pois)])
                poi_index += 1
            daily_groups[day_num] = day_pois
        return daily_groups

    def _calculate_stay_time(self, poi: POI, theme: Optional[str]) -> int:
        """计算停留时间"""
        base_time = 60  # 基础停留时间60分钟
        # 根据POI类型调整
        if "餐厅" in poi.name or "美食" in poi.name:
            base_time = 90  # 餐厅90分钟
        elif "博物馆" in poi.name or "美术馆" in poi.name:
            base_time = 120  # 文化场所120分钟
        elif "公园" in poi.name or "景区" in poi.name:
            base_time = 180  # 户外景点180分钟
        # 根据评分调整（高评分景点增加停留时间）
        if poi.rating >= 4.5:
            base_time = int(base_time * 1.2)
        elif poi.rating <= 3.0:
            base_time = int(base_time * 0.8)
        return max(30, base_time)


# 单例
_intent_planner: Optional[IntentPlanner] = None


def get_intent_planner() -> IntentPlanner:
    """获取意图规划器单例"""
    global _intent_planner
    if _intent_planner is None:
        _intent_planner = IntentPlanner()
    return _intent_planner
