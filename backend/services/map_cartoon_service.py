"""
卡通风格地图处理服务
使用OpenCV+Pillow进行卡通化处理
支持4种风格：卡通/素描/水彩/像素

处理流程：
1. 获取高德静态地图截图
2. 双边滤波保留边缘同时平滑颜色
3. 颜色量化到8色，增强卡通感
4. 饱和度提升1.3倍让颜色更鲜艳
5. 缓存处理后的图片
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import base64
import hashlib
import logging
import time
from typing import Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class MapStyle(str, Enum):
    """地图卡通风格枚举"""
    CARTOON = "cartoon"      # 卡通风格
    SKETCH = "sketch"        # 素描风格
    WATERCOLOR = "watercolor"  # 水彩风格
    PIXEL = "pixel"          # 像素风格


class MapCartoonService:
    """卡通风格地图处理服务"""
    
    def __init__(self):
        # 内存缓存，生产环境建议使用Redis
        self._cache = {}
        self._cache_ttl = 86400  # 24小时缓存
    
    def _get_cache_key(self, image_data: bytes, style: MapStyle, width: int, height: int) -> str:
        """生成缓存key"""
        content = f"{hashlib.md5(image_data).hexdigest()}_{style}_{width}_{height}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _base64_to_image(self, base64_str: str) -> np.ndarray:
        """将base64字符串转换为OpenCV图像"""
        # 移除data:image/png;base64,前缀
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]
        
        image_data = base64.b64decode(base64_str)
        nparr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return image
    
    def _image_to_base64(self, image: np.ndarray, format: str = "png") -> str:
        """将OpenCV图像转换为base64字符串"""
        _, buffer = cv2.imencode(f".{format}", image)
        base64_str = base64.b64encode(buffer).decode('utf-8')
        return f"data:image/{format};base64,{base64_str}"
    
    def _pil_to_cv2(self, pil_image: Image.Image) -> np.ndarray:
        """PIL图像转OpenCV图像"""
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    
    def _cv2_to_pil(self, cv2_image: np.ndarray) -> Image.Image:
        """OpenCV图像转PIL图像"""
        return Image.fromarray(cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB))
    
    def process_image(
        self,
        image_data: str,
        style: MapStyle = MapStyle.CARTOON,
        width: int = 1200,
        height: int = 600
    ) -> str:
        """
        处理地图图片，生成卡通风格
        
        Args:
            image_data: 原始图片base64字符串
            style: 卡通风格
            width: 输出宽度
            height: 输出高度
            
        Returns:
            str: 处理后的图片base64字符串
        """
        try:
            # 检查缓存
            cache_key = self._get_cache_key(image_data.encode(), style, width, height)
            if cache_key in self._cache:
                cached_data, cached_time = self._cache[cache_key]
                if time.time() - cached_time < self._cache_ttl:
                    logger.info(f"返回缓存的卡通地图: {cache_key}")
                    return cached_data
            
            # 转换图像格式
            cv_image = self._base64_to_image(image_data)
            
            if cv_image is None:
                logger.error("图像解码失败")
                return image_data
            
            # 调整尺寸
            cv_image = cv2.resize(cv_image, (width, height), interpolation=cv2.INTER_AREA)
            
            # 根据风格处理
            if style == MapStyle.CARTOON:
                result = self._apply_cartoon_style(cv_image)
            elif style == MapStyle.SKETCH:
                result = self._apply_sketch_style(cv_image)
            elif style == MapStyle.WATERCOLOR:
                result = self._apply_watercolor_style(cv_image)
            elif style == MapStyle.PIXEL:
                result = self._apply_pixel_style(cv_image)
            else:
                result = self._apply_cartoon_style(cv_image)
            
            # 转换回base64
            result_base64 = self._image_to_base64(result)
            
            # 存入缓存
            self._cache[cache_key] = (result_base64, time.time())
            
            logger.info(f"卡通地图生成成功: style={style}, size={width}x{height}")
            return result_base64
            
        except Exception as e:
            logger.error(f"卡通地图处理失败: {str(e)}")
            # 降级方案：返回原始图片
            return image_data
    
    def _apply_cartoon_style(self, image: np.ndarray) -> np.ndarray:
        """
        应用卡通风格
        
        处理步骤：
        1. 双边滤波保留边缘同时平滑颜色
        2. 颜色量化到8色
        3. 边缘增强
        4. 饱和度提升1.3倍
        """
        # 1. 双边滤波 - 保留边缘，平滑颜色
        # d: 滤波直径，sigmaColor: 颜色空间标准差，sigmaSpace: 坐标空间标准差
        filtered = cv2.bilateralFilter(image, d=9, sigmaColor=75, sigmaSpace=75)
        
        # 2. 颜色量化 - 减少颜色数量到8色
        # 使用K-means聚类进行颜色量化
        Z = filtered.reshape((-1, 3))
        Z = np.float32(Z)
        
        # K-means参数
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        K = 8  # 8种颜色
        _, labels, centers = cv2.kmeans(Z, K, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
        
        # 重建图像
        centers = np.uint8(centers)
        quantized = centers[labels.flatten()]
        quantized = quantized.reshape((image.shape))
        
        # 3. 边缘增强
        # 转换为灰度图
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # 自适应阈值边缘检测
        edges = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY,
            blockSize=9,
            C=2
        )
        # 膨胀边缘使其更明显
        kernel = np.ones((2, 2), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        
        # 将边缘叠加到量化后的图像上
        edges_colored = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        result = cv2.bitwise_and(quantized, edges_colored)
        
        # 4. 提升饱和度
        pil_image = self._cv2_to_pil(result)
        enhancer = ImageEnhance.Color(pil_image)
        pil_image = enhancer.enhance(1.3)  # 饱和度提升1.3倍
        result = self._pil_to_cv2(pil_image)
        
        return result
    
    def _apply_sketch_style(self, image: np.ndarray) -> np.ndarray:
        """
        应用素描风格
        
        处理步骤：
        1. 灰度转换
        2. 高斯模糊
        3. 边缘检测（Canny）
        4. 反色处理
        """
        # 1. 灰度转换
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # 2. 高斯模糊
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # 3. Canny边缘检测
        edges = cv2.Canny(blurred, 50, 150)
        
        # 4. 反色处理（黑底白线 -> 白底黑线）
        edges_inv = cv2.bitwise_not(edges)
        
        # 5. 添加轻微的颜色叠加，使其看起来像铅笔素描
        # 创建米黄色背景
        sketch = np.full_like(image, [245, 245, 240])  # BGR格式的米黄色
        
        # 将边缘叠加到背景上
        edges_colored = cv2.cvtColor(edges_inv, cv2.COLOR_GRAY2BGR)
        result = cv2.bitwise_and(sketch, edges_colored)
        
        return result
    
    def _apply_watercolor_style(self, image: np.ndarray) -> np.ndarray:
        """
        应用水彩风格
        
        处理步骤：
        1. 中值滤波去噪
        2. 双边滤波平滑
        3. 颜色量化（更多颜色）
        4. 添加纹理效果
        5. 轻微模糊模拟水彩扩散
        """
        # 1. 中值滤波去噪
        denoised = cv2.medianBlur(image, 5)
        
        # 2. 双边滤波平滑
        filtered = cv2.bilateralFilter(denoised, d=9, sigmaColor=75, sigmaSpace=75)
        
        # 3. 颜色量化 - 水彩风格使用更多颜色（16色）
        Z = filtered.reshape((-1, 3))
        Z = np.float32(Z)
        
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        K = 16  # 16种颜色
        _, labels, centers = cv2.kmeans(Z, K, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
        
        centers = np.uint8(centers)
        quantized = centers[labels.flatten()]
        quantized = quantized.reshape((image.shape))
        
        # 4. 轻微高斯模糊模拟水彩扩散效果
        result = cv2.GaussianBlur(quantized, (3, 3), 0)
        
        # 5. 提升饱和度
        pil_image = self._cv2_to_pil(result)
        enhancer = ImageEnhance.Color(pil_image)
        pil_image = enhancer.enhance(1.2)
        result = self._pil_to_cv2(pil_image)
        
        return result
    
    def _apply_pixel_style(self, image: np.ndarray) -> np.ndarray:
        """
        应用像素风格
        
        处理步骤：
        1. 缩小图像（降低分辨率）
        2. 颜色量化
        3. 放大回原始尺寸（最近邻插值保持像素感）
        """
        h, w = image.shape[:2]
        
        # 1. 缩小图像（降低分辨率）
        # 缩放到原来的1/8
        small_w = max(w // 8, 1)
        small_h = max(h // 8, 1)
        small = cv2.resize(image, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        
        # 2. 颜色量化
        Z = small.reshape((-1, 3))
        Z = np.float32(Z)
        
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        K = 8
        _, labels, centers = cv2.kmeans(Z, K, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
        
        centers = np.uint8(centers)
        quantized = centers[labels.flatten()]
        quantized = quantized.reshape((small.shape))
        
        # 3. 放大回原始尺寸（最近邻插值保持像素感）
        result = cv2.resize(quantized, (w, h), interpolation=cv2.INTER_NEAREST)
        
        return result
    
    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
        logger.info("卡通地图缓存已清除")


# 单例模式
_map_cartoon_service: Optional[MapCartoonService] = None


def get_map_cartoon_service() -> MapCartoonService:
    """获取卡通地图服务单例"""
    global _map_cartoon_service
    if _map_cartoon_service is None:
        _map_cartoon_service = MapCartoonService()
    return _map_cartoon_service
