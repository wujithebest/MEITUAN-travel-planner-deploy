"""
地址搜索路由 - 提供地址搜索API
"""
import logging
from fastapi import APIRouter, Query

from services.address_service import search_address, get_districts, reverse_geocode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/address", tags=["地址搜索"])


@router.get("/search")
async def address_search(
    keyword: str = Query(..., min_length=2, description="搜索关键词，至少2个字符"),
    city: str = Query(None, description="限制搜索的城市名称"),
):
    """
    地址搜索接口
    
    - keyword: 用户输入的关键词（至少2个字符）
    - city: 可选，限制搜索范围的城市名称
    
    返回格式化的地址列表，包含名称、详细地址、经纬度和区县信息
    """
    try:
        results = await search_address(keyword=keyword, city=city)
        return {
            "status": "success",
            "data": results,
            "count": len(results),
        }
    except Exception as e:
        logger.error(f"[AddressRouter] 地址搜索失败: {e}")
        return {
            "status": "error",
            "data": [],
            "count": 0,
            "message": str(e),
        }


@router.get("/districts")
async def district_search(
    keywords: str = Query("中国", min_length=1, description="查询关键词，如'中国'获取省级，adcode获取下级"),
    subdistrict: int = Query(1, ge=0, le=2, description="下级层级：0=无下级，1=下一级，2=下两级"),
):
    """
    行政区划查询接口

    - keywords: 查询关键词（"中国"获取所有省份，adcode 如"110000"获取北京市下级）
    - subdistrict: 返回下级行政区层级

    返回省市区的层级结构数据
    """
    try:
        results = await get_districts(keywords=keywords, subdistrict=subdistrict)
        return {
            "status": "success",
            "data": results,
            "count": len(results),
        }
    except Exception as e:
        logger.error(f"[AddressRouter] 行政区划查询失败: {e}")
        return {
            "status": "error",
            "data": [],
            "count": 0,
            "message": str(e),
        }


@router.get("/reverse-geocode")
async def reverse_geocode_endpoint(
    lng: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
):
    """
    逆地理编码接口：根据经纬度获取地址信息

    - lng: 经度
    - lat: 纬度

    返回省、市、区、详细地址等信息
    """
    try:
        result = await reverse_geocode(lng=lng, lat=lat)
        if result is None:
            return {
                "status": "error",
                "data": None,
                "message": "逆地理编码失败",
            }
        return {
            "status": "success",
            "data": result,
        }
    except Exception as e:
        logger.error(f"[AddressRouter] 逆地理编码失败: {e}")
        return {
            "status": "error",
            "data": None,
            "message": str(e),
        }
