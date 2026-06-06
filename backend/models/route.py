"""
路线相关模型 - 上海旅游规划系统专用
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime, date
from enum import Enum
import models.llm as models_llm

# 导入基础模型
from .base import POI, TransportMode, WeatherInfo, ErrorResponse

# Removed: 导入大众点评评论模型
# from dianping_reviews.models.schemas import DianpingReview

class RoutePoint(BaseModel):
    """路线点模型"""
    poi: POI = Field(..., description="POI信息")
    poi_type: Literal["main", "enroute"] = Field("main", description="POI类型：主景点或沿途发现")
    arrival_time: Optional[datetime] = Field(None, description="到达时间")
    departure_time: Optional[datetime] = Field(None, description="离开时间")
    stay_minutes: int = Field(60, description="停留时长(分钟)")
    transport_from_prev: Optional[TransportMode] = Field(None, description="从上一段来的交通方式")
    distance_from_prev: float = Field(0.0, description="与上一段距离(米)")
    duration_from_prev: int = Field(0, description="与上一段行程时间(秒)")
    polyline: str = Field("", description="路线polyline编码")
    steps: List[str] = Field(default_factory=list, description="路线步骤说明")
    weather: Optional[WeatherInfo] = Field(None, description="该点天气")
    note: str = Field("", description="备注")
    insert_after_index: Optional[int] = Field(None, description="建议插入位置（沿途POI）")
    discovery_reason: Optional[str] = Field(None, description="发现原因（沿途POI）")


class EnroutePOI(POI):
    """沿途POI模型，继承POI并添加额外字段"""
    distance_from_route: float = Field(0.0, description="偏离路线距离（米）")
    insert_after_index: int = Field(0, description="建议插入到第几个主POI之后")
    discovery_reason: str = Field("", description="发现原因，如'途经延安高架时附近'")
    # Removed: reviews: List[DianpingReview] = Field(default_factory=list, description="评论列表")


class TrafficSegment(BaseModel):
    """交通拥堵段模型"""
    start_index: int = Field(..., description="polyline起始坐标索引")
    end_index: int = Field(..., description="polyline结束坐标索引")
    status: Literal["smooth", "slow", "congested", "blocked"] = Field(..., description="交通状态")
    road_name: str = Field("", description="路段名称")


class DailyRoute(BaseModel):
    """每日路线模型"""
    day: int = Field(..., description="第几天，从1开始")
    date: Optional[str] = Field(None, description="日期")
    points: List[RoutePoint] = Field(default_factory=list, description="路线点列表")
    pois: List[POI] = Field(default_factory=list, description="POI列表")
    main_pois: List[POI] = Field(default_factory=list, description="主行程POI")
    enroute_pois: List[EnroutePOI] = Field(default_factory=list, description="沿途发现POI")
    total_distance: float = Field(0.0, description="总距离(米)")
    total_duration: int = Field(0, description="总时长(秒)")
    total_transport_duration: int = Field(0, description="交通总时长(秒)")
    enroute_extra_duration: int = Field(0, description="因沿途POI额外增加的时间（分钟）")
    weather_tip: str = Field("", description="天气提示")
    smoothness_score: float = Field(0.0, description="流畅度评分1-10")
    polyline: str = Field("", description="完整路线polyline（真实道路坐标）")
    traffic_segments: List[TrafficSegment] = Field(default_factory=list, description="交通拥堵段")
    map_snapshot: Optional[str] = Field(None, description="地图截图(base64或URL)")

class RouteResponse(BaseModel):
    """路线规划响应"""
    route_id: str = Field(..., description="路线唯一标识")
    origin: Optional[POI] = Field(None, description="出发地")
    destination: Optional[POI] = Field(None, description="目的地")
    waypoints: List[POI] = Field(default_factory=list, description="途经点")
    main_pois: List[POI] = Field(default_factory=list, description="主POI列表（原始5+地点）")
    daily_routes: List[DailyRoute] = Field(default_factory=list, description="每日路线")
    total_distance: float = Field(0.0, description="总距离(米)")
    total_duration: int = Field(0, description="总时长(秒)")
    transport_mode: TransportMode = Field(TransportMode.DRIVING, description="交通方式")
    weather_forecast: List[WeatherInfo] = Field(default_factory=list, description="天气预报")
    traffic_segments: List[TrafficSegment] = Field(default_factory=list, description="交通拥堵段信息")
    overall_traffic: Literal["smooth", "slow", "congested", "blocked"] = Field("smooth", description="整体交通状况")
    enroute_pois: List[EnroutePOI] = Field(default_factory=list, description="沿途POI（最多6个）")
    route_iterations: int = Field(1, description="路线规划迭代次数（1=仅初始规划，2=经过重规划）")
    polyline: str = Field("", description="最终路线polyline（第二次重规划后的真实道路坐标）")
    plan_mode: Literal["precise", "intent"] = Field(..., description="计划模式")
    recommended_reason: Optional[str] = Field(None, description="推荐理由")
    intent: Optional[models_llm.IntentModel] = Field(None, description="意图信息")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class RouteOptimizeRequest(BaseModel):
    """路线优化请求"""
    route_id: str = Field(..., description="路线ID")
    optimize_by: str = Field("smoothness", description="优化目标")
    max_hours_per_day: float = Field(8.0, ge=4.0, le=12.0, description="每天最大游览小时数")


class DisambiguateRequest(BaseModel):
    """POI消歧请求"""
    poi_name: str = Field(..., description="POI名称")
    route_id: str = Field(..., description="路线ID")
    selected_id: str = Field(..., description="选中的POI ID")
