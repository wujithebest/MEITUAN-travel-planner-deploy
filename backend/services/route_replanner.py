"""
路线重规划服务
将沿途发现的POI并入主路线，重新规划完整真实路线
"""

import logging
from typing import Optional

from models.base import POI, TransportMode
from models.route import EnroutePOI, RoutePoint
from services.route_planner import get_route_planner, RouteResult
from services.enroute_discovery import get_enroute_discovery

logger = logging.getLogger(__name__)


class RouteReplanner:
    """路线重规划器"""
    
    def __init__(self):
        self.route_planner = get_route_planner()
        self.enroute_discovery = get_enroute_discovery()

    async def replan_with_enroute(
        self,
        main_points: list[POI],
        enroute_pois: list[EnroutePOI],
        transport_mode: TransportMode,
        polyline: str = ""
    ) -> tuple[list[RoutePoint], RouteResult]:
        """
        将沿途POI并入主路线，重新规划完整路线
        
        Args:
            main_points: 主POI列表
            enroute_pois: 沿途发现的POI列表
            transport_mode: 交通方式
            polyline: 原始路线polyline（用于计算插入位置）
            
        Returns:
            tuple: (合并后的RoutePoint列表, 新的RouteResult)
        """
        if not enroute_pois:
            logger.info("无沿途POI，跳过重规划")
            # 直接规划主路线
            route_result = await self.route_planner.plan_real_route(main_points, transport_mode)
            route_points = self._create_route_points(main_points, route_result)
            return route_points, route_result
        
        logger.info(f"开始路线重规划: {len(main_points)}个主POI + {len(enroute_pois)}个沿途POI")
        
        # 1. 计算每个沿途POI的插入位置
        enroute_with_index = []
        for enroute_poi in enroute_pois:
            insert_index = self.enroute_discovery.calculate_insertion_index(
                enroute_poi, main_points, polyline
            )
            enroute_with_index.append((insert_index, enroute_poi))
            logger.debug(f"沿途POI '{enroute_poi.name}' 建议插入位置: {insert_index}")
        
        # 2. 按插入位置排序
        enroute_with_index.sort(key=lambda x: x[0])
        
        # 3. 合并主POI和沿途POI
        merged_points = self._merge_points(main_points, enroute_with_index)
        
        logger.info(f"合并后总POI数量: {len(merged_points)}")
        
        # 4. 重新规划完整路线
        route_result = await self.route_planner.plan_real_route(
            [rp.poi for rp in merged_points],
            transport_mode
        )
        
        # 5. 更新RoutePoint的路线信息
        for i, route_point in enumerate(merged_points):
            route_point.polyline = route_result.polyline if i == 0 else ""
            route_point.steps = route_result.steps if i == 0 else []
        
        return merged_points, route_result

    def _merge_points(
        self,
        main_points: list[POI],
        enroute_with_index: list[tuple[int, EnroutePOI]]
    ) -> list[RoutePoint]:
        """
        合并主POI和沿途POI
        
        Args:
            main_points: 主POI列表
            enroute_with_index: (插入位置, 沿途POI)列表
            
        Returns:
            合并后的RoutePoint列表
        """
        merged = []
        enroute_idx = 0
        
        for i, main_poi in enumerate(main_points):
            # 在当前位置前插入所有应该在此位置的沿途POI
            while enroute_idx < len(enroute_with_index):
                insert_index, enroute_poi = enroute_with_index[enroute_idx]
                
                # 如果沿途POI应插入在当前主POI之前
                if insert_index < i:
                    route_point = RoutePoint(
                        poi=enroute_poi,
                        stay_minutes=self._estimate_stay_time(enroute_poi),
                        note=f"沿途发现（距离路线{enroute_poi.distance_from_route:.0f}米）"
                    )
                    # 标记为沿途POI
                    route_point.poi_type = "enroute"
                    merged.append(route_point)
                    enroute_idx += 1
                else:
                    break
            
            # 添加主POI
            route_point = RoutePoint(
                poi=main_poi,
                stay_minutes=self._estimate_stay_time(main_poi),
                note="主要景点"
            )
            route_point.poi_type = "main"
            merged.append(route_point)
        
        # 添加剩余的沿途POI（应在最后一个主POI之后）
        while enroute_idx < len(enroute_with_index):
            _, enroute_poi = enroute_with_index[enroute_idx]
            route_point = RoutePoint(
                poi=enroute_poi,
                stay_minutes=self._estimate_stay_time(enroute_poi),
                note=f"沿途发现（距离路线{enroute_poi.distance_from_route:.0f}米）"
            )
            route_point.poi_type = "enroute"
            merged.append(route_point)
            enroute_idx += 1
        
        return merged

    def _create_route_points(
        self,
        pois: list[POI],
        route_result: RouteResult
    ) -> list[RoutePoint]:
        """
        从POI列表和路线结果创建RoutePoint列表
        """
        route_points = []
        for i, poi in enumerate(pois):
            route_point = RoutePoint(
                poi=poi,
                stay_minutes=self._estimate_stay_time(poi),
                polyline=route_result.polyline if i == 0 else "",
                steps=route_result.steps if i == 0 else [],
                note="主要景点"
            )
            route_point.poi_type = "main"
            route_points.append(route_point)
        return route_points

    def _estimate_stay_time(self, poi) -> int:
        """
        估算POI停留时间
        """
        # 根据POI类型估算
        if hasattr(poi, 'type') and poi.type:
            if "风景名胜" in poi.type or "旅游景点" in poi.type:
                return 120
            elif "博物馆" in poi.type or "美术馆" in poi.type:
                return 90
            elif "餐厅" in poi.type or "美食" in poi.type:
                return 60
            elif "购物中心" in poi.type or "商场" in poi.type:
                return 90
        
        # 默认60分钟
        return 60


# 单例
_route_replanner: Optional[RouteReplanner] = None


def get_route_replanner() -> RouteReplanner:
    """获取路线重规划器单例"""
    global _route_replanner
    if _route_replanner is None:
        _route_replanner = RouteReplanner()
    return _route_replanner
