"""
日记路由
POST /api/diary/generate - 生成日记
GET /api/diary/{diary_id} - 获取日记
POST /api/diary/entry - 添加条目
POST /api/diary/photo - 添加照片
GET /api/diary/{diary_id}/export - 导出日记
GET /api/diary/{diary_id}/day/{day_index}/map - 获取某天的地图截图（支持风格切换）
POST /api/diary/map-snapshot - 生成地图截图（独立接口，支持风格切换）
POST /api/diary/cartoon-map - 生成卡通风格地图
"""

import json
import logging

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response

from models.base import ApiResponse
from models.diary import DiaryEntryRequest, DiaryEntryUpdateRequest, DiaryPhotoRequest
from services.diary_service import get_diary_service
from services.map_cartoon_service import MapStyle
from routers.route import _route_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diary", tags=["旅行日记"])


@router.post("/generate", response_model=ApiResponse, summary="生成旅行日记")
async def generate_diary(
    route_id: str = Query(..., description="路线ID"),
    map_style: str = Query("cartoon", description="地图风格: cartoon/sketch/watercolor/pixel")
):
    """
    根据路线自动生成旅行日记
    数据流：行程完成 -> 提取内容 -> LLM润色 -> 组装 -> 导出
    
    Args:
        route_id: 路线ID
        map_style: 地图卡通风格 (cartoon/sketch/watercolor/pixel)
    """
    logger.info(f"[generate_diary] 请求到达, route_id={route_id}, map_style={map_style}")
    print(f"[generate_diary] 请求到达, route_id={route_id}, map_style={map_style}")
    try:
        # 解析地图风格
        try:
            style = MapStyle(map_style)
        except ValueError:
            style = MapStyle.CARTOON
            logger.warning(f"无效的地图风格: {map_style}, 使用默认风格 cartoon")
        
        route = _route_store.get(route_id)
        if not route:
            logger.warning(f"[generate_diary] 路线不存在: {route_id}")
            return ApiResponse(
                success=False, data=None,
                message=f"路线不存在: {route_id}", code="NOT_FOUND"
            )

        logger.info(f"[generate_diary] 开始生成日记, route={route}")
        service = get_diary_service()
        diary = await service.generate_diary(route, map_style=style)

        logger.info(f"[generate_diary] 日记生成成功, diary_id={diary.diary_id}")
        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(diary.model_dump(), default=str)),
            message="日记生成成功"
        )
    except Exception as e:
        logger.exception(f"[generate_diary] 日记生成异常: {str(e)}")
        print(f"[generate_diary] 日记生成异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"日记生成失败: {str(e)}", code="ERROR"
        )


@router.get("/{diary_id}", response_model=ApiResponse, summary="获取日记详情")
async def get_diary(diary_id: str):
    """获取日记详情"""
    try:
        service = get_diary_service()
        diary = await service.get_diary(diary_id)
        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(diary.model_dump(), default=str)),
            message="获取成功"
        )
    except Exception as e:
        logger.exception(f"获取日记异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=str(e), code="ERROR"
        )


@router.post("/entry", response_model=ApiResponse, summary="添加日记条目")
async def add_entry(request: DiaryEntryRequest):
    """添加日记条目"""
    try:
        service = get_diary_service()
        entry = await service.add_entry(request.diary_id, request.model_dump())
        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(entry.model_dump(), default=str)),
            message="条目添加成功"
        )
    except Exception as e:
        logger.exception(f"添加条目异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=str(e), code="ERROR"
        )


@router.put("/{diary_id}/entry/{entry_id}", response_model=ApiResponse, summary="更新日记条目")
async def update_entry(diary_id: str, entry_id: str, request: DiaryEntryUpdateRequest):
    """更新日记条目"""
    try:
        service = get_diary_service()
        entry = await service.update_entry(diary_id, entry_id, request.model_dump())
        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(entry.model_dump(), default=str)),
            message="条目更新成功"
        )
    except Exception as e:
        logger.exception(f"更新条目异常: {str(e)}")
        return ApiResponse(success=False, data=None, message=str(e), code="ERROR")


@router.post("/photo", response_model=ApiResponse, summary="添加照片")
async def add_photo(request: DiaryPhotoRequest):
    """添加照片到日记条目"""
    try:
        service = get_diary_service()
        await service.add_photo(request.diary_id, request.entry_id, request.photo_url)
        return ApiResponse(success=True, data={"url": request.photo_url}, message="照片添加成功")
    except Exception as e:
        logger.exception(f"添加照片异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=str(e), code="ERROR"
        )


@router.post("/{diary_id}/share", response_model=ApiResponse, summary="生成日记分享链接")
async def share_diary(diary_id: str):
    """生成站内日记分享链接"""
    try:
        service = get_diary_service()
        await service.get_diary(diary_id)
        return ApiResponse(
            success=True,
            data={"link": f"/diary/{diary_id}"},
            message="分享链接生成成功"
        )
    except Exception as e:
        logger.exception(f"生成分享链接异常: {str(e)}")
        return ApiResponse(success=False, data=None, message=str(e), code="ERROR")


@router.get("/{diary_id}/export", response_model=ApiResponse, summary="导出日记")
async def export_diary(
    diary_id: str,
    format: str = Query("image", description="导出格式: image/pdf/h5")
):
    """导出日记为图片/PDF/H5"""
    try:
        service = get_diary_service()
        result = await service.export_diary(diary_id, format)
        return ApiResponse(
            success=result.get("success", False),
            data=result,
            message="导出成功" if result.get("success") else result.get("message", "导出失败")
        )
    except Exception as e:
        logger.exception(f"导出日记异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"导出失败: {str(e)}", code="ERROR"
        )


@router.get("/{diary_id}/day/{day_index}/map", summary="获取某天的地图截图（支持风格切换）")
async def get_day_map_snapshot(
    diary_id: str,
    day_index: int,
    style: str = Query("cartoon", description="地图风格: cartoon/sketch/watercolor/pixel"),
    width: int = Query(750, description="图片宽度"),
    height: int = Query(400, description="图片高度"),
    regenerate: bool = Query(False, description="是否重新生成")
):
    """
    获取某一天的地图截图（支持卡通风格切换）
    
    Args:
        diary_id: 日记ID
        day_index: 天数索引（从1开始）
        style: 地图卡通风格 (cartoon/sketch/watercolor/pixel)
        width: 图片宽度
        height: 图片高度
        regenerate: 是否重新生成
    """
    try:
        # 解析地图风格
        try:
            map_style = MapStyle(style)
        except ValueError:
            map_style = MapStyle.CARTOON
            logger.warning(f"无效的地图风格: {style}, 使用默认风格 cartoon")
        
        service = get_diary_service()
        
        # 获取日记
        diary = await service.get_diary(diary_id)
        
        # 查找对应的路线数据
        route = _route_store.get(diary.route_id)
        if not route:
            return ApiResponse(
                success=False, data=None,
                message=f"路线不存在: {diary.route_id}", code="NOT_FOUND"
            )
        
        # 查找对应的每日路线
        daily = None
        for d in route.daily_routes:
            if d.day == day_index:
                daily = d
                break
        
        if not daily:
            return ApiResponse(
                success=False, data=None,
                message=f"第{day_index}天的路线不存在", code="NOT_FOUND"
            )
        
        # 检查是否已有缓存的截图（且不要求重新生成）
        if daily.map_snapshot and not regenerate:
            return ApiResponse(
                success=True,
                data={"map_snapshot": daily.map_snapshot},
                message="获取成功（缓存）"
            )
        
        # 生成新的截图
        if not daily.polyline:
            return ApiResponse(
                success=False, data=None,
                message="该路线没有polyline数据", code="NO_DATA"
            )
        
        pois = [point.poi for point in daily.points if point.poi]
        if not pois:
            return ApiResponse(
                success=False, data=None,
                message="该路线没有POI数据", code="NO_DATA"
            )
        
        # 生成卡通风格地图
        cartoon_snapshot = await service.generate_cartoon_map(
            polyline=daily.polyline,
            pois=pois,
            style=map_style,
            width=width,
            height=height
        )
        
        # 缓存截图
        daily.map_snapshot = cartoon_snapshot
        
        return ApiResponse(
            success=True,
            data={"map_snapshot": cartoon_snapshot, "style": style},
            message="获取成功"
        )
        
    except Exception as e:
        logger.exception(f"获取地图截图异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"获取地图截图失败: {str(e)}", code="ERROR"
        )


@router.post("/map-snapshot", response_model=ApiResponse, summary="生成地图截图（支持风格切换）")
async def generate_map_snapshot(
    route_id: str = Query(..., description="路线ID"),
    day_index: int = Query(1, description="天数索引（从1开始）"),
    style: str = Query("cartoon", description="地图风格: cartoon/sketch/watercolor/pixel"),
    width: int = Query(750, description="图片宽度"),
    height: int = Query(400, description="图片高度")
):
    """
    生成地图截图（独立接口，支持卡通风格）
    
    Args:
        route_id: 路线ID
        day_index: 天数索引（从1开始）
        style: 地图卡通风格 (cartoon/sketch/watercolor/pixel)
        width: 图片宽度
        height: 图片高度
    """
    try:
        # 解析地图风格
        try:
            map_style = MapStyle(style)
        except ValueError:
            map_style = MapStyle.CARTOON
            logger.warning(f"无效的地图风格: {style}, 使用默认风格 cartoon")
        
        service = get_diary_service()
        
        # 获取路线
        route = _route_store.get(route_id)
        if not route:
            return ApiResponse(
                success=False, data=None,
                message=f"路线不存在: {route_id}", code="NOT_FOUND"
            )
        
        # 查找对应的每日路线
        daily = None
        for d in route.daily_routes:
            if d.day == day_index:
                daily = d
                break
        
        if not daily:
            return ApiResponse(
                success=False, data=None,
                message=f"第{day_index}天的路线不存在", code="NOT_FOUND"
            )
        
        if not daily.polyline:
            return ApiResponse(
                success=False, data=None,
                message="该路线没有polyline数据", code="NO_DATA"
            )
        
        pois = [point.poi for point in daily.points if point.poi]
        if not pois:
            return ApiResponse(
                success=False, data=None,
                message="该路线没有POI数据", code="NO_DATA"
            )
        
        # 生成卡通风格地图
        cartoon_snapshot = await service.generate_cartoon_map(
            polyline=daily.polyline,
            pois=pois,
            style=map_style,
            width=width,
            height=height
        )
        
        return ApiResponse(
            success=True,
            data={"map_snapshot": cartoon_snapshot, "style": style},
            message="生成成功"
        )
        
    except Exception as e:
        logger.exception(f"生成地图截图异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"生成地图截图失败: {str(e)}", code="ERROR"
        )


@router.post("/cartoon-map", response_model=ApiResponse, summary="生成卡通风格地图")
async def generate_cartoon_map(
    route_id: str = Query(..., description="路线ID"),
    day_index: int = Query(1, description="天数索引（从1开始）"),
    style: str = Query("cartoon", description="地图风格: cartoon/sketch/watercolor/pixel"),
    width: int = Query(1200, description="图片宽度"),
    height: int = Query(600, description="图片高度")
):
    """
    生成卡通风格地图（专用接口）
    
    Args:
        route_id: 路线ID
        day_index: 天数索引（从1开始）
        style: 地图卡通风格 (cartoon/sketch/watercolor/pixel)
        width: 图片宽度
        height: 图片高度
    """
    try:
        # 解析地图风格
        try:
            map_style = MapStyle(style)
        except ValueError:
            map_style = MapStyle.CARTOON
            logger.warning(f"无效的地图风格: {style}, 使用默认风格 cartoon")
        
        service = get_diary_service()
        
        # 获取路线
        route = _route_store.get(route_id)
        if not route:
            return ApiResponse(
                success=False, data=None,
                message=f"路线不存在: {route_id}", code="NOT_FOUND"
            )
        
        # 查找对应的每日路线
        daily = None
        for d in route.daily_routes:
            if d.day == day_index:
                daily = d
                break
        
        if not daily:
            return ApiResponse(
                success=False, data=None,
                message=f"第{day_index}天的路线不存在", code="NOT_FOUND"
            )
        
        if not daily.polyline:
            return ApiResponse(
                success=False, data=None,
                message="该路线没有polyline数据", code="NO_DATA"
            )
        
        pois = [point.poi for point in daily.points if point.poi]
        if not pois:
            return ApiResponse(
                success=False, data=None,
                message="该路线没有POI数据", code="NO_DATA"
            )
        
        # 生成卡通风格地图
        cartoon_snapshot = await service.generate_cartoon_map(
            polyline=daily.polyline,
            pois=pois,
            style=map_style,
            width=width,
            height=height
        )
        
        return ApiResponse(
            success=True,
            data={
                "map_snapshot": cartoon_snapshot, 
                "style": style,
                "width": width,
                "height": height
            },
            message="卡通地图生成成功"
        )
        
    except Exception as e:
        logger.exception(f"生成卡通地图异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"生成卡通地图失败: {str(e)}", code="ERROR"
        )


@router.get("/map-styles", response_model=ApiResponse, summary="获取支持的地图风格列表")
async def get_map_styles():
    """
    获取支持的地图风格列表
    
    Returns:
        支持的地图风格列表
    """
    styles = [
        {
            "id": "cartoon",
            "name": "卡通",
            "description": "经典卡通风格，边缘增强+颜色量化",
            "icon": "🎨"
        },
        {
            "id": "sketch",
            "name": "素描",
            "description": "铅笔素描风格，黑白线条",
            "icon": "✏️"
        },
        {
            "id": "watercolor",
            "name": "水彩",
            "description": "水彩画风格，柔和的色彩扩散",
            "icon": "🖌️"
        },
        {
            "id": "pixel",
            "name": "像素",
            "description": "像素艺术风格，复古游戏感",
            "icon": "👾"
        }
    ]
    
    return ApiResponse(
        success=True,
        data={"styles": styles},
        message="获取成功"
    )
