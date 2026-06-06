"""
大众点评爬虫服务
集成 dianping_spider-master 的功能，提供POI评论和图片获取服务
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import hashlib
import json

logger = logging.getLogger(__name__)

class DianpingService:
    """大众点评数据服务"""
    
    def __init__(self):
        self.cache = {}  # 简单的内存缓存
        self.cache_ttl = 3600  # 缓存1小时
        
    def _get_cache_key(self, shop_id: str) -> str:
        """生成缓存键"""
        return hashlib.md5(f"dianping_{shop_id}".encode()).hexdigest()
    
    def _get_from_cache(self, key: str) -> Optional[Dict]:
        """从缓存获取数据"""
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now().timestamp() - timestamp < self.cache_ttl:
                logger.info(f"缓存命中: {key}")
                return data
            else:
                # 缓存过期，删除
                del self.cache[key]
        return None
    
    def _save_to_cache(self, key: str, data: Dict):
        """保存数据到缓存"""
        self.cache[key] = (data, datetime.now().timestamp())
        logger.info(f"缓存已保存: {key}")
    
    async def search_shop(self, keyword: str, city: str = "上海") -> List[Dict[str, Any]]:
        """
        搜索店铺
        :param keyword: 搜索关键词
        :param city: 城市（默认上海）
        :return: 搜索结果列表
        """
        try:
            # 导入爬虫模块
            import sys
            sys.path.insert(0, r"D:\travel-planner-backend\dianping_spider-master\dianping_spider-master")
            
            from function.search import Search
            from utils.spider_config import spider_config
            
            # 配置爬虫
            spider_config.NEED_SEARCH_PAGES = 1  # 只搜索第一页
            
            search = Search()
            search_url = f"http://www.dianping.com/search/keyword/1/0_{keyword}"
            
            # 在线程池中执行同步的爬虫代码
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, search.search, search_url)
            
            if result:
                logger.info(f"搜索 '{keyword}' 找到 {len(result)} 个结果")
                return result
            return []
            
        except Exception as e:
            logger.error(f"搜索店铺失败: {str(e)}")
            return []
    
    async def get_shop_reviews(
        self, 
        shop_id: str, 
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        获取店铺评论
        :param shop_id: 店铺ID
        :param limit: 评论数量限制
        :return: 评论数据
        """
        cache_key = self._get_cache_key(f"reviews_{shop_id}_{limit}")
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        
        try:
            import sys
            sys.path.insert(0, r"D:\travel-planner-backend\dianping_spider-master\dianping_spider-master")
            
            from function.review import Review
            from utils.spider_config import spider_config
            
            # 配置需要的评论页数（每页约20条评论）
            spider_config.NEED_REVIEW_PAGES = (limit // 20) + 1
            
            review = Review()
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                review.get_review, 
                shop_id
            )
            
            # 限制评论数量
            if result and '精选评论' in result:
                result['精选评论'] = result['精选评论'][:limit]
            
            # 保存到缓存
            self._save_to_cache(cache_key, result)
            
            logger.info(f"获取店铺 {shop_id} 评论成功: {len(result.get('精选评论', []))} 条")
            return result
            
        except Exception as e:
            logger.error(f"获取店铺评论失败: {str(e)}")
            return {
                '店铺id': shop_id,
                '评论摘要': [],
                '评论总数': 0,
                '好评个数': 0,
                '中评个数': 0,
                '差评个数': 0,
                '带图评论个数': 0,
                '精选评论': [],
                'error': str(e)
            }
    
    async def get_shop_detail(self, shop_id: str) -> Dict[str, Any]:
        """
        获取店铺详情
        :param shop_id: 店铺ID
        :return: 店铺详情
        """
        cache_key = self._get_cache_key(f"detail_{shop_id}")
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        
        try:
            import sys
            sys.path.insert(0, r"D:\travel-planner-backend\dianping_spider-master\dianping_spider-master")
            
            from function.detail import Detail
            
            detail = Detail()
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                detail.get_detail,
                shop_id
            )
            
            self._save_to_cache(cache_key, result)
            
            logger.info(f"获取店铺 {shop_id} 详情成功")
            return result
            
        except Exception as e:
            logger.error(f"获取店铺详情失败: {str(e)}")
            return {
                '店铺id': shop_id,
                '店铺名': '',
                '评论总数': '0',
                '人均价格': '',
                '店铺地址': '',
                '店铺电话': '',
                '其他信息': '',
                'error': str(e)
            }
    
    async def get_shop_photos(self, shop_id: str) -> List[str]:
        """
        获取店铺图片（从评论中提取）
        :param shop_id: 店铺ID
        :return: 图片URL列表
        """
        try:
            reviews_data = await self.get_shop_reviews(shop_id, limit=50)
            photos = []
            
            if reviews_data and '精选评论' in reviews_data:
                for review in reviews_data['精选评论']:
                    if '评论图片' in review and review['评论图片']:
                        photos.extend(review['评论图片'])
            
            # 去重并限制数量
            photos = list(set(photos))[:20]
            
            logger.info(f"获取店铺 {shop_id} 图片: {len(photos)} 张")
            return photos
            
        except Exception as e:
            logger.error(f"获取店铺图片失败: {str(e)}")
            return []
    
    async def get_complete_shop_info(
        self, 
        shop_id: str,
        review_limit: int = 10
    ) -> Dict[str, Any]:
        """
        获取完整的店铺信息（详情+评论+图片）
        :param shop_id: 店铺ID
        :param review_limit: 评论数量限制
        :return: 完整店铺信息
        """
        try:
            # 并行获取详情和评论
            detail_task = self.get_shop_detail(shop_id)
            reviews_task = self.get_shop_reviews(shop_id, review_limit)
            
            detail, reviews = await asyncio.gather(detail_task, reviews_task)
            
            # 提取图片
            photos = []
            if reviews and '精选评论' in reviews:
                for review in reviews['精选评论']:
                    if '评论图片' in review and review['评论图片']:
                        photos.extend(review['评论图片'])
            photos = list(set(photos))[:20]
            
            result = {
                'shop_id': shop_id,
                'detail': detail,
                'reviews': reviews,
                'photos': photos,
                'fetch_time': datetime.now().isoformat()
            }
            
            logger.info(f"获取店铺 {shop_id} 完整信息成功")
            return result
            
        except Exception as e:
            logger.error(f"获取完整店铺信息失败: {str(e)}")
            return {
                'shop_id': shop_id,
                'detail': {},
                'reviews': {},
                'photos': [],
                'error': str(e),
                'fetch_time': datetime.now().isoformat()
            }


# 单例模式
_dianping_service: Optional[DianpingService] = None

def get_dianping_service() -> DianpingService:
    """获取大众点评服务单例"""
    global _dianping_service
    if _dianping_service is None:
        _dianping_service = DianpingService()
    return _dianping_service
