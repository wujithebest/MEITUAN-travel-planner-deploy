from __future__ import annotations
import asyncio
import datetime as dt
import math
import numpy as np
from pathlib import Path
from typing import Any

import folium

from . import config
from .api_client import (
    gaode_around_search,
    gaode_around_search_batch,
    gaode_bicycling_route,
    gaode_driving_route,
    gaode_get_district_boundary,
    gaode_polygon_search_batch,
    gaode_reverse_geocode,
    gaode_text_search,
    gaode_transit_route,
    gaode_walking_route,
    gaode_walking_route_waypoints,
    raw_to_place,
)
from .data_schema import AnchorPlan, CompletePlan, MicroPOI, ParsedIntent, PlannedWaypoint, RouteSegment, SubAnchor
from .plan_reality_validator import validate_plan_reality, plan_reality_audit_log
from .route_backbone import (
    get_visit_duration as v4_visit_duration,
    is_valid_route_poi,
    name_sub_anchors_by_direction,
)
from .step3_planned import resolve_planned_waypoints, build_planned_route_points, estimate_planned_duration_min
from .utils import DependencyMissingError, PipelineLogger, ZeroOutputError, coord_to_param, emit_status, haversine_km, push_output

# 候选 POI 池：由 _fill_segment 收集未选中的有序候选点
# key: (day_index, sub_anchor_name), value: list[dict]
_candidate_pool: dict[tuple[int, str], list[dict]] = {}


def _visit_duration(typecode: str, is_meal: bool = False) -> int:
    if is_meal:
        return 60
    prefix = (typecode or "")[:6]
    if prefix in {"110200", "140100"}:
        return 75
    if prefix in {"110100", "140200", "190100"}:
        return 45
    return 50


# ═══════════════════════════════════════════════════════════════
# v3 新增：锚点拆解与路线排布
# ═══════════════════════════════════════════════════════════════

ANCHOR_INTERNAL_EXCLUDE_PREFIXES = {"01", "04", "06", "09", "10", "12", "15", "17"}

# ═══════════════════════════════════════════════════════════════
# v5.2 新增：投影排序 + 贪心选取 + waypoint步行路线
# ═══════════════════════════════════════════════════════════════

# POI离路线最近点距离阈值：600m以内算"沿途经过"，超过算"需绕行"或剔除
ROUTE_POI_NEAREST_THRESHOLD_M = 600


def _pick_route_endpoints(
    pois: list[dict],
    entry_point: dict,
    time_budget_min: int,
    next_anchor_center: dict | None = None,
) -> tuple[dict, dict]:
    """v5.2 r3: 选起终点。
    起点 = 需要公共交通时，选择离下一个锚点最远的POI（确保路线流向下一目的地）
           步行可达时，选择离入口最近的POI
    终点 = 预算约束下能到达的最远POI
    """
    if not pois:
        raise ZeroOutputError("没有可用的POI来规划路线")
    if len(pois) == 1:
        return pois[0], pois[0]

    # v5.2 r3: 路线方向优化 — 有下一个锚点且需要公共交通时，
    # 选择离下一个锚点最远的POI作为起点，使路线从远端流向近端
    if next_anchor_center and len(pois) > 1:
        centroid = _compute_centroid([p.get("location", {}) for p in pois if p.get("location")])
        needs_transit = centroid and haversine_km(entry_point, centroid) > 2.0
        if needs_transit:
            # 需要公共交通：选离下一个锚点最远的POI为起点
            start = max(pois, key=lambda p: haversine_km(next_anchor_center, p.get("location", {})))
        else:
            # 步行可达：选离入口最近的POI
            start = min(pois, key=lambda p: haversine_km(entry_point, p.get("location", {})))
    else:
        start = min(pois, key=lambda p: haversine_km(entry_point, p.get("location", {})))

    # 终点：预算内可达的最远POI
    walking_ratio = {"full_day": 0.25, "half_day": 0.30}.get(
        _infer_capacity_from_budget(time_budget_min), 0.35
    )
    max_straight_km = time_budget_min * walking_ratio * (4.5 / 60) * 0.6

    reachable = [p for p in pois if haversine_km(start.get("location", {}), p.get("location", {})) <= max_straight_km]
    if not reachable:
        # 所有POI都超预算，只取最近的3个
        reachable = sorted(pois, key=lambda p: haversine_km(start.get("location", {}), p.get("location", {})))[:3]

    end = max(reachable, key=lambda p: haversine_km(start.get("location", {}), p.get("location", {})))
    return start, end


def _infer_capacity_from_budget(time_budget_min: int) -> str:
    if time_budget_min >= 360:
        return "full_day"
    if time_budget_min >= 180:
        return "half_day"
    return "quarter_day"


def _project_onto_axis(loc: dict, start_loc: dict, end_loc: dict) -> float:
    """将一个位置投影到起点→终点轴上，返回 t ∈ [0,1]"""
    ax = end_loc.get("lat", 0) - start_loc.get("lat", 0)
    ay = end_loc.get("lng", 0) - start_loc.get("lng", 0)
    ab_sq = ax * ax + ay * ay
    if ab_sq < 1e-12:
        return 0.0
    apx = loc.get("lat", 0) - start_loc.get("lat", 0)
    apy = loc.get("lng", 0) - start_loc.get("lng", 0)
    t = (apx * ax + apy * ay) / ab_sq
    return max(0.0, min(1.0, t))


def _project_sort_pois(pois: list[dict], start: dict, end: dict) -> list[dict]:
    """v5.2: 将POI按起点→终点轴投影位置排序"""
    for p in pois:
        p["_proj_t"] = _project_onto_axis(p.get("location", {}), start.get("location", {}), end.get("location", {}))
    sorted_pois = sorted(pois, key=lambda p: p.get("_proj_t", 1.0))
    # 清理临时属性
    for p in sorted_pois:
        p.pop("_proj_t", None)
    return sorted_pois


def _local_2opt_optimize(pois: list[dict]) -> list[dict]:
    """v5.2 r3: 局部2-opt优化，减少投影排序后的zigzag。
    对连续三个POI A→B→C，如果A→C→B总距离更短，则交换B和C。
    迭代直到无改善或达到最大迭代次数。
    """
    if len(pois) <= 3:
        return pois

    result = list(pois)
    max_iterations = len(result) * 3
    iteration = 0
    improved = True

    while improved and iteration < max_iterations:
        improved = False
        iteration += 1
        for i in range(len(result) - 2):
            a_loc = result[i].get("location", {})
            b_loc = result[i + 1].get("location", {})
            c_loc = result[i + 2].get("location", {})
            if not a_loc or not b_loc or not c_loc:
                continue

            d_ab = haversine_km(a_loc, b_loc)
            d_bc = haversine_km(b_loc, c_loc)
            d_ac = haversine_km(a_loc, c_loc)
            d_cb = haversine_km(c_loc, b_loc)

            # 交换后更短则执行（加5%阈值避免微小改善的频繁交换）
            if d_ac + d_cb < d_ab + d_bc - 0.005:
                result[i + 1], result[i + 2] = result[i + 2], result[i + 1]
                improved = True

    return result


def _greedy_select_by_budget(
    pois: list[dict],
    entry_point: dict,
    time_budget_min: int,
) -> list[dict]:
    """v5.2: 沿投影排序顺序贪心选取，直到时间预算用完"""
    if not pois:
        return []

    # 先选起终点并投影排序
    start, end = _pick_route_endpoints(pois, entry_point, time_budget_min)

    # 过滤掉离起终点轴太远的POI（>2km的硬排除）
    axis_pois = []
    for p in pois:
        proj_t = _project_onto_axis(p.get("location", {}), start.get("location", {}), end.get("location", {}))
        # 计算POI到轴的垂直距离
        proj_lat = start.get("location", {}).get("lat", 0) + proj_t * (end.get("location", {}).get("lat", 0) - start.get("location", {}).get("lat", 0))
        proj_lng = start.get("location", {}).get("lng", 0) + proj_t * (end.get("location", {}).get("lng", 0) - start.get("location", {}).get("lng", 0))
        perp_dist = haversine_km(p.get("location", {}), {"lat": proj_lat, "lng": proj_lng})
        if perp_dist <= 2.0:  # 2km以内的保留
            axis_pois.append(p)

    # 投影排序
    ordered = _project_sort_pois(axis_pois, start, end)

    # 贪心选取
    result: list[dict] = []
    used_time = 0.0
    current = entry_point
    for p in ordered:
        loc = p.get("location", {})
        walk = max(config.WALK_TIME_MIN_FLOOR, _estimated_walk_min(current, loc))
        visit = _get_visit_duration(p)
        if used_time + walk + visit > time_budget_min:
            continue  # 跳过超预算的，继续看后面的（可能更近的能塞进去）
        used_time += walk + visit
        result.append(p)
        current = loc

    # 确保起点和终点在结果中
    if result and start not in result:
        result.insert(0, start)
    if result and end not in result and start != end:
        # 检查终点是否能塞进去
        walk_to_end = max(config.WALK_TIME_MIN_FLOOR, _estimated_walk_min(current, end.get("location", {})))
        visit_end = _get_visit_duration(end)
        if used_time + walk_to_end + visit_end <= time_budget_min:
            result.append(end)

    # 至少保留2个POI
    if len(result) < 2 and len(ordered) >= 2:
        result = ordered[:2]

    return result


def _find_nearest_on_polyline(loc: dict, polyline: list[list[float]]) -> tuple[int, float]:
    """找到polyline上离给定位置最近的点的索引和距离(度)"""
    best_idx = 0
    best_dist_sq = float("inf")
    p_lat = loc.get("lat", 0)
    p_lng = loc.get("lng", 0)
    for i, pt in enumerate(polyline):
        dlat = p_lat - pt[0]
        dlng = p_lng - pt[1]
        d_sq = dlat * dlat + dlng * dlng
        if d_sq < best_dist_sq:
            best_dist_sq = d_sq
            best_idx = i
    return best_idx, best_dist_sq ** 0.5


def _search_with_fallback(
    center: dict,
    radius: int,
    types: str,
    keywords: str,
    budget: str,
) -> list[dict]:
    """v5.2: 带自动扩搜的POI搜索。POI不够时自动扩大半径重新搜索。"""
    min_counts = {"full_day": 6, "half_day": 4, "quarter_day": 3}
    min_count = min_counts.get(budget, 4)

    requests = [
        {"location": coord_to_param(center), "keywords": keywords, "radius": radius, "types": types,
         "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25, "sortrule": "weight" if not keywords else ""},
    ]
    if keywords:
        requests.append(
            {"location": coord_to_param(center), "keywords": keywords, "radius": radius, "types": "",
             "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25}
        )
    return requests  # 返回request列表，由调用方执行batch搜索并判断是否需要扩搜



    def _best_t(loc: dict) -> float:
        p = (loc["lat"], loc["lng"])
        best_d, best_t = float("inf"), 0.0
        for i in range(total_segs):
            a = (backbone_polyline[i][0], backbone_polyline[i][1])
            b = (backbone_polyline[i + 1][0], backbone_polyline[i + 1][1])
            abx = b[0] - a[0]
            aby = b[1] - a[1]
            ab_sq = abx * abx + aby * aby
            t_seg = max(0.0, min(1.0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / ab_sq)) if ab_sq else 0.0
            px = a[0] + t_seg * abx
            py = a[1] + t_seg * aby
            d = (p[0] - px) ** 2 + (p[1] - py) ** 2
            if d < best_d:
                best_d = d
                best_t = (i + t_seg) / total_segs
        return float(best_t)

    t_from = _best_t(from_loc)
    t_to = _best_t(to_loc)
    if t_from > t_to:
        t_from, t_to = t_to, t_from

    idx_from = max(0, int(t_from * total_segs))
    idx_to = min(total_segs, int(t_to * total_segs) + 1)
    if idx_to <= idx_from:
        idx_to = idx_from + 1
    sub_path = backbone_polyline[idx_from: idx_to + 1]
    if len(sub_path) < 2:
        sub_path = [[from_loc["lat"], from_loc["lng"]], [to_loc["lat"], to_loc["lng"]]]
    return sub_path


def _pca_analysis(coords: list[dict]) -> tuple[float, np.ndarray, np.ndarray]:
    """PCA分析POI坐标分布，返回方差比、主轴方向、投影值"""
    arr = np.array([[c["lng"], c["lat"]] for c in coords])
    centered = arr - arr.mean(axis=0)
    cov = np.cov(centered.T)
    eigenvalues, eigenvectors = np.linalg.eig(cov)
    principal_axis = eigenvectors[:, np.argmax(eigenvalues)]
    projections = centered @ principal_axis
    variance_ratio = float(max(eigenvalues) / eigenvalues.sum())
    return variance_ratio, principal_axis, projections


def _determine_degradation(internal_pois: list[dict], time_budget: str) -> tuple[str, str | None]:
    """四级降级判断"""
    n = len(internal_pois)
    if n >= config.DEGRADATION_THRESHOLDS["rich"] and time_budget == "full_day":
        return "rich", None
    if n >= config.DEGRADATION_THRESHOLDS["normal"]:
        return "normal", None
    if n >= config.DEGRADATION_THRESHOLDS["sparse"]:
        return "sparse", "该区域适合自由漫步，沿途可随意拍照游览"
    return "free", "到达该区域后适合自由探索，无需固定路线"


def _midpoint(a: dict, b: dict) -> dict:
    return {
        "lat": (a["lat"] + b["lat"]) / 2,
        "lng": (a["lng"] + b["lng"]) / 2,
    }


def _v4_resolve_sub_end(sub: SubAnchor) -> dict:
    """v5.2: 取 internal_pois 末尾坐标，降级到 sub.location。backbone已砍掉。"""
    if sub.internal_pois:
        loc = sub.internal_pois[-1].get("location")
        if loc:
            return loc
    return sub.location


def _v4_resolve_sub_start(sub: SubAnchor) -> dict:
    """v5.2: 取 internal_pois 首位坐标，降级到 sub.location。backbone已砍掉。"""
    if sub.internal_pois:
        loc = sub.internal_pois[0].get("location")
        if loc:
            return loc
    return sub.location


def _compute_centroid(locs: list[dict]) -> dict | None:
    if not locs:
        return None
    return {"lat": sum(c["lat"] for c in locs) / len(locs), "lng": sum(c["lng"] for c in locs) / len(locs)}


def _make_anchor_bbox_polygon(lat: float, lng: float, length_km: float = 3.0, width_km: float = 1.5) -> str:
    """生成锚点周围的矩形多边形（N-S方向），用于多边形搜索"""
    import math
    half_h_deg = (length_km / 2.0) / 111.32
    half_w_deg = (width_km / 2.0) / (111.32 * math.cos(math.radians(lat)))
    # 逆时针：SW → NW → NE → SE
    return (
        f"{lng - half_w_deg:.6f},{lat - half_h_deg:.6f};"
        f"{lng - half_w_deg:.6f},{lat + half_h_deg:.6f};"
        f"{lng + half_w_deg:.6f},{lat + half_h_deg:.6f};"
        f"{lng + half_w_deg:.6f},{lat - half_h_deg:.6f}"
    )


POLYGON_MIN_BBOX_DIAGONAL_KM = 1.0  # 多边形bbox对角线低于此值降级为半径搜索


def _polygon_bbox_span_km(polygon: str) -> float:
    """计算多边形字符串的bbox对角线距离(km)"""
    pts = polygon.split(";")
    if len(pts) < 2:
        return 0.0
    lngs, lats = [], []
    for pt in pts:
        parts = pt.split(",")
        if len(parts) == 2:
            lngs.append(float(parts[0]))
            lats.append(float(parts[1]))
    if not lngs:
        return 0.0
    return haversine_km({"lat": min(lats), "lng": min(lngs)}, {"lat": max(lats), "lng": max(lngs)})


async def _resolve_polygon(anchor: AnchorPlan) -> str | None:
    """为fixed_poi full_day锚点获取行政区边界多边形，小区域返回None降级半径搜索"""
    location_str = coord_to_param(anchor.location)
    if not location_str:
        return None
    addr = await gaode_reverse_geocode(location_str)
    if not addr:
        return None
    district = addr.get("district")
    if not district:
        return None
    for kw in (district, district.rstrip("区县市")):
        if not kw:
            continue
        polygon = await gaode_get_district_boundary(kw)
        if polygon:
            span = _polygon_bbox_span_km(polygon)
            if span >= POLYGON_MIN_BBOX_DIAGONAL_KM:
                return polygon
            # bbox太小，降级为半径搜索
            return None
    return None


def _direction_labels_for_groups(group_a: list[dict], group_b: list[dict]) -> tuple[str, str]:
    """v3.1 F2：根据两组POI的实际空间位置（主分散方向），返回(group_a标签, group_b标签)。
    判断主轴：纬度方差 vs 经度方差，方差大的为主轴。
    输出标签：南北分散→南段/北段；东西分散→西段/东段。
    """
    a_locs = [p.get("location") for p in group_a if p.get("location")]
    b_locs = [p.get("location") for p in group_b if p.get("location")]
    if not a_locs or not b_locs:
        return "区域1", "区域2"
    all_lats = [loc["lat"] for loc in a_locs + b_locs]
    all_lngs = [loc["lng"] for loc in a_locs + b_locs]
    lat_mean = sum(all_lats) / len(all_lats)
    lng_mean = sum(all_lngs) / len(all_lngs)
    lat_var = sum((x - lat_mean) ** 2 for x in all_lats) / len(all_lats)
    lng_var = sum((x - lng_mean) ** 2 for x in all_lngs) / len(all_lngs)

    a_avg_lat = sum(loc["lat"] for loc in a_locs) / len(a_locs)
    b_avg_lat = sum(loc["lat"] for loc in b_locs) / len(b_locs)
    a_avg_lng = sum(loc["lng"] for loc in a_locs) / len(a_locs)
    b_avg_lng = sum(loc["lng"] for loc in b_locs) / len(b_locs)

    if lat_var >= lng_var:
        # 南北分散：纬度小的为南段
        return ("南段", "北段") if a_avg_lat <= b_avg_lat else ("北段", "南段")
    # 东西分散：经度小的为西段
    return ("西段", "东段") if a_avg_lng <= b_avg_lng else ("东段", "西段")


async def _supplementary_search_for_sub_anchors(
    sub_anchors: list[SubAnchor],
) -> list[SubAnchor]:
    """v5.2: 对每个子锚点做补充搜索 — 以子锚点质心为中心，用sortrule=weight搜索。
    解决拆分后子锚点只继承父搜索POI子集、POI不够的问题。
    同时加入亲水/沿河关键词，让滨江步道、观景平台等POI优先出现。
    """
    # 只对有质心的子锚点做补充搜索（free降级的不搜）
    to_search = [
        sub for sub in sub_anchors
        if sub.location and sub.degradation_level not in ("free",)
    ]
    if not to_search:
        return sub_anchors

    requests = []
    metadata = []
    for sub in to_search:
        loc_str = coord_to_param(sub.location)
        radius = config.ANCHOR_SEARCH_RADIUS_BY_CAPACITY.get(sub.capacity, config.ANCHOR_INTERNAL_SEARCH_RADIUS)
        # 请求1: 纯types搜索 + sortrule=weight（确保分散）
        requests.append({
            "location": loc_str, "keywords": "", "radius": radius,
            "types": config.ANCHOR_INTERNAL_TYPES,
            "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25,
            "sortrule": "weight",
        })
        # 请求2: 亲水/沿河关键词搜索（让滨江步道、观景平台等POI出现）
        requests.append({
            "location": loc_str,
            "keywords": f"{sub.parent_name} {config.WATERFRONT_KEYWORDS}",
            "radius": radius, "types": config.ANCHOR_INTERNAL_TYPES,  # v5.2 r4: 加types过滤
            "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25,
        })
        # v5.2 r4: 线性锚点（街/路/步行街等）额外keyword搜索
        # 让高德沿街返回POI，解决单点半径搜索POI集中在中段、两端缺失的问题
        _is_linear = any(kw in sub.parent_name for kw in config.LINEAR_ANCHOR_KEYWORDS)
        if _is_linear:
            requests.append({
                "location": loc_str, "keywords": sub.parent_name, "radius": radius,
                "types": config.ANCHOR_INTERNAL_TYPES,
                "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25,
            })
        metadata.append(sub)

    results = await gaode_around_search_batch(requests)

    # v5.2 r4: 请求数量不固定（线性锚点有3个请求），按metadata分组
    idx = 0
    for sub in metadata:
        _is_linear = any(kw in sub.parent_name for kw in config.LINEAR_ANCHOR_KEYWORDS)
        n_reqs = 3 if _is_linear else 2
        sub_results = results[idx:idx + n_reqs]
        idx += n_reqs
        seen = {p.get("id") or p.get("name", "") for p in sub.internal_pois}
        for raw in (r for batch in sub_results for r in batch):
            pid = raw.get("id") or raw.get("name", "")
            if pid in seen:
                continue
            seen.add(pid)
            name = raw.get("name", "")
            typecode = raw.get("typecode", "")
            if name == sub.parent_name or name == sub.name:
                continue
            if not is_valid_route_poi(typecode, name):
                continue
            loc = raw.get("location")
            if isinstance(loc, str):
                parts = loc.split(",")
                loc = {"lng": float(parts[0]), "lat": float(parts[1])}
            raw["location"] = loc
            sub.internal_pois.append(raw)

        # v5.2 r4: 餐饮POI比例限制已不需要 — is_valid_route_poi硬排除所有06开头的POI
        # 游览路线里不再有任何餐饮，餐饮归独立搜索流程

        # 重新评估降级等级
        level, hint = _determine_degradation(sub.internal_pois, sub.capacity)
        if level != sub.degradation_level:
            sub.degradation_level = level
            if hint and not sub.degradation_hint:
                sub.degradation_hint = hint

    return sub_anchors


# ── v5.2 r5: POI空间性质判定 ──
# 区域级POI的typecode前缀（风景名胜/文物古迹/公园/文化场馆/地名）
# 区域级POI判定常量已移至config_v52_r3.py，此处通过config引用
# config.AREA_TYPECODE_PREFIXES = {"11", "08", "14", "19"}  — typecode前2位
# config.AREA_NAME_KEYWORDS = ["外滩", "滨江", ...]         — 名称关键词


def _is_area_poi(name: str, typecode: str) -> bool:
    """v5.2 r5: 判断POI是区域级（需要polygon搜索）还是点级（radius搜索即可）。
    
    区域级：有覆盖范围，一个坐标框不住，如"外滩""南京路步行街""五角场"
    点级：一个坐标就是全部，如"肯德基""上海博物馆"
    
    判定优先级：typecode > 名称关键词
    """
    tc = (typecode or "").strip()
    # typecode前2位命中区域级
    if len(tc) >= 2 and tc[:2] in config.AREA_TYPECODE_PREFIXES:
        return True
    # 名称含线性/区域关键词
    for kw in config.LINEAR_ANCHOR_KEYWORDS:
        if kw in name:
            return True
    for kw in config.AREA_NAME_KEYWORDS:
        if kw in name:
            return True
    return False


async def _decompose_anchors(
    anchors: list[AnchorPlan],
    city: str,
    original_location: dict,
) -> list[SubAnchor]:
    """v3新增：锚点拆解，full_day拆分，确定降级等级"""
    sub_anchors: list[SubAnchor] = []

    for idx, anchor in enumerate(anchors):
        time_budget = anchor.final_time_budget or anchor.final_capacity or "half_day"

        # ── v5.2 r5: 按POI空间性质决定搜索策略，而非time_budget ──
        # 区域级POI（外滩/南京路步行街/五角场）→ bbox polygon搜索，约束区域防泄漏
        # 点级POI（肯德基/某个博物馆）→ radius搜索，一个坐标就是全部
        _is_area = _is_area_poi(anchor.name, anchor.typecode or "")
        anchor_lat = anchor.location.get("lat", 0)
        anchor_lng = anchor.location.get("lng", 0)

        if time_budget in ("quarter_day", "half_day"):
            if _is_area:
                # 区域级：bbox polygon搜索，约束范围
                all_raw: list[dict] = []
                bbox_length = 2.0 if time_budget == "half_day" else 1.5
                bbox_width = 1.0 if time_budget == "half_day" else 0.75
                custom_polygon = _make_anchor_bbox_polygon(anchor_lat, anchor_lng, bbox_length, bbox_width)
                if custom_polygon:
                    try:
                        poly_results = await gaode_polygon_search_batch([
                            {"polygon": custom_polygon, "types": config.ANCHOR_INTERNAL_TYPES, "offset": 25, "show_fields": config.GAODE_SHOW_FIELDS},
                            {"polygon": custom_polygon, "keywords": anchor.name, "types": config.ANCHOR_INTERNAL_TYPES, "offset": 25, "show_fields": config.GAODE_SHOW_FIELDS},
                        ])
                        all_raw = poly_results[0] + poly_results[1]
                    except Exception:
                        pass

                # 去重 + 排除无关类型
                seen: set[str] = set()
                internal_pois: list[dict] = []
                for raw in all_raw:
                    pid = raw.get("id") or raw.get("name", "")
                    if pid in seen:
                        continue
                    seen.add(pid)
                    name = raw.get("name", "")
                    typecode = raw.get("typecode", "")
                    if name == anchor.name:
                        continue
                    if not is_valid_route_poi(typecode, name):
                        continue
                    loc = raw.get("location")
                    if isinstance(loc, str):
                        parts = loc.split(",")
                        loc = {"lng": float(parts[0]), "lat": float(parts[1])}
                    raw["location"] = loc
                    internal_pois.append(raw)

                # 线性锚点keyword补充搜索（沿街覆盖）
                _is_linear = any(kw in anchor.name for kw in config.LINEAR_ANCHOR_KEYWORDS)
                if _is_linear and len(internal_pois) < 6:
                    try:
                        search_radius = config.ANCHOR_SEARCH_RADIUS_BY_CAPACITY.get(time_budget, config.ANCHOR_INTERNAL_SEARCH_RADIUS)
                        linear_requests = [
                            {"location": f"{anchor_lng},{anchor_lat}", "keywords": anchor.name, "radius": search_radius, "types": config.ANCHOR_INTERNAL_TYPES, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25},
                        ]
                        linear_results = await gaode_around_search_batch(linear_requests)
                        for raw in linear_results[0]:
                            pid = raw.get("id") or raw.get("name", "")
                            if pid in seen:
                                continue
                            seen.add(pid)
                            name = raw.get("name", "")
                            typecode = raw.get("typecode", "")
                            if name == anchor.name or not is_valid_route_poi(typecode, name):
                                continue
                            loc = raw.get("location")
                            if isinstance(loc, str):
                                parts = loc.split(",")
                                loc = {"lng": float(parts[0]), "lat": float(parts[1])}
                            raw["location"] = loc
                            internal_pois.append(raw)
                    except Exception:
                        pass

                level, hint = _determine_degradation(internal_pois, time_budget)
            else:
                # 点级：直接创建空SubAnchor，由_search_anchor_internals做radius搜索
                internal_pois = []
                level, hint = "normal", None

            sub = SubAnchor(
                parent_name=anchor.name,
                name=anchor.name,
                location=anchor.location,
                time_budget_min=config.FULL_DAY_SPLIT_BUDGET_MIN * 2 if time_budget == "half_day" else config.FULL_DAY_SPLIT_BUDGET_MIN,
                capacity=time_budget,
                internal_pois=internal_pois,
                degradation_level=level,
                degradation_hint=hint,
                original_anchor_index=idx,
            )
            sub_anchors.append(sub)
            continue

        # full_day: 自定义矩形多边形优先 → 行政区边界兜底 → 多中心半径兜底
        all_raw: list[dict] = []
        # Step A: 生成自定义矩形多边形（N-S方向3km×1.5km），覆盖线性锚点全长
        anchor_lat = anchor.location.get("lat", 0)
        anchor_lng = anchor.location.get("lng", 0)
        custom_polygon = _make_anchor_bbox_polygon(anchor_lat, anchor_lng)
        if custom_polygon:
            try:
                poly_results = await gaode_polygon_search_batch([
                    {"polygon": custom_polygon, "types": config.ANCHOR_INTERNAL_TYPES, "offset": 25, "show_fields": config.GAODE_SHOW_FIELDS},
                    {"polygon": custom_polygon, "keywords": anchor.name, "types": config.ANCHOR_INTERNAL_TYPES, "offset": 25, "show_fields": config.GAODE_SHOW_FIELDS},  # v5.2 r4: 加types过滤
                ])
                all_raw = poly_results[0] + poly_results[1]
            except Exception:
                pass
        if not all_raw and anchor.fixed:
            # Step B: fixed_poi 尝试行政区边界多边形
            polygon = await _resolve_polygon(anchor)
            if polygon:
                try:
                    poly_results = await gaode_polygon_search_batch([
                        {"polygon": polygon, "types": config.ANCHOR_INTERNAL_TYPES, "offset": 25, "show_fields": config.GAODE_SHOW_FIELDS},
                        {"polygon": polygon, "keywords": anchor.name, "types": config.ANCHOR_INTERNAL_TYPES, "offset": 25, "show_fields": config.GAODE_SHOW_FIELDS},  # v5.2 r4: 加types过滤
                    ])
                    all_raw = poly_results[0] + poly_results[1]
                except Exception:
                    pass
        if not all_raw:
            # Step C: 多中心半径兜底 + sortrule=weight
            search_radius = config.ANCHOR_SEARCH_RADIUS_BY_CAPACITY.get(time_budget, config.ANCHOR_INTERNAL_SEARCH_RADIUS)
            offsets = [0.0, -0.0135, 0.0135]
            requests = []
            for offset in offsets:
                loc = f"{anchor_lng},{anchor_lat + offset}"
                requests.append({"location": loc, "keywords": "", "radius": search_radius, "types": config.ANCHOR_INTERNAL_TYPES, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25, "sortrule": "weight"})
            requests.append({"location": f"{anchor_lng},{anchor_lat}", "keywords": anchor.name, "radius": search_radius, "types": config.ANCHOR_INTERNAL_TYPES, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25})
            # v5.2: 亲水/沿河关键词搜索 — v5.2 r4: 加types过滤，避免不限类型返回
            requests.append({"location": f"{anchor_lng},{anchor_lat}", "keywords": f"{anchor.name} {config.WATERFRONT_KEYWORDS}", "radius": search_radius, "types": config.ANCHOR_INTERNAL_TYPES, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25})
            results = await gaode_around_search_batch(requests)
            for r in results:
                all_raw.extend(r)

        # 去重 + 排除无关类型
        seen: set[str] = set()
        internal_pois: list[dict] = []
        for raw in all_raw:
            pid = raw.get("id") or raw.get("name", "")
            if pid in seen:
                continue
            seen.add(pid)
            name = raw.get("name", "")
            typecode = raw.get("typecode", "")
            if name == anchor.name:
                continue
            if not is_valid_route_poi(typecode, name):
                continue
            loc = raw.get("location")
            if isinstance(loc, str):
                parts = loc.split(",")
                loc = {"lng": float(parts[0]), "lat": float(parts[1])}
            raw["location"] = loc
            internal_pois.append(raw)

        # v5.2 r4: 线性锚点（街/路/步行街等）补充keyword搜索
        # 让高德沿街返回POI，解决单点半径搜索POI集中在中段、两端缺失的问题
        _is_linear = any(kw in anchor.name for kw in config.LINEAR_ANCHOR_KEYWORDS)
        if _is_linear and len(internal_pois) < 6:
            try:
                linear_requests = [
                    {"location": f"{anchor_lng},{anchor_lat}", "keywords": anchor.name, "radius": search_radius, "types": config.ANCHOR_INTERNAL_TYPES, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25},
                ]
                linear_results = await gaode_around_search_batch(linear_requests)
                for raw in linear_results[0]:
                    pid = raw.get("id") or raw.get("name", "")
                    if pid in seen:
                        continue
                    seen.add(pid)
                    name = raw.get("name", "")
                    typecode = raw.get("typecode", "")
                    if name == anchor.name or not is_valid_route_poi(typecode, name):
                        continue
                    loc = raw.get("location")
                    if isinstance(loc, str):
                        parts = loc.split(",")
                        loc = {"lng": float(parts[0]), "lat": float(parts[1])}
                    raw["location"] = loc
                    internal_pois.append(raw)
            except Exception:
                pass

        # 降级判断
        level, hint = _determine_degradation(internal_pois, "full_day")

        if level in ("sparse", "free"):
            # 少量POI，不拆
            sub = SubAnchor(
                parent_name=anchor.name,
                name=anchor.name,
                location=anchor.location,
                time_budget_min=config.FULL_DAY_SPLIT_BUDGET_MIN * 2,
                capacity="full_day",
                internal_pois=internal_pois,
                degradation_level=level,
                degradation_hint=hint,
                original_anchor_index=idx,
            )
            sub_anchors.append(sub)
            continue

        # PCA分析 + 拆分
        if len(internal_pois) >= 2:
            coords = [poi["location"] for poi in internal_pois if poi.get("location")]
            if len(coords) >= 2:
                variance_ratio, principal_axis, projections = _pca_analysis(coords)

                if variance_ratio > config.LINEAR_VARIANCE_THRESHOLD:
                    # 线性拆分：沿主轴中点一分为二
                    median_proj = float(np.median(projections))
                    group_a = [internal_pois[i] for i in range(len(internal_pois)) if projections[i] <= median_proj]
                    group_b = [internal_pois[i] for i in range(len(internal_pois)) if projections[i] > median_proj]

                    a_avg_lat = np.mean([p["location"]["lat"] for p in group_a]) if group_a else 0
                    b_avg_lat = np.mean([p["location"]["lat"] for p in group_b]) if group_b else 0
                    south = group_a if a_avg_lat < b_avg_lat else group_b
                    north = group_b if a_avg_lat < b_avg_lat else group_a

                    # v5.2: 收集子锚点后按入口方向排序，不再固定南段先走
                    anchor_subs: list[SubAnchor] = []
                    for suffix, group in [("南段", south), ("北段", north)]:
                        if group:
                            lats = [p["location"]["lat"] for p in group]
                            lngs = [p["location"]["lng"] for p in group]
                            center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
                            anchor_subs.append(SubAnchor(
                                parent_name=anchor.name,
                                name=f"{anchor.name}{suffix}",
                                location=center,
                                time_budget_min=config.FULL_DAY_SPLIT_BUDGET_MIN,
                                capacity="full_day",
                                internal_pois=group,
                                degradation_level=level,
                                variance_ratio=variance_ratio,
                                original_anchor_index=idx,
                            ))
                    # v5.2: 按离用户入口点距离排序，近的先走，避免大环线
                    if len(anchor_subs) >= 2 and original_location:
                        anchor_subs.sort(key=lambda s: haversine_km(s.location, original_location))
                    sub_anchors.extend(anchor_subs)
                    continue

                # 聚类拆分：手动2-means
                centroids, labels = _kmeans_2(internal_pois)
                if centroids is not None:
                    near_center = centroids[0] if haversine_km(centroids[0], anchor.location) < haversine_km(centroids[1], anchor.location) else centroids[1]
                    far_center = centroids[1] if near_center == centroids[0] else centroids[0]

                    near_group = [internal_pois[i] for i, lbl in enumerate(labels) if lbl == (0 if near_center == centroids[0] else 1)]
                    far_group = [internal_pois[i] for i, lbl in enumerate(labels) if lbl != (0 if near_center == centroids[0] else 1)]

                    # v3.1 F2：按实际空间方向命名（南/北或东/西），而非"核心区/深度区"
                    near_label, far_label = _direction_labels_for_groups(near_group, far_group)

                    # v5.2: 收集子锚点后按入口方向排序
                    anchor_subs: list[SubAnchor] = []
                    if near_group:
                        lats = [p["location"]["lat"] for p in near_group]
                        lngs = [p["location"]["lng"] for p in near_group]
                        center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
                        anchor_subs.append(SubAnchor(
                            parent_name=anchor.name, name=f"{anchor.name}{near_label}",
                            location=center, time_budget_min=config.FULL_DAY_SPLIT_BUDGET_MIN,
                            capacity="full_day",
                            internal_pois=near_group, degradation_level=level,
                            variance_ratio=variance_ratio, original_anchor_index=idx,
                        ))
                    if far_group:
                        lats = [p["location"]["lat"] for p in far_group]
                        lngs = [p["location"]["lng"] for p in far_group]
                        center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
                        anchor_subs.append(SubAnchor(
                            parent_name=anchor.name, name=f"{anchor.name}{far_label}",
                            location=center, time_budget_min=config.FULL_DAY_SPLIT_BUDGET_MIN,
                            capacity="full_day",
                            internal_pois=far_group, degradation_level=level,
                            variance_ratio=variance_ratio, original_anchor_index=idx,
                        ))
                    # v5.2: 按离用户入口点距离排序，近的先走
                    if len(anchor_subs) >= 2 and original_location:
                        anchor_subs.sort(key=lambda s: haversine_km(s.location, original_location))
                    sub_anchors.extend(anchor_subs)
                    continue

        # 兜底：不拆，包装为一个SubAnchor
        sub = SubAnchor(
            parent_name=anchor.name, name=anchor.name, location=anchor.location,
            time_budget_min=config.FULL_DAY_SPLIT_BUDGET_MIN * 2,
            capacity="full_day",
            internal_pois=internal_pois, degradation_level=level,
            degradation_hint=hint, original_anchor_index=idx,
        )
        sub_anchors.append(sub)

    # v5.2: 对每个子锚点做补充搜索 — 以子锚点质心为中心，用sortrule=weight搜索
    # 解决拆分后子锚点只继承父搜索POI子集、POI不够的问题
    sub_anchors = await _supplementary_search_for_sub_anchors(sub_anchors)

    return sub_anchors


def _kmeans_2(pois: list[dict]) -> tuple[list[dict] | None, list[int] | None]:
    """手动2-means实现，避免sklearn依赖"""
    coords_list = [(i, p["location"]) for i, p in enumerate(pois) if p.get("location")]
    if len(coords_list) < 2:
        return None, None

    # 选最远两点为初始中心
    max_dist = -1
    c1_idx = c2_idx = 0
    for i in range(len(coords_list)):
        for j in range(i + 1, len(coords_list)):
            d = haversine_km(coords_list[i][1], coords_list[j][1])
            if d > max_dist:
                max_dist = d
                c1_idx, c2_idx = coords_list[i][0], coords_list[j][0]

    if max_dist <= 0:
        return None, None

    c1 = pois[c1_idx]["location"]
    c2 = pois[c2_idx]["location"]

    # 迭代3次
    for _ in range(3):
        labels = []
        for p in pois:
            loc = p.get("location")
            if not loc:
                labels.append(0)
                continue
            d1 = haversine_km(c1, loc)
            d2 = haversine_km(c2, loc)
            labels.append(0 if d1 < d2 else 1)

        g0_lats = [pois[i]["location"]["lat"] for i, lbl in enumerate(labels) if lbl == 0 and pois[i].get("location")]
        g0_lngs = [pois[i]["location"]["lng"] for i, lbl in enumerate(labels) if lbl == 0 and pois[i].get("location")]
        g1_lats = [pois[i]["location"]["lat"] for i, lbl in enumerate(labels) if lbl == 1 and pois[i].get("location")]
        g1_lngs = [pois[i]["location"]["lng"] for i, lbl in enumerate(labels) if lbl == 1 and pois[i].get("location")]

        if g0_lats:
            c1 = {"lat": sum(g0_lats) / len(g0_lats), "lng": sum(g0_lngs) / len(g0_lngs)}
        if g1_lats:
            c2 = {"lat": sum(g1_lats) / len(g1_lats), "lng": sum(g1_lngs) / len(g1_lngs)}

    return [c1, c2], labels


async def _search_anchor_internals(
    sub_anchors: list[SubAnchor],
    city: str,
    theme_search_terms: list[str] | None = None,
) -> list[SubAnchor]:
    """v3+v5.2：为half_day/quarter_day SubAnchor搜索内部POI；
    对已有POI但数量不足的子锚点做扩搜（1.5倍半径）；
    搜索时加入亲水/沿河关键词。"""
    # v5.2: 不仅搜没有POI的，也搜POI不足的（sparse降级）
    min_counts = {"full_day": 6, "half_day": 4, "quarter_day": 3}
    to_search = [
        sub for sub in sub_anchors
        if sub.degradation_level not in ("free",)
        and (
            not sub.internal_pois
            or len(sub.internal_pois) < min_counts.get(sub.capacity, 4)
        )
    ]
    if not to_search:
        return sub_anchors

    requests = []
    metadata = []
    for sub in to_search:
        loc_str = coord_to_param(sub.location)
        base_radius = config.ANCHOR_SEARCH_RADIUS_BY_CAPACITY.get(sub.capacity, config.ANCHOR_INTERNAL_SEARCH_RADIUS)
        # 如果已有POI但不够，扩大搜索半径1.5倍
        radius = base_radius if not sub.internal_pois else int(base_radius * 1.5)
        requests.extend([
            {"location": loc_str, "keywords": "", "radius": radius, "types": config.ANCHOR_INTERNAL_TYPES, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25, "sortrule": "weight"},
        # v5.2 r5: keyword搜索也加types过滤，防止返回餐饮等无关POI
            {"location": loc_str, "keywords": sub.parent_name, "radius": radius, "types": config.ANCHOR_INTERNAL_TYPES, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25},
            # v5.2: 亲水/沿河关键词搜索 — v5.2 r5: 加types过滤
            {"location": loc_str, "keywords": f"{sub.parent_name} {config.WATERFRONT_KEYWORDS}", "radius": radius, "types": config.ANCHOR_INTERNAL_TYPES, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 25},
        ])
        # v16: 主题微观搜索 — 将theme_search_terms合并到第一组keywords搜索
        if theme_search_terms:
            requests[-3]["keywords"] = " ".join(
                list(filter(None, [str(requests[-3].get("keywords", "") or "").strip()]))
                + list(theme_search_terms[:6])
            )[:200]
        metadata.append(sub)

    results = await gaode_around_search_batch(requests)

    for sub, (s1, s2, s3) in zip(to_search, [(results[i], results[i+1], results[i+2]) for i in range(0, len(results), 3)]):
        seen: set[str] = {p.get("id") or p.get("name", "") for p in (sub.internal_pois or [])}
        internal: list[dict] = list(sub.internal_pois or [])
        # v5.2: 两轮过滤——先正常过滤，数量不足时放行商场内子店铺
        subordinate_buffer: list[dict] = []  # 被subordinate过滤的POI，备用补充
        for raw in s1 + s2 + s3:
            pid = raw.get("id") or raw.get("name", "")
            if pid in seen:
                continue
            seen.add(pid)
            name = raw.get("name", "")
            typecode = raw.get("typecode", "")
            if name == sub.parent_name or name == sub.name:
                continue
            if not is_valid_route_poi(typecode, name):
                # 检查：跳过subordinate检查后是否能通过（仅因商场归属被过滤）
                if is_valid_route_poi(typecode, name, skip_subordinate_check=True):
                    loc = raw.get("location")
                    if isinstance(loc, str):
                        parts = loc.split(",")
                        loc = {"lng": float(parts[0]), "lat": float(parts[1])}
                    raw["location"] = loc
                    subordinate_buffer.append(raw)
                continue
            loc = raw.get("location")
            if isinstance(loc, str):
                parts = loc.split(",")
                loc = {"lng": float(parts[0]), "lat": float(parts[1])}
            raw["location"] = loc
            internal.append(raw)
        # 数量不足时放行商场内子店铺作为补充
        if len(internal) < 3 and subordinate_buffer:
            internal.extend(subordinate_buffer)
        sub.internal_pois = internal
        level, hint = _determine_degradation(internal, sub.capacity)
        if level != sub.degradation_level or not sub.degradation_hint:
            sub.degradation_level = level
            if hint and not sub.degradation_hint:
                sub.degradation_hint = hint

    return sub_anchors


def _is_passthrough_poi(poi: dict) -> bool:
    """v5.2: 判断POI是否为沿途经过型（公园/广场/观景台），这类POI几乎不占停留时间"""
    typecode = (poi.get("typecode") or "").strip()
    name = poi.get("name", "")
    if typecode in config.ROUTE_POI_PASSTHROUGH_TYPES or (typecode[:4] + "00") in config.ROUTE_POI_PASSTHROUGH_TYPES:
        return True
    for kw in config.PASSTHROUGH_NAME_KEYWORDS:
        if kw in name:
            return True
    return False


def _is_waterfront_anchor(anchor_name: str) -> bool:
    """v5.2: 判断锚点名是否为沿江/亲水区域，用于注入江边waypoint"""
    if not anchor_name:
        return False
    for kw in config.WATERFRONT_ANCHOR_KEYWORDS:
        if kw in anchor_name:
            return True
    return False


def _get_visit_duration(poi: dict) -> int:
    """v5.2: 沿途经过型POI只算5分钟停留，其余按typecode映射"""
    if _is_passthrough_poi(poi):
        return config.PASSTHROUGH_VISIT_DURATION_MIN
    rating = float(poi.get("rating") or 0)
    typecode = poi.get("typecode", "")
    if rating > 0:
        return config.VISIT_DURATION_MAP.get(typecode[:6], config.DEFAULT_VISIT_DURATION_MIN)
    return 20  # 无评分：历史建筑/地标等，外观打卡


def _has_rating(poi: dict) -> bool:
    return float(poi.get("rating") or 0) > 0


# ═══ v13: 微POI主题策略 ═══

MICRO_SPORT_TERMS = (
    "攀岩", "网球", "羽毛球", "乒乓", "篮球", "足球",
    "保龄球", "游泳", "健身", "瑜伽", "拳击", "台球",
    "射箭", "滑雪", "体育", "球馆",
)

MICRO_EXPLICIT_SPORT_TERMS = (
    "攀岩", "网球", "羽毛球", "乒乓", "篮球", "足球",
    "保龄球", "游泳", "健身", "瑜伽", "拳击", "台球",
    "射箭", "滑雪", "运动",
)

# v14: 使用主题画像系统
try:
    from .theme_profiles import build_effective_theme_profile
    from .theme_profile_matcher import poi_has_competing_theme
except ImportError:
    from services.theme_profiles import build_effective_theme_profile
    from services.theme_profile_matcher import poi_has_competing_theme


def _resolve_micro_poi_policy(parsed_intent: ParsedIntent) -> dict[str, Any]:
    profile = build_effective_theme_profile(parsed_intent)
    if not profile.get("active"):
        return {"active": False, "label": "", "reject_unrequested_sports": False}

    text = _intent_text(parsed_intent)
    explicit_sport = any(term in text for term in MICRO_EXPLICIT_SPORT_TERMS)

    excluded_terms = set(profile.get("excluded_terms", []) or [])
    if explicit_sport:
        excluded_terms = {t for t in excluded_terms if t not in MICRO_SPORT_TERMS}

    time_budget = float(getattr(parsed_intent, "time_budget", 0.25) or 0.25)
    minimum_themed_pois = 3 if time_budget >= 1.0 else (2 if time_budget >= 0.5 else 1)

    return {
        "active": True,
        "profile_id": profile.get("id", ""),
        "label": profile.get("label", ""),
        "search_terms": tuple(profile.get("search_terms", []) or []),
        "preferred_name_terms": tuple(profile.get("required_terms", []) or []),
        "micro_keywords": tuple(profile.get("micro_keywords", []) or []),
        "excluded_terms": tuple(excluded_terms),
        "generic_penalty_terms": tuple(profile.get("generic_penalty_terms", []) or []),
        "preferred_type_prefixes": set(profile.get("typecode_prefixes", []) or []),
        "excluded_typecode_prefixes": set(profile.get("excluded_typecode_prefixes", []) or []),
        "diversity_hint": tuple(profile.get("diversity_hint", []) or []),
        "reject_unrequested_sports": not explicit_sport,
        "minimum_themed_pois": minimum_themed_pois,
        "max_compatible_extras": 2,
    }


def _micro_poi_text(poi: dict[str, Any]) -> str:
    return " ".join(
        str(poi.get(field) or "")
        for field in ("name", "address", "type", "typecode", "category")
    ).lower()


def _is_unrequested_sport_poi(poi: dict[str, Any]) -> bool:
    text = _micro_poi_text(poi)
    type_prefix = str(poi.get("typecode") or "")[:2]
    return type_prefix == "08" or any(term in text for term in MICRO_SPORT_TERMS)


def _micro_poi_theme_score(poi: dict[str, Any], policy: dict[str, Any]) -> float:
    if not policy.get("active"):
        return 0.0
    text = _micro_poi_text(poi)
    type_prefix = str(poi.get("typecode") or "")[:2]

    required_hits = sum(1 for term in policy.get("preferred_name_terms", ()) if term and term.lower() in text)
    keyword_hits = sum(1 for term in policy.get("micro_keywords", ()) if term and term.lower() in text)

    score = min(required_hits, 3) * 12.0 + min(keyword_hits, 2) * 8.0
    if type_prefix in policy.get("preferred_type_prefixes", set()):
        score += 5.0
    if any(term and term.lower() in text for term in policy.get("excluded_terms", ())):
        score -= 100.0
    generic_hits = sum(
        1
        for term in policy.get("generic_penalty_terms", ())
        if term and term.lower() in text
    )
    score -= generic_hits * 12.0
    return score


def _is_micro_poi_compatible(poi: dict[str, Any], policy: dict[str, Any]) -> bool:
    if not policy.get("active"):
        return True
    text = _micro_poi_text(poi)
    type_prefix = str(poi.get("typecode") or "")[:2]
    if type_prefix in policy.get("excluded_typecode_prefixes", set()):
        return False
    if any(term and term.lower() in text for term in policy.get("excluded_terms", ())):
        return False
    if policy.get("reject_unrequested_sports") and _is_unrequested_sport_poi(poi):
        return False
    if _micro_poi_theme_score(poi, policy) <= 0 and poi_has_competing_theme(
        poi,
        str(policy.get("profile_id") or ""),
    ):
        return False
    return True


def _filter_and_sort_internal_pois(
    raw_pois: list[dict],
    entry_point: dict,
    time_budget_min: int,
    variance_ratio: float = 0.0,
    is_large_area: bool = False,
    micro_policy: dict[str, Any] | None = None,
    parsed_intent: Any = None,
) -> tuple[list[dict], str | None]:
    """v3+v20：排除无关typecode → 空间排序 → 跳过优化 → 时间预算裁剪 → 深度体验兜底

    v20: 传递 parsed_intent，让 is_valid_route_poi 按意图控制 typecode 过滤。
    逛吃穿插意图允许 05 轻餐饮和 06 购物/街区体验点。
    """

    policy = micro_policy or {"active": False}

    # v20: 构建 intent context for is_valid_route_poi
    _explicit_meal = False
    _poi_qtype = ""
    _allowed_shopping: list[str] | None = None
    _is_stroll_eat = False
    if parsed_intent is not None:
        _explicit_meal = bool(getattr(parsed_intent, "explicit_meal_intent", False))
        _poi_qtype = getattr(parsed_intent, "poi_query_type", "") or ""
        constraints = getattr(parsed_intent, "other_constraints", []) or []
        _is_stroll_eat = "逛吃穿插" in constraints
        # For stroll_eat or food_cuisine theme: allow 06 shopping/stroll POIs
        if _is_stroll_eat or _poi_qtype in ("poi_category", "named_poi"):
            _allowed_shopping = ["06"]  # Allow all 06xxxx for stroll/shopping intent

    # v4.1 F1/F2 + v20: 用统一白/黑名单过滤，含意图感知的 05/06 放行
    valid: list[dict] = []
    subordinate_buffer: list[dict] = []  # 被subordinate过滤的POI，备用补充
    _raw_poi_log: list[str] = []
    for poi in raw_pois:
        typecode = poi.get("typecode", "")
        name = poi.get("name", "")
        _raw_poi_log.append(f"{name}({typecode})")
        if not is_valid_route_poi(
            typecode, name,
            explicit_meal_intent=_explicit_meal,
            poi_query_type=_poi_qtype,
            allowed_shopping_prefixes=_allowed_shopping,
        ):
            # v20: collect light eat candidates into global buffer
            if _is_stroll_eat and _is_light_eat_candidate(poi):
                _stroll_eat_buffer.append(poi)
            # 检查：跳过subordinate检查后是否能通过
            if is_valid_route_poi(
                typecode, name, skip_subordinate_check=True,
                explicit_meal_intent=_explicit_meal,
                poi_query_type=_poi_qtype,
                allowed_shopping_prefixes=_allowed_shopping,
            ):
                subordinate_buffer.append(poi)
            continue
        valid.append(poi)

    print(
        f"[DEBUG step3 filter] raw={len(raw_pois)} valid={len(valid)} sub_buf={len(subordinate_buffer)} "
        f"stroll_eat={_is_stroll_eat} explicit_meal={_explicit_meal} "
        f"raw_names=[{', '.join(_raw_poi_log[:10])}]"
    )

    # 数量不足时放行商场内子店铺作为补充
    if len(valid) < 3 and subordinate_buffer:
        valid.extend(subordinate_buffer)

    theme_trim_hint: str | None = None
    # 主题策略过滤 — 在空间排序前执行
    if policy.get("active"):
        compatible = [
            poi
            for poi in valid
            if _is_micro_poi_compatible(poi, policy)
        ]
        if not compatible:
            return [], "该区域未检索到符合当前主题的可游览地点，已保留核心目的地供自由探索"

        themed = sorted(
            [poi for poi in compatible if _micro_poi_theme_score(poi, policy) > 0],
            key=lambda poi: _micro_poi_theme_score(poi, policy),
            reverse=True,
        )
        if len(themed) >= policy.get("minimum_themed_pois", 1):
            # Theme points dominate. Neutral compatible points are a small
            # connective supplement, never a way to fill an unrelated route.
            themed_names = {p.get("name") for p in themed}
            extras = [p for p in compatible if p.get("name") not in themed_names]
            max_extras = int(policy.get("max_compatible_extras", 2) or 0)
            valid = themed + extras[:max_extras]
            print(
                f"[DEBUG step3] theme_policy constrained compatible fallback "
                f"themed={len(themed)} compatible={len(compatible)} "
                f"extras={min(len(extras), max_extras)} final={len(valid)}"
            )
        else:
            valid = themed
            theme_trim_hint = (
                "该区域符合当前主题的地点不足，已仅保留主题相关地点，"
                "不再使用普通景点补齐路线"
            )
            print(
                f"[DEBUG step3] theme_policy insufficient themed pois: "
                f"required={policy.get('minimum_themed_pois', 1)} "
                f"themed={len(themed)} compatible={len(compatible)}"
            )

    if not valid:
        return [], theme_trim_hint

    # 大面积场景：估算容量，top-N 截断后再空间排序
    trim_hint: str | None = theme_trim_hint
    prefilt = valid
    if is_large_area and len(prefilt) > 8:
        avg_visit = config.DEFAULT_VISIT_DURATION_MIN
        avg_travel = 25 if is_large_area else 8
        est_capacity = max(3, time_budget_min // (avg_visit + avg_travel))
        if len(prefilt) > est_capacity:
            trim_hint = f"值得一去的景点很多，但考虑到一天的行程时间，我们精选了{est_capacity}处"
            prefilt = prefilt[:est_capacity]

    # v5.2 r5: 空间硬分配后POI已归属正确锚点，不再需要降权逻辑
    sorted_pois = _sort_backbone(prefilt, variance_ratio, entry_point)

    def _travel(prev_loc, poi_loc):
        if is_large_area:
            return _travel_time_min(prev_loc, poi_loc)
        return max(config.WALK_TIME_MIN_FLOOR, _estimated_walk_min(prev_loc, poi_loc))

    # 时间预算裁剪 + 跳过优化
    result: list[dict] = []
    cum_min = 0.0
    prev_loc = entry_point
    deep_count = 0
    i = 0
    while i < len(sorted_pois):
        poi = sorted_pois[i]
        visit = _get_visit_duration(poi)
        travel = _travel(prev_loc, poi.get("location"))
        if cum_min + travel + visit > time_budget_min:
            # 跳过优化：当前点耗时>60min且跳过它能让后面2+个点进来，则跳过
            remaining = sorted_pois[i + 1:]
            if visit > 60 and len(remaining) >= 2:
                test_cum = cum_min
                test_prev = prev_loc
                fit_count = 0
                for r_poi in remaining:
                    r_visit = _get_visit_duration(r_poi)
                    r_travel = _travel(test_prev, r_poi.get("location"))
                    if test_cum + r_travel + r_visit <= time_budget_min:
                        fit_count += 1
                        test_cum += r_travel + r_visit
                        test_prev = r_poi.get("location")
                    else:
                        break
                if fit_count >= 2:
                    i += 1
                    continue
            break
        cum_min += travel + visit
        result.append(poi)
        prev_loc = poi.get("location")
        if _has_rating(poi):
            deep_count += 1
        i += 1

    # 深度体验兜底：如果结果中没有一个有评分的点，用排序中第一个深度点替换末尾
    if deep_count == 0:
        deep_pois = [p for p in sorted_pois if _has_rating(p)]
        if deep_pois:
            # 在result中找位置插入（保持空间顺序）
            deep = deep_pois[0]
            if result:
                result[-1] = deep
            else:
                result.append(deep)

    if len(result) < 2 and len(sorted_pois) >= 2:
        result = sorted_pois[:2]
        trim_hint = None

    return result, trim_hint


def _sort_backbone(pois: list[dict], variance_ratio: float, entry_point: dict) -> list[dict]:
    """贪心最近邻排序：从入口点出发，每次选最近的未访问POI"""
    if not pois or len(pois) < 2:
        return list(pois)

    remaining = [dict(p) for p in pois]
    ordered: list[dict] = []
    cur_lat = entry_point.get("lat", 0)
    cur_lng = entry_point.get("lng", 0)

    while remaining:
        nearest = min(remaining, key=lambda p: (
            (p["location"]["lng"] - cur_lng) ** 2 + (p["location"]["lat"] - cur_lat) ** 2
        ))
        ordered.append(nearest)
        remaining.remove(nearest)
        cur_lat = nearest["location"]["lat"]
        cur_lng = nearest["location"]["lng"]

    return ordered


def _meal_search_points(
    sub_anchors: list[SubAnchor],
    meal_needs: list[str],
    original_location: dict,
) -> dict[str, dict]:
    """为餐点选择搜索参考点。

    通用规则：
    - 午餐：靠近当天前半段/上午锚点的末端；
    - 晚餐：靠近当天后半段/最后一个锚点的末端；
    - 不再用累计 time_budget_min 阈值判断，避免第一个锚点预算过大时把午餐和晚餐都落到同一区域。
    """
    result: dict[str, dict] = {}
    if not sub_anchors or not meal_needs:
        return result

    indexed_subs = list(enumerate(sub_anchors))
    ordered_subs = [
        sub
        for _, sub in sorted(
            indexed_subs,
            key=lambda row: (getattr(row[1], "original_anchor_index", row[0]), row[0]),
        )
    ]

    groups: list[list[SubAnchor]] = []
    current_group: list[SubAnchor] = []
    current_key = None
    for original_pos, sub in sorted(
        indexed_subs,
        key=lambda row: (getattr(row[1], "original_anchor_index", row[0]), row[0]),
    ):
        key = getattr(sub, "original_anchor_index", original_pos)
        if current_group and key != current_key:
            groups.append(current_group)
            current_group = []
        current_key = key
        current_group.append(sub)
    if current_group:
        groups.append(current_group)

    def _ref(sub: SubAnchor, meal_label: str) -> dict:
        loc = _v4_resolve_sub_end(sub) or sub.location or original_location
        return {
            "location": loc,
            "name": f"{meal_label}搜索点-{sub.name}",
        }

    if "lunch" in meal_needs:
        if len(groups) >= 2:
            lunch_sub = groups[0][-1]
        else:
            lunch_index = max(0, min(len(ordered_subs) - 1, len(ordered_subs) // 2 - 1))
            lunch_sub = ordered_subs[lunch_index]
        result["lunch"] = _ref(lunch_sub, "午餐")

    if "dinner" in meal_needs:
        if len(groups) >= 2:
            dinner_sub = groups[-1][-1]
        else:
            dinner_sub = ordered_subs[-1]
        result["dinner"] = _ref(dinner_sub, "晚餐")

    return result


def _route_planning(
    sub_anchors: list[SubAnchor],
    meal_pois: list[MicroPOI],
    parsed_intent: ParsedIntent,
    complete_plan: CompletePlan,
) -> list[dict[str, Any]]:
    """v5.2：简化路线排布 — 投影排序 + 贪心选取，不再区分anchor_internal和micro"""
    all_points: list[dict[str, Any]] = []
    meal_by_name: dict[str, MicroPOI] = {m.name: m for m in meal_pois}

    def _point_from_micro(item: MicroPOI, day_index: int, kind: str = "meal", meal_type: str = "") -> dict[str, Any]:
        pt = {
            "day": day_index,
            "name": item.name,
            "location": item.location,
            "kind": kind,
            "poi_id": item.gaode_poi_id or item.name,
            "gaode_poi_id": item.gaode_poi_id,
            "typecode": item.typecode,
            "category": item.typecode,
            "address": item.address,
            "rating": item.gaode_rating,
            "avg_cost": item.avg_cost,
            "photo_url": item.photo_url,
            "photo_source": item.photo_source,
            "parent_anchor": item.parent_anchor,
            "visit_duration_min": item.visit_duration_min,
        }
        if meal_type:
            pt["display_slot"] = meal_type
        return pt

    for day in complete_plan.day_plans:
        day_index = day.day_index
        origin = _origin_point(parsed_intent)

        # 找到该天的SubAnchor
        anchor_names = {a.name for a in day.anchors}
        day_subs = [s for s in sub_anchors if s.parent_name in anchor_names or s.name in anchor_names]

        # 获取餐饮slots
        lunch_slots = [s for s in day.meal_slots if s.get("meal") == "lunch"]
        dinner_slots = [s for s in day.meal_slots if s.get("meal") == "dinner"]

        # v6: 无 anchor 但有 meal slot 的纯餐饮日 — 直接将 meal POI 放入路线点
        if not day_subs:
            if day.meal_slots:
                all_points.append({
                    "day": day_index,
                    "name": origin["name"],
                    "location": origin.get("location", {}),
                    "kind": "start",
                })
                for slot in day.meal_slots:
                    pn = slot.get("poi_name")
                    if pn and pn in meal_by_name:
                        m = meal_by_name[pn]
                        all_points.append(_point_from_micro(m, day_index, "meal", slot.get("meal", "dinner")))
            continue
        day_meal_needs = []
        if lunch_slots:
            day_meal_needs.append("lunch")
        if dinner_slots:
            day_meal_needs.append("dinner")

        # 餐饮分段
        meal_refs = _meal_search_points(day_subs, day_meal_needs, origin.get("location", {}))
        segments = _insert_meals_in_route(day_subs, meal_refs, day_meal_needs, day_index)

        # 起点
        start = origin.get("location", {})
        current = {"name": origin["name"], "location": start}

        # dinner_first
        dinner_done = False
        if getattr(parsed_intent, "dinner_first", False) and dinner_slots:
            dinner_name = dinner_slots[0].get("poi_name")
            if dinner_name and dinner_name in meal_by_name:
                m = meal_by_name[dinner_name]
                all_points.append(_point_from_micro(m, day_index, "meal", "dinner"))
                current = {"name": m.name, "location": m.location}
                dinner_done = True

        all_points.append({"day": day_index, "name": current["name"], "location": current["location"], "kind": "start"})
        used_names: set[str] = {current["name"], origin["name"]}

        # 从day.meal_slots读取_select_meals填入的真实餐饮名称
        slot_meal_map: dict[str, str] = {}
        for slot in day.meal_slots:
            m = slot.get("meal")
            pn = slot.get("poi_name")
            if m and pn:
                slot_meal_map[m] = pn

        for seg_idx, seg in enumerate(segments):
            # v5.2 r3: 计算下一个锚点的中心位置，用于路线方向优化
            next_anchor_center = None
            if seg_idx + 1 < len(segments):
                next_seg = segments[seg_idx + 1]
                next_sub = next_seg.get("sub_anchor")
                if next_sub and next_sub.location:
                    next_anchor_center = next_sub.location

            # v5.2: _fill_segment 统一处理所有POI，不再传入 assigned_micro
            seg_points = _fill_segment(
                seg, seg.get("meal_poi_name"),
                current["location"], seg.get("time_budget", 240), day_index,
                used_names=used_names,
                entry_point=parsed_intent.original_location or {},
                next_anchor_center=next_anchor_center,
                parsed_intent=parsed_intent,
            )
            for sp in seg_points:
                # v5.2 r3 fix: _fill_segment可能把餐饮POI标记为anchor_internal，
                # 导致下游(1)短步行合并吞掉晚餐段 (2)step4路线缺失
                if sp["name"] in meal_by_name and sp.get("kind") != "meal":
                    sp["kind"] = "meal"
                all_points.append(sp)
                current = {"name": sp["name"], "location": sp["location"]}
                used_names.add(sp["name"])

            # 餐饮插入
            meal_name = seg.get("meal_poi_name")
            meal_type = None
            if not meal_name:
                if seg_idx == 0 and len(segments) >= 2:
                    meal_type = "lunch"
                elif seg_idx == len(segments) - 1:
                    meal_type = "dinner"
                if meal_type:
                    meal_name = slot_meal_map.get(meal_type)
            if meal_name and meal_name in meal_by_name and meal_name not in used_names:
                m = meal_by_name[meal_name]
                all_points.append(_point_from_micro(m, day_index, "meal", meal_type or ""))
                current = {"name": m.name, "location": m.location}
                used_names.add(m.name)
                if meal_type == "dinner":
                    dinner_done = True

        # 兜底未插入的晚餐
        if dinner_slots and not dinner_done:
            dinner_name = dinner_slots[0].get("poi_name")
            if dinner_name and dinner_name in meal_by_name and dinner_name not in used_names:
                m = meal_by_name[dinner_name]
                all_points.append(_point_from_micro(m, day_index, "meal", "dinner"))

    return _compress_points(all_points)


def _insert_meals_in_route(
    sub_anchors: list[SubAnchor],
    meal_refs: dict[str, dict],
    meal_needs: list[str],
    day_index: int,
) -> list[dict]:
    """v3新增：餐饮分段 — 确定餐饮在SubAnchor序列中的插入位置"""
    segments: list[dict] = []

    for i, sub in enumerate(sub_anchors):
        seg = {
            "sub_anchor": sub,
            "backbone": sub.internal_pois,
            "degradation": sub.degradation_level,
            "hint": sub.degradation_hint,
            "time_budget": sub.time_budget_min,
            "day": day_index,
        }

        # 单SubAnchor：餐饮在骨架中间
        if len(sub_anchors) == 1 and sub.internal_pois:
            mid = len(sub.internal_pois) // 2
            if "lunch" in meal_needs and "lunch" not in [s.get("meal_after") for s in segments]:
                seg["meal_poi_name"] = None  # will be filled from meal_refs
                seg["meal_after_mid"] = mid
            if "dinner" in meal_needs:
                seg["meal_at_end"] = "dinner"

        # 双SubAnchor：段1→午餐→段2
        elif len(sub_anchors) == 2:
            if i == 0 and "lunch" in meal_needs:
                seg["meal_poi_name"] = None  # lunch after this segment
            if i == 1 and "dinner" in meal_needs:
                seg["meal_poi_name"] = None  # dinner after this segment

        # 多SubAnchor
        else:
            cum = sum(s.time_budget_min for s in sub_anchors[:i+1])
            if "lunch" in meal_needs and cum >= 200 and i < len(sub_anchors) - 1:
                seg["meal_poi_name"] = None  # lunch after
            if "dinner" in meal_needs and cum >= 400 and i < len(sub_anchors) - 1:
                seg["meal_poi_name"] = None  # dinner after

        segments.append(seg)

    return segments

CORRIDOR_WIDTH_KM = 0.3  # 走廊宽度300米（v3.1 F8：从500m收窄为300m，强化空间归属约束）


def _point_to_segment_distance_deg(
    px: float, py: float, ax: float, ay: float, bx: float, by: float,
) -> float:
    """点到线段AB的垂直距离（经纬度单位）"""
    import math
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    ab_sq = abx**2 + aby**2
    if ab_sq == 0:
        return math.sqrt(apx**2 + apy**2)
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_sq))
    proj_x = ax + t * abx
    proj_y = ay + t * aby
    return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)


def _micro_in_corridor(
    micro_loc: dict, backbone_a_loc: dict, backbone_b_loc: dict, corridor_width_km: float = CORRIDOR_WIDTH_KM,
) -> bool:
    """检查微观点是否在两个backbone节点构成的走廊范围内"""
    corridor_width_deg = corridor_width_km / 111.0  # km转度
    dist_deg = _point_to_segment_distance_deg(
        micro_loc["lng"], micro_loc["lat"],
        backbone_a_loc["lng"], backbone_a_loc["lat"],
        backbone_b_loc["lng"], backbone_b_loc["lat"],
    )
    return dist_deg <= corridor_width_deg


def _fill_segment(
    segment: dict,
    meal_poi_name: str | None,
    start_location: dict,
    time_budget_min: int,
    day_index: int,
    used_names: set[str] | None = None,
    entry_point: dict | None = None,
    next_anchor_center: dict | None = None,
    parsed_intent: ParsedIntent | None = None,
) -> list[dict[str, Any]]:
    """v5.2 r3：投影排序 + 2-opt优化 + 贪心选取，统一处理所有POI（不再区分anchor_internal和micro）"""
    sub = segment.get("sub_anchor")
    if sub is None:
        return []

    poi_query_type = str(getattr(parsed_intent, "poi_query_type", "") or "") if parsed_intent else ""
    is_direct_primary_target = poi_query_type in {"poi_category", "named_poi"}

    def _primary_anchor_point() -> dict[str, Any]:
        """Keep the Step2 target itself executable even when internals are sparse."""
        return {
            "day": day_index,
            "name": sub.name,
            "location": sub.location or start_location,
            "kind": "anchor_internal",
            "poi_id": getattr(sub, "poi_id", None) or sub.name,
            "gaode_poi_id": getattr(sub, "gaode_poi_id", "") or "",
            "typecode": getattr(sub, "typecode", "") or "",
            "category": getattr(sub, "category", "") or "",
            "address": getattr(sub, "address", "") or "",
            "rating": getattr(sub, "rating", None),
            "avg_cost": getattr(sub, "avg_cost", None),
            "photo_url": getattr(sub, "photo_url", "") or "",
            "photo_source": getattr(sub, "photo_source", "") or "",
            "travel_before": 0,
            "sub_anchor_name": sub.name,
            "parent_name": getattr(sub, "parent_name", "") or "",
            "is_passthrough": False,
            "primary_target": True,
            "recommend_reason": "本次搜索的核心目标",
            "is_waypoint": True,
            "is_display_poi": True,
        }

    # For direct category/named-POI lookup, the selected Step2 anchor is the
    # destination. Nearby internals may be useful as later alternatives, but
    # they must not become route waypoints that dilute or replace the target.
    if is_direct_primary_target:
        if used_names is not None:
            used_names.add(sub.name)
        return [_primary_anchor_point()]

    if segment.get("degradation") == "free":
        intent_theme_id = str(getattr(parsed_intent, "theme_profile", "") or "") if parsed_intent else ""
        is_themed = bool(intent_theme_id or getattr(parsed_intent, "theme_label", None)) if parsed_intent else False
        is_full_or_half = (
            str(getattr(parsed_intent, "duration", "") or "").lower() in {
                "a full day", "full_day", "half day", "half_day",
            }
            or float(getattr(parsed_intent, "time_budget", 0) or 0) >= 0.5
        ) if parsed_intent else False

        if is_themed and is_full_or_half and (sub.location or start_location):
            # v18: 优先从 sub.internal_pois 取真实 POI，避免每半日只有一个 anchor
            internal = getattr(sub, "internal_pois", []) or []
            extra_points: list[dict[str, Any]] = []
            for ipo in internal[:4]:
                name = str(ipo.get("name") or "").strip()
                if not name or (used_names and name in used_names):
                    continue
                loc = ipo.get("location") or sub.location or start_location
                extra_points.append({
                    "day": day_index,
                    "name": name,
                    "location": loc,
                    "kind": "anchor_internal",
                    "poi_id": ipo.get("poi_id") or ipo.get("gaode_poi_id") or name,
                    "gaode_poi_id": str(ipo.get("gaode_poi_id") or ""),
                    "typecode": str(ipo.get("typecode") or ""),
                    "category": str(ipo.get("category") or ""),
                    "address": str(ipo.get("address") or ""),
                    "rating": ipo.get("rating"),
                    "avg_cost": ipo.get("avg_cost"),
                    "photo_url": str(ipo.get("photo_url") or ""),
                    "photo_source": str(ipo.get("photo_source") or ""),
                    "travel_before": 0,
                    "sub_anchor_name": sub.name,
                    "parent_name": getattr(sub, "parent_name", "") or "",
                    "is_passthrough": False,
                    "theme_anchor_fallback": True,
                    "fallback_reason": "theme_anchor_degraded_from_free_internal",
                    "recommend_reason": ipo.get("recommend_reason") or segment.get("hint", "") or f"该片区符合本次主题",
                    "is_waypoint": True,
                    "is_display_poi": True,
                })
                if used_names is not None:
                    used_names.add(name)
            if extra_points:
                print(
                    f"[DEBUG step3] filled free segment from internal_pois: "
                    f"{[p.get('name') for p in extra_points]}"
                )
                return extra_points

            # 没有 internal_pois 才退回单个 anchor_internal 占位
            return [{
                "day": day_index,
                "name": sub.name,
                "location": sub.location or start_location,
                "kind": "anchor_internal",
                "poi_id": getattr(sub, "poi_id", None) or sub.name,
                "gaode_poi_id": getattr(sub, "gaode_poi_id", "") or "",
                "typecode": getattr(sub, "typecode", "") or "",
                "category": getattr(sub, "category", "") or "",
                "address": getattr(sub, "address", "") or "",
                "rating": getattr(sub, "rating", None),
                "avg_cost": getattr(sub, "avg_cost", None),
                "photo_url": getattr(sub, "photo_url", "") or "",
                "photo_source": getattr(sub, "photo_source", "") or "",
                "travel_before": 0,
                "sub_anchor_name": sub.name,
                "parent_name": getattr(sub, "parent_name", "") or "",
                "is_passthrough": False,
                "theme_anchor_fallback": True,
                "fallback_reason": "theme_anchor_degraded_from_free",
                "recommend_reason": segment.get("hint", "") or "该片区符合本次主题，但周边细分POI召回不足，先保留核心片区作为可执行游览点。",
                "is_waypoint": True,
                "is_display_poi": True,
            }]

        return [{
            "day": day_index,
            "name": sub.name,
            "location": sub.location or start_location,
            "kind": "free_explore",
            "hint": segment.get("hint", ""),
        }]

    backbone = segment.get("backbone", [])
    _used = used_names or set()

    # 收集所有未使用的POI — 区分沿途经过型和深度游览型
    spine: list[dict[str, Any]] = []
    for node in backbone:
        name = node.get("name", "")
        loc = node.get("location")
        if not loc or name in _used:
            continue
        is_pass = _is_passthrough_poi(node)
        spine.append({
            "name": name,
            "location": loc,
            "kind": "anchor_internal",
            "poi_id": node.get("id") or node.get("gaode_poi_id") or name,
            "gaode_poi_id": node.get("id") or node.get("gaode_poi_id") or "",
            "typecode": node.get("typecode", ""),
            "category": node.get("typecode", ""),
            "address": node.get("address", ""),
            "rating": node.get("rating"),
            "avg_cost": (node.get("biz_ext") or {}).get("cost") if isinstance(node.get("biz_ext"), dict) else node.get("avg_cost"),
            "photo_url": ((node.get("photos") or [{}])[0] or {}).get("url") if isinstance(node.get("photos"), list) and node.get("photos") else node.get("photo_url", ""),
            "photo_source": "gaode" if isinstance(node.get("photos"), list) and node.get("photos") else node.get("photo_source", ""),
            "indoor_map": node.get("indoor_map", ""),
            "visit_min": config.PASSTHROUGH_VISIT_DURATION_MIN if is_pass else _get_visit_duration(node),
            "is_passthrough": is_pass,
        })

    if not spine:
        return []

    # v5.2 r3: 投影排序 + 2-opt优化 — 选起终点，按投影位置排序，再局部优化减少zigzag
    entry = entry_point or start_location
    start_poi, end_poi = _pick_route_endpoints(spine, entry, time_budget_min, next_anchor_center=next_anchor_center)
    ordered = _project_sort_pois(spine, start_poi, end_poi)
    # v5.2 r3: 局部2-opt优化，修正投影排序在环形POI分布（如明珠环岛）的zigzag
    ordered = _local_2opt_optimize(ordered)

    # v5.2: 贪心选取 — 沿排序顺序选取直到时间预算用完
    result: list[dict[str, Any]] = []
    current_loc = start_location
    used_time = 0.0

    # 如果 start_location 距离第一个POI太远（>2km），说明是城市间/远距离transit
    is_transit_start = False
    if ordered and ordered[0].get("location") and start_location:
        d_km = haversine_km(start_location, ordered[0].get("location"))
        is_transit_start = d_km > 2.0

    first_node = True
    for node in ordered:
        loc = node.get("location")
        if not loc:
            continue
        raw_travel = _estimated_walk_min(current_loc, loc)
        if is_transit_start and first_node:
            raw_travel = 10.0  # 远距离transit缓冲
            first_node = False
        travel = max(config.WALK_TIME_MIN_FLOOR, raw_travel)
        visit = node.get("visit_min", config.DEFAULT_VISIT_DURATION_MIN)

        if used_time + travel + visit > time_budget_min:
            continue  # 跳过超预算的，继续看后面的

        used_time += travel + visit
        is_pass = node.get("is_passthrough", False)
        result.append({
            "day": day_index,
            "name": node["name"],
            "location": loc,
            "kind": "anchor_internal",
            "poi_id": node.get("poi_id") or node["name"],
            "gaode_poi_id": node.get("gaode_poi_id", ""),
            "typecode": node.get("typecode", ""),
            "category": node.get("category", ""),
            "address": node.get("address", ""),
            "rating": node.get("rating"),
            "avg_cost": node.get("avg_cost"),
            "photo_url": node.get("photo_url", ""),
            "photo_source": node.get("photo_source", ""),
            "travel_before": round(travel, 1),
            "sub_anchor_name": sub.name,
            "parent_name": sub.parent_name,  # v5.2: 传递parent_name用于沿江检测
            "is_passthrough": is_pass,  # v5.2: 标记沿途经过型
        })
        _used.add(node["name"])
        current_loc = loc

    # 至少保留2个POI
    if len(result) < 2 and len(ordered) >= 2:
        for node in ordered[:2]:
            if node["name"] not in {r["name"] for r in result}:
                is_pass = node.get("is_passthrough", False)
                result.append({
                    "day": day_index,
                    "name": node["name"],
                    "location": node.get("location", start_location),
                    "kind": "anchor_internal",
                    "poi_id": node.get("poi_id") or node["name"],
                    "gaode_poi_id": node.get("gaode_poi_id", ""),
                    "typecode": node.get("typecode", ""),
                    "category": node.get("category", ""),
                    "address": node.get("address", ""),
                    "rating": node.get("rating"),
                    "avg_cost": node.get("avg_cost"),
                    "photo_url": node.get("photo_url", ""),
                    "photo_source": node.get("photo_source", ""),
                    "travel_before": 0,
                    "sub_anchor_name": sub.name,
                    "parent_name": sub.parent_name,  # v5.2: 传递parent_name用于沿江检测
                    "is_passthrough": is_pass,
                })
                _used.add(node["name"])

    # sparse 降级 / 大面积裁剪提示
    hint_text = segment.get("hint", "")
    if hint_text:
        result.append({
            "day": day_index,
            "name": hint_text,
            "location": current_loc if result else start_location,
            "kind": "hint",
            "hint": hint_text,
        })

    # ── v6: 收集未选中候选 POI ──
    _result_names: set[str] = {r.get("name", "") for r in result if r.get("kind") != "hint"}
    _candidates: list[dict] = []
    for node in ordered:
        n_name = node.get("name", "")
        if n_name in _result_names:
            continue
        if n_name in _used:
            continue
        # 排除无效 kind
        if node.get("kind") in ("hint", "free_explore", "route_only", "traffic", "empty"):
            continue
        n_rating = node.get("rating")
        try:
            n_rating_val = float(n_rating) if n_rating is not None else 0.0
        except (ValueError, TypeError):
            n_rating_val = 0.0
        _candidates.append({
            "name": n_name,
            "location": node.get("location") or {},
            "kind": "candidate",
            "candidate_source": "micro_pool",
            "poi_id": node.get("poi_id") or n_name,
            "gaode_poi_id": node.get("gaode_poi_id", ""),
            "typecode": node.get("typecode", ""),
            "category": node.get("category", node.get("typecode", "")),
            "address": node.get("address", ""),
            "rating": n_rating_val,
            "gaode_rating": n_rating_val,
            "avg_cost": node.get("avg_cost"),
            "photo_url": node.get("photo_url", ""),
            "photo_source": node.get("photo_source", ""),
            "parent_anchor": sub.parent_name,
            "sub_anchor_name": sub.name,
            "recommend_reason": "",
            "candidate_score": n_rating_val,
            "day": day_index,
        })
    if _candidates:
        pool_key = (day_index, sub.name)
        _candidate_pool[pool_key] = _candidates

    return result
def _to_micro(raw: dict[str, Any], parent_anchor: str, is_meal: bool = False) -> MicroPOI | None:
    try:
        data = raw_to_place(raw)
        return MicroPOI(
            name=data["name"],
            location=data["location"],
            typecode=data["typecode"],
            gaode_poi_id=data["gaode_poi_id"],
            address=data.get("address", ""),
            gaode_rating=data["gaode_rating"],
            avg_cost=data["avg_cost"],
            photo_url=data.get("photo_url", ""),
            photo_source="gaode" if data.get("photo_url") else "",
            visit_duration_min=_visit_duration(data["typecode"], is_meal=is_meal),
            is_meal=is_meal,
            parent_anchor=parent_anchor,
            indoor_map=data.get("indoor_map", ""),
        )
    except Exception:
        return None


def _dedupe_micro(items: list[MicroPOI]) -> list[MicroPOI]:
    by_id: dict[str, MicroPOI] = {}
    for item in items:
        base_key = item.gaode_poi_id or item.name
        key = base_key
        current = by_id.get(key)
        if current is None or (item.gaode_rating or 0) > (current.gaode_rating or 0):
            by_id[key] = item
    return list(by_id.values())


def _budget_filter(items: list[MicroPOI], threshold: float) -> list[MicroPOI]:
    return [item for item in items if item.avg_cost is None or item.avg_cost <= threshold]


def _unique_keywords(values: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip()
        if clean and clean not in seen:
            result.append(clean)
            seen.add(clean)
        if limit is not None and len(result) >= limit:
            break
    return result


SHOPPING_INTENT_TERMS = ["逛商场", "商场", "购物", "买东西", "逛街", "商业体", "综合体", "商圈", "买手店", "潮牌"]
EATING_INTENT_TERMS = ["吃吃喝喝", "逛吃", "美食", "餐饮", "餐厅", "小吃", "探店", "咖啡", "甜品", "下午茶", "夜宵"]
NEARBY_INTENT_TERMS = ["附近", "周边", "逛逛", "逛一逛", "随便逛", "散步", "转转", "不走远", "近一点"]
LATE_NEARBY_WALK_CUTOFF_HOUR = 21
LATE_NEARBY_MAX_STRAIGHT_KM = 1.2


def _intent_text(parsed_intent: ParsedIntent) -> str:
    parts = [
        *parsed_intent.raw_keywords,
        *parsed_intent.search_keywords,
        *parsed_intent.micro_keywords,
        *parsed_intent.food_pref_keywords,
        *getattr(parsed_intent, "meal_search_keywords", []),
        *parsed_intent.other_constraints,
    ]
    return " ".join(part for part in parts if part).lower()


def _has_any_intent(parsed_intent: ParsedIntent, terms: list[str]) -> bool:
    text = _intent_text(parsed_intent)
    return any(term.lower() in text for term in terms)


def _has_shopping_intent(parsed_intent: ParsedIntent) -> bool:
    return _has_any_intent(parsed_intent, SHOPPING_INTENT_TERMS)


def _has_eating_activity_intent(parsed_intent: ParsedIntent) -> bool:
    return _has_any_intent(parsed_intent, EATING_INTENT_TERMS)


def _is_late_nearby_walk_request(parsed_intent: ParsedIntent) -> bool:
    if not parsed_intent.start_time or parsed_intent.start_time.hour < LATE_NEARBY_WALK_CUTOFF_HOUR:
        return False
    return parsed_intent.time_budget <= 0.25 or _has_any_intent(parsed_intent, NEARBY_INTENT_TERMS)


def _meal_search_keywords(parsed_intent: ParsedIntent) -> list[str]:
    non_meal_tokens = ["咖啡", "下午茶", "甜品", "奶茶"]
    explicit_keywords = getattr(parsed_intent, "meal_search_keywords", [])
    meal_prefs = [
        keyword
        for keyword in parsed_intent.food_pref_keywords
        if not any(token in keyword for token in non_meal_tokens)
    ]
    return _unique_keywords([*explicit_keywords, *[f"{keyword} 餐厅" for keyword in meal_prefs[:2]], "餐厅"], limit=3)


def _slot_meal_keywords(parsed_intent: ParsedIntent, slot: dict[str, Any]) -> list[str]:
    fixed_name = slot.get("fixed_poi_name")
    requested = [keyword for keyword in slot.get("requested_keywords", []) if keyword]
    if fixed_name:
        return _unique_keywords([str(fixed_name), *requested, *_meal_search_keywords(parsed_intent)], limit=3)
    expanded = []
    for keyword in requested:
        expanded.append(keyword)
        if not any(token in keyword for token in ["餐厅", "饭店", "麦当劳", "肯德基"]):
            expanded.append(f"{keyword} 餐厅")
    return _unique_keywords([*expanded, *_meal_search_keywords(parsed_intent)], limit=3)


def _budget_stats(items: list[MicroPOI], threshold: float) -> dict[str, int]:
    deduped = _dedupe_micro(items)
    filtered = _budget_filter(deduped, threshold)
    return {
        "raw": len(items),
        "deduped": len(deduped),
        "budget_pass": len(filtered),
        "budget_removed": len(deduped) - len(filtered),
    }


MICRO_BAD_TERMS = [
    "图文",
    "快印",
    "印刷",
    "标书",
    "锦旗",
    "广告",
    "招牌",
    "装订",
    "证件照",
    "照相馆",
    "咖啡",
    "coffee",
    "cafe",
    "蛋糕",
    "甜品",
    "茶歇",
    "奶茶",
    "小吃",
    "上海菜",
    "本帮菜",
    "菜馆",
    "酒家",
    "食府",
    "面馆",
    "面·",
    "面(",
    "饭·",
    "粉·",
    "粥·",
    "火锅",
    "火鍋",
    "酒店",
    "宾馆",
    "旅馆",
    "民宿",
    "大饭店",
    "hostel",
    "hotel",
    "inn",
    "motel",
    "售票处",
    "售票亭",
    "摄影器材",
    "相机",
    "龟苓膏",
    "铜锣烧",
    "冰淇淋",
    "烘焙",
    "糕点",
    "糖水",
    "凉茶",
    "炸鸡",
    "汉堡",
    "披萨",
    "馄饨",
    "饺子",
    "生煎",
    "串串",
    "麻辣烫",
    "面包",
    "寿司",
    "拉面",
    "烧烤",
    "卤味",
    "熟食",
    "零食",
    "糖果",
    "薯片",
    "饼干",
    "巧克力",
]
LIGHT_FOOD_MICRO_TERMS = ["蛋糕", "甜品", "茶歇", "奶茶", "小吃", "咖啡", "cafe", "coffee"]
MEAL_POSITIVE_TERMS = ["本帮", "上海菜", "中餐", "餐厅", "饭店", "酒家", "小馆", "菜馆", "食府", "馆", "面馆", "馄饨", "烤鸭"]
MEAL_LIGHT_TERMS = [
    "咖啡", "cafe", "coffee", "奶茶", "甜品", "蛋糕", "茶歇", "小吃", "面包", "炸鸡",
    # v20: English/international light food terms for Baker & Spice etc.
    "baker", "bakery", "bread", "dessert", "pastry", "spice",
    "patisserie", "gelato", "ice cream", "yogurt", "smoothie",
    "juice", "bubble tea", "donut", "muffin", "croissant",
    "bagel", "sandwich", "salad", "snack", "sweets",
]
MEAL_CHAIN_PENALTY_TERMS = ["老乡鸡", "肯德基", "麦当劳", "必胜客", "瑞幸", "星巴克", "CoCo", "库迪"]


def _is_bad_micro_name(name: str, allow_light_food: bool) -> bool:
    bad_terms = MICRO_BAD_TERMS
    if allow_light_food:
        bad_terms = [term for term in MICRO_BAD_TERMS if term not in LIGHT_FOOD_MICRO_TERMS]
    return any(term.lower() in name.lower() for term in bad_terms)


def _micro_intent_score(item: MicroPOI, parsed_intent: ParsedIntent) -> float:
    name = item.name.lower()
    prefix = (item.typecode or "")[:2]
    score = item.gaode_rating or 0
    if _has_shopping_intent(parsed_intent):
        if prefix == "06" or any(term.lower() in name for term in SHOPPING_INTENT_TERMS):
            score += 3
    if _has_eating_activity_intent(parsed_intent):
        if prefix == "05" or any(term.lower() in name for term in EATING_INTENT_TERMS):
            score += 3
    return score


def _estimated_walk_min(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float:
    return haversine_km(a, b) / 4.5 * 60


def _is_large_area(pois: list[dict], threshold_km: float = 10.0) -> bool:
    """判断POI集合是否分布在大范围（最大两两距离>threshold_km）"""
    if len(pois) < 2:
        return False
    max_d = 0.0
    locs = [p.get("location") for p in pois if p.get("location")]
    for i in range(len(locs)):
        for j in range(i + 1, len(locs)):
            d = haversine_km(locs[i], locs[j])
            if d > max_d:
                max_d = d
    return max_d > threshold_km


def _travel_time_min(a: dict | None, b: dict | None) -> float:
    """基于距离估算交通时间：短距步行，中距公交，长距驾车"""
    d = haversine_km(a, b)
    if d <= 0:
        return 0.0
    if d <= 1.5:
        return max(config.WALK_TIME_MIN_FLOOR, d / 4.5 * 60)
    if d <= 10.0:
        return d / 30.0 * 60  # 公交/混合
    return d / 45.0 * 60      # 驾车（含岛内公路）


async def _search_meals(
    parsed_intent: ParsedIntent,
    complete_plan: CompletePlan,
    meal_refs: dict[tuple[int, str], dict[str, Any]],
    diagnostics: list[dict[str, Any]] | None = None,
) -> list[MicroPOI]:
    await emit_status("正在搜索餐饮推荐...")
    tasks = []
    metadata = []
    for day in complete_plan.day_plans:
        # v6: 不再要求 day.anchors 非空；强餐饮意图可能没有锚点
        for slot in day.meal_slots:
            meal = slot.get("meal")
            reference = meal_refs.get((day.day_index, meal))
            if not reference:
                continue
            keywords = _slot_meal_keywords(parsed_intent, slot)
            for keyword in keywords:
                tasks.append(
                    gaode_around_search(
                        location=coord_to_param(reference.get("location")),
                        keywords=keyword,
                        radius=config.GAODE_RADIUS_MEAL,
                        types="050000",
                        show_fields=config.GAODE_SHOW_FIELDS,
                        offset=10,
                    )
                )
                metadata.append((day.day_index, meal, reference.get("name", "上一地点"), keyword, slot))
    if not tasks:
        return []
    groups = await asyncio.gather(*tasks)
    meals: list[MicroPOI] = []
    for (day_index, meal, parent, keyword, slot), group in zip(metadata, groups):
        parsed_count = 0
        for raw in group:
            item = _to_micro(raw, parent_anchor=parent, is_meal=True)
            if item:
                parsed_count += 1
                meals.append(item)
        if diagnostics is not None:
            diagnostics.append(
                {
                    "day": day_index,
                    "meal": meal,
                    "reference": parent,
                    "keyword": keyword,
                    "requested_keywords": slot.get("requested_keywords", []),
                    "fixed_poi_name": slot.get("fixed_poi_name"),
                    "budget_threshold": getattr(complete_plan, "budget_threshold", None),
                    "raw_count": len(group),
                    "parsed_count": parsed_count,
                    "search_radius_m": config.GAODE_RADIUS_MEAL,
                }
            )
    return meals


async def _walking_distance_km(reference: dict[str, Any], item: MicroPOI) -> float:
    origin = coord_to_param(reference.get("location"))
    destination = coord_to_param(item.location)
    if not origin or not destination:
        raise ZeroOutputError(f"餐饮距离校验缺少坐标：{reference.get('name')} -> {item.name}")
    route = await gaode_walking_route(origin, destination, require_polyline=False)
    return route.get("distance_km", 0)


# v3.1 F1：餐饮跨江过滤参数（上海特化：黄浦江两岸经度差>0.007°即跨江）
MEAL_CROSS_RIVER_LNG_DIFF = 0.007
MEAL_STRAIGHT_MAX_KM = 1.5


def _filter_meal_candidates(
    candidates: list[MicroPOI],
    ref_lat: float,
    ref_lng: float,
    max_straight_km: float = MEAL_STRAIGHT_MAX_KM,
    anchor_centroid: dict[str, float] | None = None,
    anchor_spread_km: float | None = None,
    spread_multiplier: float = 2.0,
) -> list[MicroPOI]:
    """三层过滤：(1)直线距离>max_straight_km 排除；(2)经度差>0.007°视为跨江排除；
    (3)餐厅到当天POI质心距离 > anchor_spread_km×倍数 排除（防止跨锚点跳跃）。"""
    filtered: list[MicroPOI] = []
    for c in candidates:
        loc = c.location or {}
        c_lat = loc.get("lat")
        c_lng = loc.get("lng")
        if c_lat is None or c_lng is None:
            continue
        # 第一层：直线距离
        dist = haversine_km({"lat": c_lat, "lng": c_lng}, {"lat": ref_lat, "lng": ref_lng})
        if dist > max_straight_km:
            continue
        # 第二层：经度差跨江过滤
        if abs(c_lng - ref_lng) > MEAL_CROSS_RIVER_LNG_DIFF:
            continue
        # 第三层：锚点散布约束 — 餐厅不能跑到当天POI散布范围外
        # anchor_spread_km 由调用方传入，为当天已有POI到质心的最大距离
        if anchor_spread_km is not None and anchor_spread_km > 0:
            centroid_lat = anchor_centroid.get("lat")
            centroid_lng = anchor_centroid.get("lng")
            if centroid_lat is not None and centroid_lng is not None:
                dist_to_centroid = haversine_km(
                    {"lat": c_lat, "lng": c_lng},
                    {"lat": centroid_lat, "lng": centroid_lng},
                )
                # 餐厅到质心距离 ≤ 散布半径 × 倍数；搜不到时逐步放宽
                if dist_to_centroid > anchor_spread_km * spread_multiplier:
                    continue
        filtered.append(c)
    return filtered


def _meal_quality_score(item: MicroPOI) -> float:
    name = item.name
    name_lower = name.lower()
    category = getattr(item, "category", "") or ""
    category_lower = category.lower()
    typecode = getattr(item, "typecode", "") or ""
    score = 0.0
    if any(term in name for term in MEAL_POSITIVE_TERMS):
        score += 3.0
    if any(term in name for term in ["本帮", "上海菜", "酒家", "菜馆", "食府"]):
        score += 2.0
    if item.gaode_rating:
        score += min(item.gaode_rating, 5.0) / 5.0
    if item.avg_cost is not None and 20 <= item.avg_cost <= 180:
        score += 0.5
    # v20: Light food detection — check name (case-insensitive for English terms)
    # and typecode, not just Chinese name characters
    light_name_hit = any(
        term in name or term in name_lower for term in MEAL_LIGHT_TERMS
    )
    light_category_hit = any(
        term in category_lower for term in ["咖啡", "cafe", "coffee", "bakery", "dessert", "pastry", "snack"]
    )
    from .poi_typecodes import matches_typecode
    # v20: Only strict light food typecodes (0502xx-0510xx); 050100 only with name evidence
    light_typecode_hit = matches_typecode(typecode, ["0502", "0503", "0509", "0510"])
    if light_name_hit or light_category_hit or light_typecode_hit:
        score -= 1.5
    if any(term in name or term.lower() in name_lower for term in MEAL_CHAIN_PENALTY_TERMS):
        score -= 1.0
    return score


def _meal_constraint_score(item: MicroPOI, slot: dict[str, Any]) -> float:
    name = item.name.lower()
    fixed_name = str(slot.get("fixed_poi_name") or "").lower()
    score = 0.0
    if fixed_name:
        if fixed_name in name or name in fixed_name:
            score += 100.0
        else:
            fixed_compact = fixed_name.replace("（", "").replace("）", "").replace("(", "").replace(")", "")
            if fixed_compact and fixed_compact in name:
                score += 80.0
    for keyword in slot.get("requested_keywords", []) or []:
        clean = str(keyword).replace(" 餐厅", "").lower()
        if clean and clean in name:
            score += 8.0
    return score


async def _select_meals(
    meals: list[MicroPOI],
    complete_plan: CompletePlan,
    budget_threshold: float,
    meal_refs: dict[tuple[int, str], dict[str, Any]],
    diagnostics: list[dict[str, Any]] | None = None,
    day_anchor_locations: dict[int, list[dict[str, float]]] | None = None,
    parsed_intent: ParsedIntent | None = None,
) -> list[MicroPOI]:
    """v5.2: day_anchor_locations 为每天已有锚点POI的坐标列表，用于散布约束。"""
    filtered = _budget_filter(_dedupe_micro(meals), budget_threshold)
    # v9: 构建 anchor_name → bocha_keywords 查找表
    anchor_bocha_kw: dict[str, list[str]] = {}
    for day_plan in complete_plan.day_plans:
        for anchor in day_plan.anchors:
            kws = getattr(anchor, 'bocha_keywords', []) or []
            if kws:
                anchor_bocha_kw[anchor.name] = kws

    selected: list[MicroPOI] = []
    used_ids: set[str] = set()
    for day in complete_plan.day_plans:
        # v9: 收集当天所有锚点的 bocha 关键词，用于微POI加分
        day_bocha_kw: list[str] = []
        for anchor in day.anchors:
            day_bocha_kw.extend(getattr(anchor, 'bocha_keywords', []) or [])

        # v5.2: 计算当天POI质心和散布半径，用于锚点约束
        day_locs = (day_anchor_locations or {}).get(day.day_index, [])
        _centroid: dict[str, float] | None = None
        _spread_km: float | None = None
        if day_locs:
            c_lat = sum(l["lat"] for l in day_locs) / len(day_locs)
            c_lng = sum(l["lng"] for l in day_locs) / len(day_locs)
            _centroid = {"lat": c_lat, "lng": c_lng}
            _spread_km = max(haversine_km({"lat": l["lat"], "lng": l["lng"]}, _centroid) for l in day_locs) if len(day_locs) > 1 else 2.0

        for slot in day.meal_slots:
            meal = slot.get("meal")
            reference = meal_refs.get((day.day_index, meal))
            if reference is None:
                continue
            fixed_name = str(slot.get("fixed_poi_name") or "").lower()
            candidates = [
                item
                for item in filtered
                if item.gaode_poi_id not in used_ids
                and item.name != reference.get("name")
                and haversine_km(reference.get("location"), item.location) <= config.MEAL_MAX_ROUTE_KM
            ]
            # v3.1 F1：跨江过滤 + v5.2 锚点散布约束（仅在非fixed场景下生效）
            if not fixed_name:
                ref_loc = reference.get("location") or {}
                ref_lat = ref_loc.get("lat")
                ref_lng = ref_loc.get("lng")
                if ref_lat is not None and ref_lng is not None:
                    candidates = _filter_meal_candidates(
                        candidates, ref_lat, ref_lng,
                        anchor_centroid=_centroid,
                        anchor_spread_km=_spread_km,
                        spread_multiplier=2.0,
                    )
                    # v5.2: 如果2.0倍约束下无候选，逐步放宽到3.0
                    if not candidates and _spread_km is not None:
                        candidates = _filter_meal_candidates(
                            [
                                item for item in filtered
                                if item.gaode_poi_id not in used_ids
                                and item.name != reference.get("name")
                                and haversine_km(reference.get("location"), item.location) <= config.MEAL_MAX_ROUTE_KM
                            ],
                            ref_lat, ref_lng,
                            anchor_centroid=_centroid,
                            anchor_spread_km=_spread_km,
                            spread_multiplier=3.0,
                        )
            if fixed_name:
                fixed_candidates = [
                    item
                    for item in candidates
                    if fixed_name in item.name.lower() or item.name.lower() in fixed_name
                ]
                if fixed_candidates:
                    candidates = fixed_candidates
            # v9: 计算 bocha 关键词匹配加分（与用户口味偏好联动）
            def _bocha_boost(item: MicroPOI) -> int:
                if not day_bocha_kw:
                    return 0
                name_lower = item.name.lower()
                boost = sum(1 for kw in day_bocha_kw if kw in name_lower)
                # 若 bocha 关键词同时命中用户口味偏好 → 额外加成
                food_prefs = [fp.lower() for fp in (getattr(parsed_intent, 'food_pref_keywords', []) or []) if fp]
                if food_prefs:
                    bocha_text = ' '.join(day_bocha_kw).lower()
                    for fp in food_prefs:
                        if fp in name_lower and fp in bocha_text:
                            boost += 2
                return boost

            candidates.sort(
                key=lambda item: (
                    -_meal_constraint_score(item, slot),
                    -_meal_quality_score(item),
                    -_bocha_boost(item),  # v9: bocha关键词匹配加分
                    haversine_km(reference.get("location"), item.location),
                    -(item.gaode_rating or 0),
                    item.avg_cost if item.avg_cost is not None else 9999,
                )
            )
            chosen = None
            chosen_distance = None
            checked = 0
            for candidate in candidates[:8]:
                checked += 1
                distance = await _walking_distance_km(reference, candidate)
                if distance <= config.MEAL_MAX_ROUTE_KM + 0.05:
                    chosen = candidate
                    chosen_distance = distance
                    break
            if chosen:
                slot["poi_name"] = chosen.name
                slot["previous_poi"] = reference.get("name")
                slot["meal_walk_distance_km"] = round(chosen_distance or 0, 2)
                selected.append(chosen)
                used_ids.add(chosen.gaode_poi_id)
            if diagnostics is not None:
                diagnostics.append(
                    {
                        "day": day.day_index,
                        "meal": meal,
                        "reference": reference.get("name"),
                        "candidate_count": len(candidates),
                        "checked_count": checked,
                        "selected": chosen.name if chosen else None,
                        "walk_distance_km": round(chosen_distance, 2) if chosen_distance is not None else None,
                        "max_route_km": config.MEAL_MAX_ROUTE_KM,
                        "selected_avg_cost": chosen.avg_cost if chosen else None,
                        "requested_keywords": slot.get("requested_keywords", []),
                        "fixed_poi_name": slot.get("fixed_poi_name"),
                    }
                )
    return selected


def _nearest_order(start: dict[str, Any], candidates: list[MicroPOI], minutes_budget: int) -> list[MicroPOI]:
    remaining = list(candidates)
    current = start
    used = 0
    ordered: list[MicroPOI] = []
    while remaining:
        remaining.sort(key=lambda item: haversine_km(current, item.location))
        chosen = None
        for item in remaining:
            travel_min = max(3.0, _estimated_walk_min(current, item.location))
            projected = used + item.visit_duration_min + travel_min
            if projected <= minutes_budget:
                chosen = (item, projected)
                break
        if chosen is None:
            break
        item, projected = chosen
        ordered.append(item)
        current = item.location
        used = projected
        remaining.remove(item)
    return ordered


def _nearest_point_order(start: dict[str, Any], candidates: list[dict[str, Any]], minutes_budget: int) -> list[dict[str, Any]]:
    remaining = list(candidates)
    current = start
    used = 0.0
    ordered: list[dict[str, Any]] = []
    while remaining:
        remaining.sort(key=lambda item: haversine_km(current, item.get("location")))
        chosen = None
        for item in remaining:
            travel_min = max(3.0, _estimated_walk_min(current, item.get("location")))
            projected = used + item.get("visit_duration_min", 0) + travel_min
            if projected <= minutes_budget or not ordered:
                chosen = (item, projected)
                break
        if chosen is None:
            break
        item, projected = chosen
        ordered.append(item)
        current = item.get("location")
        used = projected
        remaining.remove(item)
    return ordered


def _slot_visit_order(anchor, previous: dict[str, Any], micro_items: list[MicroPOI], minutes_budget: int) -> list[dict[str, Any]]:
    anchor_entry = {
        "name": anchor.name,
        "location": anchor.location,
        "kind": "anchor",
        "visit_duration_min": 0,
        "gaode_poi_id": getattr(anchor, "gaode_poi_id", None) or "",
        "typecode": getattr(anchor, "typecode", None) or "",
        "address": getattr(anchor, "address", None) or "",
        "gaode_rating": getattr(anchor, "gaode_rating", None) or getattr(anchor, "rating", None),
        "photo_url": getattr(anchor, "photo_url", None) or "",
        "photo_source": getattr(anchor, "photo_source", None) or "",
        "parent_anchor": getattr(anchor, "parent_anchor", None) or "",
        "avg_cost": getattr(anchor, "avg_cost", None),
    }
    anchor_travel = max(3.0, _estimated_walk_min(previous.get("location"), anchor_entry.get("location")))
    micro_candidates = [
        {
            "name": item.name,
            "location": item.location,
            "kind": "micro",
            "visit_duration_min": item.visit_duration_min,
            "gaode_poi_id": getattr(item, "gaode_poi_id", None) or "",
            "typecode": getattr(item, "typecode", None) or "",
            "category": getattr(item, "category", None) or "",
            "address": getattr(item, "address", None) or "",
            "rating": getattr(item, "gaode_rating", None),
            "gaode_rating": getattr(item, "gaode_rating", None),
            "avg_cost": getattr(item, "avg_cost", None),
            "photo_url": getattr(item, "photo_url", None) or "",
            "photo_source": getattr(item, "photo_source", None) or "",
            "parent_anchor": getattr(item, "parent_anchor", None) or "",
        }
        for item in micro_items
    ]
    ordered = [anchor_entry]
    used = anchor_travel + anchor_entry["visit_duration_min"]
    current = anchor_entry["location"]
    remaining = list(micro_candidates)
    while remaining:
        remaining.sort(key=lambda item: haversine_km(current, item.get("location")))
        chosen = None
        for item in remaining:
            travel_min = max(3.0, _estimated_walk_min(current, item.get("location")))
            projected = used + item.get("visit_duration_min", 0) + travel_min
            if projected <= minutes_budget:
                chosen = (item, projected)
                break
        if chosen is None:
            break
        item, projected = chosen
        ordered.append(item)
        current = item.get("location")
        used = projected
        remaining.remove(item)
    return ordered


def _origin_label(parsed_intent: ParsedIntent) -> str:
    location = parsed_intent.original_location or {}
    return (
        parsed_intent.original_location_label
        or location.get("label")
        or location.get("name")
        or "出发点"
    )


def _origin_point(parsed_intent: ParsedIntent) -> dict[str, Any]:
    return {"name": _origin_label(parsed_intent), "location": parsed_intent.original_location or {}}


def _fallback_meal_reference(day_plan, parsed_intent: ParsedIntent) -> dict[str, Any]:
    """混合任务餐饮参考点：优先使用当天最后一个活动anchor，而不是出发点"""
    anchors = getattr(day_plan, "anchors", []) or []
    if anchors:
        anchor = anchors[-1]
        loc = getattr(anchor, "location", None) or {}
        if loc and loc.get("lat") is not None and loc.get("lng") is not None:
            return {"location": loc, "name": getattr(anchor, "name", "") or "活动区域"}

    origin_loc = parsed_intent.original_location or {}
    return {"location": origin_loc, "name": "出发点"}


def _day_activity_minutes(parsed_intent: ParsedIntent, day_plan, day_count: int) -> int:
    """估算单日活动可用时长（分钟），用于微观点时间预算分配。"""
    base = {
        "a quarter day": 150,
        "a half day": 240,
        "a full day": 420,
        "a day and a half": 630,
        "two days": 840,
        "two and a half days": 1050,
        "three days": 1260,
    }.get(parsed_intent.duration, 420)
    per_day = max(120, base // max(day_count, 1))
    if parsed_intent.evening_requested:
        per_day += 120
    # 出发晚的调整：14点后出发扣掉上午
    if parsed_intent.start_time and day_plan.day_index == 1:
        h = parsed_intent.start_time.hour + parsed_intent.start_time.minute / 60.0
        if h >= 14:
            per_day -= 180
        elif h >= 13:
            per_day -= 120
        elif h >= 17:
            per_day = min(per_day, 240)
    return max(per_day, 60)




def _compress_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for point in points:
        if result and result[-1]["day"] == point["day"] and result[-1]["name"] == point["name"]:
            continue
        result.append(point)
    return result


# ───────────────────────────────────────────────
# v3.1 F4：Chaikin平滑 + Douglas-Peucker简化
# ───────────────────────────────────────────────

def _point_to_line_dist(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.sqrt((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2)


def _simplify_polyline(points: list[list[float]], epsilon: float = 0.00005) -> list[list[float]]:
    """Douglas-Peucker简化polyline，epsilon≈5m，减少驾车导航返回的冗余坐标点。"""
    if len(points) <= 2:
        return points
    dmax = 0.0
    index = 0
    start, end = points[0], points[-1]
    for i in range(1, len(points) - 1):
        d = _point_to_line_dist(points[i][0], points[i][1], start[0], start[1], end[0], end[1])
        if d > dmax:
            index, dmax = i, d
    if dmax > epsilon:
        left = _simplify_polyline(points[: index + 1], epsilon)
        right = _simplify_polyline(points[index:], epsilon)
        return left[:-1] + right
    return [start, end]


def _polyline_distance_km(polyline: list[list[float]]) -> float:
    """v4: 计算 polyline 总长（km），格式 [[lat,lng],...]."""
    if not polyline or len(polyline) < 2:
        return 0.0
    total = 0.0
    for i in range(len(polyline) - 1):
        total += haversine_km(
            {"lat": polyline[i][0], "lng": polyline[i][1]},
            {"lat": polyline[i + 1][0], "lng": polyline[i + 1][1]},
        )
    return total


def _max_adjacent_gap_km(polyline: list[list[float]]) -> float:
    """v8: 计算 polyline 中相邻点之间的最大间距（km）"""
    if not polyline or len(polyline) < 2:
        return 0.0
    max_gap = 0.0
    for i in range(1, len(polyline)):
        max_gap = max(max_gap, haversine_km(
            {"lat": polyline[i - 1][0], "lng": polyline[i - 1][1]},
            {"lat": polyline[i][0], "lng": polyline[i][1]},
        ))
    return max_gap


INVALID_GEOMETRY_SOURCES = {
    "fallback_straight", "route_api_failed", "invalid_geometry",
    "discontinuous_polyline", "sparse_polyline",
}


def _is_drawable_route_polyline(
    polyline: list[list[float]],
    straight_km: float,
    polyline_source: str = "",
    transport: str = "",
    api_distance_km: float = 0.0,
) -> bool:
    """v8: 校验 polyline 是否适合在地图上绘制为真实路线。

    新增规则：
    - 已知不可绘制来源一律拒绝
    - 公交/自驾允许稍大间隔，但间断不能超过合理上限
    - api_distance_km 与 path_km 差距过大也拒绝
    """
    if not polyline or len(polyline) < 2:
        return False
    if polyline_source in INVALID_GEOMETRY_SOURCES:
        return False
    if straight_km >= 0.3 and len(polyline) <= 3:
        return False

    path_km = _polyline_distance_km(polyline)
    if api_distance_km >= 0.3 and path_km < api_distance_km * 0.55:
        return False
    if len(polyline) <= 3 and straight_km > 0.1 and path_km > 0 and straight_km > 0 and (path_km / straight_km) < 0.3:
        return False

    # v8.1: 近距离步行/骑行段若 API 路线远大于直线距离，通常是 waypoint 落入不可步行区域或导航绕桥
    if straight_km > 0:
        detour_ratio = api_distance_km / straight_km if api_distance_km > 0 else path_km / straight_km
        is_walk_like = transport in ("步行", "骑行", "")
        if is_walk_like and straight_km < 1.2 and api_distance_km > max(1.5, straight_km * 4.0):
            print(
                f"[RouteDebug] invalid detour: transport={transport} "
                f"straight={straight_km:.3f}km api_distance={api_distance_km:.3f}km "
                f"path={path_km:.3f}km ratio={detour_ratio:.1f} src={polyline_source}"
            )
            return False

    max_gap = _max_adjacent_gap_km(polyline)
    transit_or_drive = transport in ("地铁/公交", "公交", "自驾")
    gap_limit = max(0.8, straight_km * 0.55) if transit_or_drive else max(0.35, straight_km * 0.45)
    if straight_km < 5 and max_gap > gap_limit:
        print(f"[RouteDebug] invalid geometry: transport={transport} straight={straight_km:.3f}km "
              f"api_distance={api_distance_km:.3f}km path={path_km:.3f}km max_gap={max_gap:.3f}km "
              f"gap_limit={gap_limit:.3f}km points={len(polyline)} src={polyline_source}")
        return False
    return True


async def _route_between(parsed_intent: ParsedIntent, transport_hint: str, a: dict[str, Any], b: dict[str, Any]) -> dict:
    origin = coord_to_param(a.get("location"))
    destination = coord_to_param(b.get("location"))
    if not origin or not destination:
        raise ZeroOutputError(f"路线规划缺少坐标：{a.get('name')} -> {b.get('name')}")
    involves_meal = a.get("kind") == "meal" or b.get("kind") == "meal"
    straight_km = haversine_km(a.get("location"), b.get("location"))

    # v6: detect planned mode — stricter fallback rules
    is_planned = getattr(parsed_intent, "plan_mode", "") == "planned"

    # 近距离兜底：直距 < 50m 不调 API，直接用两点 stub
    if straight_km < 0.05:
        a_loc = a.get("location", {})
        b_loc = b.get("location", {})
        result = {
            "transport": "步行",
            "duration_min": max(1.0, straight_km / 4.5 * 60),
            "distance_km": max(0.01, straight_km),
            "polyline": [
                [a_loc["lat"], a_loc["lng"]],
                [b_loc["lat"], b_loc["lng"]],
            ],
        }
        if is_planned:
            result["degraded"] = False
            result["polyline_source"] = "ultra_short_stub"
            print(f"[RouteDebug] planned ultra-short stub: {a.get('name')} -> {b.get('name')} ({straight_km*1000:.0f}m)")
        return result

    # v5.2：同sub-anchor内直接用步行导航API，不再使用backbone子路径
    # v5.2: 沿江锚点注入江边waypoint，强制步行导航沿江走
    scene_kinds = {"anchor_internal"}
    same_sub_anchor = (
        a.get("sub_anchor_name") is not None
        and a.get("sub_anchor_name") == b.get("sub_anchor_name")
    )
    # 检测是否为沿江锚点
    sub_anchor_name = a.get("sub_anchor_name") or ""
    parent_name = a.get("parent_name") or sub_anchor_name
    is_waterfront = _is_waterfront_anchor(parent_name) or _is_waterfront_anchor(sub_anchor_name)

    # 同sub-anchor内的游览段：步行导航获取真实路线
    if (
        not involves_meal
        and same_sub_anchor
        and a.get("kind") in scene_kinds
        and b.get("kind") in scene_kinds
        and straight_km >= 0.05
    ):
        # v5.2: 沿江锚点注入江边waypoint
        if is_waterfront and straight_km >= 0.3:
            a_loc = a.get("location", {})
            b_loc = b.get("location", {})
            mid_lat = (a_loc.get("lat", 0) + b_loc.get("lat", 0)) / 2
            mid_lng = (a_loc.get("lng", 0) + b_loc.get("lng", 0)) / 2
            # 向江方向偏移（上海外滩：向东=lng增大方向）
            wp_lng = mid_lng + config.WATERFRONT_WAYPOINT_LNG_SHIFT
            waypoint = f"{wp_lng:.6f},{mid_lat:.6f}"
            result = await gaode_walking_route_waypoints(origin, destination, [waypoint])
            if result and result.get("polyline") and len(result["polyline"]) >= 2:
                result["polyline_source"] = "waterfront_waypoint"
                wp_dist = float(result.get("distance_km", 0) or 0)
                if _is_drawable_route_polyline(
                    result.get("polyline") or [],
                    straight_km,
                    result.get("polyline_source", ""),
                    result.get("transport", "步行"),
                    wp_dist,
                ):
                    return {
                        "transport": "步行",
                        "duration_min": round(result.get("duration_min", straight_km * 60 / 4.5), 1),
                        "distance_km": round(wp_dist, 3),
                        "polyline": result["polyline"],
                        "polyline_source": "waterfront_waypoint",
                    }
                print(
                    f"[RouteDebug] waterfront waypoint route rejected: "
                    f"{a.get('name')} -> {b.get('name')} "
                    f"straight={straight_km:.3f}km route={wp_dist:.3f}km "
                    f"waypoint={waypoint}"
                )
            # waypoint导航失败或路线被拒绝，降级为普通步行导航
        result = await gaode_walking_route(origin, destination)
        if result and result.get("polyline") and len(result["polyline"]) >= 2:
            result.setdefault("polyline_source", "same_sub_anchor_walk")
            walk_dist = float(result.get("distance_km", 0) or 0)
            if _is_drawable_route_polyline(
                result.get("polyline") or [],
                straight_km,
                result.get("polyline_source", ""),
                result.get("transport", "步行"),
                walk_dist,
            ):
                return {
                    "transport": "步行",
                    "duration_min": round(result.get("duration_min", straight_km * 60 / 4.5), 1),
                    "distance_km": round(walk_dist, 3),
                    "polyline": result["polyline"],
                    "polyline_source": result.get("polyline_source", "same_sub_anchor_walk"),
                }
            print(
                f"[RouteDebug] same-sub-anchor walking route rejected: "
                f"{a.get('name')} -> {b.get('name')} "
                f"straight={straight_km:.3f}km route={walk_dist:.3f}km"
            )
        # API失败或路线被拒绝，降级到后续通用路线逻辑

    async def non_walking_route() -> dict:
        if transport_hint == "自驾":
            return await gaode_driving_route(origin, destination)
        dep_time = getattr(parsed_intent, "start_time", None)
        try:
            return await gaode_transit_route(origin, destination, departure_time=dep_time)
        except Exception:
            try:
                return await gaode_transit_route(origin, destination, strategy=2, departure_time=dep_time)
            except Exception:
                return await gaode_driving_route(origin, destination)

    async def driving_first_route() -> dict:
        """驾车优先，三级降级：驾车 → 步行"""
        try:
            return await gaode_driving_route(origin, destination)
        except Exception:
            return await gaode_walking_route(origin, destination)

    async def bicycling_first_route() -> dict:
        """v4 M8: 骑行优先，失败降级步行。"""
        try:
            return await gaode_bicycling_route(origin, destination)
        except Exception:
            return await gaode_walking_route(origin, destination)

    if transport_hint == "步行" or _is_late_nearby_walk_request(parsed_intent):
        result = await gaode_walking_route(origin, destination)
    elif transport_hint == "骑行" and not involves_meal and straight_km >= 0.05:
        # v18: 显式骑行模式 → 优先骑行，失败降级步行 → driving
        try:
            result = await gaode_bicycling_route(origin, destination)
        except Exception:
            result = await gaode_walking_route(origin, destination)
    elif not involves_meal and a.get("kind") in scene_kinds and b.get("kind") in scene_kinds and not same_sub_anchor:
        # v4 M8: 跨 sub-anchor 游览段，按距离选交通方式
        #   >= INTER_SEG_DRIVE_KM(2km) → 驾车
        #   [INTER_SEG_BIKE_KM(1km), INTER_SEG_DRIVE_KM) → 骑行
        #   < 1km → 步行
        if straight_km >= config.INTER_SEG_DRIVE_KM:
            result = await driving_first_route()
        elif straight_km >= config.INTER_SEG_BIKE_KM:
            result = await bicycling_first_route()
        else:
            result = await gaode_walking_route(origin, destination)
    elif not involves_meal and a.get("kind") in scene_kinds and b.get("kind") in scene_kinds and straight_km >= 0.5:
        # v5.2：同sub-anchor近距离游览段仍优先步行
        result = await gaode_walking_route(origin, destination)
    elif straight_km < 1.0 or (involves_meal and straight_km <= config.MEAL_MAX_ROUTE_KM):
        walking = await gaode_walking_route(origin, destination)
        if walking.get("distance_km", 0) <= config.MEAL_MAX_ROUTE_KM + 0.05 and walking.get("duration_min", 0) <= 25:
            result = walking
        elif involves_meal and a.get("kind") == "anchor" and b.get("kind") == "meal":
            result = walking
        else:
            result = await non_walking_route()
    else:
        result = await non_walking_route()

    # v3.1 F4：长途段对polyline做Douglas-Peucker简化，去除冗余转折点
    # transit/驾车路线常有数百个冗余点，用较大epsilon；步行路线保留更多细节
    if result and result.get("polyline") and len(result["polyline"]) > 8:
        is_long_route = result.get("transport", "") in ("地铁/公交", "驾车")
        eps = 0.0003 if is_long_route else 0.00005  # transit/驾车≈30m，步行≈5m
        result["polyline"] = _simplify_polyline(result["polyline"], epsilon=eps)

    # v7: 真实路线可用性校验 — 不可绘制的路线不返回 stub，标记 route_api_failed
    polyline_src = result.get("polyline_source", "") if result else ""
    result_poly = result.get("polyline", []) if result else []
    if result and not _is_drawable_route_polyline(
        result_poly, straight_km, polyline_src,
        result.get("transport", ""),
        float(result.get("distance_km", 0) or 0),
    ):
        # 真实 API 返回了但 polyline 不可绘制 → 尝试备用真实路线
        fallback_result = None
        transport_mode = result.get("transport", "")
        if transport_mode in ("地铁/公交", "公交"):
            try:
                fallback_result = await gaode_driving_route(origin, destination)
            except Exception:
                pass
        elif transport_mode == "步行":
            try:
                fallback_result = await gaode_bicycling_route(origin, destination)
            except Exception:
                try:
                    fallback_result = await gaode_driving_route(origin, destination)
                except Exception:
                    pass
        if fallback_result and fallback_result.get("polyline") and len(fallback_result.get("polyline", [])) >= 2:
            fb_poly = fallback_result.get("polyline", [])
            fb_src = fallback_result.get("polyline_source", "")
            fb_transport = fallback_result.get("transport", result.get("transport", "步行") if result else "步行")
            fb_dist = float(fallback_result.get("distance_km", 0) or 0)
            if _is_drawable_route_polyline(fb_poly, straight_km, fb_src, fb_transport, fb_dist):
                result = fallback_result
                result_poly = fb_poly
                polyline_src = fb_src
            else:
                result_poly = []
                polyline_src = "invalid_geometry"
        else:
            result_poly = []
            polyline_src = "route_api_failed"

    if not result or len(result_poly) < 2:
        print(f"[RouteDebug] route api failed, skip drawable polyline: {a.get('name')} -> {b.get('name')}")
        return {
            "transport": result.get("transport", "步行") if result else "步行",
            "duration_min": max(1.0, result.get("duration_min", straight_km / 4.5 * 60) if result else straight_km / 4.5 * 60),
            "distance_km": max(0.01, result.get("distance_km", straight_km) if result else straight_km),
            "polyline": [],
            "degraded": True,
            "polyline_source": "route_api_failed",
            "route_error": "real_route_unavailable",
        }
    return result


def _vector_angle(a: dict[str, Any], b: dict[str, Any], c: dict[str, Any]) -> float:
    """计算三点A→B→C的转向角（0-180°），即AB与BC之间的夹角，0°表示直行"""
    a_loc = a.get("location", {})
    b_loc = b.get("location", {})
    c_loc = c.get("location", {})
    alng, alat = a_loc.get("lng", 0), a_loc.get("lat", 0)
    blng, blat = b_loc.get("lng", 0), b_loc.get("lat", 0)
    clng, clat = c_loc.get("lng", 0), c_loc.get("lat", 0)
    ab = (blng - alng, blat - alat)  # 入方向 A→B
    bc = (clng - blng, clat - blat)  # 出方向 B→C
    dot = ab[0] * bc[0] + ab[1] * bc[1]
    mag_ab = math.sqrt(ab[0]**2 + ab[1]**2)
    mag_bc = math.sqrt(bc[0]**2 + bc[1]**2)
    if mag_ab == 0 or mag_bc == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag_ab * mag_bc)))
    return float(math.degrees(math.acos(cos_angle)))


_WAYPOINT_ANGLE_THRESHOLD = 30.0  # 转向角≥30°保留为waypoint


def _compute_waypoints(stretch: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    """从排序好的POI段中筛选导航waypoint，合并直线段途经点

    v5.2 改进：
    - 沿途经过型POI (is_passthrough) 不作为waypoint，只做passing标注
    - 距离上一个waypoint过近的POI (<150m) 也降级为passing，
      避免步行API导航到近距离POI坐标时产生"拐进去再出来"的折返线

    Returns:
        waypoints: 需传入高德direction API的导航点
        passing_map: (waypoint_from, waypoint_to) → 该段中间的途经点列表
    """
    if len(stretch) <= 2:
        return list(stretch), {}

    _CLOSE_WP_DEMOTE_M = 150.0  # 距上一个waypoint <150m 的POI降级为passing

    waypoints: list[dict[str, Any]] = [stretch[0]]  # 起点始终保留
    passing_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    current_passing: list[dict[str, Any]] = []

    for i in range(1, len(stretch) - 1):
        angle = _vector_angle(stretch[i - 1], stretch[i], stretch[i + 1])
        is_passthrough = stretch[i].get("is_passthrough", False)
        # v5.2: 距离上一个waypoint过近的POI降级为passing
        prev_wp_loc = waypoints[-1].get("location", {})
        cur_loc = stretch[i].get("location", {})
        is_close = False
        if prev_wp_loc and cur_loc and "lat" in prev_wp_loc and "lat" in cur_loc:
            dlat = (cur_loc["lat"] - prev_wp_loc["lat"]) * 111000
            dlng = (cur_loc["lng"] - prev_wp_loc["lng"]) * 111000 * math.cos(math.radians(cur_loc["lat"]))
            dist_m = math.sqrt(dlat ** 2 + dlng ** 2)
            is_close = dist_m < _CLOSE_WP_DEMOTE_M
        # v5.2: passthrough或过近的POI不作为独立导航终点
        if angle >= _WAYPOINT_ANGLE_THRESHOLD and not is_passthrough and not is_close:
            if current_passing:
                passing_map[(waypoints[-1]["name"], stretch[i]["name"])] = current_passing
                current_passing = []
            waypoints.append(stretch[i])
        else:
            current_passing.append(stretch[i])

    # 终点始终保留
    waypoints.append(stretch[-1])
    if current_passing:
        passing_map[(waypoints[-2]["name"], waypoints[-1]["name"])] = current_passing

    return waypoints, passing_map


def _nearest_walk_min_to_polyline(poi_loc: dict[str, Any], polyline: list[list[float]]) -> float:
    """计算POI到路线polyline最近点的步行时间（分钟），步行速度80m/min"""
    if not polyline or not poi_loc:
        return 0.0
    poi_lat = poi_loc.get("lat", 0)
    poi_lng = poi_loc.get("lng", 0)
    min_dist_m = float("inf")
    for pt in polyline:
        if len(pt) >= 2:
            # polyline: [[lat, lng], ...]
            dist_m = haversine_km({"lat": poi_lat, "lng": poi_lng}, {"lat": pt[0], "lng": pt[1]}) * 1000
            if dist_m < min_dist_m:
                min_dist_m = dist_m
    return max(1.0, round(min_dist_m / 80.0))


def _cluster_same_building_pois(pois: list[dict[str, Any]], radius_m: float = 50.0) -> dict[str, str]:
    """v5.2: 将距离<radius_m的室内型POI聚为同建筑组。
    判定依据：(1) 高德indoor_map=1；(2) 3+个同typecode前缀POI在radius内。
    返回 name → group_id 映射，同组内POI共享group_id。"""
    _INDOOR_TYPE_PREFIXES = {"05", "06", "08", "09", "10"}  # 餐饮/购物/娱乐/医疗/教育培训
    group_map: dict[str, str] = {}
    group_counter = 0
    used: set[int] = set()

    for i, pi in enumerate(pois):
        if i in used:
            continue
        loc_i = pi.get("location", {})
        if not loc_i or "lat" not in loc_i:
            continue
        tc = pi.get("typecode", "")
        # 只对室内型POI做聚类
        if tc[:2] not in _INDOOR_TYPE_PREFIXES and pi.get("indoor_map") != "1":
            continue

        # 收集radius内的邻居
        neighbors: list[int] = [i]
        for j, pj in enumerate(pois):
            if j == i or j in used:
                continue
            loc_j = pj.get("location", {})
            if not loc_j or "lat" not in loc_j:
                continue
            dlat = (loc_j["lat"] - loc_i["lat"]) * 111000
            dlng = (loc_j["lng"] - loc_i["lng"]) * 111000 * math.cos(math.radians(loc_i["lat"]))
            if math.sqrt(dlat ** 2 + dlng ** 2) <= radius_m:
                tc_j = pj.get("typecode", "")
                if tc_j[:2] in _INDOOR_TYPE_PREFIXES or pj.get("indoor_map") == "1":
                    neighbors.append(j)

        # 至少2个POI才成组（自身+1个邻居）
        if len(neighbors) >= 2:
            gid = f"building_{group_counter}"
            group_counter += 1
            for idx in neighbors:
                group_map[pois[idx]["name"]] = gid
                used.add(idx)

    return group_map


def _point_coord(point: dict[str, Any]) -> list[float] | None:
    """提取点的 [lat, lng] 坐标"""
    loc = point.get("location") or {}
    if "lat" in loc and "lng" in loc:
        return [loc["lat"], loc["lng"]]
    return None


def _make_stub_polyline(a: dict[str, Any], b: dict[str, Any]) -> list[list[float]]:
    """v6: 用两点坐标构造 stub polyline [lat, lng] 格式，作为路线 API 无结果的降级兜底"""
    a_coord = _point_coord(a)
    b_coord = _point_coord(b)
    if a_coord and b_coord:
        return [a_coord, b_coord]
    return []


def _estimate_taxi_fare(distance_km: float) -> int:
    """v18: 粗略估算出租车/网约车费用。起步价14元（3km），超出后2.7元/km。"""
    if distance_km <= 3:
        return 14
    return round(14 + (distance_km - 3) * 2.7)


async def _build_origin_transport_options(parsed_intent: ParsedIntent, origin: str, destination: str) -> list[dict[str, Any]]:
    """v18: 起点到第一个POI的多交通方案。只在exploratory模式下调用。"""
    from .api_client import gaode_transit_route, gaode_driving_route
    options: list[dict[str, Any]] = []
    try:
        transit = await gaode_transit_route(origin, destination, departure_time=getattr(parsed_intent, "start_time", None))
        if transit and transit.get("distance_km"):
            options.append({
                "mode": "transit",
                "label": "公共交通",
                "transport": transit.get("transport", "地铁/公交"),
                "distance_km": round(float(transit.get("distance_km", 0)), 2),
                "duration_min": round(float(transit.get("duration_min", 0)), 1),
            })
    except Exception:
        pass
    try:
        driving = await gaode_driving_route(origin, destination)
        if driving and driving.get("distance_km"):
            d_km = float(driving.get("distance_km", 0))
            options.append({
                "mode": "driving",
                "label": "驾车",
                "transport": "自驾",
                "distance_km": round(d_km, 2),
                "duration_min": round(float(driving.get("duration_min", 0)), 1),
                "estimated_fare_yuan": _estimate_taxi_fare(d_km),
            })
    except Exception:
        pass
    return options


async def _build_segments(parsed_intent: ParsedIntent, transport_hint: str, points: list[dict[str, Any]]) -> tuple[list[RouteSegment], dict[str, dict[str, Any]]]:
    # 过滤掉非路线点（hint/free_explore 不参与路线连线）
    routable = [p for p in points if p.get("kind") not in ("hint", "free_explore")]

    # ── v5.2: 同建筑POI聚类 — 同组内不画步行路线，只标注 ──
    _building_groups = _cluster_same_building_pois(routable)
    # 反向映射：group_id → [names]
    _group_members: dict[str, list[str]] = {}
    for name, gid in _building_groups.items():
        _group_members.setdefault(gid, []).append(name)
    # 同组内只保留第一个POI作为路线途经点，其余标为passing
    _building_route_rep: dict[str, str] = {}  # group_id → representative name
    for gid, members in _group_members.items():
        _building_route_rep[gid] = members[0]
    # 同组内非代表POI标记为"同建筑不连线"
    _building_skip: set[str] = set()
    for gid, members in _group_members.items():
        for m in members[1:]:
            _building_skip.add(m)
    # 从routable中移除同建筑非代表POI（它们仍会在points中作为marker出现）
    routable = [p for p in routable if p["name"] not in _building_skip]

    # ── Waypoint优化：识别锚点内/微观点连续段，精简导航点 ──
    STRETCH_KINDS = {"anchor_internal", "micro"}
    optimized: list[dict[str, Any]] = []
    stretch_segments: dict[tuple[str, str], list[dict[str, Any]]] = {}  # (wp_a, wp_b) → passing POIs
    waypoint_annotations: dict[str, dict[str, Any]] = {}  # name → {is_waypoint, walk_from_route_min}

    _is_theme_route = bool(
        getattr(parsed_intent, "theme_profile", None)
        or getattr(parsed_intent, "theme_label", None)
        or getattr(parsed_intent, "micro_poi_keywords", None)
        or getattr(parsed_intent, "theme_keywords", None)
    )
    _theme_min_waypoints_per_stretch = 3 if _is_theme_route else 0

    def _promote_theme_waypoints(
        stretch: list[dict[str, Any]],
        wps: list[dict[str, Any]],
        passing: dict[tuple[str, str], list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
        if not _is_theme_route or _theme_min_waypoints_per_stretch <= 0:
            return wps, passing

        target = min(len(stretch), max(len(wps), _theme_min_waypoints_per_stretch))
        if len(wps) >= target:
            return wps, passing

        wp_names = {str(p.get("name") or "") for p in wps if p.get("name")}
        passing_names = {
            str(p.get("name") or "")
            for plist in passing.values()
            for p in plist
            if p.get("name")
        }

        promoted: list[dict[str, Any]] = []
        for p in stretch:
            name = str(p.get("name") or "")
            if not name or name in wp_names:
                continue
            if name not in passing_names:
                continue
            promoted.append(p)
            wp_names.add(name)
            if len(wps) + len(promoted) >= target:
                break

        if not promoted:
            return wps, passing

        promoted_names = {str(p.get("name") or "") for p in promoted}
        cleaned_passing: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for key, plist in passing.items():
            rest = [p for p in plist if str(p.get("name") or "") not in promoted_names]
            if rest:
                cleaned_passing[key] = rest

        index_by_name = {str(p.get("name") or ""): idx for idx, p in enumerate(stretch)}
        merged_wps = sorted(
            [*wps, *promoted],
            key=lambda p: index_by_name.get(str(p.get("name") or ""), 10_000),
        )

        print(
            "[DEBUG step3] promoted theme passing POIs to waypoints: "
            f"{[p.get('name') for p in promoted]}"
        )
        return merged_wps, cleaned_passing

    i = 0
    while i < len(routable):
        kind = routable[i].get("kind", "")
        point_day = routable[i].get("day", 0)
        if kind in STRETCH_KINDS:
            j = i
            while j < len(routable) and routable[j].get("kind", "") in STRETCH_KINDS:
                j += 1
            stretch = routable[i:j]

            if len(stretch) > 2:
                wps, passing = _compute_waypoints(stretch)
                wps, passing = _promote_theme_waypoints(stretch, wps, passing)

                optimized.extend(wps)
                for wp in wps:
                    waypoint_annotations[wp["name"]] = {"is_waypoint": True, "walk_from_route_min": 0, "day": wp.get("day", 0)}
                for (wp_a, wp_b), plist in passing.items():
                    stretch_segments[(wp_a, wp_b)] = plist
                    for p in plist:
                        # v16: 带 rebalance_reason 的点保持主展示
                        marked = bool(p.get("rebalance_reason") or p.get("theme_anchor_fallback"))
                        waypoint_annotations[p["name"]] = {
                            "is_waypoint": bool(marked),
                            "walk_from_route_min": 0,
                            "day": p.get("day", 0),
                        }
            else:
                optimized.extend(stretch)
                for p in stretch:
                    waypoint_annotations[p["name"]] = {"is_waypoint": True, "walk_from_route_min": 0, "day": p.get("day", 0)}
            i = j
        else:
            optimized.append(routable[i])
            waypoint_annotations[routable[i]["name"]] = {"is_waypoint": True, "walk_from_route_min": 0, "day": point_day}
            i += 1

    # 生成精简后的路线对
    pairs = [(optimized[k], optimized[k + 1]) for k in range(len(optimized) - 1) if optimized[k]["day"] == optimized[k + 1]["day"]]
    routes = await asyncio.gather(*[_route_between(parsed_intent, transport_hint, a, b) for a, b in pairs])

    # 计算途经点到所属路段polyline的步行时间
    for (a, b), route in zip(pairs, routes):
        polyline = route.get("polyline") or [] if route else []
        seg_key = (a["name"], b["name"])
        if seg_key in stretch_segments and polyline:
            for passing_poi in stretch_segments[seg_key]:
                walk_min = _nearest_walk_min_to_polyline(passing_poi.get("location", {}), polyline)
                if passing_poi["name"] in waypoint_annotations:
                    waypoint_annotations[passing_poi["name"]]["walk_from_route_min"] = int(walk_min)

    segments = []
    for (a, b), route in zip(pairs, routes):
        if route is None:
            # v7: route 为 None 时不构造虚假直线，保留路程信息但地图不画
            dist_km = haversine_km(a.get("location", {}), b.get("location", {}))
            print(f"[RouteDebug] route api failed, skip drawable polyline: {a['name']} -> {b['name']}")
            segments.append(RouteSegment(
                from_poi=a["name"], to_poi=b["name"],
                day_index=a["day"], transport="步行",
                duration_min=max(1, round(dist_km / 4.5 * 60)),
                distance_km=max(0.01, round(dist_km, 2)),
                polyline=[],
                degraded=True,
                polyline_source="route_api_failed",
                route_error="real_route_unavailable",
            ))
            continue
        polyline = route.get("polyline") or []
        is_degraded = bool(route.get("degraded", False))
        polyline_src = str(route.get("polyline_source", ""))
        route_err = str(route.get("route_error", ""))
        if len(polyline) < 2:
            # v7: 真实路线不足时不构造虚假 stub，保留行程信息但地图不画
            dist_km = haversine_km(a.get("location", {}), b.get("location", {}))
            print(f"[RouteDebug] route api failed, skip drawable polyline: {a['name']} -> {b['name']}")
            segments.append(RouteSegment(
                from_poi=a["name"], to_poi=b["name"],
                day_index=a["day"], transport=route.get("transport", "步行"),
                duration_min=max(1, round(route.get("duration_min", dist_km / 4.5 * 60))),
                distance_km=max(0.01, round(route.get("distance_km", dist_km), 2)),
                polyline=[],
                degraded=True,
                polyline_source=route_err and "route_api_failed" or polyline_src or "route_api_failed",
                route_error=route_err or "real_route_unavailable",
            ))
            continue
        # v18: 首段起点→第一个POI，exploratory模式下附加多交通方案
        transport_options: list[dict[str, Any]] = []
        is_planned = getattr(parsed_intent, "plan_mode", "") == "planned"
        is_origin_start = str(a.get("kind", "")).lower() in ("start", "origin")
        if is_origin_start and not is_planned:
            try:
                origin_str = f"{a['location']['lng']},{a['location']['lat']}"
                dest_str = f"{b['location']['lng']},{b['location']['lat']}"
                transport_options = await _build_origin_transport_options(parsed_intent, origin_str, dest_str)
            except Exception:
                pass

        segments.append(
            RouteSegment(
                from_poi=a["name"],
                to_poi=b["name"],
                day_index=a["day"],
                transport=route.get("transport", "地铁"),
                duration_min=route.get("duration_min", 0),
                distance_km=route.get("distance_km", 0),
                polyline=polyline,
                degraded=is_degraded,
                polyline_source=polyline_src,
                route_error=route.get("route_error", ""),
                transport_options=transport_options,
            )
        )
    return segments, waypoint_annotations


_TIME_PERIOD_COLORS = {
    "morning": {"primary": "#E67E22", "light": "#F5CBA7"},
    "lunch": {"primary": "#D35400", "light": "#FAD7A1"},
    "afternoon": {"primary": "#2980B9", "light": "#AED6F1"},
    "dinner": {"primary": "#C0392B", "light": "#F5B7B1"},
    "evening": {"primary": "#8E44AD", "light": "#D2B4DE"},
}
_START_COLOR = "#27AE60"
_MEAL_COLOR = "#E74C3C"
_WALK_WEIGHT = 4
_WALK_OPACITY = 0.85
_TRANSIT_WEIGHT = 3
_TRANSIT_OPACITY = 0.44  # v5.2 r3: 调淡到原来的80%
_ARROW_INTERVALS = (0.25, 0.5, 0.75)
_ARROW_RADIUS = 6


def _folium_icon_color(hex_color: str) -> str:
    _HEX_TO_FOLIUM = {
        "#E67E22": "orange",
        "#D35400": "darkorange",
        "#2980B9": "cadetblue",
        "#C0392B": "darkred",
        "#8E44AD": "darkpurple",
        "#27AE60": "green",
        "#E74C3C": "red",
    }
    return _HEX_TO_FOLIUM.get(hex_color, "blue")


def _lighten_color(hex_color: str, factor: float = 0.5) -> str:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def _bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlon = math.radians(lng2 - lng1)
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    y = math.sin(dlon) * math.cos(lat2_r)
    x = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _polyline_point_at(coords: list[list[float]], fraction: float) -> tuple[float, float, float]:
    n = len(coords) - 1
    if n < 1:
        return coords[0][0], coords[0][1], 0.0
    idx = int(fraction * n)
    if idx >= n:
        idx = n - 1
    ratio = fraction * n - idx
    lat = coords[idx][0] + (coords[idx + 1][0] - coords[idx][0]) * ratio
    lng = coords[idx][1] + (coords[idx + 1][1] - coords[idx][1]) * ratio
    bearing = _bearing_deg(coords[idx][0], coords[idx][1], coords[idx + 1][0], coords[idx + 1][1])
    return lat, lng, bearing


_TIME_WINDOW_LABELS = {
    "morning": "上午",
    "lunch": "午餐",
    "afternoon": "下午",
    "dinner": "晚餐",
    "evening": "晚间",
}


def _time_window_for_point(day_points: list[dict[str, Any]], point_idx: int, day_plan) -> str:
    """返回时间窗口标签: morning / lunch / afternoon / dinner / evening

    v4.1 fix: 当午餐未找到时，使用路线段位置来划分上午/下午（前50%=morning，后50%=afternoon）
    """
    meal_order: list[tuple[int, str]] = []
    for i, p in enumerate(day_points):
        if p.get("kind") == "meal":
            meal_order.append((i, p.get("name", "")))
    lunch_slots = [s for s in day_plan.meal_slots if s.get("meal") == "lunch"] if day_plan else []
    dinner_slots = [s for s in day_plan.meal_slots if s.get("meal") == "dinner"] if day_plan else []
    lunch_idx: int | None = None
    dinner_idx: int | None = None
    for i, name in meal_order:
        if lunch_slots and any(s.get("poi_name") == name for s in lunch_slots):
            lunch_idx = i
        if dinner_slots and any(s.get("poi_name") == name for s in dinner_slots):
            dinner_idx = i
    if lunch_idx is None and dinner_idx is None and len(meal_order) >= 1:
        lunch_idx = meal_order[0][0]
    if lunch_idx is not None and dinner_idx is None and len(meal_order) >= 2:
        for i, name in meal_order:
            if i > lunch_idx:
                dinner_idx = i
                break

    # v4.1: 如果没有午餐但有晚餐，使用位置来划分上午/下午
    # 对于full_day行程，前半段=上午，后半段=下午
    if lunch_idx is None and dinner_idx is not None:
        # 检查是否有full_day锚点
        has_full_day = False
        if day_plan:
            for anchor in day_plan.anchors:
                cap = anchor.final_time_budget or anchor.final_capacity or anchor.time_capacity or ""
                if "full_day" in str(cap):
                    has_full_day = True
                    break
        if has_full_day and dinner_idx > 2:
            # 使用中间点作为上午/下午分界
            midpoint = dinner_idx // 2
            if point_idx == dinner_idx:
                return "dinner"
            if point_idx > dinner_idx:
                return "evening"
            if point_idx > midpoint:
                return "afternoon"
            return "morning"

    if lunch_idx is not None and point_idx == lunch_idx:
        return "lunch"
    if dinner_idx is not None and point_idx == dinner_idx:
        return "dinner"
    if dinner_idx is not None and point_idx > dinner_idx:
        return "evening"
    if lunch_idx is not None and point_idx > lunch_idx:
        return "afternoon"
    return "morning"


def _is_transit(transport: str) -> bool:
    return transport not in ("步行", "骑行", "")


def _render_legend(fmap, day_index: int) -> None:
    legend_html = f"""<div style="
        position:fixed;bottom:40px;right:12px;z-index:9999;
        background:rgba(255,255,255,0.93);padding:10px 14px;border-radius:6px;
        box-shadow:0 1px 6px rgba(0,0,0,0.25);font-size:11px;
        font-family:'Microsoft YaHei','PingFang SC',sans-serif;line-height:1.9;max-width:175px;">
    <b style="font-size:13px;">图例 Day{day_index}</b><br>
    <span style="color:#E67E22;font-size:16px;">●</span> 上午<br>
    <span style="color:#D35400;font-size:16px;">●</span> 午餐<br>
    <span style="color:#2980B9;font-size:16px;">●</span> 下午<br>
    <span style="color:#C0392B;font-size:16px;">●</span> 晚餐<br>
    <span style="color:#8E44AD;font-size:16px;">●</span> 晚间<br>
    <span style="color:#27AE60;font-size:14px;">▶</span> 出发地<br>
    <span style="font-size:12px;">★</span> 主要景点 &nbsp;
    <span style="font-size:12px;">◉</span> 打卡点<br>
    <span style="font-size:12px;color:#3498DB;">●</span> 途经点（旁支）<br>
    <span style="border-bottom:3px dashed #666;">- - -</span> 公交/自驾<br>
    <span style="border-bottom:3px solid #666;">━━━</span> 步行<br>
    </div>"""
    fmap.get_root().html.add_child(folium.Element(legend_html))


def _render_single_day_map(
    points: list[dict[str, Any]],
    route_segments: list[RouteSegment],
    day_index: int,
    timestamp: str,
    complete_plan=None,
    parsed_intent=None,
) -> str:
    try:
        import folium  # type: ignore
    except ImportError as exc:
        raise DependencyMissingError("缺少 Python 依赖 folium，请先安装：pip install -r requirements.txt") from exc
    except Exception as exc:
        raise DependencyMissingError(
            f"地图渲染依赖加载失败，通常是 numpy/pandas/folium 版本不兼容：{exc}。"
            "请重新执行：pip install -r requirements.txt"
        ) from exc

    maps_dir = Path(__file__).parent / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    path = maps_dir / f"route_{timestamp}_day{day_index}.html"
    day_points = [point for point in points if point.get("day") == day_index]
    day_segments = [segment for segment in route_segments if segment.day_index == day_index]
    valid = [p for p in day_points if p.get("location") and "lat" in p["location"] and "lng" in p["location"]]
    if not valid:
        raise ZeroOutputError(f"Day{day_index} 地图渲染失败：没有可用 POI 坐标")
    # v6: 允许无路线段的地图（纯餐饮/极简路线），只展示 marker
    render_segments_only = bool(day_segments)

    center_lat = sum(p["location"]["lat"] for p in valid) / len(valid)
    center_lng = sum(p["location"]["lng"] for p in valid) / len(valid)
    fmap = folium.Map(location=[center_lat, center_lng], zoom_start=12, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles="https://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        attr="高德地图",
        name="高德地图",
        overlay=False,
        control=True,
    ).add_to(fmap)
    day_plan = None
    if complete_plan is not None and complete_plan.day_plans:
        for dp in complete_plan.day_plans:
            if dp.day_index == day_index:
                day_plan = dp
                break

    # 按时间窗口创建 FeatureGroup
    all_windows = ["morning", "lunch", "afternoon", "dinner", "evening"]
    feature_groups: dict[str, folium.FeatureGroup] = {}
    for window in all_windows:
        label = _TIME_WINDOW_LABELS[window]
        feature_groups[label] = folium.FeatureGroup(name=label, show=True)

    for point in valid:
        kind = point.get("kind", "")
        if kind == "meal":
            marker_color = _MEAL_COLOR
            marker_icon = "cutlery"
            window_label = _TIME_WINDOW_LABELS.get(
                _time_window_for_point(day_points, day_points.index(point), day_plan) if day_plan else "morning",
                "上午",
            )
        elif kind == "start":
            marker_color = _START_COLOR
            marker_icon = "play"
            window_label = "上午"
        elif kind == "anchor":
            point_idx = day_points.index(point) if point in day_points else 0
            window = _time_window_for_point(day_points, point_idx, day_plan) if day_plan else "morning"
            window_label = _TIME_WINDOW_LABELS[window]
            marker_color = _TIME_PERIOD_COLORS[window]["primary"]
            marker_icon = "star"
        elif kind == "anchor_internal":
            # v3：waypoint用橙色Marker，途经点用蓝色小Marker
            point_idx = day_points.index(point) if point in day_points else 0
            window = _time_window_for_point(day_points, point_idx, day_plan) if day_plan else "morning"
            window_label = _TIME_WINDOW_LABELS[window]
            is_wp = point.get("is_waypoint", True)
            walk_min = point.get("walk_from_route_min", 0)
            if is_wp:
                marker_color = "#E67E22"  # orange for waypoints
                marker_icon = "circle"
            else:
                marker_color = "#3498DB"  # blue for passing POIs
                marker_icon = "record"
                # Override tooltip to show walking time
                original_name = point.get("name", "")
                point["_tooltip"] = f"{original_name}（步行{walk_min}分钟可达）"
        elif kind == "micro":
            # v3：微观点，waypoint用蓝色标记，途经点用灰色小标记
            point_idx = day_points.index(point) if point in day_points else 0
            window = _time_window_for_point(day_points, point_idx, day_plan) if day_plan else "morning"
            window_label = _TIME_WINDOW_LABELS[window]
            is_wp = point.get("is_waypoint", True)
            walk_min = point.get("walk_from_route_min", 0)
            if is_wp:
                marker_color = "#2980B9"
                marker_icon = "info-sign"
            else:
                marker_color = "#7F8C8D"  # gray for passing micro POIs
                marker_icon = "record"
                point["_tooltip"] = f"{point.get('name', '')}（步行{walk_min}分钟可达）"
        elif kind in ("free_explore", "hint"):
            # v3新增：降级提示不画marker，v4.1移除虚线圆圈
            continue
        else:
            point_idx = day_points.index(point) if point in day_points else 0
            window = _time_window_for_point(day_points, point_idx, day_plan) if day_plan else "morning"
            window_label = _TIME_WINDOW_LABELS[window]
            marker_color = _TIME_PERIOD_COLORS[window]["primary"]
            marker_icon = "info-sign"
        # v5.2: 同建筑POI特殊tooltip
        if point.get("route_annotation") == "同建筑":
            point["_tooltip"] = f"{point.get('name', '')}（同一建筑内）"
        tooltip_text = point.get("_tooltip", point["name"])
        marker = folium.Marker(
            location=[point["location"]["lat"], point["location"]["lng"]],
            popup=point["name"],
            tooltip=tooltip_text,
            icon=folium.Icon(color=_folium_icon_color(marker_color), icon=marker_icon),
        )
        fg = feature_groups.get(window_label)
        if fg is not None:
            marker.add_to(fg)

    # v5.2: 预处理 — 短步行段合并 + 重叠检测裁剪
    # Step 1: 短段合并 — 连续步行段<500m的合并到前一段（跳过meal段，保留时间窗口分隔）
    _SHORT_WALK_MERGE_KM = 0.5
    _meal_poi_names: set[str] = {p["name"] for p in day_points if p.get("kind") == "meal"}

    merged_day_segments: list[RouteSegment] = []
    for seg in day_segments:
        _involves_meal = seg.from_poi in _meal_poi_names or seg.to_poi in _meal_poi_names
        if (seg.transport == "步行"
            and seg.distance_km < _SHORT_WALK_MERGE_KM
            and not _involves_meal
            and merged_day_segments
            and merged_day_segments[-1].transport == "步行"
            and merged_day_segments[-1].day_index == seg.day_index):
            prev = merged_day_segments[-1]
            prev_polyline = list(prev.polyline) + list(seg.polyline)
            prev_dist = prev.distance_km + seg.distance_km
            prev_dur = prev.duration_min + seg.duration_min
            merged_day_segments[-1] = RouteSegment(
                from_poi=prev.from_poi,
                to_poi=seg.to_poi,
                day_index=prev.day_index,
                transport="步行",
                duration_min=round(prev_dur, 1),
                distance_km=round(prev_dist, 3),
                polyline=prev_polyline,
            )
        else:
            merged_day_segments.append(seg)
    day_segments = merged_day_segments

    # Step 2: 合并后polyline内部去重 — 清理拼接处的重复/近距点
    _JUNCTION_DEDUP_M = 15.0
    for seg in day_segments:
        if seg.transport != "步行" or len(seg.polyline) < 4:
            continue
        cleaned: list[list[float]] = [seg.polyline[0]]
        for pt in seg.polyline[1:]:
            dlat = pt[0] - cleaned[-1][0]
            dlng = pt[1] - cleaned[-1][1]
            dist_m = math.sqrt(dlat * dlat + dlng * dlng) * 111000
            if dist_m >= _JUNCTION_DEDUP_M:
                cleaned.append(pt)
        # 确保终点不被误删
        if cleaned[-1] != seg.polyline[-1]:
            last_pt = seg.polyline[-1]
            dlat = last_pt[0] - cleaned[-1][0]
            dlng = last_pt[1] - cleaned[-1][1]
            if math.sqrt(dlat * dlat + dlng * dlng) * 111000 > 1.0:
                cleaned.append(last_pt)
        if len(cleaned) >= 2:
            seg.polyline = cleaned  # type: ignore[misc]

    # Step 3: 支路去除 — 从步行polyline中检测并去除"拐进POI再折返"的支路
    # 原理：将polyline各点投影到起终点主轴上，投影值回退超过阈值的段落即为支路
    # （路径从主路拐进POI内部再折回主路），这些支路不画，POI用标注代替
    _SPUR_BACKWARD_M = 30.0  # 回退超过30m视为支路
    _SHORT_SEG_PROJECT_KM = 0.2  # 200m以下算短段

    for seg_idx, seg in enumerate(day_segments):
        if seg.transport != "步行" or len(seg.polyline) < 3:
            continue
        pl = seg.polyline
        start_pt, end_pt = pl[0], pl[-1]
        dir_lat = end_pt[0] - start_pt[0]
        dir_lng = end_pt[1] - start_pt[1]
        dir_len = math.sqrt(dir_lat ** 2 + dir_lng ** 2)
        if dir_len < 1e-10:
            continue
        dir_lat_n = dir_lat / dir_len
        dir_lng_n = dir_lng / dir_len
        threshold_deg = _SPUR_BACKWARD_M / 111000.0

        # Step 3a: 短步行段终点投影修正（<200m）— 如果终点明显偏离主轴方向，
        # 说明步行API导航到了POI门口（支路末端），截断到最远前进点
        new_end_pt: list[float] | None = None
        if seg.distance_km < _SHORT_SEG_PROJECT_KM and len(pl) >= 3:
            # 找到polyline上最远的前进点（主轴投影最大值）
            max_proj_idx = 0
            max_proj_val = 0.0
            for idx in range(len(pl)):
                rel_lat = pl[idx][0] - start_pt[0]
                rel_lng = pl[idx][1] - start_pt[1]
                proj_val = rel_lat * dir_lat_n + rel_lng * dir_lng_n
                if proj_val > max_proj_val:
                    max_proj_val = proj_val
                    max_proj_idx = idx
            # 如果终点投影值 < 最远前进点投影值 - 阈值，说明终点是支路末端
            end_proj = (pl[-1][0] - start_pt[0]) * dir_lat_n + (pl[-1][1] - start_pt[1]) * dir_lng_n
            if max_proj_val - end_proj > threshold_deg:
                # 终点是支路，用最远前进点作为新终点
                new_end_pt = list(pl[max_proj_idx])
                pl = list(pl[:max_proj_idx + 1])
                seg.polyline = pl  # type: ignore[misc]

        # Step 3b: 投影回退检测 — 检测polyline中的折返段落
        result: list[list[float]] = [pl[0]]
        max_proj = 0.0
        in_spur = False
        for i in range(1, len(pl)):
            rel_lat = pl[i][0] - start_pt[0]
            rel_lng = pl[i][1] - start_pt[1]
            proj = rel_lat * dir_lat_n + rel_lng * dir_lng_n
            if proj >= max_proj - threshold_deg:
                # 前进或微幅回退（<30m），保留
                if in_spur:
                    in_spur = False
                result.append(pl[i])
                if proj > max_proj:
                    max_proj = proj
            else:
                # 显著回退 → 支路起点，跳过
                if not in_spur:
                    in_spur = True
        # 确保终点保留
        if result[-1] != pl[-1]:
            result.append(pl[-1])
        if len(result) >= 2:
            seg.polyline = result  # type: ignore[misc]
            new_end_pt = list(result[-1])  # 更新修正后的终点

        # Step 3c: 如果当前段终点被修正，同步修正下一段的起点
        # （下一段的polyline开头可能还是从旧终点（POI门口）出发的，需要替换为新的主路点）
        if new_end_pt is not None and seg_idx + 1 < len(day_segments):
            next_seg = day_segments[seg_idx + 1]
            if next_seg.transport == "步行" and len(next_seg.polyline) >= 2:
                old_start = next_seg.polyline[0]
                dlat = old_start[0] - new_end_pt[0]
                dlng = old_start[1] - new_end_pt[1]
                gap_m = math.sqrt(dlat * dlat + dlng * dlng) * 111000
                if gap_m > 5.0:  # 差距>5m时替换起点
                    next_seg.polyline = [new_end_pt] + list(next_seg.polyline[1:])  # type: ignore[misc]

    # Step 4: 段间衔接 — 确保相邻段polyline首尾相连不断线
    _CONNECT_GAP_M = 50.0
    prev_end: list[float] | None = None
    for seg in day_segments:
        coords = list(seg.polyline)
        if prev_end is not None and coords:
            dlat = coords[0][0] - prev_end[0]
            dlng = coords[0][1] - prev_end[1]
            gap_m = math.sqrt(dlat * dlat + dlng * dlng) * 111000
            if gap_m > _CONNECT_GAP_M:
                # 段间有空隙，用上一段末尾点补接
                coords = [prev_end] + coords
                seg.polyline = coords  # type: ignore[misc]
        if coords:
            prev_end = coords[-1]

    for segment in day_segments:
        coords = list(segment.polyline)
        if len(coords) >= 2:
            to_idx = next(
                (i for i, p in enumerate(day_points) if p.get("name") == segment.to_poi),
                0,
            )
            window = _time_window_for_point(day_points, to_idx, day_plan) if day_plan else "morning"
            window_label = _TIME_WINDOW_LABELS[window]
            palette = _TIME_PERIOD_COLORS[window]
            is_transit_mode = _is_transit(segment.transport)
            route_color = palette["primary"]
            route_weight = _TRANSIT_WEIGHT if is_transit_mode else _WALK_WEIGHT
            route_opacity = 1.0
            polyline_kwargs: dict[str, Any] = {
                "color": route_color,
                "weight": route_weight,
                "opacity": route_opacity,
            }
            if is_transit_mode:
                polyline_kwargs["dash_array"] = "10, 10"
                # v5.2: transit段优先使用API返回的真实polyline，只在缺失时降级为起终点直线
                if len(coords) < 2:
                    # polyline缺失，降级为起终点直线
                    a_loc = next((p for p in day_points if p.get("name") == segment.from_poi), None)
                    b_loc = next((p for p in day_points if p.get("name") == segment.to_poi), None)
                    if a_loc and b_loc and a_loc.get("location") and b_loc.get("location"):
                        coords = [
                            [a_loc["location"]["lat"], a_loc["location"]["lng"]],
                            [b_loc["location"]["lat"], b_loc["location"]["lng"]],
                        ]
            polyline = folium.PolyLine(
                coords,
                tooltip=(
                    f"Day{segment.day_index} {segment.from_poi} -> {segment.to_poi}: "
                    f"{segment.transport} {round(segment.duration_min)}min"
                ),
                **polyline_kwargs,
            )
            fg = feature_groups.get(window_label)
            if fg is not None:
                polyline.add_to(fg)
            arrow_color = _lighten_color(palette["primary"], 0.35) if not is_transit_mode else _lighten_color(palette["light"], 0.2)
            for frac in _ARROW_INTERVALS:
                alat, alng, bearing = _polyline_point_at(coords, frac)
                arrow = folium.RegularPolygonMarker(
                    location=[alat, alng],
                    number_of_sides=3,
                    radius=_ARROW_RADIUS,
                    rotation=bearing - 90,
                    color=arrow_color,
                    fill=True,
                    fill_color=arrow_color,
                    fill_opacity=0.75,
                    weight=1,
                )
                if fg is not None:
                    arrow.add_to(fg)
        else:
            # v6: 尝试从 day_points 中按名称找坐标构造 stub polyline
            from_pt = next((p for p in day_points if p.get("name") == segment.from_poi), None)
            to_pt = next((p for p in day_points if p.get("name") == segment.to_poi), None)
            stub = _make_stub_polyline(from_pt or {}, to_pt or {})
            if stub:
                print(f"[WARN step3] skip segment with no drawable polyline: {segment.from_poi} -> {segment.to_poi}")
            else:
                print(f"[WARN step3] skip segment with no polyline and no coords: {segment.from_poi} -> {segment.to_poi}")

    summary = "<br>".join(
        f"{segment.from_poi} -> {segment.to_poi}: {segment.transport} "
        f"{round(segment.duration_min)}min / 轨迹点{len(segment.polyline)}个"
        for segment in day_segments
    )
    folium.CircleMarker(
        location=[center_lat, center_lng],
        radius=0,
        popup=folium.Popup(summary, max_width=420),
    ).add_to(fmap)


    for fg in feature_groups.values():
        if len(fg._children) > 0:
            fg.add_to(fmap)
    _render_legend(fmap, day_index)
    folium.LayerControl(collapsed=False).add_to(fmap)

    fmap.save(str(path))
    try:
        rel_path = path.relative_to(Path.cwd())
        return f"./{rel_path.as_posix()}"
    except ValueError:
        return str(path)


def _render_maps(
    points: list[dict[str, Any]],
    route_segments: list[RouteSegment],
    complete_plan=None,
    parsed_intent=None,
) -> tuple[str, list[dict[str, Any]]]:
    # v6: 从 route_segments 推导 day_indices，不足时从 points 补充
    day_indices = sorted({segment.day_index for segment in route_segments})
    if not day_indices:
        day_indices = sorted({p.get("day", 1) for p in points if p.get("location") and "lat" in p["location"]})
    if not day_indices:
        print("[WARN step3] _render_maps: no day indices, returning empty")
        return "", []
    timestamp = f"{dt.datetime.now():%Y%m%d_%H%M%S}"
    map_infos = [
        {
            "day": day_index,
            "path": _render_single_day_map(points, route_segments, day_index, timestamp, complete_plan, parsed_intent),
            "route_segments": sum(1 for segment in route_segments if segment.day_index == day_index),
        }
        for day_index in day_indices
    ]
    label = "；".join(f"Day{item['day']}: {item['path']}" for item in map_infos)
    return label, map_infos




def _spatial_assign_pois(
    sub_anchors: list[SubAnchor],
    anchor_names: list[str],
) -> list[SubAnchor]:
    """v5.2 r5: POI空间硬分配 — 每个POI只归最近的子锚点中心。
    替代原_reassign_cross_anchor_pois的名称匹配降权方案。
    核心原则：搜索阶段可能重叠，但分配阶段一锤定音。
    注意：用sub.name而非sub.parent_name做key，因为full_day锚点会拆成
    北段/南段等子锚点，parent_name相同但name不同。
    """
    if len(sub_anchors) < 2 or not anchor_names:
        return sub_anchors

    # 构建子锚点中心坐标映射（用sub.name，唯一标识每个子锚点）
    anchor_centers: dict[str, dict] = {}
    for sub in sub_anchors:
        if sub.name not in anchor_centers and sub.location:
            anchor_centers[sub.name] = sub.location

    # 收集所有POI，重新按距离分配到子锚点
    new_pois: dict[str, list[dict]] = {sub.name: [] for sub in sub_anchors}
    for sub in sub_anchors:
        for poi in sub.internal_pois:
            poi_loc = poi.get("location")
            if not poi_loc:
                new_pois[sub.name].append(poi)
                continue
            # 找最近的子锚点
            nearest_sub = min(
                anchor_centers,
                key=lambda name: haversine_km(poi_loc, anchor_centers[name]),
            )
            new_pois[nearest_sub].append(poi)

    # 去重（同一个POI可能被多个子锚点搜到）
    for sub in sub_anchors:
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for poi in new_pois.get(sub.name, []):
            pid = poi.get("id") or poi.get("name", "")
            if pid not in seen_ids:
                seen_ids.add(pid)
                deduped.append(poi)
        sub.internal_pois = deduped

    return sub_anchors

async def _run_planned_route(
    parsed_intent: ParsedIntent,
    complete_plan: CompletePlan,
    city: str,
    logger: PipelineLogger,
) -> tuple[list[MicroPOI], list[RouteSegment], str, dict[str, dict[str, Any]]]:
    """v5.2 r3: 规划性意图路线 — 递进解析waypoint + 路线串联。
    不走锚点拆解/微观搜索流程，直接基于用户指定的途经点规划。
    """
    await emit_status("正在规划您的行程路线...")

    waypoints = parsed_intent.planned_waypoints
    start_location = parsed_intent.original_location or {}
    start_name = start_location.get("label", "出发地")

    # 1. 递进解析waypoint
    logger.start_step("step_3_0_planned_resolve")
    resolved_wps = await resolve_planned_waypoints(waypoints, start_location, city)
    resolved_count = sum(1 for wp in resolved_wps if wp.resolved_location)
    await logger.log_step(
        "step_3_0_planned_resolve",
        output_count=resolved_count,
        details={
            "total_waypoints": len(waypoints),
            "resolved": resolved_count,
            "waypoint_names": [wp.resolved_name or wp.name or wp.search_keyword for wp in resolved_wps],
        },
    )

    if resolved_count == 0:
        raise ZeroOutputError("未能找到任何途经点，请检查您的需求描述")

    # 2. 构建路线点序列
    route_points = build_planned_route_points(resolved_wps, start_location, start_name, day_index=1)

    # 3. 构建路线段（复用 _build_segments）
    logger.start_step("step_3_5_planned_routing")
    await emit_status("正在生成路线...")
    segments, waypoint_annotations = await _build_segments(parsed_intent, parsed_intent.transport_hint or "公共交通", route_points)
    await logger.log_step(
        "step_3_5_planned_routing",
        output_count=len(segments),
        details={
            "route_segments": len(segments),
            "sub_anchors": ["__planned__"],
        },
    )

    # 4. 渲染地图（复用 _render_maps）
    map_files = _render_maps(route_points, segments, waypoint_annotations, parsed_intent, complete_plan)

    # 5. 生成输出文本
    summary = _generate_planned_output_text(route_points, segments, resolved_wps)

    # 6. 返回（MicroPOI为空列表，因为planned模式不走锚点内搜索）
    return [], segments, summary, waypoint_annotations


def _generate_planned_output_text(
    route_points: list[dict],
    segments: list[RouteSegment],
    waypoints: list[PlannedWaypoint],
) -> str:
    """v5.2 r3: 生成规划性路线的输出文本"""
    lines = []
    lines.append("为您规划了连续途经点的行程路线。")

    # 构建行程描述
    route_parts = []
    current = route_points[0] if route_points else {}
    for seg in segments:
        route_parts.append(f"{seg.from_poi} - {seg.transport}({seg.duration_min:.0f}min) - {seg.to_poi}")

    if route_parts:
        lines.append("路线：" + " → ".join(
            f"{seg.from_poi} -{seg.transport}({seg.duration_min:.0f}min)-" for seg in segments[:1]
        ))
        # 简化输出
        steps = []
        for seg in segments:
            steps.append(f"{seg.from_poi} → {seg.transport}({seg.duration_min:.0f}min) → {seg.to_poi}")
        lines.append("\n".join(steps))

    # 途经点摘要
    resolved_names = [wp.resolved_name or wp.name or wp.search_keyword for wp in waypoints if wp.resolved_location]
    if resolved_names:
        lines.append(f"途经：{' → '.join(resolved_names)}")

    return "\n".join(lines)


def _inject_required_anchors(
    points: list[dict[str, Any]],
    parsed_intent: ParsedIntent,
    complete_plan: CompletePlan,
    micro_pois: list[MicroPOI],
) -> list[dict[str, Any]]:
    """v6+v20: 确保固定锚点/meal POI 进入 route_points。

    v20: ALL user-specified fixed anchors are required in route_points,
    not just meal/keyword-matched ones. Non-meal fixed anchors get
    kind='primary_anchor' with correct display properties.
    """

    # Step A: 收集必须保留的 POI 名称和对应 slot/day
    _required: dict[str, dict] = {}  # name → {day, slot, kind}
    _meal_pois_by_name: dict[str, MicroPOI] = {m.name: m for m in micro_pois if m.is_meal}

    # User-specified fixed POI names
    _user_fixed_names = {fp.name for fp in (parsed_intent.fixed_pois or [])}

    # 从 meal_slots 中收集已选餐饮 POI，记录其 slot 和 day
    for day in complete_plan.day_plans:
        for slot in day.meal_slots:
            pn = slot.get("poi_name")
            meal = slot.get("meal", "dinner")
            if pn and pn in _meal_pois_by_name:
                _required[pn] = {"day": day.day_index, "slot": meal, "kind": "meal"}

    # v20: Collect ALL fixed anchors (not just meal/keyword ones)
    for day in complete_plan.day_plans:
        for anchor in day.anchors:
            name = anchor.name
            tc = getattr(anchor, "typecode", "") or ""
            is_fixed = getattr(anchor, "fixed", False)
            is_user_named = name in _user_fixed_names
            is_meal = tc.startswith("05")

            # Already in points or already in _required
            if name in {p.get("name") for p in points} or name in _required:
                continue

            if is_fixed or is_user_named:
                # v20: Fixed anchor — inject as primary_anchor, NOT meal
                _required[name] = {
                    "day": day.day_index,
                    "slot": "",
                    "kind": "primary_anchor",
                    "fixed": True,
                    "anchor_obj": anchor,
                }
            elif is_meal:
                strong_kws = set(parsed_intent.food_pref_keywords or [])
                for kw in (parsed_intent.meal_search_keywords or []):
                    strong_kws.add(kw)
                for kw in (parsed_intent.search_keywords or []):
                    strong_kws.add(kw)
                if any(kw in name for kw in strong_kws if len(kw) >= 2):
                    _required[name] = {"day": day.day_index, "slot": "dinner", "kind": "meal"}

    if not _required:
        return points

    # v20: Log required fixed anchors
    _required_fixed = [n for n, info in _required.items() if info.get("kind") == "primary_anchor"]
    if _required_fixed:
        print(
            f"[RequiredAnchorInjection] "
            f"before={[p.get('name') for p in points]} "
            f"required_fixed={_required_fixed}"
        )

    # Step B: 将缺失的必须 POI 注入 points（插入到 start 之后）
    _existing_names = {p.get("name") for p in points}
    # 找到 start point 后面的插入位置
    _insert_idx = 1
    for i, p in enumerate(points):
        if p.get("kind") == "start":
            _insert_idx = i + 1
            break

    result = list(points)
    for name, info in _required.items():
        if name in _existing_names:
            continue

        day_idx = info["day"]
        slot = info["slot"]
        kind = info["kind"]

        m = _meal_pois_by_name.get(name)
        if m:
            pt = {
                "day": day_idx,
                "name": m.name,
                "location": m.location,
                "kind": kind,
                "poi_id": m.gaode_poi_id or m.name,
                "gaode_poi_id": m.gaode_poi_id,
                "typecode": m.typecode,
                "category": m.typecode,
                "address": m.address,
                "rating": m.gaode_rating,
                "avg_cost": m.avg_cost,
                "photo_url": m.photo_url,
                "photo_source": m.photo_source,
                "parent_anchor": m.parent_anchor,
                "is_waypoint": True,
                "is_display_poi": True,
                "display_slot": slot,
            }
        else:
            # 从 anchors 中找
            for day in complete_plan.day_plans:
                for anchor in day.anchors:
                    if anchor.name == name and anchor.location:
                        pt = {
                            "day": day_idx,
                            "name": anchor.name,
                            "location": anchor.location,
                            "kind": kind,
                            "poi_id": getattr(anchor, "gaode_poi_id", "") or anchor.name,
                            "gaode_poi_id": getattr(anchor, "gaode_poi_id", "") or "",
                            "typecode": getattr(anchor, "typecode", "") or "",
                            "category": getattr(anchor, "typecode", "") or "",
                            "address": getattr(anchor, "address", "") or "",
                            "rating": getattr(anchor, "gaode_rating", None),
                            "avg_cost": getattr(anchor, "avg_cost", None),
                            "photo_url": getattr(anchor, "photo_url", "") or "",
                            "photo_source": getattr(anchor, "photo_source", "") or "",
                            "parent_anchor": "",
                            "recommend_reason": getattr(anchor, "recommend_reason", "") or "",
                            "is_waypoint": True,
                            "is_display_poi": True,
                            "display_slot": slot,
                        }
                        break
            else:
                continue

        # v20: For primary_anchor, set correct display properties and slot
        if kind == "primary_anchor":
            pt["primary_target"] = True
            pt["fixed"] = True
            if not pt.get("display_slot"):
                existing_slots = [p.get("display_slot") for p in points if p.get("display_slot")]
                if "morning" not in str(existing_slots):
                    pt["display_slot"] = "morning"
                else:
                    pt["display_slot"] = "afternoon"
            pt["recommend_reason"] = pt.get("recommend_reason", "") or "用户指定目的地"
            print(
                f"[RequiredAnchorInjection] inserted={name} "
                f"kind={kind} slot={pt.get('display_slot')} "
                f"fixed={pt.get('fixed')} primary={pt.get('primary_target')}"
            )
        elif kind == "meal":
            print(f"[DEBUG step3] injected meal POI: {name} day={day_idx} slot={slot}")

        result.insert(_insert_idx, pt)
        _insert_idx += 1

    # v20: Log final state
    if _required_fixed:
        _final_names = [p.get("name") for p in result if p.get("kind") == "primary_anchor"]
        print(
            f"[RequiredAnchorInjection] "
            f"after={_final_names}"
        )

    return result


def _build_candidate_points(
    points: list[dict[str, Any]],
    micro_pois: list[MicroPOI],
    sub_anchors: list,
    micro_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """v6: 从 _candidate_pool 和 points 中未展示的 anchor_internal 构建候选 POI 列表。

    v13: micro_policy 控制主题相关候选过滤和排序。
    过滤规则：
    - 只排除真正进入路线的展示/必经点：kind=start, kind=meal, is_waypoint=True 的路线点
    - 将 kind='anchor_internal' 且 is_waypoint=False 的内部 POI 纳入候选池
    - 排除 kind 为 hint/free_explore/route_only/traffic/empty 的点
    - 每个 sub_anchor 最多 2 个候选点
    - 每天最多 8 个候选点
    - 全路线最多 20 个候选点
    - 优先保留 rating 高、有 photo_url/address 的点
    """
    # 收集真正路线必经点的标识（start/meal/is_waypoint=True）
    _route_key_poi_ids: set[str] = set()
    _route_key_names: set[str] = set()
    for pt in points:
        kind = pt.get("kind", "")
        is_wp = pt.get("is_waypoint", True)
        # 只排除真正路线必经点
        if kind in ("start", "meal") or (is_wp and kind != "hint"):
            pid = pt.get("poi_id") or pt.get("gaode_poi_id") or ""
            name = pt.get("name", "")
            if pid:
                _route_key_poi_ids.add(pid)
            if name:
                _route_key_names.add(name)

    # 从 points 中收集 kind=anchor_internal 且 is_waypoint=False 的内部 POI 作为候选
    _non_waypoint_internal: list[dict] = []
    for pt in points:
        kind = pt.get("kind", "")
        if kind != "anchor_internal":
            continue
        if pt.get("is_waypoint", True):
            continue
        pid = pt.get("poi_id") or pt.get("gaode_poi_id") or ""
        name = pt.get("name", "")
        if pid in _route_key_poi_ids or name in _route_key_names:
            continue
        _non_waypoint_internal.append(pt)

    # 排除非展示 kind
    _excluded_kinds = {"hint", "free_explore", "route_only", "traffic", "empty"}

    policy = micro_policy or {"active": False}

    # 按 sub_anchor 分组收集候选（从 _candidate_pool）
    _by_sub: dict[str, list[dict]] = {}
    for (d_idx, sub_name), cands in _candidate_pool.items():
        for c in cands:
            pid = c.get("poi_id") or c.get("gaode_poi_id") or ""
            name = c.get("name", "")
            if pid in _route_key_poi_ids or name in _route_key_names:
                continue
            if c.get("kind") in _excluded_kinds:
                continue
            if not _is_micro_poi_compatible(c, policy):
                continue
            c = dict(c)
            c["theme_score"] = _micro_poi_theme_score(c, policy)
            _by_sub.setdefault(sub_name, []).append(c)

    # 将 non_waypoint internal POIs 也加入候选池
    for pt in _non_waypoint_internal:
        sub_name = pt.get("sub_anchor_name", "")
        if not sub_name:
            continue
        pid = pt.get("poi_id") or pt.get("gaode_poi_id") or ""
        name = pt.get("name", "")
        if pid in _route_key_poi_ids or name in _route_key_names:
            continue
        # 去重检查
        existing = _by_sub.get(sub_name, [])
        if any((e.get("poi_id") or e.get("gaode_poi_id") or e.get("name")) == (pid or name) for e in existing):
            continue
        if not _is_micro_poi_compatible(pt, policy):
            continue
        rating_val = pt.get("rating") or pt.get("gaode_rating")
        try:
            rating_val = float(rating_val) if rating_val is not None else 0.0
        except (ValueError, TypeError):
            rating_val = 0.0
        cand = {
            "name": name,
            "location": pt.get("location", {}),
            "kind": "candidate",
            "candidate_source": "route_non_waypoint",
            "poi_id": pid or name,
            "gaode_poi_id": pt.get("gaode_poi_id", ""),
            "typecode": pt.get("typecode", ""),
            "category": pt.get("category", pt.get("typecode", "")),
            "address": pt.get("address", ""),
            "rating": rating_val,
            "gaode_rating": rating_val,
            "avg_cost": pt.get("avg_cost"),
            "photo_url": pt.get("photo_url", ""),
            "photo_source": pt.get("photo_source", ""),
            "parent_anchor": pt.get("parent_anchor") or pt.get("parent_name", ""),
            "sub_anchor_name": sub_name,
            "recommend_reason": "",
            "candidate_score": rating_val,
            "day": pt.get("day", 1),
            "theme_score": _micro_poi_theme_score(pt, policy),
        }
        _by_sub.setdefault(sub_name, []).append(cand)

    # 对每个 sub_anchor 内的候选排序（主题相关性优先）
    def _candidate_sort_key(c: dict) -> float:
        rating_score = float(c.get("rating") or c.get("candidate_score") or 0)
        richness_score = 0.0
        if c.get("photo_url"):
            richness_score += 1.0
        if c.get("address"):
            richness_score += 0.5
        theme_score = float(c.get("theme_score") or 0)
        return -(theme_score * 10 + rating_score + richness_score)

    # 每天统计
    _day_counts: dict[int, int] = {}
    _max_per_day = 8
    _max_per_sub = 2
    _max_total = 20
    candidate_points: list[dict] = []

    # 重建按 day+sub 的索引
    _by_day_sub: dict[int, dict[str, list[dict]]] = {}
    for sub_name, cands in _by_sub.items():
        for c in cands:
            d_idx = c.get("day", 1)
            _by_day_sub.setdefault(d_idx, {}).setdefault(sub_name, []).append(c)

    for d_idx in sorted(_by_day_sub.keys()):
        for sub_name in sorted(_by_day_sub[d_idx].keys()):
            cands = sorted(_by_day_sub[d_idx][sub_name], key=_candidate_sort_key)
            # v13: 主题模式 — 优先展示有主题得分的候选
            if policy.get("active"):
                themed_candidates = [
                    candidate
                    for candidate in cands
                    if float(candidate.get("theme_score") or 0) > 0
                ]
                if themed_candidates:
                    cands = themed_candidates
            taken_from_sub = 0
            for c in cands:
                if len(candidate_points) >= _max_total:
                    break
                if _day_counts.get(d_idx, 0) >= _max_per_day:
                    break
                if taken_from_sub >= _max_per_sub:
                    break
                candidate_points.append(c)
                _day_counts[d_idx] = _day_counts.get(d_idx, 0) + 1
                taken_from_sub += 1
        if len(candidate_points) >= _max_total:
            break

    # 清空池子
    _candidate_pool.clear()

    return candidate_points


# v16: 夜景 POI 轻量重排 — 避免夜景内容被排在上午

NIGHT_SCENE_TERMS = (
    "夜景",
    "夜景打卡",
    "夜景观赏",
    "灯光夜景",
    "灯光",
    "夜游",
    "夜间",
    "晚景",
    "夜色",
    "观夜景",
)


def _is_night_scene_point(point: dict[str, Any]) -> bool:
    text = " ".join(
        str(point.get(k) or "")
        for k in (
            "name",
            "recommend_reason",
            "reason",
            "core_reason",
            "description",
            "summary",
            "address",
        )
    )
    return any(term in text for term in NIGHT_SCENE_TERMS)


def _has_late_slot(points: list[dict[str, Any]]) -> bool:
    for p in points:
        slot = str(p.get("display_slot") or p.get("slot") or p.get("period") or "").lower()
        if slot in {"evening", "night", "dinner"}:
            return True
    return False


def _ensure_theme_half_day_density(
    route_points: list[dict[str, Any]],
    parsed_intent: ParsedIntent,
) -> list[dict[str, Any]]:
    """v18: 主题路线半日密度保障 — soft target 3个真实游览点/half-day, hard floor 2个。

    若某半日低于 hard floor，优先从同天另一半日挪冗余点，但不能把另一半降到 floor 以下。
    """
    _is_theme = bool(
        getattr(parsed_intent, "theme_profile", None)
        or getattr(parsed_intent, "theme_label", None)
        or getattr(parsed_intent, "micro_poi_keywords", None)
        or getattr(parsed_intent, "theme_keywords", None)
    )
    _is_full_day = float(getattr(parsed_intent, "time_budget", 0) or 0) >= 1.0
    if not _is_theme or not _is_full_day:
        return route_points

    SOFT_TARGET = 3
    HARD_FLOOR = 2

    def _is_real_visit(p: dict[str, Any]) -> bool:
        kind = str(p.get("kind") or "").lower()
        if kind in {"start", "meal", "restaurant", "hint", "free_explore"}:
            return False
        if _is_night_scene_point(p):
            return False
        return True

    def _slot_key(p: dict[str, Any]) -> str:
        slot = str(p.get("display_slot") or p.get("slot") or "").lower()
        return slot

    def _is_lunch(p: dict[str, Any]) -> bool:
        slot = _slot_key(p)
        kind = str(p.get("kind") or "").lower()
        name = str(p.get("name") or "")
        return (kind in {"meal", "restaurant"} and slot == "lunch") or "午餐" in name or "午饭" in name

    def _is_dinner(p: dict[str, Any]) -> bool:
        slot = _slot_key(p)
        kind = str(p.get("kind") or "").lower()
        name = str(p.get("name") or "")
        return (kind in {"meal", "restaurant"} and slot == "dinner") or "晚餐" in name or "晚饭" in name

    def _dist_between(a: dict, b: dict) -> float:
        al = a.get("location") or {}
        bl = b.get("location") or {}
        if al and bl and al.get("lat") and bl.get("lat"):
            return haversine_km(al, bl)
        return 999.0

    result: list[dict[str, Any]] = []
    by_day: dict[int, list[dict[str, Any]]] = {}
    for p in route_points:
        day = int(p.get("day") or p.get("day_index") or 1)
        by_day.setdefault(day, []).append(p)

    for day in sorted(by_day.keys()):
        points = list(by_day[day])
        lunch_idx = next((i for i, p in enumerate(points) if _is_lunch(p)), None)
        dinner_idx = next((i for i, p in enumerate(points) if _is_dinner(p)), None)

        if lunch_idx is None:
            result.extend(points)
            continue

        morning_end = lunch_idx
        afternoon_end = dinner_idx if dinner_idx is not None else len(points)

        morning_visits = [p for p in points[:morning_end] if _is_real_visit(p)]
        afternoon_visits = [p for p in points[morning_end:afternoon_end] if _is_real_visit(p)]
        evening_visits = [p for p in points[afternoon_end:] if _is_real_visit(p)] if dinner_idx else []

        before_counts = (len(morning_visits), len(afternoon_visits), len(evening_visits))

        # Check if any half needs help
        need_morning = len(morning_visits) < HARD_FLOOR
        need_afternoon = len(afternoon_visits) < HARD_FLOOR

        if not need_morning and not need_afternoon:
            result.extend(points)
            continue

        moved_names: list[str] = []

        # Try moving from afternoon to morning
        if need_morning and len(afternoon_visits) > HARD_FLOOR:
            morning_names = {p.get("name") for p in morning_visits}
            last_morning = points[morning_end - 1] if morning_end > 0 else points[0]
            lunch_point = points[lunch_idx]
            needed = max(1, HARD_FLOOR - len(morning_visits))
            moved_count = 0

            for i in range(morning_end, afternoon_end):
                if moved_count >= needed:
                    break
                candidate = points[i]
                if not _is_real_visit(candidate):
                    continue
                name = candidate.get("name")
                if name in morning_names:
                    continue
                d_lunch = _dist_between(candidate, lunch_point)
                d_morning = _dist_between(candidate, last_morning)
                if min(d_lunch, d_morning) > 3.0:
                    continue

                moved = dict(candidate)
                moved["display_slot"] = "morning"
                moved.pop("display_order", None)
                moved["rebalance_reason"] = "theme_half_day_density_floor"
                points.pop(i)
                points.insert(morning_end, moved)
                morning_end += 1
                moved_count += 1
                moved_names.append(name)
                morning_names.add(name)
                if lunch_idx is not None and i < lunch_idx:
                    lunch_idx += 1
                if dinner_idx is not None and i < dinner_idx:
                    dinner_idx += 1
                afternoon_end = dinner_idx if dinner_idx is not None else len(points)
                afternoon_visits = [p for p in points[morning_end:afternoon_end] if _is_real_visit(p)]
                if len(afternoon_visits) <= HARD_FLOOR:
                    break

        # Try moving from morning to afternoon
        afternoon_end = dinner_idx if dinner_idx is not None else len(points)
        afternoon_visits = [p for p in points[morning_end:afternoon_end] if _is_real_visit(p)]
        if need_afternoon and len(morning_visits) > HARD_FLOOR:
            afternoon_names = {p.get("name") for p in afternoon_visits}
            first_afternoon = points[morning_end] if morning_end < len(points) else points[-1]
            needed = max(1, HARD_FLOOR - len(afternoon_visits))
            moved_count = 0

            for i in range(morning_end - 1, -1, -1):
                if moved_count >= needed:
                    break
                candidate = points[i]
                if not _is_real_visit(candidate):
                    continue
                name = candidate.get("name")
                if name in afternoon_names:
                    continue
                d_anchor = _dist_between(candidate, first_afternoon)
                if d_anchor > 3.0:
                    continue

                moved = dict(candidate)
                moved["display_slot"] = "afternoon"
                moved.pop("display_order", None)
                moved["rebalance_reason"] = "theme_half_day_density_floor"
                points.pop(i)
                points.insert(morning_end, moved)
                moved_count += 1
                moved_names.append(name)
                afternoon_names.add(name)
                if lunch_idx is not None and i < lunch_idx:
                    lunch_idx -= 1
                if dinner_idx is not None and i < dinner_idx:
                    dinner_idx -= 1
                afternoon_end = dinner_idx if dinner_idx is not None else len(points)
                afternoon_visits = [p for p in points[morning_end:afternoon_end] if _is_real_visit(p)]
                if len(morning_visits) - moved_count <= HARD_FLOOR:
                    break

        after_counts = (len(morning_visits), len(afternoon_visits), len(evening_visits))
        if moved_names:
            print(
                f"[DEBUG step3] ensured theme half-day density day={day} "
                f"moved={moved_names} before_counts={before_counts} after_counts={after_counts}"
            )
        result.extend(points)

    for idx, p in enumerate(result, start=1):
        if p.get("kind") != "start":
            p["route_order"] = idx
        else:
            p["route_order"] = 1

    return result


def _promote_density_waypoints(
    points: list[dict[str, Any]],
    waypoint_annotations: dict[str, dict[str, Any]],
    parsed_intent: ParsedIntent,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """v18: 主题路线半日密度兜底 — 将隐藏的非waypoint anchor_internal提升为主展示点。

    对主题路线按 day + slot 分组，若某半日主展示 POI < HARD_FLOOR，
    优先从同 day 同 slot 的 anchor_internal(is_waypoint=False)中提升。
    """
    _is_theme = bool(
        getattr(parsed_intent, "theme_profile", None)
        or getattr(parsed_intent, "theme_label", None)
        or getattr(parsed_intent, "micro_poi_keywords", None)
        or getattr(parsed_intent, "theme_keywords", None)
    )
    if not _is_theme:
        return points, waypoint_annotations

    HARD_FLOOR = 2

    def _slot_of(p: dict[str, Any]) -> str:
        ds = str(p.get("display_slot") or p.get("slot") or "").lower()
        if ds in ("morning", "am", "上午"):
            return "morning"
        if ds in ("afternoon", "pm", "下午"):
            return "afternoon"
        if ds in ("evening", "night", "晚上"):
            return "evening"
        return ""

    def _is_real_display(p: dict[str, Any]) -> bool:
        kind = str(p.get("kind") or "").lower()
        if kind in {"start", "meal", "restaurant", "hint", "free_explore"}:
            return False
        if p.get("same_building"):
            return False
        if _is_night_scene_point(p):
            return False
        return True

    # Group points by (day, slot)
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for p in points:
        day = int(p.get("day") or p.get("day_index") or 1)
        slot = _slot_of(p)
        groups.setdefault((day, slot), []).append(p)

    promoted_total: list[str] = []
    for (day, slot), group in groups.items():
        if slot not in ("morning", "afternoon"):
            continue
        # Count real display waypoints
        display_wps = [p for p in group if _is_real_display(p) and p.get("is_waypoint")]
        if len(display_wps) >= HARD_FLOOR:
            continue

        # Find candidates: same day+slot, anchor_internal, not waypoint, not night
        needed = HARD_FLOOR - len(display_wps)
        candidates = [
            p for p in group
            if p.get("kind") == "anchor_internal"
            and not p.get("is_waypoint")
            and _is_real_display(p)
            and p.get("name") not in {wp.get("name") for wp in display_wps}
        ]
        # Sort by rating desc
        candidates.sort(key=lambda p: float(p.get("rating") or p.get("gaode_rating") or 0), reverse=True)

        promoted: list[str] = []
        for c in candidates[:needed]:
            c["is_waypoint"] = True
            c["density_promoted"] = True
            name = str(c.get("name") or "")
            promoted.append(name)
            waypoint_annotations[name] = {
                "is_waypoint": True,
                "walk_from_route_min": 0,
                "day": day,
                "density_promoted": True,
            }

        if promoted:
            promoted_total.extend(promoted)
            print(
                f"[DEBUG step3] promoted density POIs to waypoints "
                f"day={day} slot={slot} names={promoted}"
            )

    return points, waypoint_annotations


# v20: Light eat buffer — collects light eat candidates filtered out of internal POIs
# so _interleave_stroll_eat_points can use them even when theme policy would exclude them.
_stroll_eat_buffer: list[dict[str, Any]] = []

LIGHT_EAT_NAMES = {"小吃", "咖啡", "甜品", "蛋糕", "奶茶", "茶饮", "冰淇淋", "烘焙", "面包", "零食", "轻食", "简餐"}
LIGHT_EAT_TYPECODES = {
    "050100",  # 中餐厅 — only when combined with light food name (see _is_light_eat_candidate)
}
# v20: Light eat typecodes for use in _is_light_eat_candidate — excludes 050100 to avoid
# false-positive on regular restaurants like 海底捞. 050100 is only light food when name matches.
LIGHT_EAT_TYPECODES_STRICT = {"050200", "050300", "050301", "050302", "050900", "051000"}
# v20: English light food detection — Baker & Spice etc.
LIGHT_EAT_ENGLISH_TERMS = [
    "baker", "bakery", "bread", "cafe", "coffee", "dessert", "pastry", "spice",
    "cake", "patisserie", "boulangerie", "gelato", "ice cream", "yogurt",
    "smoothie", "juice bar", "tea house", "bubble tea", "donut", "muffin",
    "croissant", "bagel", "sandwich", "salad", "snack", "sweets",
    "starbucks", "costa", "manner", "tim hortons", "pret a manger",
]


def _is_light_eat_candidate(poi: dict[str, Any]) -> bool:
    """Check if a POI is a light eat/snack/cafe candidate — data-driven, no city names.

    v20: Uses strict typecode matching. 050100 (中餐厅) only counts as light food
    when combined with name evidence (e.g. "咖啡", "bakery").
    """
    from .poi_typecodes import matches_typecode
    name = str(poi.get("name", "") or "")
    name_lower = name.lower()
    typecode = str(poi.get("typecode", "") or "")
    category = str(poi.get("category", "") or "").lower()

    has_light_name = (
        any(term in name for term in LIGHT_EAT_NAMES)
        or any(term in name_lower for term in LIGHT_EAT_ENGLISH_TERMS)
    )
    has_light_category = any(
        term in category for term in ["咖啡", "甜品", "面包", "烘焙", "茶饮", "cafe", "bakery", "dessert", "pastry"]
    )
    has_strict_typecode = matches_typecode(typecode, list(LIGHT_EAT_TYPECODES_STRICT))

    # Light name/category alone is enough
    if has_light_name or has_light_category:
        return True
    # Strict typecodes (0502xx-0510xx) are reliably light food
    if has_strict_typecode:
        return True
    # 050100 (中餐厅) only with name or category evidence — not alone
    if matches_typecode(typecode, ["050100"]) and (has_light_name or has_light_category):
        return True

    return False


def _interleave_stroll_eat_points(
    points: list[dict[str, Any]],
    parsed_intent: ParsedIntent,
) -> list[dict[str, Any]]:
    """v18+v20: 逛吃穿插 — 在上午/下午游览点间穿插轻食/小吃/咖啡/甜品。

    v20: 每 1-2 个真实逛游点后最多插入 1 个轻食点，全天最多 2-3 个。
    轻食不能替换午餐和晚餐。候选来源包括 _stroll_eat_buffer 和 points 中未展示的轻食点。
    """
    constraints = getattr(parsed_intent, "other_constraints", []) or []
    if "逛吃穿插" not in constraints:
        return points

    def _is_visit(p: dict[str, Any]) -> bool:
        kind = str(p.get("kind") or "").lower()
        return kind in {"anchor_internal", "micro"} and p.get("is_waypoint") in (True, None)

    # Build light eat candidate pool from:
    # 1) Points that are light_eat but not waypoints
    # 2) _stroll_eat_buffer (collected during internal POI filtering)
    light_pool: list[dict[str, Any]] = []
    for p in points:
        if _is_light_eat_candidate(p) and not p.get("is_waypoint"):
            kind = str(p.get("kind") or "").lower()
            if kind not in {"meal", "restaurant", "start", "hint", "free_explore"}:
                light_pool.append(p)

    # Also check _stroll_eat_buffer for additional candidates
    for p in _stroll_eat_buffer:
        if _is_light_eat_candidate(p):
            p_already_in = any(p.get("name") == existing.get("name") for existing in points)
            if not p_already_in:
                light_pool.append(p)

    if not light_pool:
        print("[DEBUG step3] interleave_stroll_eat: no light eat candidates in pool or buffer")
        return points

    print(
        f"[DEBUG step3] interleave_stroll_eat: "
        f"light_pool_size={len(light_pool)} buffer_size={len(_stroll_eat_buffer)} "
        f"names={[p.get('name') for p in light_pool[:8]]}"
    )

    # Group by day
    by_day: dict[int, list[dict[str, Any]]] = {}
    for p in points:
        day = int(p.get("day") or p.get("day_index") or 1)
        by_day.setdefault(day, []).append(p)

    # Separate light pool by day based on location proximity to day's visit points
    def _day_for_light_candidate(lc: dict[str, Any]) -> int:
        lc_loc = lc.get("location") or {}
        if not lc_loc:
            return 1
        best_day = 1
        best_dist = float("inf")
        for d, day_pts in by_day.items():
            for dp in day_pts:
                dp_loc = dp.get("location") or {}
                if dp_loc:
                    dist = haversine_km(lc_loc, dp_loc)
                    if dist < best_dist:
                        best_dist = dist
                        best_day = d
        return best_day

    result: list[dict[str, Any]] = []
    total_light_used = 0
    max_total_light = 3  # v20: 全天最多 3 个轻食点

    for day in sorted(by_day.keys()):
        day_points = by_day[day]
        light_for_day = [lc for lc in light_pool if _day_for_light_candidate(lc) == day]
        if not light_for_day:
            result.extend(day_points)
            continue

        interleaved: list[dict[str, Any]] = []
        visit_count = 0
        light_used = 0

        for p in day_points:
            interleaved.append(p)
            if _is_visit(p):
                visit_count += 1
                if visit_count % 2 == 0 and light_used < len(light_for_day) and total_light_used < max_total_light:
                    lc = light_for_day[light_used]
                    # v20: don't replace lunch/dinner meal slots
                    slot = str(p.get("display_slot") or "")
                    if slot in {"lunch", "dinner"}:
                        continue
                    lc["kind"] = "micro"
                    lc["is_waypoint"] = True
                    lc["is_display_poi"] = True
                    lc["stroll_eat_promoted"] = True
                    lc["display_slot"] = p.get("display_slot", "")
                    lc["recommend_reason"] = lc.get("recommend_reason") or "逛吃穿插推荐"
                    lc.pop("display_order", None)
                    interleaved.append(lc)
                    light_used += 1
                    total_light_used += 1

        if light_used > 0:
            print(
                f"[DEBUG step3] interleaved stroll-eat day={day} "
                f"inserted={light_used} names={[light_for_day[i].get('name') for i in range(min(light_used, len(light_for_day)))]}"
            )
        result.extend(interleaved)

    # Recompute display_order
    for idx, p in enumerate(result, start=1):
        if p.get("kind") != "start":
            p["route_order"] = idx
        else:
            p["route_order"] = 1

    return result


def _defer_night_scene_points(route_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Move morning-position night-scene POIs to a later same-day position.

    This runs before Step4 assigns display_slot for normal activity points, so it
    must infer "morning-position" from relative order before lunch/dinner instead
    of relying on point.display_slot == "morning".
    """
    if not route_points:
        return route_points

    def _slot_of(p: dict[str, Any]) -> str:
        return str(p.get("display_slot") or p.get("slot") or p.get("period") or "").lower()

    def _kind_of(p: dict[str, Any]) -> str:
        return str(p.get("kind") or "").lower()

    def _is_lunch(p: dict[str, Any]) -> bool:
        slot = _slot_of(p)
        kind = _kind_of(p)
        name = str(p.get("name") or "")
        return (kind in {"meal", "restaurant"} and slot == "lunch") or slot == "lunch" or "午餐" in name or "午饭" in name

    def _is_dinner(p: dict[str, Any]) -> bool:
        slot = _slot_of(p)
        kind = _kind_of(p)
        name = str(p.get("name") or "")
        return (kind in {"meal", "restaurant"} and slot == "dinner") or slot == "dinner" or "晚餐" in name or "晚饭" in name

    def _is_evening_slot(p: dict[str, Any]) -> bool:
        return _slot_of(p) in {"evening", "night"}

    result: list[dict[str, Any]] = []
    by_day: dict[int, list[dict[str, Any]]] = {}

    for p in route_points:
        day = int(p.get("day") or p.get("day_index") or 1)
        by_day.setdefault(day, []).append(p)

    for day in sorted(by_day.keys()):
        points = by_day[day]
        if not points:
            continue

        lunch_idx = next((idx for idx, p in enumerate(points) if _is_lunch(p)), None)
        dinner_idx = next((idx for idx, p in enumerate(points) if _is_dinner(p)), None)
        first_meal_idx = lunch_idx if lunch_idx is not None else dinner_idx

        normal_points: list[dict[str, Any]] = []
        deferred_points: list[dict[str, Any]] = []

        for idx, p in enumerate(points):
            kind = _kind_of(p)

            if kind in {"start", "meal", "restaurant"}:
                normal_points.append(p)
                continue

            explicit_slot = _slot_of(p)
            is_already_late = explicit_slot in {"afternoon", "evening", "night"}
            is_before_first_meal = first_meal_idx is not None and idx < first_meal_idx

            if is_before_first_meal and not is_already_late and _is_night_scene_point(p):
                moved = dict(p)
                moved["display_slot"] = "afternoon"
                moved["deferred_from_slot"] = "morning"
                moved["defer_reason"] = "night_scene_before_lunch"
                moved.pop("display_order", None)
                deferred_points.append(moved)
            else:
                normal_points.append(p)

        if not deferred_points:
            result.extend(points)
            continue

        has_evening = any(_is_evening_slot(p) for p in normal_points)

        for p in deferred_points:
            if has_evening:
                p["display_slot"] = "evening"
            elif dinner_idx is not None:
                p["display_slot"] = "afternoon"
            else:
                p["display_slot"] = "afternoon"

        insert_idx = None
        for idx, p in enumerate(normal_points):
            if has_evening and _is_evening_slot(p):
                insert_idx = idx
                break
            if not has_evening and _is_dinner(p):
                insert_idx = idx
                break

        if insert_idx is None:
            normal_points.extend(deferred_points)
        else:
            normal_points[insert_idx:insert_idx] = deferred_points

        print(
            f"[DEBUG step3] deferred morning night-scene points day={day}: "
            f"{[p.get('name') for p in deferred_points]}"
        )
        result.extend(normal_points)

    for idx, p in enumerate(result, start=1):
        p["route_order"] = idx
        p.pop("display_order", None)

    return result


async def _targeted_supplement_recall(
    parsed_intent: ParsedIntent,
    complete_plan: CompletePlan,
    points: list[dict[str, Any]],
    sub_anchors: list[Any],
) -> list[dict[str, Any]]:
    """City-scoped targeted recall for a genuinely sparse full-day theme route.

    The query terms come from Step1's original theme/search fields.  Results are
    hard-limited to CompletePlan.city; no unrelated category fallback is used.
    """
    city = complete_plan.city or ""
    if not city:
        return []

    raw_terms = [
        *(getattr(parsed_intent, "micro_keywords", []) or []),
        *(getattr(parsed_intent, "micro_poi_keywords", []) or []),
        *(getattr(parsed_intent, "theme_keywords", []) or []),
        *(getattr(parsed_intent, "search_keywords", []) or []),
    ]
    supplement_terms: list[str] = []
    for term in raw_terms:
        clean = str(term or "").strip()
        if clean and clean not in supplement_terms:
            supplement_terms.append(clean)
    if not supplement_terms:
        return []

    results: list[dict[str, Any]] = []
    existing_names = {str(point.get("name") or "") for point in points}
    city_short = city.rstrip("市")

    for term in supplement_terms[:4]:
        try:
            raws = await gaode_text_search(
                term,
                city=city,
                show_fields=config.GAODE_SHOW_FIELDS,
                city_limit=True,
            )
        except Exception:
            continue

        query_tokens = [
            token for token in str(term).replace(city, "").replace(city_short, "").split()
            if len(token) >= 2 and token not in {"攻略", "推荐", "路线", "打卡", "拍照", "休闲"}
        ]
        for raw in (raws or [])[:10]:
            place = raw_to_place(raw)
            if not place or not place.get("location"):
                continue
            name = str(place.get("name", "") or "")
            if not name or name in existing_names:
                continue
            typecode = str(place.get("typecode", "") or "")
            identity_text = " ".join([
                name,
                str(place.get("category", "") or ""),
                str(place.get("address", "") or ""),
            ])
            if query_tokens and not any(token in identity_text for token in query_tokens):
                continue
            if not is_valid_route_poi(typecode, name):
                continue
            existing_names.add(name)
            results.append({
                "name": name,
                "location": place.get("location"),
                "typecode": typecode,
                "kind": "anchor_internal",
                "is_display_poi": True,
                "is_waypoint": True,
                "supplement_recall": True,
                "recommend_reason": f"{city_short}市范围内主题补充推荐",
            })
            if len(results) >= 5:
                break
        if len(results) >= 5:
            break

    print(
        f"[DEBUG step3] targeted_supplement_recall: "
        f"scope=citywide city={city} terms={supplement_terms[:4]} found={len(results)}"
    )
    return results[:5]


async def run_step3(
    parsed_intent: ParsedIntent,
    complete_plan: CompletePlan,
    logger: PipelineLogger,
) -> tuple[list[MicroPOI], list[RouteSegment], str, dict[str, str], dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    city = complete_plan.city or "上海市"
    micro_policy = _resolve_micro_poi_policy(parsed_intent)
    print(
        "[DEBUG step3] micro_theme_policy="
        f"{{'active': {micro_policy.get('active')}, "
        f"'profile_id': '{micro_policy.get('profile_id', '')}', "
        f"'label': '{micro_policy.get('label', '')}', "
        f"'search_terms': {list(micro_policy.get('search_terms', []))[:6]}, "
        f"'required_terms': {list(micro_policy.get('preferred_name_terms', []))[:10]}, "
        f"'excluded_terms': {list(micro_policy.get('excluded_terms', []))[:10]}, "
        f"'reject_unrequested_sports': {micro_policy.get('reject_unrequested_sports')}}}"
    )

    # ── v5.2 r3: 规划性意图分支 ──
    if getattr(parsed_intent, 'plan_mode', 'exploratory') == 'planned' and getattr(parsed_intent, 'planned_waypoints', []):
        result = await _run_planned_route(parsed_intent, complete_plan, city, logger)
        _candidate_pool.clear()
        # Ensure 7 return values
        if len(result) == 6:
            return result[0], result[1], result[2], result[3], result[4], result[5], []
        return result

    # ── 3.0 锚点拆解 ──
    logger.start_step("step_3_0_decompose")
    await emit_status("正在分析目的地结构...")
    all_anchors = [anchor for day in complete_plan.day_plans for anchor in day.anchors]
    sub_anchors = await _decompose_anchors(all_anchors, city, parsed_intent.original_location or {})
    await logger.log_step(
        "step_3_0_decompose",
        output_count=len(sub_anchors),
        details={
            "original_anchors": len(all_anchors),
            "sub_anchors": len(sub_anchors),
            "sub_anchor_names": [s.name for s in sub_anchors],
            "degradation": {s.name: s.degradation_level for s in sub_anchors},
        },
    )

    # ── 3.1 锚点内子POI搜索 + 筛选排序 ──
    logger.start_step("step_3_1_internal_search")
    await emit_status("正在搜索目的地内部景点...")
    # v20: clear stroll eat buffer before new search
    _stroll_eat_buffer.clear()
    theme_search = list(micro_policy.get("search_terms", []))[:8] if micro_policy.get("active") else None
    sub_anchors = await _search_anchor_internals(sub_anchors, city, theme_search_terms=theme_search)
    # v5.2 r5: POI空间硬分配 — 每个POI只归最近的锚点，解决跨锚点POI泄漏
    sub_anchors = _spatial_assign_pois(sub_anchors, [a.name for a in all_anchors])
    # v5.2 r5: 后续子锚点的entry_point用前一个子锚点的终点，避免贪心排序从出发点开始导致折返
    prev_end: dict = parsed_intent.original_location or {}
    for sub in sub_anchors:
        is_large = _is_large_area(sub.internal_pois)
        filtered, trim_hint = _filter_and_sort_internal_pois(
            sub.internal_pois,
            prev_end,
            sub.time_budget_min,
            sub.variance_ratio,
            is_large,
            micro_policy=micro_policy,
            parsed_intent=parsed_intent,
        )
        sub.internal_pois = filtered
        # 更新prev_end为当前子锚点排序后最后一个POI的位置
        if filtered:
            prev_end = filtered[-1].get("location", prev_end)
        if trim_hint and not sub.degradation_hint:
            sub.degradation_hint = trim_hint
        new_level, new_hint = _determine_degradation(filtered, sub.capacity)
        print(
            f"[DEBUG step3 degrade] sub={sub.name} filtered_count={len(filtered)} "
            f"degradation={new_level} hint={new_hint} capacity={sub.capacity}"
        )
        if new_level != sub.degradation_level:
            sub.degradation_level = new_level
            if new_hint and not sub.degradation_hint:
                sub.degradation_hint = new_hint
    await logger.log_step(
        "step_3_1_internal_search",
        output_count=sum(len(s.internal_pois) for s in sub_anchors),
        details={
            "internal_poi_counts": {s.name: len(s.internal_pois) for s in sub_anchors},
            "degradation": {s.name: s.degradation_level for s in sub_anchors},
        },
    )

    # ── 3.1.5 v5.2 sub-anchor 方向命名 ──
    if sub_anchors:
        from collections import defaultdict
        groups = defaultdict(list)
        for sub in sub_anchors:
            groups[sub.parent_name].append(sub)
        for parent_name, group in groups.items():
            if len(group) >= 2:
                name_sub_anchors_by_direction(group, anchor_name=parent_name)
        await logger.log_step(
            "step_3_1_5_naming",
            output_count=len(sub_anchors),
            details={"sub_anchor_renamed": [s.name for s in sub_anchors]},
        )

    # ── 3.1b 微观点搜索 [v5.2 已删除，POI统一由锚点面域搜索获取] ──
    selected_micro: list[MicroPOI] = []

    # ── 3.3 餐饮搜索位置 ──
    # 按 day 生成餐饮参考点，避免多锚点/多天场景下所有餐点共用全局参考点。
    meal_refs_by_day: dict[tuple[int, str], dict[str, Any]] = {}
    for day in complete_plan.day_plans:
        anchor_names = {anchor.name for anchor in day.anchors}
        day_subs = [
            sub
            for sub in sub_anchors
            if sub.parent_name in anchor_names or sub.name in anchor_names
        ]
        day_meals = [
            slot.get("meal")
            for slot in day.meal_slots
            if slot.get("meal")
        ]
        refs = _meal_search_points(
            day_subs,
            day_meals,
            parsed_intent.original_location or {},
        )
        for slot in day.meal_slots:
            meal = slot.get("meal")
            ref = refs.get(meal)
            if meal and ref:
                meal_refs_by_day[(day.day_index, meal)] = ref

    # v12: 没有 sub_anchors 但有 meal_slots 时，用当天活动anchor（而非出发点）作为餐饮参考点
    if not meal_refs_by_day:
        for day in complete_plan.day_plans:
            fallback_ref = _fallback_meal_reference(day, parsed_intent)
            for slot in day.meal_slots:
                meal = slot.get("meal")
                if meal:
                    meal_refs_by_day[(day.day_index, meal)] = fallback_ref

    # ── 3.4 餐饮搜索与筛选 ──
    meal_diagnostics: list[dict[str, Any]] = []
    meal_selection_diagnostics: list[dict[str, Any]] = []
    meal_raw = await _search_meals(parsed_intent, complete_plan, meal_refs_by_day, meal_diagnostics)
    # v6 MealDebug
    print(f"[MealDebug] strong_meal_intent: food_pref={parsed_intent.food_pref_keywords} meal_search={parsed_intent.meal_search_keywords}")
    print(f"[MealDebug] meal_refs_by_day: {[(k, v.get('name')) for k, v in meal_refs_by_day.items()]}")
    print(f"[MealDebug] meal_diagnostics: {meal_diagnostics}")
    print(f"[MealDebug] meal_raw names/typecode/category: {[(m.name, m.typecode, getattr(m, 'category', '')) for m in meal_raw[:15]]}")
    budget_threshold = complete_plan.budget_threshold or (
        parsed_intent.budget_per_capita
        if parsed_intent.budget_per_capita is not None
        else 100.0 * config.BUDGET_MULTIPLIER
    )
    print(
        f"[MealDebug] budget_threshold={budget_threshold} "
        f"request_budget={parsed_intent.budget_per_capita} "
        f"complete_plan_budget={complete_plan.budget_threshold}"
    )
    # v5.2: 构建每天锚点POI坐标列表，用于meal散布约束
    # 注意：排除出发地（kind=start），只算锚点区域内的POI
    _day_anchor_locs: dict[int, list[dict[str, float]]] = {}
    for day in complete_plan.day_plans:
        anchor_names = {a.name for a in day.anchors}
        day_subs = [s for s in sub_anchors if s.parent_name in anchor_names or s.name in anchor_names]
        for sub in day_subs:
            loc = sub.location
            if loc and "lat" in loc:
                _day_anchor_locs.setdefault(day.day_index, []).append({"lat": loc["lat"], "lng": loc["lng"]})
            for ip in (sub.internal_pois or []):
                iloc = ip.get("location")
                if iloc and "lat" in iloc:
                    _day_anchor_locs.setdefault(day.day_index, []).append({"lat": iloc["lat"], "lng": iloc["lng"]})

    selected_meals = await _select_meals(
        meal_raw, complete_plan, budget_threshold, meal_refs_by_day, meal_selection_diagnostics,
        day_anchor_locations=_day_anchor_locs,
        parsed_intent=parsed_intent,
    )
    micro_pois = selected_meals  # v5.2: 游览POI已在sub.internal_pois中，此处只有餐饮

    # v6: 调试日志 — 餐饮诊断
    print(f"[DEBUG step3] strong_meal_intent: meal_raw={len(meal_raw)} food_pref={parsed_intent.food_pref_keywords} meal_search={parsed_intent.meal_search_keywords}")
    print(f"[DEBUG step3] meal_slots: {[(s.get('meal'), s.get('poi_name')) for d in complete_plan.day_plans for s in d.meal_slots]}")
    print(f"[DEBUG step3] selected_meals names: {[m.name for m in selected_meals]}")
    print(f"[DEBUG step3] meal_selection_diagnostics: {meal_selection_diagnostics}")

    # ── 3.5 路线排布 ──
    logger.start_step("step_3_5_route_planning")
    await emit_status("正在规划详细路线...")
    points = _route_planning(sub_anchors, micro_pois, parsed_intent, complete_plan)

    # v6: 调试日志 — 路线点
    print(f"[DEBUG step3] route_points before injection names/kinds: {[(p.get('name'), p.get('kind')) for p in points]}")
    # v6: 注入强意图 anchor（如日料 POI）确保进入 route_points
    points = _inject_required_anchors(points, parsed_intent, complete_plan, micro_pois)
    print(f"[DEBUG step3] route_points after injection names/kinds: {[(p.get('name'), p.get('kind')) for p in points]}")

    # v16: 夜景 POI 轻量重排 — 不放上午，优先下午/晚间
    points = _defer_night_scene_points(points)
    print(
        "[DEBUG step3] route_points after night-scene defer names/slots: "
        f"{[(p.get('name'), p.get('display_slot'), p.get('deferred_from_slot')) for p in points]}"
    )

    # v16: 主题路线半日均衡 — 确保上午至少 2 个真实游览点
    points = _ensure_theme_half_day_density(points, parsed_intent)

    # v18: 逛吃穿插 — 上午/下午游览点之间优先穿插轻食/小吃/咖啡/甜品
    points = _interleave_stroll_eat_points(points, parsed_intent)

    route_segments, waypoint_annotations = await _build_segments(parsed_intent, parsed_intent.transport_hint or "公共交通", points)

    # 将waypoint标注信息注入points，供地图渲染和输出使用
    for point in points:
        ann = waypoint_annotations.get(point.get("name", ""))
        if ann:
            point["is_waypoint"] = ann["is_waypoint"]
            point["walk_from_route_min"] = ann["walk_from_route_min"]

    # ── v5.2: 同建筑POI标注 — 非代表POI标记为"同建筑"，并写入waypoint_annotations供step4输出 ──
    _bg = _cluster_same_building_pois([p for p in points if p.get("location") and "lat" in p["location"]])
    _bg_members: dict[str, list[str]] = {}
    for name, gid in _bg.items():
        _bg_members.setdefault(gid, []).append(name)
    _bg_skip_names: set[str] = set()
    for gid, members in _bg_members.items():
        for m in members[1:]:
            _bg_skip_names.add(m)
    for point in points:
        if point.get("name") in _bg_skip_names:
            point["route_annotation"] = "同建筑"
            # 写入waypoint_annotations，让step4输出时也能读到
            waypoint_annotations[point["name"]] = {
                "is_waypoint": False,
                "walk_from_route_min": 0,
                "day": point.get("day", 0),
                "same_building": True,
            }

    # v18: 主题路线密度兜底 — 提升隐藏点为主展示点
    points, waypoint_annotations = _promote_density_waypoints(points, waypoint_annotations, parsed_intent)

    # ── 3.6 POI路线标注 ──
    # v5.2: 对每个sub-anchor内的POI，标注其在路线polyline上的最近点和距离
    for point in points:
        if point.get("kind") == "anchor_internal" and point.get("sub_anchor_name"):
            # 找到该点所在的路线段
            for seg in route_segments:
                if seg.to_poi == point.get("name") and seg.polyline and len(seg.polyline) >= 2:
                    nearest_idx, nearest_dist_deg = _find_nearest_on_polyline(point.get("location", {}), seg.polyline)
                    nearest_dist_m = nearest_dist_deg * 111000  # 近似转换
                    point["route_nearest_dist_m"] = round(nearest_dist_m, 1)
                    # v5.2: 沿途经过型POI（公园/广场/观景台）始终标记为"沿途经过"
                    if point.get("is_passthrough"):
                        point["route_annotation"] = "沿途经过"
                    else:
                        point["route_annotation"] = (
                            f"步行{round(nearest_dist_m / 4.5 * 60 / 1000, 0)}分钟可达"
                            if nearest_dist_m > 50
                            else "沿途经过"
                        )
                    break

    # ── v20: Plan reality validation — before map rendering ──
    # Ensure primary query POI is visible, not hidden, and route matches display POIs.
    _reality = validate_plan_reality(
        parsed_intent=parsed_intent,
        route_points=points,
        selected_anchors=[
            {"name": a.name, "typecode": a.typecode, "location": a.location}
            for day in complete_plan.day_plans
            for a in day.anchors
        ],
        route_segments=[s.model_dump() if hasattr(s, "model_dump") else s for s in route_segments],
    )
    # v20: Initialize variables BEFORE conditional blocks to avoid UnboundLocalError
    _poi_qtype = getattr(parsed_intent, "poi_query_type", "") or ""
    _primary_query = getattr(parsed_intent, "primary_query", "") or ""
    _time_budget = float(getattr(parsed_intent, "time_budget", 1.0) or 1.0)

    _reality_log = plan_reality_audit_log(_reality, _primary_query)
    print(f"[DEBUG step3] {_reality_log}")

    if not _reality.valid:
        print(f"[WARN step3] Plan reality check failed: {_reality.violations}")

        # v20: Full-day theme routes with critical violations must block output
        _is_full_day_theme = (
            _poi_qtype in ("theme_route", "") and _time_budget >= 1.0
        )
        _critical_violations = (
            "no_primary_waypoint_found" in _reality.violations
            or "meal_takeover" in _reality.violations
            or "primary_target_marked_free_explore_or_hint" in _reality.violations
            or "full_day_theme_needs_3_related" in _reality.violations
        )

        # For poi_category/named_poi: hard block on critical violations
        if _poi_qtype in ("poi_category", "named_poi") and _critical_violations:
            raise ZeroOutputError(
                f"路线验证失败：{'; '.join(_reality.violations)}。"
                f"请调整搜索条件后重试。"
            )

        # v20: Full-day theme route — trigger targeted re-recall instead of silent output
        if _is_full_day_theme and _critical_violations:
            print(
                f"[WARN step3] full_day theme route with critical violations: "
                f"{_reality.violations}. Triggering targeted re-recall..."
            )
            # Try to supplement with nearby walkable POIs
            _supplement_points = await _targeted_supplement_recall(
                parsed_intent, complete_plan, points, sub_anchors,
            )
            if _supplement_points:
                for sp in _supplement_points:
                    if sp.get("name") not in {p.get("name") for p in points}:
                        points.append(sp)
                print(
                    f"[DEBUG step3] supplement recall added {len(_supplement_points)} points: "
                    f"{[sp.get('name') for sp in _supplement_points]}"
                )
            else:
                # Still failed — return clear message, don't pretend it's a valid full day
                raise ZeroOutputError(
                    f"该区域全天可逛地点不足（{_reality.violations}），"
                    f"建议缩小范围或换一个片区试试~"
                )

    # Ensure primary query POIs are visible waypoints (not hidden/free_explore)
    if _primary_query and _poi_qtype in ("poi_category", "named_poi"):
        for point in points:
            name = str(point.get("name", "") or "")
            kind = str(point.get("kind", "") or "")
            # Primary target must be visible
            if _primary_query.lower() in name.lower() and kind in ("free_explore", "hint"):
                point["kind"] = "anchor_internal"
                point["is_display_poi"] = True
                point["display_order"] = point.get("display_order") or max(
                    (p.get("display_order") or 0 for p in points if p.get("display_order")), default=0
                ) + 1
                print(f"[DEBUG step3] promoted hidden primary target to visible: {name}")

    # ── v20: Route endpoint validation ──
    # Route start/end must use final display POI coordinates, not restaurant or hidden POI.
    _visible_routable = [
        p for p in points
        if p.get("is_display_poi") or p.get("display_order") is not None
        if p.get("kind") not in ("hint", "free_explore", "route_only", "traffic")
        if p.get("location") and "lat" in p.get("location", {})
    ]
    if _visible_routable and route_segments:
        _first_name = _visible_routable[0].get("name", "")
        _last_name = _visible_routable[-1].get("name", "")
        for seg in route_segments:
            seg_from = getattr(seg, "from_poi", "") if hasattr(seg, "from_poi") else seg.get("from_poi", "")
            seg_to = getattr(seg, "to_poi", "") if hasattr(seg, "to_poi") else seg.get("to_poi", "")
            # If segment start is a meal that's not the first display POI, warn
            if "meal" in str(seg_from).lower() or "restaurant" in str(seg_from).lower():
                print(f"[WARN step3] route segment starts from meal/restaurant: {seg_from}")
            if "meal" in str(seg_to).lower() or "restaurant" in str(seg_to).lower():
                print(f"[WARN step3] route segment ends at meal/restaurant: {seg_to}")

    # ── 3.7 地图渲染 ──
    # v6: 地图渲染失败不阻断路线输出
    try:
        map_path, map_infos = _render_maps(points, route_segments, complete_plan, parsed_intent)
    except ZeroOutputError as e:
        print(f"[WARN step3] _render_maps failed (non-blocking): {e}")
        map_path = ""
        map_infos = []
    except Exception as e:
        print(f"[WARN step3] _render_maps unexpected error (non-blocking): {e}")
        map_path = ""
        map_infos = []

    await logger.log_step(
        "step_3_5_route_planning",
        output_count=len(route_segments),
        details={
            "map_path": map_path,
            "map_files": map_infos,
            "sub_anchors": [s.name for s in sub_anchors],
            "route_segments": [
                {
                    "from": segment.from_poi,
                    "to": segment.to_poi,
                    "day": segment.day_index,
                    "transport": segment.transport,
                    "duration_min": segment.duration_min,
                    "distance_km": segment.distance_km,
                    "polyline_points": len(segment.polyline),
                }
                for segment in route_segments
            ],
            "route_points": [
                {
                    "day": point.get("day"),
                    "name": point.get("name"),
                    "kind": point.get("kind"),
                    "location": point.get("location"),
                    "route_annotation": point.get("route_annotation"),
                    "route_nearest_dist_m": point.get("route_nearest_dist_m"),
                }
                for point in points
            ],
        },
    )
    # 构建锚点提示映射
    _hints: dict[str, str] = {}
    for sub in sub_anchors:
        if sub.degradation_hint and sub.parent_name not in _hints:
            _hints[sub.parent_name] = sub.degradation_hint

    # 返回 points 用于前端验证
    # ── v6: 构建候选 POI 列表 ──
    candidate_points = _build_candidate_points(
        points,
        micro_pois,
        sub_anchors,
        micro_policy=micro_policy,
    )
    return micro_pois, route_segments, map_path, _hints, waypoint_annotations, points, candidate_points
