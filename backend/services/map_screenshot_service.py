"""
高德地图截图服务
调用高德静态地图API生成路线截图
"""

import httpx
import base64
import hashlib
import logging
from io import BytesIO
from typing import List, Optional, Tuple
from functools import lru_cache

from config import get_settings
from models.base import POI

logger = logging.getLogger(__name__)


class MapScreenshotService:
    """高德地图截图服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.key = self.settings.gaode_key
        self.base_url = "https://restapi.amap.com/v3/staticmap"
        # 简单的内存缓存，生产环境建议使用Redis
        self._cache = {}
        self._cache_ttl = 86400  # 24小时缓存
    
    def _get_cache_key(self, polyline: str, width: int, height: int) -> str:
        """生成缓存key"""
        content = f"{polyline}_{width}_{height}"
        return hashlib.md5(content.encode()).hexdigest()
    
    async def generate_route_snapshot(
        self,
        polyline: str,
        pois: List[POI],
        width: int = 750,
        height: int = 400
    ) -> str:
        """
        生成路线截图
        
        Args:
            polyline: 坐标串，格式 "lng,lat;lng,lat;..."
            pois: POI列表（用于标记起点、途经点、终点）
            width: 图片宽度
            height: 图片高度
            
        Returns:
            str: 图片URL或base64编码
        """
        try:
            # 检查缓存
            cache_key = self._get_cache_key(polyline, width, height)
            if cache_key in self._cache:
                cached_data, cached_time = self._cache[cache_key]
                import time
                if time.time() - cached_time < self._cache_ttl:
                    logger.info(f"返回缓存的地图截图: {cache_key}")
                    return cached_data
            
            # 构建请求参数
            params = self._build_params(polyline, pois, width, height)
            
            # 调用高德API
            image_url = f"{self.base_url}?{params}"
            logger.info(f"生成地图截图: {image_url[:100]}...")
            
            # 获取图片数据
            image_data = await self._fetch_image(image_url)
            
            if image_data:
                # 转为base64
                base64_data = base64.b64encode(image_data).decode('utf-8')
                result = f"data:image/png;base64,{base64_data}"
                
                # 存入缓存
                import time
                self._cache[cache_key] = (result, time.time())
                
                return result
            else:
                logger.warning("获取图片失败，返回默认占位图")
                return self._get_default_placeholder()
                
        except Exception as e:
            logger.error(f"生成地图截图失败: {str(e)}")
            return self._get_default_placeholder()
    
    def _build_params(
        self,
        polyline: str,
        pois: List[POI],
        width: int,
        height: int
    ) -> str:
        """构建高德API请求参数"""
        params = {
            "key": self.key,
            "size": f"{width}*{height}",
            "scale": "2",  # 高清图
        }
        
        # 添加路径
        if polyline:
            paths_param = self._build_paths_param(polyline)
            if paths_param:
                params["paths"] = paths_param
        
        # 添加标记点
        if pois:
            markers_param = self._build_markers_param(pois)
            if markers_param:
                params["markers"] = markers_param
        
        # 计算zoom级别
        coordinates = self._parse_polyline(polyline)
        if coordinates:
            zoom = self._calculate_zoom(coordinates)
            params["zoom"] = str(zoom)
        
        # 拼接参数
        return "&".join(f"{k}={v}" for k, v in params.items())
    
    def _build_paths_param(self, polyline: str) -> str:
        """
        将polyline转为paths参数
        
        格式：线宽,线颜色,透明度,填充色,透明度:坐标串
        示例：5,0x1677FF,1,,:116.397,39.918;116.4,39.92
        """
        if not polyline:
            return ""
        
        # 线宽5，蓝色0x1677FF，透明度1，无填充色
        return f"5,0x1677FF,1,,:{polyline}"
    
    def _build_markers_param(self, pois: List[POI]) -> str:
        """
        将POI列表转为markers参数
        
        格式：
        - 起点：large,0x52C41A,S:坐标
        - 途经点：mid,0x1677FF,序号:坐标
        - 终点：large,0xF5222D,E:坐标
        """
        if not pois:
            return ""
        
        markers = []
        
        for i, poi in enumerate(pois):
            if not poi.location:
                continue
            
            location = poi.location
            
            if i == 0:
                # 起点 - 绿色大标记，S标记
                markers.append(f"large,0x52C41A,S:{location}")
            elif i == len(pois) - 1:
                # 终点 - 红色大标记，E标记
                markers.append(f"large,0xF5222D,E:{location}")
            else:
                # 途经点 - 蓝色中标记，数字序号
                markers.append(f"mid,0x1677FF,{i}:{location}")
        
        return ";".join(markers)
    
    def _parse_polyline(self, polyline: str) -> List[Tuple[float, float]]:
        """解析polyline为坐标列表"""
        if not polyline:
            return []
        
        coordinates = []
        for point in polyline.split(";"):
            point = point.strip()
            if not point:
                continue
            try:
                lng, lat = point.split(",")
                coordinates.append((float(lng), float(lat)))
            except (ValueError, IndexError):
                continue
        
        return coordinates
    
    def _calculate_zoom(self, coordinates: List[Tuple[float, float]]) -> int:
        """
        根据坐标范围计算合适的zoom级别
        
        Args:
            coordinates: 坐标列表 [(lng, lat), ...]
            
        Returns:
            int: zoom级别 (3-18)
        """
        if not coordinates:
            return 12  # 默认zoom
        
        # 计算边界
        lngs = [c[0] for c in coordinates]
        lats = [c[1] for c in coordinates]
        
        min_lng, max_lng = min(lngs), max(lngs)
        min_lat, max_lat = min(lats), max(lats)
        
        # 计算经纬度跨度
        lng_span = max_lng - min_lng
        lat_span = max_lat - min_lat
        
        # 根据跨度计算zoom
        # 经验公式：跨度越小，zoom越大
        max_span = max(lng_span, lat_span)
        
        if max_span > 1.0:
            zoom = 8
        elif max_span > 0.5:
            zoom = 9
        elif max_span > 0.2:
            zoom = 10
        elif max_span > 0.1:
            zoom = 11
        elif max_span > 0.05:
            zoom = 12
        elif max_span > 0.02:
            zoom = 13
        elif max_span > 0.01:
            zoom = 14
        elif max_span > 0.005:
            zoom = 15
        else:
            zoom = 16
        
        # 限制范围
        return max(3, min(18, zoom))
    
    async def _fetch_image(self, url: str) -> Optional[bytes]:
        """
        获取图片数据
        
        Args:
            url: 图片URL
            
        Returns:
            bytes: 图片数据，失败返回None
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "")
                    
                    # 检查是否返回了图片
                    if "image" in content_type:
                        return response.content
                    else:
                        # 可能返回了错误信息，尝试解析JSON错误
                        logger.warning(f"API返回非图片内容: {content_type}")
                        try:
                            error_data = response.json()
                            logger.error(f"高德API错误: {error_data}")
                        except:
                            logger.error(f"高德API响应内容: {response.text[:500]}")
                        return None
                else:
                    logger.warning(f"API请求失败: {response.status_code}")
                    logger.error(f"响应内容: {response.text[:500]}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error("请求高德API超时")
            return None
        except Exception as e:
            logger.error(f"请求高德API失败: {str(e)}")
            return None
    
    def _get_default_placeholder(self) -> str:
        """
        返回默认占位图（base64编码的简单图片）
        
        Returns:
            str: base64编码的占位图
        """
        # 简单的1x1像素透明PNG
        placeholder = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        return f"data:image/png;base64,{placeholder}"


# 单例模式
_map_screenshot_service: Optional[MapScreenshotService] = None


def get_map_screenshot_service() -> MapScreenshotService:
    """获取地图截图服务单例"""
    global _map_screenshot_service
    if _map_screenshot_service is None:
        _map_screenshot_service = MapScreenshotService()
    return _map_screenshot_service
