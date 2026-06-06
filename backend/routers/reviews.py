"""
评论路由 - 上海专用
仅支持上海POI评论
POST /api/reviews/batch - 批量获取上海POI评论
POST /api/reviews/search - 搜索上海POI评论
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Body

from models.base import ApiResponse
from exceptions import GaodeAPIError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["评论"])


@router.get("/{poi_name}", response_model=ApiResponse, summary="获取POI评论")
async def get_poi_reviews(
    poi_name: str,
    city: str = "上海",
    limit: int = 10
):
    """
    获取POI评论（基于高德数据）
    由于大众点评需要Cookie，此处返回模拟数据或高德评分信息
    """
    try:
        # 返回基于高德的模拟评论数据
        # 实际项目中可以集成其他评论源
        mock_reviews = {
            "poi_name": poi_name,
            "avg_rating": 4.5,
            "review_count": 100,
            "reviews": [
                {
                    "author": f"用户{i+1}",
                    "rating": 4.5,
                    "content": f"这是一个关于{poi_name}的评价。",
                    "date": "2024-01-01",
                    "likes": i * 5,
                    "photos": []
                } for i in range(min(limit, 5))
            ]
        }
        
        return ApiResponse(
            success=True,
            data=mock_reviews,
            message=f"获取'{poi_name}'评论成功（演示数据）"
        )
    except Exception as e:
        logger.exception(f"获取评论失败: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"获取评论失败: {str(e)}",
            code="REVIEWS_ERROR"
        )


@router.post("/batch", response_model=ApiResponse, summary="批量获取上海POI评论")
async def batch_get_reviews(
    poi_names: List[str] = Body(..., description="POI名称列表（仅上海）"),
    limit: int = Body(10, ge=1, le=20, description="每个POI评论数（最多20条）")
):
    """
    批量获取上海POI的大众点评评论
    所有POI限定在上海范围内
    """
    try:
        # 暂时注释掉评论获取，避免依赖问题
        logger.info(f"批量获取评论跳过: {len(poi_names)}个POI")
        
        results = []
        for poi_name in poi_names:
            results.append({
                "poi_name": poi_name,
                "success": False,
                "error": "dianping_reviews模块已移除",
                "data": None
            })
        
        return ApiResponse(
            success=True,
            data=results,
            message=f"批量获取{len(poi_names)}个上海POI评论完成（模拟数据）"
        )
    except Exception as e:
        logger.exception(f"批量获取评论异常: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"批量获取评论失败: {str(e)}",
            code="REVIEWS_ERROR"
        )


@router.post("/search", response_model=ApiResponse, summary="搜索上海POI并获取评论")
async def search_and_get_reviews(
    keyword: str = Body(..., description="搜索关键词（上海POI）"),
    limit: int = Body(10, ge=1, le=20, description="评论数（最多20条）")
):
    """
    搜索上海POI并获取评论
    仅搜索上海市内的POI
    """
    try:
        # 暂时注释掉评论获取，避免依赖问题
        logger.info(f"搜索评论跳过: 关键词'{keyword}'")
        
        from services.gaode_service import get_gaode_service
        gaode_service = get_gaode_service()
        
        # 先用高德搜索确认是上海POI
        pois = await gaode_service.place_text(keyword, city="上海")
        if not pois:
            return ApiResponse(
                success=False,
                data=None,
                message=f"未找到上海市内POI: {keyword}",
                code="POI_NOT_FOUND"
            )
        
        # 返回模拟的评论数据
        poi_name = pois[0].get("name", keyword)
        mock_reviews = [
            {
                "user_name": f"用户{i+1}",
                "rating": 4.5,
                "content": f"这是一个关于{poi_name}的模拟评论，用于演示系统功能。",
                "date": "2024-01-01",
                "images": []
            } for i in range(min(limit, 5))
        ]
        
        return ApiResponse(
            success=True,
            data={
                "poi_name": poi_name,
                "reviews": mock_reviews
            },
            message=f"获取上海POI'{poi_name}'评论成功（模拟数据）"
        )
        
    except Exception as e:
        logger.exception(f"搜索评论异常: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"搜索评论失败: {str(e)}",
            code="REVIEWS_ERROR"
        )
