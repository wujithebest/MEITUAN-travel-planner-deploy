"""
天气路由 - 上海专用
固定返回上海天气
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query
import httpx

from models.base import ApiResponse
from services.realtime_service import get_realtime_service
from services.gaode_service import get_gaode_service
from services.api_client import gaode_reverse_geocode, gaode_weather_live

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/weather", tags=["天气"])


def _weather_temperature(weather) -> int:
    if not weather:
        return 25
    value = getattr(weather, "temp_high", None)
    if value is None:
        value = getattr(weather, "temp_low", 25)
    return int(round(float(value or 25)))


def _weather_text(weather) -> str:
    if not weather:
        return "晴"
    return getattr(weather, "text_day", None) or getattr(weather, "text_night", None) or "晴"


@router.get("/shanghai", response_model=ApiResponse, summary="获取上海天气预报")
async def get_shanghai_forecast(
    days: int = Query(7, ge=1, le=15, description="预报天数")
):
    """
    获取上海天气预报（固定）
    无论传入什么参数，都返回上海天气
    """
    try:
        service = get_realtime_service()
        forecast = await service.get_weather_forecast("上海", days=days)

        return ApiResponse(
            success=True,
            data=[w.model_dump(mode='json') for w in forecast],
            message=f"获取上海{days}天天气预报成功"
        )
    except Exception as e:
        logger.exception(f"上海天气预报获取异常: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"上海天气预报获取失败: {str(e)}",
            code="WEATHER_ERROR"
        )


@router.get("/current", response_model=ApiResponse, summary="获取当前天气（需提供坐标）")
async def get_current_weather(
    lat: float = Query(None, description="纬度"),
    lng: float = Query(None, description="经度"),
):
    """获取当前天气。请优先使用 /api/weather/location 接口。"""
    if lat is None or lng is None:
        return ApiResponse(
            success=False,
            data=None,
            message="请提供 lat 和 lng 参数，或使用 /api/weather/location 接口",
            code="MISSING_PARAMS"
        )
    try:
        service = get_realtime_service()
        weather = await service.get_current_weather(f"{lng},{lat}")

        return ApiResponse(
            success=True,
            data=weather.model_dump(),
            message="获取当前天气成功"
        )
    except Exception as e:
        logger.exception(f"当前天气获取异常: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"当前天气获取失败: {str(e)}",
            code="WEATHER_ERROR"
        )


@router.get("/traffic", response_model=ApiResponse, summary="获取上海实时交通路况")
async def get_traffic(
    bounds: str = Query("", description="边界范围 lng,lat;lng,lat")
):
    """获取上海实时交通路况（固定）"""
    try:
        service = get_realtime_service()
        traffic = await service.get_traffic("上海", bounds=bounds)

        return ApiResponse(
            success=True,
            data=traffic,
            message="获取上海交通路况成功"
        )
    except Exception as e:
        logger.exception(f"上海交通路况获取异常: {str(e)}")
        return ApiResponse(
            success=False,
            data=None,
            message=f"上海交通路况获取失败: {str(e)}",
            code="TRAFFIC_ERROR"
        )


@router.get("/location", response_model=ApiResponse, summary="根据设备位置获取天气实况（高德）")
async def get_location_weather(
    lat: float = Query(..., description="纬度"),
    lng: float = Query(..., description="经度"),
):
    """
    根据设备经纬度，通过高德逆地理编码获取 adcode，
    再调用高德天气实况接口（extensions=base）获取实时天气。
    失败时返回 success=false，不降级到假数据。
    """
    location_str = f"{lng},{lat}"

    # Step 1: 逆地理编码获取 adcode + 城市名
    try:
        addr_comp = await gaode_reverse_geocode(location_str)
    except Exception as e:
        logger.warning(f"逆地理编码失败: {e}")
        return ApiResponse(
            success=False,
            data=None,
            message="无法获取当前位置的城市信息，请稍后重试",
            code="GEOCODE_ERROR",
        )

    if not addr_comp:
        return ApiResponse(
            success=False,
            data=None,
            message="无法获取当前位置的城市信息",
            code="GEOCODE_EMPTY",
        )

    adcode = addr_comp.get("adcode") or ""
    city_raw = addr_comp.get("city") or ""
    district = addr_comp.get("district") or ""
    province = addr_comp.get("province") or ""

    # 直辖市（北京/天津/上海/重庆）city 可能为空，用 province 或 district
    if not city_raw:
        city = district or province or ""
    else:
        city = city_raw
    # 去掉"市"后缀
    if city.endswith("市"):
        city = city[:-1]

    if not adcode:
        return ApiResponse(
            success=False,
            data=None,
            message="无法获取当前城市的区划代码",
            code="ADCODE_EMPTY",
        )

    # Step 2: 高德天气实况
    try:
        live = await gaode_weather_live(adcode)
    except Exception as e:
        logger.exception(f"高德天气实况获取失败: {e}")
        return ApiResponse(
            success=False,
            data=None,
            message="天气服务暂时不可用，请稍后重试",
            code="WEATHER_ERROR",
        )

    if not live:
        return ApiResponse(
            success=False,
            data=None,
            message="该城市暂无天气实况数据",
            code="WEATHER_EMPTY",
        )

    # Step 3: 组装返回数据
    temperature = live.get("temperature") or live.get("temperature_float") or ""
    humidity = live.get("humidity") or live.get("humidity_float") or ""
    winddirection = live.get("winddirection") or ""
    windpower = live.get("windpower") or ""
    weather_text = live.get("weather") or ""
    reporttime = live.get("reporttime") or ""

    return ApiResponse(
        success=True,
        data={
            "city": city,
            "adcode": adcode,
            "weather": weather_text,
            "temperature": temperature,
            "humidity": humidity,
            "winddirection": winddirection,
            "windpower": windpower,
            "reporttime": reporttime,
            "source": "gaode",
        },
        message="获取天气实况成功",
    )
