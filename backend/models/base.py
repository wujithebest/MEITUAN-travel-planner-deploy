"""
基础模型定义
上海旅游规划系统专用
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal, Any, List, Dict
from datetime import datetime, date
from enum import Enum


# ==================== 枚举类型 ====================

class TransportMode(str, Enum):
    """交通方式枚举"""
    DRIVING = "driving"
    WALKING = "walking"
    TRANSIT = "transit"
    BICYCLING = "bicycling"


class OperationType(str, Enum):
    """协作操作类型枚举"""
    ADD = "add"
    REMOVE = "remove"
    REORDER = "reorder"
    UPDATE_TIME = "update_time"
    ADD_NOTE = "add_note"
    CHANGE_TRANSPORT = "change_transport"


class Permission(str, Enum):
    """协作权限枚举"""
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


# ==================== 基础模型 ====================



class POIPhoto(BaseModel):
    """POI照片模型"""
    title: Optional[str] = Field(None, description="照片标题")
    url: str = Field(..., description="照片URL")


class POIChild(BaseModel):
    """子POI模型（如商场内的店铺）"""
    id: str = Field("", description="子POI ID")
    name: str = Field("", description="子POI名称")
    location: str = Field("", description="坐标 lng,lat")
    address: Optional[str] = Field(None, description="地址")
    type: str = Field("", description="类型")
    rating: Optional[float] = Field(None, description="评分")


class POI(BaseModel):
    """兴趣点模型 - 上海专用（扩展版）"""
    id: str = Field("", description="POI 唯一标识")
    name: str = Field(..., description="POI 名称")
    address: str | None = Field(None, description="详细地址")
    location: str = Field("", description="经纬度，格式：lng,lat")
    city: str = Field("上海", description="城市（固定为上海）")
    district: str = Field("", description="所在区域（黄浦/徐汇/静安等）")
    type: str = Field("", description="POI 类型")
    rating: float = Field(0.0, description="评分")
    open_time: Optional[str] = Field(None, description="开放时间，如 09:00-18:00")
    close_time: Optional[str] = Field(None, description="关闭时间")
    ambiguity: bool = Field(False, description="是否存在歧义")
    duration_minutes: int = Field(60, description="建议游览时长 (分钟)")
    metro_hint: str = Field("", description="最近地铁站")
    
    # 新增扩展字段
    photos: list[POIPhoto] = Field(default_factory=list, description="照片列表")
    price: Optional[str] = Field(None, description="人均消费/价格区间")
    website: Optional[str] = Field(None, description="网站")
    biz_type: Optional[str] = Field(None, description="业务类型")
    tag: list[str] = Field(default_factory=list, description="标签列表")
    indoor: Optional[bool] = Field(None, description="是否室内")
    navi_poiid: Optional[str] = Field(None, description="高德POI ID")
    entr_location: Optional[str] = Field(None, description="入口坐标")
    exit_location: Optional[str] = Field(None, description="出口坐标")
    groupbuynum: Optional[int] = Field(None, description="团购数量")
    discountnum: Optional[int] = Field(None, description="优惠数量")
    event: Optional[str] = Field(None, description="活动信息")
    children: list[POIChild] = Field(default_factory=list, description="子POI列表")

class WeatherInfo(BaseModel):
    """天气信息模型 - 上海专用"""
    forecast_date: date = Field(..., description="日期")
    city: str = Field("上海", description="城市（固定为上海）")
    text_day: str = Field("", description="白天天气")
    text_night: str = Field("", description="夜间天气")
    temp_high: float = Field(0.0, description="最高温度 (℃)")
    temp_low: float = Field(0.0, description="最低温度 (℃)")
    wind_level: int = Field(0, description="风力等级")
    wind_direction: str = Field("", description="风向")
    humidity: float = Field(0.0, description="湿度 (%)")
    rain_probability: float = Field(0.0, description="降水概率 (%)")
    is_rainy: bool = Field(False, description="是否雨天")
    is_high_temp: bool = Field(False, description="是否高温 (>35℃)")
    is_strong_wind: bool = Field(False, description="是否大风 (>=6 级)")
    indoor_recommended: bool = Field(False, description="建议室内活动")
    weather_tip: str = Field("", description="天气提示")
    
    class Config:
        json_encoders = {
            date: lambda v: v.isoformat() if v else None
        }


class ApiResponse(BaseModel):
    """通用 API 响应"""
    success: bool = Field(True, description="是否成功")
    data: Optional[Any] = None
    message: str = Field("", description="提示信息")
    code: str = Field("OK", description="状态码")


class LocationInput(BaseModel):
    """地点输入模型 - 上海旅游规划专用"""
    text: str = Field(..., description="自然语言输入，如'外滩一日游'")
    start_date: Optional[date] = Field(None, description="行程开始日期")
    days: Optional[int] = Field(None, description="行程天数")
    transport_mode: TransportMode = Field(TransportMode.DRIVING, description="交通方式")
    consider_weather: bool = Field(True, description="是否考虑天气因素")
    plan_mode: Optional[str] = Field(None, description="规划模式：precise(精确) 或 intent(意图)")


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(False, description="是否成功")
    error: Dict[str, Any] = Field(..., description="错误信息")
