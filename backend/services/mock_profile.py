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
        food_pref_tag=[],                             # v28: empty by default
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
    v26: All guest data is normalized at the boundary — lists, empty objects, and
    other bad shapes cannot leak into UserProfile and cause Pydantic ValidationError.
    """

    FALLBACK_LAT = 31.2809
    FALLBACK_LNG = 121.5011
    FALLBACK_LABEL = "同济大学四平路校区"

    # ── v26: input normalization helpers ──

    def _coerce_float(value, fallback: float) -> float:
        """Accept int/float/numeric string; reject list/dict/None/NaN/empty → fallback."""
        if value is None:
            return fallback
        if isinstance(value, (list, dict)):
            return fallback
        if isinstance(value, bool):
            return fallback
        try:
            v = float(value)
            if not math.isfinite(v):
                return fallback
            return v
        except (ValueError, TypeError):
            return fallback

    def _coerce_label(value, *fallbacks: str) -> str:
        """Return a non-empty stripped string from value or the first non-empty fallback."""
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
        # numeric → use fallback (a bare number is not a readable label)
        for fb in fallbacks:
            if isinstance(fb, str) and fb.strip():
                return fb.strip()
        return FALLBACK_LABEL

    def _normalize_home_location(raw) -> dict[str, float | str]:
        """Normalize a raw home_location input into a guaranteed-valid dict."""
        if not isinstance(raw, dict):
            raw = {}
        lat = _coerce_float(raw.get("lat"), FALLBACK_LAT)
        lng = _coerce_float(raw.get("lng"), FALLBACK_LNG)
        label = _coerce_label(
            raw.get("label"),
            raw.get("name"),
            raw.get("full_address"),
            raw.get("address"),
            FALLBACK_LABEL,
        )
        resolved: dict[str, float | str] = {
            "lat": lat,
            "lng": lng,
            "label": label,
        }
        # Only copy string/int/float scalar metadata keys — never lists or dicts
        for key in ("city", "cityname", "adcode", "district", "province", "source"):
            val = raw.get(key)
            if isinstance(val, (str, int, float)) and val not in (None, ""):
                resolved[key] = str(val) if isinstance(val, (int, float)) else val
        return resolved

    import math  # ensure available in closure scope

    # ── build normalized profile ──

    resolved_home = _normalize_home_location(guest.get("home_location"))

    # Normalize permanent_city_coord — reject non-dict / bad lat/lng
    _pcc = guest.get("permanent_city_coord")
    if isinstance(_pcc, dict):
        _pcc_lat = _coerce_float(_pcc.get("lat"), resolved_home["lat"])  # type: ignore[arg-type]
        _pcc_lng = _coerce_float(_pcc.get("lng"), resolved_home["lng"])  # type: ignore[arg-type]
    else:
        _pcc_lat = float(resolved_home["lat"])
        _pcc_lng = float(resolved_home["lng"])
    permanent_city_coord = {"lat": _pcc_lat, "lng": _pcc_lng}

    # Normalize tag lists — ensure they are list[str]
    def _coerce_str_list(value, default: list[str]) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item is not None and str(item).strip()]
        if isinstance(value, (str, int, float)):
            s = str(value).strip()
            return [s] if s else default
        return default

    activity_pref_tag = _coerce_str_list(guest.get("activity_pref_tag"), ["文艺", "历史"])
    food_pref_tag = _coerce_str_list(guest.get("food_pref_tag"), [])

    # Normalize budget — must be a positive number
    _raw_budget = guest.get("budget_per_capita")
    budget_per_capita = _coerce_float(_raw_budget, 100.0)
    if budget_per_capita <= 0:
        budget_per_capita = 100.0

    return UserProfile(
        nickname=str(guest.get("nickname", "游客") or "游客"),
        gender=str(guest.get("gender", "男") or "男"),
        age=max(1, min(120, int(_coerce_float(guest.get("age"), 30)))),
        activity_pref_tag=activity_pref_tag,
        food_pref_tag=food_pref_tag,
        permanent_city=[],
        permanent_city_coord=permanent_city_coord,
        current_device_location=None,
        home_location=resolved_home,
        budget_per_capita=budget_per_capita,
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
