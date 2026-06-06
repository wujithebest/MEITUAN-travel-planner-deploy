"""
后端路线数据 DTO 模型
用于将内部数据结构转换为前端可用的 JSON 格式

坐标系统说明：
- 后端内部使用 [lat, lng] 格式（folium/高德API返回）
- 前端高德 JS API 使用 [lng, lat] 格式
- 转换时需要注意坐标翻转
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


# ==================== 基础 DTO ====================

class RoutePointDTO(BaseModel):
    """路线点 DTO - 用于前端高德地图渲染"""
    day: int
    name: str
    location: str          # "lng,lat" 格式（高德前端直接使用）
    kind: str              # "start" | "anchor" | "meal" | "enroute" | "hint"
    sub_anchor_name: Optional[str] = None
    parent_name: Optional[str] = None
    is_waypoint: bool = True
    is_passthrough: bool = False
    walk_from_route_min: int = 0
    route_annotation: Optional[str] = None  # "同建筑内" | "沿途经过" | 步行时间描述
    travel_before_min: Optional[float] = None


class RouteSegmentDTO(BaseModel):
    """路线段 DTO - 用于前端高德地图渲染"""
    from_poi: str
    to_poi: str
    day_index: int
    transport: str         # "步行" | "地铁/公交" | "自驾" | "骑行"
    duration_min: float
    distance_km: float
    polyline: str          # "lng,lat;lng,lat" 高德格式（前端直接使用）


class TimePeriodDTO(BaseModel):
    """时间段 DTO"""
    period: str            # "morning" | "lunch" | "afternoon" | "dinner" | "evening"
    label: str             # "上午（9:00-12:00）"
    anchor_name: str       # "南京路步行街周边游览"
    pois: list[str]        # 该时段的 POI 名称列表


class DailyRouteDTO(BaseModel):
    """每日路线 DTO"""
    day: int
    points: list[RoutePointDTO]
    segments: list[RouteSegmentDTO]
    time_periods: list[TimePeriodDTO]
    anchor_hints: dict[str, str]  # 锚点推荐理由


class PlanRouteResponse(BaseModel):
    """规划路线响应 DTO - 兼容旧版前端"""
    reply: str             # 现有的文本回复
    has_route: bool        # 是否包含路线数据
    route: Optional[DailyRouteDTO] = None
    total_days: int = 1
    map_html_paths: list[str] = []  # 地图文件路径


# ==================== 高德地图 JSON DTO ====================

class GaodeRoutePointJSON(BaseModel):
    """
    高德地图路线点 JSON 格式
    坐标已转换为 [lng, lat] 供高德 JS API 直接使用
    """
    name: str
    location: list[float]   # [lng, lat] 高德格式
    kind: str              # "start" | "waypoint" | "enroute" | "meal"
    period: str            # "morning" | "lunch" | "afternoon" | "dinner" | "evening"
    is_waypoint: bool = True
    tooltip: Optional[str] = None   # 悬停提示文本
    walk_min: Optional[int] = None  # 旁支POI的步行时间（分钟）
    label: Optional[str] = None     # 标记上的文字（如序号）


class GaodeRouteSegmentJSON(BaseModel):
    """
    高德地图路线段 JSON 格式
    """
    from_poi: str
    to_poi: str
    transport: str         # "步行" | "地铁/公交" | "自驾" | "骑行"
    duration_min: float
    distance_km: float
    polyline: list[list[float]]  # [[lng, lat], ...] 高德格式
    period: str            # 所属时间段
    color: str             # 路线颜色 hex（如 "#E67E22"）
    is_dashed: bool        # 是否虚线（公交/自驾为虚线）


class GaodeDayRouteJSON(BaseModel):
    """
    高德地图单日路线 JSON 格式
    前端可直接用于渲染高德地图
    """
    day: int
    center: list[float]     # [lng, lat] 地图中心点
    points: list[GaodeRoutePointJSON]
    segments: list[GaodeRouteSegmentJSON]
    time_periods: list[str]  # ["上午", "午餐", "下午", "晚餐"]


class GaodeRouteResponse(BaseModel):
    """
    高德地图路线响应 JSON 格式
    包含多日路线数据
    """
    summary: str                           # 行程摘要文本
    days: list[GaodeDayRouteJSON]          # 每日路线数据
    total_days: int
    total_distance_km: float
    map_html_paths: list[str] = []         # 保留旧版 HTML 路径（可选）


def convert_to_frontend_route(
    points: list[dict],
    route_segments: list,
    hints: dict[str, str],
    waypoint_annotations: dict[str, dict],
    text_summary: str,
    map_paths: list[str],
) -> PlanRouteResponse:
    """
    将后端内部格式转换为前端可用格式
    
    Args:
        points: run_step3 返回的点列表（包含 day, name, location, kind 等字段）
        route_segments: RouteSegment 列表
        hints: 锚点提示字典
        waypoint_annotations: waypoint 标注信息
        text_summary: 文本摘要
        map_paths: 地图文件路径列表
    
    Returns:
        PlanRouteResponse
    """
    from .data_schema import RouteSegment
    
    # 按 day 分组
    day_indices = sorted({p.get("day", 1) for p in points})
    
    if not day_indices:
        return PlanRouteResponse(
            reply=text_summary,
            has_route=False,
            route=None,
            total_days=0,
            map_html_paths=map_paths,
        )
    
    # 将所有天的数据合并到一个 DailyRouteDTO 中
    all_route_points: list[RoutePointDTO] = []
    all_route_segments: list[RouteSegmentDTO] = []
    all_time_periods: list[TimePeriodDTO] = []
    all_hints: dict[str, str] = dict(hints)
    
    total_days = len(day_indices)
    
    for day in day_indices:
        day_points = [p for p in points if p.get("day", 1) == day]
        day_segments = [s for s in route_segments if s.day_index == day]
        
        # 转换 points
        for p in day_points:
            loc = p.get("location", {})
            # 注意：高德前端用 lng,lat
            lng_lat = f"{loc.get('lng', 0)},{loc.get('lat', 0)}"
            
            # 确定 kind
            kind = p.get("kind", "")
            if kind == "start":
                frontend_kind = "start"
            elif kind == "meal":
                frontend_kind = "meal"
            elif kind in ("hint", "free_explore"):
                frontend_kind = "hint"
            elif p.get("is_passthrough") or not p.get("is_waypoint", True):
                frontend_kind = "enroute"
            else:
                frontend_kind = "anchor_internal"
            
            # 获取 waypoint annotation
            ann = waypoint_annotations.get(p.get("name", {}), {})
            
            all_route_points.append(RoutePointDTO(
                day=day,
                name=p.get("name", ""),
                location=lng_lat,
                kind=frontend_kind,
                sub_anchor_name=p.get("sub_anchor_name"),
                parent_name=p.get("parent_name"),
                is_waypoint=ann.get("is_waypoint", True),
                is_passthrough=p.get("is_passthrough", False),
                walk_from_route_min=ann.get("walk_from_route_min", 0),
                route_annotation=p.get("route_annotation") or ("同建筑内" if ann.get("same_building") else None),
                travel_before_min=p.get("travel_before"),
            ))
        
        # 转换 segments
        for seg in day_segments:
            # polyline: [[lat,lng],...] → "lng,lat;lng,lat"
            polyline_str = ";".join(f"{pt[1]},{pt[0]}" for pt in seg.polyline)
            
            all_route_segments.append(RouteSegmentDTO(
                from_poi=seg.from_poi,
                to_poi=seg.to_poi,
                day_index=seg.day_index,
                transport=seg.transport,
                duration_min=seg.duration_min,
                distance_km=seg.distance_km,
                polyline=polyline_str,
            ))
        
        # 识别时间段
        time_periods = _infer_time_periods(day_points, day)
        all_time_periods.extend(time_periods)
    
    # 构建每日路线（目前返回所有天的合并数据）
    # 前端可以根据 day 字段自行分组
    daily_route = DailyRouteDTO(
        day=1,  # 占位，实际数据包含所有天
        points=all_route_points,
        segments=all_route_segments,
        time_periods=all_time_periods,
        anchor_hints=all_hints,
    )
    
    return PlanRouteResponse(
        reply=text_summary,
        has_route=True,
        route=daily_route,
        total_days=total_days,
        map_html_paths=map_paths,
    )


def build_points_from_segments(
    route_segments: list,
    waypoint_annotations: dict[str, dict],
) -> list[dict]:
    """
    从 route_segments 构建 points 列表
    用于当只有 segments 没有完整 points 时
    """
    from .data_schema import RouteSegment
    
    points = []
    seen_names = set()
    
    for seg in route_segments:
        # 添加 from_poi
        if seg.from_poi not in seen_names:
            seen_names.add(seg.from_poi)
            ann = waypoint_annotations.get(seg.from_poi, {})
            points.append({
                "day": seg.day_index,
                "name": seg.from_poi,
                "location": seg.polyline[0] if seg.polyline else {"lat": 0, "lng": 0},
                "kind": "start" if len(points) == 0 else "anchor_internal",
                "is_waypoint": ann.get("is_waypoint", True),
                "walk_from_route_min": ann.get("walk_from_route_min", 0),
            })
        
        # 添加 to_poi
        if seg.to_poi not in seen_names:
            seen_names.add(seg.to_poi)
            ann = waypoint_annotations.get(seg.to_poi, {})
            points.append({
                "day": seg.day_index,
                "name": seg.to_poi,
                "location": seg.polyline[-1] if seg.polyline else {"lat": 0, "lng": 0},
                "kind": "anchor_internal",
                "is_waypoint": ann.get("is_waypoint", True),
                "walk_from_route_min": ann.get("walk_from_route_min", 0),
            })
    
    return points


def _infer_time_periods(day_points: list[dict], day_index: int) -> list[TimePeriodDTO]:
    """
    从 points 顺序和 kind 推断时间段
    
    根据餐饮点和锚点位置划分：
    - morning: 第一个午餐之前
    - lunch: 午餐时段
    - afternoon: 午餐之后到晚餐之前
    - dinner: 晚餐时段
    - evening: 晚餐之后
    """
    periods: list[TimePeriodDTO] = []
    
    # 找到餐饮点的位置
    meal_indices = []
    for i, p in enumerate(day_points):
        if p.get("kind") == "meal":
            meal_indices.append((i, p.get("name", "")))
    
    # 找到锚点
    anchor_names = []
    for p in day_points:
        if p.get("kind") in ("start", "anchor", "anchor_internal"):
            parent = p.get("parent_name") or p.get("sub_anchor_name") or p.get("name", "")
            if parent and parent not in anchor_names:
                anchor_names.append(parent)
    
    # 默认锚点名
    default_anchor = anchor_names[0] if anchor_names else "游览区域"
    
    # 根据餐饮点划分时间段
    if not meal_indices:
        # 没有餐饮点，只有上午和下午
        morning_pois = [p.get("name", "") for p in day_points if p.get("kind") not in ("hint", "free_explore")]
        periods.append(TimePeriodDTO(
            period="morning",
            label="上午（9:00-12:00）",
            anchor_name=f"{default_anchor}周边游览",
            pois=morning_pois[:len(morning_pois)//2],
        ))
        periods.append(TimePeriodDTO(
            period="afternoon",
            label="下午（14:00-18:00）",
            anchor_name=f"{default_anchor}周边游览",
            pois=morning_pois[len(morning_pois)//2:],
        ))
    elif len(meal_indices) == 1:
        # 只有一个餐饮点（午餐或晚餐）
        meal_idx, meal_name = meal_indices[0]
        before_meal = day_points[:meal_idx]
        after_meal = day_points[meal_idx+1:]
        
        # 根据位置判断是午餐还是晚餐
        is_lunch = meal_idx < len(day_points) // 2
        
        if is_lunch:
            # 午餐在前半部分
            morning_pois = [p.get("name", "") for p in before_meal if p.get("kind") not in ("hint", "free_explore")]
            periods.append(TimePeriodDTO(
                period="morning",
                label="上午（9:00-12:00）",
                anchor_name=f"{default_anchor}周边游览",
                pois=morning_pois,
            ))
            periods.append(TimePeriodDTO(
                period="lunch",
                label="午餐（12:00-14:00）",
                anchor_name=meal_name,
                pois=[meal_name],
            ))
            afternoon_pois = [p.get("name", "") for p in after_meal if p.get("kind") not in ("hint", "free_explore")]
            periods.append(TimePeriodDTO(
                period="afternoon",
                label="下午（14:00-18:00）",
                anchor_name=f"{default_anchor}周边游览",
                pois=afternoon_pois,
            ))
        else:
            # 晚餐在后半部分
            morning_pois = [p.get("name", "") for p in before_meal if p.get("kind") not in ("hint", "free_explore")]
            periods.append(TimePeriodDTO(
                period="morning",
                label="上午（9:00-12:00）",
                anchor_name=f"{default_anchor}周边游览",
                pois=morning_pois[:len(morning_pois)//2],
            ))
            periods.append(TimePeriodDTO(
                period="afternoon",
                label="下午（14:00-18:00）",
                anchor_name=f"{default_anchor}周边游览",
                pois=morning_pois[len(morning_pois)//2:],
            ))
            periods.append(TimePeriodDTO(
                period="dinner",
                label="晚餐（18:00-20:00）",
                anchor_name=meal_name,
                pois=[meal_name],
            ))
    else:
        # 有午餐和晚餐
        lunch_idx = meal_indices[0][0] if meal_indices else len(day_points) // 3
        dinner_idx = meal_indices[1][0] if len(meal_indices) > 1 else len(day_points) * 2 // 3
        
        morning_pois = [p.get("name", "") for p in day_points[:lunch_idx] if p.get("kind") not in ("hint", "free_explore")]
        lunch_name = meal_indices[0][1] if meal_indices else ""
        afternoon_pois = [p.get("name", "") for p in day_points[lunch_idx+1:dinner_idx] if p.get("kind") not in ("hint", "free_explore")]
        dinner_name = meal_indices[1][1] if len(meal_indices) > 1 else ""
        evening_pois = [p.get("name", "") for p in day_points[dinner_idx+1:] if p.get("kind") not in ("hint", "free_explore")]
        
        if morning_pois:
            periods.append(TimePeriodDTO(
                period="morning",
                label="上午（9:00-12:00）",
                anchor_name=f"{default_anchor}周边游览",
                pois=morning_pois,
            ))
        if lunch_name:
            periods.append(TimePeriodDTO(
                period="lunch",
                label="午餐（12:00-14:00）",
                anchor_name=lunch_name,
                pois=[lunch_name],
            ))
        if afternoon_pois:
            periods.append(TimePeriodDTO(
                period="afternoon",
                label="下午（14:00-18:00）",
                anchor_name=f"{default_anchor}周边游览",
                pois=afternoon_pois,
            ))
        if dinner_name:
            periods.append(TimePeriodDTO(
                period="dinner",
                label="晚餐（18:00-20:00）",
                anchor_name=dinner_name,
                pois=[dinner_name],
            ))
        if evening_pois:
            periods.append(TimePeriodDTO(
                period="evening",
                label="晚间（20:00-22:00）",
                anchor_name=f"{default_anchor}周边游览",
                pois=evening_pois,
            ))
    
    return periods


# ==================== 坐标转换工具函数 ====================

def flip_coord(lat: float, lng: float) -> list[float]:
    """
    翻转坐标：[lat, lng] → [lng, lat]
    
    后端 folium 使用 [lat, lng] 格式
    高德 JS API 使用 [lng, lat] 格式
    """
    return [lng, lat]


def flip_polyline(polyline: list[list[float]]) -> list[list[float]]:
    """
    翻转 polyline 坐标：[[lat,lng],...] → [[lng,lat],...]
    
    Args:
        polyline: folium 格式的坐标列表 [[lat, lng], ...]
    
    Returns:
        高德格式的坐标列表 [[lng, lat], ...]
    """
    return [[pt[1], pt[0]] for pt in polyline]


# ==================== 高德地图 JSON 构建函数 ====================

# 时间段颜色映射（与 folium 渲染保持一致）
TIME_PERIOD_COLORS = {
    "morning": "#E67E22",
    "lunch": "#D35400",
    "afternoon": "#2980B9",
    "dinner": "#C0392B",
    "evening": "#8E44AD",
}

TIME_PERIOD_LABELS = {
    "morning": "上午",
    "lunch": "午餐",
    "afternoon": "下午",
    "dinner": "晚餐",
    "evening": "晚间",
}


def _get_period_for_point(point: dict, day_points: list[dict], day_plan=None) -> str:
    """
    推断点所属的时间段
    
    Returns:
        str: "morning" | "lunch" | "afternoon" | "dinner" | "evening"
    """
    # 根据 kind 直接判断
    kind = point.get("kind", "")
    if kind == "meal":
        # 根据在序列中的位置判断是午餐还是晚餐
        meal_idx = next((i for i, p in enumerate(day_points) if p.get("name") == point.get("name")), 0)
        return "lunch" if meal_idx < len(day_points) // 2 else "dinner"
    
    # 根据附近餐饮点判断
    point_idx = next((i for i, p in enumerate(day_points) if p.get("name") == point.get("name")), 0)
    meal_indices = [(i, p) for i, p in enumerate(day_points) if p.get("kind") == "meal"]
    
    if not meal_indices:
        return "morning" if point_idx < len(day_points) // 2 else "afternoon"
    
    # 找到最近的餐饮点
    lunch_idx = meal_indices[0][0] if meal_indices else len(day_points) // 3
    dinner_idx = meal_indices[1][0] if len(meal_indices) > 1 else len(day_points) * 2 // 3
    
    if point_idx < lunch_idx:
        return "morning"
    elif point_idx == lunch_idx:
        return "lunch"
    elif point_idx < dinner_idx:
        return "afternoon"
    elif point_idx == dinner_idx:
        return "dinner"
    else:
        return "evening"


def build_gaode_route_json(
    points: list[dict],
    route_segments: list,
    hints: dict[str, str],
    waypoint_annotations: dict[str, dict],
    text_summary: str,
    map_paths: list[str],
    complete_plan=None,
) -> GaodeRouteResponse:
    """
    构建高德地图可用的路线 JSON 数据
    
    Args:
        points: run_step3 返回的点列表
        route_segments: RouteSegment 列表
        hints: 锚点提示字典
        waypoint_annotations: waypoint 标注信息
        text_summary: 文本摘要
        map_paths: 地图文件路径列表
        complete_plan: CompletePlan 对象（可选）
    
    Returns:
        GaodeRouteResponse: 高德地图路线 JSON
    """
    from .data_schema import RouteSegment
    
    # 按 day 分组
    day_indices = sorted({p.get("day", 1) for p in points})
    
    if not day_indices:
        return GaodeRouteResponse(
            summary=text_summary,
            days=[],
            total_days=0,
            total_distance_km=0.0,
            map_html_paths=map_paths,
        )
    
    days: list[GaodeDayRouteJSON] = []
    total_distance = 0.0
    
    for day in day_indices:
        day_points = [p for p in points if p.get("day", 1) == day]
        day_segments = [s for s in route_segments if s.day_index == day]
        
        # 计算当天中心点
        valid_points = [p for p in day_points if p.get("location") and "lat" in p["location"]]
        if valid_points:
            center_lat = sum(p["location"]["lat"] for p in valid_points) / len(valid_points)
            center_lng = sum(p["location"]["lng"] for p in valid_points) / len(valid_points)
            center = flip_coord(center_lat, center_lng)
        else:
            center = [121.47, 31.23]  # 默认上海中心
        
        # 转换 points
        gaode_points: list[GaodeRoutePointJSON] = []
        for idx, p in enumerate(day_points):
            loc = p.get("location", {})
            if not loc or "lat" not in loc:
                continue
            
            # 坐标翻转：[lat, lng] → [lng, lat]
            location = flip_coord(loc["lat"], loc["lng"])
            
            # 确定 kind
            kind = p.get("kind", "")
            if kind == "start":
                point_kind = "start"
            elif kind == "meal":
                point_kind = "meal"
            elif p.get("is_passthrough") or not p.get("is_waypoint", True):
                point_kind = "enroute"
            else:
                point_kind = "waypoint"
            
            # 推断时间段
            period = _get_period_for_point(p, day_points)
            
            # 获取 waypoint annotation
            ann = waypoint_annotations.get(p.get("name"), {})
            walk_min = ann.get("walk_from_route_min", 0) or p.get("walk_from_route_min", 0)
            
            # 构建 tooltip
            tooltip = None
            route_annotation = p.get("route_annotation") or ann.get("same_building")
            if route_annotation == "同建筑内":
                tooltip = f"{p.get('name', '')}（同一建筑内）"
            elif route_annotation == "沿途经过":
                tooltip = f"{p.get('name', '')}（沿途经过）"
            elif walk_min and walk_min > 0:
                tooltip = f"{p.get('name', '')}（步行{walk_min}分钟可达）"
            elif p.get("_tooltip"):
                tooltip = p["_tooltip"]
            
            # 构建 label（序号）
            label = None
            if point_kind == "waypoint":
                # 计算当天 waypoint 序号
                waypoint_count = sum(1 for gp in gaode_points if gp.kind == "waypoint")
                label = str(waypoint_count + 1)
            
            gaode_points.append(GaodeRoutePointJSON(
                name=p.get("name", ""),
                location=location,
                kind=point_kind,
                period=period,
                is_waypoint=ann.get("is_waypoint", True) and point_kind == "waypoint",
                tooltip=tooltip,
                walk_min=walk_min if walk_min > 0 else None,
                label=label,
            ))
        
        # 转换 segments
        gaode_segments: list[GaodeRouteSegmentJSON] = []
        for seg in day_segments:
            total_distance += seg.distance_km
            
            # 坐标翻转：[[lat,lng],...] → [[lng,lat],...]
            polyline = flip_polyline(seg.polyline)
            
            # 推断时间段
            to_idx = next((i for i, p in enumerate(day_points) if p.get("name") == seg.to_poi), 0)
            period = _get_period_for_point(day_points[to_idx], day_points) if to_idx < len(day_points) else "morning"
            
            # 确定颜色
            color = TIME_PERIOD_COLORS.get(period, "#E67E22")
            
            # 是否虚线（公交/自驾）
            is_dashed = seg.transport not in ("步行", "骑行")
            
            gaode_segments.append(GaodeRouteSegmentJSON(
                from_poi=seg.from_poi,
                to_poi=seg.to_poi,
                transport=seg.transport,
                duration_min=seg.duration_min,
                distance_km=seg.distance_km,
                polyline=polyline,
                period=period,
                color=color,
                is_dashed=is_dashed,
            ))
        
        # 收集时间段标签
        time_periods = list(set(
            TIME_PERIOD_LABELS.get(_get_period_for_point(p, day_points), "上午")
            for p in day_points
            if p.get("kind") not in ("hint", "free_explore")
        ))
        
        # 按标准顺序排序
        period_order = ["上午", "午餐", "下午", "晚餐", "晚间"]
        time_periods = [p for p in period_order if p in time_periods]
        
        days.append(GaodeDayRouteJSON(
            day=day,
            center=center,
            points=gaode_points,
            segments=gaode_segments,
            time_periods=time_periods,
        ))
    
    return GaodeRouteResponse(
        summary=text_summary,
        days=days,
        total_days=len(day_indices),
        total_distance_km=round(total_distance, 1),
        map_html_paths=map_paths,
    )
