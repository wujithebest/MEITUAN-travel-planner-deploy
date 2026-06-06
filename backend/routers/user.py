"""
用户资料路由 - 处理用户资料的获取和更新
"""
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional
from pydantic import BaseModel, Field

from models.user import UserProfile, UserProfileUpdate, UsernameCheckResponse, UserPreferences, PoiInteractionRecord
from routers.auth import get_current_user
from services.user_service import UserService
from services.poi_feedback_service import record_poi_preference
from models.mongodb import UserMongoDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user", tags=["用户资料"])


@router.get("/profile", response_model=UserProfile)
async def get_user_profile(
    current_user: dict = Depends(get_current_user)
):
    """
    获取当前用户的完整资料
    
    返回用户的完整资料信息，包括：
    - 基本信息：id, username, email, avatar, bio, phone
    - 位置信息：city, district, address, latitude, longitude
    - 偏好设置：transport_modes, interests, budget_range, travel_pace, dietary_restrictions
    """
    try:
        user_profile = await UserService.get_user_profile(current_user["id"])
        if not user_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        return user_profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 获取用户资料失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户资料失败"
        )


@router.put("/profile", response_model=UserProfile)
async def update_user_profile(
    update_data: UserProfileUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    更新当前用户的资料
    
    支持更新的字段：
    - username: 用户名（2-20字符，唯一）
    - bio: 个人简介（最多500字符）
    - avatar: 头像URL
    - phone: 手机号
    - location: 位置信息（city, district, address, latitude, longitude）
    - preferences: 偏好设置（transport_modes, interests, budget_range, travel_pace, dietary_restrictions）
    
    注意：
    - 用户名修改时会检查唯一性
    - email 不可通过此接口修改
    - 所有字段均为可选，未提供的字段保持不变
    """
    try:
        updated_profile = await UserService.update_user_profile(
            current_user["id"],
            update_data
        )
        if not updated_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        return updated_profile
    except ValueError as e:
        # 用户名已存在等验证错误
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 更新用户资料失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新用户资料失败"
        )


@router.get("/check-username", response_model=UsernameCheckResponse)
async def check_username(
    username: str = Query(..., description="要检查的用户名"),
    current_user: dict = Depends(get_current_user)
):
    """
    检查用户名是否可用
    
    用于在修改用户名前进行前端验证
    
    返回：
    - available: 是否可用
    - message: 提示信息
    """
    try:
        result = await UserService.check_username_availability(
            username,
            exclude_user_id=current_user["id"]
        )
        return UsernameCheckResponse(**result)
    except Exception as e:
        logger.error(f"[UserRouter] 检查用户名失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="检查用户名失败"
        )


@router.patch("/profile/location", response_model=UserProfile)
async def update_user_location(
    location: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    仅更新用户位置信息
    
    支持的位置字段：
    - city: 城市
    - district: 区县
    - address: 详细地址
    - latitude: 纬度
    - longitude: 经度
    """
    try:
        update_data = UserProfileUpdate(location=location)
        updated_profile = await UserService.update_user_profile(
            current_user["id"],
            update_data
        )
        if not updated_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        return updated_profile
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 更新位置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新位置失败"
        )


@router.patch("/profile/preferences", response_model=UserProfile)
async def update_user_preferences(
    preferences: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    仅更新用户偏好设置
    
    支持的偏好字段：
    - transport_modes: 偏好交通方式列表
    - interests: 兴趣标签列表
    - budget_range: 预算范围（low/medium/high）
    - travel_pace: 旅行节奏（relaxed/moderate/intensive）
    - dietary_restrictions: 饮食限制列表
    """
    try:
        update_data = UserProfileUpdate(preferences=preferences)
        updated_profile = await UserService.update_user_profile(
            current_user["id"],
            update_data
        )
        if not updated_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        return updated_profile
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 更新偏好失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新偏好失败"
        )


class PoiActionRequest(BaseModel):
    """POI 交互操作请求"""
    poi_name: str = Field(..., description="POI 名称")
    poi_type: str = Field("", description="POI 分类")
    action: str = Field(..., description="like | dislike | remove | delete | add")
    poi_id: str = Field("", description="POI ID")
    route_id: str | None = None
    timestamp: int | float | str | None = None


@router.post("/preferences/poi-action")
async def record_poi_action(
    req: PoiActionRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    记录 POI 交互操作，更新用户偏好中的 POI 记录

    - like: 喜欢的 POI，记录到 poi_likes
    - dislike: 不喜欢的 POI，记录到 poi_dislikes，hit_count 递增
    - remove: 从路线移除的 POI，记录到 poi_removes
    """
    try:
        result = await record_poi_preference(
            user_id=current_user["id"],
            poi_id=req.poi_id,
            poi_name=req.poi_name,
            poi_type=req.poi_type,
            action=req.action,
            route_id=req.route_id,
            timestamp=req.timestamp or datetime.utcnow().timestamp(),
        )
        return {"success": True, "message": "POI preference updated", **result}

        user = await UserMongoDB.get_by_id(current_user["id"])
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

        prefs = user.get("preferences", {}) or {}

        action_field = {"like": "poi_likes", "dislike": "poi_dislikes", "remove": "poi_removes", "add": "poi_likes"}.get(req.action)
        if not action_field:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"无效的 action: {req.action}")

        records = prefs.get(action_field, [])

        existing = None
        for r in records:
            if r.get("poi_name") == req.poi_name and r.get("poi_type") == req.poi_type:
                existing = r
                break

        if existing:
            existing["hit_count"] = existing.get("hit_count", 1) + 1
            existing["timestamp"] = datetime.utcnow().isoformat()
        else:
            records.append({
                "poi_name": req.poi_name,
                "poi_type": req.poi_type,
                "action": req.action,
                "timestamp": datetime.utcnow().isoformat(),
                "hit_count": 1
            })

        prefs[action_field] = records

        await UserMongoDB.update_preferences(current_user["id"], prefs)

        return {"success": True, "message": "POI 交互记录已更新", action_field: records}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 记录 POI 交互失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="记录 POI 交互失败")


# ═══════════════════════════════════════════════════════════════
# 路线收藏
# ═══════════════════════════════════════════════════════════════

class FavoriteCreateRequest(BaseModel):
    """创建收藏路线请求"""
    title: str = Field("", description="路线标题")
    destination: str = Field("上海", description="目的地")
    days: int = Field(1, description="天数")
    route_id: str | None = None
    route_hash: str = Field(..., description="去重 hash")
    complete_plan: dict | None = None
    route_data: dict | None = None
    panel_days: list | None = None
    map_route_data: dict | None = None
    poi_details: dict | None = None
    summary: dict | None = None


@router.get("/favorites")
async def get_favorites(
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户的路线收藏列表（按更新时间倒序）"""
    try:
        favorites = await UserMongoDB.get_favorite_routes(current_user["id"])
        return {"success": True, "data": favorites, "message": "获取收藏列表成功"}
    except Exception as e:
        logger.error(f"[UserRouter] 获取收藏列表失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取收藏列表失败")


@router.post("/favorites")
async def create_favorite(
    req: FavoriteCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """创建或更新路线收藏（route_hash 去重）"""
    try:
        if not req.complete_plan and not req.route_data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少需要 complete_plan 或 route_data")

        # 日志：打印收藏数据量
        rp_len = len(req.route_data.get("points", [])) if req.route_data else 0
        rs_len = len(req.route_data.get("segments", [])) if req.route_data else 0
        mp_len = len(req.map_route_data.get("polylines", [])) if req.map_route_data else 0
        pd = req.poi_details or {}
        pd_photo = sum(1 for d in pd.values() if isinstance(d, dict) and d.get("photo_url"))
        pd_rating = sum(1 for d in pd.values() if isinstance(d, dict) and d.get("rating") is not None)
        pd_addr = sum(1 for d in pd.values() if isinstance(d, dict) and d.get("address"))
        logger.info(f"[Favorites] 保存收藏: routePoints={rp_len} routeSegments={rs_len} mapPolylines={mp_len} poiDetails={len(pd)} withPhoto={pd_photo} withRating={pd_rating} withAddress={pd_addr} title={req.title}")

        favorite = req.model_dump(exclude_none=True)
        result = await UserMongoDB.add_favorite_route(current_user["id"], favorite)
        return {"success": True, "data": result, "message": "收藏成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 创建收藏失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建收藏失败")


@router.delete("/favorites/{favorite_id}")
async def delete_favorite(
    favorite_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除指定收藏路线"""
    try:
        deleted = await UserMongoDB.delete_favorite_route(current_user["id"], favorite_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="收藏路线不存在")
        return {"success": True, "message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 删除收藏失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除收藏失败")


# ==================== 规划历史 ====================

@router.get("/route-histories")
async def get_route_histories(
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户的规划历史列表（按创建时间倒序）"""
    try:
        histories = await UserMongoDB.get_route_histories(current_user["id"])
        logger.info(f"[RouteHistory] list: user_id={current_user['id']} count={len(histories)}")
        return {"success": True, "data": histories, "message": "获取规划历史成功"}
    except Exception as e:
        logger.error(f"[UserRouter] 获取规划历史失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取规划历史失败")


@router.post("/route-histories")
async def create_route_history(
    req: dict,
    current_user: dict = Depends(get_current_user)
):
    """创建规划历史记录"""
    try:
        rp_len = len(req.get("route_data", {}).get("points", []))
        rs_len = len(req.get("route_data", {}).get("segments", []))
        mp_len = len(req.get("map_route_data", {}).get("polylines", [])) if req.get("map_route_data") else 0
        pd = req.get("poi_details") or {}
        msgs = len(req.get("messages", []))
        title = req.get("title", "")
        logger.info(f"[RouteHistory] save: routePoints={rp_len} routeSegments={rs_len} mapPolylines={mp_len} panelDays={len(req.get('panel_days', []))} messages={msgs} poiDetails={len(pd)} title={title}")
        result = await UserMongoDB.add_route_history(current_user["id"], req)
        return {"success": True, "data": result, "message": "历史保存成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 保存规划历史失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="保存规划历史失败")


@router.delete("/route-histories/{history_id}")
async def delete_route_history(
    history_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除指定规划历史"""
    try:
        logger.info(f"[RouteHistory] delete: user_id={current_user['id']} history_id={history_id}")
        deleted = await UserMongoDB.delete_route_history(current_user["id"], history_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规划历史不存在")
        return {"success": True, "message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UserRouter] 删除规划历史失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除规划历史失败")


@router.delete("/route-histories")
async def clear_route_histories(
    current_user: dict = Depends(get_current_user)
):
    """清空所有规划历史"""
    try:
        await UserMongoDB.clear_route_histories(current_user["id"])
        return {"success": True, "message": "清空规划历史成功"}
    except Exception as e:
        logger.error(f"[UserRouter] 清空规划历史失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="清空规划历史失败")
