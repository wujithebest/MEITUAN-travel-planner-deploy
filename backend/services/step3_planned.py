"""v5.2 r3: 规划性意图的递进路线规划模块。

处理用户明确指定途经点的连续决策需求，如：
  "去百联又一城逛→找麦当劳吃晚饭→顺路买水果"

核心逻辑：
  1. 按有序waypoint列表递进解析
  2. 每个waypoint基于上一站终点坐标搜索
  3. 搜索半径从小到大扩搜（500m→1000m→2000m）
  4. 用户指定的固定点绕过is_valid_route_poi过滤
  5. 路线串联复用_route_between
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any

from . import config
from .api_client import gaode_around_search, gaode_text_search
from .data_schema import ParsedIntent, PlannedWaypoint, RouteSegment
from .route_backbone import is_valid_route_poi
from .utils import PipelineLogger, ZeroOutputError, coord_to_param, emit_status, haversine_km, push_output


def _normalized_poi_identity(value: str) -> str:
    return re.sub(r"[\s\-()（）\[\]【】·]", "", str(value or "")).lower()


def _fixed_poi_name_matches(requested_name: str, candidate_name: str) -> bool:
    """Require an actual identity match before accepting a fixed POI result."""
    requested = _normalized_poi_identity(requested_name)
    candidate = _normalized_poi_identity(candidate_name)
    return bool(requested and len(requested) >= 2 and (requested in candidate or candidate in requested))


# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

# 搜索半径梯度（米）
_SEARCH_RADIUS_STEPS = [500, 1000, 2000, 3000]

# 品类关键词 → 默认搜索词映射
_CATEGORY_SEARCH_MAP = {
    "purchase": "",       # 用waypoint.search_keyword
    "meal": "",           # 用waypoint.name或search_keyword
    "visit": "",          # 用waypoint.name
    "explore": "",        # 用waypoint.search_keyword
}

# 品类 → 默认停留时间（分钟），可被waypoint.stay_minutes覆盖
_CATEGORY_STAY_MINUTES = {
    "visit": 45,
    "meal": 50,
    "purchase": 15,
    "explore": 60,
}

# 品类 → 高德types过滤（空字符串=不过滤）
_CATEGORY_TYPES = {
    "purchase": "060000|070000",  # 餐饮|生活服务（水果店在070000下）
    "meal": "060000",             # 餐饮
    "visit": "",                  # 不限类型
    "explore": "",                # 不限类型
}


# ═══════════════════════════════════════════════════════════════
# 核心逻辑
# ═══════════════════════════════════════════════════════════════

async def _search_waypoint(
    wp: PlannedWaypoint,
    center: dict,
    city: str = "上海",
) -> PlannedWaypoint:
    """解析单个waypoint：基于中心点搜索，返回带坐标的waypoint。
    
    搜索策略：
    - fixed类型：优先精确名称搜索，失败则around_search
    - placeholder类型：基于search_keyword的around_search
    - 半径从小到大扩搜
    """
    keyword = wp.name if wp.type == "fixed" else (wp.search_keyword or "")
    if not keyword:
        return wp

    category_types = _CATEGORY_TYPES.get(wp.category, "")

    # 策略1：fixed类型先尝试精确名称搜索（不限距离）
    if wp.type == "fixed" and wp.name:
        try:
            results = await gaode_text_search(wp.name, city=city)
            if results and len(results) > 0:
                best = results[0]
                loc = best.get("location")
                if isinstance(loc, str):
                    parts = loc.split(",")
                    loc = {"lng": float(parts[0]), "lat": float(parts[1])}
                wp.resolved_location = loc
                wp.resolved_name = best.get("name", wp.name)
                return wp
        except Exception:
            pass  # 降级到around_search

    # 策略2：around_search，半径从小到大
    for radius in _SEARCH_RADIUS_STEPS:
        try:
            loc_str = coord_to_param(center)
            results = await gaode_around_search(
                location=loc_str,
                keywords=keyword,
                radius=radius,
                types=category_types,
                show_fields=config.GAODE_SHOW_FIELDS,
                offset=5,
                sortrule="distance",  # 距离优先，找最近的
            )
            if results and len(results) > 0:
                best = results[0]
                loc = best.get("location")
                if isinstance(loc, str):
                    parts = loc.split(",")
                    loc = {"lng": float(parts[0]), "lat": float(parts[1])}
                # 验证结果确实匹配关键词
                result_name = best.get("name", "")
                if wp.type == "fixed" and wp.name:
                    # fixed点：检查结果名称是否包含搜索词
                    if wp.name.lower() not in result_name.lower() and result_name.lower() not in wp.name.lower():
                        continue  # 不匹配，扩大半径重试
                wp.resolved_location = loc
                wp.resolved_name = result_name
                return wp
        except Exception:
            continue

    # 所有半径都搜不到
    return wp


async def resolve_planned_waypoints(
    waypoints: list[PlannedWaypoint],
    start_location: dict,
    city: str = "上海",
) -> list[PlannedWaypoint]:
    """递进解析所有waypoint：按顺序逐点搜索，每个点基于上一站的终点。
    
    返回更新后的waypoint列表（resolved_location已填充）。
    搜索失败的waypoint保留原始状态，后续跳过。
    """
    resolved = []
    current_center = start_location

    for wp in waypoints:
        wp_copy = PlannedWaypoint(
            type=wp.type,
            name=wp.name,
            search_keyword=wp.search_keyword,
            category=wp.category,
            stay_minutes=wp.stay_minutes,
            search_center_name=getattr(wp, "search_center_name", None),
            search_center_location=getattr(wp, "search_center_location", None),
            time_slot=getattr(wp, "time_slot", None),
        )
        resolved_wp = await _search_waypoint(wp_copy, current_center, city)

        if resolved_wp.resolved_location:
            # 解析成功，更新中心点为当前站终点
            current_center = resolved_wp.resolved_location
        
        resolved.append(resolved_wp)

    return resolved


def build_planned_route_points(
    waypoints: list[PlannedWaypoint],
    start_location: dict,
    start_name: str,
    day_index: int = 1,
) -> list[dict[str, Any]]:
    """从解析后的waypoint列表生成路线点序列。
    
    跳过解析失败的waypoint，只保留成功定位的点。
    返回格式与step3_micro的route_points一致，可直接用于_build_segments。
    """
    points: list[dict[str, Any]] = []
    
    # 起点
    points.append({
        "day": day_index,
        "name": start_name,
        "location": start_location,
        "kind": "start",
    })

    current_loc = start_location
    for wp in waypoints:
        if not wp.resolved_location:
            continue  # 跳过解析失败的

        name = wp.resolved_name or wp.name or wp.search_keyword or "途经点"
        kind = "meal" if wp.category == "meal" else "anchor_internal"
        
        points.append({
            "day": day_index,
            "name": name,
            "location": wp.resolved_location,
            "kind": kind,
            "sub_anchor_name": "__planned__",
            "parent_name": "__planned__",
            "is_passthrough": False,
            "visit_min": wp.stay_minutes or _CATEGORY_STAY_MINUTES.get(wp.category, 30),
        })
        current_loc = wp.resolved_location

    return points


def estimate_planned_duration_min(waypoints: list[PlannedWaypoint]) -> int:
    """估算规划性waypoint的总停留时间（分钟），用于时间窗口校验。"""
    total = 0
    for wp in waypoints:
        total += wp.stay_minutes or _CATEGORY_STAY_MINUTES.get(wp.category, 30)
    # 加上合理的交通时间（每段平均15分钟）
    total += max(0, len(waypoints) - 1) * 15
    return total


def classify_plan_mode(waypoints: list[PlannedWaypoint]) -> str:
    """判断行程模式：纯探索 / 纯规划 / 混合。
    
    规则：
    - 无planned_waypoints → exploratory
    - 所有fixed_pois都转为planned_waypoints → planned  
    - 两者都有 → mixed
    """
    if not waypoints:
        return "exploratory"
    return "planned"


# ═══════════════════════════════════════════════════════════════
# v6 增强：候选 POI + 富数据 route_points
# ═══════════════════════════════════════════════════════════════

# 品类 → 类型过滤 + 停留时间
_PLANNED_CATEGORY_CONFIG: dict[str, dict] = {
    "meal": {"types": "050000|060000", "stay": 40, "radius": 3000},
    "purchase": {"types": "060000|060400|060401|060402|060200|060900|060100|070000", "stay": 20, "radius": 2500},
    "cafe": {"types": "050400|050900|051000", "stay": 25, "radius": 2000},
    "service": {"types": "070000|071000|071400|071500", "stay": 45, "radius": 3000},
    "visit": {"types": "", "stay": 30, "radius": 2000},
    "explore": {"types": "", "stay": 60, "radius": 2000},
    "home": {"types": "", "stay": 0, "radius": 0},
}

# 关键词 → category 推断
_KEYWORD_CATEGORY_HINTS = {
    "日料": "meal", "寿司": "meal", "拉面": "meal", "烤肉": "meal",
    "火锅": "meal", "烧烤": "meal", "本帮菜": "meal", "粤菜": "meal",
    "川菜": "meal", "湘菜": "meal", "西餐": "meal", "韩国": "meal",
    "炸鸡": "meal", "汉堡": "meal", "披萨": "meal", "沙拉": "meal",
    "麦当劳": "meal", "肯德基": "meal", "kfc": "meal",
    "吃": "meal", "餐厅": "meal", "饭店": "meal", "食堂": "meal",
    "咖啡": "cafe", "奶茶": "cafe", "星巴克": "cafe", "瑞幸": "cafe",
    "manner": "cafe", "下午茶": "cafe", "甜品": "cafe",
    "水果": "purchase", "超市": "purchase", "便利店": "purchase",
    "面包": "purchase", "蛋糕": "purchase", "买菜": "purchase",
    "全家": "purchase", "罗森": "purchase",
    "理发": "service", "剪发": "service", "美发": "service",
    "回家": "home", "到家": "home",
}


def _infer_category_from_keyword(keyword: str) -> str | None:
    """从关键词推断品类"""
    kw_lower = keyword.lower()
    for key, cat in _KEYWORD_CATEGORY_HINTS.items():
        if key in kw_lower:
            return cat
    return None


_PLANNED_POSITIVE_TERMS = {
    "fruit": ["水果", "果", "百果园", "果然", "生鲜", "鲜丰", "鲜果", "果品"],
    "market": ["生鲜", "菜场", "菜市场", "农贸", "超市", "便利店"],
    "japanese": ["日料", "日本料理", "寿司", "刺身", "鮨", "料理", "居酒屋", "丼", "拉面"],
    "meal": [
        "餐厅", "饭店", "小馆", "菜馆", "酒家", "食府", "面馆", "馄饨",
        "水饺", "砂锅", "米线", "盖饭", "简餐", "食堂", "料理", "拉面",
    ],
    "hair_service": ["理发", "美发", "美容美发", "发廊", "剪发", "造型", "发型", "发型设计", "洗剪吹", "烫发", "染发", "Barber", "barber", "Hair", "hair", "Salon", "salon"],
    "pharmacy": ["药店", "大药房", "医药", "药房"],
    "flower": ["花店", "鲜花", "花艺"],
    "cinema": ["电影院", "影院", "影城"],
}

_PLANNED_BLOCKED_TERMS = {
    "purchase": ["快印", "打印", "图文", "数码", "摄影", "照相", "复印", "广告", "文印", "印刷"],
    "meal_generic": ["星巴克", "瑞幸", "Manner", "manner", "咖啡", "Coffee", "coffee", "奶茶", "甜品", "面包", "茶饮"],
    "hair_service": [
        "收发室", "收发", "快递", "驿站", "菜鸟", "丰巢", "快递柜", "代收", "自提",
        "包裹", "物流", "货运", "配送", "派送", "邮政", "邮局",
        "打印", "快印", "复印", "图文", "数码快印",
        "维修", "开锁", "搬家", "洗衣", "房产", "中介", "通讯", "营业厅"
    ],
    "common": ["停车场", "停车楼", "公交站", "地铁站", "公厕", "卫生间", "入口", "出口", "充电桩", "ATM"],
}

def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _is_hair_service_intent(wp: PlannedWaypoint) -> bool:
    haystack = " ".join([
        getattr(wp, "name", "") or "",
        getattr(wp, "search_keyword", "") or "",
        " ".join(getattr(wp, "search_keywords", []) or []),
        " ".join(getattr(wp, "required_terms", []) or []),
    ])
    return _contains_any(haystack, _PLANNED_POSITIVE_TERMS.get("hair_service", []))


def _poi_distance_m(raw: dict[str, Any], center: dict | None) -> float:
    try:
        if raw.get("distance") not in (None, ""):
            return float(raw.get("distance") or 0)
    except (TypeError, ValueError):
        pass
    loc = raw.get("location")
    if isinstance(loc, str):
        try:
            lng, lat = loc.split(",", 1)
            loc = {"lng": float(lng), "lat": float(lat)}
        except Exception:
            loc = None
    if isinstance(loc, dict) and center:
        return haversine_km(loc, center) * 1000
    return 999999.0


async def _search_planned_keywords_for_radius(
    *,
    wp: PlannedWaypoint,
    current_center: dict,
    search_keywords: list[str],
    radius: int,
    search_radius: int,
    category_types: str,
    city: str,
) -> list[dict[str, Any]]:
    """Search keyword alternatives concurrently while preserving their priority.

    实际 QPS 仍由 api_client._gaode_rate_limit 全局控制。
    The first query that produces valid candidates wins; broad fallback terms
    must never replace an explicit user target merely because they are closer.
    """
    loc_str = coord_to_param(current_center)

    async def _one(search_keyword: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            results = await gaode_around_search(
                location=loc_str,
                keywords=search_keyword,
                radius=min(radius, search_radius),
                types=category_types,
                show_fields=config.GAODE_SHOW_FIELDS,
                offset=8,
                sortrule="distance",
                fallback_city=city,
                strict_nearby_fallback=True,
            )
            return search_keyword, results or []
        except Exception:
            return search_keyword, []

    for i in range(0, len(search_keywords), 3):
        batch = search_keywords[i:i + 3]
        batch_results = await asyncio.gather(*[_one(kw) for kw in batch])
        for query, results in batch_results:
            if results:
                print(
                    f"[PlannedSearchKeywordAudit] keyword={query} "
                    f"result_count={len(results)} "
                    f"top_names={[str(item.get('name', '')) for item in results[:3]]}"
                )
                return results

    return []


def _planned_semantic_score(
    wp: PlannedWaypoint,
    raw: dict[str, Any],
    center: dict | None,
) -> float | None:
    name = str(raw.get("name") or "")
    keyword = str(wp.search_keyword or wp.name or "")
    required_terms = list(getattr(wp, "required_terms", []) or [])
    excluded_terms = list(getattr(wp, "excluded_terms", []) or [])
    text = f"{name} {raw.get('type') or ''} {raw.get('typecode') or ''} {raw.get('address') or ''}"
    category = wp.category or "visit"

    if _contains_any(text, _PLANNED_BLOCKED_TERMS["common"]):
        return None
    if excluded_terms and _contains_any(text, excluded_terms):
        return None

    # A contract waypoint was explicitly requested by the user.  Its required
    # terms are therefore a filter, not merely a ranking bonus: this prevents
    # a closer unrelated restaurant/gym from replacing roast duck or a walk.
    if getattr(wp, "must_match_terms", False) and required_terms and not _contains_any(text, required_terms):
        return None

    score = 0.0
    if required_terms and _contains_any(text, required_terms):
        score += 10
    if category == "purchase":
        if _contains_any(text, _PLANNED_BLOCKED_TERMS["purchase"]):
            return None
        wants_fruit = _contains_any(keyword, ["水果", "果", "生鲜"])
        wants_pharmacy = _contains_any(keyword, ["药", "药店", "感冒"])
        wants_flower = _contains_any(keyword, ["花", "鲜花", "花束"])
        if wants_fruit:
            if not _contains_any(text, _PLANNED_POSITIVE_TERMS["fruit"]):
                return None
            score += 12
        elif wants_pharmacy:
            if _contains_any(text, _PLANNED_POSITIVE_TERMS["pharmacy"]):
                score += 10
        elif wants_flower:
            if _contains_any(text, _PLANNED_POSITIVE_TERMS["flower"]):
                score += 10
        elif _contains_any(text, _PLANNED_POSITIVE_TERMS["market"]):
            score += 8

    elif category == "service":
        wants_hair = _is_hair_service_intent(wp)

        if wants_hair:
            if _contains_any(text, _PLANNED_BLOCKED_TERMS.get("hair_service", [])):
                return None
            if not _contains_any(text, _PLANNED_POSITIVE_TERMS.get("hair_service", [])):
                return None
            score += 18
        else:
            if _contains_any(text, ["宠物", "培训", "学校"]):
                return None
            if _contains_any(text, _PLANNED_POSITIVE_TERMS.get("hair_service", [])):
                score += 8

    elif category == "meal":
        wants_cafe = _contains_any(keyword, ["咖啡", "奶茶", "下午茶", "甜品"])
        wants_japanese = _contains_any(keyword, ["日料", "寿司", "日本料理", "刺身"])
        if wants_japanese:
            if not _contains_any(text, _PLANNED_POSITIVE_TERMS["japanese"]):
                return None
            score += 14
        elif not wants_cafe:
            if _contains_any(text, _PLANNED_BLOCKED_TERMS["meal_generic"]):
                return None
            if _contains_any(text, _PLANNED_POSITIVE_TERMS["meal"]):
                score += 8
            else:
                score += 2

    elif category == "cafe":
        if _contains_any(text, ["咖啡", "Coffee", "coffee", "奶茶", "茶饮", "甜品", "星巴克", "瑞幸", "Manner", "manner"]):
            score += 10

    distance_m = _poi_distance_m(raw, center)
    score -= min(distance_m / 1000.0, 3.0)
    return score


def _safe_float_cost(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        text = (
            text.replace("¥", "")
            .replace("￥", "")
            .replace("元", "")
            .replace("/人", "")
            .replace("人均", "")
            .strip()
        )
        try:
            parsed = float(text)
            return parsed if parsed > 0 else None
        except ValueError:
            return None
    return None


def _raw_avg_cost(raw: dict[str, Any]) -> float | None:
    biz_ext = raw.get("biz_ext") or {}
    cost = None
    if isinstance(biz_ext, dict):
        cost = biz_ext.get("cost") or biz_ext.get("price")
    if cost is None:
        cost = raw.get("avg_cost") or raw.get("cost") or raw.get("price")
    return _safe_float_cost(cost)


def _budget_filter_raw_results(
    results: list[dict[str, Any]],
    budget_threshold: float | None,
) -> list[dict[str, Any]]:
    if budget_threshold is None or budget_threshold <= 0:
        return results
    filtered: list[dict[str, Any]] = []
    for item in results:
        avg_cost = _raw_avg_cost(item)
        if avg_cost is None or avg_cost <= budget_threshold:
            filtered.append(item)
    return filtered


def _rank_planned_results(
    wp: PlannedWaypoint,
    results: list[dict[str, Any]],
    center: dict | None,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, float, int, dict[str, Any]]] = []
    for idx, item in enumerate(results):
        score = _planned_semantic_score(wp, item, center)
        if score is None:
            continue
        ranked.append((score, _poi_distance_m(item, center), idx, item))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [item for _, _, _, item in ranked]


def _planned_search_keywords(wp: PlannedWaypoint) -> list[str]:
    keyword = (wp.search_keyword or wp.name or "").strip()
    llm_keywords = [
        kw.strip()
        for kw in (getattr(wp, "search_keywords", []) or [])
        if isinstance(kw, str) and kw.strip()
    ]
    if llm_keywords:
        if wp.category == "service" and _is_hair_service_intent(wp):
            preferred = ["理发店", "美发店", "美容美发", "发廊", "剪发", "发型设计"]
            ordered = [kw for kw in preferred if kw in llm_keywords]
            ordered += [kw for kw in llm_keywords if kw not in ordered]
            return list(dict.fromkeys(ordered[:3]))
        return list(dict.fromkeys(llm_keywords[:4]))
    if not keyword:
        return []
    if wp.category == "meal" and _contains_any(keyword, ["简餐", "餐厅", "晚饭", "晚餐"]):
        return list(dict.fromkeys([keyword, "餐厅", "小吃", "面馆", "快餐"]))
    if wp.category == "purchase" and _contains_any(keyword, ["水果", "果"]):
        return list(dict.fromkeys([keyword, "水果店", "生鲜超市"]))
    if wp.category == "service" and _contains_any(keyword, ["理发", "美发", "剪发", "发廊"]):
        return list(dict.fromkeys([keyword, "理发店", "美发店", "发廊"]))
    if wp.category == "purchase" and _contains_any(keyword, ["药", "药店"]):
        return list(dict.fromkeys([keyword, "药店", "大药房"]))
    if wp.category == "purchase" and _contains_any(keyword, ["花", "鲜花"]):
        return list(dict.fromkeys([keyword, "花店", "鲜花店"]))
    if wp.category == "visit" and _contains_any(keyword, ["电影", "影院"]):
        return list(dict.fromkeys([keyword, "电影院", "影院"]))
    return [keyword]


def _planned_recommend_reason(wp: PlannedWaypoint, poi_name: str) -> str:
    label = wp.search_keyword or wp.name or poi_name
    if wp.category == "purchase":
        return f"匹配理由：符合“{label}”的顺路采购需求；通勤成本：按当前位置附近优先筛选，适合下班途中短暂停留。"
    if wp.category == "meal":
        return f"匹配理由：符合“{label}”的用餐需求；通勤成本：按上一站附近递进搜索，减少绕路。"
    if wp.category == "cafe":
        return f"匹配理由：符合“{label}”的短休需求；通勤成本：优先选择附近可步行到达的门店。"
    if wp.category == "service":
        return f"匹配理由：符合“{label}”的生活服务需求；通勤成本：适合并入下班后的顺路链路。"
    return f"匹配理由：符合“{label}”的途经点需求；通勤成本：按路线顺序衔接。"


def _to_poi_dict(raw: dict[str, Any], target_index: int = -1, is_candidate: bool = False) -> dict[str, Any]:
    """将高德 POI raw 数据转换为标准 POI 字典（带完整信息）"""
    loc = raw.get("location")
    if isinstance(loc, str):
        parts = loc.split(",")
        loc = {"lng": float(parts[0]), "lat": float(parts[1])}

    lng = loc.get("lng", 0) if isinstance(loc, dict) else 0
    lat = loc.get("lat", 0) if isinstance(loc, dict) else 0

    # 处理 biz_ext 中的 cost — 统一使用标准解析
    avg_cost = _raw_avg_cost(raw)

    # 处理 photos
    photos = raw.get("photos") or []
    photo_url = ""
    if isinstance(photos, list) and len(photos) > 0:
        if isinstance(photos[0], dict):
            photo_url = photos[0].get("url", "")

    name = raw.get("name", "")
    typecode = raw.get("typecode", "")
    rating = raw.get("rating")

    return {
        "poi_id": raw.get("id") or raw.get("gaode_poi_id") or f"{name}:{lng},{lat}",
        "gaode_poi_id": raw.get("id") or raw.get("gaode_poi_id", ""),
        "name": name,
        "lat": lat,
        "lng": lng,
        "location": {"lat": lat, "lng": lng},
        "address": raw.get("address", ""),
        "typecode": typecode,
        "category": typecode,
        "rating": rating,
        "gaode_rating": rating,
        "avg_cost": avg_cost,
        "photo_url": photo_url,
        "photo_source": "gaode" if photo_url else "",
        "phone": raw.get("tel", ""),
        "is_candidate": is_candidate,
        "target_index": target_index,
    }


async def resolve_planned_waypoints_with_candidates(
    waypoints: list[PlannedWaypoint],
    start_location: dict,
    city: str = "上海",
    home_location: dict | None = None,
    budget_threshold: float | None = None,
    # v20: Search area context from area-category/proximity parsing
    search_area_location: dict | None = None,
    search_area_label: str = "",
) -> tuple[list[PlannedWaypoint], dict[int, list[dict[str, Any]]]]:
    """v6+v20: 递进解析 planned waypoints，每个 waypoint 返回主 POI + 候选 POI。

    v20 search center priority:
    1. search_area_location (from "朝阳区的商场" parsing)
    2. start_location (original/home)

    Args:
        start_location: 出发位置
        home_location: 用户的家地址
        search_area_location: 区域搜索中心（如"朝阳区"坐标）
        search_area_label: 搜索区域名称（日志用）

    Returns:
        (resolved_waypoints, candidate_map)
    """
    resolved = []
    candidate_map: dict[int, list[dict[str, Any]]] = {}

    # A clause-local waypoint reference takes precedence over the global
    # proximity area.  In multi-stop routes the global area must not become
    # the starting center for unrelated fixed visits.
    has_local_reference = any(getattr(wp, "search_center_name", None) for wp in waypoints)
    if search_area_location and search_area_location.get("lat") and not has_local_reference:
        current_center = search_area_location
        print(
            f"[DEBUG planned_search] search_center_source=search_area "
            f"label={search_area_label} "
            f"loc=({current_center.get('lat','')},{current_center.get('lng','')})"
        )
    else:
        current_center = start_location
        print(
            f"[DEBUG planned_search] search_center_source=start_location "
            f"loc=({current_center.get('lat','')},{current_center.get('lng','')})"
        )

    for idx, wp in enumerate(waypoints):
        wp_copy = PlannedWaypoint(
            type=wp.type,
            name=wp.name,
            search_keyword=wp.search_keyword,
            category=wp.category,
            stay_minutes=wp.stay_minutes,
            search_keywords=list(getattr(wp, "search_keywords", []) or []),
            required_terms=list(getattr(wp, "required_terms", []) or []),
            excluded_terms=list(getattr(wp, "excluded_terms", []) or []),
            search_center_name=getattr(wp, "search_center_name", None),
            search_center_location=getattr(wp, "search_center_location", None),
            time_slot=getattr(wp, "time_slot", None),
            must_match_terms=bool(getattr(wp, "must_match_terms", False)),
        )

        # Default recursion uses the previous selected waypoint.  A local
        # reference (X附近的Y) overrides the center for this waypoint only.
        waypoint_center = current_center
        if wp_copy.search_center_location and wp_copy.search_center_location.get("lat"):
            waypoint_center = wp_copy.search_center_location
        elif wp_copy.search_center_name:
            try:
                reference_results = await gaode_text_search(wp_copy.search_center_name, city=city)
                if reference_results:
                    reference_loc = reference_results[0].get("location")
                    if isinstance(reference_loc, str):
                        lng, lat = reference_loc.split(",", 1)
                        reference_loc = {"lng": float(lng), "lat": float(lat)}
                    if isinstance(reference_loc, dict) and reference_loc.get("lat") is not None:
                        wp_copy.search_center_location = reference_loc
                        waypoint_center = reference_loc
            except Exception as exc:
                print(
                    f"[WARNING planned_search] waypoint_reference_failed "
                    f"idx={idx} name={wp_copy.search_center_name} error={exc}"
                )
        if wp_copy.search_center_name:
            print(
                f"[DEBUG planned_search] idx={idx} "
                f"search_center_source=waypoint_reference "
                f"search_center_name={wp_copy.search_center_name} "
                f"loc=({waypoint_center.get('lat','')},{waypoint_center.get('lng','')})"
            )

        # 推断 category（如果原始未指定）
        if wp_copy.category == "visit" and wp_copy.search_keyword:
            inferred = _infer_category_from_keyword(wp_copy.search_keyword)
            if inferred:
                wp_copy.category = inferred

        cfg = _PLANNED_CATEGORY_CONFIG.get(wp_copy.category, _PLANNED_CATEGORY_CONFIG["visit"])
        category_types = cfg["types"]
        search_radius = cfg["radius"]

        main_poi = None
        candidates = []

        # home 类别：优先使用真实 home_location，不存在则降级为 start_location
        if wp_copy.category == "home":
            if home_location and home_location.get("lat") and home_location.get("lng"):
                home_loc = {
                    "lng": home_location.get("lng", 0),
                    "lat": home_location.get("lat", 0),
                }
                wp_copy.resolved_name = home_location.get("label") or wp_copy.name or "家"
                print(f"[DEBUG planned] home 使用真实 home_location: {home_loc}")
            else:
                # 降级：使用 start_location 作为兜底
                home_loc = {
                    "lng": start_location.get("lng", 0),
                    "lat": start_location.get("lat", 0),
                }
                wp_copy.resolved_name = wp_copy.name or "家"
                print(f"[WARNING planned] home_location 未配置，使用 start_location 兜底: {home_loc}")
            wp_copy.resolved_location = home_loc
            resolved.append(wp_copy)
            continue

        # 策略1：fixed 类型先精确名称搜索
        if wp_copy.type == "fixed" and wp_copy.name:
            try:
                results = await gaode_text_search(wp_copy.name, city=city)
                if results:
                    valid_results = []
                    for r in results:
                        r_name = r.get("name", "")
                        r_typecode = r.get("typecode", "")
                        if is_valid_route_poi(r_typecode, r_name, bypass_filter=True):
                            valid_results.append(r)

                    valid_results = _budget_filter_raw_results(valid_results, budget_threshold)
                    name_matched = [
                        item for item in valid_results
                        if _fixed_poi_name_matches(wp_copy.name, str(item.get("name") or ""))
                    ]

                    if name_matched:
                        main_poi = name_matched[0]
                        if len(name_matched) > 1:
                            candidates = name_matched[1:4]
                    elif valid_results:
                        print(
                            f"[PlannedFixedPoiAudit] rejected_unmatched_text_result "
                            f"requested={wp_copy.name} candidates={[str(item.get('name') or '') for item in valid_results[:3]]}"
                        )
            except Exception:
                pass

        # 策略2：around_search 找最近匹配（同半径关键词受限并发）
        keyword = wp_copy.search_keyword or wp_copy.name or ""
        search_keywords = _planned_search_keywords(wp_copy)
        search_started = time.monotonic()
        if not main_poi and search_keywords and search_radius > 0:
            for radius in _SEARCH_RADIUS_STEPS:
                try:
                    results = await _search_planned_keywords_for_radius(
                        wp=wp_copy,
                        current_center=waypoint_center,
                        search_keywords=search_keywords,
                        radius=radius,
                        search_radius=search_radius,
                        category_types=category_types,
                        city=city,
                    )
                    print(f"[DEBUG planned_search] idx={idx} keyword={keyword} radius={radius} keywords={search_keywords} results={len(results)} elapsed={time.monotonic() - search_started:.2f}s")
                    if results:
                        valid_results = []
                        for r in results:
                            r_name = r.get("name", "")
                            r_typecode = r.get("typecode", "")
                            if is_valid_route_poi(r_typecode, r_name, bypass_filter=True):
                                # 过滤名称黑名单（停车场等）
                                name_lower = r_name.lower()
                                blocked = any(kw.lower() in name_lower for kw in [
                                    "停车场", "停车楼", "公交站", "地铁站", "公厕", "卫生间",
                                    "入口", "出口", "充电桩", "ATM", "取款机",
                                ])
                                if not blocked:
                                    valid_results.append(r)

                        valid_results = _budget_filter_raw_results(valid_results, budget_threshold)
                        if valid_results:
                            ranked_results = _rank_planned_results(wp_copy, valid_results, waypoint_center)
                            if not ranked_results:
                                continue
                            main_poi = ranked_results[0]
                            # 候选：仅占位符/wander 类型且 >1 结果时提供
                            if wp_copy.type != "fixed" and len(ranked_results) > 1:
                                candidates = ranked_results[1:4]
                            break
                except Exception:
                    continue

        if main_poi:
            loc = main_poi.get("location")
            if isinstance(loc, str):
                parts = loc.split(",")
                loc = {"lng": float(parts[0]), "lat": float(parts[1])}
            wp_copy.resolved_location = loc
            wp_copy.resolved_name = main_poi.get("name", keyword)
            wp_copy.resolved_poi = _to_poi_dict(main_poi, target_index=idx, is_candidate=False)
            # 更新 stay_minutes
            if not wp_copy.stay_minutes or wp_copy.stay_minutes == 30:
                wp_copy.stay_minutes = cfg["stay"]
            current_center = loc

        # 收集候选
        if candidates:
            candidate_map[idx] = [
                _to_poi_dict(c, target_index=idx, is_candidate=True) for c in candidates
            ]

        resolved.append(wp_copy)

    return resolved, candidate_map


def build_planned_route_points_rich(
    waypoints: list[PlannedWaypoint],
    start_location: dict,
    start_name: str,
    day_index: int = 1,
    meal_label: str = "",
) -> list[dict[str, Any]]:
    """v6: 从解析后的 waypoints 构建带完整信息的 route_points。

    每个 POI 包含 id, name, lat, lng, address, typecode, category, rating,
    photo_url, display_slot, display_order, route_order, target_index, is_candidate=false
    """
    points: list[dict[str, Any]] = []
    start_lng = start_location.get("lng", 0)
    start_lat = start_location.get("lat", 0)

    # 起点
    points.append({
        "poi_id": f"start:{start_lng},{start_lat}",
        "gaode_poi_id": "",
        "name": start_name or "当前设备位置",
        "location": {"lat": start_lat, "lng": start_lng},
        "kind": "start",
        "day": day_index,
        "is_waypoint": True,
        "is_display_poi": False,  # start point
        "is_candidate": False,
        "is_start": True,
        "target_index": -1,
        "display_order": 0,
        "route_order": 0,
        "display_label": "起点",
        "plan_mode": "planned",
    })

    display_order = 1
    route_order = 1
    for idx, wp in enumerate(waypoints):
        if not wp.resolved_location:
            continue

        name = wp.resolved_name or wp.name or wp.search_keyword or "途经点"
        category = wp.category

        # kind 映射
        if category == "meal":
            kind = "meal"
        elif category in ("home",):
            kind = "visit"
        elif category in ("purchase",):
            kind = "visit"
        elif category in ("service",):
            kind = "visit"
        elif category in ("cafe",):
            kind = "meal"
        else:
            kind = "visit"

        # display_slot: only set when user intent has explicit time/meal slot.
        # In planned mode display_slot is a label only — it must not affect display order.
        # Do NOT default meal to "dinner" or home to "afternoon".
        explicit_slot = getattr(wp, "time_slot", "") or getattr(wp, "meal_slot", "") or ""
        display_slot = explicit_slot if explicit_slot in {"morning", "afternoon", "evening", "lunch", "dinner"} else ""

        # stay_minutes
        stay_minutes = wp.stay_minutes or _PLANNED_CATEGORY_CONFIG.get(category, {}).get("stay", 30)

        loc = wp.resolved_location
        lng = loc.get("lng", 0)
        lat = loc.get("lat", 0)
        resolved_poi = wp.resolved_poi or {}
        poi_id = resolved_poi.get("poi_id") or f"{name}:{lng},{lat}"

        point = {
            "poi_id": poi_id,
            "gaode_poi_id": resolved_poi.get("gaode_poi_id", poi_id),
            "name": name,
            "lat": lat,
            "lng": lng,
            "location": {"lat": lat, "lng": lng},
            "kind": kind,
            "day": day_index,
            "typecode": resolved_poi.get("typecode", ""),
            "category": category,
            "address": resolved_poi.get("address", ""),
            "rating": resolved_poi.get("rating"),
            "gaode_rating": resolved_poi.get("gaode_rating"),
            "avg_cost": resolved_poi.get("avg_cost"),
            "photo_url": resolved_poi.get("photo_url", ""),
            "photo_source": resolved_poi.get("photo_source", ""),
            "recommend_reason": _planned_recommend_reason(wp, name),
            "is_waypoint": True,
            "is_display_poi": True,
            "is_candidate": False,
            "target_index": idx,
            "target_label": wp.search_keyword or wp.name or "",
            "display_slot": display_slot,
            "display_order": display_order,
            "route_order": route_order,
            "stay_minutes": stay_minutes,
            "plan_mode": "planned",
        }
        points.append(point)
        display_order += 1
        route_order += 1

    return points


def build_planned_candidate_points(
    candidate_map: dict[int, list[dict[str, Any]]],
    waypoints: list[PlannedWaypoint],
    start_location: dict,
) -> list[dict[str, Any]]:
    """v6: 构建 candidate_points 列表。

    每个候选点包含完整前端弹窗所需信息。
    """
    candidate_points = []
    for target_idx, cands in candidate_map.items():
        wp = waypoints[target_idx] if target_idx < len(waypoints) else None
        target_label = wp.search_keyword if wp and wp.search_keyword else (wp.name if wp else "")
        category = wp.category if wp else "visit"

        for ci, cand in enumerate(cands):
            loc = cand.get("location", {})
            if isinstance(loc, str):
                parts = loc.split(",")
                loc = {"lng": float(parts[0]), "lat": float(parts[1])}
            lng = loc.get("lng", 0) if isinstance(loc, dict) else 0
            lat = loc.get("lat", 0) if isinstance(loc, dict) else 0

            # 距离计算
            start_lng_val = start_location.get("lng", 0)
            start_lat_val = start_location.get("lat", 0)
            distance_m = int(haversine_km(
                {"lat": lat, "lng": lng},
                {"lat": start_lat_val, "lng": start_lng_val},
            ) * 1000)

            candidate_points.append({
                "poi_id": cand.get("poi_id", f"cand_{target_idx}_{ci}"),
                "gaode_poi_id": cand.get("gaode_poi_id", ""),
                "name": cand.get("name", ""),
                "lat": lat,
                "lng": lng,
                "location": {"lat": lat, "lng": lng},
                "kind": "candidate",
                "is_waypoint": False,
                "is_display_poi": False,
                "day": 1,
                "typecode": cand.get("typecode", ""),
                "category": cand.get("category", cand.get("typecode", "")),
                "address": cand.get("address", ""),
                "rating": cand.get("rating"),
                "gaode_rating": cand.get("gaode_rating"),
                "avg_cost": cand.get("avg_cost"),
                "photo_url": cand.get("photo_url", ""),
                "photo_source": cand.get("photo_source", ""),
                "is_candidate": True,
                "source": "planned_candidate",
                "target_index": target_idx,
                "target_label": target_label,
                "display_slot": category if category in ("meal", "cafe") else "",
                "candidate_score": float(cand.get("rating") or 0),
                "distance": distance_m,
            })

    return candidate_points
