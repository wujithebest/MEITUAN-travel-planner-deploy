"""
大众点评数据路由
提供POI评论和图片获取API
"""

import logging
from typing import Optional
from fastapi import APIRouter, Query, Path

from models.base import ApiResponse
from services.dianping_service import get_dianping_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dianping", tags=["大众点评"])


@router.get("/search", response_model=ApiResponse, summary="搜索大众点评店铺")
async def search_shop(
    keyword: str = Query(..., description="搜索关键词"),
    city: str = Query("上海", description="城市")
):
    """
    搜索大众点评店铺
    """
    try:
        service = get_dianping_service()
        result = await service.search_shop(keyword, city)
        
        return ApiResponse(
            success=True,
            data=result,
            message=f"搜索完成，找到 {len(result)} 个结果"
        )
    except Exception as e:
        logger.exception(f"搜索失败: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"搜索失败: {str(e)}",
            code="SEARCH_ERROR"
        )


@router.get("/shop/{shop_id}/reviews", response_model=ApiResponse, summary="获取店铺评论")
async def get_shop_reviews(
    shop_id: str = Path(..., description="大众点评店铺ID"),
    limit: int = Query(10, ge=1, le=50, description="评论数量（最多50条）")
):
    """
    获取大众点评店铺评论
    """
    try:
        service = get_dianping_service()
        result = await service.get_shop_reviews(shop_id, limit)
        
        review_count = len(result.get('精选评论', []))
        return ApiResponse(
            success=True,
            data=result,
            message=f"获取评论成功，共 {review_count} 条"
        )
    except Exception as e:
        logger.exception(f"获取评论失败: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"获取评论失败: {str(e)}",
            code="REVIEWS_ERROR"
        )


@router.get("/shop/{shop_id}/detail", response_model=ApiResponse, summary="获取店铺详情")
async def get_shop_detail(
    shop_id: str = Path(..., description="大众点评店铺ID")
):
    """
    获取大众点评店铺详情
    """
    try:
        service = get_dianping_service()
        result = await service.get_shop_detail(shop_id)
        
        return ApiResponse(
            success=True,
            data=result,
            message="获取详情成功"
        )
    except Exception as e:
        logger.exception(f"获取详情失败: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"获取详情失败: {str(e)}",
            code="DETAIL_ERROR"
        )


@router.get("/shop/{shop_id}/photos", response_model=ApiResponse, summary="获取店铺图片")
async def get_shop_photos(
    shop_id: str = Path(..., description="大众点评店铺ID")
):
    """
    获取大众点评店铺图片（从评论中提取）
    """
    try:
        service = get_dianping_service()
        result = await service.get_shop_photos(shop_id)
        
        return ApiResponse(
            success=True,
            data=result,
            message=f"获取图片成功，共 {len(result)} 张"
        )
    except Exception as e:
        logger.exception(f"获取图片失败: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"获取图片失败: {str(e)}",
            code="PHOTOS_ERROR"
        )


@router.get("/shop/{shop_id}/complete", response_model=ApiResponse, summary="获取完整店铺信息")
async def get_complete_shop_info(
    shop_id: str = Path(..., description="大众点评店铺ID"),
    review_limit: int = Query(10, ge=1, le=50, description="评论数量（最多50条）")
):
    """
    获取大众点评店铺完整信息（详情+评论+图片）
    """
    try:
        service = get_dianping_service()
        result = await service.get_complete_shop_info(shop_id, review_limit)
        
        if 'error' in result:
            return ApiResponse(
                success=False,
                data=result,
                message=f"获取信息失败: {result['error']}",
                code="FETCH_ERROR"
            )
        
        return ApiResponse(
            success=True,
            data=result,
            message="获取完整信息成功"
        )
    except Exception as e:
        logger.exception(f"获取完整信息失败: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"获取完整信息失败: {str(e)}",
            code="FETCH_ERROR"
        )


@router.get("/poi/{poi_name}/match", response_model=ApiResponse, summary="通过POI名称匹配大众点评店铺")
async def match_poi_to_dianping(
    poi_name: str = Path(..., description="POI名称"),
    city: str = Query("上海", description="城市")
):
    """
    通过POI名称搜索大众点评店铺，返回最匹配的结果
    用于将高德POI与大众点评店铺关联
    """
    try:
        service = get_dianping_service()
        results = await service.search_shop(poi_name, city)
        
        if not results:
            return ApiResponse(
                success=False,
                data=None,
                message=f"未找到匹配的店铺: {poi_name}",
                code="NOT_FOUND"
            )
        
        # 返回第一个最匹配的结果
        best_match = results[0]
        
        return ApiResponse(
            success=True,
            data={
                'search_results': results[:5],  # 返回前5个结果
                'best_match': best_match,
                'shop_id': best_match.get('店铺id', ''),
                'shop_name': best_match.get('店铺名', ''),
                'rating': best_match.get('店铺总分', ''),
                'review_count': best_match.get('评论总数', ''),
                'address': best_match.get('店铺地址', ''),
                'detail_url': best_match.get('详情链接', ''),
                'image_url': best_match.get('图片链接', '')
            },
            message="匹配成功"
        )
    except Exception as e:
        logger.exception(f"POI匹配失败: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"POI匹配失败: {str(e)}",
            code="MATCH_ERROR"
        )
