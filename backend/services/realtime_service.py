"""
实时数据服务 - 上海专用
提供上海交通路况和天气数据
天气仅查询上海（cityid=101020100或location=121.4737,31.2304）
支持Redis缓存和内存缓存降级
"""

import json
import logging
from typing import Optional
from datetime import date, datetime, timedelta

import httpx
from cachetools import TTLCache

from config import get_settings
from models.base import WeatherInfo
from exceptions import GaodeAPIError, WeatherAPIError

logger = logging.getLogger(__name__)

# 上海天气城市ID（和风天气）
SHANGHAI_CITY_ID = "101020100"
# 上海中心坐标
SHANGHAI_LOCATION = "121.4737,31.2304"

# 天气内存缓存：1小时过期
_weather_cache: TTLCache = TTLCache(maxsize=500, ttl=3600)
# 交通内存缓存：5分钟过期
_traffic_cache: TTLCache = TTLCache(maxsize=200, ttl=300)


class RealtimeService:
    """实时数据服务：上海天气 + 上海交通路况"""

    def __init__(self):
        self.settings = get_settings()
        self.weather_key = self.settings.weather_key
        self.gaode_key = self.settings.gaode_key
        self.timeout = 10.0

    # ==================== 上海天气服务 ====================

    async def get_weather_forecast(
        self, city: str = "上海", days: int = 7
    ) -> list[WeatherInfo]:
        """
        获取上海逐日天气预报（和风天气API）
        固定查询上海天气（cityid=101020100）
        缓存1小时，雨天优先室内，高温减少户外，大风取消高空项目
        
        Args:
            city: 城市名称（忽略，固定为上海）
            days: 预报天数
            
        Returns:
            list[WeatherInfo]: 天气信息列表
        """
        cache_key = f"forecast:上海"
        if cache_key in _weather_cache:
            logger.info("天气缓存命中: 上海")
            return _weather_cache[cache_key]

        try:
            # 获取逐日预报 - 使用上海固定cityid
            forecast_url = "https://dev.qweather.com/v7/weather/7d"
            forecast_params = {
                "key": self.weather_key,
                "location": SHANGHAI_CITY_ID  # 上海固定cityid
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(forecast_url, params=forecast_params)
                
                # 防御式编程：处理403/401/404等错误
                if resp.status_code in [403, 401, 404]:
                    logger.warning(f"天气API请求失败: {resp.status_code}，降级为静态提示")
                    return self._get_static_weather(days)
                
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") != "200":
                logger.warning(f"天气API返回错误: {data.get('code')}，使用静态提示")
                return self._get_static_weather(days)

            weather_list = []
            for daily in data.get("daily", [])[:days]:
                weather = WeatherInfo(
                    forecast_date=date.fromisoformat(daily.get("fxDate", "")),
                    city="上海",  # 固定上海
                    text_day=daily.get("textDay", ""),
                    text_night=daily.get("textNight", ""),
                    temp_high=float(daily.get("tempMax", 0)),
                    temp_low=float(daily.get("tempMin", 0)),
                    wind_level=int(daily.get("windScaleDay", 0)),
                    wind_direction=daily.get("windDirDay", ""),
                    humidity=float(daily.get("humidity", 0)),
                    rain_probability=float(daily.get("precip", 0)),
                    is_rainy="雨" in daily.get("textDay", "") or "雨" in daily.get("textNight", ""),
                    is_high_temp=float(daily.get("tempMax", 0)) > 35,
                    is_strong_wind=int(daily.get("windScaleDay", 0)) >= 6,
                    indoor_recommended="雨" in daily.get("textDay", "") or float(daily.get("tempMax", 0)) > 38,
                    weather_tip=self._generate_daily_tip(daily)
                )
                weather_list.append(weather)

            _weather_cache[cache_key] = weather_list
            logger.info(f"获取上海天气成功: {len(weather_list)}天")
            return weather_list

        except Exception as e:
            logger.warning(f"天气API调用失败: {str(e)}，降级为静态提示")
            return self._get_static_weather(days)

    async def get_current_weather(self, city: str = "上海") -> WeatherInfo:
        """
        获取上海当前天气
        固定查询上海
        """
        cache_key = f"current:上海"
        if cache_key in _weather_cache:
            return _weather_cache[cache_key]

        try:
            # 使用上海固定cityid
            url = "https://dev.qweather.com/v7/weather/now"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params={
                    "key": self.weather_key,
                    "location": SHANGHAI_CITY_ID
                })
                
                # 防御式编程：处理403/401/404等错误
                if resp.status_code in [403, 401, 404]:
                    logger.warning(f"天气API请求失败: {resp.status_code}，降级为静态提示")
                    return self._get_static_current_weather()
                
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") != "200":
                return self._get_static_current_weather()

            now = data.get("now", {})
            weather = WeatherInfo(
                forecast_date=date.today(),
                city="上海",  # 固定上海
                text_day=now.get("text", ""),
                text_night="",
                temp_high=float(now.get("temp", 0)),
                temp_low=float(now.get("temp", 0)),
                wind_level=int(now.get("windScale", 0)),
                wind_direction=now.get("windDir", ""),
                humidity=float(now.get("humidity", 0)),
                rain_probability=0,
                is_rainy="雨" in now.get("text", ""),
                is_high_temp=float(now.get("temp", 0)) > 35,
                is_strong_wind=int(now.get("windScale", 0)) >= 6,
                indoor_recommended="雨" in now.get("text", ""),
                weather_tip=self._generate_current_tip(now)
            )

            _weather_cache[cache_key] = weather
            return weather

        except Exception as e:
            logger.warning(f"上海当前天气获取失败: {str(e)}")
            return self._get_static_current_weather()

    def _generate_daily_tip(self, daily: dict) -> str:
        """生成每日天气提示"""
        tips = []
        text = daily.get("textDay", "")
        temp_max = float(daily.get("tempMax", 0))
        wind_scale = int(daily.get("windScaleDay", 0))

        if "雨" in text:
            tips.append("有雨，建议携带雨具，优先安排室内活动（博物馆/商场）")
        if temp_max > 35:
            tips.append(f"高温{temp_max}℃，注意防暑降温，减少户外步行")
        if wind_scale >= 6:
            tips.append(f"风力{wind_scale}级，注意安全，取消高空项目")
        if not tips:
            tips.append("天气适宜出行")

        return "; ".join(tips)

    def _generate_current_tip(self, now: dict) -> str:
        """生成当前天气提示"""
        tips = []
        text = now.get("text", "")
        temp = float(now.get("temp", 0))
        wind_scale = int(now.get("windScale", 0))

        if "雨" in text:
            tips.append("当前有雨，建议携带雨具")
        if temp > 35:
            tips.append(f"当前{temp}℃，注意防暑")
        if wind_scale >= 6:
            tips.append(f"风力较大({wind_scale}级)，注意安全")

        return "; ".join(tips) if tips else "天气适宜"

    def _get_static_weather(self, days: int) -> list[WeatherInfo]:
        """降级：返回上海静态天气提示"""
        result = []
        base_date = date.today()
        for i in range(days):
            d = base_date + timedelta(days=i)
            result.append(WeatherInfo(
                forecast_date=d,
                city="上海",
                text_day="未知",
                text_night="未知",
                temp_high=25.0,
                temp_low=18.0,
                wind_level=2,
                wind_direction="东南",
                humidity=60.0,
                rain_probability=0,
                is_rainy=False,
                is_high_temp=False,
                is_strong_wind=False,
                indoor_recommended=False,
                weather_tip="上海天气数据暂不可用，出行前请关注最新预报"
            ))
        return result

    def _get_static_current_weather(self) -> WeatherInfo:
        """降级：返回上海静态当前天气"""
        return WeatherInfo(
            forecast_date=date.today(),
            city="上海",
            text_day="未知",
            text_night="未知",
            temp_high=25.0,
            temp_low=25.0,
            wind_level=2,
            wind_direction="东南",
            humidity=60.0,
            rain_probability=0,
            is_rainy=False,
            is_high_temp=False,
            is_strong_wind=False,
            indoor_recommended=False,
            weather_tip="上海天气数据暂不可用"
        )

    # ==================== 上海交通路况服务 ====================

    async def get_traffic(self, city: str = "上海", bounds: str = "") -> dict:
        """
        获取上海实时交通路况（高德API）
        解析tmcs字段，Redis缓存5分钟
        
        Args:
            city: 城市名称（忽略，固定为上海）
            bounds: 边界范围 "lng,lat;lng,lat"
            
        Returns:
            dict: 路况信息
        """
        cache_key = "traffic:上海"
        if cache_key in _traffic_cache:
            logger.info("交通缓存命中: 上海")
            return _traffic_cache[cache_key]

        try:
            url = "https://restapi.amap.com/v3/traffic/status/city"
            params = {
                "key": self.gaode_key,
                "city": "上海",  # 固定上海
                "output": "JSON"
            }
            if bounds:
                params["bounds"] = bounds

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            if data.get("status") != "1":
                logger.warning(f"交通API返回错误: {data.get('info')}")
                return {"status": "unknown", "description": "上海交通数据暂不可用"}

            traffic_info = {
                "status": data.get("status"),
                "description": data.get("info", ""),
                "evaluation": data.get("trafficinfo", {}).get("evaluation", {}),
                "roads": []
            }

            # 解析道路路况
            for road in data.get("trafficinfo", {}).get("roads", []):
                traffic_info["roads"].append({
                    "name": road.get("name", ""),
                    "status": road.get("status", ""),  # 0=未知,1=畅通,2=缓行,3=拥堵,4=严重拥堵
                    "direction": road.get("direction", ""),
                    "speed": road.get("speed", 0),
                    "polyline": road.get("polyline", "")
                })

            _traffic_cache[cache_key] = traffic_info
            logger.info("获取上海交通路况成功")
            return traffic_info

        except Exception as e:
            logger.warning(f"交通API调用失败: {str(e)}")
            return {"status": "unknown", "description": "上海交通数据暂不可用"}


_realtime_service: Optional[RealtimeService] = None


def get_realtime_service() -> RealtimeService:
    """获取实时数据服务单例"""
    global _realtime_service
    if _realtime_service is None:
        _realtime_service = RealtimeService()
    return _realtime_service
