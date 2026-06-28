"""v4 先路后点架构核心模块。

提供:
  - generate_walk_backbone : 主路锚定 + waypoint 导航生成步行主干线 (M1)
  - search_pois_along_backbone : 按 road_segment 缓冲区并行搜POI (M2)
  - sort_pois_by_route_position : 沿主干线投影排序 (M3)
  - select_pois_by_time_budget : 时间预算贪心选取 (M3)
  - is_valid_route_poi : POI类型白/黑名单 (M4)
  - get_visit_duration : typecode→游览时长 (M5)
  - name_sub_anchors_by_direction : 方向命名 (M7)
  - assign_micro_pois_to_sub_anchor : bbox+走廊归属 (M7)
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

from . import config
from .api_client import (
    gaode_around_search,
    gaode_regeo_road,
    gaode_road_polyline,
    gaode_walking_route,
    gaode_walking_route_waypoints,
)
from .data_schema import SubAnchor



def _is_subordinate_poi(name: str) -> bool:
    """v5.2: 检测商场内下级POI（如"Shake Shack(国金中心店)"）。
    只筛掉名称中明确引用商业综合体的子店铺，保留街边独立店铺。
    
    判断逻辑：
    - 名称括号内含商业综合体关键词（商场/购物中心/广场/大厦/IFC等）→ 下级POI
    - 名称括号内含地址关键词（路/街/号/弄/巷）→ 街边店，保留
    - 其他 → 保留（宁可放过不可错杀）
    """
    import re
    if not name:
        return False
    # 提取括号内容
    bracket_match = re.search(r'[（(]([^）)]+)[）)]', name)
    if not bracket_match:
        # 无括号，检查是否以"XX店"结尾且前面有商业综合体特征
        # 如"老吉士上海ifc商场" → 这种名称不带括号但明显是商场内
        mall_keywords = ["商场", "购物中心", "购物广场", "商业广场", "综合体"]
        for kw in mall_keywords:
            if kw in name:
                return True
        return False
    
    bracket_content = bracket_match.group(1)
    
    # 括号内含地址关键词 → 街边店，保留
    address_keywords = ["路", "街", "号", "弄", "巷", "大道", "桥头", "路口", "地铁"]
    for kw in address_keywords:
        if kw in bracket_content:
            return False
    
    # 括号内含商业综合体关键词 → 商场内子店铺，过滤
    mall_keywords = [
        "商场", "购物中心", "购物广场", "商业广场", "综合体", "百货",
        "大厦", "大楼", "广场", "中心",  # "中心"需要结合上下文，但"国金中心""IFC"这种很明显
        "IFC", "ifc", "国金", "恒隆", "环贸", "嘉里", "来福士", "太古", "万象",
        "iapm", "K11", "k11", "静安嘉里", "SK", "龙湖", "银泰", "百联",
    ]
    for kw in mall_keywords:
        if kw in bracket_content:
            return True
    
    # 括号内是"XX店"格式，如"南京东路店"→保留，"国金中心店"→过滤
    if bracket_content.endswith("店"):
        # 检查"店"前面的内容是否含商业综合体关键词
        before_store = bracket_content[:-1]
        for kw in mall_keywords:
            if kw in before_store:
                return True
    
    return False

def is_valid_route_poi(
    typecode: str,
    name: str = "",
    skip_subordinate_check: bool = False,
    bypass_filter: bool = False,
    # v20: intent-based filtering replaces blanket 05/06 rejection
    explicit_meal_intent: bool = False,
    poi_query_type: str = "",
    allowed_shopping_prefixes: list[str] | None = None,
) -> bool:
    """v20: POI 是否允许进入游览路线。

    按用户意图控制：
    - 无明确餐饮意图时拒绝 05xxxx（餐饮服务）
    - 直接购物/服务查询时允许符合目标品类的 06xxxx
    - 游览主题路线时按白名单筛选

    skip_subordinate_check: 为True时跳过商场内子店铺过滤，用于POI不足时的补充放行。
    bypass_filter: 为True时绕过所有过滤（planned意图，用户明确指定的POI）。
    """
    if not typecode:
        return bypass_filter  # v5.2 r3: bypass时无typecode也放行
    tc = typecode.strip()

    # v5.2 r3: 用户明确指定的POI绕过所有过滤（planned意图）
    if bypass_filter:
        return True

    # ── 1. 名称兜底黑名单（停车场/学校/游泳馆等），最高优先级 ──
    if name:
        name_lower = name.lower()
        for kw in config.ROUTE_POI_NAME_BLACKLIST:
            if kw.lower() in name_lower:
                return False
        # ── 正餐名称关键词兜底（高德typecode误标时拦截）──
        for kw in config.ROUTE_POI_MEAL_NAME_KEYWORDS:
            if kw in name:
                return False

    # ── 2. Intent-based typecode filtering (v20: replaces blanket 05/06 block) ──
    # 05xxxx = 餐饮服务 (Gaode v3) — only allow when user explicitly wants meals
    # 06xxxx = 购物服务 (Gaode v3) — allow when user has direct shopping/service intent
    from .poi_typecodes import matches_typecode

    prefix2 = (tc[:2] + "0000") if len(tc) >= 2 else ""

    # v20: 05xxxx — reject unless explicit_meal_intent
    if matches_typecode(tc, ["05"]):
        if not explicit_meal_intent:
            return False

    # v20: 06xxxx — only allow when user has shopping/service POI intent
    if matches_typecode(tc, ["06"]):
        shop_query_types = {"poi_category", "named_poi", "purchase"}
        if poi_query_type in shop_query_types:
            if allowed_shopping_prefixes and matches_typecode(tc, allowed_shopping_prefixes):
                # Allowed shopping category — pass through to white/blacklist check
                pass
            elif not allowed_shopping_prefixes:
                # No specific shopping prefixes defined — use general white/blacklist
                pass
            else:
                # Has specific shopping prefixes but this POI doesn't match — reject
                return False
        else:
            # Not a shopping intent — reject 06xxxx
            return False

    # ── 3. 精确白名单（6位typecode精确匹配）──
    if tc in config.ROUTE_POI_ALLOWED_TYPES:
        if not skip_subordinate_check and name and _is_subordinate_poi(name):
            return False
        return True

    # ── 4. 白名单前缀匹配（4位子类，如080100→080000）──
    prefix4 = (tc[:4] + "00") if len(tc) >= 4 else ""
    if prefix4 in config.ROUTE_POI_ALLOWED_TYPES:
        if not skip_subordinate_check and name and _is_subordinate_poi(name):
            return False
        return True

    # ── 5. 通用黑名单 ──
    if tc in config.ROUTE_POI_EXCLUDED_TYPES or prefix2 in config.ROUTE_POI_EXCLUDED_TYPES:
        return False

    # ── 6. 不在白名单默认排除 ──
    return False

def get_visit_duration(typecode: str, name: str = "") -> int:
    """v4 M5 + v5.2: typecode → 预估游览时长（分钟）。沿途经过型POI只算5分钟。"""
    if not typecode:
        return config.TYPECODE_VISIT_DURATION["DEFAULT"]
    tc = typecode.strip()
    # v5.2: 沿途经过型POI（公园/广场/观景台）— 几乎不占停留时间
    if tc in config.ROUTE_POI_PASSTHROUGH_TYPES or (tc[:4] + "00") in config.ROUTE_POI_PASSTHROUGH_TYPES:
        return config.PASSTHROUGH_VISIT_DURATION_MIN
    if name:
        for kw in config.PASSTHROUGH_NAME_KEYWORDS:
            if kw in name:
                return config.PASSTHROUGH_VISIT_DURATION_MIN
    if tc in config.TYPECODE_VISIT_DURATION:
        return config.TYPECODE_VISIT_DURATION[tc]
    prefix = (tc[:2] + "0000") if len(tc) >= 2 else ""
    if prefix in config.TYPECODE_VISIT_DURATION:
        return config.TYPECODE_VISIT_DURATION[prefix]
    return config.TYPECODE_VISIT_DURATION["DEFAULT"]

def name_sub_anchors_by_direction(
    sub_anchors: list[SubAnchor],
    anchor_name: str = "",
) -> None:
    """v4 M7: 按sub-anchor质心方位命名（南/北/东/西段）。原地修改 sub_anchors。"""
    if len(sub_anchors) <= 1:
        return
    centroids: list[tuple[float, float]] = []
    for sub in sub_anchors:
        if sub.internal_pois:
            lats = [p["location"]["lat"] for p in sub.internal_pois if p.get("location")]
            lngs = [p["location"]["lng"] for p in sub.internal_pois if p.get("location")]
            if lats:
                centroids.append((sum(lats) / len(lats), sum(lngs) / len(lngs)))
                continue
        loc = sub.location or {}
        centroids.append((loc.get("lat", 0.0), loc.get("lng", 0.0)))

    parent = anchor_name or (sub_anchors[0].parent_name if sub_anchors else "")
    # 全锚点质心
    all_lat = sum(c[0] for c in centroids) / len(centroids)
    all_lng = sum(c[1] for c in centroids) / len(centroids)
    # 判断主分散方向
    lat_var = sum((c[0] - all_lat) ** 2 for c in centroids)
    lng_var = sum((c[1] - all_lng) ** 2 for c in centroids)

    for sub, (clat, clng) in zip(sub_anchors, centroids):
        if lat_var >= lng_var:
            suffix = "北段" if clat > all_lat else "南段"
        else:
            suffix = "东段" if clng > all_lng else "西段"
        sub.name = f"{parent}{suffix}" if parent else suffix
