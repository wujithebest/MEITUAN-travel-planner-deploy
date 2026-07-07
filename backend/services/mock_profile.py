from __future__ import annotations
import os
import asyncio
import logging

from .data_schema import UserProfile

logger = logging.getLogger(__name__)

# 尝试导入 MongoDB 模型
try:
    from models.mongodb import UserMongoDB
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False
    UserMongoDB = None


async def get_user_home_location(user_id: str = None) -> dict[str, float | str]:
    """从数据库获取用户设置的常住地址
    
    优先从MongoDB读取，失败则降级使用环境变量
    
    Args:
        user_id: 用户ID，如果提供则从数据库读取该用户的地址
    
    Returns:
        地址字典 {"lat": float, "lng": float, "label": str}
    """
    if not user_id:
        return _env_home_location()
    
    # 从 MongoDB 读取
    if MONGODB_AVAILABLE and UserMongoDB is not None:
        try:
            user = await UserMongoDB.get_by_id(user_id)
            if user:
                location_data = user.get("location", {})
                if location_data:
                    # 尝试获取 home_address
                    home_address = location_data.get("home_address")
                    if home_address:
                        lat = home_address.get("lat")
                        lng = home_address.get("lng")
                        if lat is not None and lng is not None:
                            return {
                                "lat": float(lat),
                                "lng": float(lng),
                                "label": home_address.get("name", "家"),
                            }
                    # 尝试获取经纬度
                    lat = location_data.get("latitude")
                    lng = location_data.get("longitude")
                    if lat is not None and lng is not None:
                        return {
                            "lat": float(lat),
                            "lng": float(lng),
                            "label": location_data.get("address", "当前位置"),
                        }
        except Exception as e:
            logger.warning(f"从数据库读取用户地址失败: {e}，降级使用环境变量")
    else:
        logger.info("[MockProfile] MongoDB 不可用，使用环境变量获取用户地址")
    
    # 降级：从环境变量读取
    return _env_home_location()


def _env_home_location() -> dict[str, float | str]:
    """从环境变量读取（兼容原有逻辑）"""
    lat = os.getenv("ROUTE_PLANNER_HOME_LAT")
    lng = os.getenv("ROUTE_PLANNER_HOME_LNG")
    label = os.getenv("ROUTE_PLANNER_HOME_LABEL")
    
    if lat and lng:
        return {
            "lat": float(lat),
            "lng": float(lng),
            "label": label or "家",
        }
    
    # 默认地址
    return {
        "lat": 31.2809,
        "lng": 121.5011,
        "label": "同济大学四平路校区",
    }


# 同步包装函数（供非异步代码调用）
def get_home_location_sync(user_id: str = None) -> dict[str, float | str]:
    """同步获取家位置"""
    try:
        loop = asyncio.get_running_loop()
        # 如果已经在事件循环中，使用默认地址（避免嵌套事件循环错误）
        return {
            "lat": 31.2809,
            "lng": 121.5011,
            "label": "同济大学四平路校区",
        }
    except RuntimeError:
        # 没有运行中的事件循环，可以安全地创建一个新的
        return asyncio.run(get_user_home_location(user_id))


def _env_device_location() -> dict[str, float | str]:
    lat = os.getenv("ROUTE_PLANNER_DEVICE_LAT")
    lng = os.getenv("ROUTE_PLANNER_DEVICE_LNG")
    label = os.getenv("ROUTE_PLANNER_DEVICE_LABEL")
    if lat and lng:
        return {
            "lat": float(lat),
            "lng": float(lng),
            "label": label or "当前设备位置",
        }
    return {
        "lat": 31.2809,
        "lng": 121.5011,
        "label": "同济大学四平路校区",
    }


async def get_mock_profile(user_id: str = None) -> UserProfile:
    """获取用户画像，支持传入 user_id 读取个性化设置
    
    Args:
        user_id: 用户ID，如果提供则从数据库读取用户设置的常住地址
    
    Returns:
        UserProfile 实例
    """
    home_loc = await get_user_home_location(user_id)
    default_city = os.getenv("ROUTE_PLANNER_DEFAULT_CITY", "")
    default_district = os.getenv("ROUTE_PLANNER_DEFAULT_DISTRICT", "")
    perm_city = [default_city, default_district] if default_city else []
    return UserProfile(
        nickname="小明",
        gender="男",
        age=30,
        activity_pref_tag=["文艺", "历史"],         # 兴趣标签，不会在request中主动表达时自动注入搜索
        food_pref_tag=["本帮菜", "咖啡"],           # 口味偏好，request未提餐饮偏好时注入餐饮搜索
        permanent_city=perm_city,                    # 从环境变量读取，默认空
        permanent_city_coord={"lat": home_loc.get("lat", 31.2809), "lng": home_loc.get("lng", 121.5011)},
        current_device_location=None,                     # v18: 不再作为独立出发地
        home_location=home_loc,                      # ← 异步获取个性化地址（唯一出发地来源）
        budget_per_capita=100.0,                     # 人均消费预算（元），阈值=100*1.5=150元
    )


def build_profile_from_guest(guest: dict) -> UserProfile:
    """从游客前端画像构建 UserProfile。

    当用户以游客模式使用应用时，前端将用户在设置中编辑的画像数据通过
    guest_profile 字段传入后端，后端据此构建 UserProfile 而非使用硬编码兜底。

    v18: home_location 为唯一路线出发地来源。
    """

    home_loc = guest.get("home_location") or {}
    FALLBACK_LAT = 31.2809
    FALLBACK_LNG = 121.5011

    # 统一使用 home_location 作为位置来源
    resolved_lat = home_loc.get("lat", FALLBACK_LAT)
    resolved_lng = home_loc.get("lng", FALLBACK_LNG)
    resolved_label = home_loc.get("label", "同济大学四平路校区")

    resolved_home = {
        "lat": resolved_lat,
        "lng": resolved_lng,
        "label": resolved_label,
    }
    for key in ("city", "cityname", "adcode", "district", "province"):
        if home_loc.get(key) not in (None, ""):
            resolved_home[key] = home_loc[key]

    return UserProfile(
        nickname=guest.get("nickname", "游客"),
        gender=guest.get("gender", "男"),
        age=guest.get("age", 30),
        activity_pref_tag=guest.get("activity_pref_tag", ["文艺", "历史"]),
        food_pref_tag=guest.get("food_pref_tag", ["本帮菜", "咖啡"]),
        # city 后续由 Step2 基于 home_location 自动解析，不再信任前端手动 city
        permanent_city=[],
        # v18: permanent_city_coord = home_location 坐标，不再降级到 current_device
        permanent_city_coord=guest.get("permanent_city_coord") or {"lat": resolved_lat, "lng": resolved_lng},
        # v18: current_device_location 不再作为独立出发地
        current_device_location=None,
        home_location=resolved_home,
        budget_per_capita=guest.get("budget_per_capita", 100.0),
        # v21: Structured preference profile
        preference_profile=_build_preference_profile(guest),
    )


def _build_preference_profile(guest: dict) -> "UserPreferenceProfile | None":
    """Build UserPreferenceProfile from guest dict, with backward compat."""
    from .data_schema import UserPreferenceProfile
    pp = guest.get("preference_profile") or {}
    if isinstance(pp, UserPreferenceProfile):
        return pp
    if not isinstance(pp, dict) or not pp:
        # Fallback: convert old array preferences to interests
        old_prefs = guest.get("preferences") or guest.get("activity_pref_tag") or []
        if old_prefs and isinstance(old_prefs, list):
            return UserPreferenceProfile(interests=list(old_prefs))
        return None
    return UserPreferenceProfile(
        interests=list(pp.get("interests", []) or []),
        cuisine_preferences=list(pp.get("cuisine_preferences", []) or []),
        dietary_restrictions=list(pp.get("dietary_restrictions", []) or []),
        ambience_preferences=list(pp.get("ambience_preferences", []) or []),
        travel_pace=str(pp.get("travel_pace", "moderate") or "moderate"),
        crowd_tolerance=str(pp.get("crowd_tolerance", "moderate") or "moderate"),
        walking_tolerance=str(pp.get("walking_tolerance", "moderate") or "moderate"),
        companion_types=list(pp.get("companion_types", []) or []),
        avoid_tags=list(pp.get("avoid_tags", []) or []),
    )
