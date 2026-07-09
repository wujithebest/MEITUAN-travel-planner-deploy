from __future__ import annotations
import asyncio
import math
import re
import sys
import os
from typing import Any

# 确保 backend 目录在 sys.path 最前面，解决跨目录 import 问题
_current_file = os.path.abspath(__file__)
_services_dir = os.path.dirname(_current_file)
_backend_dir = os.path.dirname(_services_dir)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from . import config
from .api_client import (
    bocha_search_batch,
    gaode_around_search,
    gaode_around_search_batch,
    gaode_driving_route,
    gaode_text_search,
    gaode_transit_route,
    gaode_walking_route,
    raw_to_place,
)
from .data_schema import AnchorPlan, CompletePlan, DayPlan, ExtractedPlace, FixedPoi, ParsedIntent, ScoredPlace, SearchCentralityItem, UserProfile
from .day_slots import DURATION_TO_BUDGET, MEAL_WINDOWS, WEATHER_PENALTY, infer_capacity_from_typecode
from .poi_feedback_service import calculate_feedback_score, get_profile_feedback_records
from .poi_relevance import recall_audit_log, score_poi_against_intent
from .poi_typecodes import matches_typecode, split_typecodes
from .route_backbone import is_valid_route_poi
from .theme_profile_matcher import get_theme_profile


# v20: Check if parsed_intent has a concrete POI target (named POI or registered category)
def _is_concrete_target(parsed_intent) -> bool:
    _ptype = getattr(parsed_intent, "poi_query_type", "") or ""
    _primary = getattr(parsed_intent, "primary_query", "") or ""
    _cat_id = getattr(parsed_intent, "category_id", None)
    _has_tc = bool(getattr(parsed_intent, "allowed_typecode_prefixes", None))
    if _ptype == "named_poi" and _primary:
        return True
    if _ptype == "poi_category" and _cat_id and _has_tc:
        return True
    return False


# v20: Build intent context kwargs for is_valid_route_poi from parsed_intent
def _is_valid_route_poi_ctx(typecode: str, name: str, parsed_intent, **extra) -> bool:
    """Call is_valid_route_poi with intent + theme context from parsed_intent."""
    _theme_id = getattr(parsed_intent, "theme_profile", None)
    _theme_terms = None
    _merged_typecodes = list(getattr(parsed_intent, "allowed_typecode_prefixes", None) or [])
    if _theme_id:
        _tp = get_theme_profile(_theme_id)
        _theme_terms = _tp.get("allowed_name_terms", None) if _tp else None
        # Merge theme typecodes with parsed_intent typecodes
        _theme_tc = _tp.get("allowed_typecode_prefixes", []) or [] if _tp else []
        for tc in _theme_tc:
            if tc not in _merged_typecodes:
                _merged_typecodes.append(tc)
    return is_valid_route_poi(
        typecode,
        name,
        poi_query_type=getattr(parsed_intent, "poi_query_type", "") or "",
        primary_query=getattr(parsed_intent, "primary_query", "") or "",
        category_id=getattr(parsed_intent, "category_id", None),
        allowed_typecode_prefixes=_merged_typecodes if _merged_typecodes else None,
        explicit_meal_intent=bool(getattr(parsed_intent, "explicit_meal_intent", False)),
        theme_id=_theme_id,
        theme_allowed_name_terms=_theme_terms,
        explicit_utility_intent=bool(getattr(parsed_intent, "utility_lookup_requested", False)),
        **extra,
    )
from .utils import ExternalAPIError, PipelineLogger, ZeroOutputError, capacity_budget, coord_to_param, emit_status, haversine_km
from .city_context import apply_resolved_city, resolve_departure_city
from .theme_profiles import OFFICIAL_THEME_PROFILES
try:
    from .theme_profile_matcher import (
        build_theme_recall_queries,
        canonicalize_search_keywords,
        score_poi_against_theme,
    )
except ImportError:
    from services.theme_profile_matcher import (
        build_theme_recall_queries,
        canonicalize_search_keywords,
        score_poi_against_theme,
    )


ANCHOR_LEVEL_TYPECODES = [
    "110000", "110100", "110200",
    "080500", "080600",
    "140100", "140200", "140300", "140400", "140500", "140600", "140700", "140900",
    "190100",
]

# ── v16: city 解析工具 — 不再信任前端手动 city ──
CITY_NAME_RE = re.compile(r"([一-龥]{2,12}市)")
DIRECT_MUNICIPALITIES = {"北京", "北京市", "上海", "上海市", "天津", "天津市", "重庆", "重庆市"}
CITY_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    "上海": (120.80, 122.20, 30.60, 31.90),
    "北京": (115.40, 117.60, 39.40, 41.10),
    "天津": (116.70, 118.10, 38.50, 40.30),
    "重庆": (105.20, 110.20, 28.10, 32.30),
}


def _normalize_city_name(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    text = str(value or "").strip()
    if not text:
        return ""
    if text in DIRECT_MUNICIPALITIES:
        return text if text.endswith("市") else f"{text}市"
    match = CITY_NAME_RE.search(text)
    if match:
        return match.group(1)
    if len(text) >= 2 and not text.endswith("市"):
        return f"{text}市"
    return text


def _city_short(city: str) -> str:
    city = _normalize_city_name(city)
    return city[:-1] if city.endswith("市") else city


def _in_city_bounds(city: str, location: dict | None) -> bool:
    short = _city_short(city)
    bounds = CITY_BOUNDS.get(short)
    if not bounds or not isinstance(location, dict):
        return False
    lng = location.get("lng")
    lat = location.get("lat")
    if lng is None or lat is None:
        return False
    min_lng, max_lng, min_lat, max_lat = bounds
    return min_lng <= float(lng) <= max_lng and min_lat <= float(lat) <= max_lat


async def _resolve_city_from_profile(user_profile: UserProfile) -> str:
    return await resolve_departure_city(user_profile)


def _apply_resolved_city(user_profile: UserProfile, city: str) -> None:
    apply_resolved_city(user_profile, city)

# 050500(餐饮) 已从基础白名单移除，仅在餐饮意图时通过 EATING_ANCHOR_TYPECODES 放行
ANIME_ANCHOR_TYPECODES = [
    *ANCHOR_LEVEL_TYPECODES,
    "060000",
    "060100",
    # 060400 便利店 removed — 不符合二次元打卡场景
    "060900",
    "061000",
]
EATING_ANCHOR_TYPECODES = [
    *ANCHOR_LEVEL_TYPECODES,
    "050000",   # 餐饮总类
    "050100",   # 中餐厅
    "050200",   # 外国餐厅
    "050300",   # 快餐
    "050301",   # 中式快餐（简餐主入口）
    "050302",   # 西式快餐（麦当劳肯德基）
    "050303",   # 日韩式快餐
    "050400",   # 休闲餐饮（咖啡奶茶）
    "050500",   # 烧烤夜宵
    "050900",   # 茶艺馆
    "051000",   # 糕饼店（面包）
    "060400",   # 便利店
    "060401",   # 超市
    "060402",   # 菜市场
]
OUTDOOR_TYPECODES = ["110000", "110100", "110200", "160100", "080500"]
INDOOR_TYPECODE_PREFIXES = ["060000", "060100", "060900", "061000", "080600", "140100", "140200"]
INDOOR_NAME_TERMS = [
    "室内",
    "博物馆",
    "美术馆",
    "展览",
    "展馆",
    "商场",
    "购物中心",
    "商业体",
    "综合体",
    "百货",
    "书店",
    "书屋",
    "剧院",
    "影院",
    "艺术中心",
    "文化馆",
]
OUTDOOR_NAME_TERMS = [
    "公园",
    "广场",
    "绿地",
    "滨江",
    "江边",
    "步道",
    "草坪",
    "湿地",
    "森林",
    "河畔",
    "露天",
    "风景区",
]
SPECIFIC_PREFERENCE_TERMS = {
    "二次元": ["二次元", "动漫", "ACG", "谷子", "手办", "潮玩", "卡牌", "一番赏", "周边", "漫展", "animate", "ZX"],
    "古街": ["古街", "老街", "古镇", "历史街区", "水乡"],
    "古镇": ["古街", "老街", "古镇", "历史街区", "水乡"],
}
CASUAL_NEARBY_BAD_TERMS = [
    "健康",
    "体检",
    "医疗",
    "诊所",
    "药房",
    "养生",
    "培训",
    "维修",
    "公司",
    "办公",
    "咖啡",
    "甜品",
    "蛋糕",
    "茶歇",
    "奶茶",
    "餐厅",
    "饭店",
    "小吃",
    "coffee",
    "cafe",
    "manner",
    "starbucks",
    "luckin",
    "库迪",
    "瑞幸",
    "星巴克",
]
SCENIC_BAD_TERMS = ["图文", "快印", "印刷", "标书", "锦旗", "广告", "招牌", "装订", "摄影工作室", "证件照"]
ALWAYS_BAD_TERMS = [
    "图文",
    "快印",
    "印刷",
    "标书",
    "锦旗",
    "广告",
    "招牌",
    "装订",
    "证件照",
    "摄影工作室",
    "照相馆",
    "冲印",
    "打印",
    "复印",
]
BAD_EXCERPT_TERMS = [
    "依法须经批准",
    "许可证",
    "经营项目",
    "查看地图",
    "注册资本",
    "企查查",
    "爱企查",
    "电话：",
    "地址：",
    "企业名称",
    "联系人",
    "注册日期",
    "在线联系",
    "展开 企业",
    "旅游攻略",
    "景点介绍",
    "途牛",
    "当地游",
    "<",
    ">",
    "_",
    "交通:",
    "交通：",
    "携程用户",
    "地图上",
    "天天好心情",
    "祝大家",
    "发表于",
    "评论",
    "2025",
    "2024",
    "已结束",
    "详见正文",
    "具体参加攻略",
    "可爱鼠",
    "还有很多",
    "关东煮",
    "烤饭团",
    "炸鸡",
]
GOOD_EXCERPT_TERMS = ["攻略", "快闪", "限定", "展", "活动", "主题", "周边", "谷子", "打卡", "观景", "夜景", "古镇", "老街", "门店", "旗舰"]
SHOPPING_INTENT_TERMS = ["逛商场", "商场", "购物", "买东西", "逛街", "商业体", "综合体", "商圈", "买手店", "潮牌"]
EATING_INTENT_TERMS = ["吃吃喝喝", "逛吃", "美食", "餐饮", "餐厅", "小吃", "探店", "咖啡", "甜品", "下午茶", "夜宵"]
SHOPPING_ANCHOR_TYPECODES = [
    *ANCHOR_LEVEL_TYPECODES,
    "060000",
    "060100",
    # 060200 综合市场 removed — 会搜出综合商店、小卖部等非购物中心结果
    # 060400 便利店 removed — 不符合"广场、商场、购物中心"预期
    "060900",
    "061000",
    "061100",
]


SHOPPING_BAD_TERMS = [
    "便利店",
    "小卖部",
    "食品店",
    "零售店",
    "综合商店",
    "烟酒",
    "日用百货",
    "五金",
    "建材",
    "药房",
    "诊所",
    "维修",
]

SHOPPING_BAD_FOOD_TERMS = [
    "咖啡",
    "coffee",
    "cafe",
    "甜品",
    "蛋糕",
    "茶歇",
    "奶茶",
    "星巴克",
    "瑞幸",
    "库迪",
    "manner",
    "starbucks",
    "luckin",
]


def _mismatches_shopping(place: ScoredPlace, parsed_intent: ParsedIntent) -> bool:
    if not _has_shopping_intent(parsed_intent):
        return False
    name = place.name
    typecode = (place.typecode or "")[:6]
    if typecode == "060400":
        return True
    text = f"{name} {place.enrichment_text}"
    if any(term in text for term in SHOPPING_BAD_TERMS):
        return True
    if not _has_eating_activity_intent(parsed_intent):
        if any(term in name for term in SHOPPING_BAD_FOOD_TERMS):
            return True
    return False


def _mismatches_always_bad(place: ScoredPlace, parsed_intent: ParsedIntent) -> bool:
    name = place.name
    return any(term in name for term in ALWAYS_BAD_TERMS)


def _intent_text(parsed_intent: ParsedIntent) -> str:
    parts = [
        *parsed_intent.raw_keywords,
        *parsed_intent.search_keywords,
        *parsed_intent.micro_keywords,
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


def _prefers_indoor(parsed_intent: ParsedIntent) -> bool:
    return "室内优先" in parsed_intent.other_constraints or "雨天" in parsed_intent.other_constraints


def _rainy_context(parsed_intent: ParsedIntent) -> bool:
    if "雨天" in parsed_intent.other_constraints:
        return True
    weather = str((parsed_intent.weather_info.get("day1") or {}).get("weather", ""))
    return any(term in weather for term in ["雨", "雪", "雷"])


def _is_indoor_place(place: ExtractedPlace) -> bool:
    prefix = (place.typecode or "")[:6]
    text = f"{place.name} {place.enrichment_text}".lower()
    return prefix in INDOOR_TYPECODE_PREFIXES or any(term.lower() in text for term in INDOOR_NAME_TERMS)


def _is_outdoor_place(place: ExtractedPlace) -> bool:
    prefix = (place.typecode or "")[:6]
    text = f"{place.name} {place.enrichment_text}".lower()
    if _is_indoor_place(place) and not any(term.lower() in text for term in OUTDOOR_NAME_TERMS):
        return False
    return prefix in OUTDOOR_TYPECODES or any(term.lower() in text for term in OUTDOOR_NAME_TERMS)


def _mismatches_rainy_indoor(place: ScoredPlace, parsed_intent: ParsedIntent) -> bool:
    if place.fixed:
        return False
    if not _rainy_context(parsed_intent):
        return False
    return _is_outdoor_place(place) and not _is_indoor_place(place)


def _type_allowed(typecode: str, allowed_typecodes: list[str] | None = None) -> bool:
    """v20: Parent-class matching for typecode whitelist.

    Each individual code from a composite typecode is checked:
    1. Exact 6-digit match in the whitelist → pass.
    2. Family (first 4 digits + "00") in the whitelist → pass.
       e.g. 110102 → family 110100; 110204 → family 110200.
    Does NOT do broad 2-digit prefix matching to avoid over-matching.
    """
    if not typecode:
        return False
    whitelist = allowed_typecodes or ANCHOR_LEVEL_TYPECODES
    from .poi_typecodes import split_typecodes
    codes = split_typecodes(typecode)
    for code in codes:
        code6 = code[:6] if len(code) >= 6 else code.ljust(6, "0")
        if code6 in whitelist:
            return True
        # Parent-class: e.g. 110102 → 110100
        if len(code6) >= 4:
            family = code6[:4] + "00"
            if family in whitelist:
                return True
    return False


def _is_nearby_request(parsed_intent: ParsedIntent) -> bool:
    return parsed_intent.time_budget <= 0.25 or any(
        keyword in {"附近", "逛逛", "附近逛逛"} for keyword in parsed_intent.raw_keywords
    ) or any(
        keyword in {"不走远", "近一点", "距离近"} for keyword in parsed_intent.other_constraints
    )


def _is_nearest_request(parsed_intent: ParsedIntent) -> bool:
    return "最近" in parsed_intent.raw_keywords or "最近" in parsed_intent.other_constraints


def _to_extracted(raw: dict[str, Any]) -> ExtractedPlace | None:
    try:
        data = raw_to_place(raw)
        return ExtractedPlace(**data)
    except Exception:
        return None


def _campus_canteen_university_name(parsed_intent: ParsedIntent) -> str:
    if (getattr(parsed_intent, "activity_facet", "") or "") != "campus_canteen_visit":
        return ""
    for fp in getattr(parsed_intent, "fixed_pois", []) or []:
        name = str(getattr(fp, "name", "") or "").strip()
        if name and ("大学" in name or name in ("北大", "清华", "人大")):
            return "北京大学" if name == "北大" else name
    for constraint in getattr(parsed_intent, "meal_constraints", []) or []:
        name = str(constraint.get("fixed_poi_name") or "").strip()
        if name and ("大学" in name or name in ("北大", "清华", "人大")):
            return "北京大学" if name == "北大" else name
    text = " ".join(
        list(getattr(parsed_intent, "search_keywords", []) or [])
        + list(getattr(parsed_intent, "micro_keywords", []) or [])
        + list(getattr(parsed_intent, "raw_keywords", []) or [])
    )
    if "北大" in text or "北京大学" in text:
        return "北京大学"
    if "清华" in text:
        return "清华大学"
    if "人大" in text:
        return "中国人民大学"
    return ""


def _dedupe_places(places: list[ExtractedPlace]) -> list[ExtractedPlace]:
    by_id: dict[str, ExtractedPlace] = {}
    for place in places:
        key = place.gaode_poi_id or place.name
        current = by_id.get(key)
        if current is None or (place.gaode_rating or 0) > (current.gaode_rating or 0):
            by_id[key] = place

    result: list[ExtractedPlace] = []
    for place in by_id.values():
        duplicate_index = None
        for index, existing in enumerate(result):
            if place.name in existing.name or existing.name in place.name:
                duplicate_index = index
                break
        if duplicate_index is None:
            result.append(place)
        elif (place.gaode_rating or 0) > (result[duplicate_index].gaode_rating or 0):
            result[duplicate_index] = place
    return result


def _budget_threshold(parsed_intent: ParsedIntent, user_profile: UserProfile) -> float:
    if parsed_intent.budget_per_capita is not None:
        return parsed_intent.budget_per_capita
    return user_profile.budget_per_capita * config.BUDGET_MULTIPLIER


def _budget_filter(places: list[ExtractedPlace], threshold: float) -> tuple[list[ExtractedPlace], list[str]]:
    kept: list[ExtractedPlace] = []
    deleted: list[str] = []
    for place in places:
        if place.avg_cost is not None and place.avg_cost > threshold:
            deleted.append(place.name)
        else:
            kept.append(place)
    return kept, deleted


def _preference_match(place: ExtractedPlace, parsed_intent: ParsedIntent) -> tuple[int, int, list[str]]:
    targets = [item for item in [*parsed_intent.raw_keywords, *parsed_intent.other_constraints] if item]
    if _has_shopping_intent(parsed_intent):
        targets.append("购物")
    if _has_eating_activity_intent(parsed_intent):
        targets.append("美食")
    if not targets:
        return 0, 1, []
    # Hard preference matching must use the POI's own identity. A web article
    # mentioning art near an unrelated POI must not make that POI "文艺".
    text = f"{place.name} {place.address} {place.typecode}"
    synonyms = {
        "古镇": ["老街", "水乡", "古街"],
        "古街": ["老街", "水乡", "古镇", "历史街区"],
        "二次元": ["动漫", "ACG", "谷子", "手办", "潮玩", "卡牌", "一番赏", "周边", "漫展", "animate", "ZX"],
        "文艺": ["艺术", "创意园", "书店", "咖啡"],
        "文艺优先": ["艺术", "创意园", "书店", "咖啡", "展览", "美术馆", "画廊", "文化空间"],
        "有氛围": ["艺术", "创意园", "书店", "展览", "美术馆", "画廊", "历史街区", "老街", "里弄", "弄堂", "文化"],
        "氛围优先": ["艺术", "创意园", "书店", "展览", "美术馆", "画廊", "历史街区", "老街", "里弄", "弄堂", "文化"],
        "精神漫游": ["艺术", "创意园", "书店", "展览", "美术馆", "历史街区", "老街", "里弄", "公园", "滨江"],
        "慢节奏": ["书店", "展览", "美术馆", "创意园", "历史街区", "老街", "里弄", "公园", "滨江"],
        "历史": ["博物馆", "旧址", "老建筑"],
        "拍照": ["打卡", "观景", "网红"],
        "逛吃": ["小吃", "美食", "夜市"],
        "购物": ["商场", "购物中心", "商圈", "商业体", "综合体", "逛街", "买手店", "潮牌"],
        "美食": ["餐厅", "饭店", "餐饮", "小吃", "探店", "美食"],
        "雨天": ["室内", "博物馆", "美术馆", "展览", "展馆", "商场", "购物中心", "书店", "剧院", "影院"],
        "室内优先": ["室内", "博物馆", "美术馆", "展览", "展馆", "商场", "购物中心", "书店", "剧院", "影院"],
    }
    matched = []
    for item in targets:
        if item in text or any(alias in text for alias in synonyms.get(item, [])):
            matched.append(item)
    return len(matched), max(len(targets), 1), matched


def _generic_anchor_mismatches_specific_preference(place: ScoredPlace, parsed_intent: ParsedIntent) -> bool:
    prefix = (place.typecode or "")[:6]
    if prefix not in {"110000", "110100", "110200"}:
        return False
    name = place.name.lower()
    for raw_keyword in parsed_intent.raw_keywords:
        terms = SPECIFIC_PREFERENCE_TERMS.get(raw_keyword, [])
        if terms and not any(term.lower() in name for term in terms):
            return True
    return False


def _mismatches_casual_nearby(place: ScoredPlace, parsed_intent: ParsedIntent) -> bool:
    if not any(keyword in {"附近", "逛逛", "附近逛逛"} for keyword in parsed_intent.raw_keywords):
        return False
    if (place.typecode or "").startswith("05") and not _has_eating_activity_intent(parsed_intent):
        return True
    text = f"{place.name} {place.enrichment_text}".lower()
    return any(term.lower() in text for term in CASUAL_NEARBY_BAD_TERMS)


def _mismatches_scenic_photo(place: ScoredPlace, parsed_intent: ParsedIntent) -> bool:
    scenic_intents = {"拍照", "拍照打卡", "夜景", "古街", "古镇"}
    if not any(keyword in scenic_intents for keyword in parsed_intent.raw_keywords):
        return False
    if (place.typecode or "").startswith("05"):
        return True
    scenic_bad_terms = [
        *SCENIC_BAD_TERMS,
        "咖啡",
        "coffee",
        "cafe",
        "甜品",
        "蛋糕",
        "奶茶",
        "餐厅",
        "饭店",
    ]
    return any(term.lower() in place.name.lower() for term in scenic_bad_terms)


def _mismatches_ancient_street(place: ScoredPlace, parsed_intent: ParsedIntent) -> bool:
    if not any(keyword in {"古街", "古镇"} for keyword in parsed_intent.raw_keywords):
        return False
    terms = SPECIFIC_PREFERENCE_TERMS["古街"]
    if any(term in place.name for term in terms):
        return False
    prefix = (place.typecode or "")[:6]
    if prefix in {"110000", "110100", "110200", "080500", "080600", "140100"}:
        return False
    clearly_modern = {"050000", "060000", "070000", "090000", "100000", "120000", "130000", "150000", "160000", "170000", "180000"}
    return prefix in clearly_modern


def _mismatches_anime_anchor(place: ScoredPlace, parsed_intent: ParsedIntent) -> bool:
    if "二次元" not in parsed_intent.raw_keywords:
        return False
    name = place.name.lower()
    if any(term in name for term in ["hair", "美发", "发型", "刺绣", "餐厅", "饭店", "菜馆", "面馆"]):
        return True
    strong_name_terms = [
        "二次元",
        "动漫",
        "acg",
        "谷子",
        "手办",
        "潮玩",
        "卡牌",
        "一番赏",
        "周边",
        "漫展",
        "animate",
        "zx",
        "造趣场",
        "百联",
        "寄售",
        "中古",
        "goods",
    ]
    if any(term in name for term in strong_name_terms):
        return False
    return any(term in name for term in ["咖啡", "coffee", "cafe", "茶", "甜品"])


def _anime_anchor_category(name: str) -> str:
    lowered = name.lower()
    if any(term in lowered for term in ["hair", "美发", "发型", "刺绣", "餐厅", "饭店", "菜馆", "面馆"]):
        return "bad"
    if any(term in lowered for term in ["寄售", "中古"]):
        return "consignment"
    if any(term in lowered for term in ["卡牌", "宝可梦", "对战", "hit"]):
        return "card"
    if any(term in lowered for term in ["手办", "潮玩", "模玩", "一番赏", "模型", "酷乐", "jin"]):
        return "figure"
    if "animate" in lowered:
        return "animate"
    if any(term in lowered for term in ["谷子", "goods", "二次元", "动漫", "acg", "zx", "造趣场", "百联", "萌购", "飞社长", "南漫社", "繁花谷"]):
        return "goods"
    return "generic"


def _diversify_anime_candidates(candidates: list[ScoredPlace], parsed_intent: ParsedIntent) -> list[ScoredPlace]:
    if "二次元" not in parsed_intent.raw_keywords:
        return candidates
    categories = ["goods", "card", "consignment", "figure", "animate"]
    selected: list[ScoredPlace] = []
    selected_ids: set[str] = set()
    for category in categories:
        for candidate in candidates:
            if candidate.gaode_poi_id in selected_ids:
                continue
            if _anime_anchor_category(candidate.name) == category:
                selected.append(candidate)
                selected_ids.add(candidate.gaode_poi_id)
                break
    for candidate in candidates:
        if candidate.gaode_poi_id in selected_ids:
            continue
        if _anime_anchor_category(candidate.name) == "bad":
            continue
        selected.append(candidate)
        selected_ids.add(candidate.gaode_poi_id)
    return selected


def _weather_penalty(place: ExtractedPlace, parsed_intent: ParsedIntent, fixed: bool = False) -> float:
    if fixed:
        return 1.0
    if not _is_outdoor_place(place):
        return 1.0
    weather = (parsed_intent.weather_info.get("day1") or {}).get("weather", "晴")
    penalty = WEATHER_PENALTY.get(weather, 1.0)
    if _rainy_context(parsed_intent):
        penalty = min(penalty, 0.25)
    return penalty


def _score_place(
    place: ExtractedPlace,
    parsed_intent: ParsedIntent,
    transit_min: float | None,
    fixed: bool = False,
    user_profile: UserProfile | None = None,
) -> ScoredPlace:
    rating = place.gaode_rating or 4.0
    rating_score = min(rating / 5.0, 1.0) * config.GAODE_RATING_WEIGHT

    # v15: 角色化距离惩罚 — destination_anchor用更弱距离惩罚
    poi_role = getattr(place, "poi_role", "") or "route_waypoint"
    effective_transit = transit_min or config.MAX_TRANSIT_MIN
    if poi_role == "destination_anchor":
        distance_factor = 0.45
    elif poi_role == "enroute_optional":
        distance_factor = 1.35
    else:
        distance_factor = 0.85
    transit_score = max(
        0.0,
        1.0 - (effective_transit * distance_factor) / config.MAX_TRANSIT_MIN
    ) * config.TRANSIT_SCORE_WEIGHT
    anchor_score = rating_score + transit_score

    matched, total, _ = _preference_match(place, parsed_intent)
    event_score = config.EVENT_SCORES.get(place.event_status, 0)
    heat_score = min(max(place.enrichment_heat, 0.0), 1.0) * config.HEAT_SCORE_WEIGHT
    preference_score = (matched / total) * config.PREFERENCE_SCORE_WEIGHT
    enrichment_score = event_score + heat_score + preference_score

    # Theme relevance is calculated once from the POI's own identity. Do not
    # stack source + role + a fixed theme score for regex-extracted names.
    recall_source = getattr(place, "recall_source", "") or ""
    theme_recall_score = float(getattr(place, "theme_recall_score", 0.0) or 0.0)
    theme_id = getattr(parsed_intent, "theme_profile", "") or ""
    theme_profile = OFFICIAL_THEME_PROFILES.get(theme_id, {})
    theme_evidence = score_poi_against_theme(place, theme_profile) if theme_profile else None
    if recall_source == "bocha_theme_recall":
        enrichment_score += min(max(theme_recall_score, 0.0), 30.0)
    elif theme_evidence and theme_evidence.accepted:
        enrichment_score += min(theme_evidence.score, 20.0)
    if poi_role == "destination_anchor" and recall_source != "bocha_theme_recall":
        enrichment_score += 12
    if theme_evidence and theme_evidence.generic_penalty_hits:
        enrichment_score -= 12.0 * len(theme_evidence.generic_penalty_hits)
    if "二次元" in parsed_intent.raw_keywords:
        name_text = place.name.lower()
        full_text = f"{place.name} {place.enrichment_text}".lower()
        anime_terms = [
            "二次元",
            "动漫",
            "acg",
            "谷子",
            "手办",
            "潮玩",
            "卡牌",
            "一番赏",
            "周边",
            "漫展",
            "animate",
            "zx",
            "造趣场",
            "百联",
            "寄售",
            "中古",
            "goods",
        ]
        name_strong = any(term in name_text for term in anime_terms)
        text_strong = any(term in full_text for term in anime_terms)
        if name_strong:
            enrichment_score += 20
        elif text_strong:
            enrichment_score += 6
        if any(term in name_text for term in ["咖啡", "coffee", "cafe"]) and not name_strong:
            enrichment_score -= 20
    if parsed_intent.raw_keywords and matched == 0:
        enrichment_score -= 25
    # 关键词相关性加分：POI名称与raw_keywords/search_keywords重叠度
    keyword_text = f"{place.name} {place.typecode or ''}"
    raw_hits = sum(1 for kw in parsed_intent.raw_keywords if kw in keyword_text)
    search_hits = sum(1 for kw in (parsed_intent.search_keywords or [])[:3] if any(t in keyword_text for t in kw.split()))
    keyword_bonus = raw_hits * 6 + search_hits * 3
    enrichment_score += keyword_bonus
    if _prefers_indoor(parsed_intent):
        if _is_indoor_place(place):
            enrichment_score += 22
        if _is_outdoor_place(place):
            enrichment_score -= 35
            if parsed_intent.time_budget <= 0.5:
                enrichment_score -= 15
    # 小众冷门 POI 在家庭场景下降分
    if parsed_intent.crowd_type == "家庭" and place.enrichment_heat < 0.3:
        enrichment_score -= 15
    if parsed_intent.crowd_type == "家庭" and place.enrichment_heat >= 0.6:
        enrichment_score += 8
    if fixed:
        enrichment_score += 30
    if _is_nearby_request(parsed_intent) and transit_min is not None:
        if transit_min > 45:
            enrichment_score -= 35
        elif transit_min > 30:
            enrichment_score -= 20
        elif transit_min <= 20:
            enrichment_score += 10
    feedback_score = 0.0
    if user_profile is not None:
        feedback_score = calculate_feedback_score(
            get_profile_feedback_records(user_profile),
            poi_id=place.gaode_poi_id,
            poi_name=place.name,
        )
        enrichment_score += feedback_score

    # v20: Lifestyle POI boost for full-day+ routes — increase dining/shopping/entertainment weight
    _time_budget = float(parsed_intent.time_budget or 0)
    _lifestyle_boost = 0.0
    if _time_budget > 0.5 and not fixed:
        _tc = (place.typecode or "")[:2]
        _has_lifestyle_terms = any(
            t in (place.name or "").lower() for t in [
                "餐厅", "饭店", "小吃", "咖啡", "甜品", "烘焙", "酒吧",
                "茶饮", "ktv", "桌游", "密室", "轰趴", "演出", "剧场",
                "购物", "商场", "买手", "集市", "影院",
            ]
        )
        # Type-based boost: dining 05, shopping 06, entertainment 08
        if _tc == "05" and _has_lifestyle_terms:
            _lifestyle_boost = 12.0 * min(_time_budget, 3.0) / 3.0
        elif _tc in ("05", "06", "08") and _has_lifestyle_terms:
            _lifestyle_boost = 8.0 * min(_time_budget, 3.0) / 3.0
        elif _tc == "05":
            _lifestyle_boost = 5.0 * min(_time_budget, 3.0) / 3.0

    # Disable boost if user explicitly rejected dining/entertainment
    _constraints_text = " ".join(parsed_intent.other_constraints or []).lower()
    if any(t in _constraints_text for t in ["不吃饭", "不看展", "纯景点", "只看", "不安排餐厅"]):
        _lifestyle_boost = 0.0
    if parsed_intent.explicit_meal_intent:
        _lifestyle_boost = max(_lifestyle_boost, 10.0)  # Stronger for explicit meal queries

    # v20: Mountain exclusion for pure waterfront walk requests
    _has_waterfront = any(
        "waterfront_walk" in (getattr(parsed_intent, "activity_facets", []) or [])
        for _ in [None]
    ) or "waterfront_walk" in str(getattr(parsed_intent, "activity_facets", []) or [])
    if _has_waterfront:
        _name_text = (place.name or "").lower()
        _has_mountain = any(t in _name_text for t in [
            "登山", "爬山", "山地", "浅山", "山谷", "山峰", "峡谷",
            "峪", "森林登山", "攀岩", "越野", "登顶", "山",
        ])
        if _has_mountain and not any(t in str(getattr(parsed_intent, "raw_keywords", []) or "") for t in ["登山", "山", "爬山", "登"]):
            enrichment_score -= 40  # Heavy penalty for mountain in pure waterfront request

    # v20: Transit time budget check for short-duration requests
    _tb = float(parsed_intent.time_budget or 0)
    if _tb <= 0.25 and transit_min is not None and transit_min > 45:
        enrichment_score -= 50
        print(f"[TravelBudgetAudit] duration=quarter_day candidate={place.name} transit_min={transit_min:.0f} max=45 accepted=false")
    elif _tb <= 0.5 and transit_min is not None and transit_min > 90:
        enrichment_score -= 40

    penalty = _weather_penalty(place, parsed_intent, fixed=fixed)
    final_score = (anchor_score + enrichment_score + _lifestyle_boost) * penalty

    return ScoredPlace(
        **place.model_dump(),
        anchor_score=round(anchor_score, 2),
        enrichment_score=round(enrichment_score, 2),
        weather_penalty=penalty,
        final_score=round(final_score, 2),
        fixed=fixed,
        final_capacity=place.time_capacity,
        transit_from_origin_min=transit_min,
    )


async def _route_from_origin(parsed_intent: ParsedIntent, place: ExtractedPlace, city: str) -> dict | None:
    origin = coord_to_param(parsed_intent.original_location)
    destination = coord_to_param(place.location)
    if not origin or not destination:
        return None
    distance = haversine_km(parsed_intent.original_location, place.location)
    if distance <= config.MEAL_MAX_ROUTE_KM:
        return await gaode_walking_route(origin, destination, require_polyline=False)
    try:
        if parsed_intent.transport_hint == "自驾":
            return await gaode_driving_route(origin, destination)
        return await gaode_transit_route(
            origin, destination, city=city, require_polyline=False,
            departure_time=parsed_intent.start_time,
        )
    except ExternalAPIError as exc:
        if "未返回可用路线" in str(exc):
            if distance <= 3.0:
                return await gaode_walking_route(origin, destination, require_polyline=False)
            # 远郊/岛屿目的地公交常无结果，尝试最少换乘策略（更容易匹配渡轮）
            try:
                return await gaode_transit_route(
                    origin, destination, city=city, strategy=2, require_polyline=False,
                    departure_time=parsed_intent.start_time,
                )
            except ExternalAPIError:
                pass
            try:
                return await gaode_driving_route(origin, destination)
            except ExternalAPIError:
                raise exc
        raise


async def _route_from_origin_bounded(
    parsed_intent: ParsedIntent,
    place: ExtractedPlace,
    city: str,
    timeout_seconds: float = 8.0,
) -> dict | None:
    """Bound route-API long tails and fall back to a distance estimate."""
    try:
        return await asyncio.wait_for(
            _route_from_origin(parsed_intent, place, city),
            timeout=timeout_seconds,
        )
    except (asyncio.TimeoutError, ExternalAPIError) as exc:
        origin = parsed_intent.original_location or {}
        distance = haversine_km(origin, place.location) if origin and place.location else 0.0
        estimated_minutes = max(5.0, distance * 4.0) if distance else None
        print(
            f"[WARN step2] route degraded name={place.name} distance_km={distance:.1f} "
            f"timeout={timeout_seconds}s reason={type(exc).__name__}"
        )
        return {
            "duration_min": estimated_minutes,
            "distance_km": distance,
            "degraded": True,
            "polyline_source": "haversine_estimate",
        }


def _clean_reason_text(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"\s+", " ", text).strip(" ，。；;")
    return text


def _enrichment_excerpt(place: ScoredPlace, parsed_intent: ParsedIntent) -> str:
    text = _clean_reason_text(place.enrichment_text)
    if not text:
        return ""
    terms = [place.name, *parsed_intent.raw_keywords, *parsed_intent.other_constraints, "攻略", "打卡", "活动", "展", "周边"]
    fragments = [
        re.sub(r"^[.。…》>xX\s·\-]+", "", item.strip(" ，。；;"))
        for item in re.split(r"[。；;！!？?\n]", text)
        if item.strip()
    ]
    for fragment in fragments:
        if any(term in fragment for term in BAD_EXCERPT_TERMS):
            continue
        if len(fragment) < 8:
            continue
        if not any(term in fragment for term in GOOD_EXCERPT_TERMS):
            continue
        if any(term and term in fragment for term in terms):
            return fragment[:64]
    for fragment in fragments:
        if (
            not any(term in fragment for term in BAD_EXCERPT_TERMS)
            and any(term in fragment for term in GOOD_EXCERPT_TERMS)
            and len(fragment) >= 8
        ):
            return fragment[:64]
    return ""


def _event_highlight(place: ScoredPlace) -> str:
    if not place.event_name:
        return ""
    if place.event_status == "ongoing":
        return f"近期有{place.event_name}正在进行中"
    if place.event_status != "uncertain":
        return ""
    text = f"{place.name} {place.enrichment_text}"
    if place.event_name != "主题活动":
        suffix = "" if place.event_name.endswith("活动") else "活动"
        return f"可能有{place.event_name}{suffix}"
    if any(token in text for token in ["快闪", "限定", "特展", "灯光秀", "市集", "展览"]):
        return "近期可能有快闪、特展或限定主题内容，适合出发前再确认档期"
    return ""


def _theme_highlight(place: ScoredPlace, parsed_intent: ParsedIntent) -> str:
    text = f"{place.name} {place.enrichment_text}".lower()
    name = place.name.lower()
    raw_keywords = set(parsed_intent.raw_keywords)
    if "二次元" in raw_keywords:
        if "谷子" in name and "咖啡" in name:
            return "谷子主题咖啡属性鲜明，适合把买周边、拍陈列和短休息合在一起"
        if any(token in name for token in ["寄售", "中古"]):
            return "偏寄售和中古谷子，适合淘绝版、补冷门角色或慢慢翻货"
        if any(token in name for token in ["卡牌", "对战"]):
            return "卡牌对战和交流属性更强，适合喜欢实物收藏与现场氛围的人"
        if "咖啡" in name and any(token in text for token in ["二次元", "动漫", "谷子", "周边", "ip", "限定", "主题"]):
            return "主题咖啡和休息属性明显，适合放在跨区行程中当补给点"
        if any(token in name for token in ["zx", "造趣场", "百联"]) or any(token in text for token in ["zx", "造趣场", "百联"]):
            return "核心商圈扫货属性强，适合集中逛谷子、IP主题店和快闪陈列"
        if any(token in text for token in ["寄售", "中古"]):
            return "偏寄售和中古谷子，适合淘绝版、补冷门角色或慢慢翻货"
        if any(token in text for token in ["卡牌", "对战"]):
            return "卡牌对战和交流属性更强，适合喜欢实物收藏与现场氛围的人"
        if any(token in text for token in ["谷子", "goods", "周边"]):
            return "谷子和周边属性明确，适合吃谷、补立牌徽章或顺手比价"
        if any(token in text for token in ["手办", "潮玩", "模型"]):
            return "手办、潮玩或模型属性更强，适合偏硬核收藏向的停留"
        if "咖啡" in text and any(token in text for token in ["二次元", "动漫", "谷子", "周边", "ip", "限定", "主题"]):
            return "主题咖啡和休息属性明显，适合放在跨区行程中当补给点"
        if any(token in name for token in ["动漫", "acg"]):
            return "动漫主题识别度高，适合作为二次元路线里的打卡节点"
    if any(token in text for token in ["黄浦江", "外滩", "观景", "码头", "金茂", "陆家嘴"]):
        if "黄浦江" in name:
            return "黄浦江游览能把外滩、十六铺码头和陆家嘴天际线串成一条夜景视线，适合压轴拍照"
        if "外滩" in name:
            return "万国建筑群和黄浦江岸线辨识度高，是外滩夜景与城市人像取景的核心位置"
        return "江景和城市天际线属性突出，适合安排拍照、夜景和观景段"
    if any(token in text for token in ["古镇", "老街", "水乡"]):
        if any(token in name for token in ["老街", "古街", "古镇"]):
            return "老街街巷和在地生活感更突出，适合慢慢看老建筑、街边小店和午餐前后的烟火气"
        return "街区游览属性强，适合慢逛、拍照和顺路找小吃"
    if any(token in raw_keywords for token in ["拍照", "夜景"]):
        return "打卡取景属性更强，适合把停留时间留给构图、等灯光和步行取景"
    if any(token in text for token in ["公园", "绿地", "散步"]):
        return "户外散步属性更强，适合附近短途放松和低强度转场"
    if any(token in text for token in ["书店", "书屋"]):
        return "书店停留属性明显，适合安静逛、翻书和短时休息"
    if any(token in text for token in ["甜品", "蛋糕", "茶歇"]):
        return "甜品补给属性明显，适合放在小半天路线后段收尾"
    if any(token in text for token in ["书店", "艺术", "展览", "创意"]):
        return "文艺和展览属性更突出，适合安排成低强度的室内体验"
    prefix = (place.typecode or "")[:6]
    if prefix in {"050500", "060100"}:
        return "商业配套密集，适合作为吃逛结合的中转点"
    if prefix in {"080500", "080600", "140100", "140200"}:
        return "室内文化体验属性较强，天气不稳定时也比较稳"
    return "作为行程锚点可串联周边小点，适合展开成一段完整游览"


def _play_hint(place: ScoredPlace, parsed_intent: ParsedIntent) -> str:
    text = f"{place.name} {place.enrichment_text}".lower()
    name = place.name.lower()
    raw_keywords = set(parsed_intent.raw_keywords)
    if "二次元" in raw_keywords:
        if "谷子" in name and "咖啡" in name:
            return "玩法建议：先看主题陈列和周边，再把它作为上午路线的轻休息点"
        if any(token in name for token in ["寄售", "中古"]):
            return "玩法建议：适合慢慢翻货，重点看寄售柜和角色专区"
        if any(token in name for token in ["卡牌", "对战"]):
            return "玩法建议：可以预留一点时间看现场对战、卡包或交换氛围"
        if "咖啡" in name and any(token in text for token in ["二次元", "动漫", "谷子", "周边", "ip", "限定", "主题"]):
            return "玩法建议：把它当休息点，顺手拍主题陈列或限定饮品"
        if any(token in text for token in ["zx", "百联", "造趣场"]):
            return "玩法建议：先逛高密度楼层，再把想买的周边回头集中结账"
        if any(token in text for token in ["寄售", "中古"]):
            return "玩法建议：适合慢慢翻货，重点看寄售柜和角色专区"
        if any(token in text for token in ["卡牌", "对战"]):
            return "玩法建议：可以预留一点时间看现场对战、卡包或交换氛围"
        if "咖啡" in text and any(token in text for token in ["二次元", "动漫", "谷子", "周边", "ip", "限定", "主题"]):
            return "玩法建议：把它当休息点，顺手拍主题陈列或限定饮品"
    if any(token in raw_keywords for token in ["拍照", "夜景"]):
        return "玩法建议：预留等灯光和换机位的时间，尽量避开纯赶路式打卡"
    if any(token in raw_keywords for token in ["古街", "古镇"]):
        return "玩法建议：按主街慢逛，再把午餐放在离最后一站步行可达的位置"
    if _is_nearby_request(parsed_intent):
        return "玩法建议：控制总步行强度，公园、书店或商场只选两三个点就好，中途再顺手找咖啡休息"
    return ""


def _capacity_hint(capacity: str) -> str:
    if capacity == "full_day":
        return "建议预留大半天到一天"
    if capacity == "half_day":
        return "建议预留2-3小时"
    return "建议预留45-90分钟"


def _transit_hint(minutes: float | None) -> str:
    if minutes is None:
        return ""
    if minutes <= 15:
        return "离出发地很近，适合做当天开场"
    if minutes <= 30:
        return "半小时内可达，适合和附近点位顺路串联"
    if minutes <= 45:
        return "通勤成本中等，建议作为半天核心点而不是临时加塞"
    return "通勤较长，更适合当作独立主题段来安排"


def _recommend_reason(place: ScoredPlace, parsed_intent: ParsedIntent) -> str:
    highlights: list[str] = []
    highlights.append(_theme_highlight(place, parsed_intent))
    event = _event_highlight(place)
    if event:
        highlights.append(event)

    signals: list[str] = []
    if place.enrichment_heat >= 0.7:
        signals.append("多个攻略平台都在推荐")
    elif place.enrichment_heat >= 0.4:
        signals.append("不少游客分享过")

    _, _, matched_tags = _preference_match(place, parsed_intent)
    if matched_tags:
        signals.append(f"命中{'、'.join(matched_tags)}偏好")

    if place.gaode_rating is not None and place.gaode_rating >= 4.5:
        signals.append(f"评分{place.gaode_rating:.1f}")
    elif place.gaode_rating is not None and place.gaode_rating >= 4.0:
        signals.append(f"评分{place.gaode_rating:.1f}")

    arrangement: list[str] = [_capacity_hint(place.final_capacity or place.time_capacity)]
    transit_hint = _transit_hint(place.transit_from_origin_min)
    if transit_hint:
        arrangement.append(transit_hint)
    if place.transit_from_origin_min is not None:
        arrangement.append(f"从出发地约{int(round(place.transit_from_origin_min))}分钟")

    if _prefers_indoor(parsed_intent) and _is_indoor_place(place):
        arrangement.append("下雨天更稳，适合作为室内半日核心点")
    elif 0.7 <= place.weather_penalty < 1.0:
        arrangement.append("天气可能有点影响，优先安排室内或可替代时段")

    excerpt = _enrichment_excerpt(place, parsed_intent)
    if excerpt:
        highlights.append(f"补充信息：{excerpt}")

    reason_parts = [f"核心看点：{'；'.join(highlights[:2])}"]
    if signals:
        reason_parts.append(f"匹配理由：{'，'.join(signals[:4])}")
    play_hint = _play_hint(place, parsed_intent)
    if play_hint:
        reason_parts.append(play_hint)
    reason_parts.append(f"安排建议：{'，'.join(arrangement[:3])}")
    return "；".join(reason_parts)


def _select_best_fixed_match(
    items: list[dict], target_name: str, city: str, city_short: str
) -> dict | None:
    """v20: Select the best match for a user-specified fixed POI.
    Priority: exact name match > normalized match > name overlap + park/scenic type > first result.
    All must be in the correct city.
    """
    if not items:
        return None

    target_lower = target_name.lower().strip()

    # Score each item
    scored = []
    for item in items:
        score = 0
        item_name = str(item.get("name", "") or "").strip()
        item_name_lower = item_name.lower()
        item_city = str(item.get("cityname", "") or item.get("city", "") or "")
        item_adname = str(item.get("adname", "") or "")
        item_typecode = str(item.get("typecode", "") or "")

        # City check: must be in Beijing (or target city)
        city_ok = (
            city in item_city or city_short in item_city
            or city in item_adname or city_short in item_adname
            or (not item_city and not item_adname)  # no city info → assume correct
        )
        if not city_ok:
            continue

        # Exact name match
        if item_name == target_name:
            score += 100
        elif item_name_lower == target_lower:
            score += 90
        # Normalized match (strip punctuation)
        norm_item = re.sub(r"[（(].*?[）)]", "", item_name).strip()
        norm_target = re.sub(r"[（(].*?[）)]", "", target_name).strip()
        if norm_item == norm_target:
            score += 80
        elif norm_item.lower() == norm_target.lower():
            score += 70
        # High character overlap
        item_chars = set(item_name_lower)
        target_chars = set(target_lower)
        overlap = len(item_chars & target_chars)
        if overlap >= max(len(target_chars) * 0.7, 2):
            score += 30

        # Type bonus: park/scenic/landmark
        if item_typecode.startswith("11"):
            score += 10

        scored.append((score, item))

    if not scored:
        return items[0] if items else None

    scored.sort(key=lambda x: -x[0])
    best_score, best_item = scored[0]

    if best_score >= 30:
        print(
            f"[DEBUG fixed_match] selected={best_item.get('name')} "
            f"score={best_score} candidates={[(s, i.get('name','')[:20]) for s, i in scored[:5]]}"
        )
        return best_item

    return None


def _extract_photo_from_raw(raw: dict) -> str:
    """Extract photo URL from raw Gaode result if available."""
    photos = raw.get("photos") or raw.get("photo") or []
    if isinstance(photos, list) and photos:
        first = photos[0]
        if isinstance(first, dict):
            return str(first.get("url", "") or "")
        return str(first)
    return ""


async def _fixed_anchors(parsed_intent: ParsedIntent, user_profile: UserProfile) -> list[AnchorPlan]:
    if not parsed_intent.fixed_pois:
        return []
    # v10: 过滤 delete_list 和别名
    delete_lowered = {d.lower() for d in (parsed_intent.delete_list or [])}
    area_lowered = {a.lower() for a in (getattr(parsed_intent, 'excluded_areas', []) or [])}
    all_excluded = delete_lowered | area_lowered
    # expand aliases
    from .step1_intent import EXCLUDE_ALIASES
    for poi_name in list(all_excluded):
        for alias in EXCLUDE_ALIASES.get(poi_name, []):
            all_excluded.add(alias.lower())

    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""

    # 对未查询过的FixedPoi进行高德搜索（v20: 城市限制精确匹配）
    fixed_pois = [fp for fp in parsed_intent.fixed_pois if fp.name.lower() not in all_excluded]
    city_short = city[:-1] if city.endswith("市") else city

    # v20: Enhanced search — city-limited, best-match selection, preserve real data
    to_search = [(i, fp) for i, fp in enumerate(fixed_pois) if not fp.location or not fp.typecode]
    if to_search:
        search_results = await asyncio.gather(*[
            gaode_text_search(fp.name, city=city) for _, fp in to_search
        ])
        for (idx, fp), items in zip(to_search, search_results):
            if not items:
                continue
            # v20: Select best match by name exactness, city match, type relevance
            best_item = _select_best_fixed_match(items, fp.name, city, city_short)
            if best_item:
                fp.location = fp.location or best_item.get("location")
                fp.typecode = fp.typecode or best_item.get("typecode", "")
                # v20: Preserve real Gaode POI data
                fp.gaode_poi_id = str(best_item.get("id", "") or best_item.get("uid", ""))
                fp.address = str(best_item.get("address", "") or "")
                fp.district = str(best_item.get("adname", "") or best_item.get("district", "") or "")
                _biz = best_item.get("biz_ext")
                _rating = best_item.get("rating")
                if _rating in (None, "") and isinstance(_biz, dict):
                    _rating = _biz.get("rating")
                try:
                    fp.poi_rating = float(_rating) if _rating not in (None, "") else None
                except (TypeError, ValueError):
                    fp.poi_rating = None
                fp.photo_url = _extract_photo_from_raw(best_item)
                print(
                    f"[FixedAnchorAudit] name={fp.name} "
                    f"gaode_poi_id={fp.gaode_poi_id} "
                    f"fixed=True explicit=True "
                    f"resolved=True "
                    f"typecode={fp.typecode} "
                    f"city={city}"
                )

    anchors: list[AnchorPlan] = []
    places: list[ExtractedPlace] = []
    for fp in fixed_pois:
        name = fp.name
        location = fp.location or parsed_intent.original_location or {}
        gaode_id = getattr(fp, "gaode_poi_id", "") or name
        raw = {
            "name": name,
            "typecode": fp.typecode or "110200",
            "location": location,
            "id": gaode_id,
            "address": getattr(fp, "address", "") or "",
            "district": getattr(fp, "district", "") or "",
        }
        extracted = _to_extracted(raw)
        if extracted:
            extracted.time_capacity = fp.resolved_time_budget or infer_capacity_from_typecode(extracted.typecode, extracted.name)
            # v20: Carry real POI data forward
            extracted.gaode_poi_id = gaode_id
            places.append(extracted)
    routes = await asyncio.gather(*[_route_from_origin(parsed_intent, place, city) for place in places])
    for place, route in zip(places, routes):
        transit = route.get("duration_min") if route else None
        scored = _score_place(place, parsed_intent, transit, fixed=True, user_profile=user_profile)
        effective_capacity = _effective_capacity_for_request(scored.final_capacity or scored.time_capacity, parsed_intent, is_fixed=True)
        data = scored.model_dump()
        data["final_capacity"] = effective_capacity
        data.pop("fixed", None)  # v20: prevent duplicate kwarg clash with AnchorPlan.fixed
        reason_place = scored.model_copy(update={"final_capacity": effective_capacity})
        reason = _recommend_reason(reason_place, parsed_intent)
        time_budget = fp.resolved_time_budget or effective_capacity or place.time_capacity or "half_day"
        anchors.append(
            AnchorPlan(
                **data,
                final_time_budget=time_budget,
                recommend_reason=reason,
                origin_transit=f"从出发点约{int(transit or 0)}分钟",
                fixed=True,
            )
        )
    return anchors


async def _search_macro_places(parsed_intent: ParsedIntent, central_locations: list[dict[str, Any]] | None = None) -> list[ExtractedPlace]:
    if _is_nearby_request(parsed_intent):
        radius = config.GAODE_RADIUS_NEARBY
    else:
        radius = config.GAODE_RADIUS_CASE_C_SHORT if parsed_intent.time_budget <= 0.5 else config.GAODE_RADIUS_CASE_C_LONG
    locations = central_locations or [parsed_intent.original_location]
    # v6: 强餐饮意图检测
    strong_meal = _has_strong_meal_intent(parsed_intent)

    # v20: Use intent typecodes for poi_category/named_poi queries
    _poi_qtype = getattr(parsed_intent, "poi_query_type", "") or ""
    _intent_typecodes = getattr(parsed_intent, "allowed_typecode_prefixes", []) or []
    if _poi_qtype in ("poi_category", "named_poi") and _intent_typecodes:
        # Use the exact typecodes from the category rule
        allowed_types = list(_intent_typecodes)
        # Include wide fallback so we don't miss relevant results
        from .poi_typecodes import CATEGORY_RULES
        _cat_id = getattr(parsed_intent, "primary_query", "") or ""
        for cid, rule in CATEGORY_RULES.items():
            for term in rule.get("semantic_terms", []):
                if term.lower() in _cat_id.lower():
                    for wf in rule.get("wide_fallback", []):
                        if wf not in allowed_types:
                            allowed_types.append(wf)
                    break
            if allowed_types != _intent_typecodes:
                break
        print(
            f"[DEBUG macro search] using intent typecodes: "
            f"intent={_intent_typecodes} full={allowed_types}"
        )
    elif "二次元" in parsed_intent.raw_keywords:
        allowed_types = ANIME_ANCHOR_TYPECODES
    else:
        allowed_types = list(ANCHOR_LEVEL_TYPECODES)
        # v20: Merge theme-specific typecodes when theme_route is active
        _theme_id = getattr(parsed_intent, "theme_profile", None)
        if _theme_id:
            _theme_profile_data = get_theme_profile(_theme_id)
            _theme_tc = _theme_profile_data.get("allowed_typecode_prefixes", []) or []
            if _theme_tc:
                for tc in _theme_tc:
                    if tc not in allowed_types:
                        allowed_types.append(tc)
                print(
                    f"[DEBUG macro search] merged theme typecodes for {_theme_id}: "
                    f"{_theme_tc} -> total allowed={len(allowed_types)}"
                )
        # v20: Lifestyle POI boost for full-day+ routes — expand typecodes for dining/shopping/entertainment
        _tb = float(parsed_intent.time_budget or 0)
        if _tb > 0.5:
            _lifestyle_tc = ["050000", "050500", "060100", "060900", "080300", "080500"]
            for _ltc in _lifestyle_tc:
                if _ltc not in allowed_types:
                    allowed_types.append(_ltc)
            print(f"[DEBUG macro search] lifestyle boost: time_budget={_tb:.1f} added_typecodes={_lifestyle_tc}")
        if _has_shopping_intent(parsed_intent):
            allowed_types.extend(["060000", "060100", "060900", "061000", "061100"])
        if _has_eating_activity_intent(parsed_intent) or strong_meal:
            allowed_types.append("050500")
        # v6: 强餐饮意图 — 加入餐饮大类和日料相关 typecode
        if strong_meal:
            allowed_types.extend(["050000", "050100", "050200", "050300"])
        # v20: Quiet retreat — expand typecodes for libraries, bookstores, cafes, tea houses, parks
        if getattr(parsed_intent, "quiet_retreat_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "quiet_retreat":
            _quiet_tc = [
                "061205",  # 书店
                "060900",  # 文化用品/文化空间
                "050400",  # 休闲餐饮 (咖啡馆)
                "050900",  # 茶艺馆
                "060100",  # 购物中心 (书店/文化空间可能在商场内)
                "061000",  # 综合文化场所
            ]
            for _qtc in _quiet_tc:
                if _qtc not in allowed_types:
                    allowed_types.append(_qtc)
            print(f"[DEBUG macro search] quiet_retreat typecodes added: {_quiet_tc}")
        # v21: Lawn rest — expand typecodes for parks, green spaces, gardens
        if getattr(parsed_intent, "lawn_rest_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "lawn_rest":
            _lawn_tc = [
                "110100",  # 公园
                "110101",  # 城市公园
                "110200",  # 景点/景区 (可能含绿地)
                "110000",  # 风景名胜
            ]
            for _ltc in _lawn_tc:
                if _ltc not in allowed_types:
                    allowed_types.append(_ltc)
            print(f"[DEBUG macro search] lawn_rest typecodes added: {_lawn_tc}")
        # v21: Local life / market — expand typecodes for markets, community streets, old streets
        if getattr(parsed_intent, "local_life_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "local_life":
            _local_tc = [
                "061200",  # 综合市场
                "061100",  # 花鸟鱼虫市场
                "060202",  # 农贸市场/菜市场
                "060201",  # 便利店/便民店
                "060400",  # 文化用品/书店 (用于识别老街/社区商业街)
                "110200",  # 景点/老街
            ]
            for _ltc in _local_tc:
                if _ltc not in allowed_types:
                    allowed_types.append(_ltc)
            print(f"[DEBUG macro search] local_life typecodes added: {_local_tc}")
        # v21: Souvenir shopping — expand typecodes for gift/specialty stores
        if getattr(parsed_intent, "souvenir_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "souvenir_shopping":
            _souv_tc = [
                "060000", "060100", "060400", "060900", "061000", "061100",
                "061200",  # 综合市场 / 特产
            ]
            for _stc in _souv_tc:
                if _stc not in allowed_types:
                    allowed_types.append(_stc)
            print(f"[DEBUG macro search] souvenir typecodes added: {_souv_tc}")
        # v21: Fruit picking — expand typecodes for agritourism/farm
        if getattr(parsed_intent, "fruit_picking_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "fruit_picking_combo":
            _farm_tc = [
                "080503",  # 采摘园/农业观光
                "110103",  # 农业观光园
                "110000", "110100", "110200",  # 景区/公园 (for combo)
            ]
            for _ftc in _farm_tc:
                if _ftc not in allowed_types:
                    allowed_types.append(_ftc)
            print(f"[DEBUG macro search] fruit_picking typecodes added: {_farm_tc}")
        # v21: No-reservation flexible trip — open streets, parks, public
        # spaces and low-reservation-risk cultural venues.
        if (getattr(parsed_intent, "activity_facet", "") or "") == "no_reservation_flexible_trip":
            _no_res_tc = [
                "110000", "110100", "110101", "110105", "110200", "110209", "110210",
                "060100", "061000", "061200",
                "140100", "140200", "140300", "140400", "140500",
            ]
            for _ntc in _no_res_tc:
                if _ntc not in allowed_types:
                    allowed_types.append(_ntc)
            print(f"[DEBUG macro search] no_reservation typecodes added: {_no_res_tc}")
        # v21: Rain shelter — expand typecodes for indoor public spaces
        if getattr(parsed_intent, "rain_shelter_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "rain_shelter":
            _rain_tc = [
                "060100",  # 购物中心/商场
                "050400",  # 咖啡馆
                "050900",  # 茶馆
                "061205",  # 书店
                "140100",  # 博物馆
                "140200",  # 展览馆
                "140300",  # 文化宫
                "140500",  # 图书馆
                "080600",  # 美术馆
                "050300",  # 快餐
                "060200",  # 便利店
            ]
            for _rtc in _rain_tc:
                if _rtc not in allowed_types:
                    allowed_types.append(_rtc)
            print(f"[DEBUG macro search] rain_shelter typecodes added: {_rain_tc}")
        # v21: Rest stop — expand typecodes for cafes, tea houses, bookstores, parks
        if getattr(parsed_intent, "rest_stop_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "rest_stop":
            _rest_tc = [
                "050400",   # 咖啡馆
                "050900",   # 茶馆
                "061205",   # 书店
                "050100",   # 中餐厅 (茶馆)
                "110100", "110101",  # 公园
                "060100",   # 购物中心 (休息区)
                "140500",   # 图书馆
            ]
            for _rtc in _rest_tc:
                if _rtc not in allowed_types:
                    allowed_types.append(_rtc)
            print(f"[DEBUG macro search] rest_stop typecodes added: {_rest_tc}")
        # v21: Stress relief — expand typecodes for all activity categories
        if getattr(parsed_intent, "stress_relief_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "stress_relief":
            _stress_tc = [
                "110100", "110101",  # 公园
                "110200",            # 景点
                "061205",            # 书店
                "050400",            # 咖啡馆
                "140600",            # 科技馆
                "080100",            # 运动场馆
                "080300",            # 娱乐场所 (KTV/游戏厅)
                "080500", "080600",  # 展览馆/美术馆
                "060100",            # 购物中心 (手工坊常在商场内)
            ]
            for _stc in _stress_tc:
                if _stc not in allowed_types:
                    allowed_types.append(_stc)
            print(f"[DEBUG macro search] stress_relief typecodes added: {_stress_tc}")
        # v21: Open terrace — expand typecodes for cafes, restaurants, bars, hotels, malls
        if getattr(parsed_intent, "open_terrace_requested", False) or (getattr(parsed_intent, "activity_facet", "") or "") == "open_terrace":
            _terrace_tc = [
                "050400",  # 休闲餐饮 (咖啡馆 — 常有露台)
                "050100",  # 中餐厅 (可能含露台)
                "050200",  # 外国餐厅
                "050900",  # 茶艺馆
                "060100",  # 购物中心 (屋顶花园/露台)
                "080304",  # 酒吧 (露台酒吧)
                "100000",  # 酒店 (可能有露台/rooftop bar)
                "110200",  # 景点 (观景露台)
            ]
            for _ttc in _terrace_tc:
                if _ttc not in allowed_types:
                    allowed_types.append(_ttc)
            print(f"[DEBUG macro search] open_terrace typecodes added: {_terrace_tc}")
    # v21: Multi-day optimization — reduce keyword limit for scoped recall
    _is_multi_day_opt = getattr(parsed_intent, "optimization_profile", "") == "multi_day_fixed_anchor_enhanced"
    keyword_limit = 8 if ("二次元" in parsed_intent.raw_keywords or _has_shopping_intent(parsed_intent)) else (
        3 if _is_multi_day_opt else 5
    )

    # v6: 强餐饮意图时, meal_search_keywords 优先作为锚点搜索关键词
    search_kws = list(parsed_intent.search_keywords[:keyword_limit])
    if strong_meal:
        meal_kws = getattr(parsed_intent, "meal_search_keywords", []) or []
        for mk in meal_kws:
            if mk not in search_kws:
                search_kws.insert(0, mk)  # 优先插入到最前面
    elif len(search_kws) < 2:
        meal_kws = getattr(parsed_intent, "meal_search_keywords", []) or []
        for mk in meal_kws:
            if mk not in search_kws:
                search_kws.append(mk)
            if len(search_kws) >= keyword_limit:
                break

    requests = [
        {
            "location": coord_to_param(location),
            "keywords": keyword,
            "radius": radius,
            "types": "|".join(allowed_types),
            "show_fields": config.GAODE_SHOW_FIELDS,
            "offset": 20,
        }
        for location in locations
        for keyword in search_kws
    ]
    results = await gaode_around_search_batch(requests)
    places = [_to_extracted(raw) for group in results for raw in group]
    raw_count = len(places)

    # v20: category validation for poi_category queries
    if _poi_qtype in ("poi_category", "named_poi") and _intent_typecodes:
        from .poi_typecodes import validate_poi_category
        _cat_id = getattr(parsed_intent, "primary_query", "") or ""
        inferred_cat = None
        for cid in CATEGORY_RULES:
            if cid == "restaurant":
                continue
            for term in CATEGORY_RULES[cid].get("semantic_terms", []):
                if term.lower() in _cat_id.lower():
                    inferred_cat = cid
                    break
            if inferred_cat:
                break

        category_passed: list = []
        category_rejected: list = []
        for place in places:
            if not place or not place.typecode:
                continue
            if inferred_cat:
                ok, _ = validate_poi_category(
                    {"name": place.name, "typecode": place.typecode, "category": getattr(place, "category", "") or ""},
                    inferred_cat,
                )
                if ok:
                    category_passed.append(place)
                else:
                    category_rejected.append((place.name, place.typecode))
            else:
                category_passed.append(place)

        print(
            f"[DEBUG macro search] raw_count={raw_count} "
            f"category_pass={len(category_passed)} category_reject={len(category_rejected)} "
            f"rejected=[{', '.join(f'{n}({t})' for n, t in category_rejected[:8])}]"
        )
        return category_passed

    # v4.1 F1/F2: 宏观搜索也应用 POI 名称过滤（拦截餐厅/停车场等）
    filtered = [
        place for place in places
        if place
        and _type_allowed(place.typecode, allowed_types)
        and _is_valid_route_poi_ctx(place.typecode, place.name, parsed_intent)
    ]
    print(
        f"[DEBUG macro search] raw_count={raw_count} deduped={len(filtered)} "
        f"passed_types_count={len([p for p in places if p and _type_allowed(p.typecode, allowed_types)])} "
    )
    return filtered


# v20: District-level filtering utilities
def _place_matches_district_raw(place, district_label: str, search_adcode: str = "") -> bool:
    """Check if an ExtractedPlace belongs to the target district."""
    if not district_label:
        return True
    # Primary: adname match (require non-empty adname to avoid "" in "海淀区")
    adname = str(getattr(place, "district", "") or "").strip()
    if adname and (district_label in adname or adname in district_label):
        return True
    # Secondary: address contains district
    addr = str(getattr(place, "address", "") or "").strip()
    if addr and district_label in addr:
        return True
    # Tertiary: adcode match (use [:6] not [:4] to avoid matching all Beijing districts)
    adcode = str(getattr(place, "adcode", "") or "")
    if search_adcode and adcode and len(adcode) >= 6 and len(search_adcode) >= 6:
        if adcode[:6] == search_adcode[:6]:
            return True
    return False


async def _theme_recall_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
    city: str,
) -> list[ExtractedPlace]:
    """v15: Bocha主题召回 — 从博查攻略语义中抽取主题片区/POI名称，高德校准后加入候选池"""
    theme_id = getattr(parsed_intent, "theme_profile", None)
    if not theme_id or theme_id not in OFFICIAL_THEME_PROFILES:
        return []
    profile = OFFICIAL_THEME_PROFILES[theme_id]
    # Always build city-scoped queries from generic profile terms. Legacy
    # recall_queries may contain concrete POIs from a different city.
    recall_queries = build_theme_recall_queries(profile, city, limit=3)
    if not recall_queries:
        return []

    city = _normalize_city_name(city) or await _resolve_city_from_profile(user_profile)
    city_short = _city_short(city)
    dest_terms = list(dict.fromkeys(profile.get("destination_anchor_terms", []) or []))

    # v20: District-level filtering
    _search_area_label = str(getattr(parsed_intent, "search_area_label", "") or "")
    _is_district = bool(re.search(
        r"(?:区|县|镇|乡|街道|商圈|片区|新城|新区)$", _search_area_label
    ))
    _search_area_adcode = getattr(parsed_intent, "search_area_adcode", None)
    _search_area_polygon = None  # lazy-load if needed

    def _place_matches_district(raw: dict, place) -> bool:
        """Check if a candidate belongs to the requested administrative district."""
        if not _is_district or not _search_area_label:
            return True  # no district constraint
        # Check adname (require non-empty to avoid "" in "海淀区")
        ad = str(raw.get("adname") or raw.get("district") or "").strip()
        if ad and (_search_area_label in ad or ad in _search_area_label):
            return True
        # Check address
        addr = str(raw.get("address") or "").strip()
        if addr and _search_area_label in addr:
            return True
        # Check adcode (use [:6] to avoid matching all districts within same city)
        raw_adcode = str(raw.get("adcode") or "")
        if (
            _search_area_adcode and raw_adcode
            and len(raw_adcode) >= 6 and len(str(_search_area_adcode)) >= 6
            and raw_adcode[:6] == str(_search_area_adcode)[:6]
        ):
            return True
        return False

    def _place_matches_city(raw: dict, place) -> bool:
        if not city_short:
            return True

        cn = str(raw.get("cityname") or raw.get("city") or "")
        pn = str(raw.get("pname") or raw.get("province") or "")
        ad = str(raw.get("adname") or "")
        addr = str(raw.get("address") or "")
        name_t = str(raw.get("name") or getattr(place, "name", "") or "")
        haystack = " ".join([cn, pn, ad, addr, name_t])

        if city and city in haystack:
            return True
        if city_short and city_short in haystack:
            return True

        loc = getattr(place, "location", None)
        if _in_city_bounds(city, loc):
            return True

        return False

    all_web_items: list[dict] = []
    for query in recall_queries[:3]:
        try:
            results = await bocha_search_batch([query.format(city=city_short)])
            for items in results:
                all_web_items.extend(items)
        except Exception as exc:
            print(f"[WARN step2] theme recall bocha search failed '{query}': {exc}")

    if not all_web_items:
        return []

    # 从博查摘要中抽取候选名称
    candidate_names: list[str] = []
    for item in all_web_items:
        text = f"{item.get('name', '')} {item.get('snippet', '')}"
        for term in dest_terms:
            if term in text and term not in candidate_names:
                candidate_names.append(term)
    # 补充正则抽取
    import re as _re
    for item in all_web_items:
        snippet = item.get("snippet", "")
        matches = _re.findall(r"[一-龥A-Za-z\d·]+(?:园|路|街区|风貌区|美术馆|书店|创意园|公馆|老场坊|艺术中心|博物馆|馆|坊|里弄|弄堂)", snippet)
        for m in matches:
            if len(m) >= 3 and m not in candidate_names and m not in dest_terms:
                candidate_names.append(m)

    if not candidate_names:
        return []

    # 高德坐标校准（最多校准8个名称）
    places: list[ExtractedPlace] = []
    import re as _re2
    for name in candidate_names[:8]:
        try:
            raws = await gaode_text_search(name, city=city, show_fields=config.GAODE_SHOW_FIELDS)
            for raw in raws:
                place = _to_extracted(raw)
                if not place or not place.location:
                    continue
                if not _is_valid_route_poi_ctx(place.typecode, place.name, parsed_intent):
                    continue
                if not _place_matches_city(raw, place):
                    print(
                        f"[DEBUG step2] drop cross-city theme recall: "
                        f"name={place.name} city={raw.get('cityname')} province={raw.get('pname')} target={city}"
                    )
                    continue
                # v20: District-level filter — reject candidates outside the requested admin district
                if not _place_matches_district(raw, place):
                    print(
                        f"[AreaScopeAudit] drop cross-district theme recall: "
                        f"name={place.name} adname={raw.get('adname','')} "
                        f"adcode={raw.get('adcode','')} target_district={_search_area_label}"
                    )
                    continue
                # enrichment
                snippets = " ".join(
                    f"{item.get('name', '')} {item.get('snippet', '')}"
                    for item in all_web_items[:10]
                    if name[:3] in (item.get("snippet", "") + item.get("name", ""))
                )
                evidence = score_poi_against_theme(place, profile, snippets)
                if not evidence.accepted:
                    print(
                        "[DEBUG step2] drop theme recall for low relevance: "
                        f"name={place.name} score={evidence.score} "
                        f"positive={list(evidence.positive_hits)} "
                        f"generic={list(evidence.generic_penalty_hits)} "
                        f"excluded={list(evidence.excluded_hits)}"
                    )
                    continue

                place.recall_source = "bocha_theme_recall"
                place.poi_role = "destination_anchor" if evidence.score >= 16.0 else "route_waypoint"
                place.theme_recall_score = min(30.0, evidence.score)
                if snippets:
                    place.enrichment_text = (place.enrichment_text or "") + snippets[:300]
                # bocha keywords
                kw_set = set()
                for item in all_web_items:
                    text = f"{item.get('name', '')} {item.get('snippet', '')}"
                    for word in _re2.split(r"[，。、\s]", text):
                        w = word.strip().lower()
                        if len(w) >= 2:
                            kw_set.add(w)
                place.bocha_keywords = list(kw_set)[:50]
                places.append(place)
                break
        except Exception as exc:
            print(f"[WARN step2] theme recall geocode failed '{name}': {exc}")

    if places:
        print(f"[DEBUG step2] theme recall found {len(places)} places: {[(p.name, p.location) for p in places]}")
    return places


async def _enrich_places(places: list[ExtractedPlace], city: str) -> list[ExtractedPlace]:
    # Enrich only the strongest two candidates.  This runs before final
    # selection, so enriching six candidates amplified every BoCha long tail.
    enrich_limit = 2
    queries = [f"{city} {place.name} 推荐 攻略 活动" for place in places[:enrich_limit]]
    if not queries:
        return places
    try:
        results = await asyncio.wait_for(bocha_search_batch(queries), timeout=7.0)
    except Exception as exc:
        print(f"[WARN step2] candidate enrichment degraded: {type(exc).__name__}: {exc}")
        return places
    for place, web_items in zip(places[:enrich_limit], results):
        snippets = " ".join([f"{item.get('name', '')} {item.get('snippet', '')}" for item in web_items])
        place.enrichment_text = snippets[:500]
        place.enrichment_heat = min(1.0, 0.25 + len(web_items) * 0.08)
        if any(token in snippets for token in ["活动", "展", "节", "市集"]):
            place.has_event = True
            place.event_status = "uncertain"
            place.event_name = "主题活动"
        # v9: 从博查摘要中提取关键词，供微观POI评分使用
        kw_set: set[str] = set()
        for item in web_items:
            text = f"{item.get('name', '')} {item.get('snippet', '')}"
            for word in text.replace("，", " ").replace("。", " ").replace("、", " ").split():
                w = word.strip().lower()
                if len(w) >= 2 and w not in {"推荐", "攻略", "活动", "上海", "介绍", "地址", "电话"}:
                    kw_set.add(w)
        place.bocha_keywords = list(kw_set)[:50]
    return places


# v20: Ranking modifier — primary sort for popularity/rating/distance/scale/history.
# Uses entity_role priority as first sort key, then ranking evidence, then original score.
def _apply_ranking_modifier(
    scored: list,
    parsed_intent,
    ranking_intent: str,
) -> list:
    """Apply ranking intent as PRIMARY sort, not a small bonus.

    For popularity: entity_role > fame evidence > original score > distance.
    Distance is only a tiebreaker, never the primary factor.
    """
    from .poi_typecodes import classify_university_role

    ROLE_PRIORITY = {
        "main_university_campus": 0,
        "conventional_college_campus": 1,
        "generic": 2,
        "branch_or_department": 3,
        "campus_internal_facility": 4,
        "adult_or_vocational_school": 5,
    }

    for place in scored:
        poiweight = float(getattr(place, "poiweight", 0) or 0)
        rating = float(getattr(place, "gaode_rating", 0) or 0)
        transit = float(getattr(place, "transit_from_origin_min", 999) or 999)
        entity_role = classify_university_role({
            "name": place.name,
            "category": getattr(place, "typecode", ""),
        })
        role_priority = ROLE_PRIORITY.get(entity_role, 2)

        # Compute ranking_score (fame evidence)
        if ranking_intent == "popularity":
            ranking_score = round(
                poiweight * 20.0 + rating * 1.5 + max(0, (10 - min(transit, 10)) * 0.1),
                2,
            )
        elif ranking_intent == "rating":
            ranking_score = round(rating * 3.0 + poiweight * 5.0, 2)
        elif ranking_intent == "distance":
            ranking_score = round(max(0, (30 - min(transit, 30)) * 0.5), 2)
        elif ranking_intent == "scale":
            ranking_score = round(poiweight * 15.0, 2)
        elif ranking_intent == "history":
            ranking_score = round(poiweight * 10.0 + rating * 0.5, 2)
        else:
            ranking_score = 0.0

        old_score = place.final_score
        # Store ranking score for sorting
        place._role_priority = role_priority
        place._ranking_score = ranking_score
        place._original_final_score = old_score

        # Always log, even when evidence is zero
        print(
            f"[RankingAudit] intent={ranking_intent} candidate={place.name} "
            f"entity_role={entity_role} role_priority={role_priority} "
            f"poiweight={poiweight} rating={rating} transit={transit} "
            f"ranking_score={ranking_score:.1f} original_score={old_score} "
            f"evidence_missing={'poiweight_rating_zero' if poiweight==0 and rating==0 else 'none'}"
        )

    # Primary sort: role_priority > ranking_score > original score
    scored.sort(key=lambda item: (
        getattr(item, "_role_priority", 2),
        -getattr(item, "_ranking_score", 0),
        -item.final_score,
    ))
    return scored


def _score_places_prefetched(
    places: list[ExtractedPlace],
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
    transit_map: dict[str, float | None],
) -> list[ScoredPlace]:
    """v4.1 F7: 使用预查的 transit 结果评分，不再重复调 API。"""
    origin = parsed_intent.original_location
    scored = []
    for place in places:
        pid = getattr(place, "gaode_poi_id", None) or place.name
        transit = transit_map.get(pid)
        if transit is None and origin:
            est_transit = haversine_km(origin, place.location) * 4.0
            transit = est_transit
        scored.append(_score_place(place, parsed_intent, transit, user_profile=user_profile))
    scored.sort(key=lambda item: item.final_score, reverse=True)
    # 复用 _score_places 的后处理过滤链
    if _is_nearby_request(parsed_intent):
        nearby_scored = [
            item
            for item in scored
            if item.transit_from_origin_min is not None and item.transit_from_origin_min <= 20
        ]
        if nearby_scored:
            scored = nearby_scored
    preference_matched = [item for item in scored if _preference_match(item, parsed_intent)[0] > 0]
    anime_intent = any(kw in parsed_intent.raw_keywords for kw in ["二次元", "动漫", "ACG", "谷子", "手办"])
    if parsed_intent.raw_keywords and preference_matched and not anime_intent:
        scored = preference_matched
    filtered = [item for item in scored if not _generic_anchor_mismatches_specific_preference(item, parsed_intent)]
    if filtered:
        scored = filtered
    casual_filtered = [item for item in scored if not _mismatches_casual_nearby(item, parsed_intent)]
    if casual_filtered:
        scored = casual_filtered
    scenic_filtered = [item for item in scored if not _mismatches_scenic_photo(item, parsed_intent)]
    if scenic_filtered:
        scored = scenic_filtered
    ancient_filtered = [item for item in scored if not _mismatches_ancient_street(item, parsed_intent)]
    if ancient_filtered:
        scored = ancient_filtered
    anime_filtered = [item for item in scored if not _mismatches_anime_anchor(item, parsed_intent)]
    if anime_filtered:
        scored = anime_filtered
    shopping_filtered = [item for item in scored if not _mismatches_shopping(item, parsed_intent)]
    if shopping_filtered:
        scored = shopping_filtered
    always_bad_filtered = [item for item in scored if not _mismatches_always_bad(item, parsed_intent)]
    if always_bad_filtered:
        scored = always_bad_filtered
    # v20: Apply ranking modifier from Step1 (popularity/rating/distance/scale/history)
    _ranking_intent = getattr(parsed_intent, "ranking_intent", None)
    if _ranking_intent and scored:
        scored = _apply_ranking_modifier(scored, parsed_intent, _ranking_intent)

    before_rainy = len(scored)
    rainy_indoor_filtered = [item for item in scored if not _mismatches_rainy_indoor(item, parsed_intent)]
    if rainy_indoor_filtered:
        scored = rainy_indoor_filtered
    # [DEBUG-雨天半天] 雨天过滤前后数量 + top-5 candidates
    after_rainy = len(scored)
    rainy_flag = _rainy_context(parsed_intent)
    print(f"[DEBUG step2] rainy_context={rainy_flag} before_filter={before_rainy} after_filter={after_rainy}")
    for i, c in enumerate(scored[:5]):
        print(f"[DEBUG step2] top{i+1}: name={c.name} role={getattr(c, 'poi_role', '')} recall={getattr(c, 'recall_source', '')} theme_score={getattr(c, 'theme_recall_score', 0)} transit={c.transit_from_origin_min} typecode={c.typecode} weather_penalty={c.weather_penalty} final_score={c.final_score}")
    if parsed_intent.delete_list or getattr(parsed_intent, 'excluded_areas', []):
        delete_lowered = [name.lower() for name in parsed_intent.delete_list]
        excluded = delete_lowered + [a.lower() for a in (getattr(parsed_intent, 'excluded_areas', []) or [])]
        delete_filtered = [
            item for item in scored
            if not any(
                d in (item.name.lower() or '')
                or d in (getattr(item, 'address', '') or '').lower()
                or d in (getattr(item, 'district', '') or '').lower()
                for d in excluded
            )
        ]
        if delete_filtered:
            scored = delete_filtered
    return scored


async def _score_places(places: list[ExtractedPlace], parsed_intent: ParsedIntent, user_profile: UserProfile) -> list[ScoredPlace]:
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    origin = parsed_intent.original_location
    # Four real routes are enough after straight-line pre-ranking.  Remaining
    # candidates use the existing local estimate.
    TOP_N_REAL_ROUTE = 4
    if len(places) > TOP_N_REAL_ROUTE and origin:
        pre_ranked = []
        for place in places:
            est_transit = haversine_km(origin, place.location) * 4.0
            fast_score = (place.gaode_rating or 4.0) / 5.0 * 30 + max(0.0, 1.0 - est_transit / 60) * 20 + min(max(place.enrichment_heat, 0.0), 1.0) * 20
            pre_ranked.append((fast_score, place, est_transit))
        pre_ranked.sort(key=lambda x: x[0], reverse=True)
        top_places = [p for _, p, _ in pre_ranked[:TOP_N_REAL_ROUTE]]
        rest_places = [(p, est) for _, p, est in pre_ranked[TOP_N_REAL_ROUTE:]]
        top_routes = await asyncio.gather(*[
            _route_from_origin_bounded(parsed_intent, place, city) for place in top_places
        ])
        scored = []
        for place, route in zip(top_places, top_routes):
            transit = route.get("duration_min") if route else None
            scored.append(_score_place(place, parsed_intent, transit, user_profile=user_profile))
        for place, est_transit in rest_places:
            scored.append(_score_place(place, parsed_intent, est_transit, user_profile=user_profile))
    else:
        routes = await asyncio.gather(*[
            _route_from_origin_bounded(parsed_intent, place, city) for place in places
        ])
        scored = []
        for place, route in zip(places, routes):
            transit = route.get("duration_min") if route else None
            scored.append(_score_place(place, parsed_intent, transit, user_profile=user_profile))
    scored.sort(key=lambda item: item.final_score, reverse=True)
    if _is_nearby_request(parsed_intent):
        nearby_scored = [
            item
            for item in scored
            if item.transit_from_origin_min is not None and item.transit_from_origin_min <= 20
        ]
        if nearby_scored:
            scored = nearby_scored
    preference_matched = [item for item in scored if _preference_match(item, parsed_intent)[0] > 0]
    anime_intent = any(kw in parsed_intent.raw_keywords for kw in ["二次元", "动漫", "ACG", "谷子", "手办"])
    if parsed_intent.raw_keywords and preference_matched and not anime_intent:
        scored = preference_matched
    filtered = [item for item in scored if not _generic_anchor_mismatches_specific_preference(item, parsed_intent)]
    if filtered:
        scored = filtered
    casual_filtered = [item for item in scored if not _mismatches_casual_nearby(item, parsed_intent)]
    if casual_filtered:
        scored = casual_filtered
    scenic_filtered = [item for item in scored if not _mismatches_scenic_photo(item, parsed_intent)]
    if scenic_filtered:
        scored = scenic_filtered
    ancient_filtered = [item for item in scored if not _mismatches_ancient_street(item, parsed_intent)]
    if ancient_filtered:
        scored = ancient_filtered
    anime_filtered = [item for item in scored if not _mismatches_anime_anchor(item, parsed_intent)]
    if anime_filtered:
        scored = anime_filtered
    shopping_filtered = [item for item in scored if not _mismatches_shopping(item, parsed_intent)]
    if shopping_filtered:
        scored = shopping_filtered
    always_bad_filtered = [item for item in scored if not _mismatches_always_bad(item, parsed_intent)]
    if always_bad_filtered:
        scored = always_bad_filtered
    before_rainy2 = len(scored)
    rainy_indoor_filtered = [item for item in scored if not _mismatches_rainy_indoor(item, parsed_intent)]
    if rainy_indoor_filtered:
        scored = rainy_indoor_filtered
    # [DEBUG-雨天半天] _score_places 路径雨天过滤
    after_rainy2 = len(scored)
    rainy_flag2 = _rainy_context(parsed_intent)
    if before_rainy2 != after_rainy2:
        print(f"[DEBUG step2-legacy] rainy_context={rainy_flag2} before_filter={before_rainy2} after_filter={after_rainy2}")
    if parsed_intent.delete_list or getattr(parsed_intent, 'excluded_areas', []):
        delete_lowered = [name.lower() for name in parsed_intent.delete_list]
        excluded = delete_lowered + [a.lower() for a in (getattr(parsed_intent, 'excluded_areas', []) or [])]
        delete_filtered = [
            item for item in scored
            if not any(
                d in (item.name.lower() or '')
                or d in (getattr(item, 'address', '') or '').lower()
                or d in (getattr(item, 'district', '') or '').lower()
                for d in excluded
            )
        ]
        if delete_filtered:
            scored = delete_filtered
    if _is_nearest_request(parsed_intent):
        scored.sort(
            key=lambda item: (
                item.transit_from_origin_min if item.transit_from_origin_min is not None else 9999,
                -item.final_score,
            )
        )
    return scored


def _select_anchors(fixed: list[AnchorPlan], candidates: list[ScoredPlace], parsed_intent: ParsedIntent) -> list[AnchorPlan]:
    selected: list[AnchorPlan] = list(fixed)
    used = sum(capacity_budget(anchor.final_capacity or anchor.time_capacity) for anchor in fixed)
    target = max(parsed_intent.time_budget, 0.25)
    # v20: debug logging
    print(
        f"[DEBUG step2 select] START fixed_anchors={[(a.name, a.final_capacity or a.time_capacity) for a in fixed]} "
        f"used={used:.2f} target={target:.2f} "
        f"candidates={[(c.name, c.final_capacity or c.time_capacity, getattr(c, 'typecode', '')[:6]) for c in candidates[:8]]}"
    )
    if "节奏宽松" in parsed_intent.other_constraints and any(
        keyword in {"古街", "古镇"} for keyword in parsed_intent.raw_keywords
    ):
        target = min(target, 0.5)
    seen = {anchor.name for anchor in fixed}
    seen_locations: list[tuple[float, float]] = [
        (anchor.location.get("lat", 0), anchor.location.get("lng", 0))
        for anchor in fixed
        if anchor.location
    ]
    excluded_all = [n.lower() for n in parsed_intent.delete_list]
    excluded_all += [a.lower() for a in (getattr(parsed_intent, 'excluded_areas', []) or [])]
    for candidate in _diversify_anime_candidates(candidates, parsed_intent):
        if candidate.name in seen:
            continue
        # 排除列表过滤
        if excluded_all and any(
            d in (candidate.name.lower() or '')
            or d in (getattr(candidate, 'address', '') or '').lower()
            or d in (getattr(candidate, 'district', '') or '').lower()
            for d in excluded_all
        ):
            continue
        if _mismatches_anime_anchor(candidate, parsed_intent):
            continue
        # 同区域去重：与已选 anchor 间距 < 500m 且同类 typecode 则跳过（保留至少2个后放宽）
        # 二次元/动漫主题通常聚集在同一商场，不适用此规则
        anime_intent = any(kw in parsed_intent.raw_keywords for kw in ["二次元", "动漫", "ACG", "谷子", "手办"])
        if not anime_intent and len(selected) >= 2 and candidate.location and seen_locations:
            cand_lat = candidate.location.get("lat", 0)
            cand_lng = candidate.location.get("lng", 0)
            too_close = False
            for sl in seen_locations:
                if haversine_km({"lat": cand_lat, "lng": cand_lng}, {"lat": sl[0], "lng": sl[1]}) < 0.5:
                    if (candidate.typecode or "")[:3] == (selected[-1].typecode or "")[:3]:
                        too_close = True
                        break
            if too_close:
                continue
        selected_capacity = _effective_capacity_for_request(
            candidate.final_capacity or candidate.time_capacity,
            parsed_intent,
            has_fixed_anchors=bool(fixed),
        )
        budget = capacity_budget(selected_capacity)
        if used + budget > target + 0.001 and selected:
            print(
                f"[DEBUG step2 select] SKIP {candidate.name}: "
                f"capacity={selected_capacity} budget={budget:.2f} used={used:.2f} target={target:.2f} "
                f"would_exceed={used + budget > target + 0.001}"
            )
            continue
        data = candidate.model_dump()
        data["final_capacity"] = selected_capacity
        reason_place = candidate.model_copy(update={"final_capacity": selected_capacity})
        reason = _recommend_reason(reason_place, parsed_intent)
        selected.append(
            AnchorPlan(
                **data,
                final_time_budget=selected_capacity,
                recommend_reason=reason,
                origin_transit=f"从出发点约{int(candidate.transit_from_origin_min or 0)}分钟",
            )
        )
        seen.add(candidate.name)
        used += budget
        if candidate.location:
            seen_locations.append((candidate.location.get("lat", 0), candidate.location.get("lng", 0)))
        if used >= target - 0.001:
            break
    if not selected and candidates:
        candidate = candidates[0]
        capacity = _effective_capacity_for_request(candidate.final_capacity or candidate.time_capacity, parsed_intent, has_fixed_anchors=bool(fixed))
        print(
            f"[DEBUG step2 select] FALLBACK single anchor: {candidate.name} "
            f"original_capacity={candidate.final_capacity or candidate.time_capacity} "
            f"upgraded_capacity={capacity}"
        )
        selected.append(
            AnchorPlan(
                **candidate.model_dump(),
                final_time_budget=capacity,
                recommend_reason=_recommend_reason(candidate, parsed_intent),
            )
        )
    if _has_shopping_intent(parsed_intent) and len(selected) > len(fixed):
        has_shopping_anchor = any(
            (anchor.typecode or "").startswith("06")
            for anchor in selected
        )
        if not has_shopping_anchor:
            shopping_candidates = [
                c for c in candidates
                if (c.typecode or "").startswith("06")
                and c.name not in seen
                and not _mismatches_shopping(c, parsed_intent)
            ]
            if shopping_candidates:
                for i in range(len(selected) - 1, -1, -1):
                    if not selected[i].fixed:
                        non_fixed_to_replace = selected[i]
                        break
                else:
                    non_fixed_to_replace = None
                if non_fixed_to_replace is not None:
                    best = shopping_candidates[0]
                    selected_capacity = _effective_capacity_for_request(
                        best.final_capacity or best.time_capacity,
                        parsed_intent,
                        has_fixed_anchors=bool(fixed),
                    )
                    data = best.model_dump()
                    data["final_capacity"] = selected_capacity
                    reason_place = best.model_copy(update={"final_capacity": selected_capacity})
                    reason = _recommend_reason(reason_place, parsed_intent)
                    selected[i] = AnchorPlan(
                        **data,
                        final_time_budget=selected_capacity,
                        recommend_reason=reason,
                        origin_transit=f"从出发点约{int(best.transit_from_origin_min or 0)}分钟",
                    )
    print(
        f"[DEBUG step2 select] DONE selected={[(a.name, a.final_capacity or a.time_capacity) for a in selected]} "
        f"used/target={used:.2f}/{target:.2f} count={len(selected)}"
    )
    return selected


def _capacity_rejects_for_macro_search(parsed_intent: ParsedIntent) -> list[str]:
    if parsed_intent.time_budget <= 0.25:
        return []
    return list(parsed_intent.reject_capacities)


def _effective_capacity_for_request(capacity: str, parsed_intent: ParsedIntent, *, is_fixed: bool = False, has_fixed_anchors: bool = False) -> str:
    """v5.2+v20: is_fixed=True时不升级用户明确指定的capacity。

    v20: 有固定锚点时不再将 half_day 普遍升级为 full_day，
    以免单个候选占满预算导致其他候选全部被跳过。
    仅在无固定锚点且最终只有一个候选时才扩大单锚点预算。
    """
    if parsed_intent.time_budget <= 0.25:
        return "quarter_day"
    if not is_fixed:
        # v20: 有固定锚点时保持 half_day，允许组合多个候选
        if parsed_intent.time_budget >= 1.0 and capacity == "half_day" and not has_fixed_anchors:
            return "full_day"
        if parsed_intent.time_budget >= 0.5 and capacity == "quarter_day" and not _is_nearby_request(parsed_intent):
            return "half_day"
    return capacity


def _order_day_anchors(day_anchors: list[AnchorPlan], parsed_intent: ParsedIntent) -> list[AnchorPlan]:
    if len(day_anchors) <= 1:
        return day_anchors
    ordered = list(day_anchors)
    if parsed_intent.evening_requested:
        night_terms = ["外滩", "陆家嘴", "黄浦江", "夜景", "观景", "东方明珠", "万国建筑"]
        night_indices = [
            index
            for index, anchor in enumerate(ordered)
            if any(term in f"{anchor.name} {anchor.enrichment_text}" for term in night_terms)
        ]
        if night_indices:
            index = night_indices[-1]
            ordered.append(ordered.pop(index))
    return ordered


def _assign_anchor_time_budget(
    anchors: list[AnchorPlan],
    parsed_intent: ParsedIntent,
) -> list[AnchorPlan]:
    """v3新增 (step_2_5_5)：为每个锚点确定 final_time_budget。
    - fixed_poi 锚点已有 resolved_time_budget
    - 搜索发现锚点用 typecode 映射值
    - 兜底默认 half_day
    - v5: 若用户意图为full_day且锚点不足，升级锚点容量
    """
    for anchor in anchors:
        if anchor.final_time_budget:
            continue
        anchor.final_time_budget = infer_capacity_from_typecode(anchor.typecode, anchor.name) or "half_day"
    # v5.2: 不再自动将单个锚点升级为full_day
    # 用户说"上午去X"→half_day就是half_day，不应被升级
    # 如果用户确实要玩一天，应该在fixed_poi里说"玩一天"
    return anchors


def _target_day_count(parsed_intent: ParsedIntent) -> int:
    if parsed_intent.time_budget <= 1.25:
        return 1
    return max(1, math.ceil(max(parsed_intent.time_budget, 0.25)))


def _requested_day_for_anchor(anchor: AnchorPlan, parsed_intent: ParsedIntent) -> int | None:
    for constraint in getattr(parsed_intent, "day_poi_constraints", []):
        poi_name = str(constraint.get("poi_name") or "")
        if not poi_name:
            continue
        if poi_name in anchor.name or anchor.name in poi_name:
            try:
                return int(constraint.get("day_index") or 0) or None
            except (TypeError, ValueError):
                return None
    return None


def _anchor_allowed_on_day(anchor: AnchorPlan, parsed_intent: ParsedIntent, day_index: int) -> bool:
    requested_day = _requested_day_for_anchor(anchor, parsed_intent)
    return requested_day is None or requested_day == day_index


def _meal_constraints_for_slot(parsed_intent: ParsedIntent, day_index: int, meal: str) -> list[dict]:
    constraints = []
    for constraint in getattr(parsed_intent, "meal_constraints", []):
        constraint_meal = constraint.get("meal")
        constraint_day = constraint.get("day_index")
        if constraint_day not in (None, "", day_index):
            try:
                if int(constraint_day) != day_index:
                    continue
            except (TypeError, ValueError):
                continue
        if constraint_meal not in (None, "", meal):
            continue
        constraints.append(constraint)
    return constraints


def _apply_meal_constraints(parsed_intent: ParsedIntent, day_index: int, slots: list[dict]) -> list[dict]:
    by_meal = {slot.get("meal"): slot for slot in slots}
    for constraint in getattr(parsed_intent, "meal_constraints", []):
        meal = constraint.get("meal")
        if meal not in MEAL_WINDOWS:
            continue
        constraint_day = constraint.get("day_index")
        if constraint_day not in (None, "", day_index):
            try:
                if int(constraint_day) != day_index:
                    continue
            except (TypeError, ValueError):
                continue
        if meal not in by_meal:
            by_meal[meal] = {"meal": meal, "time_range": list(MEAL_WINDOWS[meal]), "poi_name": None}
    result = list(by_meal.values())
    for slot in result:
        keywords: list[str] = []
        fixed_poi_name = None
        for constraint in _meal_constraints_for_slot(parsed_intent, day_index, slot.get("meal")):
            keywords.extend(keyword for keyword in constraint.get("keywords", []) if keyword)
            if constraint.get("fixed_poi_name"):
                fixed_poi_name = constraint.get("fixed_poi_name")
        if keywords:
            slot["requested_keywords"] = list(dict.fromkeys(keywords))
        if fixed_poi_name:
            slot["fixed_poi_name"] = fixed_poi_name
    return result


def _meal_slots_for_day(parsed_intent: ParsedIntent, day_index: int) -> list[dict]:
    meal_needs = parsed_intent.meal_needs
    if not meal_needs:
        slots = _apply_meal_constraints(parsed_intent, day_index, [])
        # v6: 强餐饮任务型需求 — 用户明确要找餐厅/吃某类餐，但没有 lunch/dinner 标记
        # 根据 start_time 推断一个 meal slot
        if not slots and _has_strong_meal_intent(parsed_intent):
            inferred_meal = _infer_meal_from_time(parsed_intent)
            if inferred_meal:
                slots = [{"meal": inferred_meal, "time_range": list(MEAL_WINDOWS[inferred_meal]), "poi_name": None}]
                # 同时把 meal_search_keywords 写入 slot 的 requested_keywords
                meal_kws = getattr(parsed_intent, "meal_search_keywords", []) or []
                if meal_kws:
                    slots[0]["requested_keywords"] = list(meal_kws)
        return slots
    if all(isinstance(item, str) for item in meal_needs):
        day_meals = meal_needs if day_index == 1 else []
    else:
        day_meals = meal_needs[day_index - 1] if day_index - 1 < len(meal_needs) else []
    slots = []
    for meal in day_meals:
        if meal in MEAL_WINDOWS:
            slots.append({"meal": meal, "time_range": list(MEAL_WINDOWS[meal]), "poi_name": None})
    return _apply_meal_constraints(parsed_intent, day_index, slots)


# ── v20: Synonym wide recall for poi_category queries ──
async def _synonym_wide_recall(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace] | None:
    """When primary search produces no results, try once with wider synonym terms."""
    from .poi_typecodes import CATEGORY_RULES, get_semantic_terms, get_allowed_typecode_prefixes

    city = await _resolve_city_from_profile(user_profile) or (
        user_profile.permanent_city[0] if user_profile.permanent_city else ""
    )
    if not city:
        return None

    primary_query = getattr(parsed_intent, "primary_query", "") or ""
    if not primary_query:
        return None

    # Find matching category rule
    cat_id = None
    rule = None
    for cid, r in CATEGORY_RULES.items():
        if cid == "restaurant":
            continue
        for term in r.get("semantic_terms", []):
            if term.lower() in primary_query.lower():
                cat_id = cid
                rule = r
                break
        if rule:
            break

    if not rule:
        return None

    city_short = city[:-1] if city.endswith("市") else city
    synonyms = rule.get("semantic_terms", [])[:6]
    wide_keywords = [f"{city_short} {syn}" for syn in synonyms if syn != primary_query]

    if not wide_keywords:
        return None

    print(f"[DEBUG step2] synonym wide recall: keywords={wide_keywords}")

    try:
        results = await asyncio.gather(
            *[gaode_text_search(kw, city=city, show_fields=config.GAODE_SHOW_FIELDS) for kw in wide_keywords[:4]],
            return_exceptions=True,
        )
    except Exception:
        return None

    places: list[ExtractedPlace] = []
    for group in results:
        if isinstance(group, Exception):
            continue
        if not group:
            continue
        for raw in group:
            place = _to_extracted(raw)
            if place and place.location and place.name:
                # Basic filter: must pass is_valid_route_poi
                if _is_valid_route_poi_ctx(place.typecode, place.name, parsed_intent):
                    places.append(place)

    return places[:8] if places else None


# ── v20: Intent-based candidate filtering ──
def _filter_candidates_by_intent(
    candidates: list[ScoredPlace],
    parsed_intent: ParsedIntent,
) -> list[ScoredPlace]:
    """Filter candidates using score_poi_against_intent. Hard-conflict POIs are deleted."""
    poi_query_type = getattr(parsed_intent, "poi_query_type", "") or ""
    if poi_query_type not in ("poi_category", "named_poi"):
        return candidates

    filtered: list[ScoredPlace] = []
    _has_typecodes = bool(getattr(parsed_intent, "allowed_typecode_prefixes", None))
    _has_registered_cat = bool(
        getattr(parsed_intent, "category_id", None)
        and _has_typecodes
    )
    for place in candidates:
        evidence = score_poi_against_intent(
            poi={
                "name": place.name,
                "typecode": place.typecode or "",
                "category": getattr(place, "category", "") or "",
                "address": getattr(place, "address", "") or "",
                "business_area": getattr(place, "district", "") or "",
            },
            parsed_intent=parsed_intent,
            matched_query=getattr(parsed_intent, "primary_query", "") or "",
        )
        audit_msg = recall_audit_log(
            primary_query=getattr(parsed_intent, "primary_query", "") or "",
            poi_query_type=poi_query_type,
            candidate={"name": place.name, "typecode": place.typecode},
            evidence=evidence,
        )
        print(f"[DEBUG step2] {audit_msg}")

        # v21: Restaurant category enforcement — typecode MUST start with "05"
        _cat_id = getattr(parsed_intent, "category_id", None) or ""
        if _cat_id == "restaurant" and not (place.typecode or "").startswith("05"):
            print(
                f"[DEBUG step2] restaurant category reject (typecode not 05): "
                f"{place.name} typecode={place.typecode}"
            )
            continue

        # v20: For poi_category with typecodes, accepted=False MUST delete
        if not evidence.accepted:
            if _has_typecodes:
                print(f"[DEBUG step2] hard reject (has typecodes, accepted=False): {place.name}")
                continue
            if evidence.score <= -80:
                print(f"[DEBUG step2] hard reject (score<=-80): {place.name} reason={evidence.rejection_reasons}")
                continue

        if evidence.accepted:
            # Boost accepted/intent-matched candidates
            place.final_score = (getattr(place, "final_score", 0) or 0) + evidence.score * 0.5

        filtered.append(place)

    return filtered


def _has_strong_meal_intent(parsed_intent: ParsedIntent) -> bool:
    """v6: 检测用户是否明确表达了找餐厅/吃某类餐的强餐饮意图。
    基于 ParsedIntent 已有字段判断，不依赖 user_request。"""
    meal_keywords = getattr(parsed_intent, "meal_search_keywords", []) or []
    food_prefs = getattr(parsed_intent, "food_pref_keywords", []) or []
    meal_constraints = getattr(parsed_intent, "meal_constraints", []) or []
    # 字段非空直接判定
    if meal_keywords or food_prefs or meal_constraints:
        return True

    # 从已有字段拼接文本，匹配强餐饮词
    lowered_text = " ".join([
        *(parsed_intent.raw_keywords or []),
        *(parsed_intent.search_keywords or []),
        *meal_keywords,
        *food_prefs,
        *(parsed_intent.other_constraints or []),
    ]).lower()

    strong_tokens = [
        "找一家", "找个", "找家", "下馆子", "吃", "餐厅", "饭店", "美食", "日料",
        "寿司", "刺身", "拉面", "烤肉", "火锅", "串串", "麻辣烫", "中餐", "西餐",
        "韩料", "泰餐", "本帮菜", "粤菜", "川菜", "湘菜", "快餐", "小吃",
    ]
    return any(token in lowered_text for token in strong_tokens)


NON_MEAL_EXPLORATION_TERMS = [
    "随便走走", "走走", "散步", "逛逛", "转转", "游览", "看看", "看美景",
    "拍照", "打卡", "滨江", "江边", "步道", "公园", "绿地", "景点",
    "自然景色", "风景", "夜景", "美景"
]

MEAL_TEXT_TERMS = [
    "餐厅", "饭店", "晚餐", "晚饭", "午餐", "午饭", "吃饭", "美食",
    "小吃", "咖啡", "甜品", "日料", "本帮菜", "人均", "不超过", "以内"
]

ACTIVITY_QUERY_STOP_WORDS = [
    "上海", "上海市", "附近", "周边", "一带", "随便", "走走", "逛逛",
    "散步", "转转", "游览", "看看", "看美景", "拍照", "打卡", "推荐",
    "攻略", "路线", "帮我", "再", "顺便", "找一个", "找一家",
    "餐厅", "饭店", "晚餐", "晚饭", "午餐", "午饭", "吃饭", "美食",
    "小吃", "咖啡", "甜品", "人均", "不超过", "以内", "以下"
]


def _has_non_meal_explore_intent(parsed_intent: ParsedIntent) -> bool:
    texts = [
        *(getattr(parsed_intent, "raw_keywords", []) or []),
        *(getattr(parsed_intent, "search_keywords", []) or []),
        *(getattr(parsed_intent, "micro_keywords", []) or []),
        *(getattr(parsed_intent, "other_constraints", []) or []),
    ]
    joined = " ".join(str(t) for t in texts if t)
    if not joined:
        return False
    return any(term in joined for term in NON_MEAL_EXPLORATION_TERMS)


def _clean_activity_query(text: str) -> str:
    cleaned = str(text or "")
    for token in ACTIVITY_QUERY_STOP_WORDS:
        cleaned = cleaned.replace(token, " ")
    cleaned = re.sub(r"\d+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    parts = [p for p in cleaned.split(" ") if len(p) >= 2]
    return " ".join(parts[:3]).strip()


def _activity_fallback_queries(parsed_intent: ParsedIntent, user_profile: UserProfile) -> list[str]:
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    texts = [
        *(getattr(parsed_intent, "micro_keywords", []) or []),
        *(getattr(parsed_intent, "search_keywords", []) or []),
        *(getattr(parsed_intent, "raw_keywords", []) or []),
    ]
    queries: list[str] = []
    for text in texts:
        raw = str(text or "").strip()
        if not raw:
            continue
        if not any(term in raw for term in NON_MEAL_EXPLORATION_TERMS):
            continue
        query = _clean_activity_query(raw)
        if not query:
            continue
        if city and city not in query:
            query = f"{city} {query}"
        if query not in queries:
            queries.append(query)

    joined = " ".join(str(t) for t in texts if t)
    if "滨江" in joined:
        fallback = f"{city} 滨江步道".strip()
        if fallback and fallback not in queries:
            queries.append(fallback)
    if "公园" in joined:
        fallback = f"{city} 公园".strip()
        if fallback and fallback not in queries:
            queries.append(fallback)

    return queries[:4]


async def _fallback_rest_stop_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace]:
    """Fallback for rest_stop — progressive radius (800m→5km) around search area.

    Prioritizes cafes, tea houses, bookstores, park rest areas with seating.
    """
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    city_short = city[:-1] if city.endswith("市") else city
    _area_label = getattr(parsed_intent, "search_area_label", "") or ""

    # v21: Rest stop queries
    rest_queries = [
        [f"{city_short} 咖啡馆", f"{city_short} 茶馆", f"{city_short} 书店",
         f"{city_short} 公园休息区", f"{city_short} 甜品店"],
        [f"{city_short} 阅读空间", f"{city_short} 公共文化空间",
         f"{city_short} 商场休息区", f"{city_short} 图书馆"],
    ]

    REST_TYPECODES = ["050400", "050900", "061205", "050100", "110101", "060100", "140500"]
    EXCLUDE_TERMS = ["石舫", "景观", "构筑物", "停车场", "物业", "私人", "仅会员"]

    _radii = [800, 1500, 3000, 5000]
    _origin = parsed_intent.search_area_location or parsed_intent.original_location

    found: list[ExtractedPlace] = []
    seen: set[str] = set()

    for radius in _radii:
        if len(found) >= 3:
            break
        for queries in rest_queries:
            if len(found) >= 3:
                break
            for query in queries[:4]:
                if len(found) >= 3:
                    break
                try:
                    _loc = coord_to_param(_origin) if _origin else None
                    if not _loc:
                        raws = await gaode_text_search(query, city=city, show_fields=config.GAODE_SHOW_FIELDS)
                    else:
                        _req = {"location": _loc, "keywords": query.replace(f"{city_short} ", ""),
                                "radius": radius, "show_fields": config.GAODE_SHOW_FIELDS, "offset": 20}
                        batch = await gaode_around_search_batch([_req])
                        raws = batch[0] if batch else []
                except Exception as exc:
                    print(f"[WARN step2] rest_stop fallback r={radius}m query={query}: {exc}")
                    continue

                for raw in raws[:8]:
                    place = _to_extracted(raw)
                    if not place or not place.location:
                        continue
                    if place.name in seen:
                        continue
                    if not any(place.typecode.startswith(tc[:4]) for tc in REST_TYPECODES):
                        continue
                    name_text = f"{place.name} {place.address or ''}"
                    if any(t in name_text for t in EXCLUDE_TERMS):
                        continue
                    # v21: Sittable evidence
                    SIT_EV = ["座", "椅", "休息", "茶", "咖啡", "书", "甜品", "堂食"]
                    if not any(t in name_text for t in SIT_EV):
                        continue

                    if not place.enrichment_text:
                        place.enrichment_text = "可休息场所"
                    place.recall_source = "rest_stop_fallback"
                    place.poi_role = "route_waypoint"
                    seen.add(place.name)
                    found.append(place)
    if found:
        print(f"[DEBUG step2] rest_stop fallback found {len(found)}: {[(p.name, p.typecode) for p in found[:6]]}")
    return found


async def _fallback_stress_relief_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace]:
    """Fallback for stress_relief — progressive radius (3-15km) across activity categories.

    Searches quiet (parks/books/cafes), active (sports/KTV/games), and creative (crafts/DIY)
    based on stress_relief_mode. Mixed mode searches all three.
    """
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    city_short = city[:-1] if city.endswith("市") else city
    _mode = getattr(parsed_intent, "stress_relief_mode", "mixed") or "mixed"
    is_rainy = "雨天" in parsed_intent.other_constraints or "室内优先" in parsed_intent.other_constraints

    # v21: Build queries per mode
    all_queries: list[tuple[str, list[str]]] = []
    if _mode in ("quiet", "mixed"):
        all_queries.append(("quiet", [
            f"{city_short} 城市公园", f"{city_short} 滨水步道",
            f"{city_short} 独立书店", f"{city_short} 安静咖啡馆",
            f"{city_short} 美术馆", f"{city_short} 茶馆",
        ]))
    if _mode in ("active", "mixed"):
        all_queries.append(("active", [
            f"{city_short} 保龄球馆", f"{city_short} 攀岩馆",
            f"{city_short} KTV", f"{city_short} 游戏厅",
            f"{city_short} 运动体验馆", f"{city_short} 台球",
        ]))
    if _mode in ("creative", "mixed"):
        all_queries.append(("creative", [
            f"{city_short} 陶艺体验", f"{city_short} 手作体验",
            f"{city_short} DIY手工坊", f"{city_short} 绘画体验",
            f"{city_short} 沉浸式体验", f"{city_short} 烘焙体验",
        ]))
    if not all_queries:
        all_queries.append(("quiet", [
            f"{city_short} 城市公园", f"{city_short} 独立书店",
            f"{city_short} 安静咖啡馆",
        ]))

    # v21: Allowed typecodes per mode
    STRESS_TYPECODES = {
        "quiet": ["110100", "110101", "110200", "061205", "050400", "140600", "080500", "080600"],
        "active": ["080100", "080300"],
        "creative": ["060100", "080500"],
    }

    # v21: Medical terms to EXCLUDE
    MEDICAL_EXCLUDE = [
        "心理咨询", "精神卫生", "医院", "康复中心", "医疗",
        "诊所", "疗养院", "精神病", "心理科", "卫生站",
    ]

    STRESS_EV_TERMS = [
        "公园", "书店", "咖啡", "茶", "美术馆", "步道",
        "保龄球", "攀岩", "KTV", "游戏", "台球", "运动",
        "陶艺", "手作", "DIY", "绘画", "烘焙", "沉浸",
        "花园", "阅读", "体验",
    ]

    # v21: Progressive radius: 3km, 5km, 10km, 15km
    _radii = [3000, 5000, 10000, 15000]
    _origin_loc = parsed_intent.original_location or getattr(parsed_intent, "search_area_location", None)
    _types_str = ""  # no type filter for stress_relief

    found_places: list[ExtractedPlace] = []
    seen_names: set[str] = set()

    for radius in _radii:
        if found_places and len(found_places) >= 3:
            break

        for mode_label, queries in all_queries:
            if found_places and len(found_places) >= 3:
                break

            allowed_tc = STRESS_TYPECODES.get(mode_label, [])
            for query in queries[:3]:
                if found_places and len(found_places) >= 3:
                    break
                try:
                    # v21: Use around search with progressive radius
                    _loc_param = coord_to_param(_origin_loc) if _origin_loc else None
                    if not _loc_param:
                        # Fallback to text search
                        raws = await gaode_text_search(query, city=city, show_fields=config.GAODE_SHOW_FIELDS)
                    else:
                        _req = {
                            "location": _loc_param,
                            "keywords": query.replace(f"{city_short} ", ""),
                            "radius": radius,
                            "show_fields": config.GAODE_SHOW_FIELDS,
                            "offset": 20,
                        }
                        _batch_result = await gaode_around_search_batch([_req])
                        raws = _batch_result[0] if _batch_result else []
                except Exception as exc:
                    print(f"[WARN step2] stress_relief fallback r={radius}m query={query}: {exc}")
                    continue

                for raw in raws[:8]:
                    place = _to_extracted(raw)
                    if not place or not place.location:
                        continue
                    if place.name in seen_names:
                        continue

                    tc_ok = any(place.typecode.startswith(tc[:4]) for tc in allowed_tc)
                    if not tc_ok:
                        continue

                    name_text = f"{place.name} {place.address or ''}"

                    # v21: Hard reject medical facilities
                    if any(t in name_text for t in MEDICAL_EXCLUDE):
                        continue

                    # v21: Evidence check
                    has_ev = any(t.lower() in name_text.lower() for t in STRESS_EV_TERMS)
                    if not has_ev:
                        continue

                    # v21: Distance check for this radius tier
                    if _origin_loc:
                        _dist = haversine_km(_origin_loc, place.location)
                        if _dist > radius * 1.2 / 1000:  # 20% tolerance
                            continue

                    print(
                        f"[FeatureIntentAudit] candidate={place.name} "
                        f"mode={mode_label} radius={radius}m accepted=true "
                        f"typecode={place.typecode}"
                    )

                    if not place.enrichment_text:
                        place.enrichment_text = f"解压活动场所({mode_label})"
                    place.recall_source = "stress_relief_fallback"
                    place.poi_role = "route_waypoint"

                    seen_names.add(place.name)
                    found_places.append(place)

    if found_places:
        print(
            f"[DEBUG step2] stress_relief fallback found {len(found_places)} places: "
            f"{[(p.name, p.typecode) for p in found_places[:8]]}"
        )
    else:
        print("[DEBUG step2] stress_relief fallback found 0 places")

    return found_places


async def _fallback_local_life_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace]:
    """Fallback for local_life/market when primary theme_route search returns 0.

    Searches for: markets, old streets, community commercial streets, morning/night markets.
    Uses progressive radius: 3km, 5km, 10km, 15km.
    """
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    city_short = city[:-1] if city.endswith("市") else city

    local_life_queries = [
        # Stage 1: Direct market/street search
        [f"{city_short} 菜市场", f"{city_short} 农贸市场", f"{city_short} 便民市场",
         f"{city_short} 社区商业街", f"{city_short} 老街"],
        # Stage 2: Broader
        [f"{city_short} 邻里中心", f"{city_short} 花鸟市场", f"{city_short} 胡同",
         f"{city_short} 夜市", f"{city_short} 早市"],
        # Stage 3: Evening/night
        [f"{city_short} 小吃街", f"{city_short} 社区餐饮街", f"{city_short} 晚市",
         f"{city_short} 社区菜场", f"{city_short} 熟食市场"],
        # Stage 4: Wide
        [f"{city_short} 早餐街", f"{city_short} 集贸市场", f"{city_short} 跳蚤市场",
         f"{city_short} 古玩市场"],
    ]

    # Evidence must identify an actual market/neighbourhood destination.  Very
    # broad tokens such as "铺" or "摊" turn individual shops into false
    # positives and do not prove that the place itself has a local-life scene.
    LOCAL_LIFE_EV_TERMS = [
        "菜市场", "农贸市场", "便民市场", "社区商业", "邻里中心", "老街",
        "胡同", "早市", "夜市", "晚市", "市集", "熟食市场",
        "小吃街", "餐饮街", "菜场", "集市", "跳蚤市场", "古玩市场",
        "早餐街", "集贸市场", "一条街",
    ]

    # v21: Hard exclusions — NOT local life
    LOCAL_LIFE_EXCLUDE = [
        "水族", "宠物", "花鸟", "动物园", "博物馆", "展览馆",
        "办公楼", "高端购物中心", "写字楼", "景区观光",
        "高尔夫", "酒店", "停车场", "施工", "私人",
    ]

    found_places: list[ExtractedPlace] = []
    seen_names: set[str] = set()

    origin = (
        getattr(parsed_intent, "search_area_location", None)
        or getattr(parsed_intent, "original_location", None)
        or getattr(user_profile, "home_location", None)
    )
    origin_param = ""
    if isinstance(origin, dict) and origin.get("lng") is not None and origin.get("lat") is not None:
        origin_param = f"{origin['lng']},{origin['lat']}"
    stage_radii = [3000, 5000, 10000, 15000]

    for stage_idx, queries in enumerate(local_life_queries):
        if found_places and len(found_places) >= 3:
            break

        for query in queries[:5]:
            try:
                if origin_param:
                    around_keyword = query
                    city_prefix = f"{city_short} "
                    if city_short and around_keyword.startswith(city_prefix):
                        around_keyword = around_keyword[len(city_prefix):]
                    raws = await gaode_around_search(
                        location=origin_param,
                        keywords=around_keyword,
                        radius=stage_radii[min(stage_idx, len(stage_radii) - 1)],
                        show_fields=config.GAODE_SHOW_FIELDS,
                        offset=20,
                        sortrule="distance",
                    )
                else:
                    raws = await gaode_text_search(
                        query,
                        city=city,
                        show_fields=config.GAODE_SHOW_FIELDS,
                        city_limit=True,
                    )
            except Exception as exc:
                print(f"[WARN step2] local_life fallback search failed query={query}: {exc}")
                continue

            for raw in raws[:10]:
                place = _to_extracted(raw)
                if not place or not place.location:
                    continue
                if place.name in seen_names:
                    continue

                # This request asks for a local-life destination, not a single
                # restaurant whose brand/address happens to mention a market.
                # Accept shopping/market POIs and area-level old-street POIs;
                # food shops can be added later as micro POIs.
                tc_ok = place.typecode.startswith("06") or place.typecode.startswith("1102")
                if not tc_ok:
                    continue

                name_text = f"{place.name} {place.address or ''}"

                # v21: Hard reject water/pet/aquarium shops
                if any(t in name_text for t in ["水族", "宠物", "鱼", "鸟"]):
                    if not any(t in name_text for t in ["菜市场", "农贸", "便民", "市场", "社区", "邻里", "老街", "餐饮"]):
                        print(
                            f"[FeatureIntentAudit] candidate={place.name} "
                            f"required_features=['local_life'] "
                            f"feature_hits=[] accepted=false "
                            f"rejection_reason=pet_aquarium_not_local_life"
                        )
                        continue

                # v21: Reject other exclusions
                if any(t in name_text for t in LOCAL_LIFE_EXCLUDE):
                    continue

                has_local_ev = any(t.lower() in name_text.lower() for t in LOCAL_LIFE_EV_TERMS)

                if not has_local_ev:
                    print(
                        f"[FeatureIntentAudit] candidate={place.name} "
                        f"required_features=['local_life'] "
                        f"feature_hits=[] accepted=false "
                        f"rejection_reason=missing_local_life_evidence"
                    )
                    continue

                print(
                    f"[FeatureIntentAudit] candidate={place.name} "
                    f"required_features=['local_life'] "
                    f"feature_hits=['local_life'] accepted=true "
                    f"evidence_source=name_address typecode={place.typecode}"
                )

                if not place.enrichment_text:
                    place.enrichment_text = "本地生活街区/市场"
                place.recall_source = "local_life_fallback"
                place.poi_role = "route_waypoint"

                seen_names.add(place.name)
                found_places.append(place)

                if len(found_places) >= 8:
                    break

    if found_places:
        print(
            f"[DEBUG step2] local_life fallback found {len(found_places)} places: "
            f"{[(p.name, p.typecode) for p in found_places[:6]]}"
        )
    else:
        print("[DEBUG step2] local_life fallback found 0 places")

    return found_places


async def _fallback_open_terrace_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace]:
    """Fallback for open_terrace when primary theme_route search returns 0.

    Terraces exist in cafes, restaurants, bars, hotels, malls.
    Uses progressive radius (3km, 5km, 10km) and tiered category search.
    """
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    city_short = city[:-1] if city.endswith("市") else city

    # v21: Progressive terrace queries by category
    terrace_queries = [
        # Stage 1: Direct terrace search
        [f"{city_short} 开放露台", f"{city_short} 露台咖啡", f"{city_short} 露台餐厅",
         f"{city_short} rooftop", f"{city_short} 屋顶花园"],
        # Stage 2: Venue-level search
        [f"{city_short} 户外露台", f"{city_short} 空中露台", f"{city_short} 观景露台",
         f"{city_short} 露台酒吧", f"{city_short} 屋顶餐厅"],
        # Stage 3: Broader
        [f"{city_short} 露天咖啡", f"{city_short} 天台", f"{city_short} 观景台",
         f"{city_short} 酒店屋顶", f"{city_short} 商场露台"],
    ]

    # v21: Terrace-relevant typecodes
    TERRACE_TYPECODES = [
        "050400",  # 休闲餐饮 (咖啡馆常有露台)
        "050100",  # 中餐厅
        "050200",  # 外国餐厅
        "050900",  # 茶艺馆
        "060100",  # 购物中心
        "080304",  # 酒吧
        "100000",  # 酒店
        "110200",  # 景点/观景台
    ]

    # v21: Terrace evidence terms
    TERRACE_EV_TERMS = [
        "露台", "天台", "屋顶", "rooftop", "terrace",
        "户外座", "露天座", "观景台", "空中花园",
        "屋顶花园", "室外平台",
    ]

    # v21: Exclusions
    EXCLUDE_TERMS = [
        "私人", "住宅", "仅住客", "暂停开放", "施工中",
        "无公开入口", "内部权限", "办公楼",
    ]

    found_places: list[ExtractedPlace] = []
    seen_names: set[str] = set()

    for stage_idx, queries in enumerate(terrace_queries):
        if found_places and len(found_places) >= 3:
            break

        for query in queries[:5]:
            try:
                raws = await gaode_text_search(query, city=city, show_fields=config.GAODE_SHOW_FIELDS)
            except Exception as exc:
                print(f"[WARN step2] open_terrace fallback search failed query={query}: {exc}")
                continue

            for raw in raws[:10]:
                place = _to_extracted(raw)
                if not place or not place.location:
                    continue
                if place.name in seen_names:
                    continue

                tc_ok = any(place.typecode.startswith(tc[:4]) for tc in TERRACE_TYPECODES)
                if not tc_ok:
                    continue

                name_text = f"{place.name} {place.address or ''}"
                if any(t in name_text for t in EXCLUDE_TERMS):
                    continue

                has_terrace_ev = any(t.lower() in name_text.lower() for t in TERRACE_EV_TERMS)

                if not has_terrace_ev:
                    print(
                        f"[FeatureIntentAudit] candidate={place.name} "
                        f"required_features=['open_terrace'] "
                        f"feature_hits=[] accepted=false "
                        f"rejection_reason=missing_required_open_terrace_evidence"
                    )
                    continue

                print(
                    f"[FeatureIntentAudit] candidate={place.name} "
                    f"required_features=['open_terrace'] "
                    f"feature_hits=['open_terrace'] accepted=true "
                    f"evidence_source=name_address typecode={place.typecode}"
                )

                if not place.enrichment_text:
                    place.enrichment_text = "开放露台场所"
                place.recall_source = "open_terrace_fallback"
                place.poi_role = "route_waypoint"

                seen_names.add(place.name)
                found_places.append(place)

                if len(found_places) >= 8:
                    break

    if found_places:
        print(
            f"[DEBUG step2] open_terrace fallback found {len(found_places)} places: "
            f"{[(p.name, p.typecode) for p in found_places[:6]]}"
        )
    else:
        print("[DEBUG step2] open_terrace fallback found 0 places")

    return found_places


async def _fallback_lawn_rest_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace]:
    """Fallback for lawn_rest when primary theme_route search returns 0.

    Expands search across parks, green spaces, gardens, pocket parks.
    Uses progressive radius expansion.
    """
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    city_short = city[:-1] if city.endswith("市") else city

    is_rainy = "雨天" in parsed_intent.other_constraints or "室内优先" in parsed_intent.other_constraints
    required_features = getattr(parsed_intent, "required_features", []) or []

    # v21: Progressive lawn_rest search queries
    lawn_queries = [
        # Stage 1: Direct green space search
        [f"{city_short} 公园", f"{city_short} 城市绿地", f"{city_short} 草坪公园",
         f"{city_short} 口袋公园", f"{city_short} 公共花园"],
        # Stage 2: Broader green space
        [f"{city_short} 社区绿地", f"{city_short} 植物园", f"{city_short} 滨江绿地",
         f"{city_short} 花园", f"{city_short} 开放草坪"],
        # Stage 3: Even broader
        [f"{city_short} 野餐区", f"{city_short} 休闲广场",
         f"{city_short} 市民公园", f"{city_short} 街心花园"],
    ]

    if is_rainy:
        # Add indoor alternatives
        lawn_queries.append([f"{city_short} 室内植物园", f"{city_short} 温室花园",
                             f"{city_short} 带落地窗咖啡馆"])

    # v21: Lawn-relevant typecodes
    LAWN_TYPECODES = [
        "110100", "110101",  # 公园/城市公园
        "110200", "110000",  # 景点/风景名胜
    ]

    found_places: list[ExtractedPlace] = []
    seen_names: set[str] = set()

    # v21: Exclusions — NOT lawn/sittable
    EXCLUDE_LAWN_TERMS = [
        "高尔夫", "足球场", "篮球场", "网球场", "运动场",
        "道路隔离", "施工", "私人", "住宅", "封闭",
        "禁止进入", "不对外开放", "内部使用",
    ]

    for stage_idx, queries in enumerate(lawn_queries):
        if found_places and len(found_places) >= 3:
            break

        for query in queries[:5]:
            try:
                raws = await gaode_text_search(query, city=city, show_fields=config.GAODE_SHOW_FIELDS)
            except Exception as exc:
                print(f"[WARN step2] lawn_rest fallback search failed query={query}: {exc}")
                continue

            for raw in raws[:10]:
                place = _to_extracted(raw)
                if not place or not place.location:
                    continue
                if place.name in seen_names:
                    continue

                # v21: Validate lawn-relevant typecode
                tc_ok = any(place.typecode.startswith(tc[:4]) for tc in LAWN_TYPECODES)
                if not tc_ok:
                    continue

                # v21: Exclude non-lawn places
                name_text = f"{place.name} {place.address or ''} {place.typecode or ''}"
                if any(t in name_text for t in EXCLUDE_LAWN_TERMS):
                    print(
                        f"[FeatureIntentAudit] candidate={place.name} "
                        f"required_features={required_features} "
                        f"feature_hits=[] accepted=false "
                        f"rejection_reason=excluded_lawn_term"
                    )
                    continue

                # v21: Lawn evidence from name/address/typecode
                has_lawn_evidence = any(
                    t in name_text for t in [
                        "草坪", "草地", "绿地", "公园", "花园",
                        "草坪", "绿化", "绿洲", "植物园", "园",
                    ]
                )

                if not has_lawn_evidence:
                    print(
                        f"[FeatureIntentAudit] candidate={place.name} "
                        f"required_features={required_features} "
                        f"feature_hits=[] accepted=false "
                        f"rejection_reason=missing_required_lawn_evidence"
                    )
                    continue

                # v21: Set lawn enrichment
                if not place.enrichment_text:
                    place.enrichment_text = "城市绿地/草坪区域"
                # Mark as lawn candidate
                place.recall_source = "lawn_rest_fallback"
                place.poi_role = "route_waypoint"

                seen_names.add(place.name)
                found_places.append(place)

                print(
                    f"[FeatureIntentAudit] candidate={place.name} "
                    f"required_features={required_features} "
                    f"feature_hits={['lawn'] if has_lawn_evidence else []} "
                    f"accepted=true "
                    f"evidence_source=name_address_typecode "
                    f"typecode={place.typecode}"
                )

                if len(found_places) >= 8:
                    break

    if found_places:
        print(
            f"[DEBUG step2] lawn_rest fallback found {len(found_places)} places: "
            f"{[(p.name, p.typecode) for p in found_places[:6]]}"
        )
    else:
        print("[DEBUG step2] lawn_rest fallback found 0 places")

    return found_places


async def _fallback_quiet_retreat_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace]:
    """Fallback for quiet_retreat when primary theme_route search returns 0.

    Expands search across concrete quiet-space categories:
    libraries, bookstores, quiet cafes, tea houses, small parks, reading spaces.
    Uses wider radius in stages.
    """
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    city_short = city[:-1] if city.endswith("市") else city

    # v20: Check weather for indoor priority
    is_rainy = "雨天" in parsed_intent.other_constraints or "室内优先" in parsed_intent.other_constraints

    # v20: Multi-stage recall — start with precise quiet categories, then broaden
    quiet_fallback_queries = [
        # Stage 1: Precise quiet-space categories
        [f"{city_short} 图书馆", f"{city_short} 阅读空间", f"{city_short} 独立书店",
         f"{city_short} 安静咖啡馆", f"{city_short} 茶馆", f"{city_short} 美术馆"],
        # Stage 2: Broader quiet-space categories
        [f"{city_short} 书店", f"{city_short} 咖啡馆", f"{city_short} 自习室",
         f"{city_short} 茶室", f"{city_short} 展览馆", f"{city_short} 文化空间"],
        # Stage 3: Outdoor quiet spaces (lower priority in rain)
        [f"{city_short} 公园", f"{city_short} 口袋公园", f"{city_short} 滨水步道",
         f"{city_short} 社区绿地", f"{city_short} 花园", f"{city_short} 步道"],
    ]

    if is_rainy:
        # Indoors first, outdoors last
        pass
    else:
        # Interleave outdoor with indoor
        quiet_fallback_queries = [
            quiet_fallback_queries[0],
            quiet_fallback_queries[2],  # outdoor earlier in good weather
            quiet_fallback_queries[1],
        ]

    from .poi_typecodes import split_typecodes
    # v20: Quiet retreat relevant typecodes
    QUIET_RETREAT_TYPECODES = [
        "061205",  # 书店
        "050100",  # 中餐厅 (茶馆)
        "050400",  # 休闲餐饮 (咖啡)
        "050900",  # 茶艺馆
        "060100",  # 购物中心 (书店/文化空间可能在商场内)
        "060900",  # 文化用品
        "061000",  # 综合文化场所
        "080500",  # 展览馆
        "080600",  # 美术馆
        "110100",  # 公园
        "110101",  # 城市公园
        "110200",  # 景点
        "140100",  # 博物馆
        "140200",  # 展览
        "140600",  # 科技馆 (可能安静)
    ]

    found_places: list[ExtractedPlace] = []
    seen_names: set[str] = set()

    for stage_idx, queries in enumerate(quiet_fallback_queries):
        if found_places and len(found_places) >= 3:
            break  # Enough results

        for query in queries[:5]:
            try:
                raws = await gaode_text_search(query, city=city, show_fields=config.GAODE_SHOW_FIELDS)
            except Exception as exc:
                print(f"[WARN step2] quiet_retreat fallback search failed query={query}: {exc}")
                continue

            for raw in raws[:10]:
                place = _to_extracted(raw)
                if not place or not place.location:
                    continue
                if place.name in seen_names:
                    continue

                # v20: Validate that this is a reasonable quiet retreat candidate
                tc_ok = any(place.typecode.startswith(tc[:4]) for tc in QUIET_RETREAT_TYPECODES)
                if not tc_ok:
                    continue

                # v20: Exclude obviously non-quiet places
                name_text = f"{place.name} {place.address or ''}"
                LOUD_TERMS = ["火锅", "烧烤", "KTV", "酒吧", "夜店", "网吧", "游戏厅",
                              "菜市场", "夜市", "大排档", "批发", "建材", "维修", "洗车"]
                if any(t in name_text for t in LOUD_TERMS):
                    continue

                # v20: Rain check — exclude outdoor-only in rain
                if is_rainy and stage_idx >= 2:
                    if any(t in place.typecode for t in ["11"]) and not any(
                        t in name_text for t in ["室内", "博物馆", "展览馆"]
                    ):
                        # Outdoor park in rain — still keep but mark as low priority
                        pass

                # v20: Set enrichment with quiet evidence if available
                if not place.enrichment_text:
                    place.enrichment_text = "安静场所"

                seen_names.add(place.name)
                found_places.append(place)

                if len(found_places) >= 8:
                    break

    if found_places:
        print(
            f"[DEBUG step2] quiet_retreat fallback found {len(found_places)} places: "
            f"{[(p.name, p.typecode) for p in found_places[:6]]}"
        )
    else:
        print("[DEBUG step2] quiet_retreat fallback found 0 places")

    return found_places


async def _fallback_activity_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace]:
    if not _has_non_meal_explore_intent(parsed_intent):
        return []

    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    queries = _activity_fallback_queries(parsed_intent, user_profile)
    if not queries:
        return []

    fallback_places: list[ExtractedPlace] = []
    for query in queries:
        try:
            raws = await gaode_text_search(query, city=city, show_fields=config.GAODE_SHOW_FIELDS)
        except Exception as exc:
            print(f"[WARN step2] activity fallback text search failed query={query}: {exc}")
            continue

        for raw in raws:
            place = _to_extracted(raw)
            if not place or not place.location:
                continue

            text = f"{place.name} {place.address}"
            is_food = any(term in text for term in MEAL_TEXT_TERMS)
            is_area_like = any(term in text for term in ["滨江", "江边", "步道", "公园", "绿地", "景区", "广场", "码头"])
            if is_food and not is_area_like:
                continue

            if not _is_valid_route_poi_ctx(place.typecode, place.name, parsed_intent):
                continue

            data = place.model_dump()
            data["time_capacity"] = "quarter_day" if parsed_intent.time_budget <= 0.25 else (data.get("time_capacity") or "half_day")
            data["enrichment_text"] = data.get("enrichment_text") or "用户指定区域的短途游览锚点"
            data["enrichment_heat"] = max(float(data.get("enrichment_heat") or 0.0), 0.5)
            fallback_places.append(ExtractedPlace(**data))
            break

        if fallback_places:
            break

    if fallback_places:
        print(f"[DEBUG step2] activity fallback anchors={[(p.name, p.location) for p in fallback_places]}")
    return fallback_places


async def _fallback_campus_canteen_places(
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
) -> list[ExtractedPlace]:
    """Fallback anchor for "X大学食堂 + 校园游览".

    The route anchor must be the requested campus, not an arbitrary nearby
    attraction. Around-search can return many internal facilities that fail
    generic route validation, so this fallback preserves the campus itself or
    highly recognizable campus landmarks.
    """
    if (getattr(parsed_intent, "activity_facet", "") or "") != "campus_canteen_visit":
        return []
    university = _campus_canteen_university_name(parsed_intent)
    if not university:
        return []
    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    campus_terms = {
        university,
        university.replace("北京大学", "北大"),
        "未名湖" if university == "北京大学" else "",
        "博雅塔" if university == "北京大学" else "",
    }
    campus_terms = {term for term in campus_terms if term}
    queries = [
        university,
        f"{university} 校园",
        f"{university} 西门",
        f"{university} 未名湖" if university == "北京大学" else f"{university} 校内",
        f"{university} 博雅塔" if university == "北京大学" else f"{university} 食堂",
    ]

    results: list[ExtractedPlace] = []
    seen: set[str] = set()
    for query in queries:
        try:
            raws = await gaode_text_search(query, city=city, show_fields=config.GAODE_SHOW_FIELDS)
        except Exception as exc:
            print(f"[WARN step2] campus_canteen fallback search failed query={query}: {exc}")
            continue
        for raw in raws[:8]:
            place = _to_extracted(raw)
            if not place or not place.location:
                continue
            text = f"{place.name} {place.address or ''}"
            if not any(term in text for term in campus_terms):
                continue
            if any(bad in text for bad in ["附属医院", "培训", "驾校", "家教", "东北大馅"]):
                continue
            if place.name in seen:
                continue
            seen.add(place.name)
            data = place.model_dump()
            data["time_capacity"] = "quarter_day" if parsed_intent.time_budget <= 0.25 else "half_day"
            data["recall_source"] = "campus_canteen_fallback"
            data["poi_role"] = "destination_anchor"
            data["enrichment_text"] = data.get("enrichment_text") or "用户指定的校园食堂游览锚点"
            results.append(ExtractedPlace(**data))
            if len(results) >= 4:
                break
        if results:
            break

    print(
        f"[DEBUG step2] campus_canteen fallback university={university} "
        f"found={[(p.name, p.typecode) for p in results[:4]]}"
    )
    return results


def _infer_meal_from_time(parsed_intent: ParsedIntent) -> str | None:
    """v6: 根据 start_time 推断 meal 类型"""
    st = parsed_intent.start_time
    if st is None:
        return "lunch"  # 默认午餐
    hour = st.hour + st.minute / 60
    if 10.5 <= hour < 14:
        return "lunch"
    if 16.5 <= hour < 21:
        return "dinner"
    if 6 <= hour < 10.5:
        return "lunch"
    return "dinner"  # 晚间默认 dinner


def _has_requested_dinner(parsed_intent: ParsedIntent) -> bool:
    meal_needs = parsed_intent.meal_needs
    if all(isinstance(item, str) for item in meal_needs):
        return "dinner" in meal_needs
    return bool(meal_needs and "dinner" in meal_needs[0])


def _assemble_plan(
    anchors: list[AnchorPlan],
    parsed_intent: ParsedIntent,
    user_profile: UserProfile,
    delete_list: list[str],
    fixed_budget: float,
    budget_threshold: float,
) -> CompletePlan:
    max_days = _target_day_count(parsed_intent)
    print(
        f"[DEBUG step2 assemble] START anchors={[(a.name, a.final_capacity or a.time_capacity) for a in anchors]} "
        f"max_days={max_days} delete_list={delete_list[:10]} "
        f"meal_needs={parsed_intent.meal_needs} time_budget={parsed_intent.time_budget}"
    )
    day_bins: list[dict[str, Any]] = [{"anchors": [], "used": 0.0, "long_transit_used": False} for _ in range(max_days)]
    single_day_capacity = 1.25 if max_days == 1 and parsed_intent.evening_requested else 1.0
    remaining = list(enumerate(anchors))
    for day_index, day_bin in enumerate(day_bins, start=1):
        if not remaining:
            break
        start_pos = next(
            (
                pos
                for pos, (_, item) in enumerate(remaining)
                if _anchor_allowed_on_day(item, parsed_intent, day_index)
                and capacity_budget(item.final_capacity or item.time_capacity) <= single_day_capacity + 0.001
            ),
            None,
        )
        if start_pos is None:
            continue
        original_index, anchor = remaining.pop(start_pos)
        budget = capacity_budget(anchor.final_capacity or anchor.time_capacity)
        day_bin["anchors"].append((original_index, anchor))
        day_bin["used"] += budget
        # v5.2: full_day锚点不再强制独占一天；如果还有其他锚点待分配，允许配对
        # （用户说"上午去A，下午去B"时，两个锚点应在同一天）
        origin_transit = anchor.transit_from_origin_min or 0
        if origin_transit > 60:
            day_bin["long_transit_used"] = True
        while remaining:
            fit_candidates = [
                (idx, item)
                for idx, item in remaining
                if _anchor_allowed_on_day(item, parsed_intent, day_index)
                if day_bin["used"] + capacity_budget(item.final_capacity or item.time_capacity) <= single_day_capacity + 0.001
            ]
            if not fit_candidates:
                break
            last_anchor = day_bin["anchors"][-1][1]
            fit_candidates.sort(
                key=lambda item: (
                    haversine_km(last_anchor.location, item[1].location),
                    item[0],
                ),
            )
            best_index, best_anchor = fit_candidates[0]
            est_transit = haversine_km(last_anchor.location, best_anchor.location) * 4.0
            if day_bin["long_transit_used"] and est_transit > 35:
                fit_candidates = [
                    (idx, item) for idx, item in fit_candidates
                    if haversine_km(last_anchor.location, item.location) * 4.0 <= 35
                ]
                if not fit_candidates:
                    break
                best_index, best_anchor = fit_candidates[0]
                est_transit = haversine_km(last_anchor.location, best_anchor.location) * 4.0
            if est_transit > 60 and not day_bin["long_transit_used"]:
                day_bin["long_transit_used"] = True
            remaining.remove((best_index, best_anchor))
            day_bin["anchors"].append((best_index, best_anchor))
            day_bin["used"] += capacity_budget(best_anchor.final_capacity or best_anchor.time_capacity)

    day_plans: list[DayPlan] = []
    for index, day_bin in enumerate(day_bins, start=1):
        day_anchors = [anchor for _, anchor in sorted(day_bin["anchors"], key=lambda item: item[0])]
        day_anchors = _order_day_anchors(day_anchors, parsed_intent)
        # v6: 即使没有 anchors，强餐饮意图也需要 meal slots
        meal_slots = _meal_slots_for_day(parsed_intent, index)
        if not day_anchors and not meal_slots:
            meal_slots = []
        # v20: a full day 且时间范围覆盖晚餐窗口时，不得因 anchor 数量少删除 dinner
        # meal_needs 中已计算出的 dinner 应视为明确需要
        _full_day_covers_dinner = (
            parsed_intent.time_budget >= 1.0
            and "dinner" in (parsed_intent.meal_needs if isinstance(parsed_intent.meal_needs, list) else [])
        )
        _should_keep_dinner = (
            parsed_intent.evening_requested
            or _has_requested_dinner(parsed_intent)
            or _full_day_covers_dinner
        )
        if len(day_anchors) <= 1 and not _should_keep_dinner:
            meal_slots_before = [s.get("meal") for s in meal_slots]
            meal_slots = [slot for slot in meal_slots if slot.get("meal") != "dinner"]
            print(
                f"[DEBUG step2 assemble] dinner removed: "
                f"day_anchors={len(day_anchors)} meal_slots_before={meal_slots_before} "
                f"meal_slots_after={[s.get('meal') for s in meal_slots]}"
            )
        day_plans.append(DayPlan(day_index=index, anchors=day_anchors, meal_slots=meal_slots))

    city = user_profile.permanent_city[0] if user_profile.permanent_city else ""
    return CompletePlan(
        time_budget=parsed_intent.time_budget,
        fixed_budget=fixed_budget,
        remaining_budget=max(0.0, parsed_intent.time_budget - fixed_budget),
        day_plans=day_plans,
        delete_list=delete_list,
        city=city,
        transport=parsed_intent.transport_hint or "公共交通",
        budget_threshold=budget_threshold,
        request_budget_per_capita=parsed_intent.budget_per_capita,
    )


async def run_step2(parsed_intent: ParsedIntent, user_profile: UserProfile, logger: PipelineLogger) -> CompletePlan:
    # v21: Preserve city from previous route context if home differs
    _prev_city = getattr(parsed_intent, "resolved_city", "") or ""
    resolved_city = await _resolve_city_from_profile(user_profile)
    if _prev_city and resolved_city != _prev_city:
        _city_short = lambda c: c[:-1] if c.endswith("市") else c
        if _city_short(resolved_city) != _city_short(_prev_city):
            # Previous context has a different city — preserve it
            resolved_city = _prev_city
            print(f"[DEBUG step2] preserved previous city: {resolved_city} (home={await _resolve_city_from_profile(user_profile)})")
    _apply_resolved_city(user_profile, resolved_city)
    parsed_intent.resolved_city = resolved_city
    parsed_intent.search_keywords = canonicalize_search_keywords(
        list(parsed_intent.search_keywords or []),
        resolved_city,
        limit=8,
    )
    print(
        f"[DEBUG step2] resolved_city_from_home={resolved_city} "
        f"permanent_city={getattr(user_profile, 'permanent_city', [])} "
        f"search_keywords={parsed_intent.search_keywords}"
    )

    # v6: planned 模式跳过宏观搜索，直接返回轻量 CompletePlan
    if getattr(parsed_intent, 'plan_mode', 'exploratory') == 'planned' and getattr(parsed_intent, 'planned_waypoints', []):
        city = user_profile.permanent_city[0] if user_profile.permanent_city else "上海市"
        budget_threshold = _budget_threshold(parsed_intent, user_profile)
        print(
            "[DEBUG step2] planned 模式 — 跳过宏观搜索，返回轻量 CompletePlan "
            f"budget_threshold={budget_threshold} request_budget={parsed_intent.budget_per_capita}"
        )
        return CompletePlan(
            time_budget=0.5,
            fixed_budget=0.0,
            remaining_budget=0.5,
            day_plans=[],
            city=city,
            transport=getattr(parsed_intent, 'transport_hint', '公共交通') or '公共交通',
            budget_threshold=budget_threshold,
            request_budget_per_capita=parsed_intent.budget_per_capita,
        )

    fixed_anchors = await _fixed_anchors(parsed_intent, user_profile)
    fixed_budget = sum(capacity_budget(anchor.final_time_budget or anchor.final_capacity or anchor.time_capacity) for anchor in fixed_anchors)
    budget_threshold = _budget_threshold(parsed_intent, user_profile)
    candidates: list[ScoredPlace] = []
    delete_list: list[str] = []

    # v9: 探索模式下，即使 fixed anchors 填满预算，也跑 Bocha 富化
    # v20: poi_category/named_poi queries MUST always execute target recall
    _poi_qtype = getattr(parsed_intent, "poi_query_type", "") or ""
    _primary_q = getattr(parsed_intent, "primary_query", "") or ""
    _proximity_req = bool(getattr(parsed_intent, "proximity_requested", False))
    _has_search_center = (
        bool(getattr(parsed_intent, "search_area_location", None))
        or bool(getattr(parsed_intent, "search_area_label", None))
    )
    # v20: must_recall_target is ONLY for concrete POI queries, not theme routes.
    # "雅致路线" / "文艺路线" are theme_route — must NOT set must_recall_target.
    _has_registered_category = bool(
        getattr(parsed_intent, "category_id", None)
        or getattr(parsed_intent, "allowed_typecode_prefixes", None)
    )
    _must_recall_target = (
        _poi_qtype in ("poi_category", "named_poi")
        and _has_registered_category
    )

    should_skip_search = bool(
        fixed_anchors and fixed_budget >= parsed_intent.time_budget
        and not _must_recall_target  # v20: never skip when user has explicit target
    )
    is_exploratory = getattr(parsed_intent, 'plan_mode', 'exploratory') != 'planned'
    if should_skip_search and is_exploratory and fixed_anchors:
        # 仅富化 fixed anchors 本身，不跑宏观搜索
        city_name = user_profile.permanent_city[0] if user_profile.permanent_city else ""
        # 把 fixed anchors 转为 ExtractedPlace 供 enrich 使用
        fixed_places: list[ExtractedPlace] = []
        for anchor in fixed_anchors:
            loc = anchor.location or {}
            p = ExtractedPlace(
                name=anchor.name,
                location={"lat": loc.get("lat", 0), "lng": loc.get("lng", 0)},
                typecode=anchor.typecode or "",
                time_capacity=anchor.final_capacity or anchor.time_capacity or "half_day",
                gaode_rating=None,
                avg_cost=None,
                address="",
                district="",
                enrichment_text="",
                enrichment_heat=0.0,
                gaode_poi_id="",
            )
            fixed_places.append(p)
        await emit_status("正在补充目的地详情...")
        await _enrich_places(fixed_places, city_name)
        print(f"[DEBUG step2] enriched {len(fixed_places)} fixed anchor(s) without macro search")

    if not should_skip_search:
        logger.start_step("step_2_1_gaode_search")
        await emit_status("正在搜索周边好去处...")
        # v20: Search center priority:
        # 1. search_area_location (from proximity parsing)
        # 2. fixed anchor locations (when fixed anchors are destinations, not search centers)
        # 3. original_location (home)
        _search_center = None
        _search_center_label = ""
        if parsed_intent.search_area_location:
            _search_center = [parsed_intent.search_area_location]
            _search_center_label = getattr(parsed_intent, "search_area_label", "") or "search_area"
            print(
                f"[DEBUG macro search] search_center_source=search_area_location "
                f"label={_search_center_label} "
                f"loc=({_search_center[0].get('lat','')},{_search_center[0].get('lng','')})"
            )
        elif fixed_anchors and not parsed_intent.is_search_center_only:
            _search_center = [anchor.location for anchor in fixed_anchors]
            _search_center_label = ", ".join(a.name for a in fixed_anchors)
            print(f"[DEBUG macro search] search_center_source=fixed_anchors label={_search_center_label}")
        else:
            _search_center = [parsed_intent.original_location] if parsed_intent.original_location else None
            _search_center_label = "original_location"
            print(f"[DEBUG macro search] search_center_source=original_location label={_search_center_label}")

        central_locations = _search_center
        print(
            f"[DEBUG macro search] "
            f"should_skip_search={should_skip_search} "
            f"must_recall_target={_must_recall_target} "
            f"primary_query={_primary_q} "
            f"poi_query_type={_poi_qtype} "
            f"keywords={parsed_intent.search_keywords[:4]} "
            f"radius={'proximity' if _proximity_req else 'default'} "
        )
        raw_places = await _search_macro_places(parsed_intent, central_locations=central_locations)
        places = _dedupe_places(raw_places)
        deduped_count = len(places)
        capacity_rejects = _capacity_rejects_for_macro_search(parsed_intent)
        capacity_filtered = [place for place in places if place.time_capacity in capacity_rejects]
        places = [place for place in places if place.time_capacity not in capacity_rejects]
        places, deleted = _budget_filter(places, budget_threshold)

        # local_life is a semantic scene rather than a POI name.  Run its
        # evidence-aware nearby recall even when generic macro search returned
        # something: non-empty but unrelated results must not suppress the
        # fallback (the previous behaviour selected aquariums/scenic spots).
        _pre_activity_facet = getattr(parsed_intent, "activity_facet", "") or ""
        _pre_is_local_life = bool(getattr(parsed_intent, "local_life_requested", False))
        if _pre_is_local_life or _pre_activity_facet == "local_life":
            verified_local_places = await _fallback_local_life_places(parsed_intent, user_profile)
            if not verified_local_places:
                raise ZeroOutputError(
                    "附近暂未找到能够核实为市集、菜市场或本地生活街区的地点，已将搜索范围扩大至15公里。"
                )
            places = verified_local_places
            deleted = []
            print(
                f"[DEBUG step2] local_life evidence recall replaced generic candidates: "
                f"count={len(places)} names={[p.name for p in places[:6]]}"
            )
        if not places:
            await logger.log_step(
                "step_2_1_gaode_search",
                status="empty",
                output_count=0,
                details={
                    "search_keywords": parsed_intent.search_keywords,
                    "raw_count": len(raw_places),
                    "deduped_count": deduped_count,
                    "capacity_rejects": capacity_rejects,
                    "capacity_filtered": [
                        {"name": place.name, "typecode": place.typecode, "capacity": place.time_capacity}
                        for place in capacity_filtered[:20]
                    ],
                    "budget_threshold": budget_threshold,
                    "request_budget_per_capita": parsed_intent.budget_per_capita,
                    "budget_deleted": deleted,
                },
            )
            # v12: 混合任务（游览+餐饮）禁止直接 meal-only，先尝试活动 fallback
            # v20: 直接品类查询不得进入 meal-only；无结果时提示无匹配
            _poi_qtype = getattr(parsed_intent, "poi_query_type", "") or ""
            _explicit_meal = bool(getattr(parsed_intent, "explicit_meal_intent", False))
            _primary_q = getattr(parsed_intent, "primary_query", "") or ""
            _is_quiet_retreat = bool(getattr(parsed_intent, "quiet_retreat_requested", False))
            _is_lawn_rest = bool(getattr(parsed_intent, "lawn_rest_requested", False))
            _is_open_terrace = bool(getattr(parsed_intent, "open_terrace_requested", False))
            _is_local_life = bool(getattr(parsed_intent, "local_life_requested", False))
            _is_stress_relief = bool(getattr(parsed_intent, "stress_relief_requested", False))
            _is_rest_stop = bool(getattr(parsed_intent, "rest_stop_requested", False))
            _activity_facet = getattr(parsed_intent, "activity_facet", "") or ""

            # v21: Rest stop fallback — progressive radius around search area
            if _is_rest_stop or _activity_facet == "rest_stop":
                rest_places = await _fallback_rest_stop_places(parsed_intent, user_profile)
                if rest_places:
                    places = rest_places
                    deleted = []
                    print(f"[DEBUG step2] rest_stop fallback found {len(places)} candidates")
                else:
                    _area = getattr(parsed_intent, "search_area_label", "") or "附近"
                    raise ZeroOutputError(
                        f"{_area}暂未找到能够核实为可坐、可公开进入的歇脚场所，已将范围扩大至5公里。"
                        f"你也可以告诉我更偏向咖啡馆、书店还是公园休息区。"
                    )
            # v21: Stress relief fallback
            elif _is_stress_relief or _activity_facet == "stress_relief":
                stress_places = await _fallback_stress_relief_places(parsed_intent, user_profile)
                if stress_places:
                    places = stress_places
                    deleted = []
                    print(f"[DEBUG step2] stress_relief fallback found {len(places)} candidates")
                else:
                    raise ZeroOutputError(
                        "附近暂未找到当前可进入的放松或解压活动场所，已将搜索范围扩大至15公里。"
                        "可以告诉我你更想安静放空、运动发泄，还是做点手工体验。"
                    )
            # v21: Local life / market fallback — search for markets, old streets, community commercial
            elif _is_local_life or _activity_facet == "local_life":
                local_places = await _fallback_local_life_places(parsed_intent, user_profile)
                if local_places:
                    places = local_places
                    deleted = []
                    print(f"[DEBUG step2] local_life fallback found {len(places)} candidates")
                else:
                    raise ZeroOutputError(
                        "附近暂未找到能够核实为市集、菜市场或本地生活街区的地点，已将搜索范围扩大至15公里。"
                    )
            # v21: Open terrace fallback — expand search with terrace categories
            elif _is_open_terrace or _activity_facet == "open_terrace":
                terrace_places = await _fallback_open_terrace_places(parsed_intent, user_profile)
                if terrace_places:
                    places = terrace_places
                    deleted = []
                    print(f"[DEBUG step2] open_terrace fallback found {len(places)} candidates")
                else:
                    raise ZeroOutputError(
                        "附近暂未找到能够核实为公众开放的露台地点，已将搜索范围扩大至10公里。"
                    )
            # v21: Lawn rest fallback — expand search with parks, green spaces
            elif _is_lawn_rest or _activity_facet == "lawn_rest":
                lawn_places = await _fallback_lawn_rest_places(parsed_intent, user_profile)
                if lawn_places:
                    places = lawn_places
                    deleted = []
                    print(f"[DEBUG step2] lawn_rest fallback found {len(places)} candidates")
                else:
                    raise ZeroOutputError(
                        "附近暂未找到有明确开放草坪证据的地点，可为你扩大一点搜索范围再试试。"
                    )
            # v20: Quiet retreat fallback — expand search with concrete categories + wider radius
            elif _is_quiet_retreat or _activity_facet == "quiet_retreat":
                quiet_places = await _fallback_quiet_retreat_places(parsed_intent, user_profile)
                if quiet_places:
                    places = quiet_places
                    deleted = []
                    print(f"[DEBUG step2] quiet_retreat fallback found {len(places)} candidates")
                else:
                    # Last resort: mention that we couldn't find confirmed quiet spots nearby
                    raise ZeroOutputError(
                        "附近暂未找到有明确安静环境证据的场所，可为你扩大一点搜索范围再试试。"
                    )
            elif _poi_qtype in ("poi_category", "named_poi") and not _explicit_meal:
                # Try synonym wide recall once
                wide_places = await _synonym_wide_recall(parsed_intent, user_profile)
                if wide_places:
                    places = wide_places
                    deleted = []
                    print(f"[DEBUG step2] poi_category wide recall found {len(places)} candidates")
                else:
                    if _is_concrete_target(parsed_intent):
                        raise ZeroOutputError(f"未找到与「{_primary_q}」匹配的地点，请尝试修改搜索范围或关键词")
                    else:
                        raise ZeroOutputError(f"未找到符合您需求的路线地点，请尝试调整搜索范围")
            else:
                campus_places = await _fallback_campus_canteen_places(parsed_intent, user_profile)
                if campus_places:
                    places = campus_places
                    deleted = []
                    print("[DEBUG step2] macro places empty, using campus_canteen fallback")
                else:
                    fallback_places = await _fallback_activity_places(parsed_intent, user_profile)
                    if fallback_places:
                        places = fallback_places
                        deleted = []
                        print("[DEBUG step2] macro places empty, using activity fallback instead of meal-only")
                    elif _has_strong_meal_intent(parsed_intent) and not _has_non_meal_explore_intent(parsed_intent):
                        print("[DEBUG step2] 宏观 anchor 为空且为纯餐饮意图，进入 meal-only 流程")
                    else:
                        raise ZeroOutputError("宏观 POI 搜索结果为空或全部被过滤")
        delete_list.extend(deleted)
        await logger.log_step(
            "step_2_1_gaode_search",
            output_count=len(places),
            details={
                "search_keywords": parsed_intent.search_keywords,
                "raw_count": len(raw_places),
                "deduped_count": deduped_count,
                "capacity_rejects": capacity_rejects,
                "capacity_filtered": [
                    {"name": place.name, "typecode": place.typecode, "capacity": place.time_capacity}
                    for place in capacity_filtered[:20]
                ],
                "budget_threshold": budget_threshold,
                "request_budget_per_capita": parsed_intent.budget_per_capita,
                "places": [
                    {"name": place.name, "typecode": place.typecode, "capacity": place.time_capacity}
                    for place in places[:20]
                ],
            },
        )

        logger.start_step("step_2_3_bocha_enrich")
        await emit_status("正在补充目的地详情...")
        # v4.1 F7: 并行启动 bocha enrich 和 transit route 预查询
        # 1. haversine-only 预排，选出 top-8 供 route API 调用
        city_name = user_profile.permanent_city[0] if user_profile.permanent_city else ""
        TOP_N_REAL_ROUTE = 4
        origin_loc = parsed_intent.original_location
        if origin_loc and len(places) > TOP_N_REAL_ROUTE:
            pre_ranked = []
            for place in places:
                est_transit = haversine_km(origin_loc, place.location) * 4.0
                fast_score = (place.gaode_rating or 4.0) / 5.0 * 30 + max(0.0, 1.0 - est_transit / 60) * 20
                pre_ranked.append((fast_score, place, est_transit))
            pre_ranked.sort(key=lambda x: x[0], reverse=True)
            top_places_for_route = [p for _, p, _ in pre_ranked[:TOP_N_REAL_ROUTE]]
        else:
            top_places_for_route = list(places)
        # 2. 并行：bocha enrich + transit route calls
        enrich_task = asyncio.create_task(_enrich_places(places, city_name))

        async def _fetch_routes():
            return await asyncio.gather(*[
                _route_from_origin_bounded(parsed_intent, p, city_name)
                for p in top_places_for_route
            ])

        route_task = asyncio.create_task(_fetch_routes())
        places_enriched, top_routes = await asyncio.gather(enrich_task, route_task)
        # 构建 transit 映射
        transit_map: dict[str, float | None] = {}
        for place, route in zip(top_places_for_route, top_routes):
            pid = getattr(place, "gaode_poi_id", None) or place.name
            transit_map[pid] = route.get("duration_min") if route else None
        await logger.log_step("step_2_3_bocha_enrich", output_count=min(len(places_enriched), 10))

        # v15: 主题召回 — 用博查搜索主题攻略语义，补充 destination_anchor
        theme_recall_places = await _theme_recall_places(parsed_intent, user_profile, city_name)
        if theme_recall_places:
            places_enriched = list(places_enriched) + theme_recall_places

        # v20: District boundary filter — reject candidates outside requested admin district
        _search_area_label = str(getattr(parsed_intent, "search_area_label", "") or "")
        _is_admin_district = bool(re.search(
            r"(?:区|县|镇|乡|街道|商圈|片区|新城|新区)$", _search_area_label
        ))
        if _is_admin_district and places_enriched:
            _search_adcode = str(getattr(parsed_intent, "search_area_adcode", "") or "")
            # Save before list for accurate audit
            _before_places = list(places_enriched)
            before_count = len(_before_places)
            inside_places = [
                p for p in _before_places
                if _place_matches_district_raw(p, _search_area_label, _search_adcode)
            ]
            rejected_places = [
                p for p in _before_places
                if not _place_matches_district_raw(p, _search_area_label, _search_adcode)
            ]
            places_enriched = inside_places
            after_count = len(inside_places)
            if after_count < before_count:
                rejected = before_count - after_count
                print(
                    f"[AreaScopeAudit] district_filter: {_search_area_label} "
                    f"before={before_count} after={after_count} rejected={rejected}"
                )
                for rp in rejected_places:
                    print(
                        f"[AreaScopeAudit]   REJECTED: name={getattr(rp, 'name', '?')} "
                        f"adname={getattr(rp, 'district', '?')} "
                        f"adcode={getattr(rp, 'adcode', '?')} "
                        f"reason=outside_{_search_area_label}"
                    )

        logger.start_step("step_2_4_scoring")
        await emit_status("正在评估和筛选目的地...")
        # v4.1 F7: 直接用已预查的 transit 结果，不再重复 API 调用
        candidates = _score_places_prefetched(places_enriched, parsed_intent, user_profile, transit_map)

        # v20: Apply intent-based filtering for poi_category/named_poi queries
        if candidates:
            candidates = _filter_candidates_by_intent(candidates, parsed_intent)

        if not candidates:
            # v20: 直接品类查询不得进入 meal-only
            _poi_qtype = getattr(parsed_intent, "poi_query_type", "") or ""
            _explicit_meal = bool(getattr(parsed_intent, "explicit_meal_intent", False))
            _primary_q = getattr(parsed_intent, "primary_query", "") or ""
            if _is_concrete_target(parsed_intent) and not _explicit_meal:
                raise ZeroOutputError(f"未找到与「{_primary_q}」匹配的地点，请尝试修改搜索范围或关键词")
            # v12: 混合任务禁止直接 meal-only
            if _has_strong_meal_intent(parsed_intent) and not _has_non_meal_explore_intent(parsed_intent):
                candidates = []
                print("[DEBUG step2] 评分后无可用候选且为纯餐饮意图，进入 meal-only 流程")
            else:
                raise ZeroOutputError("宏观 POI 评分后无可用候选")
        await logger.log_step(
            "step_2_4_scoring",
            output_count=len(candidates),
            details={
                "candidates": [
                    {
                        "name": item.name,
                        "typecode": item.typecode,
                        "capacity": item.final_capacity or item.time_capacity,
                        "score": item.final_score,
                        "transit_min": item.transit_from_origin_min,
                    }
                    for item in candidates[:20]
                ]
            },
        )

    logger.start_step("step_2_5_pairing")
    await emit_status("正在匹配最优组合...")
    pool_size = max(config.POOL_SIZE, 20) if "二次元" in parsed_intent.raw_keywords else config.POOL_SIZE
    selected = _select_anchors(fixed_anchors, candidates[:pool_size], parsed_intent)
    if not selected:
        # v20: 直接品类查询不得进入 meal-only
        _poi_qtype = getattr(parsed_intent, "poi_query_type", "") or ""
        _explicit_meal = bool(getattr(parsed_intent, "explicit_meal_intent", False))
        _primary_q = getattr(parsed_intent, "primary_query", "") or ""
        if _is_concrete_target(parsed_intent) and not _explicit_meal:
            raise ZeroOutputError(f"未找到与「{_primary_q}」匹配的地点，请尝试修改搜索范围或关键词")
        if _has_strong_meal_intent(parsed_intent) and not _has_non_meal_explore_intent(parsed_intent):
            selected = []
            print("[DEBUG step2] 无可用路线锚点且为纯餐饮意图，进入 meal-only 流程")
        else:
            raise ZeroOutputError("未匹配到可用路线锚点")
    # v3新增 (step_2_5_5)：确定每个锚点的final_time_budget
    selected = _assign_anchor_time_budget(selected, parsed_intent)
    plan = _assemble_plan(selected, parsed_intent, user_profile, delete_list, fixed_budget, budget_threshold)
    parsed_intent.search_centrality = [
        SearchCentralityItem(name=anchor.name, score=anchor.final_score, location=anchor.location)
        for day in plan.day_plans
        for anchor in day.anchors
    ]
    await logger.log_step(
        "step_2_5_pairing",
        output_count=len(parsed_intent.search_centrality),
        details={
            "selected": [
                {
                    "day": day.day_index,
                    "name": anchor.name,
                    "capacity": anchor.final_capacity,
                    "typecode": anchor.typecode,
                    "score": anchor.final_score,
                    "requested_day": _requested_day_for_anchor(anchor, parsed_intent),
                }
                for day in plan.day_plans
                for anchor in day.anchors
            ],
            "meal_slots": [
                {"day": day.day_index, "slots": day.meal_slots}
                for day in plan.day_plans
            ],
        },
    )
    return plan
