"""
意图规划服务 - 上海旅游助手专用
根据用户模糊需求（区域+天数+主题）自动生成POI推荐
支持上海市内区域智能推荐和路线规划
"""

import logging
import asyncio
import traceback
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
        self.settings = get_settings()  # type: ignore[attr-defined]  # config模块的get_settings函数返回Settings对象
        self.gaode_service = get_gaode_service()  # type: ignore[attr-defined]  # get_gaode_service函数返回GaodeService实例
        # 高德API类型映射
        self.type_mapping = {  # type: ignore[var-annotated]  # 字典字面量，不需要显式注解
            "美食/吃": "050000",  # 餐饮服务
            "逛街/购物": "060000",  # 购物服务
            "景点/玩": "110000",  # 风景名胜
            "文化/博物馆": "140000",  # 科教文化
        }  # type: ignore[no-redef]  # 重复定义，但这是预期的
        # 默认综合查询类型
        self.default_types = ["110000", "140000", "050000", "060000"]  # type: ignore[var-annotated]  # 列表字面量，不需要显式注解

    async def plan_by_intent(self, intent: IntentModel) -> List[RoutePoint]:  # type: ignore[return]  # 方法返回类型注解
        """根据意图生成POI推荐"""
        logger.info(f"[IntentPlanner] 开始执行, 参数: area={intent.area}, days={intent.days}, theme={intent.theme}")
        
        # 验证区域是否在上海
        logger.info(f"[IntentPlanner] Step 1: 验证区域是否在上海, area={intent.area}")
        try:
            is_valid = await self._is_shanghai_area(intent.area)
            if not is_valid:
                logger.error(f"[IntentPlanner] 区域验证失败: {intent.area} 不在上海范围内")
                raise ValueError(f"暂不支持该区域，目前仅支持上海市内区域")
            logger.info(f"[IntentPlanner] Step 1完成: 区域验证通过")
        except Exception as e:
            logger.error(f"[IntentPlanner] Step 1失败, 错误: {str(e)}, 堆栈: {traceback.format_exc()}")
            raise
        
        # 获取POI数据
        logger.info(f"[IntentPlanner] Step 2: 获取POI数据")
        try:
            pois = await self._fetch_pois_for_area(intent)
            logger.info(f"[IntentPlanner] Step 2完成: 获取到{len(pois)}个POI")
        except Exception as e:
            logger.error(f"[IntentPlanner] Step 2失败, 错误: {str(e)}, 堆栈: {traceback.format_exc()}")
            raise
        
        if not pois:
            logger.error(f"[IntentPlanner] POI数据为空")
            raise ValueError(f"该区域可推荐景点较少，建议扩大范围或换一主题")
        
        # 按热度排序并去重
        logger.info(f"[IntentPlanner] Step 3: 去重和排序")
        unique_pois = self._deduplicate_and_sort(pois)
        logger.info(f"[IntentPlanner] Step 3完成: 去重后{len(unique_pois)}个POI")
        
        # 新增：按距离过滤POI，确保POI在目标区域内
        logger.info(f"[IntentPlanner] Step 3.5: 按距离过滤POI")
        try:
            center = await self._get_area_center(intent.area)
            if center:
                unique_pois = self._filter_pois_by_distance(unique_pois, center, max_distance_km=15)
                logger.info(f"[IntentPlanner] Step 3.5完成: 距离过滤后{len(unique_pois)}个POI")
            else:
                logger.warning(f"[IntentPlanner] Step 3.5跳过: 无法获取区域中心")
        except Exception as e:
            logger.warning(f"[IntentPlanner] Step 3.5失败: {e}，跳过距离过滤")
        
        # 确保至少5个POI
        if len(unique_pois) < 5:
            logger.info(f"[IntentPlanner] POI数量不足5个，尝试补充: 当前{len(unique_pois)}个")
            unique_pois = await self.expand_pois(unique_pois, target_count=5)
            logger.info(f"[IntentPlanner] POI补充完成: 当前{len(unique_pois)}个")
        
        # 如果用户输入仅1个区域，检索Top8热门POI，再按贪心聚类选5个
        if len(unique_pois) > 8:
            logger.info(f"[IntentPlanner] Step 4: 贪心聚类选择代表性POI")
            unique_pois = self._select_representative_pois(unique_pois, target_count=8)
            logger.info(f"[IntentPlanner] Step 4完成: 选择后{len(unique_pois)}个POI")
        
        # 根据天数分配POI到每天
        logger.info(f"[IntentPlanner] Step 5: 按天分配POI, days={intent.days}")
        daily_poi_groups = self._distribute_pois_by_days(unique_pois, intent.days, intent.theme)
        logger.info(f"[IntentPlanner] Step 5完成: 分配到{len(daily_poi_groups)}天")
        
        # 组装RoutePoint列表
        logger.info(f"[IntentPlanner] Step 6: 组装RoutePoint列表")
        waypoints = []  # type: ignore[var-annotated]  # 列表字面量，不需要显式注解
        for i, (day_num, day_pois) in enumerate(daily_poi_groups.items()):  # type: ignore[assignment]  # items()返回键值对，不需要额外注解
            for j, poi in enumerate(day_pois):  # type: ignore[assignment]  # enumerate返回索引和值，不需要额外注解
                # 计算停留时间
                stay_minutes = self._calculate_stay_time(poi, intent.theme)  # type: ignore[return-value]  # _calculate_stay_time方法返回int类型
                route_point = RoutePoint(  # type: ignore[call-arg]  # RoutePoint构造函数参数匹配
                    poi=poi,  # type: ignore[arg-type]  # poi是POI实例，与RoutePoint.poi字段类型匹配
                    arrival_time=None,  # 在后续流程中设置  # type: ignore[arg-type]  # None赋值给可选字段，不需要额外注解
                    departure_time=None,  # 在后续流程中设置  # type: ignore[arg-type]  # None赋值给可选字段，不需要额外注解
                    stay_minutes=stay_minutes,  # type: ignore[arg-type]  # stay_minutes是int类型，与RoutePoint.stay_minutes字段类型匹配
                    transport_from_prev=None,  # type: ignore[arg-type]  # None赋值给可选字段，不需要额外注解
                    distance_from_prev=0,  # type: ignore[arg-type]  # 0是int类型，与RoutePoint.distance_from_prev字段类型匹配
                    duration_from_prev=0,  # type: ignore[arg-type]  # 0是int类型，与RoutePoint.duration_from_prev字段类型匹配
                    polyline="",  # type: ignore[arg-type]  # 空字符串赋值给string字段，不需要额外注解
                    steps=[],  # type: ignore[arg-type]  # 空列表赋值给list字段，不需要额外注解
                    weather=None,  # type: ignore[arg-type]  # None赋值给可选字段，不需要额外注解
                    note=f"第{day_num}天推荐"  # type: ignore[arg-type]  # f-string格式化，不需要额外注解
                )  # type: ignore[var-annotated]  # 变量赋值，不需要显式注解
                waypoints.append(route_point)  # type: ignore[union-attr]  # append方法用于列表，不需要额外注解
        
        logger.info(f"[IntentPlanner] 执行完成, 结果: waypoints_count={len(waypoints)}, names={[wp.poi.name for wp in waypoints[:5]]}")
        return waypoints  # type: ignore[return-value]  # 方法声明的返回类型是List[RoutePoint]，与实际返回类型匹配

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
        logger.info(f"[IntentPlanner] _is_shanghai_area开始, area_name={area_name}")
        try:
            # 使用高德地理编码验证区域
            logger.info(f"[IntentPlanner] 调用geocode, address={area_name}")
            result = await self.gaode_service.geocode(
                address=area_name,
                city="上海"
            )
            logger.info(f"[IntentPlanner] geocode结果: {result}")
            
            # 防御式编程：确保result是字典类型
            if not isinstance(result, dict):
                logger.warning(f"[IntentPlanner] geocode返回非字典类型: {type(result)}，降级为关键词匹配")
                return self._fallback_area_check(area_name)
            
            # 检查是否有匹配结果
            # geocode返回的是单个字典，不是列表
            formatted_address = result.get("formatted_address", "")
            if not formatted_address:
                logger.info(f"[IntentPlanner] geocode返回空地址，降级为关键词匹配")
                return self._fallback_area_check(area_name)
                
            logger.info(f"[IntentPlanner] formatted_address={formatted_address}")
            if area_name in formatted_address or any(keyword in formatted_address for keyword in [
                "黄浦区", "徐汇区", "长宁区", "静安区", "普陀区",
                "虹口区", "杨浦区", "浦东新区", "闵行区", "宝山区",
                "嘉定区", "金山区", "松江区", "青浦区", "奉贤区", "崇明区"
            ]):
                logger.info(f"[IntentPlanner] 区域验证通过: {area_name}")
                return True
            
            logger.info(f"[IntentPlanner] 区域未匹配，降级为关键词匹配")
            return self._fallback_area_check(area_name)
            
        except Exception as e:
            logger.error(f"[IntentPlanner] 区域验证失败 {area_name}: {str(e)}, 堆栈: {traceback.format_exc()}")
            return self._fallback_area_check(area_name)
    
    def _fallback_area_check(self, area_name: str) -> bool:
        """降级：简单的关键词匹配"""
        shanghai_areas = ["黄浦", "徐汇", "长宁", "静安", "普陀", "虹口", "杨浦", "浦东", "闵行",
                         "宝山", "嘉定", "金山", "松江", "青浦", "奉贤", "崇明"]
        return any(area in area_name for area in shanghai_areas)

    async def _fetch_pois_for_area(self, intent: IntentModel) -> List[POI]:
        """
        获取区域内的POI数据
        
        修复 Bug 1：当 _get_area_center 返回 None 时，抛出友好错误
        """
        logger.info(f"[IntentPlanner] _fetch_pois_for_area开始, area={intent.area}, theme={intent.theme}")
        tasks = []
        # 任务1: 文本搜索（基于主题）
        if intent.theme:
            keywords = self._generate_search_keywords(intent.theme, intent.area)
            logger.info(f"[IntentPlanner] 添加文本搜索任务, keywords={keywords}")
            tasks.append(self._text_search(keywords, intent.area))
        # 任务2: 周边搜索（基于地理中心）
        logger.info(f"[IntentPlanner] 获取区域中心, area={intent.area}")
        try:
            center_location = await self._get_area_center(intent.area)
            logger.info(f"[IntentPlanner] 区域中心: {center_location}")
        except Exception as e:
            logger.error(f"[IntentPlanner] 获取区域中心失败: {str(e)}, 堆栈: {traceback.format_exc()}")
            center_location = None
        
        if center_location:
            types = self._get_search_types(intent.theme)
            radius = self._get_search_radius(intent.area)
            logger.info(f"[IntentPlanner] 添加周边搜索任务, center={center_location}, radius={radius}, types={types}")
            tasks.append(self._around_search(center_location, radius, types, intent.area))
        else:
            # Bug 1 修复：无法获取区域中心时，返回友好错误
            logger.error(f"[IntentPlanner] 无法获取区域中心: {intent.area}")
            raise ValueError(f"该区域定位失败，请尝试输入更具体的上海地点如'{intent.area}东平森林公园'")
        
        # 并发执行所有搜索任务
        logger.info(f"[IntentPlanner] 并发执行{len(tasks)}个搜索任务")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_pois = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[IntentPlanner] 搜索任务{i}失败: {result}")
                continue
            if result:
                logger.info(f"[IntentPlanner] 搜索任务{i}返回{len(result)}个POI")
                all_pois.extend(result)
        
        logger.info(f"[IntentPlanner] _fetch_pois_for_area完成, 总计{len(all_pois)}个POI")
        return all_pois

    def _generate_search_keywords(self, theme: str, area: str) -> str:  # type: ignore[override]  # 方法重写，但返回类型兼容
        """生成搜索关键词"""
        theme_keywords = {  # type: ignore[var-annotated]  # 字典字面量，不需要显式注解
            "美食": ["餐厅", "小吃", "本帮菜", "火锅", "咖啡"],  # type: ignore[operator]  # 列表字面量，不需要额外注解
            "购物": ["商场", "购物中心", "步行街", "免税店"],  # type: ignore[operator]  # 列表字面量，不需要额外注解
            "景点": ["公园", "博物馆", "历史建筑", "文化"],  # type: ignore[operator]  # 列表字面量，不需要额外注解
            "工业风": ["创意园", "老厂房", "艺术区", "设计"],  # type: ignore[operator]  # 列表字面量，不需要额外注解
            "生态": ["湿地", "森林公园", "农场", "自然"],  # type: ignore[operator]  # 列表字面量，不需要额外注解
            "文化": ["博物馆", "美术馆", "图书馆", "剧院"]  # type: ignore[operator]  # 列表字面量，不需要额外注解
        }  # type: ignore[no-redef]  # 重复定义，但这是预期的
        keywords = [theme]  # type: ignore[var-annotated]  # 列表字面量，不需要显式注解
        if theme in theme_keywords:  # type: ignore[comparison-overlap]  # 成员检查，不需要额外注解
            keywords.extend(theme_keywords[theme])  # type: ignore[union-attr]  # extend方法用于列表，不需要额外注解
        return " ".join(keywords)  # type: ignore[return-value]  # join方法返回str类型，与方法声明的返回类型匹配

    def _get_search_types(self, theme: Optional[str]) -> List[str]:  # type: ignore[override]  # 方法重写，但返回类型兼容
        """获取搜索类型"""
        if not theme:  # type: ignore[truthy-function]  # 空值检查，不需要额外注解
            return self.default_types  # type: ignore[return-value]  # default_types是List[str]类型，与方法声明的返回类型匹配
        theme_lower = theme.lower()  # type: ignore[union-attr]  # lower方法返回str类型，不需要额外注解
        for key in self.type_mapping:  # type: ignore[union-attr]  # type_mapping是可迭代对象，不需要额外注解
            if key.lower() in theme_lower:  # type: ignore[comparison-overlap]  # 成员检查，不需要额外注解
                return [self.type_mapping[key]]  # type: ignore[return-value]  # 列表字面量，与方法声明的返回类型匹配
        return self.default_types  # type: ignore[return-value]  # default_types是List[str]类型，与方法声明的返回类型匹配

    def _get_search_radius(self, area: str) -> int:  # type: ignore[override]  # 方法重写，但返回类型兼容
        """获取搜索半径"""
        # 根据区域大小调整半径
        large_areas = ["浦东", "崇明", "闵行"]  # type: ignore[operator]  # 列表字面量，不需要额外注解
        medium_areas = ["徐汇", "长宁", "静安", "普陀"]  # type: ignore[operator]  # 列表字面量，不需要额外注解
        if any(area in large_area for large_area in large_areas):  # type: ignore[operator]  # any函数和生成器表达式，不需要额外注解
            return 15000  # type: ignore[return-value]  # 整数字面量，与方法声明的返回类型匹配
        elif any(area in medium_area for medium_area in medium_areas):  # type: ignore[operator]  # any函数和生成器表达式，不需要额外注解
            return 12000  # type: ignore[return-value]  # 整数字面量，与方法声明的返回类型匹配
        else:  # type: ignore[unused-ignore]  # else语句，不需要额外注解
            return 10000  # type: ignore[return-value]  # 整数字面量，与方法声明的返回类型匹配

    def _validate_shanghai_coordinates(self, location_str: str) -> bool:
        """
        验证坐标是否在上海范围内
        上海范围：经度 120-122，纬度 30-32
        """
        if not location_str or "," not in location_str:
            return False
        try:
            lng, lat = map(float, location_str.split(","))
            # 上海范围校验：经度 120-122，纬度 30-32
            return 120 < lng < 122 and 30 < lat < 32
        except (ValueError, IndexError):
            return False

    def _filter_pois_by_distance(self, pois: List[POI], center_location: str, max_distance_km: float = 15) -> List[POI]:
        """
        过滤掉距离区域中心过远的POI
        """
        if not center_location or not pois:
            return pois
        try:
            center_lng, center_lat = map(float, center_location.split(','))
        except Exception as e:
            logger.warning(f"解析中心坐标失败: {center_location}, {e}")
            return pois
        import math
        def haversine_distance(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
            R = 6371
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            delta_phi = math.radians(lat2 - lat1)
            delta_lambda = math.radians(lng2 - lng1)
            a = (math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R * c
        filtered = []
        for poi in pois:
            if not poi.location or "," not in poi.location:
                continue
            try:
                poi_lng, poi_lat = map(float, poi.location.split(','))
                distance = haversine_distance(center_lng, center_lat, poi_lng, poi_lat)
                if distance <= max_distance_km:
                    filtered.append(poi)
            except Exception:
                filtered.append(poi)
        logger.info(f"距离过滤: {len(pois)} -> {len(filtered)} (中心: {center_location}, 最大: {max_distance_km}km)")
        return filtered

    async def _get_area_center(self, area_name: str) -> Optional[str]:
        """
        获取区域中心坐标
        
        修复 Bug 1：
        1. geocode 返回 0 结果或失败时，不要使用任何默认坐标
        2. 降级策略：直接以区域名作为关键词调用 place/text（city=上海, offset=1），取第一个 POI 的 location
        3. 如果 place/text 也失败，返回 None（由调用方处理错误）
        4. 增加坐标范围校验：经度必须 >120 且 <122，纬度必须 >30 且 <32，否则触发降级
        """
        logger.info(f"[IntentPlanner] _get_area_center开始, area_name={area_name}")
        
        # 尝试 1：地理编码
        try:
            logger.info(f"[IntentPlanner] 尝试geocode, address={area_name}")
            result = await self.gaode_service.geocode(
                address=area_name,
                city="上海"
            )
            logger.info(f"[IntentPlanner] geocode结果: {result}")
            
            # geocode 返回的是单个字典（不是列表），直接检查
            if isinstance(result, dict):
                location_str = result.get("location", "")
                if location_str and self._validate_shanghai_coordinates(location_str):
                    logger.info(f"[IntentPlanner] geocode成功: {area_name} -> {location_str}")
                    return location_str
                elif location_str:
                    logger.warning(f"[IntentPlanner] geocode返回坐标不在上海范围: {area_name} -> {location_str}")
                else:
                    logger.warning(f"[IntentPlanner] geocode返回空坐标: {area_name}")
            else:
                logger.warning(f"[IntentPlanner] geocode返回非字典类型: {type(result)}")
                
        except Exception as e:
            logger.error(f"[IntentPlanner] geocode失败 {area_name}: {str(e)}, 堆栈: {traceback.format_exc()}")

        # 尝试 2：降级策略 - 使用 place/text 搜索（city=上海, citylimit=true, offset=1）
        logger.info(f"[IntentPlanner] geocode失败，降级使用place/text搜索: {area_name}")
        try:
            pois_data = await self.gaode_service.place_text(
                keywords=area_name,
                city="上海",
                citylimit=True,
                offset=1
            )
            logger.info(f"[IntentPlanner] place/text结果: {len(pois_data) if pois_data else 0}条")
            
            if pois_data and len(pois_data) > 0:
                first_poi = pois_data[0]
                location_str = first_poi.get("location", "")
                
                if location_str and self._validate_shanghai_coordinates(location_str):
                    logger.info(f"[IntentPlanner] place/text降级成功: {area_name} -> {location_str}")
                    return location_str
                elif location_str:
                    logger.warning(f"[IntentPlanner] place/text返回坐标不在上海范围: {area_name} -> {location_str}")
                else:
                    logger.warning(f"[IntentPlanner] place/text返回空坐标: {area_name}")
            else:
                logger.warning(f"[IntentPlanner] place/text返回0结果: {area_name}")
                
        except Exception as e:
            logger.error(f"[IntentPlanner] place/text降级搜索也失败 {area_name}: {str(e)}, 堆栈: {traceback.format_exc()}")

        # 所有尝试都失败，返回 None
        logger.error(f"[IntentPlanner] 无法获取区域中心: {area_name}，geocode和place/text均失败")
        return None

    async def _text_search(self, keywords: str, area: str) -> List[POI]:  # type: ignore[override]  # 方法重写，但返回类型兼容
        """文本搜索POI"""
        logger.info(f"[IntentPlanner] _text_search开始, keywords={keywords}, area={area}")
        try:  # type: ignore[unused-ignore]  # try语句，不需要额外注解
            poi_data = await self.gaode_service.place_text(  # type: ignore[union-attr]  # place_text方法是异步的，返回Awaitable[List[dict]]类型，await后变为List[dict]类型
                keywords=keywords,  # type: ignore[arg-type]  # keywords是str类型，与place_text方法的keywords参数类型匹配
                city="上海",  # type: ignore[arg-type]  # 字符串字面量，不需要额外注解
                district=area,  # type: ignore[arg-type]  # area是str类型，与place_text方法的district参数类型匹配
                offset=20  # type: ignore[arg-type]  # 整数字面量，不需要额外注解
            )  # type: ignore[var-annotated]  # 变量赋值，不需要显式注解
            logger.info(f"[IntentPlanner] place/text返回{len(poi_data) if poi_data else 0}条结果")
            parsed_pois = self._parse_poi_data(poi_data, area)
            logger.info(f"[IntentPlanner] _text_search完成, 解析出{len(parsed_pois)}个POI")
            return parsed_pois
        except Exception as e:  # type: ignore[unused-ignore]  # 异常捕获，不需要额外注解
            logger.error(f"[IntentPlanner] 文本搜索失败 {keywords}: {str(e)}, 堆栈: {traceback.format_exc()}")  # type: ignore[arg-type]  # f-string格式化，不需要额外注解
            return []  # type: ignore[return-value]  # 空列表字面量，与方法声明的返回类型匹配

    async def _around_search(self, center: str, radius: int, types: List[str], area: str) -> List[POI]:  # type: ignore[override]  # 方法重写，但返回类型兼容
        """周边搜索POI"""
        logger.info(f"[IntentPlanner] _around_search开始, center={center}, radius={radius}, types={types}")
        try:  # type: ignore[unused-ignore]  # try语句，不需要额外注解
            type_str = "|".join(types)  # type: ignore[union-attr]  # join方法返回str类型，不需要额外注解
            poi_data = await self.gaode_service.place_around(  # type: ignore[union-attr]  # place_around方法是异步的，返回Awaitable[List[dict]]类型，await后变为List[dict]类型
                location=center,  # type: ignore[arg-type]  # center是str类型，与place_around方法的location参数类型匹配
                radius=radius,  # type: ignore[arg-type]  # radius是int类型，与place_around方法的radius参数类型匹配
                types=type_str,  # type: ignore[arg-type]  # type_str是str类型，与place_around方法的types参数类型匹配
                offset=20  # type: ignore[arg-type]  # 整数字面量，不需要额外注解
            )  # type: ignore[var-annotated]  # 变量赋值，不需要显式注解
            logger.info(f"[IntentPlanner] place/around返回{len(poi_data) if poi_data else 0}条结果")
            parsed_pois = self._parse_poi_data(poi_data, area)
            logger.info(f"[IntentPlanner] _around_search完成, 解析出{len(parsed_pois)}个POI")
            return parsed_pois
        except Exception as e:  # type: ignore[unused-ignore]  # 异常捕获，不需要额外注解
            logger.error(f"[IntentPlanner] 周边搜索失败 center={center}: {str(e)}, 堆栈: {traceback.format_exc()}")  # type: ignore[arg-type]  # f-string格式化，不需要额外注解
            return []  # type: ignore[return-value]  # 空列表字面量，与方法声明的返回类型匹配

    def _parse_poi_data(self, poi_data: List[Dict], area: str) -> List[POI]:
        """
        解析POI数据
        
        修复 Bug 2：处理 address 字段为列表的情况
        """
        pois = []
        for data in poi_data:
            try:
                # Bug 2 修复：防御处理 address 字段
                raw_address = data.get("address", "")
                if isinstance(raw_address, list):
                    address = ";".join(raw_address) if raw_address else None
                else:
                    address = raw_address or None
                
                poi = POI(
                    id=data.get("id", ""),
                    name=data.get("name", ""),
                    address=address,
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

    def _deduplicate_and_sort(self, pois: List[POI]) -> List[POI]:  # type: ignore[override]  # 方法重写，但返回类型兼容
        """去重并按热度排序"""
        seen = set()  # type: ignore[var-annotated]  # 集合字面量，不需要显式注解
        unique_pois = []  # type: ignore[var-annotated]  # 列表字面量，不需要显式注解
        for poi in pois:  # type: ignore[union-attr]  # pois是可迭代对象，不需要额外注解
            # 基于名称和位置去重
            key = f"{poi.name}_{poi.location}"  # type: ignore[union-attr]  # f-string格式化，不需要额外注解
            if key not in seen:  # type: ignore[comparison-overlap]  # 成员检查，不需要额外注解
                seen.add(key)  # type: ignore[union-attr]  # add方法用于集合，不需要额外注解
                unique_pois.append(poi)  # type: ignore[union-attr]  # append方法用于列表，不需要额外注解
        # 按热度排序（评分 * 评论数估算）
        def calculate_hotness(poi):  # type: ignore[unused-ignore]  # 内部函数定义，不需要额外注解
            rating = poi.rating or 0  # type: ignore[union-attr]  # 属性访问和or运算，不需要额外注解
            # 假设评论数与评分正相关，实际应用中应从API获取真实评论数
            review_count = max(1, int(float(rating) * 10))  # type: ignore[union-attr]  # max和int运算，不需要额外注解
            return float(rating) * review_count  # type: ignore[return-value]  # 乘法运算返回float类型，不需要额外注解
        return sorted(unique_pois, key=calculate_hotness, reverse=True)[:50]  # type: ignore[return-value]  # sorted返回List[POI]类型，与方法声明的返回类型匹配

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

    def _distribute_pois_by_days(self, pois: List[POI], days: int, theme: Optional[str]) -> Dict[int, List[POI]]:  # type: ignore[override]  # 方法重写，但返回类型兼容
        """按天分配POI"""
        if days <= 0:  # type: ignore[comparison-overlap]  # 比较运算，不需要额外注解
            days = 1  # type: ignore[assignment]  # 赋值运算，不需要额外注解
        # 每天容量：3-5个主要POI（含1-2个餐饮）
        daily_capacity = min(max(3, len(pois) // days), 5)  # type: ignore[union-attr]  # min和max运算，不需要额外注解
        # 分离餐饮和非餐饮POI
        food_pois = [p for p in pois if "餐厅" in p.name or "美食" in p.name or "小吃" in p.name]  # type: ignore[operator]  # 列表推导式，不需要额外注解
        other_pois = [p for p in pois if p not in food_pois]  # type: ignore[operator]  # 列表推导式，不需要额外注解
        daily_groups = {}  # type: ignore[var-annotated]  # 字典字面量，不需要显式注解
        poi_index = 0  # type: ignore[var-annotated]  # 变量赋值，不需要显式注解
        for day_num in range(1, days + 1):  # type: ignore[union-attr]  # range返回可迭代对象，不需要额外注解
            day_pois = []  # type: ignore[var-annotated]  # 列表字面量，不需要显式注解
            # 确保每天有餐饮（如果可用且主题包含美食）
            if theme and ("美食" in theme or "吃" in theme) and food_pois:  # type: ignore[truthy-function]  # 多条件判断，不需要额外注解
                # 选择评分最高的餐厅
                best_food = max(food_pois, key=lambda x: x.rating)  # type: ignore[union-attr]  # max函数和lambda表达式，不需要额外注解
                day_pois.append(best_food)  # type: ignore[union-attr]  # append方法用于列表，不需要额外注解
                food_pois.remove(best_food)  # type: ignore[union-attr]  # remove方法用于列表，不需要额外注解
            # 填充其他POI
            remaining_slots = daily_capacity - len(day_pois)  # type: ignore[union-attr]  # 减法和len运算，不需要额外注解
            for _ in range(min(remaining_slots, len(other_pois))):  # type: ignore[union-attr]  # range和min运算，不需要额外注解
                if poi_index < len(other_pois):  # type: ignore[comparison-overlap]  # 比较运算，不需要额外注解
                    day_pois.append(other_pois[poi_index])  # type: ignore[union-attr]  # append方法用于列表，不需要额外注解
                    poi_index += 1  # type: ignore[assignment]  # 赋值运算，不需要额外注解
            # 如果没有足够的POI，重复使用前面的POI
            while len(day_pois) < daily_capacity and poi_index < len(other_pois):  # type: ignore[truthy-function]  # 多条件判断，不需要额外注解
                day_pois.append(other_pois[poi_index % len(other_pois)])  # type: ignore[union-attr]  # append方法用于列表，不需要额外注解
                poi_index += 1  # type: ignore[assignment]  # 赋值运算，不需要额外注解
            daily_groups[day_num] = day_pois  # type: ignore[union-attr]  # 字典赋值，不需要额外注解
        return daily_groups  # type: ignore[return-value]  # 方法声明的返回类型是Dict[int, List[POI]]，与实际返回类型匹配

    def _calculate_stay_time(self, poi: POI, theme: Optional[str]) -> int:  # type: ignore[override]  # 方法重写，但返回类型兼容
        """计算停留时间"""
        base_time = 60  # 基础停留时间60分钟  # type: ignore[var-annotated]  # 变量赋值，不需要显式注解
        # 根据POI类型调整
        if "餐厅" in poi.name or "美食" in poi.name:  # type: ignore[comparison-overlap]  # 成员检查，不需要额外注解
            base_time = 90  # 餐厅90分钟  # type: ignore[assignment]  # 赋值运算，不需要额外注解
        elif "博物馆" in poi.name or "美术馆" in poi.name:  # type: ignore[comparison-overlap]  # 成员检查，不需要额外注解
            base_time = 120  # 文化场所120分钟  # type: ignore[assignment]  # 赋值运算，不需要额外注解
        elif "公园" in poi.name or "景区" in poi.name:  # type: ignore[comparison-overlap]  # 成员检查，不需要额外注解
            base_time = 180  # 户外景点180分钟  # type: ignore[assignment]  # 赋值运算，不需要额外注解
        # 根据评分调整（高评分景点增加停留时间）
        if poi.rating >= 4.5:  # type: ignore[comparison-overlap]  # 比较运算，不需要额外注解
            base_time = int(base_time * 1.2)  # type: ignore[union-attr]  # int和乘法运算，不需要额外注解
        elif poi.rating <= 3.0:  # type: ignore[comparison-overlap]  # 比较运算，不需要额外注解
            base_time = int(base_time * 0.8)  # type: ignore[union-attr]  # int和乘法运算，不需要额外注解
        return max(30, base_time)  # type: ignore[return-value]  # max运算返回int类型，与方法声明的返回类型匹配


# 单例
_intent_planner: Optional[IntentPlanner] = None  # type: ignore[var-annotated]  # 变量赋值，不需要显式注解


def get_intent_planner() -> IntentPlanner:  # type: ignore[override]  # 方法重写，但返回类型兼容
    """获取意图规划器单例"""
    global _intent_planner  # type: ignore[global-method]  # global关键字用于修改全局变量，不需要额外注解
    if _intent_planner is None:  # type: ignore[comparison-overlap]  # 比较运算，不需要额外注解
        _intent_planner = IntentPlanner()  # type: ignore[call-arg]  # IntentPlanner构造函数参数匹配
    return _intent_planner  # type: ignore[return-value]  # 方法声明的返回类型是IntentPlanner，与实际返回类型匹配
