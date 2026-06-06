"""
沿途POI发现服务
基于真实polyline采样，搜索路线两侧的POI
"""

import logging
import math
from typing import Optional
import httpx
import asyncio
from cachetools import TTLCache

from config import get_settings
from models.base import POI
from models.route import EnroutePOI
from exceptions import GaodeAPIError

logger = logging.getLogger(__name__)

# 缓存：5分钟过期，最多500条
_search_cache: TTLCache = TTLCache(maxsize=500, ttl=300)


class EnrouteDiscoveryService:
    """沿途POI发现服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.key = self.settings.gaode_key
        self.base_url = "https://restapi.amap.com/v3"
        self.timeout = 10.0
        # POI类型：餐饮/购物/景点/文化
        self.search_types = "050000|060000|110000|140000"
        # 基础采样间隔（米）
        self.sample_interval = 1500
        # 最小采样间隔（米）
        self.min_sample_interval = 2500
        # 搜索半径（米）
        self.search_radius = 800
        # 最大结果数
        self.max_results = 6
        # 最大采样点数
        self.max_sample_points = 15
        # 请求延迟（秒）
        self.request_delay = 0.3
        # 最大并发数
        self.max_concurrent = 3

    async def discover_enroute_pois(
        self,
        polyline: str,
        main_pois: list[str],
        max_results: int = 6
    ) -> list[EnroutePOI]:
        """
        发现沿途POI
        
        Args:
            polyline: 路线polyline编码字符串
            main_pois: 主POI名称列表（用于去重）
            max_results: 最大返回结果数
            
        Returns:
            list[EnroutePOI]: 沿途发现的POI列表
        """
        self.max_results = max_results
        
        # 1. 解析polyline获取坐标点
        coordinates = self._decode_polyline(polyline)
        if not coordinates:
            logger.warning("polyline解析失败，无法发现沿途POI")
            return []
        
        logger.info(f"polyline解析完成: 共{len(coordinates)}个坐标点")
        
        # 2. 动态调整采样间隔并采样
        total_distance = self._calculate_total_distance(coordinates)
        adjusted_interval = self._adjust_sample_interval(total_distance)
        sample_points = self._sample_by_distance(coordinates, adjusted_interval)
        
        # 限制最大采样点数
        if len(sample_points) > self.max_sample_points:
            sample_points = self._reduce_sample_points(sample_points, self.max_sample_points)
        
        logger.info(f"总距离: {total_distance:.1f}km, 调整后采样间隔: {adjusted_interval}m, 采样点数量: {len(sample_points)}")
        
        # 3. 对每个采样点进行周边搜索（带缓存和限流）
        all_pois = await self._search_with_rate_limit(sample_points)
        
        logger.info(f"初步搜索结果: {len(all_pois)}个POI")
        
        # 4. 过滤和排序
        filtered_pois = self._filter_and_sort(all_pois, sample_points, main_pois)
        
        logger.info(f"沿途POI发现完成: 最终{len(filtered_pois)}个")
        return filtered_pois[:max_results]

    def _decode_polyline(self, polyline: str) -> list[tuple[float, float]]:
        """
        解码高德polyline字符串
        
        高德polyline格式: "lng1,lat1;lng2,lat2;..."
        """
        coordinates = []
        if not polyline:
            return coordinates
        
        try:
            points = polyline.split(";")
            for point in points:
                if "," in point:
                    lng, lat = point.split(",")
                    coordinates.append((float(lng), float(lat)))
        except Exception as e:
            logger.error(f"polyline解码失败: {e}")
        
        return coordinates

    def _calculate_total_distance(self, coordinates: list[tuple[float, float]]) -> float:
        """计算polyline总距离（千米）"""
        if len(coordinates) < 2:
            return 0.0
        
        total_distance = 0.0
        for i in range(1, len(coordinates)):
            prev = coordinates[i - 1]
            curr = coordinates[i]
            distance = self._haversine_distance(prev[0], prev[1], curr[0], curr[1])
            total_distance += distance
        
        return total_distance / 1000  # 转换为千米

    def _adjust_sample_interval(self, total_distance_km: float) -> int:
        """根据路线长度动态调整采样间隔"""
        if total_distance_km <= 5:
            return self.sample_interval  # 短路线保持原间隔
        elif total_distance_km <= 15:
            return max(self.sample_interval, self.min_sample_interval // 2)
        else:
            return self.min_sample_interval  # 长路线增大间隔

    def _reduce_sample_points(self, sample_points: list[tuple[float, float]], max_points: int) -> list[tuple[float, float]]:
        """减少采样点数量到指定最大值"""
        if len(sample_points) <= max_points:
            return sample_points
        
        # 均匀采样
        step = len(sample_points) / max_points
        reduced_points = []
        for i in range(max_points):
            index = int(i * step)
            if index < len(sample_points):
                reduced_points.append(sample_points[index])
        
        # 确保包含起点和终点
        if reduced_points[0] != sample_points[0]:
            reduced_points.insert(0, sample_points[0])
        if reduced_points[-1] != sample_points[-1]:
            reduced_points.append(sample_points[-1])
        
        return reduced_points

    def _sample_by_distance(
        self,
        coordinates: list[tuple[float, float]],
        interval: int
    ) -> list[tuple[float, float]]:
        """
        按累计距离采样坐标点
        
        Args:
            coordinates: 坐标列表
            interval: 采样间隔（米）
            
        Returns:
            采样点列表
        """
        if len(coordinates) < 2:
            return coordinates
        
        sample_points = [coordinates[0]]  # 起点
        accumulated_distance = 0.0
        
        for i in range(1, len(coordinates)):
            prev = coordinates[i - 1]
            curr = coordinates[i]
            
            # 计算两点间距离
            distance = self._haversine_distance(prev[0], prev[1], curr[0], curr[1])
            accumulated_distance += distance
            
            # 达到采样间隔时取点
            if accumulated_distance >= interval:
                sample_points.append(curr)
                accumulated_distance = 0.0
        
        # 确保终点被包含
        if sample_points[-1] != coordinates[-1]:
            sample_points.append(coordinates[-1])
        
        return sample_points

    def _haversine_distance(
        self,
        lng1: float,
        lat1: float,
        lng2: float,
        lat2: float
    ) -> float:
        """
        计算两点间的Haversine距离（米）
        """
        R = 6371000  # 地球半径（米）
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_phi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c

    async def _search_with_rate_limit(self, sample_points: list[tuple[float, float]]) -> list[dict]:
        """带速率限制的周边搜索"""
        tasks = []
        for point in sample_points:
            cache_key = f"{point[0]:.6f},{point[1]:.6f}"
            if cache_key not in _search_cache:
                tasks.append(self._search_around_point(point))
        
        if not tasks:
            logger.info("所有采样点搜索都在缓存中")
            return []
        
        logger.info(f"开始周边搜索: {len(tasks)}个采样点")
        
        # 分批处理，每批最多3个请求
        batch_size = self.max_concurrent
        all_results = []
        
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            batch_results = await self._process_batch(batch)
            all_results.extend(batch_results)
            
            # 批次间延迟 - 增加延迟以减少请求频率
            if i + batch_size < len(tasks):
                logger.info(f"等待 {self.request_delay}s 以避免QPS限制...")
                await asyncio.sleep(self.request_delay)
        
        logger.info(f"完成周边搜索: 共{len(all_results)}个POI")
        
        logger.info(f"周边搜索完成: 获取到{len(all_results)}个POI")
        return all_results

    async def _search_around_point(
        self,
        point: tuple[float, float]
    ) -> list[dict]:
        """
        对单个采样点进行周边搜索
        """
        url = f"{self.base_url}/place/around"
        location = f"{point[0]},{point[1]}"
        params = {
            "key": self.key,
            "location": location,
            "radius": self.search_radius,
            "types": self.search_types,
            "offset": 10,
            "page": 1,
            "extensions": "all",
            "output": "JSON"
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
            
            if data.get("status") == "1":
                return data.get("pois", [])
            else:
                logger.warning(f"周边搜索失败: {data.get('info', '未知错误')}")
                return []
        except Exception as e:
            logger.warning(f"周边搜索异常: {e}")
            return []

    async def _process_batch(self, tasks: list) -> list[dict]:
        """处理一批搜索任务"""
        results = []
        
        async def limited_search(task):
            try:
                result = await task
                if result:
                    return result
                return []
            except Exception as e:
                logger.warning(f"搜索任务异常: {e}")
                return []
        
        # 限制并发数
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def bounded_task(task):
            async with semaphore:
                return await limited_search(task)
        
        batch_results = await asyncio.gather(*[bounded_task(task) for task in tasks])
        
        for result in batch_results:
            if result:
                results.extend(result)
        
        return results

    def _filter_and_sort(
        self,
        pois: list[dict],
        sample_points: list[tuple[float, float]],
        main_pois: list[str]
    ) -> list[EnroutePOI]:
        """
        过滤和排序POI
        
        过滤规则：
        1. 剔除与主POI名称相似度>0.6的
        2. 剔除距离采样点>500米的
        3. 按 rating * log(review_count+1) 排序
        """
        filtered = []
        seen_ids = set()
        
        for poi_data in pois:
            poi_id = poi_data.get("id", "")
            poi_name = poi_data.get("name", "")
            poi_location = poi_data.get("location", "")
            
            # 去重
            if poi_id in seen_ids:
                continue
            seen_ids.add(poi_id)
            
            # 检查与主POI的相似度
            if self._is_similar_to_main(poi_name, main_pois):
                continue
            
            # 检查距离采样点的距离
            if not self._is_near_route(poi_location, sample_points, max_distance=500):
                continue
            
            # 解析POI
            try:
                rating = float(poi_data.get("biz_ext", {}).get("rating", 0) or 0)
                review_count = int(poi_data.get("biz_ext", {}).get("review_count", 0) or 0)
                
                # 计算热度分数
                hotness_score = rating * math.log(review_count + 1) if review_count > 0 else rating
                
                # 计算距离路线的最近距离
                distance_from_route = self._calculate_distance_to_route(
                    poi_location, sample_points
                )
                
                enroute_poi = EnroutePOI(
                    id=poi_id,
                    name=poi_name,
                    address=poi_data.get("address", ""),
                    location=poi_location,
                    city="上海",
                    district=poi_data.get("adname", ""),
                    type=poi_data.get("type", ""),
                    rating=rating,
                    open_time=poi_data.get("biz_ext", {}).get("open_time"),
                    distance_from_route=distance_from_route,
                    reviews=[]
                )
                
                # 附加排序分数（不在模型中，用于排序）
                enroute_poi._hotness_score = hotness_score
                filtered.append(enroute_poi)
                
            except Exception as e:
                logger.warning(f"POI解析失败: {poi_name}, {e}")
                continue
        
        # 按热度排序
        filtered.sort(key=lambda x: x._hotness_score, reverse=True)
        
        return filtered

    def _is_similar_to_main(self, poi_name: str, main_pois: list[str]) -> bool:
        """
        检查POI名称是否与主POI相似
        相似度>0.6返回True
        """
        for main_name in main_pois:
            similarity = self._calculate_similarity(poi_name, main_name)
            if similarity > 0.6:
                return True
        return False

    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """
        计算两个名称的相似度（Jaccard相似度）
        """
        if not name1 or not name2:
            return 0.0
        
        set1 = set(name1)
        set2 = set(name2)
        
        intersection = set1 & set2
        union = set1 | set2
        
        if not union:
            return 0.0
        
        return len(intersection) / len(union)

    def _is_near_route(
        self,
        poi_location: str,
        sample_points: list[tuple[float, float]],
        max_distance: float
    ) -> bool:
        """
        检查POI是否在路线附近
        """
        if not poi_location:
            return False
        
        try:
            lng, lat = poi_location.split(",")
            poi_lng, poi_lat = float(lng), float(lat)
        except Exception:
            return False
        
        for point in sample_points:
            distance = self._haversine_distance(poi_lng, poi_lat, point[0], point[1])
            if distance <= max_distance:
                return True
        
        return False

    def _calculate_distance_to_route(
        self,
        poi_location: str,
        sample_points: list[tuple[float, float]]
    ) -> float:
        """
        计算POI到路线的最近距离
        """
        if not poi_location or not sample_points:
            return float("inf")
        
        try:
            lng, lat = poi_location.split(",")
            poi_lng, poi_lat = float(lng), float(lat)
        except Exception:
            return float("inf")
        
        min_distance = float("inf")
        for point in sample_points:
            distance = self._haversine_distance(poi_lng, poi_lat, point[0], point[1])
            min_distance = min(min_distance, distance)
        
        return min_distance

    def calculate_insertion_index(
        self,
        enroute_poi: EnroutePOI,
        main_points: list[POI],
        polyline: str
    ) -> int:
        """
        计算沿途POI建议插入位置
        
        Args:
            enroute_poi: 沿途POI
            main_points: 主POI列表
            polyline: 路线polyline
            
        Returns:
            int: 建议插入到第几个主POI之后
        """
        if not main_points or not enroute_poi.location:
            return 0
        
        # 解析沿途POI坐标
        try:
            lng, lat = enroute_poi.location.split(",")
            poi_lng, poi_lat = float(lng), float(lat)
        except Exception:
            return 0
        
        # 解析polyline
        coordinates = self._decode_polyline(polyline)
        if not coordinates:
            return 0
        
        # 找到距离沿途POI最近的polyline点
        min_distance = float("inf")
        nearest_index = 0
        
        for i, coord in enumerate(coordinates):
            distance = self._haversine_distance(poi_lng, poi_lat, coord[0], coord[1])
            if distance < min_distance:
                min_distance = distance
                nearest_index = i
        
        # 根据最近点在polyline中的位置，判断应在哪个主POI之后
        # 简化处理：根据nearest_index占总polyline的比例，映射到主POI索引
        if len(coordinates) > 0 and len(main_points) > 1:
            ratio = nearest_index / len(coordinates)
            insertion_index = int(ratio * (len(main_points) - 1))
            return max(0, min(insertion_index, len(main_points) - 1))
        
        return 0


# 单例
_enroute_discovery: Optional[EnrouteDiscoveryService] = None


def get_enroute_discovery() -> EnrouteDiscoveryService:
    """获取沿途POI发现服务单例"""
    global _enroute_discovery
    if _enroute_discovery is None:
        _enroute_discovery = EnrouteDiscoveryService()
    return _enroute_discovery
