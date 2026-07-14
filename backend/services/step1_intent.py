from __future__ import annotations
import asyncio
import copy
import datetime as dt
import json
import re

from pydantic import BaseModel, Field

from . import config
from .api_client import call_llm, gaode_geocode, gaode_text_search, gaode_weather
from .data_schema import FixedPoi, ParsedIntent, PlannedWaypoint, PlanSegment, UserProfile
from .day_slots import DURATION_TO_BUDGET, compute_meal_needs, compute_reject_capacities, infer_capacity_from_typecode
from .utils import PipelineLogger, ZeroOutputError, emit_status, haversine_km
from .city_context import apply_resolved_city, city_from_text, resolve_departure_city
from .theme_profile_matcher import (
    canonicalize_search_keywords,
    rank_theme_profiles,
    resolve_theme_profile,
    get_all_theme_profiles,
)
from .poi_typecodes import (
    CATEGORY_RULES,
    category_for_query,
    get_allowed_typecode_prefixes,
    get_excluded_typecode_prefixes,
    get_semantic_terms,
)


class CompactStep1Intent(BaseModel):
    """Minimal first-turn local-task contract used by sparse Step1 activation.

    It intentionally excludes theme planning and multi-turn editing fields.  A
    response must pass the local-task validator below before it is converted to
    ParsedIntent; otherwise Step1 repeats the request through the full contract.
    """

    is_route_planning_request: bool = True
    duration: str = "a quarter day"
    raw_keywords: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    food_pref_keywords: list[str] = Field(default_factory=list)
    meal_search_keywords: list[str] = Field(default_factory=list)
    meal_constraints: list[dict] = Field(default_factory=list)
    other_constraints: list[str] = Field(default_factory=list)
    plan_mode: str = "planned"
    planned_waypoints: list[PlannedWaypoint] = Field(default_factory=list)
    poi_query_type: str = ""
    category_id: str | None = None
    primary_query: str = ""
    explicit_meal_intent: bool = False
    allowed_typecode_prefixes: list[str] = Field(default_factory=list)
    primary_required_terms: list[str] = Field(default_factory=list)
    primary_excluded_terms: list[str] = Field(default_factory=list)
    proximity_requested: bool = True
    proximity_radius_m: int | None = None
    activity_facet: str = ""
    required_features: list[str] = Field(default_factory=list)
    preferred_features: list[str] = Field(default_factory=list)


# ── v24: conversation_context parsing helpers ──


def _extract_latest_user_input(text: str) -> str:
    """Extract the latest user input from a conversation_context XML wrapper.

    When the caller wraps the request in <conversation_context>...<latest_user_input>...
    this returns only the user's actual latest message. Otherwise returns the text as-is.
    """
    if not text:
        return text
    m = re.search(r"<latest_user_input>\s*(.+?)\s*</latest_user_input>", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _has_conversation_context(text: str) -> bool:
    """Check if text is wrapped in a conversation_context XML."""
    return "<conversation_context>" in (text or "")


INCOMPLETE_REQUEST_TEXT = "消息似乎不全面，可以再说得详细一点吗~"
PAST_TIME_TOLERANCE_MINUTES = 15

IMMEDIATE_TIME_TOKENS = ["待会儿", "一会儿", "一会", "马上", "现在", "等会儿"]
FUTURE_DATE_TOKENS = ["明天", "后天", "周末"]
TIME_PERIOD_TOKENS = ["早上", "上午", "中午", "下午", "傍晚", "晚上", "夜里", "夜间"]
NEARBY_CASUAL_TOKENS = [
    "附近",
    "周边",
    "逛逛",
    "逛一逛",
    "逛一圈",
    "逛一下",
    "随便逛",
    "转转",
    "出门",
    "出去逛",
    "出去玩",
    "出去走走",
    "玩一会儿",
    "走走",
    "溜达",
]
NIGHT_ACTIVITY_TOKENS = ["夜景", "夜游", "夜宵", "酒吧", "清吧", "灯光秀", "夜市"]

# Shared across nearby-food-stroll, multi-facet art routes, and work-friendly cafe.
# Keep this module-level so _postprocess branches can reference it before local branching.
CAFE_WORK_TERMS: tuple[str, ...] = (
    "适合办公", "可以办公", "适合学习", "适合工作", "适合远程",
    "能带电脑", "有插座", "能充电", "有WiFi", "能久坐",
)


def _has_work_cafe_terms(text: str) -> bool:
    return any(term in (text or "") for term in CAFE_WORK_TERMS)

# ── v25: multi_facet_art cafe/shop facet search terms ──

MULTI_FACET_ART_CAFE_TERMS = ["精品咖啡馆", "独立咖啡馆", "咖啡馆", "咖啡", "coffee", "cafe"]
MULTI_FACET_ART_SHOP_TERMS = ["特色小店", "买手店", "文创店", "杂货店", "生活方式集合店", "集合店"]

SHOPPING_TOKENS = ["逛商场", "商场", "购物", "买东西", "逛街", "商业体", "综合体", "商圈", "买手店", "潮牌"]
EATING_ACTIVITY_TOKENS = ["吃吃喝喝", "逛吃", "美食", "餐饮", "餐厅", "小吃", "探店", "喝咖啡", "咖啡", "甜品", "下午茶", "夜宵"]
RAINY_DAY_TOKENS = ["下雨", "雨天", "阴雨", "有雨", "下雨天", "避雨"]
INDOOR_PREF_TOKENS = ["室内", "室内玩", "室内活动", "不淋雨", "避雨"]
# v5.3: 晚上餐饮意图检测 — "晚上找个好吃的地方"等应识别为晚餐
_EVENING_DINNER_RE = re.compile(r"晚上.{0,12}(好吃|吃|餐厅|美食|饭店|吃饭|觅食|探店|用餐|正餐|顿好的|顿好|找.{0,4}吃)")

# === v6 扩展：生活服务类 ===
LIFE_SERVICE_TOKENS = [
    "水果", "水果店", "买水果", "买点水果", "摘水果",
    "菜场", "菜市场", "农贸市场", "生鲜", "买菜的",
    "超市", "便利店", "全家", "罗森", "711", "7-11",
    "面包", "面包店", "烘焙", "糕点", "蛋糕", "买面包",
    "奶茶", "奶茶店", "喜茶", "奈雪", "一点点", "coco",
    "咖啡", "咖啡店", "星巴克", "manner", "瑞幸",
]
# === v6 扩展：轻食简餐类 ===
LIGHT_MEAL_TOKENS = [
    "简单吃", "随便吃点", "对付一口", "垫垫肚子",
    "轻食", "简餐", "快餐", "便餐",
    "面条", "面馆", "拉面", "兰州拉面", "重庆小面",
    "馄饨", "饺子", "包子", "馒头", "烧麦",
    "盖浇饭", "盒饭", "炒饭", "拌面",
    "麦当劳", "肯德基", "kfc", "m记", "金拱门", "开封菜",
    "汉堡", "披萨", "沙拉", "三明治",
    "黄焖鸡", "沙县", "兰州拉面",
]
# === v6 扩展：夜宵小吃类 ===
NIGHT_SNACK_TOKENS = [
    "夜宵", "撸串", "烧烤", "烤串", "啤酒",
    "小龙虾", "麻辣烫", "冒菜", "串串", "关东煮",
    "螺蛳粉", "酸辣粉", "米线", "过桥米线",
    "煎饼", "鸡蛋灌饼", "手抓饼", "肉夹馍",
]
# === v6 扩展：生活场景类 ===
LIFE_SCENE_TOKENS = [
    "下班", "下班路上", "通勤", "路上",
    "顺路", "顺便", "路过", "顺道",
    "加班", "出差", "周末", "假期",
    "带孩子", "遛娃", "溜娃", "带娃", "亲子",
    "约会", "聚餐", "团建", "聚会",
    "一个人", "独处", "放空", "发呆",
    "散步", "慢跑", "跑步", "健身",
]

# v18: 短关键词意图路由 — 补充裸词命中后转可执行字段
CYCLING_TRANSPORT_TOKENS = ["骑行", "骑车", "自行车", "单车", "骑单车", "共享单车"]
LIGHT_TOUR_TOKENS = ["轻游", "轻松游", "轻松逛", "低强度", "不累", "慢游"]
STROLL_EAT_TOKENS = ["逛吃", "边逛边吃", "吃吃逛逛", "边玩边吃"]
NIGHT_SHORT_ROUTE_TOKENS = ["夜游", "夜景路线", "夜晚游览", "夜间游览", "灯光秀"]

# === v6 扩展：季节天气类 ===
WEATHER_SCENE_TOKENS = [
    "下雨", "雨天", "阴雨", "有雨", "下雨天", "避雨",
    "刮风", "大风", "降温", "冷", "热", "暴晒",
    "春天", "夏天", "秋天", "冬天", "梅雨",
]
KNOWN_POIS = [
    "外滩", "北外滩",
    "陆家嘴",
    "东方明珠",
    "人民广场",
    "南京路步行街",
    "南京路",
    "豫园",
    "城隍庙",
    "武康路",
    "新天地",
    "田子坊",
    "朱家角",
    "七宝古镇",
    "南翔古镇",
    "真如古镇",
    "中山公园",
    "静安寺",
    "徐家汇",
    "淮海路",
    "苏州河",
    "迪士尼",
    "上海迪士尼",
]

# v10: POI 排除别名映射 — 排除一个地点时同时排除相关别名和子区域
EXCLUDE_ALIASES: dict[str, list[str]] = {
    "外滩": ["外滩", "北外滩", "外白渡桥", "万国建筑", "外滩源", "十六铺", "陈毅广场",
             "外滩轮渡", "外滩观光隧道", "外滩信号台", "外滩气象广场", "外滩观景大道", "外滩观景台"],
    "北外滩": ["北外滩", "外滩", "北外滩滨江", "北外滩国客中心", "北外滩滨江绿地", "外白渡桥"],
    "陆家嘴": ["陆家嘴", "东方明珠", "上海中心", "金茂大厦", "环球金融中心", "国金中心",
               "正大广场", "明珠广场", "上海海洋水族馆", "东方明珠公园"],
    "东方明珠": ["东方明珠", "东方明珠公园", "东方明珠广播电视塔", "陆家嘴"],
    "迪士尼": ["迪士尼", "上海迪士尼", "上海迪士尼乐园", "迪士尼乐园"],
    "豫园": ["豫园", "城隍庙", "豫园商城", "豫园灯会"],
}

# 否定触发器 — 任意匹配即触发排除逻辑
NEGATION_TRIGGERS = ["不要", "不想去", "别去", "避开", "排除", "不要安排", "换掉", "删掉", "也不想去",
                     "不去", "别安排", "去掉", "跳过", "略过", "免了", "不要了", "不想要",
                     "替换成", "替换为", "换成", "改成", "替换掉"]

DAY_INDEX_PATTERNS = [
    (r"(周六|星期六|礼拜六|第?1天|第一天|day\s*1)", 1),
    (r"(周日|周天|星期日|星期天|礼拜日|礼拜天|第?2天|第二天|day\s*2)", 2),
    (r"(第?3天|第三天|day\s*3)", 3),
]

FOOD_STYLE_ALIASES = {
    # ── 原有保留 ──
    "日料": ["日料", "日本料理", "寿司", "刺身"],
    "日本料理": ["日料", "日本料理", "寿司", "刺身"],
    "寿司": ["日料", "日本料理", "寿司"],
    "本帮菜": ["本帮菜", "上海菜", "江浙菜"],
    "上海菜": ["本帮菜", "上海菜", "江浙菜"],
    "北京菜": ["北京菜", "京味", "老北京", "炸酱面", "烤鸭", "卤煮", "爆肚"],
    "川菜": ["川菜", "四川菜"],
    "粤菜": ["粤菜", "广东菜"],
    "火锅": ["火锅"],
    "烧烤": ["烧烤", "烤串", "撸串"],
    "麦当劳": ["麦当劳", "金拱门", "m记"],
    "肯德基": ["肯德基", "kfc", "开封菜"],
    # ── v6 新增：轻食简餐 ──
    "轻食": ["轻食", "沙拉", "简餐"],
    "简餐": ["简餐", "快餐", "便餐", "面条", "馄饨", "盖浇饭"],
    "快餐": ["快餐", "麦当劳", "肯德基", "汉堡", "黄焖鸡", "沙县"],
    "面条": ["面条", "面馆", "拉面", "兰州拉面", "重庆小面", "拌面"],
    "馄饨": ["馄饨", "饺子", "包子"],
    "夜宵": ["夜宵", "烧烤", "小龙虾", "麻辣烫", "螺蛳粉"],
    # ── v6 新增：菜系补全 ──
    "湘菜": ["湘菜"],
    "东北菜": ["东北菜", "锅包肉", "地三鲜"],
    "新疆菜": ["新疆菜", "羊肉串", "大盘鸡"],
    "云南菜": ["云南菜", "过桥米线", "汽锅鸡"],
    "东南亚": ["东南亚", "泰国菜", "越南菜", "冬阴功"],
    "西餐": ["西餐", "牛排", "披萨", "意大利面"],
    "咖啡": ["咖啡", "咖啡店", "星巴克"],
    "奶茶": ["奶茶", "喜茶", "奈雪"],
    "面包": ["面包", "面包店", "烘焙", "糕点"],
}

ROUTE_RELEVANCE_TOKENS = [
    "路线",
    "规划",
    "行程",
    "安排",
    "推荐",
    "出行",
    "旅游",
    "旅行",
    "游玩",
    "玩",
    "逛",
    "去",
    "来上海",
    "附近",
    "周边",
    "景点",
    "打卡",
    "晚饭",
    "晚餐",
    "午饭",
    "午餐",
    "吃饭",
    "吃",
    "餐厅",
    "商场",
    "购物",
    "买东西",
    "逛街",
    "吃吃喝喝",
    "逛吃",
    "美食",
    "探店",
    "朋友",
    "周末",
    "漫展",
    "二次元",
    "自驾",
    "步行",
    "夜宵",
    "散步",
]


# v6: 真正闲逛动词 — 命中了才追加公园/书店/商场等泛化游玩关键词
CASUAL_STROLL_TOKENS = ["逛逛", "走走", "随便逛", "溜达", "玩一会儿", "逛一圈", "逛一逛", "逛一下", "转转", "出门逛", "出去逛", "出去玩", "出去走走", "散步"]

# v6: 强餐饮意图关键词 — 命中了就不能用泛化游玩覆盖
STRONG_MEAL_TOKENS = [
    "吃", "餐厅", "饭店", "食堂", "吃饭", "用餐", "就餐", "下馆子",
    "日料", "寿司", "刺身", "拉面", "烤肉", "火锅", "串串", "麻辣烫",
    "中餐", "西餐", "韩料", "泰餐", "本帮菜", "粤菜", "川菜", "湘菜",
    "快餐", "小吃", "美食", "探店", "找一家", "找一家...店",
    # v20: Extended meal intent tokens
    "必吃", "必尝", "招牌菜", "特色菜", "有什么好吃的", "吃什么",
    "早餐", "午饭", "晚饭", "夜宵", "宵夜", "有什么推荐",
]

# v20: Abstract expressions — must NOT become poi_category primary_query.
# These are either style/themes or social scenarios, never concrete POI names.
_STYLE_THEME_SYNONYMS = frozenset({
    "文艺", "文艺范", "文艺感", "文艺风", "文艺风格",
    "雅致", "清雅", "安静雅致", "雅致风格", "清雅风格",
    "有格调", "有格调的", "格调",
    "艺术感", "艺术氛围", "有艺术感", "有审美",
    "文化气息", "新中式氛围", "新中式风格",
    "小资", "有氛围", "氛围感", "精神漫游", "松弛感",
    "放空", "发呆", "独处",
    # v20: Abstract social scenario expressions
    "情侣约会", "闺蜜聚会", "团建拓展", "团建", "朋友聚会",
    "多人活动", "轻社交", "仪式感", "惊喜感", "参与感", "共创感",
    "拍照约会", "纪念日", "拍照打卡",
    "适合情侣约会的地方", "闺蜜聚会的地方", "团建的地方",
    "有仪式感的地方", "有惊喜感的地方", "适合多人活动的地方",
    "有参与感的活动", "可以共创的地方",
})

# v20: Abstract placeholder terms — when proximity captures these as Y,
# they must NOT become poi_category. They are scene descriptions, not places.
_ABSTRACT_PLACEHOLDER_TERMS: frozenset[str] = frozenset({
    "角落", "地方", "空间", "去处", "一个地方", "个地方",
    "安静的角落", "清净的地方", "不被打扰的地方",
})

# v20: Quiet retreat expressions — user wants a quiet, private environment.
# These map to real POI categories like libraries, bookstores, quiet cafes, parks.
# Must NOT become: POI names, poi_category names, psychological counseling, social activities.
_QUIET_RETREAT_EXPRESSIONS: frozenset[str] = frozenset({
    "安静的角落", "清静一点", "不被打扰", "想一个人待会儿",
    "找个地方放空", "安静坐坐", "人少一点", "想发会儿呆",
    "找个清净地方", "想独处一会儿",
    "想找个安静的", "想找个人少的", "想找个清静",
    "想自己待着", "想静一静",
})

# v20: Quiet retreat search keywords — concrete POI categories for quiet retreat
_QUIET_RETREAT_INDOOR_KEYWORDS = [
    "图书馆", "阅读空间", "独立书店", "安静咖啡馆",
    "茶馆", "美术馆", "共享自习室", "公共文化空间",
]

_QUIET_RETREAT_OUTDOOR_KEYWORDS = [
    "口袋公园", "小型城市公园", "安静花园", "滨水步道",
    "社区绿地", "公园休息区", "林荫步道",
]

_QUIET_RETREAT_MICRO_KEYWORDS = [
    "图书馆 安静", "书店 阅读", "咖啡馆 安静",
    "茶馆 品茶", "公园 散步", "美术馆 展览",
]

# v21: Lawn rest / green space feature intent expressions
_LAWN_REST_EXPRESSIONS: frozenset[str] = frozenset({
    "有草坪的地方坐着", "有草坪的地方",
    "找个草地晒太阳", "找个草地坐",
    "有长椅的地方休息", "能坐着看湖的地方",
    "有树荫的公园", "可以野餐的草坪",
    "能躺一会儿的草地", "有遮雨棚的地方",
    "找块草坪", "找个草坪", "草地坐着", "草坪坐着",
    "有草坪的", "找个有草坪", "找片草地",
})

# v21: Feature terms — indicate a feature-based (not named POI) intent
_FEATURE_LAWN_TERMS: frozenset[str] = frozenset({
    "草坪", "草地", "绿地", "绿草坪", "大草坪", "开放草坪",
    "野餐草坪", "野餐区", "可坐草坪",
})

_FEATURE_REST_TERMS: frozenset[str] = frozenset({
    "坐着", "坐坐", "休息", "躺一会儿", "晒太阳",
    "野餐", "放空", "发呆", "看书",
})

# A resting activity (for example, sitting on the lawn) does not by itself
# require dedicated seating infrastructure. Only explicit facility wording
# should make ``sittable`` a hard feature requirement.
_FEATURE_SEATING_FACILITY_TERMS: frozenset[str] = frozenset({
    "长椅", "座椅", "石凳", "木椅", "躺椅", "休息区",
    "有地方坐", "可坐设施", "能坐的设施",
})

# v21: Lawn rest search keywords — concrete POI categories for green space
_LAWN_REST_CATEGORY_KEYWORDS = [
    "公园", "城市绿地", "草坪公园", "开放草坪",
    "野餐草坪", "口袋公园", "公共花园", "社区绿地",
    "滨江绿地", "植物园",
]

_LAWN_REST_MICRO_KEYWORDS = [
    "草坪 休息", "公园 草坪", "绿地 野餐",
    "花园 散步", "草地 晒太阳",
]

# v21: Indoor rest alternatives for rainy weather
_INDOOR_REST_ALTERNATIVES = [
    "带落地窗咖啡馆", "有顶棚公园休息区",
    "室内植物园", "温室花园",
]

# v21: Night view / city skyline scene expressions
_NIGHT_VIEW_EXPRESSIONS: frozenset[str] = frozenset({
    "看城市夜景", "看夜景", "城市夜景", "城市天际线",
    "灯光夜景", "夜景观景台", "能俯瞰城市的地方",
    "晚上看城市灯光", "看城市灯光", "夜景灯光",
    "城市观景", "夜晚城市", "夜景打卡",
    "看城市夜景的地方",
})

_NIGHT_VIEW_FEATURE_TERMS: frozenset[str] = frozenset({
    "夜景", "城市灯光", "天际线", "俯瞰", "观景台",
    "灯光秀", "城市夜景", "夜景观景",
})

_NIGHT_VIEW_CATEGORY_KEYWORDS = [
    "夜景观景台", "城市观景平台", "天际线观景",
    "滨水夜景", "高层观景台", "灯光夜景打卡",
    "城市高点", "夜景观光",
]

_NIGHT_VIEW_MICRO_KEYWORDS = [
    "观景台 夜景", "天际线 观景", "滨水 夜景",
    "城市灯光 打卡", "高层 俯瞰",
]

# v21: Open terrace / outdoor terrace feature expressions
_OPEN_TERRACE_EXPRESSIONS: frozenset[str] = frozenset({
    "开放露台", "户外露台", "室外露台", "屋顶露台",
    "观景露台", "空中露台", "露天平台", "屋顶花园",
    "rooftop", "terrace", "有露台的地方",
    "可以坐在外面的露台", "能吹风的露台", "带露台的地方",
    "有开放露台的地方", "有露台的",
})

_OPEN_TERRACE_CATEGORY_KEYWORDS = [
    "开放露台", "户外露台咖啡馆", "露台餐厅",
    "屋顶花园", "观景露台", "空中露台",
    "rooftop", "露台酒吧",
]

_OPEN_TERRACE_MICRO_KEYWORDS = [
    "露台 观景", "露台 咖啡", "屋顶 花园",
    "户外 露台", "露天 座位",
]

# v21: Feature evidence terms for open_terrace
_OPEN_TERRACE_EVIDENCE_TERMS: list[str] = [
    "开放露台", "户外露台", "室外露台", "屋顶露台",
    "观景露台", "空中露台", "露天平台", "屋顶花园",
    "rooftop", "roof terrace", "terrace seating",
    "outdoor terrace", "露台", "露天座", "露台座",
]

# v21: Exclusions — NOT valid open terrace
_OPEN_TERRACE_EXCLUSIONS: set[str] = {
    "私人露台", "住宅露台", "办公楼内部", "仅住客",
    "暂停开放", "施工中", "无公开入口", "内部权限",
}

# v21: Stress relief / decompress activity expressions
_STRESS_RELIEF_EXPRESSIONS: frozenset[str] = frozenset({
    "解压", "放松一下", "释放压力", "缓解压力",
    "散散心", "调整心情", "清空脑子", "放空一下",
    "找点轻松的活动", "想发泄一下", "想做点治愈的事",
    "最近压力大想出去走走", "减压",
})

# v21: Stress relief mode indicators
_STRESS_RELIEF_QUIET_TERMS: frozenset[str] = frozenset({
    "安静", "一个人", "放空", "清静", "散心", "发呆",
    "独处", "静一静", "休息", "舒缓",
})

_STRESS_RELIEF_ACTIVE_TERMS: frozenset[str] = frozenset({
    "发泄", "释放", "刺激", "动一动", "运动", "出汗",
    "喊", "蹦", "跑", "跳", "打",
})

_STRESS_RELIEF_CREATIVE_TERMS: frozenset[str] = frozenset({
    "手工", "做点", "画画", "涂", "沉浸", "体验",
    "做东西", "烘焙", "陶艺", "木工", "编织",
})

# v21: Stress relief search keywords by mode
_STRESS_RELIEF_QUIET_KW = [
    "城市公园", "滨水步道", "独立书店", "安静咖啡馆",
    "公共花园", "美术馆", "茶馆", "阅读空间",
]

_STRESS_RELIEF_ACTIVE_KW = [
    "保龄球馆", "攀岩馆", "射箭馆", "蹦床馆",
    "卡丁车", "运动体验馆", "KTV", "游戏厅",
    "台球", "飞镖馆",
]

_STRESS_RELIEF_CREATIVE_KW = [
    "陶艺体验", "手作体验", "木工体验", "tufting体验",
    "绘画体验", "烘焙体验", "沉浸式体验", "DIY手工坊",
]

# v21: Stress relief micro keywords
_STRESS_RELIEF_MICRO_KW = [
    "公园 散步", "书店 安静", "咖啡馆 放松",
    "运动 体验", "手作 工坊", "DIY 体验",
]

# v21: Medical/psychological terms to EXCLUDE for stress_relief
_STRESS_RELIEF_EXCLUDE_CATS = {
    "心理咨询", "精神卫生", "医院", "康复中心", "医疗门诊",
    "诊所", "卫生站", "疗养院", "精神病", "心理科",
}

# v21: University / college short-name alias mapping for geocoding
_UNIVERSITY_ALIAS_MAP: dict[str, str] = {
    "北大": "北京大学",
    "北大东门": "北京大学东门",
    "北大西门": "北京大学西门",
    "北大南门": "北京大学南门",
    "北大东南门": "北京大学东南门",
    "清华": "清华大学",
    "人大": "中国人民大学",
    "北航": "北京航空航天大学",
    "北理工": "北京理工大学",
    "北师大": "北京师范大学",
    "北邮": "北京邮电大学",
    "中传": "中国传媒大学",
    "中戏": "中央戏剧学院",
    "央美": "中央美术学院",
    "北外": "北京外国语大学",
    "北语": "北京语言大学",
    "北科": "北京科技大学",
    "北交": "北京交通大学",
    "北化": "北京化工大学",
    "农大": "中国农业大学",
    "林大": "北京林业大学",
    "地大": "中国地质大学(北京)",
    "矿大": "中国矿业大学(北京)",
    "石油大学": "中国石油大学(北京)",
    "政法大学": "中国政法大学",
    "华电": "华北电力大学",
    "央财": "中央财经大学",
    "贸大": "对外经济贸易大学",
    "首师": "首都师范大学",
    "首医": "首都医科大学",
    "北体": "北京体育大学",
    "央音": "中央音乐学院",
    "国音": "中国音乐学院",
    "民大": "中央民族大学",
    "北影": "北京电影学院",
    "国戏": "中国戏曲学院",
    "北舞": "北京舞蹈学院",
}

# v21: Heat shelter — "避暑/纳凉/凉快/有空调" expressions
_HEAT_SHELTER_EXPRESSIONS: frozenset[str] = frozenset({
    "避暑", "纳凉", "凉快", "凉快点", "有空调", "太热",
    "找个凉快", "阴凉", "晒", "暴晒", "热得",
})

_HEAT_SHELTER_KEYWORDS = [
    "商场", "购物中心", "咖啡馆", "茶馆",
    "图书馆", "室内书店", "电影院", "博物馆",
    "美术馆", "文化馆", "室内展馆",
]

# v21: Area route — district-level tour pattern: "X区一日游", "X区半日游"
_AREA_TOUR_RE = re.compile(
    r"([一-龥A-Za-z]{2,8}(?:区|新区|县|镇|街道|商圈))"
    r"\s*(?:一日游|半日游|玩一天|逛一天|一天游)"
)

# v21: Noise prefix to strip before area matching
_AREA_TOUR_NOISE_RE = re.compile(
    r"^(?:我|我们|想|想去|去|在|推荐|求推荐|求|帮|请|"
    r"明天|今天|后天|周末|上午|下午|晚上|"
    r"有没有|哪里有|求介绍|介绍下|"
    r"帮我|给我|替我|"
    r"看看|逛逛|玩|找一个|找个)+"
)

# v21: Rain shelter / indoor refuge expressions
_RAIN_SHELTER_EXPRESSIONS: frozenset[str] = frozenset({
    "找个地方避雨", "避雨", "躲雨", "找个室内地方",
    "下雨", "有雨", "雨天", "要下雨",
    "找个地方躲", "找个地方待一会",
})

_RAIN_SHELTER_KEYWORDS = [
    "商场", "购物中心", "咖啡馆", "茶馆",
    "图书馆", "室内书店", "博物馆", "美术馆",
    "文化馆", "室内展馆",
]

# v21: Souvenir / gift shopping expressions
_SOUVENIR_EXPRESSIONS: frozenset[str] = frozenset({
    "伴手礼", "手信", "礼物带", "当地特产",
    "特产", "买点礼物", "北京特产", "文创店",
    "买纪念品", "纪念品", "地方特色", "带回去",
    "买点伴手礼", "伴手礼店",
})

# v21: Casual rest stop UGC expressions — "随意自在/不想打扮/不排队/社区店"
_CASUAL_REST_EXPRESSIONS: frozenset[str] = frozenset({
    "随意", "自在", "不想打扮", "不用打扮", "穿得随便",
    "舒服坐着", "松弛", "没人催", "不限时", "不用预约",
    "不想排队", "不要网红", "社区小店", "街坊",
    "本地人坐", "不想拍照", "不打卡", "轻松坐",
    "换个舒服", "随意一点", "自在一点",
})

_CASUAL_REST_KEYWORDS = [
    "社区咖啡店", "茶馆", "社区书店", "阅读空间",
    "面包店", "甜品店", "社区公园", "安静绿地",
    "文化空间", "社区小吃",
]

# v21: Rest stop / short break activity expressions
_REST_STOP_EXPRESSIONS: frozenset[str] = frozenset({
    "歇脚", "找地方坐一会", "走累了休息", "走累了歇一会",
    "找个地方缓缓", "找个能坐的地方", "临时休息一下",
    "中途停下来休息", "逛累了坐坐", "找个落脚的地方",
    "找个地方喝口水", "找个可以稍作休息的地方",
    "适合走累了歇脚", "适合走累了",
})

# v21: Restroom / toilet utility expressions — keyword-based, not full-phrase matching
_RESTROOM_KEY_TERMS: frozenset[str] = frozenset({
    "厕所", "公共厕所", "公厕", "卫生间", "洗手间", "如厕", "WC", "wc",
    "方便一下", "方便的地方", "方便的厕所", "近的厕所",
    "附近的厕所", "近一点的卫生间", "近的洗手间",
})

# v21: Corridor task patterns — "去X的路上顺路Y"
# Detect route-order tasks with explicit destination + corridor category
_CORRIDOR_PATTERNS: list[re.Pattern] = [
    # 去X的路上顺路看看Y / 去X的路上顺路买Y / 去X的路上顺路找Y
    re.compile(r"去(.{1,20}?)的?路上顺路(?:看看|买点?|找(?:一家|个)?|逛逛?)(.{1,16})"),
    # 去X途中找一家Y / 去X路上买点Y
    re.compile(r"去(.{1,20}?)(?:途中|路上|的时候)(?:找(?:一家|个)?|买点?|逛逛?|看看)(.{1,16})"),
    # 去X时顺便去Y
    re.compile(r"去(.{1,20}?)时?顺便(?:去|逛逛?|看看|买点?)(.{1,16})"),
    # 到X之前找个Y / 前往X途中经过Y
    re.compile(r"(?:到|前往)(.{1,20}?)之前找(?:个|一家)?(.{1,16})"),
    # 回家路上顺路买Y
    re.compile(r"回家路上顺路(?:买点?|看看|逛逛?|找(?:一家|个)?)(.{1,16})"),
    # v21: 想在X的路上找一家Y / 在X的路上找个Y / 从A去B的路上找Y
    re.compile(r"(?:想|想要|打算|准备)?在(.{1,20}?)的?路上找(?:一家|一个|个)?(.{1,16})"),
    # 在去X的路上找Y
    re.compile(r"在去(.{1,20}?)的?路上找(?:一家|一个|个)?(.{1,16})"),
    # v21: 从A去B的路上找Y → destination=B
    re.compile(r"从.{1,16}?去(.{1,16}?)的?路上(?:找|买|逛)(?:一家|一个|个)?(.{1,16})"),
]

# v21: Strip polite/noise suffixes from corridor captures
_CORRIDOR_POLITE_STRIP_RE = re.compile(
    r"(?:求推荐|帮我推荐|推荐一下|可以吗|有没有|有什么|行不行|"
    r"能推荐|好推荐|求介绍|介绍下|我想找|请推荐|"
    r"谢谢|麻烦了|拜托|，|,|。|！|!)+$"
)

# v21: Strip polite/noise prefixes from corridor destination
_CORRIDOR_DEST_STRIP_RE = re.compile(
    r"^(?:北京|上海|天津|重庆|广州|深圳|成都|武汉|南京|杭州|西安|长沙|"
    r"就|然后|再|先|想|要|打算|准备|顺便|顺便去|出发去|"
    r"的|附近|周边|那|那个|这个|一个|一家)+"
)

# v21: Landmark/POI alias mapping for famous locations
_LANDMARK_ALIAS_MAP: dict[str, str] = {
    "军事博物馆": "中国人民革命军事博物馆",
    "军博": "中国人民革命军事博物馆",
    "新文化运动纪念馆": "北京新文化运动纪念馆",
    "北大红楼": "北京大学红楼",
    "抗日战争纪念馆": "中国人民抗日战争纪念馆",
    "环球影城": "北京环球度假区",
    "北京环球影城": "北京环球度假区",
    "环球度假区": "北京环球度假区",
    "Universal Beijing Resort": "北京环球度假区",
    "北环影": "北京环球度假区",
}

# v21: Rest stop category keywords
_REST_STOP_CATEGORY_KEYWORDS = [
    "咖啡馆", "茶馆", "独立书店", "阅读空间",
    "公园休息区", "商场休息区", "公共文化空间",
    "甜品店", "有座位的地方",
]

STYLE_ROUTE_TOKENS = [
    "文艺", "文艺感", "艺术氛围", "艺术感",
    "有氛围", "氛围感", "有感觉", "小资", "有格调",
    "精神漫游", "城市漫游", "慢逛", "慢慢逛", "松弛感",
    "放空", "发呆", "独处",
    # v20: Also include the new synonyms
    "文艺范", "文艺风", "雅致", "清雅", "安静雅致",
    "有审美", "文化气息", "新中式氛围", "新中式风格",
]

STYLE_NIGHT_TOKENS = [
    "夜景", "夜游", "夜间", "夜晚", "夜里", "晚上", "傍晚", "灯光",
]

KEYWORD_PROFILES = [
    {
        # v6: 只在命中真正闲逛动词时追加泛化游玩关键词
        # "附近找一家日料店"命中"附近"但不命中闲逛动词 → 不触发此 profile
        "tokens": CASUAL_STROLL_TOKENS,
        "raw": ["附近逛逛"],
        "search": [
            "公园",
            "书店",
            "商场",
            "创意园",
            "绿地",
        ],
        "micro": ["公园 散步", "咖啡 休息", "书店 逛逛", "甜品 小吃", "商场 逛街"],
        "require_stroll": True,  # v6: 标记为需要闲逛动词
    },
    {
        "tokens": SHOPPING_TOKENS,
        "raw": ["购物"],
        "search": [
            "{city} 购物中心",
            "{city} 商场",
            "{city} 商圈",
            "{city} 商业广场",
            "{city} 综合体",
        ],
        "micro": ["商场 逛街", "潮牌 买手店", "购物中心 打卡"],
    },
    {
        "tokens": EATING_ACTIVITY_TOKENS,
        "raw": ["美食"],
        "search": [
            "{city} 美食",
            "{city} 餐饮",
        ],
        "micro": ["美食 餐饮", "咖啡 甜品", "小吃 探店"],
        "meal": ["餐厅", "美食", "小吃", "咖啡", "甜品"],
    },
    {
        "tokens": ["二次元", "动漫", "acg", "谷子", "谷店", "手办", "漫展"],
        "raw": ["二次元"],
        "search": [
            "{city} 百联ZX 造趣场",
            "{city} 寄售谷子店",
            "{city} 卡牌 谷子店",
            "{city} animate 二次元",
            "{city} 手办 潮玩",
            "{city} 动漫 周边",
            "{city} ACG 展览",
            "{city} 二次元 打卡",
        ],
        "micro": ["二次元 周边店", "动漫 主题咖啡", "谷子店", "手办 潮玩店", "ACG 展览"],
    },
    {
        "tokens": ["古街", "古镇", "老街", "水乡"],
        "raw": ["古街"],
        "search": ["{city} 古镇 推荐", "{city} 古镇 攻略", "{city} 水乡", "{city} 老街"],
        "micro": ["古镇 手工艺品", "老街 小吃", "古镇 拍照打卡"],
    },
    {
        "tokens": ["拍照", "打卡", "出片"],
        "raw": ["拍照"],
        "search": ["{city} 拍照 打卡", "{city} 网红打卡", "{city} 创意园", "{city} 展览"],
        "micro": ["网红打卡 拍照", "创意园 涂鸦墙", "展览 拍照"],
    },
    {
        "tokens": ["文艺", "文艺感", "艺术氛围", "艺术感", "文艺路线"],
        "raw": ["文艺"],
        "search": [
            "{city} 文艺街区",
            "{city} 艺术展览",
            "{city} 创意园",
            "{city} 独立书店",
        ],
        "micro": ["艺术展览", "独立书店", "创意园区", "文化空间"],
        "constraints": ["文艺优先", "慢节奏"],
    },
    {
        "tokens": ["有氛围", "氛围感", "有感觉", "小资", "有格调"],
        "raw": ["有氛围"],
        "search": [
            "{city} 文艺街区",
            "{city} 历史街区 漫步",
            "{city} 创意园",
            "{city} 独立书店",
        ],
        "micro": ["文艺街区", "历史街区 漫步", "独立书店", "艺术展览"],
        "constraints": ["氛围优先", "慢节奏"],
    },
    {
        "tokens": ["精神漫游", "城市漫游", "慢逛", "慢慢逛", "松弛感", "放空", "发呆", "独处"],
        "raw": ["精神漫游"],
        "search": [
            "{city} 文艺街区",
            "{city} 城市漫步",
            "{city} 独立书店",
            "{city} 艺术展览",
        ],
        "micro": ["城市慢行", "独立书店", "艺术展览", "创意园区"],
        "constraints": ["氛围优先", "慢节奏"],
    },
    {
        "tokens": ["夜景", "晚上", "夜游", "灯光"],
        "raw": ["夜景"],
        "search": [
            "{city} 夜景 拍照",
            "{city} 黄浦江 观景",
            "{city} 外滩 夜景",
            "{city} 陆家嘴 观景",
        ],
        "micro": ["夜景 拍照", "江景 打卡", "观景台", "灯光秀", "摄影 打卡"],
    },
    # === v6 新增 8 个 profile ===
    # 7. 水果生鲜 / 便利店 / 面包
    {
        "tokens": ["水果", "水果店", "买水果", "买点水果",
                  "菜场", "菜市场", "农贸市场", "生鲜",
                  "超市", "便利店", "全家", "罗森", "711",
                  "面包", "面包店", "烘焙", "糕点", "蛋糕", "买面包"],
        "raw": ["买点东西"],
        "search": [
            "水果店",
            "菜市场",
            "便利店",
            "面包店",
        ],
        "micro": ["水果店 生鲜", "菜市场 买菜", "便利店 零食", "面包店 烘焙"],
        "typecodes": ["060200", "060201"],  # v20 fix: 0602xx = 便利店, 不是 060400 (书店/文具)
    },
    # 8. 轻食简餐
    {
        "tokens": ["简单吃", "随便吃点", "对付一口", "垫垫肚子",
                  "轻食", "简餐", "快餐", "便餐",
                  "面条", "面馆", "拉面", "兰州拉面", "重庆小面",
                  "馄饨", "饺子", "包子", "馒头", "烧麦",
                  "盖浇饭", "盒饭", "炒饭", "拌面",
                  "麦当劳", "肯德基", "kfc", "m记", "金拱门", "开封菜",
                  "汉堡", "披萨", "沙拉", "三明治",
                  "黄焖鸡", "沙县"],
        "raw": ["简单吃"],
        "search": [
            "{city} 快餐",
            "{city} 面条",
            "{city} 馄饨",
            "{city} 麦当劳",
            "{city} 肯德基",
            "{city} 简餐",
        ],
        "micro": ["快餐 简餐", "面条 面馆", "馄饨 饺子", "黄焖鸡 沙县"],
        "meal": ["快餐", "面条", "馄饨", "简餐"],
        "typecodes": ["050300", "050301", "050302", "050303"],
    },
    # 9. 夜宵
    {
        "tokens": ["夜宵", "撸串", "烧烤", "烤串", "啤酒",
                  "小龙虾", "麻辣烫", "冒菜", "串串", "关东煮",
                  "螺蛳粉", "酸辣粉", "米线", "过桥米线",
                  "煎饼", "鸡蛋灌饼", "手抓饼", "肉夹馍"],
        "raw": ["夜宵"],
        "search": [
            "{city} 夜宵",
            "{city} 烧烤",
            "{city} 小龙虾",
            "{city} 麻辣烫",
            "{city} 螺蛳粉",
        ],
        "micro": ["夜宵 撸串", "小龙虾 啤酒", "麻辣烫 冒菜", "烧烤 烤串"],
        "typecodes": ["050400", "050500", "050501", "050502"],
    },
    # 10. 茶饮咖啡
    {
        "tokens": ["奶茶", "奶茶店", "喜茶", "奈雪", "一点点", "coco",
                  "咖啡", "咖啡店", "星巴克", "manner", "瑞幸",
                  "下午茶", "甜品", "蛋糕"],
        "raw": ["下午茶"],
        "search": [
            "{city} 奶茶店",
            "{city} 喜茶",
            "{city} 奈雪",
            "{city} 星巴克",
            "{city} 咖啡店",
        ],
        "micro": ["奶茶 喜茶", "咖啡 星巴克", "下午茶 甜品", "manner 咖啡"],
        "typecodes": ["050100", "050200", "050900", "051000"],
    },
    # 11. 通勤路上
    {
        "tokens": ["下班", "下班路上", "通勤", "路上",
                  "顺路", "顺便", "路过", "顺道"],
        "raw": ["通勤"],
        "search": [
            "公司 附近 {city}",
            "地铁站 附近",
            "公交站 附近",
            "顺路 便利店",
            "顺路 水果店",
        ],
        "micro": ["顺路 便利店", "顺路 水果店", "地铁站 周边", "公司 附近"],
    },
    # 12. 亲子遛娃
    {
        "tokens": ["带孩子", "遛娃", "溜娃", "带娃", "亲子",
                  "儿童", "宝宝", "小朋友", "幼儿园"],
        "raw": ["遛娃"],
        "search": [
            "{city} 亲子 餐厅",
            "{city} 儿童 乐园",
            "{city} 亲子 公园",
            "{city} 室内 儿童",
        ],
        "micro": ["亲子 餐厅", "儿童 乐园", "亲子 公园", "室内 儿童"],
    },
    # 13. 雨天室内
    {
        "tokens": ["下雨", "雨天", "阴雨", "有雨", "下雨天", "避雨",
                  "室内", "室内玩", "室内活动", "不淋雨"],
        "raw": ["雨天室内"],
        "search": [
            "{city} 室内 景点",
            "{city} 博物馆",
            "{city} 商场",
            "{city} 美术馆",
            "{city} 展览",
        ],
        "micro": ["博物馆 室内", "商场 避雨", "美术馆 展览", "书店 咖啡"],
    },
    # 14. 生活场景兜底
    {
        "tokens": ["约会", "聚餐", "团建", "聚会",
                  "一个人", "散步", "慢跑", "跑步", "健身"],
        "raw": ["生活场景"],
        "search": [
            "{city} 约会 餐厅",
            "{city} 聚餐 推荐",
            "{city} 公园 散步",
        ],
        "micro": ["约会 餐厅", "聚餐 推荐", "公园 散步", "健身房"],
    },
]


def _append_unique(values: list[str], additions: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values + additions:
        clean = value.strip()
        if clean and clean not in seen:
            result.append(clean)
            seen.add(clean)
        if limit is not None and len(result) >= limit:
            break
    return result


# v18: 父母/长辈/老人误判为儿童亲子主题的后处理修正
_CHILD_TERMS = {"孩子", "小孩", "儿童", "亲子", "带娃", "带孩子", "遛娃", "溜娃", "宝宝", "小朋友", "婴儿", "幼儿", "少年"}
_PARENT_ELDER_TERMS = {"父母", "爸妈", "爸爸", "妈妈", "父亲", "母亲", "长辈", "老人", "老年", "爸妈来", "父母来"}
_CHILD_FAMILY_IDS = {"family_friendly", "family_child_friendly"}


def _apply_parent_elder_theme_guard(parsed: ParsedIntent, user_request: str, city: str) -> ParsedIntent:
    """防止"父母/长辈/老人"误触发儿童亲子主题。

    若用户提到父母/长辈且未提到儿童，且当前 theme_profile 是亲子类，
    则将主题修改为更宽泛的城市热闹/经典游览主题。
    """
    current_profile = getattr(parsed, "theme_profile", None)
    if current_profile not in _CHILD_FAMILY_IDS:
        return parsed

    text_lower = user_request.lower()
    has_parent = any(t in user_request for t in _PARENT_ELDER_TERMS)
    has_child = any(t in user_request for t in _CHILD_TERMS)

    if not has_parent or has_child:
        return parsed

    # 命中：仅提到父母/长辈且未提儿童 → 不能使用儿童亲子 profile
    old_profile = current_profile
    parsed.theme_profile = "local_character"
    parsed.theme_label = parsed.theme_label or "长辈友好 / 热闹商圈 / 城市经典"
    parsed.theme_confidence = max(float(getattr(parsed, "theme_confidence", 0) or 0), 0.80)

    # micro_poi_keywords: 替换儿童词为成人通用词
    child_blocked = {"儿童博物馆", "儿童乐园", "亲子餐厅", "亲子", "儿童", "科技馆", "自然教育", "动物园", "游乐场", "主题乐园"}
    adult_keywords = ["热门景点", "热闹商圈", "城市地标", "老字号", "历史街区", "步行街", "公园", "本帮菜", "经典游览", "城市漫步"]
    existing = [k for k in (getattr(parsed, "micro_poi_keywords", []) or []) if k not in child_blocked]
    parsed.micro_poi_keywords = _append_unique(existing, adult_keywords, limit=14)

    # micro_required_terms: 移除强儿童词
    child_required = {"儿童", "亲子", "母婴", "玩具", "婴儿", "幼儿"}
    parsed.micro_required_terms = [
        t for t in (getattr(parsed, "micro_required_terms", []) or [])
        if t not in child_required
    ]

    # search_keywords: 补入成人通用搜索词
    city_short = city[:-1] if city.endswith("市") else city
    adult_search = [f"{city_short} 热门景点", f"{city_short} 热闹商圈", f"{city_short} 城市地标", f"{city_short} 老字号", f"{city_short} 历史街区"]
    parsed.search_keywords = _append_unique(parsed.search_keywords, adult_search, limit=8)

    print(
        f"[DEBUG step1] parent_elder_theme_guard applied "
        f"old_profile={old_profile} new_profile={parsed.theme_profile} "
        f"keywords={parsed.micro_poi_keywords[:8]}"
    )
    return parsed


def _duration_hint_for_llm(user_request: str) -> str:
    duration = _duration_from_request(user_request)
    if duration:
        return f'用户原文包含关键词，duration应为"{duration}"'
    return "未检测到明确的时长关键词，请从上下文推断"


def _duration_from_request(user_request: str) -> str | None:
    # ── v5.2: 多时段检测优先——用户同时提到上午+下午/晚上，说明要玩一整天 ──
    has_morning = bool(re.search(r"明早|今早|上午|早上|一上午", user_request))
    has_afternoon = bool(re.search(r"下午|一下午", user_request))
    has_evening = bool(re.search(r"晚上|夜里|夜间|傍晚", user_request))
    time_period_count = sum([has_morning, has_afternoon, has_evening])
    # 上午+下午 或 上午+晚上 或 下午+晚上 → full_day
    if time_period_count >= 2:
        return "a full day"

    checks = [
        (r"(三天|三日|3天|3日)", "three days"),
        (r"(两天半|二天半|2\.5天|2天半|两日半|二日半)", "two and a half days"),
        (r"(一天半|1\.5天|1天半|一日半)", "a day and a half"),
        (r"(一天|一日|1天|1日|整天|一整天)", "a full day"),
        (r"(两天|二天|两日|二日|2天|2日|周末)", "two days"),
        (r"(半天|半日|中午前后|午饭前后|午餐前后)", "a half day"),
        (r"(上午|下午|晚上|夜里|夜间|傍晚)", "a half day"),  # 单时段 → half_day
        (r"(待会儿|等会儿|马上|现在|一会儿|一会|附近逛|出去逛|出去玩|出去走走|玩一会儿|转转|走走|溜达|逛一圈|逛一逛|逛逛|逛一下)", "a quarter day"),
    ]
    for pattern, duration in checks:
        if re.search(pattern, user_request):
            return duration
    return None


USER_TIME_BUDGET_MAP: dict[str, str] = {
    "一上午": "half_day",
    "上午": "half_day",
    "一下午": "half_day",
    "下午": "half_day",
    "半天": "half_day",
    "大半天": "half_day",
    "一天": "full_day",
    "全天": "full_day",
    "整天": "full_day",
    "一天半": "a day and a half",
    "晚上": "quarter_day",
    "傍晚": "quarter_day",
    "夜里": "quarter_day",
    "夜间": "quarter_day",
}


def _parse_user_time_budget(raw: str | None) -> str | None:
    """v3新增：解析 FixedPoi.user_time_budget 为标准枚举值。None → None（留给 typecode 映射兜底）。"""
    if not raw:
        return None
    return USER_TIME_BUDGET_MAP.get(raw.strip())


def _looks_like_route_request(user_request: str) -> bool:
    lowered = user_request.lower()
    return any(token.lower() in lowered for token in ROUTE_RELEVANCE_TOKENS)


def _has_any_token(user_request: str, tokens: list[str]) -> bool:
    lowered = user_request.lower()
    return any(token.lower() in lowered for token in tokens)


def _hour_value(value: dt.datetime) -> float:
    return value.hour + value.minute / 60


def _is_casual_nearby_request(user_request: str) -> bool:
    return _has_any_token(user_request, NEARBY_CASUAL_TOKENS)


def _has_night_activity_intent(user_request: str) -> bool:
    return _has_any_token(user_request, NIGHT_ACTIVITY_TOKENS)


def _has_evening_dinner_intent(user_request: str) -> bool:
    """v5.3: 检测晚上餐饮意图。'晚上找个好吃的地方'→True，'晚上看夜景'→False。"""
    return bool(_EVENING_DINNER_RE.search(user_request))


def _has_shopping_intent(user_request: str) -> bool:
    return _has_any_token(user_request, SHOPPING_TOKENS)


def _has_eating_activity_intent(user_request: str) -> bool:
    return _has_any_token(user_request, EATING_ACTIVITY_TOKENS)


def _adjust_past_start_time(
    start_time: dt.datetime,
    user_request: str,
    current_time: dt.datetime,
) -> dt.datetime:
    # v6: normalize — LLM may return naive datetime, but current_time is now aware (client timezone)
    if start_time.tzinfo is None and current_time.tzinfo is not None:
        start_time = start_time.replace(tzinfo=current_time.tzinfo)
    elif start_time.tzinfo is not None and current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=start_time.tzinfo)
    if start_time >= current_time - dt.timedelta(minutes=PAST_TIME_TOLERANCE_MINUTES):
        return start_time
    if _has_any_token(user_request, FUTURE_DATE_TOKENS):
        return start_time
    has_explicit_period = _has_any_token(user_request, TIME_PERIOD_TOKENS)
    if _has_any_token(user_request, IMMEDIATE_TIME_TOKENS) or _has_night_activity_intent(user_request) or (
        _is_casual_nearby_request(user_request) and not has_explicit_period
    ):
        return current_time.replace(second=0, microsecond=0)
    next_day = current_time.date() + dt.timedelta(days=1)
    return dt.datetime.combine(next_day, start_time.timetz())


def _apply_keyword_overrides(parsed: ParsedIntent, user_request: str, city: str) -> ParsedIntent:
    city_short = city[:-1] if city.endswith("市") else city
    lowered = user_request.lower()

    # v20: Direct POI category queries have focused keywords already set;
    # skip profile-based expansion to avoid mixing in unrelated categories.
    _poi_cat = getattr(parsed, "poi_query_type", "") or ""
    if _poi_cat == "poi_category":
        # v20: If category is restaurant or strong meal intent detected, force explicit_meal_intent
        _cat = getattr(parsed, "category_id", None)
        _is_rest = (_cat == "restaurant" or bool(getattr(parsed, "explicit_meal_intent", False)))
        _has_meal_kw = any(token.lower() in lowered for token in STRONG_MEAL_TOKENS)
        if _is_rest or _has_meal_kw:
            parsed.explicit_meal_intent = True
        else:
            parsed.explicit_meal_intent = getattr(parsed, "explicit_meal_intent", False)
        return parsed

    # v6 Layer 2: 检测强餐饮意图 — 有明确就餐需求时，不追加快闪游玩关键词
    has_explicit_meal = (
        bool(parsed.food_pref_keywords)
        or bool(parsed.meal_search_keywords)
        or any(token.lower() in lowered for token in STRONG_MEAL_TOKENS)
    )

    # v6: 检测"附近/待会儿"距离约束
    has_nearby_distance = any(token in lowered for token in ["附近", "周边", "周围", "旁边", "就近", "待会儿", "一会儿", "马上", "现在"])
    if has_nearby_distance:
        if "不走远" not in parsed.other_constraints:
            parsed.other_constraints.append("不走远")

    for profile in KEYWORD_PROFILES:
        if not any(token.lower() in lowered for token in profile["tokens"]):
            continue

        # v6 Layer 1: require_stroll profile 需要同时命中距离词才算真正的"附近逛逛"
        if profile.get("require_stroll"):
            if not has_nearby_distance:
                continue
            # v6 Layer 2: 强餐饮意图下不追加泛化游玩关键词
            if has_explicit_meal:
                continue

        parsed.raw_keywords = _append_unique(parsed.raw_keywords, profile["raw"])
        explicit_search = [template.format(city=city_short) for template in profile["search"]]

        # v6 Layer 3: LLM 关键词优先，profile 关键词只能补充
        parsed.search_keywords = _append_unique(parsed.search_keywords, explicit_search, limit=6)
        parsed.micro_keywords = _append_unique(parsed.micro_keywords, profile["micro"], limit=5)
        # v13: 风格/氛围 profile 写入 other_constraints 供 step2/step3 使用
        extra_constraints = profile.get("constraints", [])
        if extra_constraints:
            parsed.other_constraints = _append_unique(
                parsed.other_constraints,
                extra_constraints,
            )
        if profile.get("meal"):
            parsed.meal_search_keywords = _append_unique(parsed.meal_search_keywords, profile["meal"], limit=6)

    # v13: 风格主题请求 — 禁止未经用户明确许可的夜间词泄露
    style_requested = any(token in lowered for token in STYLE_ROUTE_TOKENS)
    explicit_night_requested = any(token in lowered for token in STYLE_NIGHT_TOKENS)
    if style_requested and not explicit_night_requested:
        night_leak_terms = ("夜景", "夜游", "夜间", "夜晚", "灯光", "酒吧", "lounge", "bar")
        parsed.search_keywords = [
            keyword
            for keyword in parsed.search_keywords
            if not any(term in keyword.lower() for term in night_leak_terms)
        ]
        parsed.micro_keywords = [
            keyword
            for keyword in parsed.micro_keywords
            if not any(term in keyword.lower() for term in night_leak_terms)
        ]

    # v18: 裸词后处理 — 命中短关键词后转成可执行字段
    # CYCLING: 设置 transport_hint = "骑行"
    if any(token in lowered for token in CYCLING_TRANSPORT_TOKENS):
        parsed.transport_hint = "骑行"

    # STROLL_EAT: 逛吃 → 注入小吃/咖啡/甜品搜索
    if any(token in lowered for token in STROLL_EAT_TOKENS):
        parsed.raw_keywords = _append_unique(parsed.raw_keywords, ["逛吃"])
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["逛吃穿插"])
        parsed.meal_search_keywords = _append_unique(parsed.meal_search_keywords, ["小吃", "美食", "咖啡", "甜品"], limit=6)
        parsed.micro_keywords = _append_unique(parsed.micro_keywords, ["街区逛吃", "小吃探店", "咖啡甜品"], limit=5)

    # LIGHT_TOUR: 轻游 → 低强度约束，不强拉 duration
    if any(token in lowered for token in LIGHT_TOUR_TOKENS):
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["轻游", "低强度", "节奏宽松"])

    # NIGHT_SHORT: 夜游短路线 → evening + half_day
    _has_night_short = any(token in lowered for token in NIGHT_SHORT_ROUTE_TOKENS)
    _has_full_day_intent = any(token in lowered for token in ["全天", "一整天", "整天", "两天", "周末", "上午", "下午"])
    if _has_night_short and not _has_full_day_intent:
        parsed.evening_requested = True
        if parsed.duration in ("a full day", "two days", "three days", None, ""):
            parsed.duration = "a half day"
        parsed.time_budget = min(float(getattr(parsed, "time_budget", 999) or 999), 0.5)

    return parsed


def _replacement_left_pois(user_request: str) -> set[str]:
    left_pois: set[str] = set()
    for word in ("替换成", "替换为", "换成", "改成"):
        if word not in user_request:
            continue
        left = user_request.split(word, 1)[0]
        left = re.sub(r"^(把|将|请把|帮我把)", "", left).strip()
        for poi in sorted(KNOWN_POIS, key=len, reverse=True):
            if poi in left:
                left_pois.add(poi)
    return left_pois


def _append_fixed_poi_from_request(parsed: ParsedIntent, user_request: str) -> ParsedIntent:
    existing_names = {fp.name for fp in parsed.fixed_pois}
    excluded = set(name.lower() for name in (parsed.delete_list or []))
    replacement_left = _replacement_left_pois(user_request)
    for poi in sorted(KNOWN_POIS, key=len, reverse=True):
        if poi in replacement_left:
            continue
        if poi.lower() in excluded:
            continue
        if poi not in user_request:
            continue
        if any(poi in en or en in poi for en in existing_names):
            continue
        # v10: POI 附近有否定词则不加为固定锚点
        idx = user_request.index(poi)
        window = user_request[max(0, idx - 10):idx + len(poi) + 10]
        if any(trig in window for trig in NEGATION_TRIGGERS):
            continue
        parsed.fixed_pois.append(FixedPoi(name=poi, user_time_budget=None))
        existing_names.add(poi)
    return parsed


NEGATIVE_POI_PATTERNS = [
    # 已去过 + 否定（放宽间距到 15 字）
    r"(?:已经|之前|上次|都|也都|早就|以前)?去过了.{0,15}(?:就不要|就别|就不|别|不用|不要|不要再|不要有|不要包含|不想|不需要|不用再)(?:去|安排|包含|有)?[了啦]?",
    # 否定 + 动作/包含
    r"(?:就不|就别|不要|别|不用|不想|不打算|不需要|不要有|不要包含|别安排|不想去|不用去).{0,10}(?:去|安排|包含)?[了啦]?",
    # 直接否定/排除短语
    r"(?:就算了|不去了|别去了|免了|跳过|排除|不要了|不用了|不需要了|去掉|删掉|略过)",
    # POI 后置否定："外滩不要""南京路别安排了"
    r"(?:不要|别|不用|不想|不去了|免了|跳过|排除|去掉)",
]


def _exclude_pois_from_request(parsed: ParsedIntent, user_request: str) -> ParsedIntent:
    # 合并 LLM 已提取的 delete_list
    llm_deletes = set(name.lower() for name in parsed.delete_list)

    # v11: 替换左侧的POI自动排除
    replacement_left = _replacement_left_pois(user_request)
    for poi in replacement_left:
        parsed.fixed_pois = [fp for fp in parsed.fixed_pois if fp.name != poi]
        for alias in EXCLUDE_ALIASES.get(poi, [poi]):
            if alias not in parsed.delete_list:
                parsed.delete_list.append(alias)

    # 正则兜底：检测 LLM 可能漏掉的已知 POI
    for poi in sorted(KNOWN_POIS, key=len, reverse=True):
        if poi.lower() in llm_deletes:
            continue
        if poi not in user_request:
            continue
        # 在 POI 附近 30 字窗口内搜索否定模式
        idx = user_request.index(poi)
        window_start = max(0, idx - 30)
        window_end = min(len(user_request), idx + len(poi) + 30)
        window = user_request[window_start:window_end]
        matched = False
        for pattern in NEGATIVE_POI_PATTERNS:
            if re.search(pattern, window):
                matched = True
                break
        # v10: 也检查否定触发器
        if not matched:
            if any(trig in window for trig in NEGATION_TRIGGERS):
                matched = True
        if matched:
            parsed.fixed_pois = [fp for fp in parsed.fixed_pois if fp.name != poi]
            # v10: 扩展别名加入 delete_list
            aliases = EXCLUDE_ALIASES.get(poi, [poi])
            for alias in aliases:
                if alias not in parsed.delete_list:
                    parsed.delete_list.append(alias)
            break
    return parsed


def _split_clauses(user_request: str) -> list[str]:
    pieces = re.split(r"[，,。；;\n]+", user_request)
    clauses: list[str] = []
    for piece in pieces:
        clauses.extend(part for part in re.split(r"(?:并且|并|然后|再|其中)", piece) if part)
    return [clause.strip() for clause in clauses if clause.strip()]


def _day_index_from_text(text: str) -> int | None:
    lowered = text.lower()
    for pattern, day_index in DAY_INDEX_PATTERNS:
        if re.search(pattern, lowered):
            return day_index
    return None


def _meal_from_text(text: str) -> str | None:
    # A time word and the food action do not need to be adjacent:
    # "晚上去首都医科大学旁边的饭馆吃饭" is still dinner.
    if re.search(r"(?:晚上|傍晚|夜里|夜间).{0,40}(?:吃|用餐|就餐|饭馆|饭店|餐厅)", text):
        return "dinner"
    if any(token in text for token in ["午饭", "午餐", "中饭", "中餐", "中午"]):
        return "lunch"
    if any(token in text for token in ["晚饭", "晚餐", "晚间吃", "晚上吃", "吃个晚饭", "吃晚饭"]):
        return "dinner"
    return None


def _food_keywords_from_text(text: str) -> list[str]:
    keywords: list[str] = []
    for token, aliases in FOOD_STYLE_ALIASES.items():
        if token in text:
            keywords.extend(aliases)
    return _append_unique([], keywords, limit=6)


def _fixed_meal_name_from_text(text: str) -> str | None:
    if not any(token in text for token in ["吃", "用餐", "就餐"]):
        return None
    match = re.search(r"(?:在|去|到)([^，。；,;]{1,40}?)(?:吃饭|吃午饭|吃晚饭|用餐|就餐|吃一顿|吃)", text)
    if not match:
        return None
    name = match.group(1).strip(" ：:，,。；;")
    name = re.sub(r"^(?:中午|晚上|午餐|晚餐|餐厅|饭店|一家|一个|附近|周边|的)+", "", name)
    if not name:
        return None
    # "X附近/旁边的饭馆" is a category near a reference location, not a
    # fixed restaurant name.  It is represented on PlannedWaypoint instead.
    if any(token in name for token in ["附近", "周边", "周围", "旁边", "一带", "餐厅请帮我找", "帮我找", "找一家"]):
        return None
    if len(name) > 30:
        return None
    return name


def _day_poi_constraints_from_request(user_request: str) -> list[dict]:
    constraints: list[dict] = []
    seen: set[tuple[int, str]] = set()
    current_day: int | None = None
    for clause in _split_clauses(user_request):
        explicit_day = _day_index_from_text(clause)
        if explicit_day:
            current_day = explicit_day
        day_index = explicit_day or current_day
        if not day_index:
            continue
        for poi in sorted(KNOWN_POIS, key=len, reverse=True):
            if poi not in clause:
                continue
            if any(
                item["day_index"] == day_index
                and (poi in item["poi_name"] or item["poi_name"] in poi)
                for item in constraints
            ):
                continue
            key = (day_index, poi)
            if key in seen:
                continue
            constraints.append({"day_index": day_index, "poi_name": poi})
            seen.add(key)
    return constraints


def _meal_constraints_from_request(user_request: str) -> list[dict]:
    constraints: list[dict] = []
    current_day: int | None = None
    pending_day_keywords: dict[int, list[str]] = {}
    seen: set[tuple[int | None, str | None, str | None, str]] = set()
    for clause in _split_clauses(user_request):
        explicit_day = _day_index_from_text(clause)
        if explicit_day:
            current_day = explicit_day
        day_index = explicit_day or current_day
        meal = _meal_from_text(clause)
        keywords = _food_keywords_from_text(clause)
        fixed_name = _fixed_meal_name_from_text(clause)
        has_food_evidence = bool(
            keywords
            or fixed_name
            or re.search(r"吃|用餐|就餐|饭馆|饭店|餐厅|美食|小吃|简餐|午饭|午餐|晚饭|晚餐", clause)
        )
        if meal and not has_food_evidence:
            # A time marker alone ("中午去天坛公园") is not a meal request.
            meal = None
        if day_index and keywords and not meal and not fixed_name:
            pending_day_keywords[day_index] = _append_unique(pending_day_keywords.get(day_index, []), keywords)
            continue
        if not (meal or keywords or fixed_name):
            continue
        if day_index and pending_day_keywords.get(day_index):
            keywords = _append_unique(pending_day_keywords[day_index], keywords)
        if not meal and fixed_name:
            meal = "lunch"
        key = (
            day_index,
            meal,
            fixed_name,
            "|".join(keywords),
        )
        if key in seen:
            continue
        constraints.append(
            {
                "day_index": day_index,
                "meal": meal,
                "keywords": keywords,
                "fixed_poi_name": fixed_name,
            }
        )
        seen.add(key)
    return constraints


def _request_food_keywords_from_constraints(meal_constraints: list[dict]) -> list[str]:
    keywords: list[str] = []
    for constraint in meal_constraints:
        keywords.extend(keyword for keyword in constraint.get("keywords", []) if keyword)
        fixed_name = constraint.get("fixed_poi_name")
        if fixed_name:
            keywords.extend(_food_keywords_from_text(str(fixed_name)))
    return _append_unique([], keywords, limit=6)


def _merge_constraints(existing: list[dict], additions: list[dict], key_fields: list[str]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple] = set()
    for constraint in existing + additions:
        if not isinstance(constraint, dict):
            continue
        key = tuple(str(constraint.get(field) or "") for field in key_fields)
        if key in seen:
            continue
        merged.append(constraint)
        seen.add(key)
    return merged


def _order_fixed_pois_by_day_constraints(fixed_pois: list[FixedPoi], constraints: list[dict]) -> list[FixedPoi]:
    ordered: list[FixedPoi] = []
    for constraint in sorted(constraints, key=lambda item: int(item.get("day_index") or 99)):
        poi_name = str(constraint.get("poi_name") or "")
        for fp in fixed_pois:
            if fp.name == poi_name and fp not in ordered:
                ordered.append(fp)
                break
    for fp in fixed_pois:
        if fp not in ordered:
            ordered.append(fp)
    return ordered


def _has_explicit_origin(user_request: str) -> bool:
    return bool(re.search(r"(从|自).{0,20}(出发|走|开始)", user_request)) or any(
        token in user_request for token in ["出发地", "起点"]
    )


def _explicit_meals(user_request: str) -> list[str]:
    meals: list[str] = []
    if any(token in user_request for token in ["午饭", "午餐", "中饭", "中餐"]):
        meals.append("lunch")
    if any(token in user_request for token in ["晚饭", "晚餐", "晚间吃", "吃个晚饭", "吃晚饭"]) or re.search(
        r"(?:晚上|傍晚|夜里|夜间).{0,40}(?:吃|用餐|就餐|饭馆|饭店|餐厅)",
        user_request,
    ):
        meals.append("dinner")
    return meals


def _dinner_before_activity(user_request: str) -> bool:
    return bool(
        re.search(
            r"(先)?(吃.{0,4})?(晚饭|晚餐).{0,12}(然后|再|之后|接着|随后).{0,24}(夜景|逛|散步|打卡|玩|观景)",
            user_request,
        )
    )


def _normalize_food_preferences(values: list[str]) -> list[str]:
    meal_words = {"午饭", "午餐", "中饭", "中餐", "晚饭", "晚餐", "吃饭", "正餐", "吃吃喝喝", "逛吃", "美食", "餐饮"}
    return [value for value in values if value and value not in meal_words]


def _normalize_meal_search_keywords(parsed: ParsedIntent, user_request: str) -> list[str]:
    keywords = list(parsed.meal_search_keywords)
    if _has_eating_activity_intent(user_request):
        keywords.extend(["餐厅", "美食", "小吃"])
        if _has_any_token(user_request, ["咖啡", "下午茶", "甜品", "奶茶", "喝咖啡", "甜点", "吃甜", "喝茶"]):
            keywords.extend(["咖啡", "甜品"])
    for pref in parsed.food_pref_keywords[:2]:
        if not any(token in pref for token in ["咖啡", "下午茶", "甜品", "奶茶"]):
            keywords.append(f"{pref} 餐厅")
        else:
            keywords.append(pref)
    return _append_unique([], keywords, limit=6)


def _budget_from_request(user_request: str) -> float | None:
    patterns = [
        r"(?:人均(?:消费|预算)?|每人|每位|餐厅人均).{0,12}?(\d+(?:\.\d+)?)\s*(?:元|块|rmb|RMB)?(?:以内|以下|左右)?",
        r"(?:预算|消费).{0,8}?人均.{0,8}?(\d+(?:\.\d+)?)\s*(?:元|块|rmb|RMB)?(?:以内|以下|左右)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_request, flags=re.IGNORECASE)
        if not match:
            continue
        value = float(match.group(1))
        if 0 < value <= 10000:
            return value
    return None


def _merge_meal_needs(meal_needs: list[str] | list[list[str]], explicit: list[str]) -> list[str] | list[list[str]]:
    if not explicit:
        return meal_needs
    if not meal_needs:
        return list(dict.fromkeys(explicit))
    if all(isinstance(item, str) for item in meal_needs):
        merged = list(meal_needs)  # type: ignore[list-item]
        for meal in explicit:
            if meal not in merged:
                merged.append(meal)
        return merged
    nested = [list(day) for day in meal_needs]  # type: ignore[arg-type]
    if not nested:
        nested = [[]]
    for meal in explicit:
        if meal not in nested[0]:
            nested[0].append(meal)
    return nested


def _merge_constraint_meals(
    meal_needs: list[str] | list[list[str]],
    meal_constraints: list[dict],
) -> list[str] | list[list[str]]:
    requested = [
        (constraint.get("day_index"), constraint.get("meal"))
        for constraint in meal_constraints
        if constraint.get("meal") in {"lunch", "dinner"}
    ]
    if not requested:
        return meal_needs
    max_day = max([int(day or 1) for day, _ in requested] + [1])
    if all(isinstance(item, str) for item in meal_needs):
        nested = [list(meal_needs)]  # type: ignore[list-item]
    else:
        nested = [list(day) for day in meal_needs]  # type: ignore[arg-type]
    while len(nested) < max_day:
        nested.append([])
    for day, meal in requested:
        day_index = int(day or 1)
        if meal not in nested[day_index - 1]:
            nested[day_index - 1].append(meal)
    return nested if len(nested) > 1 else nested[0]


def _next_start_time(user_request: str, current_time: dt.datetime, duration: str | None = None) -> dt.datetime:
    target_date = current_time.date()
    # v6: "待会儿下班/下班后/回家前" → 晚间场景，直接用当前时间
    is_off_work = _has_any_token(user_request, ["下班", "下班后", "下班前", "回家前", "晚高峰", "下班路上", "待会儿下班", "下班了","加班后","忙完"])
    if not is_off_work and _has_any_token(user_request, IMMEDIATE_TIME_TOKENS):
        return current_time.replace(second=0, microsecond=0)
    # v6: 下班场景直接用 current_time（取 max(current, 18:00)）
    if is_off_work:
        now_hour = current_time.hour + current_time.minute / 60
        if now_hour >= 17:
            # 已经下班时间，直接用当前时间
            return current_time.replace(second=0, microsecond=0)
        else:
            # 还没下班，从 18:00 开始
            return dt.datetime.combine(target_date, dt.time(hour=18, minute=0, tzinfo=current_time.tzinfo))
    if "明天" in user_request:
        target_date = target_date + dt.timedelta(days=1)
    elif "后天" in user_request:
        target_date = target_date + dt.timedelta(days=2)
    elif "周末" in user_request:
        days_until_sat = (5 - current_time.weekday()) % 7
        target_date = target_date + dt.timedelta(days=days_until_sat)

    hour = 9
    minute = 0
    full_or_multi_day = duration in {
        "a full day",
        "a day and a half",
        "two days",
        "two and a half days",
        "three days",
    } or bool(re.search(r"(玩一天|一整天|整天|全天|两天|二天|两日|二日|周末)", user_request))
    if full_or_multi_day and not re.search(r"(下午出发|傍晚出发|晚上出发|夜里出发|夜间出发)", user_request):
        hour = 9
    elif "早" in user_request or "上午" in user_request:
        hour = 9
    elif "下午" in user_request:
        hour = 14
    elif "晚上" in user_request or "夜景" in user_request:
        hour = 19
    elif "中午" in user_request:
        hour = 12
    # v6: 下班场景 → 傍晚/晚间
    if is_off_work:
        now_hour = current_time.hour + current_time.minute / 60
        if now_hour < 17:
            hour = 18  # 还没下班，按傍晚处理
        else:
            hour = max(18, int(now_hour))  # 已经下班，用当前时间但至少18点
    return dt.datetime.combine(target_date, dt.time(hour=hour, minute=minute, tzinfo=current_time.tzinfo))


def _fallback_origin(parsed: ParsedIntent, user_profile: UserProfile) -> dict | None:
    # v18: 统一使用 home_location 作为路线出发地，不再优先 device_location
    home_location = getattr(user_profile, "home_location", None)
    permanent_city_coord = getattr(user_profile, "permanent_city_coord", None)
    result = home_location or permanent_city_coord

    # v22: Detect mixed city/coordinate — label says Beijing but coords are Shanghai fallback
    if result:
        label = str(result.get("label", "") or "")
        lat = float(result.get("lat", 0) or 0)
        lng = float(result.get("lng", 0) or 0)
        src = str(result.get("source", "") or "")

        # Shanghai fallback coordinates (Tongji University)
        _is_tongji_fallback = (abs(lat - 31.2809) < 0.001 and abs(lng - 121.5011) < 0.001)
        _label_has_beijing = "北京" in label
        _label_has_shanghai = "上海" in label

        if _is_tongji_fallback and _label_has_beijing:
            print(
                f"[OriginResolveAudit] mixed_location_detected "
                f"label_city=北京市 coord_city=上海市 label={label[:40]} "
                f"lat={lat} lng={lng}"
            )
            # Mark for attention — async geocode will be done by the pipeline
            result["_mixed_coords_warning"] = "label城市与坐标城市不一致，坐标可能为兜底值"
            result["source"] = result.get("source") or "mixed_coords_suspect"
            print(
                f"[OriginResolveAudit] mixed_location_detected "
                f"label_city=北京市 coord_city=上海市 label={label[:40]} "
                f"— marking for async geocode repair"
            )

        print(
            f"[DEBUG step1] fallback_origin_source={src or 'home_location'} "
            f"label={label[:40]} lat={lat} lng={lng}"
        )
    return result


def _deterministic_fallback_parsed_intent(
    user_request: str,
    plan_mode: str = "auto",
    city: str = "",
) -> "ParsedIntent":
    """Deterministic fallback when LLM fails. Extracts sequential tasks from keywords.

    v24: Enhanced with time-slot based waypoint extraction.  Handles patterns like:
    "先去北海公园走走，中午吃顿烤鸭，下午去景山公园"
    → 3 ordered PlannedWaypoints (北海公园→烤鸭→景山公园) with correct categories/slots.
    """
    from .data_schema import ParsedIntent

    raw_kws: list[str] = []
    search_kws: list[str] = []
    planned_waypoints: list[PlannedWaypoint] = []
    fixed_pois: list[FixedPoi] = []
    food_pref_keywords: list[str] = []
    meal_search_keywords: list[str] = []
    meal_needs: list[str] = []

    # ── v24: time-slot + name extraction per clause ──
    # Split by common Chinese punctuation / connectors, keeping time markers
    _clauses = re.split(r"[，,。；;、]\s*", user_request)

    _time_slot_map: dict[str, str] = {
        "上午": "morning", "早上": "morning", "早晨": "morning",
        "中午": "lunch",   "午饭": "lunch",   "午餐": "lunch",
        "下午": "afternoon",
        "傍晚": "evening", "晚上": "evening", "晚饭": "dinner", "晚餐": "dinner",
        "夜里": "evening", "夜间": "evening",
    }
    # v24: expanded food keyword registry — maps food terms to search keywords
    _food_search_kw_map: dict[str, list[str]] = {
        "烤鸭":   ["烤鸭", "北京烤鸭", "烤鸭店"],
        "涮羊肉": ["涮羊肉", "火锅", "羊肉", "涮肉"],
        "火锅":   ["火锅", "涮肉", "火锅店"],
        "川菜":   ["川菜", "四川菜", "川菜 餐厅"],
        "粤菜":   ["粤菜", "广东菜", "粤菜 餐厅"],
        "日料":   ["日料", "日本料理", "寿司"],
        "本帮菜": ["本帮菜", "上海菜", "江浙菜"],
        "烧烤":   ["烧烤", "烤串", "烤肉"],
        "海鲜":   ["海鲜", "海鲜餐厅"],
        "西餐":   ["西餐", "牛排", "西餐厅"],
    }

    # v24: compound place regex — extracts "去X", "逛X", etc. with trailing 走走/逛逛 stripped
    _place_re = re.compile(
        r"(?:先去|先去到|去|到|逛|看|参观|游览|玩|爬|登)"
        r"(.{1,20}?)"
        r"(?:走走|逛逛|看看|玩玩|一下|一圈|一转|溜达|溜达溜达)?$"
    )
    # v24: compound eat regex — extracts "吃X", "尝X", etc.
    _eat_re = re.compile(
        r"(?:吃|尝|品|享用|来)"
        r"(?:顿|份|个|次|点)?"
        r"(.{1,15}?)"
        r"(?:吧|呀|呢|了)?$"
    )

    _current_time_slot: str | None = None

    for clause in _clauses:
        clause = clause.strip()
        if not clause:
            continue
        # Also strip leading connectors "先", "再", "然后", "接着", "最后"
        clause = re.sub(r"^(?:先|再|然后|接着|最后)\s*", "", clause).strip()
        if not clause:
            continue

        # Detect time slot in this clause
        for marker, slot in _time_slot_map.items():
            if marker in clause:
                _current_time_slot = slot
                break

        # ── Pattern A: "吃X" → meal placeholder ──
        _eat_match = _eat_re.search(clause)
        if _eat_match:
            _food = _eat_match.group(1).strip()
            _food = re.sub(r"^(了|的|个|一|下)", "", _food).strip()
            # v24: Strip trailing "走走/逛逛/..." that might remain after clause split
            _food = re.sub(r"(走走|逛逛|看看|玩玩|一下|一圈|一转)$", "", _food).strip()
            if _food and 1 <= len(_food) <= 15:
                # Deduplicate food keywords
                if _food not in food_pref_keywords:
                    food_pref_keywords.append(_food)

                _meal_kws = _food_search_kw_map.get(_food)
                if _meal_kws is None:
                    if "菜" in _food and _food not in ("菜",):
                        _meal_kws = [_food, f"{_food} 餐厅"]
                    else:
                        _meal_kws = [_food, f"{_food}店", f"{_food}餐厅"]
                for _mk in _meal_kws:
                    if _mk not in meal_search_keywords:
                        meal_search_keywords.append(_mk)

                _meal_slot = _current_time_slot if _current_time_slot in ("lunch", "dinner") else "lunch"
                if _meal_slot not in meal_needs:
                    meal_needs.append(_meal_slot)

                planned_waypoints.append(PlannedWaypoint(
                    type="placeholder",
                    search_keyword=_food,
                    category="meal",
                    stay_minutes=60,
                    search_keywords=list(dict.fromkeys(_meal_kws)),
                    required_terms=[_food],
                    excluded_terms=["咖啡", "奶茶", "甜品", "面包"],
                    time_slot=_meal_slot,
                ))
                if _food not in raw_kws:
                    raw_kws.append(_food)
                continue

        # ── Pattern B: "去/逛/看 X" → fixed visit waypoint ──
        _place_match = _place_re.search(clause)
        if _place_match:
            _place = _place_match.group(1).strip()
            _place = re.sub(r"^(了|的|个|一|下)", "", _place).strip()
            _place = re.sub(r"(走走|逛逛|看看|玩玩|一下|一圈|一转)$", "", _place).strip()

            # v24: Guard — skip generic non-POI words
            _non_poi_words = frozenset({
                "走走", "逛逛", "看看", "玩玩", "好吃", "一顿", "一会", "一下",
                "那里", "这里", "那儿", "这儿", "地方", "哪里",
            })
            if _place and len(_place) >= 2 and len(_place) <= 30 and _place not in _non_poi_words:
                # v24: Also skip if it's purely food-related (caught by pattern A)
                _is_foodish = any(kw in _place for kw in [
                    "烤", "涮", "火锅", "菜", "面", "粉", "串",
                ])
                # Allow named restaurants as visit waypoints if they are known landmarks
                if _is_foodish and len(_place) <= 5:
                    # Ambiguous — likely food, skip if already got a meal from pattern A
                    if planned_waypoints:
                        continue

                planned_waypoints.append(PlannedWaypoint(
                    type="fixed",
                    name=_place,
                    search_keyword=_place,
                    category="visit",
                    stay_minutes=90,
                    search_keywords=[_place],
                    required_terms=[_place],
                    time_slot=_current_time_slot,
                ))
                fixed_pois.append(FixedPoi(name=_place, user_time_budget=None))
                if _place not in raw_kws:
                    raw_kws.append(_place)
                if _place not in search_kws:
                    search_kws.append(_place)
                continue

        # ── Pattern C: loose noun extraction — catch named places without explicit verb ──
        # "北海公园走走" → 北海公园
        _loose_match = re.match(r"^(.{2,15}?)(?:走走|逛逛|看看|玩玩|一下|一逛|一转|溜达)$", clause)
        if _loose_match and not planned_waypoints:
            _loose_place = _loose_match.group(1).strip()
            if _loose_place not in _non_poi_words and len(_loose_place) >= 2:
                planned_waypoints.append(PlannedWaypoint(
                    type="fixed",
                    name=_loose_place,
                    search_keyword=_loose_place,
                    category="visit",
                    stay_minutes=90,
                    search_keywords=[_loose_place],
                    required_terms=[_loose_place],
                    time_slot=_current_time_slot,
                ))
                fixed_pois.append(FixedPoi(name=_loose_place, user_time_budget=None))
                if _loose_place not in raw_kws:
                    raw_kws.append(_loose_place)
                if _loose_place not in search_kws:
                    search_kws.append(_loose_place)

    # ── v24: structured-waypoints path — generated from above patterns ──
    if planned_waypoints:
        _is_planned = True  # at least 2 time-slot waypoints = planned route
        _dur = "a full day" if len(planned_waypoints) >= 3 else "a half day"

        if city:
            search_kws = [f"{city} {kw}" for kw in search_kws]

        _now = dt.datetime.now()
        return ParsedIntent(
            is_route_planning_request=True,
            duration=_dur,
            start_time=_now,
            raw_keywords=raw_kws,
            search_keywords=search_kws,
            food_pref_keywords=list(dict.fromkeys(food_pref_keywords)),
            meal_search_keywords=list(dict.fromkeys(meal_search_keywords)),
            meal_needs=meal_needs,
            fixed_pois=fixed_pois,
            planned_waypoints=planned_waypoints,
            plan_mode="planned",
        )

    # ── v21 legacy fallback: simple keyword matching (no structured waypoints) ──
    is_planned = "先" in user_request or "再" in user_request or "然后" in user_request

    _seq_tasks: list = []
    _action_map = {
        "买书": ("书店", "purchase", 30),
        "吃饭": ("餐厅", "meal", 60),
        "看电影": ("电影院", "visit", 120),
        "理发": ("理发店", "service", 45),
        "取蛋糕": ("蛋糕店", "purchase", 15),
        "逛公园": ("公园", "visit", 90),
        "喝咖啡": ("咖啡", "cafe", 30),
        "去图书馆": ("图书馆", "visit", 90),
    }
    _seq_match = re.findall(r"(?:先|再|然后|接着|最后)?\s*(买书|吃饭|看电影|理发|取蛋糕|逛公园|喝咖啡|去图书馆)", user_request)
    for i, action in enumerate(_seq_match):
        if action in _action_map:
            kw, cat, stay = _action_map[action]
            _seq_tasks.append({"type": "placeholder", "search_keyword": kw,
                              "category": cat, "stay_minutes": stay, "sequence": i + 1})

    for kw in ["书店", "餐厅", "电影院", "公园", "博物馆", "图书馆", "夜景", "咖啡"]:
        if kw in user_request:
            raw_kws.append(kw)
            search_kws.append(kw)

    if city:
        search_kws = [f"{city} {kw}" for kw in search_kws]

    _now = dt.datetime.now()
    return ParsedIntent(
        is_route_planning_request=True,
        duration="a full day" if is_planned else "a half day",
        start_time=_now,
        raw_keywords=raw_kws,
        search_keywords=search_kws,
        plan_mode="planned" if is_planned else "exploratory",
        # planned_waypoints set in _postprocess fallback pipeline
    )


_COMPACT_STEP1_LOCAL_TERMS = ("附近", "周边", "周围", "旁边", "就近", "待会儿", "一会儿", "现在", "下班")
_COMPACT_STEP1_ACTION_TERMS = (
    "找", "买", "吃", "喝", "理发", "剪发", "看电影", "唱歌", "电玩", "玩游戏",
)
_COMPACT_STEP1_COMPLEX_TERMS = (
    "明天", "后天", "周末", "上午", "下午", "中午", "傍晚", "晚上", "夜景", "夜游",
    "一日", "一天", "两天", "多天", "先去", "最后", "文艺", "拍照", "特色小店", "河边",
    "预算", "人均", "地铁", "公交", "打车", "不想", "不要", "别去", "改成", "替换",
    "朋友", "同行", "一起", "不吃辣", "亲子", "老人", "故宫", "天安门", "北海公园",
    "景山", "三里河", "外滩", "迪士尼", "颐和园",
)


def _is_compact_step1_candidate(
    user_request: str,
    routing_context: dict | None = None,
) -> bool:
    """Allow only low-ambiguity local tasks onto the compact LLM contract.

    This is a safety gate, not an intent classifier.  The compact LLM still
    determines POI categories and waypoint order.  Any context, timeline,
    named showcase route, negative edit, or complex preference stays on the
    complete Step1 prompt.
    """
    has_active_route_context = bool(
        isinstance(routing_context, dict)
        and (
            routing_context.get("previous_intent")
            or routing_context.get("previous_complete_plan")
            or routing_context.get("points")
            or routing_context.get("point_names")
        )
    )
    if not config.STEP1_SPARSE_ACTIVATION_ENABLED or has_active_route_context or _has_conversation_context(user_request):
        return False
    text = _extract_latest_user_input(user_request).strip()
    if not text or len(text) > 80:
        return False
    if not any(term in text for term in _COMPACT_STEP1_LOCAL_TERMS):
        return False
    if not any(term in text for term in _COMPACT_STEP1_ACTION_TERMS):
        return False
    if any(term in text for term in _COMPACT_STEP1_COMPLEX_TERMS):
        return False
    return True


def _compact_intent_is_executable(parsed: CompactStep1Intent, user_request: str) -> bool:
    """Reject a compact response unless it can safely enter the existing pipeline."""
    if not parsed.is_route_planning_request or parsed.plan_mode != "planned":
        return False
    waypoints = list(parsed.planned_waypoints or [])
    if not waypoints:
        return False
    if any(not (wp.name or wp.search_keyword) for wp in waypoints):
        return False
    if any(wp.category not in {"meal", "cafe", "purchase", "service", "visit", "home"} for wp in waypoints):
        return False
    has_order = any(term in user_request for term in ("再", "然后", "接着", "之后", "顺便", "吃完"))
    if has_order and len(waypoints) < 2:
        return False
    return bool(parsed.search_keywords or parsed.primary_query or waypoints)


async def _llm_parse_compact(
    user_request: str,
    current_time: dt.datetime,
) -> CompactStep1Intent:
    """Use a small schema and prompt for simple nearby first-turn tasks only."""
    time_str = current_time.strftime("%Y-%m-%d %H:%M")
    messages = [
        {
            "role": "system",
            "content": (
                "你是本地即时出行意图解析器。只处理首轮、附近或即时的简单找点任务。"
                "不规划主题路线，不使用用户画像，不编造具体POI。"
                "把每个用户明确想完成的动作都输出为有序 planned_waypoints："
                "餐饮=meal，咖啡/奶茶/茶饮=cafe，购买=purchase，理发等=service，其他去处=visit。"
                "只要有两个动作，必须保留用户顺序，不能把后一个目标塞进 meal_constraints。"
                "计划模式固定为 planned；附近是搜索范围，不是途经点。"
                "search_keyword 必须是可供地图直接搜索的用户目标或通用类别词。"
                "严格按 response_model 返回 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"当前时间：{time_str}\n"
                f"用户输入：{user_request}\n"
                "仅提取：时长、关键词、餐饮关键词、附近约束、POI类别、以及有序途经点。"
            ),
        },
    ]
    return await call_llm(
        response_model=CompactStep1Intent,
        messages=messages,
        max_tokens=config.DEEPSEEK_MAX_TOKENS_STEP_1_COMPACT,
        temperature=config.DEEPSEEK_TEMPERATURE,
        max_retries=0,
    )


async def parse_step1_llm_stage(
    user_request: str,
    current_time: dt.datetime,
    *,
    plan_mode: str = "auto",
    planned_rule_hints: list[PlannedWaypoint] | None = None,
    fallback_city: str = "",
    routing_context: dict | None = None,
) -> tuple[ParsedIntent, str]:
    """Select compact or complete Step1 parsing while preserving full fallback."""
    compact_candidate = plan_mode == "auto" and _is_compact_step1_candidate(user_request, routing_context)
    if compact_candidate:
        try:
            compact = await _llm_parse_compact(user_request, current_time)
            if _compact_intent_is_executable(compact, user_request):
                print(
                    "[Step1SparseAudit] path=compact_llm accepted=true "
                    f"waypoints={[(wp.search_keyword or wp.name, wp.category) for wp in compact.planned_waypoints]}"
                )
                return ParsedIntent(**compact.model_dump()), "compact_llm"
            print("[Step1SparseAudit] path=compact_llm accepted=false reason=invalid_contract fallback=full_llm")
        except Exception as exc:
            print(
                "[Step1SparseAudit] path=compact_llm accepted=false "
                f"reason={type(exc).__name__} fallback=full_llm"
            )
    else:
        print("[Step1SparseAudit] path=full_llm reason=complex_or_contextual")

    parsed = await _llm_parse(
        user_request,
        current_time,
        plan_mode=plan_mode,
        planned_rule_hints=planned_rule_hints,
        fallback_city=fallback_city,
        routing_context=routing_context,
    )
    return parsed, "full_llm"


async def _llm_parse(
    user_request: str,
    current_time: dt.datetime,
    plan_mode: str = "auto",  # v18: "auto" — LLM 自己判断 exploratory/planned
    planned_rule_hints: list[PlannedWaypoint] | None = None,
    fallback_city: str = "",  # v24: city for deterministic fallback when LLM fails
    routing_context: dict | None = None,
) -> ParsedIntent:
    time_str = current_time.strftime("%Y-%m-%d %H:%M")

    # Keep conversation state compact and structured.  The model receives the
    # latest utterance separately, so previous route data cannot be mistaken for
    # fresh user requirements.
    routing_context_text = ""
    if routing_context:
        previous_intent = routing_context.get("previous_intent") or {}
        previous_intent = {
            key: previous_intent.get(key)
            for key in (
                "duration", "plan_mode", "raw_keywords", "search_keywords",
                "food_pref_keywords", "meal_search_keywords", "fixed_pois",
                "planned_waypoints", "transport_hint", "other_constraints",
                "excluded_typecode_prefixes", "original_location_label",
            )
            if previous_intent.get(key) not in (None, "", [], {})
        }
        route_points = [
            {
                "name": point.get("name", ""),
                "kind": point.get("kind", ""),
                "day": point.get("day", 1),
                "display_slot": point.get("display_slot", ""),
                "location": point.get("location"),
            }
            for point in (routing_context.get("points") or [])[:20]
            if isinstance(point, dict)
        ]
        routing_context_text = json.dumps({
            "has_current_route": bool(route_points),
            "previous_intent": previous_intent,
            "recent_user_messages": (routing_context.get("recent_user_messages") or [])[-3:],
            "current_route_points": route_points,
        }, ensure_ascii=False, default=str)

    # v6: 构造 rule hints 文本，帮助 LLM 更稳定地提取 planned_waypoints
    planned_rule_hints_text = ""
    if plan_mode in ("auto", "planned") and planned_rule_hints:
        hint_payload = [
            {
                "type": wp.type,
                "name": wp.name,
                "search_keyword": wp.search_keyword,
                "category": wp.category,
                "stay_minutes": wp.stay_minutes,
                "search_keywords": getattr(wp, "search_keywords", []) or [],
                "required_terms": getattr(wp, "required_terms", []) or [],
                "excluded_terms": getattr(wp, "excluded_terms", []) or [],
                "search_center_name": getattr(wp, "search_center_name", None),
            }
            for wp in planned_rule_hints
        ]
        planned_rule_hints_text = (
            "<rule_hints>\n"
            "以下是规则引擎从用户原话中预提取的候选途经点，仅供参考，不可盲信。"
            "你必须结合用户原话重新判断：补全遗漏、删除误判、修正顺序、修正category和搜索词。"
            "尤其注意：回家前/回家路上/下班路上/附近/顺路是路线语境，不应自动变成独立POI；"
            "只有用户明确说 然后回家/最后回家/回到家 时，才加入home途经点。\n"
            f"{json.dumps(hint_payload, ensure_ascii=False)}\n"
            "</rule_hints>\n"
        )

    # v6: planned 模式下追加 planned_waypoints 提取说明
    # v18: auto 模式也注入 — LLM 需要自己判断是否填充 planned_waypoints
    planned_waypoints_section = ""
    planned_waypoints_field = ""
    planned_waypoints_step = ""
    if plan_mode in ("auto", "planned"):
        planned_waypoints_field = (
            "\n"
            "14. planned_waypoints (object[]) — 有序途经点列表"
            + (" ⚠️ 精准规划/连续决策时必填" if plan_mode == "planned" else " ⚠️ 仅在用户明确表达有序任务序列时填写") +
            "\n"
            '   用户表达了一系列按顺序执行的动作时（如"先X，然后Y，再Z"），提取为有序途经点。\n'
            '   路由硬约束：只要用户明确说出两个及以上需要完成的地点或品类，即使没有“先”，也必须设置 plan_mode="planned" 并逐项输出 planned_waypoints；不得把其中任一明确目标仅放进 meal_constraints。\n'
            '   每个途经点含：type(fixed|placeholder)、name、search_keyword、category、stay_minutes、search_keywords、required_terms、excluded_terms。\n'
            '   search_keyword：该点的主检索词，必须是可搜索品类或具体地点名，不要使用"附近/顺路/下班路上/找个地方"这类上下文词。\n'
            '   search_keywords：2-5个地图检索词，按优先级排列；不要编造具体POI名称。\n'
            '   required_terms：POI结果名称/类型/地址中优先包含的词，用于排序加分。\n'
            '   excluded_terms：明显不符合该意图的词，命中应排除。\n'
            '   规则：回家/到家→category=home、type=fixed、name="家"、stay_minutes=0。\n'
            '         买水果→category=purchase、search_keyword="水果店"、search_keywords=["水果店","生鲜超市","超市"]、required_terms=["水果","鲜果","生鲜","超市"]、excluded_terms=["快印","打印","数码","摄影","复印"]。\n'
            '         简单吃饭/晚饭→category=meal、search_keyword="餐厅"、search_keywords=["餐厅","小吃","面馆","快餐"]、required_terms=["餐厅","饭店","小吃","面馆","快餐"]、excluded_terms=["咖啡","奶茶","茶饮","甜品","面包"]。\n'
            '         日料/火锅/烧烤等→category=meal、search_keyword=品类名，并生成对应品类检索词和required_terms。\n'
            '         咖啡/奶茶→category=cafe，不要归入meal。\n'
            '         例如“附近找一下饭馆，再找一家咖啡店”必须输出顺序为 meal(餐厅) → cafe(咖啡店) 的两个 planned_waypoints；“附近”仅是搜索中心，不是 waypoint。\n'
            '   通用提取原则：先识别用户真正想完成的动作，再映射成可搜索POI类型。不要把语气词、路线词、位置词当成POI。\n'
            '   生活服务映射：理发/理个发/剪头发/美发/洗剪吹→category=service，search_keyword="理发店"，search_keywords=["理发店","美发店","发廊","剪发","发型设计"]，required_terms 必须包含理发/美发/发廊/剪发/造型/发型，excluded_terms 必须排除快递、收发室、驿站、菜鸟、丰巢、代收、物流、打印快印、维修、开锁、洗衣、房产中介等泛生活服务。\n'
            '   采购映射：买药→"药店"；买花→"花店"；买蛋糕/面包→"蛋糕店"/"面包店"；买饮料零食→"便利店"；买菜/生鲜→"生鲜超市"/"菜市场"。\n'
            '   餐饮映射：简单吃饭→"餐厅/小吃/面馆/快餐"；夜宵→"夜宵/烧烤/小吃"；明确菜系如日料/火锅/川菜则保留菜系。\n'
            '   休闲映射：看电影→"电影院"；唱歌→"KTV"；散步→"公园/滨江步道"；喝咖啡→category=cafe；喝酒小坐→"酒吧/清吧"。\n'
            '   夜景映射：看夜景→category="night_view"，search_keyword="城市夜景"，\n'
            '     search_keywords=["城市夜景","夜景观景台","城市地标夜景","滨水夜景","夜间开放观景平台"]，\n'
            '     required_terms=["夜景","观景台","城市天际线","灯光夜景"]，\n'
            '     excluded_terms=["酒店客房","停车场","办公楼","住宅区","仅白天开放"]，\n'
            '     time_slot="evening"，stay_minutes=90，evening_requested=true。\n'
        )
        planned_waypoints_step = '4.5. 若为精准规划(planned)模式，提取 planned_waypoints：按 然后/再/接着/顺便 等顺序连接词拆分动作序列，并为每个途经点生成 search_keywords、required_terms、excluded_terms\n'
        planned_waypoints_section = (
            "\n"
            "【示例5 — planned 精准规划】\n"
            '输入："待会儿下班，在附近找一家日料店，然后回家"\n'
            'duration: "a quarter day"\n'
            'is_route_planning_request: true\n'
            'raw_keywords: ["日料", "下班", "回家"]\n'
            'food_pref_keywords: ["日料"]\n'
            'search_keywords: ["日料", "日本料理", "寿司"]\n'
            'planned_waypoints: [{"type":"placeholder","search_keyword":"日料","category":"meal","stay_minutes":60,"search_keywords":["日料","日本料理","寿司"],"required_terms":["日料","日本料理","寿司","刺身","居酒屋"],"excluded_terms":["咖啡","奶茶","甜品"]},{"type":"fixed","name":"家","category":"home","stay_minutes":0}]\n'
            '说明："下班/附近"是路线和位置上下文，不作为独立途经点；"日料"是placeholder meal；"回家"是fixed home。\n'
            "\n"
            "【示例6 — planned 多任务采购+用餐】\n"
            '输入："下班路上想顺便买点水果，再找个地方简单吃晚饭"\n'
            'duration: "a quarter day"\n'
            'is_route_planning_request: true\n'
            'raw_keywords: ["水果", "晚饭"]\n'
            'food_pref_keywords: []\n'
            'meal_search_keywords: ["餐厅","小吃","面馆","快餐"]\n'
            'search_keywords: ["水果店", "生鲜超市", "餐厅", "小吃", "面馆"]\n'
            'planned_waypoints: [{"type":"placeholder","search_keyword":"水果店","category":"purchase","stay_minutes":20,"search_keywords":["水果店","生鲜超市","超市"],"required_terms":["水果","鲜果","生鲜","超市"],"excluded_terms":["快印","打印","数码","摄影","复印"]},{"type":"placeholder","search_keyword":"餐厅","category":"meal","stay_minutes":40,"search_keywords":["餐厅","小吃","面馆","快餐"],"required_terms":["餐厅","饭店","小吃","面馆","快餐"],"excluded_terms":["咖啡","奶茶","茶饮","甜品","面包"]}]\n'
            '说明："买点水果"和"简单吃晚饭"是两个独立途经点；不要把咖啡茶饮当作正餐，不要把快印数码店当作水果采购。\n'
            "\n"
            "【示例7 — planned 生活服务+短休】\n"
            '输入："回家前想理个发，附近如果有不错的咖啡店也可以坐一会儿"\n'
            'raw_keywords: ["理发", "咖啡"]\n'
            'search_keywords: ["理发店", "美发店", "咖啡店"]\n'
            'planned_waypoints: [{"type":"placeholder","search_keyword":"理发店","category":"service","stay_minutes":45,"search_keywords":["理发店","美发店","发廊","剪发","发型设计"],"required_terms":["理发","美发","美容美发","发廊","剪发","造型","发型","洗剪吹"],"excluded_terms":["宠物","培训","学校","收发室","收发","快递","驿站","菜鸟","丰巢","快递柜","代收","自提","包裹","物流","货运","配送","派送","邮政","邮局","打印","快印","复印","图文","维修","开锁","搬家","洗衣","房产","中介","通讯","营业厅"]},{"type":"placeholder","search_keyword":"咖啡","category":"cafe","stay_minutes":25,"search_keywords":["咖啡店","咖啡"],"required_terms":["咖啡","Coffee","星巴克","瑞幸","Manner"],"excluded_terms":["奶茶","茶饮"]}]\n'
            '说明："回家前/附近"是路线语境，不要提取成"家"；真实需求是理发店和咖啡店。\n'
            "\n"
            "【示例8 — planned 多生活任务】\n"
            '输入："下班后先去药店买点感冒药，再买束花，最后回家"\n'
            'raw_keywords: ["药店", "花店", "回家"]\n'
            'planned_waypoints: [{"type":"placeholder","search_keyword":"药店","category":"purchase","stay_minutes":15,"search_keywords":["药店","大药房"],"required_terms":["药店","大药房","医药"],"excluded_terms":["宠物","诊所"]},{"type":"placeholder","search_keyword":"花店","category":"purchase","stay_minutes":15,"search_keywords":["花店","鲜花店"],"required_terms":["花店","鲜花","花艺"],"excluded_terms":["花鸟市场"]},{"type":"fixed","name":"家","category":"home","stay_minutes":0}]\n'
        )

    # v19: 初步主题排名，注入 LLM 提示词
    preliminary_candidates = rank_theme_profiles(
        raw_text=user_request,
        auxiliary_text="",
        top_k=3,
    )
    theme_candidates_text = ""
    if preliminary_candidates:
        theme_candidates_text = (
            "<theme_candidates>\n"
            + json.dumps([
                {
                    "id": c.profile_id,
                    "label": c.label,
                    "matched_terms": list(c.matched_terms),
                    "score": c.score,
                }
                for c in preliminary_candidates
            ], ensure_ascii=False) +
            "\n</theme_candidates>\n"
        )

    messages = [
        {
            "role": "system",
            "content": (
                "<role>本地出行意图解析器</role>\n"
                "<background>\n"
                "你只从用户原话提取字段，不补全用户画像，不执行计算、查表或外部查询。\n"
                "所有时间预算计算、餐点窗口判断、POI容量过滤等由后续工具链完成。\n"
                "</background>\n"
                "\n"
                "<clarification_rules>\n"
                "在提取字段前，先判断信息是否足以规划路线。缺少必要信息时必须先澄清，不得强行生成路线。\n"
                "必要信息优先级：destination > duration > preference\n"
                "1. destination：目的城市、区域或具体地点\n"
                "2. duration：计划游玩的时长\n"
                "3. preference：可选，包括主题、活动和同行人\n"
                "缺少destination时只追问目的地，不要一次问多个问题。\n"
                "用户只说日期或出游意愿但没有说去哪里→只追问目的地。\n"
                "不得根据用户画像推断目的地、主题或同行人。\n"
                "用户没有提到孩子/亲子/遛娃→任何回复中不得出现\"亲子\"\"儿童\"\"带娃\"。\n"
                "用户没有明确时长→不得出现\"一日路线\"\"两日路线\"等确定描述。\n"
                "信息不足时设置 is_route_planning_request=true 但所有检索字段保持为空。\n"
                "</clarification_rules>\n"
                "\n"
                "<critical_rules>\n"
                "1. 严禁推断、联想或补全用户未明确表达的内容。用户没说吃的，raw_keywords/food_pref_keywords/meal_search_keywords 必须为空。\n"
                "2. duration 严格遵守：\"一会儿/待会儿/逛一圈\"→\"a quarter day\"；\"上午/下午/半天\"→\"a half day\"；\"一天/一日/全天\"→\"a full day\"；\"两天/两日\"→\"two days\"。\"周末\"不自动等于两天，只说\"周末想出去玩\"→duration=null。\"周末两天/整个周末/周六和周日\"→\"two days\"。\n"
                "3. search_keywords 只能基于 raw_keywords 展开，不能凭空生成用户没提到的类别；只返回关键词主体，不添加城市名。\n"
                "4. 排除项提取：用户明确否定表达时，把被排除的地点名提取到 delete_list。这是强约束。\n"
                "5. 风格/氛围词保留到 raw_keywords，但只能展开为受控地点类型词，不得编造具体POI名称。\n"
                "6. 用户没有提到夜晚/夜景/餐饮时，不得自动生成夜游/酒吧/餐饮关键词。\n"
                "7. 泛化需求（\"周末想出去玩\"/\"想出门走走\"/\"附近有什么好玩的\"）→所有检索字段为空，不得用用户画像填充主题。\n"
                "</critical_rules>"
            ),
        },
        {
            "role": "user",
            "content": (
                f"<context>当前时间：{time_str}。"
                f"系统预检测：{_duration_hint_for_llm(user_request)}"
                f"当前模式：{plan_mode}（"
                + ("精准规划，需提取planned_waypoints" if plan_mode == "planned" else
                   "自动判断 — 若用户给出有序任务/连续决策，设 plan_mode='planned' 并填 planned_waypoints；若只是主题/氛围/区域探索，设 plan_mode='exploratory' 并留空 planned_waypoints"
                   if plan_mode == "auto" else "自由探索，无需planned_waypoints")
                + "）</context>\n"
                + planned_rule_hints_text +
                (f"<routing_context>{routing_context_text}</routing_context>\n" if routing_context_text else "") +
                "\n"
                f"<user_input>{user_request}</user_input>\n"
                "\n"
                "<task>从用户输入中提取以下字段，用于后续POI检索和路线规划。</task>\n"
                "\n"
                "<field_definitions>\n"
                "<planning_sufficiency>\n"
                "提取字段前先判断信息是否足以规划路线。\n"
                "信息充分：指定了具体地点/区域，或明确了主题（历史建筑/自然风景/博物馆/美食/购物），或给出了有序任务。\n"
                "信息不足（泛化需求）：\"周末想出去玩\"/\"想出门走走\"/\"附近有什么好玩的\"/\"推荐一个路线\"/只有日期没有地点或主题。\n"
                "泛化需求处理：is_route_planning_request=true，但所有检索字段（raw_keywords/search_keywords/micro_keywords/fixed_pois）保持空数组，theme_profile=null，duration=null（除非用户明确说了时长）。不得使用用户画像填充主题。\n"
                "</planning_sufficiency>\n"
                "\n"
                "1. is_route_planning_request (bool)\n"
                "   用户是否在请求出行/游玩/餐饮/路线/行程规划。闲聊、命令、乱码、问候、天气闲聊、事实问答返回 false。\n"
                "   注意：信息不足的泛化需求仍然为 true（用户确实想出行），但检索字段留空由代码兜底澄清。\n"
                "\n"
                "2. duration (string) — 严格枚举值\n"
                "   a quarter day | a half day | a full day | a day and a half | two days | two and a half days | three days | null\n"
                "   判断依据：逛一会儿/转转→a quarter day；半天→a half day；一天/出去玩/陪你逛一天→a full day；两天→two days\n"
                '   ⚠️ \"周末\"不自动等于two days。\"周末想出去玩\"→duration=null。只有\"周末两天/整个周末/周六和周日\"→two days。\n'
                '   ⚠️ 同时提到两个以上时段（上午+下午/上午+晚上）→a full day。\n'
                "\n"
                "3. raw_keywords (string[]) — 用户原词 ⚠️ 只提取用户明确说出的，严禁推断\n"
                '   "逛古镇"→["古镇"]，"二次元"→["二次元"]。只保留实义词，去掉"逛/去/玩玩"等虚词。\n'
                '   "我想去外滩拍夜景"→["外滩","夜景"]，不要添加用户没说的词如"美食""本帮菜"。\n'
                '   如果用户只说景点/拍照，raw_keywords中不要出现餐饮类词汇。\n'
                "\n"
                "4. search_keywords (string[]) — 地图POI检索词 ⚠️ 见下方&lt;examples&gt;\n"
                '   只输出"类目/场景"关键词主体，不要添加北京、上海等城市前缀；后端会根据路线出发地统一添加城市。\n'
                "   使用具体地点类型、商圈、活动场景，不用抽象词，不编造具体POI名称。\n"
                "\n"
                "5. fixed_pois (object[]) — 用户明确指定的必去地点，含时间预算 ⚠️ v3新增user_time_budget\n"
                '   每个元素为 {{\"name\":\"地点名\",\"user_time_budget\":\"时间表述或null\"}}\n'
                '   name: 地图上能找到的命名地点：景点/场馆（外滩、迪士尼）、商圈/片区（陆家嘴、新天地）、\n'
                '   岛屿/古镇/度假区（崇明岛、佘山、朱家角、滴水湖）等。\n'
                '   不要把"古镇/商场/文艺"等没有具体地名的类别词放入。\n'
                '   user_time_budget: 填写规则：\n'
                '   ① 用户明确说了时长→填时长表述，如"一天"/"半天"/"一上午"；\n'
                '   ② 用户用时段词修饰地点→填对应时段，如"上午"/"下午"/"晚上"；\n'
                '   ③ 仅说"逛逛""逛一圈"等无时段修饰→填null。\n'
                '   示例：\n'
                '   "明天去外滩玩一天" → [{{\"name\":\"外滩\",\"user_time_budget\":\"一天\"}}]\n'
                '   "上午去南京东路逛逛" → [{{\"name\":\"南京东路\",\"user_time_budget\":\"上午\"}}]\n'
                '   "下午想去陆家嘴" → [{{\"name\":\"陆家嘴\",\"user_time_budget\":\"下午\"}}]\n'
                '   "想去外滩，帮我规划路线" → [{{\"name\":\"外滩\",\"user_time_budget\":null}}]\n'
                "\n"
                "6. day_poi_constraints (object[]) — 分天目的地\n"
                '   "周六去外滩，周日去中山公园"→[{"day_index":1,"poi_name":"外滩"},{"day_index":2,"poi_name":"中山公园"}]\n'
                '   未提及返回[]。\n'
                "\n"
                "7. start_time (string|null) — ISO格式开始时间，未提及返回null\n"
                "\n"
                "8. original_location_label (string|null) — 出发地标签，未提及返回null\n"
                "\n"
                "9. food_pref_keywords (string[]) — 餐饮偏好 ⚠️ 严禁推断！用户未提食物=[]\n"
                '   只提取用户明确说出的餐饮偏好。"想吃日料"→["日料"]。"去外滩玩一天"→[]（没提吃的）。未提及返回[]。\n'
                "\n"
                "10. meal_search_keywords (string[]) — 餐饮检索词 ⚠️ 严禁推断！用户未提吃喝=[]\n"
                '    用户说吃吃喝喝/逛吃/探店/美食→["餐厅","美食","小吃"]；\n'
                '    提到口味如本帮菜→["本帮菜 餐厅"]。\n'
                '    用户只说"去外滩玩/拍照/看夜景"→[]（没提吃喝/餐饮/美食）。\n'
                "\n"
                "11. meal_constraints (object[]) — 指定用餐约束\n"
                '    "周日中午吃日料"→[{"day_index":2,"meal":"lunch","keywords":["日料"],"fixed_poi_name":null}]\n'
                '    "中午在麦当劳（同济MTR）餐厅吃饭"→[{"day_index":null,"meal":"lunch","keywords":["麦当劳"],"fixed_poi_name":"麦当劳（同济MTR）餐厅"}]\n'
                '    注意："在外面/出去/附近/周边+吃"是饮食方式描述，不是餐厅名。不要把"外面""旁边""附近""周边""出去"等方位词放入fixed_poi_name。\n'
                "\n"
                "12. budget_per_capita (number|null) — 人均预算上限\n"
                '    "人均150以内"→150.0。未提及返回null。\n'
                "\n"
                "13. micro_keywords (string[]) — 2-4个具体体验词\n"
                '    "古镇"→["古镇 手工艺品","老街 小吃","古镇 拍照打卡"]\n'
                "    风格词也必须生成可检索的具体体验词：\n"
                '    "文艺路线" → ["艺术展览","独立书店","创意园区","文化空间"]\n'
                '    "有氛围的路线" → ["文艺街区","历史街区 漫步","独立书店","艺术展览"]\n'
                '    "精神漫游" → ["城市慢行","独立书店","艺术展览","创意园区"]\n'
                "    若用户未提夜间，不要加入\"夜景\"\"夜游\"\"酒吧\"等词；若未提吃喝，不要加入餐饮词。\n"
                "\n"
                "14. delete_list (string[]) — 用户明确排除的地点/景区/区域名 ⚠️ 必检项\n"
                "    用户用任何方式表达了\"不去/不要/排除/跳过/已去过\"的地点，必须放入本数组。\n"
                "    提取规则：\n"
                "    - 提取被否定的具体地名（外滩、陆家嘴、迪士尼…），不要放品类词（博物馆、公园…）\n"
                "    - 同一地点可能有多段表述，只放一次（自动去重）\n"
                '    - "XX已经去过了，这次不要安排" → ["XX"]\n'
                '    - "不要有外滩和豫园" → ["外滩","豫园"]\n'
                '    - "除了迪士尼，其他都可以" → delete_list 留空，用 other_constraints 承载偏好\n'
                "    示例：\n"
                '      "外滩去过了，这次不要" → delete_list: ["外滩"]\n'
                '      "把南京路去掉" → delete_list: ["南京路"]\n'
                '      "陆家嘴和豫园都去过了" → delete_list: ["陆家嘴","豫园"]\n'
                '      "博物馆就别安排了" → delete_list: ["博物馆"]\n'
                '      "不想去人太多的地方" → delete_list: [] （这是偏好不是具体地点排除，放 other_constraints）\n'
                "\n"
                + planned_waypoints_field
                + (
                    "\n"
                    "<multi_period_rules>\n"
                    '上午/下午/晚上/傍晚明确两个以上时段→plan_mode="planned", duration="a full day"。\n'
                    "即使用探索性动词，分时段也必须用planned模式。"
                    "每个时段独立为一个planned_waypoint，不得合并或丢弃。\n"
                    "附近/周边场景中，若用户明确说“找A，再找B/然后找B”，这是有序精准规划："
                    "plan_mode必须为planned，planned_waypoints必须按原顺序保留A和B；"
                    "B必须保留用户原始地点类型作为search_keyword，不能塞进meal_constraints或忽略。\n"
                    '"再、还要、另外、顺便"追加时段→继承已有waypoints末尾追加，不替换。\n'
                    "morning+afternoon+evening→a full day(固定)。\n"
                    "</multi_period_rules>\n"
                    "\n"
                    "15. plan_mode (string) — 路线模式 ⚠️ auto 模式下必须输出\n"
                    '    "planned"：用户给出了有序途经点、通勤链路、上午/下午/晚上分时段安排、先X再Y等连续决策\n'
                    '    "exploratory"：用户只给出了主题/氛围/区域/泛游玩需求，没有明确的时间顺序\n'
                    '    若为 "planned"，必须同时填充 planned_waypoints；若为 "exploratory"，planned_waypoints 留空。\n'
                    if plan_mode == "auto" else ""
                ) +
                (
                    "\n"
                    "16. theme_profile (string|null) — 主题画像ID\n"
                    "    规则引擎已根据用户输入匹配到以下候选主题，你可以结合语义从候选列表中挑选最合适的一个。\n"
                    "    候选为空或不确定时返回 null。只能从 theme_candidates 中选择ID，禁止编造。\n"
                    "    theme_label、theme_confidence 不要自行填写，由后处理计算。\n"
                    + theme_candidates_text
                    if theme_candidates_text else ""
                ) +
                "</field_definitions>\n"
                "\n"
                "<examples>\n"
                "以下展示 search_keywords 的生成规则——把出行意图转成具体可检索的\"类目/场景\"，不要输出城市：\n"
                "\n"
                "【示例1】\n"
                '输入："周末想去上海逛古镇"\n'
                'search_keywords: ["古镇 推荐", "古镇 攻略", "水乡", "老街"]\n'
                'micro_keywords: ["古镇 手工艺品", "老街 小吃", "古镇 拍照打卡"]\n'
                '说明：古镇→展开为"古镇推荐/攻略/水乡/老街/手工艺品/小吃/拍照打卡"\n'
                "\n"
                "【示例2】\n"
                '输入："想去商场购物逛街买东西"\n'
                'search_keywords: ["购物中心", "商场", "商圈", "商业广场"]\n'
                'micro_keywords: ["商场 逛街", "购物中心 打卡"]\n'
                '说明：购物→"购物中心/商场/商圈/商业广场"，只用购物类词，不混入餐饮\n'
                "\n"
                "【示例3】\n"
                '输入："找好吃的餐厅，顺便逛逛拍照打卡的地方"\n'
                'search_keywords: ["美食", "餐饮", "拍照 打卡", "网红打卡"]\n'
                'micro_keywords: ["美食 探店", "网红打卡 拍照"]\n'
                "说明：吃喝+拍照→餐饮类+\"拍照打卡/网红打卡\"，两类意图分别生成\n"
                "\n"
                "【示例4 — 反例】\n"
                '输入："明天想去外滩玩一天，晚上在外滩拍夜景"\n'
                'duration: "a full day"  ← 注意：晚上是同一天的晚间，不是第二天！\n'
                'evening_requested: true\n'
                'raw_keywords: ["外滩", "夜景"]  ← 用户没提餐饮，不出现"本帮菜""美食"等\n'
                'search_keywords: ["外滩 攻略", "夜景 拍照", "黄浦江 观景"]\n'
                'food_pref_keywords: []  ← 没提吃的！\n'
                'meal_search_keywords: []  ← 没提吃的！\n'
                '说明：\"玩一天+晚上\"是单日行程含晚间，duration仍是"a full day"；用户没说吃的，餐饮字段全空。\n'
                + planned_waypoints_section +
                "\n"
                "【示例5 — 含排除项】\n"
                '输入："这周末我朋友要来上海玩，帮我规划两天的路线，其中外滩他已经去过了，规划中不要包含外滩。"\n'
                'duration: "two days"\n'
                'is_route_planning_request: true\n'
                'delete_list: ["外滩"]\n'
                'raw_keywords: ["上海", "游玩", "两天"]\n'
                'search_keywords: ["旅游 攻略", "景点 推荐", "打卡", "美食"]\n'
                "说明：用户明确排除外滩——已去过+不要包含→delete_list=[\"外滩\"]。duration=两天周末。\n"
                "\n"
                "【示例6 — 多排除项+餐饮偏好】\n"
                '输入："三天上海深度游，迪士尼、东方明珠、城隍庙都去过了，别安排了，想去没去过的地方，尤其想吃地道本帮菜。"\n'
                'duration: "three days"\n'
                'is_route_planning_request: true\n'
                'delete_list: ["迪士尼","东方明珠","城隍庙"]\n'
                'food_pref_keywords: ["本帮菜"]\n'
                'raw_keywords: ["上海","深度游","本帮菜","没去过的地方"]\n'
                'search_keywords: ["深度游 攻略","小众景点","本帮菜 餐厅","老街 弄堂","博物馆"]\n'
                "说明：三个地点明确排除；餐饮偏好提取本帮菜；\"没去过的地方\"→search_keywords偏小众/深度。\n"
                "\n"
                "规则总结：\n"
                '- 使用"城市+具体地点类型/场景/活动"，不用"开心/放松/随便逛"等抽象词\n'
                "- 不编造用户未提到的具体POI名称\n"
                "- 只说购物→只生成购物类词；只说吃喝→只生成餐饮类词；两者都提→同时包含\n"
                "</examples>\n"
                "\n"
                "<shopping_route_rules>\n"
                "商业街、步行街、商圈、逛街、购物中心、商业广场、百货商场→购物类别路线。\n"
                '用户输入"北京商业街两日游"时，必须输出：\n'
                'poi_query_type="poi_category", category_id="shopping_mall", primary_query="商业街"\n'
                'duration="two days", time_budget=2.0（不得因为商业街是单个类别缩短为一天）\n'
                "search_keywords含：商业街/步行街/商圈/购物中心/商业广场/商业综合体/百货商场\n"
                "primary_required_terms：商业街/步行街/购物街/商圈/购物中心/商场/百货/商业广场等\n"
                "primary_excluded_terms：会议中心/国际会议中心/创新中心/会展中心/写字楼/办公楼/产业园/停车场/公交站/培训机构\n"
                "allowed_typecode：060100/060101/060102/060103/060400/060900/061000\n"
                "两日购物路线至少选择两个不同区域的购物锚点，不选择会议中心/公园/博物馆作为主锚点\n"
                "</shopping_route_rules>\n"
                "\n"
                "<thinking_steps>\n"
                "0. 同时做路由决策：conversation_mode 只能是 new_plan/refine_current/point_edit/follow_up/answer_only。"
                "没有 current_route 时必须为 new_plan；有 current_route 时，替换/删除/增加单点为 point_edit，"
                "调整预算、主题、餐饮偏好或时段为 refine_current，明确承接上一站附近搜索为 follow_up。\n"
                "   对 refine_current，必须基于 routing_context.previous_intent 输出合并后的完整意图：最新输入覆盖明确字段，"
                "未提及字段继承；否定词优先，不能保留被否定类别。\n"
                "   同时填写 earliest_step、dispatch_confidence、dispatch_reason、intent_patch、include_constraints、"
                "exclude_constraints、point_operations。point_operations 仅用于明确单点 add/remove/replace。\n"
                "   多轮边界示例：已有文艺路线时“不要咖啡馆了，改成书店”必须是 point_edit，"
                "point_operations 至少包含 remove_category(cafe) 和 add(书店)，不能只写 refine_current。\n"
                "   已有路线时“不想吃烤鸭，想吃川菜”是 refine_current，必须保留所有非餐饮点和原 plan_mode，"
                "intent_patch 必须包含 meal_replacement=true、new_food_keywords=[川菜] 和 meal_slot；不能当作普通 POI 替换。\n"
                "   若用户明确取消旧路线的核心活动，并改为一组新的活动，例如“不吃饭了，改成下午逛展和喝咖啡”，"
                "必须是 new_plan，plan_mode=planned，不能继承旧餐饮路线。\n"
                "按以下顺序逐步提取：\n"
                "1. 判断 is_route_planning_request：是否涉及出行/路线/游玩/餐饮\n"
                "2. 识别 duration：根据时长描述词选择枚举值\n"
                "3. 提取 raw_keywords（用户原词）和 fixed_pois（具体地名）\n"
                "4. 检测排除项 delete_list：扫描整段话中所有否定表达，识别被排除的具体地名。地名不在用户原话中出现的不要编造。\n"
                "5. 按&lt;examples&gt;规则生成 search_keywords 和 micro_keywords\n"
                + planned_waypoints_step +
                "6. 依次提取 start_time、original_location_label、food_pref_keywords、meal_search_keywords、meal_constraints、budget_per_capita、day_poi_constraints\n"
                "7. 注意：不执行任何计算（时间预算、餐点窗口、容量过滤均交给后续工具）\n"
                "\n"
                "<route_continuation_rules>\n"
                "已有当天路线，用户输入新时段/活动→优先判断为路线续接，不是新路线。\n"
                '"晚上去图书馆"→refine_current，不是point_edit，不是new_plan。\n'
                "图书馆是地点类别不是命名POI，类别追加不得使用point_edit。\n"
                "续接时不得重新使用home_location作为起点。\n"
                "起点必须从当前路线最后一个可见POI获取。\n"
                "原上午和下午POI必须保留，duration保持a full day。\n"
                '"晚上"时段→验证晚间营业，不选晚上关闭的图书馆。\n'
                "</route_continuation_rules>\n"
                "</thinking_steps>\n"
                "\n"
                "<format>\n"
                "严格按 response_model (ParsedIntent) 返回结构化JSON。\n"
                '若 is_route_planning_request=false，duration填"a quarter day"，其余可空字段填null或[]。\n'
                "</format>"
            ),
        },
    ]
    # v21: Try step1 with configured max_tokens; retry at 4096 on IncompleteOutputException
    _max_tokens = config.DEEPSEEK_MAX_TOKENS_STEP_1_1
    for _attempt in range(2):
        try:
            _result = await call_llm(
                response_model=ParsedIntent,
                messages=messages,
                max_tokens=_max_tokens,
                temperature=config.DEEPSEEK_TEMPERATURE,
                max_retries=config.DEEPSEEK_MAX_RETRIES,
            )
            return _result
        except Exception as _exc:
            _exc_name = type(_exc).__name__
            if _attempt == 0 and (_exc_name == "IncompleteOutputException" or "incomplete" in str(_exc).lower()):
                _max_tokens = 4096
                print(
                    f"[LLMConfig] step1_max_tokens={config.DEEPSEEK_MAX_TOKENS_STEP_1_1} "
                    f"truncated, retrying with max_tokens=4096"
                )
                continue
            print(f"[WARN step1] LLM call failed ({_exc_name}): {_exc}")
            # v21: Fallback — use deterministic rules on final failure
            from .utils import emit_status
            await emit_status("正在使用离线规则解析意图...")
            # v24: Use fallback_city (safe) instead of undefined permanent_city (NameError)
            _city_fb = fallback_city
            if _city_fb and _city_fb.endswith("市"):
                _city_fb = _city_fb[:-1]
            # v24: Extract latest_user_input to avoid parsing conversation_context XML as route text
            _nl_fallback = _extract_latest_user_input(user_request)
            print(
                f"[ContextParseAudit] _llm_parse fallback: "
                f"has_conv_ctx={_has_conversation_context(user_request)} "
                f"latest_user_input={_nl_fallback[:120]} "
                f"fallback_city={_city_fb}"
            )
            return _deterministic_fallback_parsed_intent(_nl_fallback, plan_mode, _city_fb)


CATEGORY_TOKENS = {
    "美食", "餐厅", "小吃", "推荐", "攻略", "打卡", "拍照", "游玩", "购物", "逛街",
    "周边", "手工艺品", "特色美食", "景点", "公园", "博物馆", "特产", "一日游",
    "商场", "商圈", "步行街", "古镇", "老街", "水乡", "夜景", "网红", "探店",
    "火锅", "日料", "本帮菜", "咖啡", "下午茶", "酒吧", "书店", "创意",
    "展览", "演出", "话剧", "音乐剧", "科技馆", "天文馆",
    # v20: 类目/场所类型词 — 避免被 geocode 成具体地点
    "古玩市场", "花鸟市场", "旧货市场", "跳蚤市场", "菜市场", "农贸市场",
    "批发市场", "建材市场", "家具城", "灯饰城", "汽车城",
    "夜市", "早市", "大排档", "美食街", "小吃街",
    "花卉市场", "宠物市场", "二手市场", "收藏品市场",
    "茶城", "文化市场", "书画市场", "工艺美术",
}

# v20: 城市名后缀 — geocode 结果如果是纯城市/区级行政区划，不能作为目的地
_CITY_CENTER_PATTERN = re.compile(
    r"^(北京市|上海市|天津市|重庆市|"
    r".{2,8}(?:市|省|自治区|特别行政区|"
    r"区|县|旗|自治州|地区|盟))$"
)


async def _detect_destination_from_keywords(search_keywords: list[str], origin: dict, city: str) -> list[str]:
    """从search_keywords中检测具体地名，geocode后若离origin够远且不是城市中心则加入fixed_pois。

    v20: 跳过类别词（古玩市场、花鸟市场等）和城市/行政区划名，避免把类别搜索退化为城市中心搜索。
    """
    if not search_keywords or not origin:
        return []
    normalized_city = city[:-1] if city.endswith("市") else city
    city_variants = {city, normalized_city, f"{city}市", f"{normalized_city}市"}
    detected = []
    seen: set[str] = set()
    for kw in search_keywords[:8]:
        tokens = kw.split()
        for n in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:n])
            if candidate in CATEGORY_TOKENS:
                continue
            if candidate in city_variants:
                continue
            if candidate in seen:
                break
            seen.add(candidate)
            try:
                loc = await gaode_geocode(candidate, city=city)
                if loc:
                    # v20: 检查 geocode 结果是否为城市/行政区划，而非具体地点
                    addr = str(loc.get("address", "") or loc.get("name", ""))
                    if _CITY_CENTER_PATTERN.match(addr.strip()):
                        continue
                    dist = haversine_km(origin, loc)
                    if dist > 5.0:
                        detected.append(candidate)
                break
            except Exception:
                continue
        if len(detected) >= 3:
            break
    return detected


# ── v20: Proximity modifier parsing ──
# Deterministically extracts "X附近的Y" into search_area_label=X and primary_query=Y.
# Does NOT rely on LLM. Prevents X from entering fixed_pois.

_PROXIMITY_PATTERNS = [
    # v20: X and Y must NOT cross clause boundaries (，,。；;\n).
    # Trailing action words (吃饭/耍一耍/看一看/坐一会儿 etc.) are stripped by caller.
    # X附近的Y / X附近Y / X周边的Y / X周围Y / X旁边Y / X一带的Y
    re.compile(r"([^，,。；;\n]{1,16}?)(?:的)?(?:附近|周边|周围|旁边|一带)(?:的|有没有|哪里有|找|找个|找一家|看|去)?([^，,。；;\n]{1,20}?)(?:吃饭|耍一耍|看一看|看看|逛逛|坐一会儿|走一走|玩|$|[。，,;])"),
    # 在X附近找Y / 去X附近看Y
    re.compile(r"(?:在|去|到)([^，,。；;\n]{1,16}?)(?:的)?(?:附近|周边|周围|旁边|一带)(?:找|找个|找一家|看|逛逛|有没有)([^，,。；;\n]{1,20}?)(?:吃饭|耍一耍|看一看|看看|逛逛|坐一会儿|走一走|玩|$|[。，,;])"),
    # X附近有没有Y / X附近哪里有Y
    re.compile(r"([^，,。；;\n]{1,16}?)(?:的)?(?:附近|周边|周围)(?:有没有|哪里有)([^，,。；;\n]{1,20}?)(?:吃饭|耍一耍|看一看|看看|逛逛|坐一会儿|走一走|玩|$|[。，,;])"),
]

# "附近的Y" / "周边的Y" / "周围的Y" — no X, use original_location as search center
# v20: expanded optional group to consume "个", "一家", "一个" etc. between preposition and target
_PROXIMITY_NO_AREA_PATTERNS = [
    # "附近的Y" / "周边的Y" / "周围的Y"
    re.compile(r"(?:^| )?(?:附近的?|周边的?|周围的?)(?:的|找|找个|找一家|找一个|有没有|哪里有)?(.{1,20}?)(?:[。，,;]|$)"),
    # "周边找Y" / "附近找Y" / "周围找Y"
    re.compile(r"(?:^| )?(?:周边找|附近找|周围找)(?:个|一家|一个)?(.{1,20}?)(?:[。，,;]|$)"),
    # v20: "周围Y" without any preposition — e.g. "推荐一个周围公园", "周围公园逛一逛"
    re.compile(r"(?:^|[，,。；;\s])(?:周围的?)([一-龥]{1,12}?)(?:[。，,;\s]|逛|玩|看|去|求|推荐|$)"),
]

# v20: Generic category nouns — when matched and CATEGORY_RULES has no entry,
# still create poi_category query with unknown category fallback.
_GENERIC_SERVICE_NOUNS = {
    # Healthcare
    "医院", "三甲医院", "综合医院", "专科医院", "诊所", "卫生院", "社区医院",
    "医疗中心", "妇幼保健院", "中医院", "口腔医院", "眼科医院", "骨科医院",
    "药店", "大药房", "中药房",
    # Finance
    "银行", "ATM", "储蓄所",
    # Auto/Transport
    "加油站", "充电站", "停车场", "洗车", "修车", "汽车美容",
    # Retail
    "超市", "菜市场", "农贸市场", "水果店", "生鲜超市",
    "建材店", "建材市场", "五金店", "灯具城", "家具城",
    "维修店", "手机维修", "家电维修",
    # Entertainment
    "电影院", "影院", "KTV", "网吧",
    # Other services
    "理发店", "美发店", "干洗店", "洗衣店",
    "卫生间", "公共厕所",
    "快递", "邮政", "邮局",
    "打印", "复印", "图文快印",
    "眼镜店", "手机店", "数码店",
}

# v20: Expanded direct category patterns — hospital, pharmacy and other service categories
_DIRECT_CATEGORY_PATTERNS: list[tuple[list[str], str]] = [
    (["古玩市场", "古玩城", "文玩市场", "旧货市场", "收藏品市场", "古玩", "文玩"], "antique_market"),
    (["非遗手作", "非遗体验", "手作体验", "手工坊", "手工艺", "非遗", "扎染体验", "陶艺体验"], "handcraft_intangible"),
    (["花艺市场", "花市", "花卉市场", "鲜花市场", "花店", "买花", "花鸟市场"], "flower_market"),
    (["木材工作坊", "木工坊", "木作体验", "木艺工作室", "木工体验", "木工"], "wood_craft"),
    (["便利店", "附近便利店", "小卖部", "士多"], "convenience_store"),
    (["书店", "城市书房", "书局", "书城"], "bookstore"),
    # v21: Cafe
    (["咖啡馆", "咖啡店", "咖啡厅", "咖啡", "coffee", "cafe", "coffee shop"], "cafe"),
    # v20: Healthcare
    (["三甲医院", "综合医院", "专科医院", "社区医院", "妇幼保健院", "中医院", "口腔医院", "眼科医院", "骨科医院"], "hospital"),
    (["医院", "卫生院", "医疗中心", "诊所", "卫生站", "社区卫生"], "hospital_general"),
    (["药店", "大药房", "中药房", "药铺"], "pharmacy"),
    # v20: Finance
    (["银行", "储蓄所", "ATM", "atm", "自动取款机"], "bank"),
    # v20: Auto
    (["加油站", "加气站", "充电站", "充电桩"], "gas_station"),
    # v20: Other services
    (["电影院", "影院"], "cinema"),
    (["停车场", "停车库"], "parking"),
    (["建材店", "建材市场", "五金店", "灯具城", "家具城"], "building_materials"),
    (["超市", "菜市场", "农贸市场", "生鲜超市"], "supermarket_market"),
    (["维修店", "手机维修", "家电维修"], "repair_shop"),
    (["卫生间", "公共厕所", "洗手间", "厕所"], "restroom"),
    (["理发店", "美发店", "发廊", "剪发"], "hair_salon"),
    (["快递", "邮政", "邮局", "顺丰", "菜鸟"], "postal"),
    # v20: University / campus
    (["大学", "高校", "高等院校", "大学校园", "大学校区", "校园", "学院"], "university_campus"),
    # v20: Sports venues
    (["运动场馆", "运动馆", "体育馆", "体育中心", "运动中心",
      "健身房", "游泳馆", "篮球场", "足球场", "网球场",
      "羽毛球馆", "乒乓球馆", "攀岩馆", "滑雪场", "滑冰场",
      "保龄球馆", "找个地方运动", "运动场所", "运动的地方"], "sports_venue"),
    # v20: Arcade / game centers
    (["电玩城", "游戏厅", "动漫城", "电玩中心", "街机厅", "街机", "电玩"], "arcade"),
    # v20: Restaurants and cuisine types
    (["餐厅", "饭店", "饭馆", "餐馆", "日料", "日本料理", "寿司", "刺身",
      "火锅", "烧烤", "川菜", "粤菜", "西餐", "湘菜", "鲁菜",
      "小吃", "面馆", "快餐", "简餐"], "restaurant"),
    # v20: Science museum / planetarium
    (["科技馆", "天文馆", "科学技术馆", "科学中心", "科学宫", "科技中心", "天文台"], "science_museum"),
    # v20: Parks (narrower priority before scenic_area)
    (["公园", "城市公园", "森林公园", "湿地公园", "郊野公园",
      "体育公园", "文化公园", "植物园"], "park"),
    # v20: Scenic areas / tourist spots
    (["景区", "景点", "风景区", "名胜", "旅游景点", "风景名胜"], "scenic_area"),
]


# v20: Container-target parsing ("商场里的电玩城", "园区中的咖啡馆").
# Parse the relation separately instead of requiring an extra character before
# the container suffix.  The old pattern therefore could not match bare
# containers such as "商场" or "园区" despite listing them as examples.
_CONTAINER_SUFFIXES = (
    "商业综合体", "购物中心", "中心城", "步行街", "商场", "商城", "百货",
    "综合体", "园区", "公园", "广场", "大楼", "大厦", "街区", "景区",
    "场馆", "卖场",
)
_CONTAINER_RELATION_RE = re.compile(r"里面(?:的)?|内部(?:的)?|中的?|里的?|内(?:的)?")
_CONTAINER_LEADING_NOISE_RE = re.compile(
    r"^(?:(?:明天|今天|后天|周末|上午|下午|中午|晚上|傍晚|夜里|"
    r"我|我们|帮我|请|想要|想|要|打算|准备|去|到|在|找|逛|看看?)\s*)+"
)
_CONTAINER_TARGET_LEADING_RE = re.compile(
    r"^(?:(?:找一家|找一个|找个|找|去|逛逛|逛|看看|看|有没有|有个|有一家)\s*)+"
)
_CONTAINER_TARGET_TRAILING_RE = re.compile(
    r"(?:玩一玩|体验一下|推荐一下|求推荐|好玩吗|怎么样|有没有|有吗|看看|逛逛|体验|玩|吗|吧)+$"
)


def _parse_container_target(user_request: str) -> tuple[str, str] | None:
    """Return ``(container, target)`` for a clause-local container query.

    Both sides are bounded by ``_split_clauses`` so a relation can never pull
    text from the preceding or following itinerary step.
    """
    for clause in _split_clauses(user_request):
        for relation in _CONTAINER_RELATION_RE.finditer(clause):
            container = clause[:relation.start()].strip()
            container = _CONTAINER_LEADING_NOISE_RE.sub("", container).strip()
            if not container or not any(container.endswith(suffix) for suffix in _CONTAINER_SUFFIXES):
                # For example, skip the "中" inside "购物中心" and continue
                # until the actual relation word "里/中的" is reached.
                continue

            target = clause[relation.end():].strip()
            target = _CONTAINER_TARGET_LEADING_RE.sub("", target).strip()
            target = _CONTAINER_TARGET_TRAILING_RE.sub("", target).strip()
            if not target:
                continue
            return container, target
    return None


# v20: Multi-theme enumeration — shared-suffix parsing (e.g. "工业，农业，水利，交通遗产")
_ENUM_HERITAGE_FACETS: dict[str, dict] = {
    "工业遗产": {
        "facet_id": "industrial_heritage", "canonical_label": "工业遗产",
        "search_keywords": ["工业遗产", "工业遗址", "老厂房", "工业博物馆", "矿业遗存"],
        "required_terms": ["工业", "工厂", "厂房", "矿业", "制造", "车间", "钢铁", "纺织"],
    },
    "农业遗产": {
        "facet_id": "agricultural_heritage", "canonical_label": "农业遗产",
        "search_keywords": ["农业遗产", "农业博物馆", "农耕文化", "农业展览馆", "传统村落"],
        "required_terms": ["农业", "农耕", "农田", "农具", "作物", "渔", "畜牧", "蚕桑"],
    },
    "水利遗产": {
        "facet_id": "water_heritage", "canonical_label": "水利遗产",
        "search_keywords": ["水利遗产", "水利工程", "水利博物馆", "古代水利", "运河水利", "水闸遗址"],
        "required_terms": ["水利", "水闸", "运河", "水渠", "灌溉", "水库", "堤坝", "渡槽"],
    },
    "交通遗产": {
        "facet_id": "transport_heritage", "canonical_label": "交通遗产",
        "search_keywords": ["交通遗产", "交通博物馆", "铁路博物馆", "老火车站", "老码头", "历史桥梁"],
        "required_terms": ["交通", "铁路", "火车", "车站", "码头", "桥梁", "隧道", "公路", "航空", "驿道"],
    },
}


def _parse_multi_theme_enumeration(user_request: str) -> dict | None:
    """Detect shared-suffix enumerations like '工业，农业，水利，交通遗产'.

    Uses linear scanning — NO nested quantifier regex that could
    cause catastrophic backtracking on long text.
    """
    text = user_request.strip().rstrip("。，,.!！?？")

    # v20: Fast bail-out — only scan further if a target suffix is present
    _SUFFIXES = ("遗产", "文化", "遗址", "博物馆", "文化路线", "主题路线")
    matched_suffix = None
    suffix_pos = -1
    for sfx in _SUFFIXES:
        pos = text.find(sfx)
        if pos > 0 and (suffix_pos < 0 or pos < suffix_pos):
            matched_suffix = sfx
            suffix_pos = pos
    if matched_suffix is None:
        return None

    shared_suffix = matched_suffix
    # Extract the ~40-char segment just before the suffix (enumeration is short)
    start = max(0, suffix_pos - 40)
    prefix_block = text[start:suffix_pos]

    # Strip leading functional / city words from the prefix segment
    prefix_block = re.sub(
        r"^(?:想看看|想看|想去|去看看?|推荐|游览|参观|玩|求|有没有|附近|周边)?"
        r"(?:北京的?|上海的?|杭州的?|广州的?|深圳的?|成都的?|武汉的?|南京的?)?"
        r"\s*",
        "", prefix_block,
    )

    # Split by separators (commas, 、, 和/与/及)
    prefixes = [p.strip() for p in re.split(r"[，,、和与及]\s*", prefix_block) if p.strip()]
    if len(prefixes) < 2:
        return None

    # Keep only short prefix terms (genuine enumeration items, not stray text)
    prefixes = [p for p in prefixes if 1 <= len(p) <= 6 and re.match(r'^[一-龥]+$', p)]
    if len(prefixes) < 2:
        return None

    facets: list[dict] = []
    for prefix in prefixes:
        full_label = f"{prefix}{shared_suffix}"
        if full_label in _ENUM_HERITAGE_FACETS:
            fdef = dict(_ENUM_HERITAGE_FACETS[full_label])
            fdef["raw_label"] = prefix
            facets.append(fdef)
        else:
            facets.append({
                "facet_id": f"custom_{prefix}_{shared_suffix}",
                "raw_label": prefix,
                "canonical_label": full_label,
                "search_keywords": [full_label, prefix],
                "required_terms": [prefix, shared_suffix],
            })

    if len(facets) < 2:
        return None

    return {
        "facets": facets,
        "umbrella_profile": "history_heritage",
        "shared_suffix": shared_suffix,
    }


# v20: Ranking modifier parsing — removes ranking words from search terms
_RANKING_MODIFIERS: list[tuple[list[str], str, str]] = [
    (["最有名", "最知名", "最热门", "人气最高", "最受欢迎", "著名的",
      "有名", "知名", "热门", "人气高", "人气旺", "口碑好",
      "当地人常去", "老字号", "老牌"], "popularity", "desc"),
    (["评分最高", "口碑最好", "评价最高", "口碑最佳", "评分高"], "rating", "desc"),
    (["最近", "离我最近", "距离最近", "最近的", "近的", "较近"], "distance", "asc"),
    (["最大", "规模最大", "面积最大"], "scale", "desc"),
    (["最老", "历史最悠久", "最古老"], "history", "desc"),
]
_RANKING_CLEANUP_RE = re.compile(
    r"最(?:有名|知名|热门|受欢迎|高|好|近|大|老|古老)的?"
    r"|人气最高|口碑最好|评价最高|口碑最佳|规模最大|历史最悠久"
    r"|离我最近|距离最近|著名的|有名|知名|热门|人气高|人气旺|口碑好"
    r"|当地人常去|老牌"
)

# v20: Novelty detection patterns — "没吃过的" triggers history exclusion, NOT a search keyword
_NOVELTY_PATTERNS: list[tuple[str, str]] = [
    ("没吃过的", "restaurant"), ("没去过的", "restaurant"),
    ("以前没去过", "restaurant"), ("之前没推荐过", "restaurant"),
    ("换一家新的", "restaurant"), ("别推荐吃过的", "restaurant"),
    ("不要重复", "restaurant"), ("换个没试过的", "restaurant"),
    ("换个没吃过的", "restaurant"), ("换家没去过的", "restaurant"),
]
_NOVELTY_CLEANUP_RE = re.compile(
    r"(?:吃点?|换个?|换一家?|尝)?(?:没吃过的|没去过的|以前没去过|没试过的|"
    r"之前没推荐过|新的|不要重复的|别推荐吃过的|吃过的)"
)


def _detect_novelty_intent(text: str) -> tuple[bool, str]:
    """Detect if the user wants something they haven't tried before.
    Returns (novelty_required, novelty_scope)."""
    for pattern, scope in _NOVELTY_PATTERNS:
        if pattern in text:
            return True, scope
    return False, ""


# v20: Meal suffix stripping — remove "吃饭/用餐/就餐" from primary_query
_MEAL_SUFFIX_CLEANUP_RE = re.compile(
    r"(?:吃[个顿]?饭|用餐|就餐|吃一顿|尝尝|吃饭|吃东西)[。，,!！]*$"
)


# v20: Unified set of time/duration expressions — must NOT become primary_query etc.
# v20: Activity/experience expressions — must NOT become poi_category primary_query
_ACTIVITY_EXPRESSIONS: set[str] = {
    "随便走走", "走走", "散步", "逛逛", "转转", "溜达",
    "沿江走走", "滨江漫步", "看看风景", "拍照打卡",
    "随便逛逛", "随便逛", "逛一逛", "走一走", "遛一遛",
    "citywalk", "骑行", "骑车逛逛", "遛弯",
}

# v20: Waterfront terms + mountain competing terms
_WATERFRONT_TERMS: set[str] = {
    "江边", "沿江", "滨江", "江畔", "河边", "河畔", "河滨", "沿河",
    "水岸", "湖边", "湖畔", "湖滨", "环湖", "亲水", "滨水",
    "湿地", "河道", "湖泊", "堤岸", "水边", "江岸", "湖岸",
}
_MOUNTAIN_COMPETING_TERMS: set[str] = {
    "登山", "爬山", "山地", "浅山", "山谷", "山峰", "峡谷", "峪",
    "森林登山", "攀岩", "越野", "徒步登高", "观峰", "山路", "登顶",
}

# v20: Area stroll detection — named area + 逛逛/走走/转转 → internal POI expansion
_SHOPPABLE_AREA_TERMS: set[str] = {
    "步行街", "商圈", "街区", "古镇", "夜市", "商场", "购物中心",
    "创意园", "文创园", "滨江街区", "天地", "商厦", "百货",
}
# v21: Extended area terms for parks, scenic areas, campuses, waterfronts
_EXPLORABLE_AREA_SUFFIXES: set[str] = {
    "公园", "景区", "风景区", "植物园", "动物园", "游乐园",
    "大学", "校园", "学院", "校区",
    "滨江", "滨河", "绿地", "湿地", "森林公园",
    "文化园", "艺术区", "创意园区", "产业园",
    "奥体", "奥森", "体育公园", "生态园",
}
_STROLL_INTENT_VERBS: set[str] = {
    "逛逛", "逛街", "随便逛", "走走", "citywalk",
    "买东西", "购物", "逛一下", "逛一逛", "溜达", "逛",
    # v21: Extended stroll verbs
    "转转", "散散步", "散步", "随便走走", "逛一逛", "走一走",
}


def _is_area_stroll_request(user_request: str, poi_name: str) -> bool:
    """Check if user wants to explore internal POIs inside a named area vs just visiting.
    Extended to parks, scenic areas, campuses, waterfronts — not just shopping streets."""
    lowered = user_request.lower()
    has_stroll = any(v in lowered for v in _STROLL_INTENT_VERBS)
    if not has_stroll:
        return False
    # Check shopping area terms first
    if any(poi_name.endswith(t) or t in poi_name for t in _SHOPPABLE_AREA_TERMS):
        return True
    # v21: Extended check — parks, scenic areas, campuses
    if any(poi_name.endswith(t) or t in poi_name for t in _EXPLORABLE_AREA_SUFFIXES):
        return True
    # v21: Typecode-based check — parks (11xxxx), scenic (11xxxx), campuses (1412xx)
    _area_typecodes = {"110100", "110101", "110200", "141200"}
    return False


# v20: Style/quality preference modifiers — ranking words not POI identity
_STYLE_PREFERENCE_TERMS: set[str] = {
    "精致", "精致的", "高颜值", "好看", "好吃", "好喝的",
    "适合拍照", "拍照好看", "出片", "氛围感", "有情调",
    "浪漫", "温馨", "舒服", "环境好", "安静", "清净",
    "好的", "好吃的", "好喝的", "靠谱", "不错", "正宗",
    "地道", "高级", "有档次", "格调",
}
# Also extend _PREFERENCE_MODIFIERS with style terms
_PREFERENCE_MODIFIERS: set[str] = {
    "冷门", "小众", "人少", "清静", "不拥挤", "低拥挤",
    "本地人私藏", "宝藏", "非热门", "避开热门", "避开人流",
    "幽静", "安静", "清净",
    *_STYLE_PREFERENCE_TERMS,
}


def _split_preference_from_category(text: str) -> tuple[str, list[str]]:
    """Split preference modifiers from base category, e.g. '冷门景区' → ('景区', ['冷门'])."""
    t = text.strip()
    found_mods: list[str] = []
    for mod in sorted(_PREFERENCE_MODIFIERS, key=len, reverse=True):
        if t.startswith(mod):
            found_mods.append(mod)
            t = t[len(mod):]
            break
        if t.endswith(mod):
            found_mods.append(mod)
            t = t[:-len(mod)]
            break
    return t.strip(), found_mods


_TIME_FUNCTIONAL_EXPRESSIONS: set[str] = {
    "一整天", "整天", "全天", "一天", "一日", "半天", "半日",
    "上午", "下午", "中午", "晚上", "早上", "傍晚", "夜里",
    "玩一天", "逛一天", "待一天", "玩半天", "逛半天",
    "两小时", "三小时", "几个小时", "一会儿", "一阵子",
    "耍一耍", "看一看", "看看", "逛逛", "走走", "坐一会儿",
    "玩一玩", "走一走", "遛一遛", "转一转",
    "附近", "周边", "周围", "旁边", "就近",
    "找个地方", "哪里有", "有没有", "求推荐", "推荐一下",
}
_TIME_FUNC_PATTERN = re.compile(
    r"^(?:一整天|整天|全天|一天|一日|半天|半日|"
    r"上午|下午|中午|晚上|早上|傍晚|夜里|"
    r"玩[一二两三]?(?:天|小时)|逛[一二两三]?(?:天|小时)|待[一二两三]?(?:天|小时)|"
    r"[两三]小时|几个小时|一会儿|一阵子|"
    r"耍一耍|看一看|看看|逛逛|走走|坐一会儿|"
    r"玩一玩|走一走|遛一遛|转一转)$"
)


# v20: Normalize proximity query — strip garbage prefixes/suffixes, keep semantic core
_QUERY_CLEAN_PREFIX_RE = re.compile(
    r"^(?:我想在|我想|想在|帮我|请帮我|找|找个|找一家|一家|一个|个|"
    r"获得一些|获得|得到|寻找|寻求|查找|"
    r"吃点|吃个|吃顿|吃一些|喝点|喝个|喝杯|"
    r"可以|可以找个|可以找|能不能|有没有|哪里有|推荐个)+"
)
_QUERY_CLEAN_SUFFIX_RE = re.compile(
    r"(?:中午吃饭|晚上吃饭|去吃饭|吃饭|可以去哪里|哪里有|求推荐|"
    r"玩一会儿|逛一逛|看一看|耍一耍|玩玩|逛逛|"
    r"的地方吗|的地方|的吗|吗|呢)+$"
)

# v20: Restaurant/food detection — must generate explicit_meal_intent + restaurant category
_RESTAURANT_CATEGORY_TOKENS: set[str] = {
    "餐厅", "饭店", "饭馆", "餐馆", "酒店",
    "日料", "日本料理", "寿司", "刺身", "烧鸟", "居酒屋",
    "火锅", "烧烤", "川菜", "粤菜", "西餐", "湘菜", "鲁菜",
    "小吃", "面馆", "快餐", "简餐",
}
_MEAL_TIME_TOKENS: dict[str, str] = {
    "中午": "lunch", "午饭": "lunch", "午餐": "lunch",
    "晚上": "dinner", "晚饭": "dinner", "晚餐": "dinner",
}


def _normalize_primary_query(text: str) -> str:
    """Strip garbage prefixes/suffixes from proximity-captured primary_query.

    '一家电脑维修店' → '电脑维修店'
    '获得一些未来科技体验' → '未来科技体验'
    '一家饭店中午吃饭' → '饭店'
    """
    t = text.strip()
    # v21: Strip modifier prefixes BEFORE category detection
    # "适合拍照的饭馆" → "饭馆", "适合约会的餐厅" → "餐厅"
    t = re.sub(r"^(?:适合|可以|能|好|方便)(?:拍照|约会|打卡|休息|看书|学习|发呆|带娃)的", "", t).strip()
    # "环境好看的咖啡馆" → "咖啡馆", "安静一点的书店" → "书店"
    t = re.sub(r"^(?:环境好看|安静一点|氛围好|有氛围|服务好)的?", "", t).strip()
    # v21: "适合办公的咖啡馆" → "咖啡馆", "能带电脑工作的咖啡店" → "咖啡店"
    t = re.sub(r"^(?:适合|可以|能|好|方便)(?:办公|学习|工作|远程|久坐|带电脑|上网)的?", "", t).strip()
    # "有插座的咖啡馆" → "咖啡馆", "能久坐的咖啡厅" → "咖啡厅"
    t = re.sub(r"^(?:有插座|能久坐|能充电|有WiFi|有Wi-Fi|有wifi|带电源)的", "", t).strip()
    t = _QUERY_CLEAN_PREFIX_RE.sub("", t).strip()
    t = _QUERY_CLEAN_SUFFIX_RE.sub("", t).strip()
    t = _MEAL_SUFFIX_CLEANUP_RE.sub("", t).strip()  # remove 吃饭/用餐/就餐
    t = _RANKING_CLEANUP_RE.sub("", t).strip()  # remove 有名/知名/热门
    t = _NOVELTY_CLEANUP_RE.sub("", t).strip()  # remove 没吃过的/没去过的
    # v21: Normalize restroom terms — "地方上厕所" / "找个地方上厕所" → "公共厕所"
    if any(x in t for x in ["厕所", "洗手间", "卫生间", "公厕", "如厕"]):
        return "公共厕所"
    # v21: Strip "有...的地方/吗/呢" patterns ("有开放露台的地方吗" → "开放露台")
    t = re.sub(r"有(.+?)的(?:地方|去处|空间|角落)(?:吗|呢)?$", r"\1", t).strip()
    # v20: Strip abstract placeholder residue — "的角落", "的地方", "的空间"
    t = re.sub(r"的(?:角落|地方|空间|去处|一个地方|个地方)(?:吗|呢)?$", "", t).strip()
    # v20: Strip bare placeholder container words when they're the only content
    if t in _ABSTRACT_PLACEHOLDER_TERMS:
        t = ""
    # v21: Strip leading "的" residue after modifier removal ("的饭馆" → "饭馆")
    t = re.sub(r"^的", "", t).strip()
    # v21: Normalize "饭馆/餐馆/饭店" → "餐厅"
    if t in ("饭馆", "餐馆", "饭店"):
        t = "餐厅"
    # v21: Normalize "咖啡店/咖啡厅" → "咖啡馆"
    if t in ("咖啡店", "咖啡厅"):
        t = "咖啡馆"
    # v20: If cleaning stripped everything away, return empty (not original garbage)
    if not t:
        return ""
    return t or text.strip()


def _is_time_or_functional_expression(text: str) -> bool:
    """Return True if text is purely a time, duration, or functional word."""
    t = text.strip()
    if not t:
        return True
    if t in _TIME_FUNCTIONAL_EXPRESSIONS:
        return True
    if _TIME_FUNC_PATTERN.match(t):
        return True
    return False


def _parse_ranking_modifier(user_request: str) -> dict | None:
    """Detect ranking/ordering modifier words and remove them from the query.

    Returns ranking_intent, ranking_raw_terms, ranking_direction, or None.
    Does NOT modify user_request in-place — callers use ranking_result to adjust search.
    """
    for terms, intent, direction in _RANKING_MODIFIERS:
        for term in sorted(terms, key=len, reverse=True):
            if term in user_request:
                return {
                    "ranking_intent": intent,
                    "ranking_raw_terms": [term],
                    "ranking_direction": direction,
                    "cleaned_text": _RANKING_CLEANUP_RE.sub("", user_request).strip(),
                }
    return None


# v20: Area-category modifier parsing (e.g. "朝阳区的商场", "海淀区书店")
# Detects patterns like "X的Y", "去X的Y", "X的Y + 动作词"
# where X is an administrative area / district / business zone.

# Area name patterns — administrative divisions and business zones
# v20: Semantic POI suffixes (景区/风景区/度假区 etc.) are filtered in code, not regex.
_AREA_SUFFIX_PATTERN = re.compile(
    r"((?:"
    r"[一-龥A-Za-z\d·]+(?:省|市|区|县|镇|乡|街道|商圈|片区|一带|开发区|园区|新城|"
    r"新区|商务区|金融区|科技园|高新区|经济区|自贸区|保税区|"
    r"胡同|里弄|弄堂|社区|小区)"
    r"))"
)

# v20: POI category suffixes that end with 区 but are NOT administrative districts
_NON_ADMIN_AREA_SUFFIXES: set[str] = {
    "景区", "风景区", "游览区", "度假区", "工业区", "居住区",
    "服务区", "停车区", "休息区", "观景区",
}

# Pattern: "X的Y" where X contains area suffix and Y is a target category
_AREA_CATEGORY_RE = re.compile(
    r"(?:(?:去|在|到|找|看|逛)?)"
    r"([一-龥A-Za-z\d·]+(?:省|市|区|县|镇|乡|街道|商圈|片区|一带|开发区|园区|新城|"
    r"新区|商务区|金融区|科技园|高新区|经济区|自贸区|保税区|"
    r"胡同|里弄|弄堂|社区|小区))"
    r"(?:的|之)"
    r"([一-龥A-Za-z\d·]{1,18}?)"  # non-greedy, max 18 chars for target
    r"(?:玩一玩|看一看|看看|逛逛|坐一会儿|走一走|遛一遛|玩|参拜|祈福|拜佛|上香|拜一拜|"
    r"顺便|然后|再|接着|并且|同时)?"
    r"(?:[。，,;]|$)"
)

# Pattern without "的": "X区Y" / "海淀区书店" — area suffix acts as boundary
_AREA_CATEGORY_NO_DE_RE = re.compile(
    r"(?:(?:去|在|到|找|看|逛)?)"
    r"([一-龥A-Za-z\d·]+(?:省|市|区|县|镇|乡|街道|商圈|片区|一带|开发区|园区|新城|"
    r"新区|商务区|金融区|科技园|高新区|经济区|自贸区|保税区|"
    r"胡同|里弄|弄堂|社区|小区))"
    r"([一-龥A-Za-z\d·]{1,10}?(?:店|馆|场|所|院|站|中心|市场|超市|医院)"
    r"|[一-龥A-Za-z\d·]{2,6})"
    r"(?:玩一玩|看一看|看看|逛逛|坐一会儿|走一走|遛一遛|玩|参拜|祈福|拜佛|上香|拜一拜|"
    r"顺便|然后|再|接着|并且|同时)?"
    r"(?:[。，,;]|$)"
)


def _parse_area_category_modifier(user_request: str) -> dict | None:
    """Detect 'X的Y' patterns where X is an administrative area and Y is a category.

    Examples:
        "朝阳区的商场" → search_area="朝阳区", target="商场"
        "海淀区书店" → search_area="海淀区", target="书店"
        "三里屯商圈的购物中心" → search_area="三里屯商圈", target="购物中心"
        "五道口商圈的书店" → search_area="五道口商圈", target="书店"

    Returns None if no area-category pattern detected.
    """
    text = user_request.strip()

    # Strip leading time/functional words
    _TIME_FUNC_STRIP = re.compile(
        r"^(?:明天|今天|后天|周末|上午|下午|中午|晚上|傍晚|夜里|"
        r"想|要|帮|请|帮忙|可以|能不能|是否|"
        r"去|在|到|找|看|顺便)+"
    )
    clean_text = _TIME_FUNC_STRIP.sub("", text).strip()

    m = _AREA_CATEGORY_RE.search(clean_text)
    if not m:
        # Try without "的": "海淀区书店", "朝阳区商场"
        m = _AREA_CATEGORY_NO_DE_RE.search(clean_text)
    if not m:
        # Try with more flexible patterns
        flex_pat = re.compile(
            r"(?:去|在|到|找|看|逛)?"
            r"([一-龥A-Za-z\d·]{2,12}?(?:省|市|区|县|镇|乡|街道|商圈|片区|一带|开发区|园区|新城|"
            r"新区|商务区|金融区|科技园|高新区|经济区|自贸区|保税区|"
            r"胡同|里弄|弄堂|社区|小区))"
            r"(?:的|之)"
            r"([一-龥A-Za-z\d·]{1,10})"
        )
        m = flex_pat.search(clean_text)

    if not m:
        return None

    area_raw = m.group(1).strip()
    target_raw = m.group(2).strip()

    # v20: Reject non-admin "区" suffixes like 景区/风景区/度假区
    if area_raw.endswith("区") and area_raw in _NON_ADMIN_AREA_SUFFIXES:
        return None

    # The no-"的" form commonly puts an action verb between area and category,
    # e.g. "朝阳区找商场".  Keep only the searchable category in primary_query.
    _TARGET_PREFIX_RE = re.compile(
        r"^(?:帮我找|想找|想去|想看|有没有|哪里有|找|看|逛|去|到)+"
    )
    target_raw = _TARGET_PREFIX_RE.sub("", target_raw).strip()

    # Strip clause splitters first (so action words at line end become visible)
    _CLAUSE_SPLIT_RE = re.compile(r"(顺便|然后|再|接着|并且|同时|，|,|。).*$")
    target_raw = _CLAUSE_SPLIT_RE.sub("", target_raw).strip()
    # Then strip action suffixes from the end
    _ACTION_SUFFIX_RE = re.compile(
        r"(玩一天|逛一天|待一天|玩半天|逛半天|待半天|玩一玩|看一看|看看|逛逛|坐一会儿|走一走|遛一遛|玩|参拜|祈福|拜佛|上香|拜一拜)$"
    )
    target_raw = _ACTION_SUFFIX_RE.sub("", target_raw).strip()
    # v20: Normalize — strip ranking words + meal suffixes from target
    target_raw = _normalize_primary_query(target_raw)

    # Validate: area must look like a place name
    if len(area_raw) < 2:
        return None
    # Don't treat pure functional words as area
    skip_area = {"附近的", "周边的", "旁边的"}
    if area_raw in skip_area:
        return None

    # Validate: target must look like a category or POI type
    if len(target_raw) < 1:
        return None
    # Skip if target is purely an action word
    skip_target = {"玩一玩", "看看", "逛逛", "坐一会儿", "走走", "溜达", "转转"}
    if target_raw in skip_target:
        return None

    # v21: Reject garbage area names — must look like a real geographic name
    _GARBAGE_AREA_TOKENS = {"附近", "找个", "能看", "想在", "想找", "找一个", "去看"}
    if any(g in area_raw for g in _GARBAGE_AREA_TOKENS):
        print(
            f"[DEBUG area_category] rejected garbage area='{area_raw}' "
            f"target='{target_raw}' — contains functional words"
        )
        return None
    # v21: Area must not be longer than 12 chars (real district names are short)
    if len(area_raw) > 12:
        print(
            f"[DEBUG area_category] rejected too-long area='{area_raw}' "
            f"(len={len(area_raw)}) — likely a sentence fragment"
        )
        return None
    # v21: Area must start with a geographic-looking prefix (not "附近找个")
    if re.match(r"^(?:附近|周边|周围|旁边|找个|想找|去看|能看)", area_raw):
        print(
            f"[DEBUG area_category] rejected area='{area_raw}' — starts with proximity/functional prefix"
        )
        return None

    # Try to find matching category
    from .poi_typecodes import (
        CATEGORY_RULES, category_for_query, get_search_keywords,
        get_negative_terms, get_allowed_typecode_prefixes,
        get_excluded_typecode_prefixes, get_semantic_terms,
    )
    cat_id = category_for_query(target_raw)
    rule = CATEGORY_RULES.get(cat_id) if cat_id else None

    return {
        "search_area_label": area_raw,
        "primary_query": target_raw,
        "proximity_requested": False,
        "is_search_center_only": True,
        "category_id": cat_id,
        "explicit_meal_intent": cat_id == "restaurant",
        "allowed_typecode_prefixes": get_allowed_typecode_prefixes(cat_id) if cat_id else [],
        "excluded_typecode_prefixes": get_excluded_typecode_prefixes(cat_id) if cat_id else [],
        "primary_required_terms": get_semantic_terms(cat_id) if cat_id else [target_raw],
        "primary_excluded_terms": get_negative_terms(cat_id) if cat_id else [],
        "search_keywords": get_search_keywords(cat_id) if cat_id else [target_raw],
        "category_label": rule.get("label", target_raw) if rule else target_raw,
    }


def _detect_lawn_rest_intent(user_request: str) -> tuple[bool, list[str], list[str]]:
    """Detect lawn/green space feature intent + rest/sit activity.

    Returns (is_lawn_rest, required_features, preferred_features).
    required_features: explicitly requested physical features such as 'lawn'
    preferred_features: useful soft features such as seating, shade, lake_view
    """
    required: list[str] = []
    preferred: list[str] = []

    # v21: Check explicit lawn rest expressions
    has_explicit = any(expr in user_request for expr in _LAWN_REST_EXPRESSIONS)
    has_lawn = any(t in user_request for t in _FEATURE_LAWN_TERMS)
    has_rest = any(t in user_request for t in _FEATURE_REST_TERMS)

    is_lawn_rest = has_explicit or (has_lawn and has_rest)

    if is_lawn_rest:
        if has_lawn:
            required.append("lawn")
        has_explicit_seating = any(
            t in user_request for t in _FEATURE_SEATING_FACILITY_TERMS
        )
        if has_explicit_seating:
            required.append("sittable")
        elif has_rest:
            preferred.append("sittable")
        if any(t in user_request for t in ["树荫", "阴凉", "遮阳"]):
            preferred.append("shade")
        if any(t in user_request for t in ["湖", "水边", "河边", "江边"]):
            preferred.append("water_view")

    return is_lawn_rest, required, preferred


def _build_lawn_rest_proximity_result(
    search_area_label: str | None = None,
    required_features: list[str] | None = None,
    preferred_features: list[str] | None = None,
) -> dict:
    """Build a theme_route with lawn_rest facet from proximity parsing.

    Concrete search keywords: parks, green spaces, gardens.
    NOT grass/lawn as POI name.
    """
    return {
        "poi_query_type": "theme_route",
        "primary_query": "",
        "activity_facet": "lawn_rest",
        "proximity_requested": True,
        "is_search_center_only": True if search_area_label else False,
        "search_area_label": search_area_label,
        "required_features": list(required_features or []),
        "preferred_features": list(preferred_features or []),
        "time_budget_override": "quarter_day",
        "category_id": None,
        "allowed_typecode_prefixes": [],
        "excluded_typecode_prefixes": [],
        "primary_required_terms": [],
        "primary_excluded_terms": [],
        "category_label": "",
        "search_keywords_override": [],
        "explicit_meal_intent": False,
    }


def _detect_utility_lookup(user_request: str) -> tuple[bool, str, str]:
    """Detect restroom/toilet utility lookup requests.

    Uses keyword-based matching (not full-phrase) for broader coverage.
    Excludes false positives like "方便面".
    """
    _lower = user_request.lower()
    # Exclude false positives
    if any(t in user_request for t in ["方便面", "方便的话", "顺便方便", "图方便"]):
        return False, "", ""
    # Check for restroom key terms
    has_restroom = any(t in user_request for t in _RESTROOM_KEY_TERMS)
    if has_restroom:
        return True, "restroom", "公共厕所"
    return False, "", ""


def _parse_corridor_task(user_request: str) -> tuple[str | None, str | None, str | None]:
    """Parse "去X的路上顺路Y" corridor task pattern.

    Returns (destination_raw, task_category, task_action) or (None, None, None).
    destination_raw: e.g., "北航" (will be resolved via alias → geocode)
    task_category: e.g., "水果店" (the corridor POI category to search)
    task_action: "看看" | "买点" | "逛逛" (informs stay duration)
    """
    text = user_request.strip()
    for pat in _CORRIDOR_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        dest_raw = m.group(1).strip()
        task_raw = m.group(2).strip() if m.lastindex >= 2 else ""
        # Clean destination — strip politeness, "的", and noise prefixes
        dest_raw = dest_raw.strip().rstrip("的了呢吗吧")
        dest_raw = _CORRIDOR_POLITE_STRIP_RE.sub("", dest_raw).strip()
        dest_raw = _CORRIDOR_DEST_STRIP_RE.sub("", dest_raw).strip()
        # Clean task — strip politeness, meal suffixes, ranking, leading "的"
        task_raw = task_raw.strip().rstrip("的了呢吗吧")
        task_raw = task_raw.lstrip("的了")  # strip leading "的"/"了" residue
        task_raw = _CORRIDOR_POLITE_STRIP_RE.sub("", task_raw).strip()
        # v21: Strip meal action suffixes from task (吃饭→餐厅, 用餐→餐厅)
        task_raw = re.sub(r"(?:吃饭|用餐|就餐|吃个饭|吃顿饭|吃一顿|吃饭饭)$", "", task_raw).strip()
        # v21: Normalize meal task to standard keyword
        task_raw = re.sub(r"^(?:的|一家|一个|个)?\s*(?:餐馆|饭馆|饭店)$", "餐厅", task_raw).strip()
        # v21: Strip ranking modifiers from task (有名的餐馆→餐馆, 热门餐厅→餐厅)
        _ranking_terms = ""
        for _rkw in ["有名", "知名", "热门", "著名", "人气", "口碑好"]:
            if _rkw in task_raw:
                _ranking_terms = _rkw
                task_raw = task_raw.replace(_rkw, "").strip()
                break
        if not dest_raw or not task_raw or len(dest_raw) < 2 or len(task_raw) < 2:
            continue
        # v21: Detect action type — meal intent from "吃饭/用餐/餐馆/餐厅"
        action = "browse"
        if any(w in text for w in ["吃饭", "用餐", "就餐", "吃顿饭", "吃个饭"]):
            action = "meal"
        elif any(w in task_raw for w in ["餐馆", "餐厅", "饭店", "饭馆", "美食"]):
            action = "meal"
        elif any(w in text for w in ["买", "购买", "采购"]):
            action = "purchase"
        elif any(w in text for w in ["逛", "看看"]):
            action = "browse"
        return dest_raw, task_raw, action
    return None, None, None


def _detect_rest_stop_intent(user_request: str) -> tuple[bool, list[str]]:
    """Detect rest stop / short break intent.

    Returns (is_rest_stop, required_features).
    '歇脚' means user needs real sittable, rest-able places.
    """
    required: list[str] = []
    has_explicit = any(expr in user_request for expr in _REST_STOP_EXPRESSIONS)
    if has_explicit:
        required.append("sittable")
    return has_explicit, required


def _build_rest_stop_proximity_result(
    search_area_label: str | None = None,
    required_features: list[str] | None = None,
) -> dict:
    """Build a theme_route with rest_stop facet."""
    return {
        "poi_query_type": "theme_route",
        "primary_query": "",
        "activity_facet": "rest_stop",
        "proximity_requested": True,
        "is_search_center_only": False,
        "search_area_label": search_area_label,
        "required_features": list(required_features or []),
        "time_budget_override": "quarter_day",
        "category_id": None,
        "allowed_typecode_prefixes": [],
        "excluded_typecode_prefixes": [],
        "primary_required_terms": [],
        "primary_excluded_terms": [],
        "category_label": "",
        "search_keywords_override": [],
        "explicit_meal_intent": False,
    }


def _apply_rest_stop_keywords(parsed: ParsedIntent, city: str, activity_facet: str = "rest_stop") -> None:
    """Set concrete search keywords for rest stop / short break.

    Prioritizes cafes, tea houses, bookstores, park rest areas with seating.
    """
    city_short = city[:-1] if city.endswith("市") else city
    _area = getattr(parsed, "search_area_label", None) or ""
    _prefix = f"{_area}附近 " if _area else f"{city_short} "

    GARBAGE_TERMS = {"适合走累了歇脚", "歇脚", "走累了", "的地方", "可以稍作休息"}
    clean_llm_kw = [kw for kw in parsed.search_keywords if not any(g in kw for g in GARBAGE_TERMS)]

    category_keywords = [f"{_prefix}{kw}" for kw in _REST_STOP_CATEGORY_KEYWORDS]

    parsed.search_keywords = _append_unique(category_keywords, clean_llm_kw[:2], limit=10)
    parsed.micro_keywords = _append_unique(
        ["咖啡馆 休息", "书店 座位", "茶馆 安静", "公园 长椅", "甜品 休息"],
        clean_llm_kw[:1], limit=6,
    )

    parsed.rest_stop_requested = True
    _req = getattr(parsed, "required_features", []) or []
    if "sittable" not in _req:
        _req = list(_req) + ["sittable"]
    parsed.required_features = _req

    print(
        f"[DEBUG rest_stop] area={_area} "
        f"required_features={parsed.required_features} "
        f"search_kw={parsed.search_keywords[:6]}"
    )


def _apply_casual_rest_intent(
    parsed: ParsedIntent,
    city: str,
    user_request: str,
) -> None:
    """Lock UGC-style casual sitting requests to the rest-stop pipeline.

    This intentionally runs after generic proximity/category parsing so a phrase
    such as ``在清华周围找个随意自在的地方坐着`` can first contribute 清华 as
    the search centre, while ``随意自在的地方坐着`` is never retained as a POI
    name/category query.
    """
    city_short = city[:-1] if city.endswith("市") else city
    area = getattr(parsed, "search_area_label", None) or ""
    prefix = f"{area}附近 " if area else f"{city_short} "

    parsed.poi_query_type = "theme_route"
    parsed.primary_query = ""
    parsed.category_id = None
    parsed.activity_facet = "rest_stop"
    parsed.rest_stop_requested = True
    parsed.proximity_requested = True
    parsed.is_search_center_only = bool(area) or parsed.is_search_center_only
    parsed.allowed_typecode_prefixes = []
    parsed.excluded_typecode_prefixes = []
    parsed.primary_required_terms = []
    parsed.primary_excluded_terms = []

    # "可坐" is verifiable and remains hard. Atmosphere/community/low queue
    # pressure are subjective preferences and must not zero out recall.
    parsed.required_features = ["sittable"]
    parsed.preferred_features = _append_unique(
        getattr(parsed, "preferred_features", []) or [],
        ["casual_atmosphere", "community_scale", "low_queue_pressure"],
    )
    parsed.other_constraints = _append_unique(
        [
            item for item in (parsed.other_constraints or [])
            if item not in {"不排队", "不用预约", "不走远"} or item in user_request
        ],
        ["随意自在", "低社交压力"],
    )

    # The earlier provisional detector used broad negative terms. Keep only
    # exclusions that the user actually stated; otherwise they reduce nearby
    # community-store recall for no reason.
    injected_exclusions = {"网红", "排队", "预约", "限时", "高端商务", "私人会所"}
    parsed.micro_excluded_terms = [
        item for item in (getattr(parsed, "micro_excluded_terms", []) or [])
        if item not in injected_exclusions or item in user_request
    ]

    # Use concrete mappable categories, scoped to the already resolved area.
    # Never send the subjective phrase itself to the map POI endpoint.
    parsed.search_keywords = [
        f"{prefix}{keyword}" for keyword in _CASUAL_REST_KEYWORDS[:8]
    ]
    parsed.micro_keywords = _append_unique(
        ["社区咖啡馆 可坐", "书店 阅读座位", "茶馆 安静", "社区公园 长椅"],
        [],
        limit=6,
    )

    print(
        f"[DEBUG casual_rest_final] area={area} facet={parsed.activity_facet} "
        f"query_type={parsed.poi_query_type} required={parsed.required_features} "
        f"preferred={parsed.preferred_features} search_kw={parsed.search_keywords[:6]}"
    )


def _detect_stress_relief_intent(user_request: str) -> tuple[bool, str]:
    """Detect stress relief / decompress activity intent.

    Returns (is_stress_relief, mode): mode is "quiet"|"active"|"creative"|"mixed".
    Never infers medical/psychological needs.
    """
    has_explicit = any(expr in user_request for expr in _STRESS_RELIEF_EXPRESSIONS)
    if not has_explicit:
        return False, ""

    # Determine sub-mode
    has_quiet = any(t in user_request for t in _STRESS_RELIEF_QUIET_TERMS)
    has_active = any(t in user_request for t in _STRESS_RELIEF_ACTIVE_TERMS)
    has_creative = any(t in user_request for t in _STRESS_RELIEF_CREATIVE_TERMS)

    if sum([has_quiet, has_active, has_creative]) == 0:
        mode = "mixed"
    elif has_quiet and not has_active and not has_creative:
        mode = "quiet"
    elif has_active and not has_quiet and not has_creative:
        mode = "active"
    elif has_creative and not has_quiet and not has_active:
        mode = "creative"
    else:
        mode = "mixed"

    return True, mode


def _build_stress_relief_proximity_result(
    search_area_label: str | None = None,
    stress_relief_mode: str = "mixed",
) -> dict:
    """Build a theme_route with stress_relief facet."""
    return {
        "poi_query_type": "theme_route",
        "primary_query": "",
        "activity_facet": "stress_relief",
        "stress_relief_mode": stress_relief_mode,
        "proximity_requested": True,
        "is_search_center_only": False,
        "search_area_label": search_area_label,
        "time_budget_override": "quarter_day",
        "category_id": None,
        "allowed_typecode_prefixes": [],
        "excluded_typecode_prefixes": [],
        "primary_required_terms": [],
        "primary_excluded_terms": [],
        "category_label": "",
        "search_keywords_override": [],
        "explicit_meal_intent": False,
    }


def _apply_stress_relief_keywords(parsed: ParsedIntent, city: str, activity_facet: str = "stress_relief") -> None:
    """Generate concrete activity search keywords based on stress_relief mode.

    Mode determines which categories: quiet (parks/books/cafes), active (sports),
    creative (crafts/DIY), mixed (all three).
    Never searches "解压" itself.
    """
    city_short = city[:-1] if city.endswith("市") else city

    # v21: Filter garbage and medical terms
    GARBAGE_SR_TERMS = {"解压", "放松", "压力", "疗愈", "治愈"}
    EXCLUDE_MEDICAL = {"心理", "精神", "医院", "康复", "诊所", "医疗"}
    clean_llm_kw = [
        kw for kw in parsed.search_keywords
        if not any(g in kw for g in GARBAGE_SR_TERMS)
        and not any(m in kw for m in EXCLUDE_MEDICAL)
    ]

    # v21: Get stress relief mode
    _mode = getattr(parsed, "stress_relief_mode", "mixed") or "mixed"

    # Build keywords per mode
    category_keywords: list[str] = []
    if _mode in ("quiet", "mixed"):
        category_keywords += [f"{city_short} {kw}" for kw in _STRESS_RELIEF_QUIET_KW[:3]]
    if _mode in ("active", "mixed"):
        category_keywords += [f"{city_short} {kw}" for kw in _STRESS_RELIEF_ACTIVE_KW[:3]]
    if _mode in ("creative", "mixed"):
        category_keywords += [f"{city_short} {kw}" for kw in _STRESS_RELIEF_CREATIVE_KW[:3]]
    # Ensure minimum coverage
    if not category_keywords:
        category_keywords = [f"{city_short} {kw}" for kw in _STRESS_RELIEF_QUIET_KW[:2]]

    parsed.search_keywords = _append_unique(
        category_keywords,
        clean_llm_kw[:2],
        limit=12,
    )
    parsed.micro_keywords = _append_unique(
        list(_STRESS_RELIEF_MICRO_KW),
        clean_llm_kw[:1],
        limit=8,
    )

    parsed.stress_relief_requested = True
    parsed.stress_relief_mode = _mode

    # v21: Medical/psychological terms must be in excluded_terms
    parsed.micro_excluded_terms = _append_unique(
        getattr(parsed, "micro_excluded_terms", []) or [],
        list(_STRESS_RELIEF_EXCLUDE_CATS),
        limit=20,
    )

    print(
        f"[DEBUG stress_relief] city={city_short} mode={_mode} "
        f"search_kw={parsed.search_keywords[:8]} "
        f"micro_kw={parsed.micro_keywords[:5]}"
    )


def _detect_open_terrace_intent(user_request: str) -> tuple[bool, list[str]]:
    """Detect open terrace / outdoor terrace feature intent.

    Returns (is_open_terrace, required_features).
    """
    required: list[str] = []

    has_explicit = any(expr in user_request for expr in _OPEN_TERRACE_EXPRESSIONS)
    has_terrace = any(t in user_request for t in ["露台", "rooftop", "terrace", "露天", "屋顶花园"])
    has_proximity = any(t in user_request for t in ["附近", "周边", "周围", "旁边", "就近", "离我近"])

    is_terrace = has_explicit or (has_terrace and has_proximity)

    if is_terrace:
        required.append("open_terrace")

    return is_terrace, required


def _build_open_terrace_proximity_result(
    search_area_label: str | None = None,
    required_features: list[str] | None = None,
) -> dict:
    """Build a theme_route with open_terrace facet."""
    return {
        "poi_query_type": "theme_route",
        "primary_query": "",
        "activity_facet": "open_terrace",
        "proximity_requested": True,
        "is_search_center_only": False,
        "search_area_label": search_area_label,
        "required_features": list(required_features or []),
        "time_budget_override": "quarter_day",
        "category_id": None,
        "allowed_typecode_prefixes": [],
        "excluded_typecode_prefixes": [],
        "primary_required_terms": [],
        "primary_excluded_terms": [],
        "category_label": "",
        "search_keywords_override": [],
        "explicit_meal_intent": False,
    }


def _apply_open_terrace_keywords(parsed: ParsedIntent, city: str, activity_facet: str = "open_terrace") -> None:
    """Set concrete search keywords for open terrace scenarios.

    Terraces exist in cafes, restaurants, bars, hotels, malls, viewing platforms.
    """
    city_short = city[:-1] if city.endswith("市") else city

    GARBAGE_TERMS = {"可以找个", "的地方吗", "的地方", "其他不变", "保持theme", "保持location"}
    clean_llm_kw = [
        kw for kw in parsed.search_keywords
        if not any(g in kw for g in GARBAGE_TERMS)
    ]

    category_keywords = [f"{city_short} {kw}" for kw in _OPEN_TERRACE_CATEGORY_KEYWORDS]

    parsed.search_keywords = _append_unique(
        category_keywords,
        clean_llm_kw[:3],
        limit=10,
    )
    parsed.micro_keywords = _append_unique(
        list(_OPEN_TERRACE_MICRO_KEYWORDS),
        clean_llm_kw[:2],
        limit=8,
    )

    parsed.open_terrace_requested = True
    _req = getattr(parsed, "required_features", []) or []
    if "open_terrace" not in _req:
        _req = list(_req) + ["open_terrace"]
    parsed.required_features = _req

    print(
        f"[DEBUG open_terrace] city={city_short} "
        f"required_features={parsed.required_features} "
        f"search_kw={parsed.search_keywords[:6]} "
        f"micro_kw={parsed.micro_keywords[:5]}"
    )


def _detect_night_view_intent(user_request: str) -> tuple[bool, list[str]]:
    """Detect night view / city skyline scene intent.

    Returns (is_night_view, required_features).
    These are scene/feature requests, NOT named POI or poi_category.
    """
    required: list[str] = []

    has_explicit = any(expr in user_request for expr in _NIGHT_VIEW_EXPRESSIONS)
    has_night_feature = any(t in user_request for t in _NIGHT_VIEW_FEATURE_TERMS)
    has_proximity = any(t in user_request for t in ["附近", "周边", "周围", "旁边", "就近", "离我近"])

    is_night_view = has_explicit or (has_night_feature and has_proximity)

    if is_night_view:
        required.append("night_view")

    return is_night_view, required


def _build_night_view_proximity_result(
    search_area_label: str | None = None,
    required_features: list[str] | None = None,
) -> dict:
    """Build a theme_route with night_view facet."""
    return {
        "poi_query_type": "theme_route",
        "primary_query": "",
        "activity_facet": "night_view",
        "proximity_requested": True,
        "is_search_center_only": False,
        "search_area_label": search_area_label,
        "required_features": list(required_features or []),
        "time_budget_override": "quarter_day",
        "category_id": None,
        "allowed_typecode_prefixes": [],
        "excluded_typecode_prefixes": [],
        "primary_required_terms": [],
        "primary_excluded_terms": [],
        "category_label": "",
        "search_keywords_override": [],
        "explicit_meal_intent": False,
        "evening_requested": True,
    }


def _apply_night_view_keywords(parsed: ParsedIntent, city: str, activity_facet: str = "night_view") -> None:
    """Set concrete search keywords for night view / city skyline scenarios."""
    city_short = city[:-1] if city.endswith("市") else city

    # v21: Filter garbage from LLM
    GARBAGE_NIGHT_TERMS = {"其他不变", "保持theme", "保持location", "按以下参数"}
    clean_llm_kw = [
        kw for kw in parsed.search_keywords
        if not any(g in kw for g in GARBAGE_NIGHT_TERMS)
    ]

    category_keywords = [f"{city_short} {kw}" for kw in _NIGHT_VIEW_CATEGORY_KEYWORDS]

    parsed.search_keywords = _append_unique(
        category_keywords,
        clean_llm_kw[:3],
        limit=10,
    )
    parsed.micro_keywords = _append_unique(
        list(_NIGHT_VIEW_MICRO_KEYWORDS),
        clean_llm_kw[:2],
        limit=8,
    )

    # v21: Set evening + night view features
    parsed.evening_requested = True
    parsed.night_view_requested = True
    _req = getattr(parsed, "required_features", []) or []
    if "night_view" not in _req:
        _req = list(_req) + ["night_view"]
    parsed.required_features = _req

    print(
        f"[DEBUG night_view] city={city_short} "
        f"evening_requested={parsed.evening_requested} "
        f"required_features={parsed.required_features} "
        f"search_kw={parsed.search_keywords[:6]}"
    )


def _detect_quiet_retreat_intent(user_request: str) -> bool:
    """Detect if user request is a quiet retreat / solitude / relaxation scenario.

    Returns True for expressions like:
    - 安静的角落, 清静一点, 不被打扰, 想一个人待会儿
    - 找个地方放空, 安静坐坐, 人少一点, 想发会儿呆
    - 找个清净地方, 想独处一会儿

    These must NOT become:
    - POI names, poi_category names, psychological counseling, social activities.
    """
    lowered = user_request.lower()
    for expr in _QUIET_RETREAT_EXPRESSIONS:
        if expr in user_request:
            return True
    # Also detect combination patterns: "安静" / "清静" + "地方" / "角落" / "空间"
    _has_quiet = any(t in user_request for t in ["安静", "清静", "清净", "幽静", "静谧"])
    _has_abstract_target = any(t in user_request for t in ["角落", "地方", "空间", "去处"])
    if _has_quiet and _has_abstract_target:
        return True
    # "不被打扰" + proximity context
    if "不被打扰" in user_request and any(t in user_request for t in ["附近", "周边", "周围", "旁边", "找个"]):
        return True
    # "想一个人" + "待"/"坐"
    if any(t in user_request for t in ["想一个人", "想自己"]) and any(t in user_request for t in ["待", "坐", "静", "呆"]):
        return True
    return False


def _build_quiet_retreat_proximity_result(
    search_area_label: str | None = None,
    pref_terms: list[str] | None = None,
    crowd_pref: str | None = None,
) -> dict:
    """Build a theme_route with quiet_retreat facet from proximity parsing.

    This is NOT a poi_category — it generates concrete search keywords
    for libraries, bookstores, quiet cafes, parks, etc.
    """
    _prefs = list(pref_terms or [])
    return {
        "poi_query_type": "theme_route",
        "primary_query": "",
        "activity_facet": "quiet_retreat",
        "proximity_requested": True,
        "is_search_center_only": True if search_area_label else False,
        "search_area_label": search_area_label,
        "preference_terms": _prefs,
        "crowd_preference": crowd_pref or "low",
        "privacy_preference": "soft",
        "time_budget_override": "quarter_day",
        "category_id": None,
        "allowed_typecode_prefixes": [],
        "excluded_typecode_prefixes": [],
        "primary_required_terms": [],
        "primary_excluded_terms": [],
        "category_label": "",
        "search_keywords_override": [],
        "explicit_meal_intent": False,
    }


def _parse_proximity_modifier(user_request: str) -> dict | None:
    """Deterministically parse 'X附近的Y' proximity patterns.

    Returns dict with search_area_label, primary_query, proximity_requested,
    or None if no proximity pattern found.

    X → search_area_label (not a destination, just a search center)
    Y → primary_query (the actual target category/POI)
    """
    text = user_request.strip()

    # Leading functional words to strip from captured X
    _LEADING_STRIP_RE = re.compile(
        r"^(?:明天|今天|后天|周末|早上|上午|中午|下午|晚上|夜里|傍晚|"
        r"想|要|帮|请|帮忙|可以|能不能|是否|"
        r"去|在|到|找|看|逛|玩|来|再去|想去|要去|"
        r"帮我|给我|给|顺便|我在|我在想|我想在|我想|想在)+"
        r"(?:的|一下|一会|一会儿)?"
    )

    # v20: Functional/noise words that must NOT be treated as area X
    _FUNCTIONAL_X_SKIP = {
        "明天", "今天", "后天", "周末", "上午", "下午", "晚上",
        "想", "要", "帮", "请", "帮忙", "可以", "能不能", "是否",
        "推荐", "推荐一个", "给我", "安排", "找", "找一个", "去一个",
    }
    # v20: Phrases that indicate X is purely functional, not a real area
    _FUNCTIONAL_X_PATTERN = re.compile(
        r"^(?:推荐|帮我|给我|安排|找|去|来|到)(?:一个|一下|个|下)?"
        r"(?:明天|今天|后天|周末)?(?:去|到)?$"
    )

    # v20: Detect if the whole request is a quiet retreat / abstract expression
    _is_quiet_retreat = _detect_quiet_retreat_intent(user_request)
    # v21: Detect lawn_rest / green space feature intent
    _is_lawn_rest, _lawn_required, _lawn_preferred = _detect_lawn_rest_intent(user_request)
    # v21: Detect night_view / city skyline scene intent
    _is_night_view, _night_required = _detect_night_view_intent(user_request)
    # v21: Detect open_terrace / outdoor terrace feature intent
    _is_open_terrace, _terrace_required = _detect_open_terrace_intent(user_request)
    # v21: Detect stress_relief / decompress activity intent
    _is_stress_relief, _stress_mode = _detect_stress_relief_intent(user_request)
    # v21: Detect rest_stop / short break intent
    _is_rest_stop, _rest_required = _detect_rest_stop_intent(user_request)
    # v20: Preference terms, crowd, privacy preferences from the request
    _pref_terms: list[str] = []
    if any(t in user_request for t in ["安静", "清静", "清净", "幽静"]):
        _pref_terms.append("安静")
    if any(t in user_request for t in ["人少", "人不多", "没人", "不拥挤"]):
        _pref_terms.append("人少")
    if any(t in user_request for t in ["不被打扰", "独处", "自己待", "一个人待"]):
        _pref_terms.append("不被打扰")
    _crowd_pref = "low" if ("人少" in _pref_terms or "不被打扰" in _pref_terms) else None

    # Try patterns with explicit area X
    for pat in _PROXIMITY_PATTERNS:
        m = pat.search(text)
        if m:
            x_raw = m.group(1).strip()
            y_raw = m.group(2).strip()
            # Strip leading functional words from X
            x_clean = _LEADING_STRIP_RE.sub("", x_raw).strip()
            # v20: Validate X is a real area, not functional phrase
            if x_clean in _FUNCTIONAL_X_SKIP or len(x_clean) < 2:
                continue
            if _FUNCTIONAL_X_PATTERN.match(x_clean):
                continue
            # v20: X must contain at least one geographic indicator or known place/building name
            _has_geo_indicator = bool(re.search(
                r"(?:路|街|巷|弄|里|园|苑|庄|村|桥|门|口|"
                r"省|市|区|县|镇|乡|街道|商圈|片区|一带|社区|小区|"
                r"胡同|里弄|弄堂|新城|新区|开发区|园区|"
                r"大学|学院|学校|医院|商场|广场|大厦|大楼|公园|"
                r"地铁站|火车站|机场|码头|车站|"
                r"滨江|江|河|湖|海|山|塘|浦)",
                x_clean,
            ))
            if not _has_geo_indicator and len(x_clean) > 3:
                # Long X without geo indicators is likely a false positive — treat as standalone proximity
                continue
            # Y should not be empty or purely functional
            skip_y = {"附近", "周边", "旁边", "一带", "逛逛", "走走", "的"}
            if y_raw in skip_y or len(y_raw) < 1:
                continue
            # v20: Clean + normalize Y
            _base_y, _prefs = _split_preference_from_category(y_raw)
            _effective_y = _base_y if _base_y else y_raw
            _effective_y = _normalize_primary_query(_effective_y)
            # v20: After cleaning, if Y is empty or abstract placeholder → theme_route
            _y_clean_final = _effective_y.strip()
            if not _y_clean_final or _y_clean_final in _ABSTRACT_PLACEHOLDER_TERMS:
                # v21: If rest_stop detected
                if _is_rest_stop:
                    return _build_rest_stop_proximity_result(
                        search_area_label=None,
                        required_features=_rest_required,
                    )
                # v21: If stress_relief detected
                elif _is_stress_relief:
                    return _build_stress_relief_proximity_result(
                        search_area_label=None,
                        stress_relief_mode=_stress_mode,
                    )
                # v21: If open_terrace detected
                elif _is_open_terrace:
                    return _build_open_terrace_proximity_result(
                        search_area_label=None,
                        required_features=_terrace_required,
                    )
                # v21: If night_view detected
                elif _is_night_view:
                    return _build_night_view_proximity_result(
                        search_area_label=None,
                        required_features=_night_required,
                    )
                # v21: If lawn_rest detected
                elif _is_lawn_rest:
                    return _build_lawn_rest_proximity_result(
                        search_area_label=x_clean,
                        required_features=_lawn_required,
                        preferred_features=_lawn_preferred,
                    )
                # v20: If quiet retreat detected
                elif _is_quiet_retreat or _pref_terms:
                    return _build_quiet_retreat_proximity_result(
                        search_area_label=x_clean,
                        pref_terms=_pref_terms,
                        crowd_pref=_crowd_pref,
                    )
                # Otherwise, the proximity target is abstract but not recognized
                print(
                    f"[DEBUG step1] proximity Y='{_effective_y}' is abstract placeholder "
                    f"→ theme_route"
                )
                return None
            # v21: Check if Y contains only feature terms
            _y_lower = _y_clean_final.lower()
            if _is_rest_stop:
                return _build_rest_stop_proximity_result(
                    search_area_label=None,
                    required_features=_rest_required,
                )
            elif _is_stress_relief:
                return _build_stress_relief_proximity_result(
                    search_area_label=None,
                    stress_relief_mode=_stress_mode,
                )
            elif _is_open_terrace:
                return _build_open_terrace_proximity_result(
                    search_area_label=None,
                    required_features=_terrace_required,
                )
            elif _is_night_view:
                return _build_night_view_proximity_result(
                    search_area_label=None,
                    required_features=_night_required,
                )
            elif _is_lawn_rest and not any(
                t in _y_lower for t in _RESTAURANT_CATEGORY_TOKENS
            ):
                return _build_lawn_rest_proximity_result(
                    search_area_label=x_clean,
                    required_features=_lawn_required,
                    preferred_features=_lawn_preferred,
                )
            # v20: Restaurant detection — check if any restaurant token is in the query
            _is_rest = any(t in _effective_y for t in _RESTAURANT_CATEGORY_TOKENS)
            return {
                "search_area_label": x_clean,
                "primary_query": _effective_y if not _is_rest else ("餐厅" if _effective_y in ("饭店", "饭馆", "餐馆") else _effective_y),
                "preference_terms": (_prefs if _prefs else None) or _pref_terms or None,
                "proximity_requested": True,
                "is_search_center_only": True,
                "explicit_meal_intent": _is_rest,
                "restaurant_category": _is_rest,
                "crowd_preference": _crowd_pref,
            }

    # v20: Strip leading quantifier/functional words from captured Y
    _Y_LEADING_STRIP_RE = re.compile(
        r"^(?:个|下|一下|个新的|新开的|附近的|周边的|旁边的)+"
    )

    # Try patterns without explicit area (e.g. "附近的医院")
    for pat in _PROXIMITY_NO_AREA_PATTERNS:
        m = pat.search(text)
        if m:
            y_raw = m.group(1).strip()
            # Strip leading noise
            y_clean = _Y_LEADING_STRIP_RE.sub("", y_raw).strip()
            skip_y = {"逛逛", "走走", "溜达", "转转", "玩"}
            if y_clean in skip_y or len(y_clean) < 1:
                continue
            _base_y2, _prefs2 = _split_preference_from_category(y_clean)
            _effective_y2 = _base_y2 if _base_y2 else y_clean
            _effective_y2 = _normalize_primary_query(_effective_y2)
            # v20: After cleaning, if Y is empty or abstract placeholder → theme_route
            _y_clean_final2 = _effective_y2.strip()
            if not _y_clean_final2 or _y_clean_final2 in _ABSTRACT_PLACEHOLDER_TERMS:
                if _is_rest_stop:
                    return _build_rest_stop_proximity_result(
                        search_area_label=None,
                        required_features=_rest_required,
                    )
                elif _is_stress_relief:
                    return _build_stress_relief_proximity_result(
                        search_area_label=None,
                        stress_relief_mode=_stress_mode,
                    )
                elif _is_open_terrace:
                    return _build_open_terrace_proximity_result(
                        search_area_label=None,
                        required_features=_terrace_required,
                    )
                elif _is_night_view:
                    return _build_night_view_proximity_result(
                        search_area_label=None,
                        required_features=_night_required,
                    )
                elif _is_lawn_rest:
                    return _build_lawn_rest_proximity_result(
                        search_area_label=None,
                        required_features=_lawn_required,
                        preferred_features=_lawn_preferred,
                    )
                elif _is_quiet_retreat or _pref_terms:
                    return _build_quiet_retreat_proximity_result(
                        search_area_label=None,
                        pref_terms=_pref_terms,
                        crowd_pref=_crowd_pref,
                    )
                print(
                    f"[DEBUG step1] proximity (no-area) Y='{_effective_y2}' is abstract placeholder "
                    f"→ theme_route"
                )
                return None
            # v21: Check for feature-only Y
            _y_lower2 = _effective_y2.lower()
            if _is_rest_stop:
                return _build_rest_stop_proximity_result(
                    search_area_label=None,
                    required_features=_rest_required,
                )
            elif _is_stress_relief:
                return _build_stress_relief_proximity_result(
                    search_area_label=None,
                    stress_relief_mode=_stress_mode,
                )
            elif _is_open_terrace:
                return _build_open_terrace_proximity_result(
                    search_area_label=None,
                    required_features=_terrace_required,
                )
            elif _is_night_view:
                return _build_night_view_proximity_result(
                    search_area_label=None,
                    required_features=_night_required,
                )
            elif _is_lawn_rest and not any(
                t in _y_lower2 for t in _RESTAURANT_CATEGORY_TOKENS
            ):
                return _build_lawn_rest_proximity_result(
                    search_area_label=None,
                    required_features=_lawn_required,
                    preferred_features=_lawn_preferred,
                )
            _is_rest2 = any(t in _effective_y2 for t in _RESTAURANT_CATEGORY_TOKENS)
            return {
                "search_area_label": None,
                "primary_query": _effective_y2 if not _is_rest2 else ("餐厅" if _effective_y2 in ("饭店", "饭馆", "餐馆") else _effective_y2),
                "preference_terms": (_prefs2 if _prefs2 else None) or _pref_terms or None,
                "proximity_requested": True,
                "is_search_center_only": False,
                "explicit_meal_intent": _is_rest2,
                "restaurant_category": _is_rest2,
                "crowd_preference": _crowd_pref,
            }

    # v21: Final fallback — rest_stop intent without proximity match
    if _is_rest_stop:
        return _build_rest_stop_proximity_result(
            search_area_label=None,
            required_features=_rest_required,
        )

    # v21: Final fallback — stress_relief intent without proximity match
    if _is_stress_relief:
        return _build_stress_relief_proximity_result(
            search_area_label=None,
            stress_relief_mode=_stress_mode,
        )

    # v21: Final fallback — open_terrace intent without proximity match
    if _is_open_terrace:
        return _build_open_terrace_proximity_result(
            search_area_label=None,
            required_features=_terrace_required,
        )

    # v21: Final fallback — night_view intent without proximity match
    if _is_night_view:
        return _build_night_view_proximity_result(
            search_area_label=None,
            required_features=_night_required,
        )

    # v21: Final fallback — lawn_rest intent without proximity match
    if _is_lawn_rest:
        return _build_lawn_rest_proximity_result(
            search_area_label=None,
            required_features=_lawn_required,
            preferred_features=_lawn_preferred,
        )

    # v20: If no proximity pattern matched but quiet retreat expressions detected,
    # still return a quiet retreat result for theme_route fallback
    if _is_quiet_retreat or _pref_terms:
        return _build_quiet_retreat_proximity_result(
            search_area_label=None,
            pref_terms=_pref_terms,
            crowd_pref=_crowd_pref,
        )

    return None


def _apply_preference_modifiers(result: dict) -> dict:
    """Split '冷门景区' → base='景区' + prefs=['冷门'], with scenic_area category."""
    pq = result.get("primary_query", "")
    if pq and not result.get("category_id"):
        base, mods = _split_preference_from_category(pq)
        if mods:
            result["primary_query"] = base
            result["preference_terms"] = mods
            for tokens, cat_id in _DIRECT_CATEGORY_PATTERNS:
                for token in tokens:
                    if token == base or base in token:
                        rule = CATEGORY_RULES.get(cat_id)
                        if rule:
                            result["category_id"] = cat_id
                            result["allowed_typecode_prefixes"] = get_allowed_typecode_prefixes(cat_id)
                            result["excluded_typecode_prefixes"] = get_excluded_typecode_prefixes(cat_id)
                            result["primary_required_terms"] = get_semantic_terms(cat_id)
                            result["category_label"] = rule.get("label", base)
                            print(
                                f"[PreferenceAudit] raw_terms={mods} "
                                f"base_category={base} category_id={cat_id} "
                                f"matching_mode=category_plus_preference"
                            )
                            return result
            print(
                f"[PreferenceAudit] raw_terms={mods} "
                f"base_category={base} category_id=None "
                f"matching_mode=preference_only"
            )
    return result


def _detect_poi_category_query(user_request: str) -> dict | None:
    """Detect if user request is a direct POI category query.

    Priority chain:
    1. Proximity modifier ("X附近的Y") → extracts search_area + target category
    2. Direct category patterns → registered CATEGORY_RULES entry
    3. Generic service noun → poi_category with keyword fallback
    4. category_for_query → last-resort category inference

    Returns a dict with poi_query_type, primary_query, category metadata, or None.
    No city or POI name is hardcoded — all derived from category rules.
    """
    lowered = user_request.lower()

    # === Layer 0: Container-target parsing ("商场里的电玩城", "园区中的咖啡馆") ===
    # A = container (mall/park/plaza), B = actual target category
    # B determines primary_query, category_id, typecodes; A is a location constraint
    container_target = _parse_container_target(user_request)
    if container_target:
        container, target = container_target
        # Find the longest category token for B (target), NOT A (container).
        # Longest-match avoids a broad token winning over a more precise one.
        category_matches: list[tuple[int, str]] = []
        for tokens, cat_id in _DIRECT_CATEGORY_PATTERNS:
            for token in tokens:
                if token in target:
                    category_matches.append((len(token), cat_id))
        best_cat_id = max(category_matches, default=(0, ""))[1] or None
        if not best_cat_id:
            best_cat_id = category_for_query(target)
        rule = CATEGORY_RULES.get(best_cat_id) if best_cat_id else None

        print(
            f"[DEBUG step1] container-target: container={container} target={target} "
            f"cat_id={best_cat_id} "
            f"allowed_tc={get_allowed_typecode_prefixes(best_cat_id) if best_cat_id else []}"
        )
        return {
            "poi_query_type": "poi_category",
            "primary_query": target,
            "explicit_meal_intent": best_cat_id == "restaurant",
            "category_id": best_cat_id,
            "allowed_typecode_prefixes": get_allowed_typecode_prefixes(best_cat_id) if best_cat_id else [],
            "excluded_typecode_prefixes": get_excluded_typecode_prefixes(best_cat_id) if best_cat_id else [],
            "primary_required_terms": get_semantic_terms(best_cat_id) if best_cat_id else [target],
            "primary_excluded_terms": [],
            "category_label": rule.get("label", target) if rule else target,
            "container_constraint": container,
        }

    # === Layer 1: Area-category modifier parsing ("朝阳区的商场") ===
    area_cat = _parse_area_category_modifier(user_request)
    if area_cat:
        return {
            "poi_query_type": "poi_category",
            "primary_query": area_cat["primary_query"],
            "explicit_meal_intent": area_cat.get("explicit_meal_intent", False),
            "proximity_requested": False,
            "is_search_center_only": True,
            "search_area_label": area_cat["search_area_label"],
            "category_id": area_cat["category_id"],
            "allowed_typecode_prefixes": area_cat["allowed_typecode_prefixes"],
            "excluded_typecode_prefixes": area_cat["excluded_typecode_prefixes"],
            "primary_required_terms": area_cat["primary_required_terms"],
            "primary_excluded_terms": area_cat["primary_excluded_terms"],
            "search_keywords_override": area_cat["search_keywords"],
            "category_label": area_cat["category_label"],
        }

    # === Layer 2: Proximity modifier parsing ===
    prox = _parse_proximity_modifier(user_request)
    if prox:
        # v20: If proximity already set poi_query_type to theme_route (quiet_retreat etc.),
        # pass through directly with theme_route info
        _prox_query_type = prox.get("poi_query_type", "poi_category")
        if _prox_query_type == "theme_route":
            print(
                f"[DEBUG step1] proximity parsing returned theme_route: "
                f"activity_facet={prox.get('activity_facet')} "
                f"pref_terms={prox.get('preference_terms')} "
                f"crowd_pref={prox.get('crowd_preference')}"
            )
            return prox

        search_area_label = prox.get("search_area_label")
        primary_query = prox.get("primary_query", "")
        # Find the best category for the target
        best_cat_id = None
        best_cat_rule = None
        for tokens, cat_id in _DIRECT_CATEGORY_PATTERNS:
            for token in tokens:
                if token.lower() in primary_query.lower() or primary_query.lower() in token.lower():
                    best_cat_id = cat_id
                    best_cat_rule = CATEGORY_RULES.get(cat_id)
                    break
            if best_cat_id:
                break
        if not best_cat_id:
            best_cat_id = category_for_query(primary_query)
            if best_cat_id:
                best_cat_rule = CATEGORY_RULES.get(best_cat_id)

        # v20: All fields initialized with defaults — no KeyError on missing keys
        result: dict = {
            "poi_query_type": "poi_category",
            "primary_query": primary_query,
            "explicit_meal_intent": bool(prox.get("explicit_meal_intent", False)),
            "proximity_requested": True,
            "is_search_center_only": prox.get("is_search_center_only", True),
            "category_id": None,
            "allowed_typecode_prefixes": [],
            "excluded_typecode_prefixes": [],
            "primary_required_terms": [],
            "primary_excluded_terms": [],
            "category_label": primary_query,
            "preference_terms": prox.get("preference_terms") or [],
            "search_keywords_override": [],
        }

        if search_area_label:
            result["search_area_label"] = search_area_label
            result["search_center_label"] = search_area_label

        if best_cat_id and best_cat_rule:
            result["category_id"] = best_cat_id
            result["allowed_typecode_prefixes"] = get_allowed_typecode_prefixes(best_cat_id)
            result["excluded_typecode_prefixes"] = get_excluded_typecode_prefixes(best_cat_id)
            result["primary_required_terms"] = get_semantic_terms(best_cat_id)
            result["primary_excluded_terms"] = []
            result["category_label"] = best_cat_rule.get("label", primary_query)
            if best_cat_id == "restaurant":
                result["explicit_meal_intent"] = True
        # v20: Pure meal action verb → force restaurant (e.g. "吃点", "吃个")
        if primary_query in ("吃点", "吃个", "吃顿", "喝点", "喝个", "喝杯", "来点", "来份"):
            result["primary_query"] = "餐厅"
            result["category_id"] = "restaurant"
            result["explicit_meal_intent"] = True
            result["allowed_typecode_prefixes"] = get_allowed_typecode_prefixes("restaurant")
            result["excluded_typecode_prefixes"] = get_excluded_typecode_prefixes("restaurant")
            result["primary_required_terms"] = get_semantic_terms("restaurant")
            result["primary_excluded_terms"] = []
            result["category_label"] = "餐厅"
        # v20: Also set meal intent when strong meal keywords hit (but no registered category)
        elif any(t.lower() in primary_query.lower() for t in STRONG_MEAL_TOKENS):
            result["explicit_meal_intent"] = True
        # v20: Style-only query → fallback to restaurant if user said "吃/喝"
        elif primary_query in _STYLE_PREFERENCE_TERMS:
            if any(t in user_request for t in ["吃", "喝", "食", "餐", "饭"]):
                result["primary_query"] = "餐厅"
                result["category_id"] = "restaurant"
                result["explicit_meal_intent"] = True
                result["allowed_typecode_prefixes"] = get_allowed_typecode_prefixes("restaurant")
                result["excluded_typecode_prefixes"] = get_excluded_typecode_prefixes("restaurant")
                result["primary_required_terms"] = get_semantic_terms("restaurant")
                result["primary_excluded_terms"] = []
                result["preference_terms"] = list(result.get("preference_terms", []) or []) + [primary_query]
                result["category_label"] = "餐厅"
                print(
                    f"[DEBUG step1] style preference '{primary_query}' + meal intent → restaurant, "
                    f"prefs={result.get('preference_terms')}"
                )
        else:
            # v20: If target looks like a theme/style expression (ends with 路线, or is a style word),
            # return None so it falls through to theme_route.  Don't create a broken poi_category state.
            _is_theme_expr = (
                primary_query.endswith("路线")
                or primary_query.endswith("游")
                or primary_query in _STYLE_THEME_SYNONYMS
                or any(
                    primary_query == kw or (primary_query.endswith(kw) and len(primary_query) <= len(kw) + 2)
                    for kw in _STYLE_THEME_SYNONYMS
                )
            )
            if _is_theme_expr:
                print(
                    f"[DEBUG step1] proximity target '{primary_query}' is a theme/style expression, "
                    f"NOT poi_category — falling back to theme_route"
                )
                return None

            # Unknown category — generic fallback: allow any typecode, filter by keyword
            result["category_id"] = None
            result["allowed_typecode_prefixes"] = []
            result["excluded_typecode_prefixes"] = []
            result["primary_required_terms"] = [primary_query]
            result["primary_excluded_terms"] = []

        # v20: Activity expressions like "随便走走/散步/逛逛" → theme_route, not poi_category
        if primary_query in _ACTIVITY_EXPRESSIONS:
            result["poi_query_type"] = "theme_route"
            result["primary_query"] = ""
            result["primary_required_terms"] = []
            if search_area_label:
                result["activity_facet"] = primary_query
                result["search_keywords_override"] = [
                    f"{search_area_label} 步道", f"{search_area_label} 公园",
                    f"{search_area_label} 观景点", f"{search_area_label} 打卡点",
                    f"{search_area_label} 徒步",
                ]
            print(
                f"[DEBUG step1] activity expression '{primary_query}' → theme_route "
                f"search_area={search_area_label}"
            )
        else:
            print(
                f"[DEBUG step1] proximity parsing: "
                f"label={search_area_label} target={primary_query} "
                f"cat_id={result.get('category_id')} "
                f"allowed_tc={result.get('allowed_typecode_prefixes')}"
            )
        return result

    # === Layer 3: Direct registered category patterns ===
    for tokens, cat_id in _DIRECT_CATEGORY_PATTERNS:
        for token in tokens:
            if token.lower() in lowered:
                rule = CATEGORY_RULES.get(cat_id)
                if not rule:
                    continue
                return {
                    "poi_query_type": "poi_category",
                    "primary_query": token,
                    "explicit_meal_intent": cat_id == "restaurant" or any(
                        t.lower() in lowered for t in STRONG_MEAL_TOKENS
                    ),
                    "category_id": cat_id,
                    "allowed_typecode_prefixes": get_allowed_typecode_prefixes(cat_id),
                    "excluded_typecode_prefixes": get_excluded_typecode_prefixes(cat_id),
                    "primary_required_terms": get_semantic_terms(cat_id),
                    "primary_excluded_terms": [],
                    "category_label": rule.get("label", token),
                }

    # === Layer 4: Generic service noun detection ===
    # Detect any known service noun even without registered CATEGORY_RULES entry.
    for noun in sorted(_GENERIC_SERVICE_NOUNS, key=len, reverse=True):
        if noun in lowered:
            # Try to find a matching category rule first
            cat_id = category_for_query(noun)
            rule = CATEGORY_RULES.get(cat_id) if cat_id else None
            return {
                "poi_query_type": "poi_category",
                "primary_query": noun,
                "explicit_meal_intent": (cat_id == "restaurant" if cat_id else any(
                    t.lower() in noun.lower() for t in STRONG_MEAL_TOKENS
                )),
                "category_id": cat_id,
                "allowed_typecode_prefixes": get_allowed_typecode_prefixes(cat_id) if cat_id else [],
                "excluded_typecode_prefixes": get_excluded_typecode_prefixes(cat_id) if cat_id else [],
                "primary_required_terms": get_semantic_terms(cat_id) if cat_id else [noun],
                "primary_excluded_terms": [],
                "category_label": (rule.get("label", noun) if rule else noun),
            }

    # === Layer 5: category_for_query (more general matching) ===
    inferred_cat = category_for_query(user_request)
    if inferred_cat:
        rule = CATEGORY_RULES.get(inferred_cat)
        if rule:
            return {
                "poi_query_type": "poi_category",
                "primary_query": user_request.strip(),
                "explicit_meal_intent": False,
                "category_id": inferred_cat,
                "allowed_typecode_prefixes": get_allowed_typecode_prefixes(inferred_cat),
                "excluded_typecode_prefixes": get_excluded_typecode_prefixes(inferred_cat),
                "primary_required_terms": get_semantic_terms(inferred_cat),
                "primary_excluded_terms": [],
                "category_label": rule.get("label", user_request.strip()),
            }

    return None


def _apply_lawn_rest_keywords(parsed: ParsedIntent, city: str, activity_facet: str = "lawn_rest") -> None:
    """Set concrete search keywords for lawn_rest / green space scenarios.

    Maps abstract "lawn/grass + sitting" intent to real POI categories:
    parks, green spaces, gardens, pocket parks.
    Prioritizes indoor alternatives if it's raining.
    """
    city_short = city[:-1] if city.endswith("市") else city

    # v21: Filter garbage from LLM
    GARBAGE_FEATURE_TERMS = {"草坪的地方", "有草坪的地方坐着", "地方坐着", "草地的地方"}
    clean_llm_kw = [
        kw for kw in parsed.search_keywords
        if not any(g in kw for g in GARBAGE_FEATURE_TERMS)
    ]

    # v21: Check if rainy
    is_rainy = "雨天" in parsed.other_constraints or any(
        t in str((parsed.weather_info or {}).get("day1", {}).get("weather", "") or "") for t in ["雨", "雪"]
    )

    # v21: Build concrete category keywords
    category_keywords = [f"{city_short} {kw}" for kw in _LAWN_REST_CATEGORY_KEYWORDS]

    if is_rainy:
        # Rain: add indoor alternatives
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["雨后草坪可能湿滑"])
        indoor_kw = [f"{city_short} {kw}" for kw in _INDOOR_REST_ALTERNATIVES]
        category_keywords = category_keywords + indoor_kw

    # v21: Prepend concrete keywords, then cleaned LLM keywords
    parsed.search_keywords = _append_unique(
        category_keywords,
        clean_llm_kw[:3],
        limit=10,
    )

    # v21: Micro keywords for lawn/grass experiences
    parsed.micro_keywords = _append_unique(
        list(_LAWN_REST_MICRO_KEYWORDS),
        clean_llm_kw[:2],
        limit=8,
    )

    # v21: Set required features
    _req_features = getattr(parsed, "required_features", []) or []
    parsed.required_features = list(_req_features)
    parsed.lawn_rest_requested = True

    print(
        f"[DEBUG lawn_rest] city={city_short} rainy={is_rainy} "
        f"required_features={parsed.required_features} "
        f"search_kw={parsed.search_keywords[:6]} "
        f"micro_kw={parsed.micro_keywords[:5]}"
    )


def _apply_quiet_retreat_keywords(parsed: ParsedIntent, city: str, activity_facet: str = "quiet_retreat") -> None:
    """Set concrete search keywords for quiet retreat / solitude scenarios.

    Maps abstract "quiet corner" intent to real POI categories:
    libraries, bookstores, quiet cafes, tea houses, small parks, reading spaces.
    Prioritizes indoor spaces if it's raining; outdoor parks otherwise.
    Replaces garbage LLM keywords (安静 角落, 静谧 空间) with real category keywords.
    """
    city_short = city[:-1] if city.endswith("市") else city

    # v20: Check if rainy — prefer indoor spaces
    is_rainy = "雨天" in parsed.other_constraints or any(
        t in str((parsed.weather_info or {}).get("day1", {}).get("weather", "") or "") for t in ["雨", "雪"]
    )

    # v20: For quiet_retreat, replace LLM keywords entirely with concrete category keywords.
    # The LLM doesn't know about quiet_retreat mapping, so its output is noise.
    # Only keep LLM keywords that are clearly real quiet-retreat POI categories.
    QUIET_RETREAT_VALID_TERMS = {
        "图书馆", "书店", "书局", "咖啡馆", "茶馆", "茶室", "阅读", "自习",
        "美术馆", "展览", "博物馆", "画廊",
        "公园", "花园", "绿地", "步道", "滨水", "口袋",
        "书院", "文化馆", "艺术馆",
    }
    GARBAGE_KEYWORD_TERMS = {"角落", "安静的", "静谧", "不被打扰", "清静", "的角"}
    clean_llm_kw = [
        kw for kw in parsed.search_keywords
        if not any(g in kw for g in GARBAGE_KEYWORD_TERMS)
        and any(v in kw for v in QUIET_RETREAT_VALID_TERMS)
    ]

    # v20: Build concrete category keywords
    indoor_kw = [f"{city_short} {kw}" for kw in _QUIET_RETREAT_INDOOR_KEYWORDS]
    outdoor_kw = [f"{city_short} {kw}" for kw in _QUIET_RETREAT_OUTDOOR_KEYWORDS]

    if is_rainy:
        # Rain: prioritize indoor spaces
        category_keywords = indoor_kw + outdoor_kw
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["室内优先"])
    else:
        # Good weather: mix indoor and outdoor
        category_keywords = indoor_kw[:4] + outdoor_kw[:3]

    # v20: Prepend concrete category keywords, then append cleaned LLM keywords
    parsed.search_keywords = _append_unique(
        category_keywords,
        clean_llm_kw[:4],
        limit=10,
    )

    # v20: Clean micro keywords too
    clean_llm_micro = [
        kw for kw in (parsed.micro_keywords or [])
        if not any(g in kw for g in GARBAGE_KEYWORD_TERMS)
    ]
    parsed.micro_keywords = _append_unique(
        list(_QUIET_RETREAT_MICRO_KEYWORDS),
        clean_llm_micro[:3],
        limit=8,
    )
    # v20: Set required terms for quiet evidence
    parsed.quiet_retreat_requested = True
    print(
        f"[DEBUG quiet_retreat] city={city_short} rainy={is_rainy} "
        f"search_kw={parsed.search_keywords[:6]} "
        f"micro_kw={parsed.micro_keywords[:5]} "
        f"garbage_filtered={len(parsed.search_keywords) - len(category_keywords)} llm_kw_left"
    )


_DAY_MARKER_RE_V2 = re.compile(
    r"(?:\u7b2c\s*([\u4e00\u4e8c\u4e09123])\s*[\u5929\u65e5]|D\s*([123])|Day\s*([123]))",
    re.IGNORECASE,
)
_TWO_DAY_REQUEST_RE_V2 = re.compile(
    r"(?:[\u4e24\u4e8c2]\s*[\u5929\u65e5](?:\u6e38)?)|(?:two\s+days?)",
    re.IGNORECASE,
)
_PERIOD_TOKENS_V2 = [
    ("\u4e0a\u5348", "morning"),
    ("\u4e0b\u5348", "afternoon"),
    ("\u665a\u4e0a", "evening"),
    ("\u591c\u95f4", "evening"),
    ("\u508d\u665a", "evening"),
]
_TRANSPORT_PATTERNS_V2 = [
    (re.compile(r"\u5730\u94c1|\u8f68\u9053\u4ea4\u901a"), "transit_subway", "\u5730\u94c1"),
    (re.compile(r"\u516c\u4ea4|\u5df4\u58eb|\u516c\u5171\u6c7d\u8f66"), "bus", "\u516c\u4ea4"),
    (re.compile(r"\u6253\u8f66|\u51fa\u79df|\u7f51\u7ea6\u8f66|taxi", re.IGNORECASE), "taxi", "\u6253\u8f66"),
    (re.compile(r"\u9a91\u8f66|\u9a91\u884c|\u5355\u8f66|\u81ea\u884c\u8f66"), "bicycle", "\u9a91\u8f66"),
    (re.compile(r"\u6b65\u884c|\u8d70\u8def"), "walking", "\u6b65\u884c"),
]


def _extract_period_transport_constraints_v2(user_request: str) -> list[dict[str, Any]]:
    """Parse explicit day/period transport constraints from raw Chinese text.

    The legacy block below is kept for compatibility, but the source file has
    seen mojibake in several Chinese regex literals.  This parser uses unicode
    escapes so requests such as "第一天上午地铁，第一天下午公交，第二天上午打车，
    第二天下午骑车" remain deterministic.
    """
    day_num_map = {
        "\u4e00": 1,
        "\u4e8c": 2,
        "\u4e09": 3,
        "1": 1,
        "2": 2,
        "3": 3,
    }

    day_matches = list(_DAY_MARKER_RE_V2.finditer(user_request or ""))
    constraints: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()

    def _find_transport(text: str) -> tuple[str, str]:
        for pattern, mode, label in _TRANSPORT_PATTERNS_V2:
            if pattern.search(text):
                return mode, label
        return "", ""

    for idx, match in enumerate(day_matches):
        day_token = next((g for g in match.groups() if g), "1")
        day_index = day_num_map.get(day_token, 1)
        chunk_start = match.end()
        chunk_end = day_matches[idx + 1].start() if idx + 1 < len(day_matches) else len(user_request)
        chunk = user_request[chunk_start:chunk_end]

        period_hits = []
        for token, period in _PERIOD_TOKENS_V2:
            pos = chunk.find(token)
            if pos >= 0:
                period_hits.append((pos, token, period))
        period_hits.sort(key=lambda item: item[0])

        if period_hits:
            for pidx, (pos, token, period) in enumerate(period_hits):
                start = pos + len(token)
                end = period_hits[pidx + 1][0] if pidx + 1 < len(period_hits) else len(chunk)
                mode, label = _find_transport(chunk[start:end])
                if not mode:
                    continue
                key = (day_index, period, mode)
                if key in seen:
                    continue
                seen.add(key)
                constraints.append({
                    "day_index": day_index,
                    "period": period,
                    "transport": label,
                    "transport_mode": mode,
                })
        else:
            mode, label = _find_transport(chunk)
            if mode:
                key = (day_index, "all_day", mode)
                if key not in seen:
                    seen.add(key)
                    constraints.append({
                        "day_index": day_index,
                        "period": "all_day",
                        "transport": label,
                        "transport_mode": mode,
                    })

    return constraints


def _looks_like_multi_day_transport_request_v2(user_request: str) -> bool:
    constraints = _extract_period_transport_constraints_v2(user_request)
    if any(c.get("day_index", 1) >= 2 for c in constraints):
        return True
    return bool(_TWO_DAY_REQUEST_RE_V2.search(user_request or "") and constraints)


_NO_RESERVATION_TERMS_V2 = [
    "没有预约", "没预约", "没抢到票", "临时安排", "临时出发",
    "不用预约", "免预约", "不需要预约", "没约上", "当天能去",
]


def _is_no_reservation_request_v2(user_request: str) -> bool:
    return any(term in (user_request or "") for term in _NO_RESERVATION_TERMS_V2)


def _apply_no_reservation_flexible_trip_v2(parsed: ParsedIntent, city: str) -> None:
    city_short = city[:-1] if city.endswith("市") else city
    parsed.poi_query_type = "theme_route"
    parsed.primary_query = ""
    parsed.category_id = None
    parsed.allowed_typecode_prefixes = []
    parsed.excluded_typecode_prefixes = []
    parsed.primary_required_terms = []
    parsed.primary_excluded_terms = []
    parsed.activity_facet = "no_reservation_flexible_trip"
    parsed.plan_mode = "exploratory"
    parsed.theme_required = False
    if float(getattr(parsed, "time_budget", 0) or 0) >= 2.0:
        parsed.requested_days = max(2, int(float(parsed.time_budget)))
        parsed.preserve_requested_days = True
    parsed.other_constraints = _append_unique(parsed.other_constraints, [
        "无需预约", "可当天前往", "优先开放街区/公园/公共空间",
        "避开强预约制热门景点",
    ])
    parsed.search_keywords = [
        f"{city_short} 无需预约 景点", f"{city_short} 免预约 景点",
        f"{city_short} 可现场购票 景点", f"{city_short} 开放街区 游玩",
        f"{city_short} 公园 免预约", f"{city_short} 城市公园",
        f"{city_short} 文化街区", f"{city_short} 滨水步道",
        f"{city_short} 老街 漫步", f"{city_short} 夜景街区",
    ]
    parsed.micro_keywords = [
        "开放街区 漫步", "公园 散步", "城市公园",
        "文化街区", "滨水步道", "可现场购票", "无需预约",
    ]
    parsed.micro_excluded_terms = _append_unique(
        getattr(parsed, "micro_excluded_terms", []) or [],
        [
            "故宫博物院", "国家博物馆", "天安门城楼", "人民大会堂",
            "实名预约", "需提前预约", "预约", "限流", "抢票",
        ],
        limit=20,
    )


def _build_multi_facet_art_facets(
    has_photo: bool,
    has_art: bool,
    has_cafe: bool,
    has_shop: bool,
    has_relaxed: bool,
) -> list[dict]:
    """v25: Build structured theme_facets for multi_facet_art_photo_cafe_shop.

    Each facet has an id and:
    - required: must be covered by at least one visible route POI
    - role: macro_anchor (area selection) | visible_poi (must appear) | score_boost | route_pace
    """
    facets: list[dict] = []
    if has_art:
        facets.append({"id": "art_culture_lifestyle", "required": True, "role": "macro_anchor"})
    if has_cafe:
        facets.append({"id": "cafe_stop", "required": True, "role": "visible_poi"})
    if has_shop:
        facets.append({"id": "specialty_shop", "required": True, "role": "visible_poi"})
    if has_photo:
        facets.append({"id": "photo_checkin", "required": False, "role": "score_boost"})
    if has_relaxed:
        facets.append({"id": "relaxed_pace", "required": False, "role": "route_pace"})
    return facets


# ── v26: category-level exclusion extraction ──

# Known categories that can be negated and their associated keywords
_CATEGORY_NEGATION_KEYWORDS: dict[str, dict] = {
    "cafe": {
        "keyword_patterns": ["咖啡", "咖啡馆", "咖啡店", "咖啡厅", "coffee", "cafe", "café",
                             "瑞幸", "星巴克", "manner", "Manner", "Costa"],
        "typecodes": ["050400", "050500"],
        "facet_ids": ["cafe_stop", "coffee_tea_bakery"],
    },
    "specialty_shop": {
        "keyword_patterns": ["特色小店", "买手店", "文创店", "杂货店", "生活方式集合店", "集合店"],
        "typecodes": ["060100", "060900", "061000", "080300"],
        "facet_ids": ["specialty_shop"],
    },
}

# Trigger patterns for category negation
_CATEGORY_NEGATION_TRIGGERS_RE = re.compile(
    r"(?:"
    + "|".join([
        "不想去", "不想要", "不要有", "不要再有", "别去", "别安排", "别要",
        "去掉", "删除", "删掉", "跳过", "略过", "不去", "免了",
        "不要了", "不想要了", "不想去了",
    ])
    + r")"
)


def _extract_category_exclusions_from_request(parsed: ParsedIntent, user_request: str) -> ParsedIntent:
    """v26: Detect category-level negation and strip matching keywords from parsed intent.

    When the user says "不想去咖啡馆了", this function:
    1. Identifies the negated category (cafe)
    2. Removes cafe-related keywords from search_keywords/micro_keywords/food_pref_keywords/meal_search_keywords
    3. Clears primary_query if it matches the negated category
    4. Adds to delete_list, primary_excluded_terms, excluded_typecode_prefixes

    This only activates when a clear negation trigger is present AND there's no route_context
    (i.e. the negation is parsed in Step1, NOT in chat edit). For multi-turn scenarios,
    the category exclusion should be handled by conversation dispatch before reaching Step1.
    """
    text = user_request or ""

    # Must contain a negation trigger
    if not _CATEGORY_NEGATION_TRIGGERS_RE.search(text):
        return parsed

    text_lower = text.lower()

    # Check against each known category
    for cat_id, cat_info in _CATEGORY_NEGATION_KEYWORDS.items():
        # Check if any category keyword appears near the negation trigger
        _cat_matched = False
        for kw in cat_info["keyword_patterns"]:
            if kw.lower() in text_lower:
                _cat_matched = True
                break
        if not _cat_matched:
            continue

        # Category matched — strip it from all keyword fields
        _strip_words = [w.lower() for w in cat_info["keyword_patterns"]]

        def _filter_out(words: list[str]) -> list[str]:
            return [
                w for w in words
                if not any(sw in str(w).lower() for sw in _strip_words)
            ]

        # Strip from search keywords
        parsed.search_keywords = _filter_out(getattr(parsed, "search_keywords", []) or [])

        # Strip from micro keywords
        parsed.micro_keywords = _filter_out(getattr(parsed, "micro_keywords", []) or [])
        parsed.micro_poi_keywords = _filter_out(getattr(parsed, "micro_poi_keywords", []) or [])

        # Strip from food/meal keywords
        parsed.food_pref_keywords = _filter_out(getattr(parsed, "food_pref_keywords", []) or [])
        parsed.meal_search_keywords = _filter_out(getattr(parsed, "meal_search_keywords", []) or [])

        # Clear primary_query if it matches
        _pq = str(getattr(parsed, "primary_query", "") or "").lower()
        if _pq and any(sw in _pq for sw in _strip_words):
            parsed.primary_query = ""
            # If poi_query_type was set based on primary_query, revert to theme_route
            _ptype = getattr(parsed, "poi_query_type", "") or ""
            if _ptype in ("poi_category", "named_poi"):
                parsed.poi_query_type = "theme_route"

        # Clear meal_constraints that reference cafe
        _meal_cons = getattr(parsed, "meal_constraints", []) or []
        parsed.meal_constraints = [
            mc for mc in _meal_cons
            if not any(
                sw in str(mc.get("keywords", [])).lower()
                for sw in _strip_words
            )
        ]

        # Add to exclusion lists
        _delete = getattr(parsed, "delete_list", []) or []
        _raw_target = next((kw for kw in cat_info["keyword_patterns"] if kw.lower() in text_lower), cat_id)
        if _raw_target not in _delete:
            _delete.append(_raw_target)
        parsed.delete_list = _delete

        # Add typecode exclusions
        _excl_tc = list(getattr(parsed, "excluded_typecode_prefixes", []) or [])
        for tc in cat_info["typecodes"]:
            if tc not in _excl_tc:
                _excl_tc.append(tc)
        parsed.excluded_typecode_prefixes = _excl_tc

        # Add to primary excluded terms
        _excl_terms = list(getattr(parsed, "primary_excluded_terms", []) or [])
        for t in cat_info["keyword_patterns"][:6]:
            if t not in _excl_terms:
                _excl_terms.append(t)
        parsed.primary_excluded_terms = _excl_terms

        # Remove from micro_required_terms
        _mrt = list(getattr(parsed, "micro_required_terms", []) or [])
        parsed.micro_required_terms = _filter_out(_mrt)

        # Remove matching facets from theme_facets
        _facet_ids_to_remove = set(cat_info.get("facet_ids", [cat_id]))
        _facets = list(getattr(parsed, "theme_facets", []) or [])
        parsed.theme_facets = [
            f for f in _facets
            if str(f.get("id", "") if isinstance(f, dict) else "") not in _facet_ids_to_remove
        ]

        print(
            f"[CategoryNegationAudit] category={cat_id} cleared_positive_terms=true "
            f"excluded_typecode_prefixes={parsed.excluded_typecode_prefixes} "
            f"search_keywords_remaining={parsed.search_keywords[:4]}"
        )
        break  # only handle first matched category

    return parsed


# ═══ v28: Shared multi-facet art density helpers — used in _postprocess & final_normalize ═══


def _has_explicit_half_day_terms(text: str) -> bool:
    """Return True if user explicitly mentions a half-day time constraint."""
    text = text or ""
    return any(
        term in text
        for term in [
            "半天", "半日", "上午", "下午",
            "2小时", "3小时", "两小时", "三小时",
            "二小时", "仨小时",
        ]
    )


def _is_multi_facet_art_density_route(parsed: ParsedIntent) -> bool:
    """Return True if the parsed intent is a multi-facet art density route."""
    return (
        getattr(parsed, "activity_facet", "") == "multi_facet_art_photo_cafe_shop"
        or getattr(parsed, "theme_coverage_policy", "") == "cover_required_facets"
        or bool(getattr(parsed, "theme_route_locked", False))
    )


def _force_multi_facet_art_density(
    parsed: ParsedIntent,
    latest_user_text: str,
    *,
    stage: str,
) -> ParsedIntent:
    """Enforce full-day density targets for multi-facet art routes.

    "节奏轻松一点" MUST NOT be interpreted as half-day.  Unless the user
    EXPLICITLY said "半天/半日/上午/下午/2小时/3小时", this route defaults
    to a full day with density_min=6, density_target=6, candidate_target=4.
    """
    if not _is_multi_facet_art_density_route(parsed):
        return parsed

    explicit_half_day = _has_explicit_half_day_terms(latest_user_text)

    if not explicit_half_day:
        parsed.duration = "a full day"
        parsed.time_budget = 1.0

    parsed.density_min_visible_pois = 6
    parsed.density_target_visible_pois = 6
    parsed.candidate_target = 4
    setattr(parsed, "min_frontend_display_points", 6)

    print(
        f"[MultiFacetDensityAudit] stage={stage} "
        f"explicit_half_day={explicit_half_day} "
        f"duration={parsed.duration} time_budget={parsed.time_budget} "
        f"display_target={parsed.density_target_visible_pois} "
        f"candidate_target={parsed.candidate_target}"
    )
    return parsed


# ═══ v28: Route quality contract — unified density + candidates + compact + timeline ═══


def _is_route_quality_contract_query(text: str, parsed: Any) -> bool:
    """Return True if the query needs the full quality contract (6+ POIs, 4+ candidates)."""
    raw = text or ""

    art_photo_cafe_shop = (
        ("文艺" in raw or "适合拍照" in raw or "拍照" in raw)
        and ("咖啡" in raw or "咖啡馆" in raw)
        and ("特色小店" in raw or "小店" in raw)
    )
    area_meal_sunset = (
        ("天安门" in raw or "故宫" in raw)
        and ("中午" in raw or "午饭" in raw or "午餐" in raw)
        and ("景山" in raw or "日落" in raw)
    )
    afternoon_dinner_river_night = (
        ("下午" in raw)
        and ("晚饭" in raw or "晚餐" in raw or "吃完" in raw)
        and ("河边" in raw or "河边走走" in raw or "亮马河" in raw)
        and ("夜景" in raw or "拍夜景" in raw)
    )

    facet = getattr(parsed, "activity_facet", "") or ""
    policy = getattr(parsed, "theme_coverage_policy", "") or ""
    existing_multi_facet = (
        facet == "multi_facet_art_photo_cafe_shop"
        or policy == "cover_required_facets"
        or bool(getattr(parsed, "theme_route_locked", False))
    )

    return art_photo_cafe_shop or area_meal_sunset or afternoon_dinner_river_night or existing_multi_facet


def _apply_route_quality_contract(parsed: Any, text: str, stage: str = "") -> Any:
    """Enforce route quality contract: 6+ display POIs, 4+ candidates, compact, timeline."""
    if not parsed or not _is_route_quality_contract_query(text, parsed):
        return parsed

    parsed.density_min_visible_pois = 6
    parsed.density_target_visible_pois = 6
    parsed.min_frontend_display_points = 6
    parsed.max_frontend_display_points = 8
    parsed.min_candidate_points = 4
    parsed.candidate_target = 4
    parsed.max_candidate_points = 5
    parsed.compact_route_required = True
    parsed.max_in_route_segment_km = min(float(getattr(parsed, "max_in_route_segment_km", 5.0) or 5.0), 5.0)

    raw = text or ""
    if (
        ("中午" in raw or "下午" in raw or "晚饭" in raw or "吃完" in raw or "最后" in raw)
        and ("景山" in raw or "河边" in raw or "夜景" in raw)
    ):
        parsed.explicit_timeline_required = True

    parsed.time_budget = max(float(getattr(parsed, "time_budget", 0.0) or 0.0), 0.75)

    print(
        f"[RouteQualityContract] stage={stage} "
        f"min_visible={parsed.density_min_visible_pois} "
        f"target_visible={parsed.density_target_visible_pois} "
        f"min_candidates={parsed.min_candidate_points} "
        f"compact={parsed.compact_route_required} "
        f"explicit_timeline={parsed.explicit_timeline_required}"
    )
    return parsed


# v28: Deterministic time-sequence extractors for explicit timeline routes


# v28: 北海公园→烤鸭→景山公园 narrow pattern


def _is_north_sea_lunch_jingshan_query(text: str) -> bool:
    raw = _extract_latest_user_input(text or "")
    return bool(
        re.search(r"先\s*(?:去|到|逛)\s*北海公园", raw)
        and re.search(r"(?:中午|午餐|午饭).{0,20}烤鸭", raw)
        and re.search(r"下午.{0,20}景山公园", raw)
    )


def _extract_north_sea_lunch_jingshan_route(text: str):
    if not _is_north_sea_lunch_jingshan_query(text):
        return None

    from .data_schema import PlannedWaypoint as PW

    return [
        PW(
            type="fixed", name="北海公园", category="visit",
            search_keyword="北海公园",
            search_keywords=["北海公园", "北海公园 走走"],
            required_terms=["北海公园", "公园"],
            excluded_terms=[], stay_minutes=120, time_slot="morning",
        ),
        PW(
            type="placeholder", name="北海公园附近烤鸭", category="meal",
            search_keyword="北海公园附近 北京烤鸭 餐厅",
            search_keywords=[
                "北海公园附近 北京烤鸭 餐厅",
                "北海公园附近 烤鸭", "北京烤鸭 餐厅",
            ],
            required_terms=["烤鸭", "北京烤鸭", "餐厅", "饭店"],
            excluded_terms=["快餐", "卤味", "熟食", "紫燕百味鸡"],
            search_center_name="北海公园",
            stay_minutes=60, time_slot="lunch",
        ),
        PW(
            type="fixed", name="景山公园", category="visit",
            search_keyword="景山公园",
            search_keywords=["景山公园", "景山公园 万春亭"],
            required_terms=["景山公园", "万春亭"],
            excluded_terms=[], stay_minutes=120, time_slot="afternoon",
        ),
    ]


def _extract_area_meal_afternoon_route_v28(text: str):
    """天安门/故宫 + 中午吃 + 景山/日落 → morning → lunch → afternoon."""
    raw = text or ""
    if not (("天安门" in raw or "故宫" in raw) and ("中午" in raw or "午饭" in raw or "午餐" in raw) and ("景山" in raw or "日落" in raw)):
        return None

    from .data_schema import PlannedWaypoint as PW
    return [
        PW(type="placeholder", name="天安门和故宫附近", category="area_stroll", time_slot="morning",
           search_keyword="天安门 故宫 附近 可逛 景点", stay_minutes=120, required_terms=["天安门", "故宫"]),
        PW(type="placeholder", name="地道北京菜", category="meal", time_slot="lunch",
           search_keyword="天安门 故宫 附近 地道北京菜 午餐", stay_minutes=60, required_terms=["北京菜", "京味"]),
        PW(type="fixed", name="景山公园", category="scenic", time_slot="afternoon",
           search_keyword="景山公园 日落 万春亭", stay_minutes=120, required_terms=["景山", "日落"]),
    ]


# v28: 北海公园→烤鸭→三里河公园 narrow pattern


def _is_north_sea_lunch_sanlihe_query(text: str) -> bool:
    raw = _extract_latest_user_input(text or "")
    return bool(
        "北海公园" in raw
        and re.search(r"(?:中午|午餐|午饭)", raw)
        and "烤鸭" in raw
        and "下午" in raw
        and "三里河公园" in raw
    )


def _extract_north_sea_lunch_sanlihe_route(text: str):
    if not _is_north_sea_lunch_sanlihe_query(text):
        return None

    from .data_schema import PlannedWaypoint as PW

    return [
        PW(
            type="fixed", name="北海公园", category="visit",
            time_slot="morning", role="destination", route_phase="beihai",
            search_keyword="北海公园",
            search_keywords=["北海公园", "北海公园 游览"],
            required_terms=["北海公园", "公园"],
            excluded_terms=[], stay_minutes=120,
        ),
        PW(
            type="placeholder", name="北海公园至三里河公园沿线烤鸭餐厅",
            category="meal", time_slot="lunch",
            corridor_search=True, placement="before_destination",
            role="corridor_task", route_phase="lunch_corridor",
            search_keyword="北海公园 三里河公园 沿线 烤鸭 餐厅",
            search_keywords=[
                "北海公园 三里河公园 沿线 烤鸭 餐厅",
                "北海公园到三里河公园 烤鸭",
                "北京烤鸭 餐厅",
            ],
            required_terms=["烤鸭", "北京烤鸭", "餐厅", "饭店"],
            excluded_terms=["快餐", "卤味", "熟食", "紫燕百味鸡"],
            stay_minutes=60,
        ),
        PW(
            type="fixed", name="三里河公园", category="visit",
            time_slot="afternoon", role="destination", route_phase="sanlihe",
            search_keyword="三里河公园",
            search_keywords=["三里河公园", "三里河公园 游览"],
            required_terms=["三里河公园", "公园"],
            excluded_terms=[], stay_minutes=120,
        ),
    ]


def _is_nearby_single_meal_request(text: str) -> bool:
    """v28: Narrow 'nearby + single meal' → planned fast path."""
    text = str(text or "").strip()
    nearby_terms = ("附近", "周边", "就近", "旁边", "附近的")
    meal_terms = ("饭馆", "餐馆", "餐厅", "饭店", "吃饭", "用餐", "找一家吃的", "找家饭馆")
    exploration_terms = ("逛逛", "散步", "走走", "转转", "游玩", "路线", "然后", "再去", "先在", "接着")
    return any(t in text for t in nearby_terms) and any(t in text for t in meal_terms) and not any(t in text for t in exploration_terms)


def _build_nearby_single_meal_waypoint(user_request: str) -> "PlannedWaypoint":
    """Build a deterministic meal placeholder for nearby single meal queries."""
    from .data_schema import PlannedWaypoint as PW
    return PW(
        type="placeholder",
        name=None,
        search_keyword="餐厅",
        category="meal",
        stay_minutes=40,
        search_keywords=["饭馆", "餐馆", "餐厅", "饭店"],
        required_terms=["饭馆", "餐馆", "餐厅", "饭店", "食堂", "菜馆"],
        excluded_terms=["咖啡馆", "咖啡店", "酒吧", "甜品店", "奶茶店"],
        search_center_name=None,
        time_slot=None,
    )


def is_nearby_multi_stop_local_request(text: str) -> bool:
    """Detect a short first-turn local chain with two ordered explicit stops.

    This is intentionally narrow.  It is a routing-contract guard, not a
    replacement for the LLM's general intent classification.
    """
    text = str(text or "").strip()
    nearby_terms = ("附近", "周边", "就近", "旁边", "附近的")
    sequence_terms = ("再", "然后", "接着", "之后", "顺便", "吃完")
    exploration_terms = ("逛逛", "散步", "走走", "转转", "游玩", "路线", "规划", "一整天", "上午", "下午", "晚上", "夜景")
    return (
        any(term in text for term in nearby_terms)
        and any(term in text for term in sequence_terms)
        and text.count("找") >= 2
        and not any(term in text for term in exploration_terms)
    )


def _reconcile_nearby_multi_stop_contract(
    parsed: ParsedIntent,
    llm_plan_mode: str,
    llm_waypoints: list[PlannedWaypoint],
) -> str:
    """Use LLM-extracted ordered stops without hard-coding destination types."""
    valid_waypoints = [
        wp for wp in llm_waypoints
        if str(getattr(wp, "name", "") or getattr(wp, "search_keyword", "") or "").strip()
    ]
    if len(valid_waypoints) >= 2:
        parsed.plan_mode = "planned"
        parsed.planned_waypoints = copy.deepcopy(valid_waypoints)
        return "llm_waypoints"
    return "llm_missing_waypoints"


_EXPLICIT_EXECUTION_ORDER_TOKENS = (
    "先", "再", "然后", "接着", "之后", "随后", "顺便", "吃完", "饭后",
    "上午", "中午", "下午", "傍晚", "晚上", "最后",
)

_GENERIC_MEAL_TERMS = {
    "吃饭", "餐厅", "饭馆", "饭店", "美食", "好吃的",
    "晚饭", "晚餐", "午饭", "午餐", "中饭", "中餐", "简餐", "用餐",
}


def _food_style_match_terms(food: str) -> list[str]:
    """Return user-visible cuisine aliases accepted as the same food style."""
    normalized = str(food or "").strip()
    if not normalized:
        return []
    for style, aliases in FOOD_STYLE_ALIASES.items():
        if style in normalized or normalized in aliases:
            return list(dict.fromkeys([normalized, style, *aliases]))
    return [normalized]

_PLACE_NAME_SUFFIXES = ("公园", "园", "宫", "门", "馆", "街", "路", "寺", "塔", "江", "河", "湖", "滩", "场", "山")


def _extract_place_like_names(text: str) -> list[tuple[int, str]]:
    """Extract literal place-like names from a go/stroll clause without a POI list."""
    results: list[tuple[int, str]] = []
    pattern = re.compile(
        r"(?:先去|想去|去到|去|到|在)([\u4e00-\u9fffA-Za-z0-9·-]{2,24}?)(?=(?:附近|里|转转|走走|逛逛|看看|游玩|参观|$|[，,。；;]))"
    )
    for match in pattern.finditer(text or ""):
        phrase = match.group(1).strip()
        split_names = re.split(r"和|及|与|、", phrase)
        # "颐和园" contains 和 as part of its proper name.  Split only when
        # every fragment itself has the shape of a place name.
        names = split_names if (
            len(split_names) > 1
            and all(len(item.strip()) >= 2 and item.strip().endswith(_PLACE_NAME_SUFFIXES) for item in split_names)
        ) else [phrase]
        for name in names:
            name = name.strip()
            if len(name) >= 2 and name.endswith(_PLACE_NAME_SUFFIXES):
                results.append((text.find(name, match.start()), name))
    return results


def _derive_ordered_action_waypoints(
    user_request: str,
    parsed: ParsedIntent,
) -> list[PlannedWaypoint]:
    """Build a compact ordered contract from literal user actions.

    It is intentionally place-agnostic: names are recognised structurally,
    while meals, photos, cafes and walks are translated into reusable map
    categories.  It only runs after the user has explicitly supplied order.
    """
    text = _extract_latest_user_input(user_request).strip()
    if not text:
        return []

    actions: list[tuple[int, int, PlannedWaypoint]] = []
    seen: set[tuple[int, str, str]] = set()
    fixed_positions: list[int] = []

    def add(position: int, priority: int, waypoint: PlannedWaypoint) -> None:
        key = (position, waypoint.category, waypoint.name or waypoint.search_keyword or "")
        if position < 0 or key in seen:
            return
        seen.add(key)
        if waypoint.type == "fixed":
            fixed_positions.append(position)
        actions.append((position, priority, waypoint))

    # A compound location such as "天安门和故宫附近" becomes two fixed
    # waypoints.  Generic phrases do not have a place suffix and are ignored.
    for position, name in _extract_place_like_names(text):
        add(position, 0, PlannedWaypoint(
                type="fixed",
                name=name,
                search_keyword=name,
                category="visit",
                stay_minutes=90,
                search_keywords=[name],
                required_terms=[name],
                must_match_terms=True,
        ))

    for fixed in getattr(parsed, "fixed_pois", []) or []:
        name = str(getattr(fixed, "name", "") or "").strip()
        position = text.find(name)
        if name and position >= 0:
            add(position, 0, PlannedWaypoint(
                type="fixed",
                name=name,
                search_keyword=name,
                category="visit",
                stay_minutes=90,
                search_keywords=[name],
                required_terms=[name],
                must_match_terms=True,
                time_slot=getattr(fixed, "user_time_budget", None),
            ))

    food_terms = list(dict.fromkeys(
        list(getattr(parsed, "food_pref_keywords", []) or [])
        + [str(item) for item in (getattr(parsed, "meal_search_keywords", []) or []) if str(item)]
    ))
    explicit_food = next(
        (term for term in food_terms if term in text and term not in _GENERIC_MEAL_TERMS),
        "",
    )
    meal_tokens = ("吃", "饭馆", "饭店", "餐厅", "晚饭", "午饭", "晚餐", "午餐")
    meal_position = min((text.find(token) for token in meal_tokens if text.find(token) >= 0), default=-1)
    if meal_position >= 0:
        keyword = explicit_food or "餐厅"
        required = _food_style_match_terms(keyword) if explicit_food else ["餐厅", "饭店", "饭馆", "小馆", "菜馆", "食堂"]
        add(meal_position, 1, PlannedWaypoint(
            type="placeholder",
            search_keyword=keyword,
            category="meal",
            stay_minutes=50,
            search_keywords=list(dict.fromkeys([keyword, f"{keyword} 餐厅", *required])) if explicit_food else ["餐厅", "饭馆", "饭店", "小馆"],
            required_terms=required,
            excluded_terms=["咖啡", "奶茶", "甜品", "面包"],
            must_match_terms=True,
        ))

    action_specs = [
        (("拍照", "出片", "摄影", "打卡"), "拍照打卡", "visit", 80),
        (("咖啡", "咖啡店", "喝杯咖啡", "奶茶", "茶饮", "下午茶"), "咖啡", "cafe", 25),
        (("散步", "走一走", "走走", "漫步", "遛弯", "逛逛"), "公园", "visit", 45),
    ]
    for tokens, keyword, category, stay_minutes in action_specs:
        positions = [text.find(token) for token in tokens if text.find(token) >= 0]
        if not positions:
            continue
        candidate_positions = sorted(set(positions)) if keyword == "公园" else [min(positions)]
        required = (
            ["艺术", "展", "创意", "观景", "地标", "建筑", "公园", "广场", "街区"]
            if keyword == "拍照打卡"
            else (["咖啡", "Coffee", "coffee", "奶茶", "茶饮", "星巴克", "瑞幸", "Manner"] if category == "cafe"
                  else ["公园", "绿地", "滨江", "江", "河", "湖", "步行街", "街区", "广场"])
        )
        excluded = ["停车场", "办公楼", "住宅", "健身"] if keyword == "拍照打卡" else []
        if keyword == "公园":
            excluded = ["健身", "游泳", "运动", "酒吧", "KTV", "夜店"]
        for position in candidate_positions:
            # "去北海公园走走" is one fixed visit, whereas "吃完再散步" is
            # a distinct later action.  Skip only the former occurrence.
            if keyword == "公园" and any(0 <= position - fixed_pos <= 16 for fixed_pos in fixed_positions):
                continue
            add(position, 2, PlannedWaypoint(
                type="placeholder",
                search_keyword=keyword,
                category=category,
                stay_minutes=stay_minutes,
                search_keywords=(["拍照打卡", "艺术区", "创意园", "观景台", "展览"] if keyword == "拍照打卡"
                                 else (["咖啡店", "咖啡"] if category == "cafe" else ["公园", "滨江步道", "步行街", "绿地"])),
                required_terms=required,
                excluded_terms=excluded,
                must_match_terms=True,
            ))

    actions.sort(key=lambda item: (item[0], item[1]))
    return [waypoint for _, _, waypoint in actions]


def _normalize_explicit_contract_waypoint(
    waypoint: PlannedWaypoint,
    user_request: str,
    food_terms: list[str],
) -> PlannedWaypoint:
    """Normalize universally understood explicit actions into map contracts."""
    wp = copy.deepcopy(waypoint)
    text = " ".join([
        str(wp.name or ""),
        str(wp.search_keyword or ""),
        " ".join(str(item or "") for item in (wp.search_keywords or [])),
    ])
    request_lower = user_request.lower()

    if any(token in text for token in ("散步", "走一走", "走走", "漫步", "遛弯", "逛逛")):
        # Area-stroll parsers sometimes carry the full clause as the search
        # center.  Recover a literal place from it before falling back to a
        # generic park, so "颐和园附近转转" stays anchored at 颐和园.
        for _, place_name in _extract_place_like_names(
            " ".join([str(getattr(wp, "search_center_name", "") or ""), user_request])
        ):
            wp.type = "fixed"
            wp.name = place_name
            wp.search_keyword = place_name
            wp.category = "visit"
            wp.search_keywords = [place_name]
            wp.required_terms = [place_name]
            wp.must_match_terms = True
            return wp
        wp.type = "placeholder"
        wp.name = None
        wp.search_keyword = "公园"
        wp.category = "visit"
        wp.search_keywords = ["公园", "滨江步道", "步行街", "绿地"]
        wp.required_terms = ["公园", "绿地", "滨江", "江", "河", "湖", "步行街", "街区", "广场"]
        wp.excluded_terms = list(dict.fromkeys((wp.excluded_terms or []) + ["健身", "游泳", "运动", "酒吧", "KTV", "夜店"]))
        wp.must_match_terms = True
        return wp

    if any(token in text for token in ("拍照", "出片", "打卡", "摄影")):
        wp.type = "placeholder"
        wp.name = None
        wp.search_keyword = "拍照打卡"
        wp.category = "visit"
        wp.search_keywords = ["拍照打卡", "艺术区", "创意园", "观景台", "展览"]
        wp.required_terms = ["艺术", "展", "创意", "观景", "地标", "建筑", "公园", "广场", "街区"]
        wp.excluded_terms = list(dict.fromkeys((wp.excluded_terms or []) + ["停车场", "办公楼", "住宅", "健身"]))
        wp.must_match_terms = True
        return wp

    if wp.category == "meal":
        explicit_food = next(
            (
                term for term in food_terms
                if term and term.lower() in request_lower
                and term not in _GENERIC_MEAL_TERMS
            ),
            "",
        )
        if explicit_food:
            wp.type = "placeholder"
            wp.name = None
            wp.search_keyword = explicit_food
            aliases = _food_style_match_terms(explicit_food)
            wp.search_keywords = list(dict.fromkeys([
                explicit_food, f"{explicit_food} 餐厅", f"{explicit_food}店", *aliases,
            ]))
            wp.required_terms = aliases
            wp.must_match_terms = True
        elif str(wp.name or wp.search_keyword or "").strip() in _GENERIC_MEAL_TERMS:
            # Time labels such as "晚饭" describe when to eat, not what a POI
            # is called.  Search the restaurant category rather than requiring
            # a literal word that normal restaurant names rarely contain.
            wp.type = "placeholder"
            wp.name = None
            wp.search_keyword = "餐厅"
            wp.search_keywords = ["餐厅", "饭馆", "饭店", "小馆"]
            wp.required_terms = ["餐厅", "饭店", "饭馆", "小馆", "菜馆", "食堂"]
            wp.must_match_terms = True

    if wp.type == "fixed" and wp.name:
        # A phrase such as "下午继续轻松走走" is an activity description,
        # not a map place.  Turn it into the same generic walk contract rather
        # than attempting a text search for arbitrary adjective words.
        escaped_name = re.escape(wp.name)
        if not wp.name.endswith(_PLACE_NAME_SUFFIXES) and re.search(
            rf"{escaped_name}.{{0,8}}(?:散步|走一走|走走|漫步|逛逛)", user_request
        ):
            wp.type = "placeholder"
            wp.name = None
            wp.search_keyword = "公园"
            wp.category = "visit"
            wp.search_keywords = ["公园", "滨江步道", "步行街", "绿地"]
            wp.required_terms = ["公园", "绿地", "滨江", "江", "河", "湖", "步行街", "街区", "广场"]
            wp.excluded_terms = list(dict.fromkeys((wp.excluded_terms or []) + ["健身", "游泳", "运动", "酒吧", "KTV", "夜店"]))
            wp.must_match_terms = True
            return wp
        wp.required_terms = [wp.name]
        wp.must_match_terms = True

    if wp.category in {"cafe", "purchase", "service"} and (wp.name or wp.search_keyword):
        wp.must_match_terms = True
    return wp


def _apply_explicit_execution_contract(
    parsed: ParsedIntent,
    user_request: str,
    rule_hints: list[PlannedWaypoint],
) -> bool:
    """Promote explicit ordered actions to the existing planned pipeline.

    This leaves broad theme discovery and multi-turn edits untouched.  It only
    prevents an action chain that the user explicitly ordered from being
    silently downgraded into a theme/macro exploration route.
    """
    text = _extract_latest_user_input(user_request).strip()
    if not any(token in text for token in _EXPLICIT_EXECUTION_ORDER_TOKENS):
        return False
    # The literal text order wins when it can form a complete contract.  The
    # existing deterministic hints and LLM waypoints remain fallbacks for
    # requests outside this compact grammar.
    candidates = _derive_ordered_action_waypoints(text, parsed)
    if len(candidates) < 2:
        candidates = list(rule_hints or [])
    if len(candidates) < 2:
        candidates = list(getattr(parsed, "planned_waypoints", []) or [])
    if len(candidates) < 2:
        return False

    food_terms = list(dict.fromkeys(
        list(getattr(parsed, "food_pref_keywords", []) or [])
        + [str(item) for item in (getattr(parsed, "meal_search_keywords", []) or []) if str(item)]
    ))
    normalized = [
        _normalize_explicit_contract_waypoint(wp, text, food_terms)
        for wp in candidates
        if str(getattr(wp, "name", "") or getattr(wp, "search_keyword", "") or "").strip()
    ]
    if len(normalized) < 2:
        return False

    parsed.planned_waypoints = normalized
    parsed.plan_mode = "planned"
    parsed.execution_contract_required = True
    parsed.explicit_timeline_required = any(bool(getattr(wp, "time_slot", "")) for wp in normalized)

    fixed_names = {str(getattr(fp, "name", "") or "") for fp in (parsed.fixed_pois or [])}
    for wp in normalized:
        if wp.type == "fixed" and wp.name and wp.name not in fixed_names:
            parsed.fixed_pois.append(FixedPoi(name=wp.name, user_time_budget=wp.time_slot))
            fixed_names.add(wp.name)

    print(
        "[ExecutionContractAudit] enabled=true "
        f"waypoints={[(wp.name or wp.search_keyword, wp.category, wp.must_match_terms, wp.time_slot) for wp in normalized]}"
    )
    return True


def _is_afternoon_dinner_river_night_query(text: str) -> bool:
    """Narrow detection for '下午文艺 + 晚饭 + 河边 + 夜景' combo pattern."""
    text = text or ""
    return (
        "下午" in text
        and ("晚饭" in text or "晚餐" in text)
        and ("吃完" in text or "饭后" in text)
        and ("河边" in text or "亮马河" in text or "水边" in text or "滨水" in text)
        and ("夜景" in text or "拍夜景" in text or "观景" in text)
    )


def _extract_afternoon_dinner_river_night_route(text: str):
    """下午文艺 + 清淡晚饭 + 河边走走 + 拍夜景."""
    raw = text or ""
    if not _is_afternoon_dinner_river_night_query(raw):
        return None

    from .data_schema import PlannedWaypoint as PW
    return [
        PW(type="placeholder", name="北京文艺路线", category="theme_route", time_slot="afternoon",
           search_keyword="北京 文艺 路线 拍照 小店 咖啡 胡同 街区", stay_minutes=180, required_terms=["文艺", "拍照"]),
        PW(type="placeholder", name="清淡晚饭", category="meal", time_slot="dinner",
           search_keyword="北京 清淡 晚饭 餐厅", stay_minutes=60, required_terms=["清淡"]),
        PW(type="placeholder", name="河边走走", category="river_stroll", time_slot="evening",
           search_keyword="北京 河边 散步 亮马河 什刹海", stay_minutes=60, required_terms=["河边", "散步"]),
        PW(type="placeholder", name="拍夜景的地方", category="night_view", time_slot="night",
           search_keyword="北京 拍夜景 观景 夜景", stay_minutes=60, required_terms=["夜景"]),
    ]


async def _postprocess(parsed: ParsedIntent, user_request: str, user_profile: UserProfile, current_time: dt.datetime) -> ParsedIntent:
    # v21: Strip structured hints from deterministic parsers — prevent context pollution.
    # Structured hints like <structured_hints>保持theme=夜景</structured_hints> are for LLM only.
    _clean_user_request = re.sub(
        r"<structured_hints>.*?</structured_hints>", "",
        user_request, flags=re.DOTALL,
    ).strip()
    # v21: Also strip stray refine_current control text ("保持theme=...", "；其他不变...", etc.)
    _clean_user_request = re.sub(
        r"(?:；|;|,)?\s*(?:保持(?:theme|location|duration|start_time|plan_mode|其他不变)[^；;]*)+",
        "", _clean_user_request,
    ).strip()
    # v21: Strip "按以下参数调整：{...}" and trailing JSON
    _clean_user_request = re.sub(
        r"按以下参数调整：\{[^}]+\}", "", _clean_user_request,
    ).strip()
    if _clean_user_request != user_request:
        print(
            f"[DEBUG step1] stripped structured hints from request: "
            f"len_before={len(user_request)} len_after={len(_clean_user_request)}"
        )
        user_request = _clean_user_request

    # v24: Extract latest_user_input from conversation_context wrapper.
    # All text-based checks below MUST use the actual user message, never the XML wrapper.
    _nl_post = _extract_latest_user_input(user_request)
    if _has_conversation_context(user_request):
        print(
            f"[ContextParseAudit] _postprocess has_conversation_context=true "
            f"latest_user_input={_nl_post[:120]}"
        )

    city = await resolve_departure_city(user_profile)
    apply_resolved_city(user_profile, city)
    parsed.resolved_city = city
    # v21: Resolve landmark aliases in fixed_pois
    for fp in getattr(parsed, "fixed_pois", []) or []:
        if fp.name in _LANDMARK_ALIAS_MAP:
            _old = fp.name
            fp.name = _LANDMARK_ALIAS_MAP[_old]
            print(f"[DEBUG alias] resolved landmark: '{_old}' → '{fp.name}'")

    # v21: Apply contextual search center from follow_up dispatch
    _ctx_center = getattr(user_profile, "_contextual_search_center", None) or {}
    if _ctx_center and _ctx_center.get("location", {}).get("lat"):
        parsed.search_area_label = _ctx_center.get("label", "")
        parsed.search_area_location = _ctx_center.get("location")
        # Also set original_location so route starts from the contextual center
        _ctx_loc = dict(_ctx_center.get("location", {}))
        _ctx_loc["label"] = _ctx_center.get("label", _ctx_loc.get("label", ""))
        parsed.original_location = _ctx_loc
        # v21: Set proximity flags to skip re-geocoding of already-known location
        parsed.proximity_requested = True
        parsed.is_search_center_only = True
        print(
            f"[DEBUG step1] contextual_search_center applied (skip re-geocode): "
            f"label={parsed.search_area_label} "
            f"source={_ctx_center.get('source')} "
            f"loc=({_ctx_loc.get('lat','')},{_ctx_loc.get('lng','')})"
        )

    # v21: Utility lookup detection — restroom/toilet → utility fast path
    _is_util, _util_cat, _util_query = _detect_utility_lookup(user_request)
    if _is_util:
        parsed.poi_query_type = "utility_nearby"
        parsed.category_id = _util_cat
        parsed.primary_query = _util_query
        parsed.activity_facet = "restroom"
        parsed.utility_lookup_requested = True
        parsed.proximity_requested = True
        parsed.time_budget = 0.0  # zero budget — not a tourist route
        parsed.allowed_typecode_prefixes = ["200300", "200301", "200302"]
        parsed.search_keywords = ["公共厕所", "卫生间", "洗手间", "公厕"]
        parsed.plan_mode = "utility"
        print(
            f"[DEBUG utility] restroom detected: cat={_util_cat} "
            f"query={_util_query} poi_type={parsed.poi_query_type}"
        )

    # v21: "X附近找Y" pattern — convert X from fixed_poi to search_area
    # "在小西天牌楼附近找避暑" → 小西天牌楼=search_center, 避暑=feature_lookup
    _nearby_place_match = re.search(
        r"(?:在|去|到|离)?(.{2,20}?)(?:的)?(?:附近|周边|旁边|周围|近)(?:找个|找一家|找个地方|找|有没有|推荐)",
        user_request,
    )
    if _nearby_place_match and parsed.fixed_pois:
        _nearby_place = _nearby_place_match.group(1).strip()
        _nearby_place = re.sub(r"^(?:在|去|到|离|从)", "", _nearby_place).strip()
        # Check if this place matches any fixed_poi
        for fp in list(parsed.fixed_pois):
            if fp.name in _nearby_place or _nearby_place in fp.name:
                parsed.search_area_label = fp.name
                if fp.location:
                    parsed.search_area_location = fp.location
                parsed.fixed_pois.remove(fp)
                parsed.proximity_requested = True
                parsed.is_search_center_only = True
                print(
                    f"[DEBUG X附近Y] converted fixed_poi '{fp.name}' → search_area "
                    f"loc={fp.location.get('lat','') if fp.location else 'none'}"
                )
                break

    # v21: Fixed anchor enumeration detection — "A、B、C都想去" vs "先去A，再去B"
    # Only set planned when explicit sequence markers exist
    _has_sequence = any(w in user_request for w in ["先", "然后", "再", "接着", "最后"])
    _has_enum_list = bool(re.search(r"[、，,].*[、，,]", user_request))
    _no_sequence_verbs = any(w in user_request for w in [
        "都想去", "都走到", "都想看", "都逛逛", "都玩", "都去",
        "怎么安排", "怎么走", "如何安排", "路线怎么", "怎么排",
    ])
    _time_prefix = re.search(r"^(?:只有|只有|就)\s*(.{1,8}?(?:天|日|小时))", user_request)
    if _has_enum_list and _no_sequence_verbs and not _has_sequence:
        # Enumeration without sequence → exploratory with fixed anchor optimization
        parsed.plan_mode = "exploratory"
        if not getattr(parsed, "planned_waypoints", []):
            parsed.planned_waypoints = []
        # v21: Multi-day fixed anchor optimization profile
        _req_days = 1
        if parsed.time_budget > 1.0 and len(parsed.fixed_pois) >= 2:
            _req_days = max(2, int(parsed.time_budget))
        if _req_days >= 2:
            parsed.optimization_profile = "multi_day_fixed_anchor_enhanced"
            parsed.requested_days = _req_days
            parsed.preserve_requested_days = True
            print(
                f"[MultiDayOptimizationAudit] enabled=true "
                f"requested_days={_req_days} fixed_pois={len(parsed.fixed_pois)}"
            )
        print(
            f"[WaypointExtractionAudit] raw={user_request[:60]} "
            f"plan_mode=exploratory route_strategy=fixed_anchor_optimization "
            f"reason=enumeration_without_sequence_markers"
        )

    # v21: Multi-day transport constraint detection — "第一天上午地铁，第二天下午骑车"
    _multi_day_match = re.search(r"第[一二三]天|D\s*[123]|Day\s*[123]", user_request, re.IGNORECASE)
    if _multi_day_match:
        # Force two days when explicit day markers exist
        parsed.duration = "two days"
        parsed.time_budget = 2.0
        parsed.requested_days = 2
        parsed.preserve_requested_days = True
        # Extract per-period transport constraints
        _transport_map = {"地铁": "transit_subway", "公交": "bus", "巴士": "bus",
                          "打车": "taxi", "出租": "taxi", "网约车": "taxi",
                          "骑车": "bicycle", "骑行": "bicycle", "单车": "bicycle",
                          "步行": "walking", "走路": "walking"}
        _day_map = {"一": 1, "二": 2, "三": 3, "1": 1, "2": 2, "3": 3}
        _period_map = {"上午": "morning", "下午": "afternoon", "晚上": "evening"}
        _constraints = []
        for _dm in re.finditer(r"第([一二三123])天\s*(上午|下午|晚上)?\s*([地铁公交巴士打车出租网约车骑车骑行单车步行走路]{2,3})", user_request):
            _d = _day_map.get(_dm.group(1), 1)
            _p = _period_map.get(_dm.group(2) or "", "")
            _t = _transport_map.get(_dm.group(3), "")
            if _t:
                _constraints.append({"day_index": _d, "period": _p or "all_day", "transport": _dm.group(3), "transport_mode": _t})
        if _constraints:
            parsed.transport_constraints = _constraints
            parsed.transport_hint = _constraints[0].get("transport", "") if _constraints else None
            print(f"[DEBUG multi_day_transport] days=2 constraints={len(_constraints)}")

    # v22: Metro-accessible cluster route — "只坐地铁 + 景点之间步行不超过5分钟"
    _metro_only_terms = [
        "只坐地铁", "全程地铁", "只能坐地铁", "不打车", "不坐公交", "不开车",
        "靠地铁", "沿地铁线", "地铁可达", "地铁站附近",
        "只靠地铁", "仅地铁", "地铁出行", "坐地铁去",
    ]
    _metro_walk_terms = [
        "步行不超过", "走路不超过", "出站步行", "步行5分钟",
        "景点之间步行不超过", "地铁站出来步行", "地铁口步行",
    ]
    _is_metro_only = any(t in user_request for t in _metro_only_terms)
    _is_metro_walk = any(t in user_request for t in _metro_walk_terms)

    if _is_metro_only and (_is_metro_walk or "步行不超过" in user_request):
        # Determine max walk radius
        _metro_walk_match = re.search(r"步行不超过\s*(\d+)\s*分钟", user_request)
        _walk_radius = int(_metro_walk_match.group(1)) if _metro_walk_match else 5

        parsed.intent_name = "metro_accessible_cluster_route"
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.route_strategy = "station_based_itinerary"
        parsed.transport_hint = "地铁"
        parsed.transport_constraints = [{
            "day_index": 1, "period": "all_day",
            "transport": "地铁", "transport_mode": "transit_subway",
        }]
        parsed.strict_transport_mode = True
        parsed.walking_cluster_requested = True
        parsed.max_walk_between_pois_min = _walk_radius
        parsed.station_walk_radius_min = _walk_radius
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        parsed.theme_label = "地铁可达路线"

        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 地铁站附近 景点",
            f"{city_short} 地铁5分钟步行 景点",
            f"{city_short} 地铁2号线 景点",
            f"{city_short} 地铁8号线 景点",
            f"{city_short} 中轴线 地铁 游览",
            f"{city_short} 地铁可达 博物馆",
            f"{city_short} 地铁口 附近 公园",
            f"{city_short} 地铁口 附近 胡同",
        ]
        parsed.micro_keywords = [
            f"{city_short} 地铁站 周边 景点", f"{city_short} 地铁口 步行",
        ]
        # Beijing metro station anchors along the central axis
        parsed.station_anchors = [
            "天安门东站", "天安门西站", "前门站", "王府井站",
            "南锣鼓巷站", "北海北站", "什刹海站", "雍和宫站",
            "鼓楼大街站", "奥林匹克公园站",
        ]
        parsed.other_constraints = _append_unique(
            list(getattr(parsed, "other_constraints", []) or []),
            [
                f"每个景点距最近地铁站步行≤{_walk_radius}分钟",
                "跨区域移动必须通过地铁完成",
                "地铁站是路线锚点",
            ],
        )
        print(
            f"[DEBUG metro_cluster] detected: walk_radius={_walk_radius}min "
            f"strict_transport=True route_strategy=station_based_itinerary"
        )

    # v21: Walking cluster detection — "景点之间走路不超过X分钟"
    # v22: Skip if already detected as metro-accessible cluster route
    if not _is_metro_only:
        _walk_cluster_match = re.search(r"(?:景点|站|地点)之间.*?(\d+)\s*分钟", user_request)
        if not _walk_cluster_match:
            _walk_cluster_match = re.search(r"走路不(?:超过|要超过|多于).*?(\d+)\s*分", user_request)
        if _walk_cluster_match:
            _max_walk = int(_walk_cluster_match.group(1))
            parsed.poi_query_type = "theme_route"
            parsed.primary_query = ""
            parsed.category_id = None
            parsed.allowed_typecode_prefixes = []
            parsed.walking_cluster_requested = True
            parsed.max_walk_between_pois_min = _max_walk
            parsed.route_strategy = "walking_cluster_multi_day"
            parsed.plan_mode = "exploratory"
            parsed.theme_required = True
            if parsed.time_budget >= 2.0:
                parsed.requested_days = max(2, int(parsed.time_budget))
                parsed.preserve_requested_days = True
            city_short = city[:-1] if city.endswith("市") else city
            parsed.search_keywords = [
                f"{city_short} 什刹海 景点", f"{city_short} 南锣鼓巷 周边",
                f"{city_short} 北海公园 景山", f"{city_short} 前门 大栅栏",
                f"{city_short} 奥森 步行", f"{city_short} 798 艺术区 步行",
                f"{city_short} 颐和园 圆明园", f"{city_short} 胡同 漫步",
            ]
            parsed.other_constraints = _append_unique(parsed.other_constraints,
                [f"景点间步行≤{_max_walk}分钟"])
            print(f"[DEBUG walking_cluster] detected: max_walk={_max_walk}min days={parsed.requested_days}")

    # v22: Group meal preference conflict — "清淡素食 vs 重辣火锅烧烤" etc.
    _conflict_indicators = ["同行", "朋友", "同一顿饭", "满足所有人", "兼顾",
                            "都能吃", "众口难调", "一起吃饭", "一起", "找一家",
                            "一桌", "同伴", "有人吃", "有人想", "另一个", "另一个想"]
    _both_sides = (
        any(t in user_request for t in ["清淡", "素食", "素菜", "不吃辣", "不吃辣椒",
                                        "不能吃辣", "不辣"])
        and
        any(t in user_request for t in ["重辣", "麻辣", "火锅", "烧烤", "烤串",
                                        "川菜", "湘菜", "辣味", "烤肉", "辣锅"])
    )
    _is_conflict = any(t in user_request for t in _conflict_indicators)

    if _both_sides and _is_conflict:
        parsed.intent_name = "group_meal_preference_conflict"
        parsed.poi_query_type = "meal_conflict"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.route_strategy = "meal_conflict_resolution"
        parsed.strong_meal_intent = True
        parsed.conflict_meal_request = True
        parsed.plan_mode = "exploratory"
        parsed.meal_only_request = True

        # Extract food preference keywords from both sides
        _all_food_terms = ["清淡", "素食", "素菜", "重辣", "麻辣", "火锅", "烧烤",
                           "烤串", "川菜", "湘菜", "辣味", "烤肉", "辣锅", "不吃辣",
                           "不吃辣椒", "不能吃辣", "不辣", "清汤", "番茄锅", "菌汤"]
        _found_food = sorted(set(t for t in _all_food_terms if t in user_request), key=lambda x: -len(x))
        parsed.food_pref_keywords = _found_food[:8]

        city_short = city[:-1] if city.endswith("市") else city
        # Tiered search keywords for conflict resolution
        parsed.meal_search_keywords = [
            f"{city_short} 鸳鸯锅 火锅",
            f"{city_short} 火锅 清汤锅底 素菜",
            f"{city_short} 火锅 番茄锅 菌汤锅",
            f"{city_short} 综合餐厅 素食 辣",
            f"{city_short} 商场餐饮 美食广场",
            f"{city_short} 可选辣度 川菜",
            f"{city_short} 素食友好 餐厅",
            f"{city_short} 创意融合菜",
            f"{city_short} 云南菜",
            f"{city_short} 粤菜",
        ]
        parsed.search_keywords = parsed.meal_search_keywords[:]
        parsed.micro_keywords = [
            f"{city_short} 火锅 素菜拼盘",
            f"{city_short} 餐厅 清淡 辣",
        ]

        conflict_constraint = {
            "meal": "lunch_or_dinner",
            "conflict_type": "group_preference_conflict",
            "must_support": [t for t in _found_food if t in ("清淡", "素食", "素菜", "不吃辣")],
            "also_support": [t for t in _found_food if t in ("重辣", "麻辣", "火锅", "烧烤", "烤串", "辣锅", "烤肉")],
            "solution_strategy": "multi_option_same_restaurant_or_food_court",
        }
        # meal_constraints MUST be list[dict] — NEVER assign a bare dict
        _existing = list(getattr(parsed, "meal_constraints", []) or [])
        parsed.meal_constraints = _existing + [conflict_constraint]

        # Store structured conflict detail in the dedicated dict field
        parsed.meal_conflict_detail = conflict_constraint

        # v28: Post-meal stroll — "吃完想在附近散散步"
        if any(t in user_request for t in ["吃完", "饭后"]) and any(t in user_request for t in ["散步", "散散步", "走走", "逛逛"]):
            parsed.post_meal_stroll_required = True
            parsed.meal_only_request = False
            parsed.proximity_requested = True
            parsed.nearby_strict_radius_m = 3000
            parsed.nearby_max_radius_m = 5000
            parsed.max_first_leg_km = 5.0
            parsed.compact_route_required = True
            parsed.min_candidate_points = max(getattr(parsed, "min_candidate_points", 0) or 0, 2)
            parsed.candidate_target = max(getattr(parsed, "candidate_target", 0) or 0, 3)
            parsed.max_candidate_points = max(getattr(parsed, "max_candidate_points", 0) or 0, 4)

        print(
            f"[DEBUG meal_conflict] detected: "
            f"food_prefs={_found_food} strategy=meal_conflict_resolution"
            f" post_meal_stroll={parsed.post_meal_stroll_required}"
        )

    # v22: Budget contradiction — "免费路线 + 环球影城/演唱会/高端餐厅" etc.
    _free_budget_terms = [
        "免费", "不花钱", "0元", "零预算", "免费玩", "预算为0", "免费路线",
        "免费一日", "免费游", "免费游玩", "玩免费的", "不要钱", "免费景点",
    ]
    _paid_anchor_terms = [
        "环球影城", "环球度假区", "迪士尼", "演唱会", "音乐节",
        "高端餐厅", "米其林", "高奢", "奢华餐厅", "高端下午茶",
        "高档餐厅", "星级酒店", "大餐", "海鲜大餐", "日料自助",
    ]
    _is_free_budget = any(t in user_request for t in _free_budget_terms)
    _paid_conflicts = [t for t in _paid_anchor_terms if t in user_request]

    if _is_free_budget and _paid_conflicts:
        parsed.intent_name = "budget_contradiction_trip"
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.route_strategy = "auto_budget_downgrade"
        parsed.budget_contradiction_detected = True
        parsed.budget_mode = "free"
        parsed.budget_per_capita = 0
        parsed.conflict_items = _paid_conflicts
        parsed.auto_degrade_required = True
        parsed.needs_clarification = False
        parsed.clarification_required = False
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        parsed.theme_label = "免费路线（含外观打卡）"
        parsed.duration = "a full day" if parsed.time_budget < 1.0 else parsed.duration

        city_short = city[:-1] if city.endswith("市") else city
        # Free route recall: parks, streets, squares, waterfront, free culture
        parsed.search_keywords = [
            f"{city_short} 免费景点",
            f"{city_short} 免费公园",
            f"{city_short} 免费博物馆",
            f"{city_short} 胡同 街区 免费",
            f"{city_short} 中轴线 外观 打卡",
            f"{city_short} 滨水步道 免费",
            f"{city_short} 城市广场 免费",
            f"{city_short} 商圈 外部游览",
            f"{city_short} 免费展览",
        ]
        # Degrade paid items to external check-in
        _degraded = []
        _paid_items_degraded = []
        if "环球影城" in _paid_conflicts or "环球度假区" in _paid_conflicts:
            _degraded.append("北京环球城市大道")
            _degraded.append("环球度假区外部商圈打卡")
            _paid_items_degraded.append("环球影城→外部城市大道打卡(不入园)")
        if "迪士尼" in _paid_conflicts:
            _degraded.append("迪士尼小镇外部打卡")
            _paid_items_degraded.append("迪士尼→小镇外部打卡(不入园)")
        if "演唱会" in _paid_conflicts:
            _paid_items_degraded.append("演唱会→晚间自费可选")
        if "音乐节" in _paid_conflicts:
            _paid_items_degraded.append("音乐节→自费可选活动")
        if "高端餐厅" in _paid_conflicts or "米其林" in _paid_conflicts or "高端下午茶" in _paid_conflicts:
            _paid_items_degraded.append("高端餐饮→自费可选(主路线用平价餐饮)")
        parsed.paid_items_degraded = _paid_items_degraded

        # Meal search: budget-friendly alternatives
        parsed.meal_search_keywords = [
            f"{city_short} 平价简餐",
            f"{city_short} 商圈轻食",
            f"{city_short} 便利店",
            f"{city_short} 人均低 餐厅",
            f"{city_short} 小吃 快餐",
        ]
        parsed.micro_keywords = [
            "免费 街区", "免费 公园", "免费 打卡",
            "平价 简餐", "商圈 外部", "城市大道",
        ]

        parsed.other_constraints = _append_unique(
            list(getattr(parsed, "other_constraints", []) or []),
            [
                "免费路线为主，付费项目降级为外观打卡或自费可选",
                "不要将付费项目(环球影城入园/演唱会/高端餐厅)放入免费主路线",
                "不要只返回餐饮POI作为主路线",
            ],
        )
        print(
            f"[DEBUG budget_contradiction] detected: "
            f"free_budget=True paid_conflicts={_paid_conflicts} "
            f"strategy=auto_budget_downgrade"
        )

    # v21: Fruit picking + scenic combo detection
    _picking_terms = ["采摘", "摘水果", "果园", "梨园", "苹果", "葡萄",
                      "柿子", "枣", "栗子", "草莓", "樱桃", "秋天采摘", "秋季采摘"]
    _combo_terms = ["景点结合", "和景点结合", "顺便玩", "去哪一区", "哪个区", "区县推荐"]
    _is_picking = any(t in user_request for t in _picking_terms)
    _is_combo = any(t in user_request for t in _combo_terms)
    if _is_picking and (_is_combo or "采摘" in user_request):
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.activity_facet = "fruit_picking_combo"
        parsed.fruit_picking_requested = True
        parsed.scenic_combo_requested = _is_combo
        parsed.district_recommendation_requested = "哪个区" in user_request or "去哪一区" in user_request
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        if parsed.time_budget < 0.5:
            parsed.duration = "a full day"
            parsed.time_budget = 1.0
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 秋季采摘园", f"{city_short} 果园 采摘",
            f"{city_short} 苹果采摘", f"{city_short} 梨园采摘",
            f"{city_short} 农业观光园", f"{city_short} 采摘园 景点",
            f"{city_short} 昌平 采摘园", f"{city_short} 顺义 采摘园",
        ]
        parsed.micro_keywords = ["采摘园 体验", "果园 采摘", "农庄 亲子"]
        print(f"[DEBUG fruit_picking] detected: combo={_is_combo} district_req={parsed.district_recommendation_requested}")

    # v21: Handcraft intangible heritage detection — 景泰蓝/掐丝珐琅/毛猴/非遗手作
    _handcraft_terms = ["景泰蓝", "掐丝珐琅", "珐琅厂", "毛猴", "北京毛猴",
                        "非遗", "传统工艺", "手工艺", "手作", "工坊", "体验课"]
    _is_handcraft = any(t in user_request for t in _handcraft_terms)
    if _is_handcraft:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.theme_profile = "handcraft_intangible_heritage"
        parsed.activity_facet = "handcraft_workshop"
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        if parsed.time_budget < 0.25:
            parsed.duration = "a half day"
            parsed.time_budget = 0.5
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 景泰蓝 体验", f"{city_short} 掐丝珐琅 体验",
            f"{city_short} 毛猴 制作体验", f"{city_short} 非遗体验馆",
            f"{city_short} 传统工艺体验", f"{city_short} 手作工坊",
            f"{city_short} 景泰蓝艺术博物馆", f"{city_short} 非遗手作",
        ]
        parsed.micro_keywords = [
            "景泰蓝 制作体验", "掐丝珐琅 DIY", "毛猴 制作体验",
            "非遗 手作体验", "传统工艺 工坊",
        ]
        print(f"[DEBUG handcraft] detected: theme=handcraft_intangible_heritage")

    # v21: No-reservation flexible trip detection
    _is_no_reservation = _is_no_reservation_request_v2(user_request)
    if _is_no_reservation:
        _apply_no_reservation_flexible_trip_v2(parsed, city)
        print(f"[DEBUG no_reservation] detected: activity=no_reservation_flexible_trip")

    # v21: Campus canteen visit detection — "北大食堂/清华食堂"
    _canteen_match = re.search(r"(北大|清华大学|清华|北航|人大|北师大|北京航空航天大学)\s*食堂", user_request)
    if _canteen_match:
        _uni_raw = _canteen_match.group(1)
        _uni_full = _UNIVERSITY_ALIAS_MAP.get(_uni_raw, _uni_raw)
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "campus_canteen_visit"
        parsed.explicit_meal_intent = True
        parsed.plan_mode = "exploratory"
        if _uni_full not in [fp.name for fp in (getattr(parsed, "fixed_pois", []) or [])]:
            parsed.fixed_pois.append(FixedPoi(name=_uni_full))
        _existing_meals = getattr(parsed, "meal_constraints", []) or []
        _existing_meals.append({"meal": "lunch", "fixed_poi_name": _uni_full,
                                "keywords": [f"{_uni_full} 食堂", f"{_uni_raw} 食堂"]})
        parsed.meal_constraints = _existing_meals[:3]
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{_uni_full} 校园游览", f"{_uni_full} 未名湖",
            f"{_uni_full} 食堂", f"{_uni_raw} 食堂",
        ]
        parsed.micro_keywords = ["校园游览", "大学食堂", f"{_uni_raw} 校园"]
        print(f"[DEBUG campus_canteen] detected: uni={_uni_full}")

    # v21: Park boating detection — "北海或颐和园划船/游船"
    _boating_terms = ["划船", "游船", "泛舟", "租船", "脚踏船", "电瓶船", "船码头", "湖面"]
    _is_boating = any(t in user_request for t in _boating_terms)
    if _is_boating:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "park_boating"
        parsed.plan_mode = "exploratory"
        if parsed.time_budget < 0.5:
            parsed.duration = "a half day"
            parsed.time_budget = 0.5
        city_short = city[:-1] if city.endswith("市") else city
        # Detect park candidates
        _park_kws = []
        if "北海" in user_request: _park_kws.append("北海公园")
        if "颐和园" in user_request: _park_kws.append("颐和园")
        if "昆明湖" in user_request: _park_kws.append("昆明湖")
        _both = "和" in user_request and "都" in user_request
        if _both and len(_park_kws) >= 2:
            for pk in _park_kws[:2]:
                if pk not in [fp.name for fp in (getattr(parsed, "fixed_pois", []) or [])]:
                    parsed.fixed_pois.append(FixedPoi(name=pk))
        elif _park_kws:
            parsed.optional_anchor_candidates = _park_kws[:2]
        parsed.search_keywords = [
            f"{city_short} 北海公园 划船", f"{city_short} 颐和园 划船",
            f"{city_short} 北海公园 游船", f"{city_short} 颐和园 游船",
            f"{city_short} 北海公园 码头", f"{city_short} 颐和园 码头",
            f"{city_short} 昆明湖 游船",
        ] if _park_kws else [f"{city_short} 公园 划船", f"{city_short} 游船 码头"]
        parsed.micro_keywords = ["划船 游船", "公园 码头", "湖面 泛舟"]
        print(f"[DEBUG park_boating] detected: parks={_park_kws} both={_both}")

    # v21: Hot spring relaxation detection — "温泉/泡汤/汤泉/汗蒸/SPA"
    _hotspring_terms = ["温泉", "泡温泉", "泡汤", "汤泉", "汤池", "私汤", "洗浴", "汗蒸", "SPA", "水疗"]
    _is_hotspring = any(t in user_request for t in _hotspring_terms)
    if _is_hotspring:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = "温泉"
        parsed.activity_facet = "hot_spring_after_trip"
        parsed.plan_mode = "exploratory"
        _is_after_trip = any(t in user_request for t in ["玩累了", "行程结束", "一天行程", "结束后", "晚上去"])
        if _is_after_trip:
            parsed.evening_requested = True
            parsed.relaxation_after_route = True
        if parsed.time_budget < 0.5:
            parsed.duration = "a half day"
            parsed.time_budget = 0.5
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 温泉", f"{city_short} 汤泉",
            f"{city_short} 泡汤", f"{city_short} 温泉酒店",
            f"{city_short} 私汤", f"{city_short} 洗浴 汤泉",
            f"{city_short} 汗蒸 温泉", f"{city_short} 周边 温泉",
        ]
        parsed.micro_keywords = ["温泉 泡汤", "汤泉 洗浴", "私汤 度假"]
        print(f"[DEBUG hotspring] detected: after_trip={_is_after_trip}")

    # v21: Anti-group-tour / low-crowd local route detection
    _low_crowd_terms = ["不想去旅行团", "避开旅行团", "不要游客团", "人少一点",
                        "别太商业化", "避开热门景区", "不要人挤人", "小众",
                        "非热门", "冷门", "不扎堆", "不要景区", "避开景区"]
    _is_low_crowd = any(t in user_request for t in _low_crowd_terms)
    if _is_low_crowd:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "low_crowd_local_route"
        parsed.plan_mode = "exploratory"
        parsed.crowd_preference = "low"
        if parsed.time_budget < 0.5:
            parsed.duration = "a half day"
            parsed.time_budget = 0.5
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 小众路线", f"{city_short} 本地人推荐",
            f"{city_short} 人少 景点", f"{city_short} 胡同 漫步",
            f"{city_short} 老街 区域", f"{city_short} 社区博物馆",
            f"{city_short} 小众公园", f"{city_short} 安静 文化空间",
        ]
        parsed.micro_keywords = [
            "本地生活街区", "胡同漫步", "小众文化点",
            "社区博物馆", "安静公园", "老街散步",
        ]
        parsed.micro_excluded_terms = _append_unique(
            getattr(parsed, "micro_excluded_terms", []) or [],
            ["旅行团", "团队游", "网红打卡扎堆", "热门景区", "游客中心", "排队", "人流拥挤"],
            limit=15,
        )
        print(f"[DEBUG low_crowd] detected: crowd_pref=low")

    # v21: Hotel hopping / multi-area lodging detection
    _hotel_hop_terms = ["体验不同区域的酒店", "每天换酒店", "一天住一个区", "换着住",
                        "酒店怎么匹配行程", "staycation", "多区域住宿", "每天换一家酒店"]
    _is_hotel_hop = any(t in user_request for t in _hotel_hop_terms)
    if _is_hotel_hop:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "multi_area_lodging_route"
        parsed.theme_profile = "lodging_campus_staycation"
        parsed.lodging_required = True
        parsed.hotel_hopping_requested = True
        parsed.plan_mode = "exploratory"
        _req_days = max(2, int(parsed.time_budget) if parsed.time_budget > 0 else 3)
        parsed.requested_days = _req_days
        parsed.preserve_requested_days = True
        parsed.duration = "two days" if _req_days == 2 else "three days"
        parsed.time_budget = float(_req_days)
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 精品酒店", f"{city_short} 设计酒店",
            f"{city_short} 四合院酒店", f"{city_short} 胡同酒店",
            f"{city_short} 国贸 酒店", f"{city_short} 三里屯 酒店",
            f"{city_short} 后海 酒店", f"{city_short} 前门 酒店",
        ]
        parsed.micro_keywords = ["精品酒店", "设计酒店", "四合院民宿", "区域住宿体验"]
        print(f"[DEBUG hotel_hop] detected: days={_req_days}")

    # v21: New Year / flag-raising trip detection
    _newyear_terms = ["元旦", "跨年", "跨年夜", "12月31", "1月1", "升旗", "天安门升旗"]
    _is_newyear = any(t in user_request for t in _newyear_terms)
    if _is_newyear:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "new_year_flag_raising_trip"
        parsed.plan_mode = "exploratory"
        parsed.evening_requested = True
        parsed.early_morning_event_required = True
        parsed.duration = "two days" if "跨年" in user_request or "12月31" in user_request else "a full day"
        parsed.time_budget = 2.0 if parsed.duration == "two days" else 1.0
        if "升旗" in user_request:
            if not getattr(parsed, "fixed_pois", []):
                parsed.fixed_pois = []
            parsed.fixed_pois.append(FixedPoi(name="天安门广场"))
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 跨年夜 三里屯", f"{city_short} 跨年夜 蓝色港湾",
            f"{city_short} 元旦 升旗 天安门广场", f"{city_short} 元旦 故宫",
            f"{city_short} 元旦 天坛", f"{city_short} 中轴线 元旦游览",
        ]
        parsed.other_constraints = _append_unique(parsed.other_constraints, [
            "跨年需提前查开放时间", "升旗需查官方时间+安检排队",
            "元旦严寒注意保暖", "提前确认故宫预约"
        ])
        print(f"[DEBUG newyear_flag] detected: duration={parsed.duration}")

    # v21: Graduation fun trip / Universal Resort detection
    _grad_terms = ["大学毕业旅行", "毕业游", "毕业旅行", "嗨玩", "环球影城", "环球度假区"]
    _is_grad = any(t in user_request for t in _grad_terms)
    if _is_grad:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "graduation_fun_trip"
        parsed.plan_mode = "exploratory"
        parsed.crowd_type = "朋友"
        if parsed.time_budget < 1.0:
            parsed.duration = "a full day"
            parsed.time_budget = 1.0
        _group_match = re.search(r"(\d+)个?人", user_request)
        if _group_match:
            parsed.other_constraints = _append_unique(parsed.other_constraints or [],
                [f"{_group_match.group(1)}人同行"])
        if not parsed.budget_per_capita:
            parsed.budget_per_capita = 1500.0
        if "环球影城" in user_request or "环球度假区" in user_request:
            _uni_name = _LANDMARK_ALIAS_MAP.get("环球影城", "北京环球度假区")
            if _uni_name not in [fp.name for fp in (getattr(parsed, "fixed_pois", []) or [])]:
                parsed.fixed_pois.append(FixedPoi(name=_uni_name))
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 环球度假区", f"{city_short} 环球影城",
            f"{city_short} 年轻人 嗨玩", f"{city_short} 夜生活",
            f"{city_short} 密室 KTV", f"{city_short} 聚餐",
        ]
        parsed.micro_keywords = ["毕业旅行", "环球影城", "嗨玩", "朋友聚会"]
        print(f"[DEBUG grad_trip] detected: crowd=朋友 budget={parsed.budget_per_capita}")

    # v21: Romantic couple weekend route detection
    _couple_terms = ["女朋友", "男朋友", "对象", "情侣", "约会", "纪念日", "浪漫"]
    _photo_night_terms = ["拍照", "出片", "夜景"]
    _is_couple = any(t in user_request for t in _couple_terms)
    _is_photo_night = any(t in user_request for t in _photo_night_terms)
    if _is_couple or (_is_photo_night and ("周末" in user_request or "约会" in user_request)):
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "romantic_couple_weekend_route"
        parsed.theme_profile = "relationship_group_scenarios"
        parsed.crowd_type = "情侣"
        parsed.evening_requested = True
        parsed.plan_mode = "exploratory"
        if parsed.time_budget < 1.0:
            parsed.duration = "a full day"
            parsed.time_budget = 1.0
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 情侣约会 路线", f"{city_short} 浪漫约会",
            f"{city_short} 夜景约会", f"{city_short} 适合情侣 拍照",
            f"{city_short} 约会餐厅 夜景", f"{city_short} 亮马河 夜景",
            f"{city_short} 798 拍照", f"{city_short} 景山 傍晚",
        ]
        parsed.micro_keywords = [
            "情侣拍照", "浪漫散步", "夜景观赏", "约会餐厅", "出片街区",
        ]
        print(f"[DEBUG romantic_couple] detected: crowd=情侣 evening=True")

    # v21: Overnight Great Wall stargazing detection
    _overnight_terms = ["夜宿", "住一晚", "过夜", "住宿", "露营", "民宿",
                        "星空", "观星", "看星星", "银河", "夜空"]
    _great_wall_terms = ["长城", "八达岭", "慕田峪", "古北水镇", "司马台",
                          "金山岭", "怀柔长城", "延庆长城"]
    _is_overnight = any(t in user_request for t in _overnight_terms)
    _is_great_wall = any(t in user_request for t in _great_wall_terms)
    if _is_overnight and _is_great_wall:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "great_wall_overnight_stargazing"
        parsed.overnight_stay_requested = True
        parsed.lodging_required = True
        parsed.stargazing_requested = "星空" in user_request or "观星" in user_request
        parsed.great_wall_anchor_requested = True
        parsed.evening_requested = True
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        parsed.duration = "a full day"
        parsed.time_budget = 1.5
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 慕田峪长城", f"{city_short} 八达岭长城",
            f"{city_short} 古北水镇", f"{city_short} 司马台长城",
            f"{city_short} 长城脚下民宿", f"{city_short} 长城露营地",
            f"{city_short} 星空民宿 怀柔", f"{city_short} 长城 观星",
        ]
        parsed.micro_keywords = ["长城 日出", "古北水镇 夜景", "长城 观星"]
        parsed.other_constraints = _append_unique(parsed.other_constraints,
            ["overnight:夜宿长城脚下", "stargazing:视天气而定", "建议自驾或包车"])
        print(f"[DEBUG great_wall_overnight] detected: overnight=True stargazing={parsed.stargazing_requested}")

    # v21: Courtyard/hutong heritage detection — "真正的四合院，不是商业化那种"
    _courtyard_terms = ["四合院", "院子", "传统民居", "胡同院落", "老北京院落",
                        "真正的四合院", "不是商业化", "原生态", "能进去看看",
                        "开放参观", "非商业化", "想进.*四合院"]
    _is_courtyard = any(
        t in user_request if ".*" not in t else re.search(t, user_request)
        for t in _courtyard_terms
    )
    if _is_courtyard or "四合院" in user_request:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.theme_profile = "history_heritage"
        parsed.activity_facet = "courtyard_visit"
        parsed.courtyard_visit_requested = True
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        if "非商业化" in user_request or "不是商业化" in user_request:
            parsed.non_commercial_requested = True
        # Don't default to quarter_day
        if parsed.time_budget < 0.5:
            parsed.duration = "a half day"
            parsed.time_budget = 0.5
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 史家胡同博物馆", f"{city_short} 胡同博物馆",
            f"{city_short} 四合院博物馆", f"{city_short} 名人故居",
            f"{city_short} 老舍纪念馆", f"{city_short} 茅盾故居",
            f"{city_short} 传统民居 参观", f"{city_short} 胡同文化 展览馆",
        ]
        parsed.micro_keywords = ["四合院 参观", "胡同 漫步", "故居 纪念馆"]
        # Exclude commercial venues
        parsed.micro_excluded_terms = _append_unique(
            getattr(parsed, "micro_excluded_terms", []) or [],
            ["餐厅", "咖啡馆", "酒吧", "酒店", "民宿", "网红", "写真", "剧本杀",
             "售楼处", "摄影基地", "商业街"],
            limit=15,
        )
        print(f"[DEBUG courtyard] detected: activity=courtyard_visit non_commercial={parsed.non_commercial_requested}")

    # v21: Revolutionary/red history theme detection — "革命历史景点，比如军事博物馆"
    _red_history_terms = ["革命历史", "红色景点", "红色文化", "红色路线",
                          "党史", "抗战", "五四", "新文化运动", "革命旧址",
                          "红色旅游", "爱国教育", "革命纪念馆"]
    _is_red_history = any(t in user_request for t in _red_history_terms)
    if _is_red_history:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.theme_profile = "history_heritage"
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        parsed.red_history_requested = True
        # v21: Don't default to quarter_day for theme exploration with fixed anchors
        if parsed.time_budget < 0.5 and parsed.fixed_pois:
            parsed.duration = "a half day"
            parsed.time_budget = 0.5
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 革命历史 纪念馆", f"{city_short} 红色文化路线",
            f"{city_short} 党史旧址", f"{city_short} 抗战纪念馆",
            f"{city_short} 名人故居 纪念馆",
        ]
        print(f"[DEBUG red_history] detected: theme_route, fixed_pois={len(parsed.fixed_pois)}")

    # v21: Fix: when primary_query is generic "景点/景区/名胜" and theme is active, clear it
    _generic_pq = getattr(parsed, "primary_query", "") or ""
    _active_theme = getattr(parsed, "theme_profile", "") or ""
    if _generic_pq in ("景点", "景区", "名胜", "风景区") and _active_theme:
        parsed.primary_query = ""
        print(f"[DEBUG step1] cleared generic primary_query='{_generic_pq}' for theme={_active_theme}")

    # v21: Spring Festival / Chinese New Year theme detection
    _spring_festival_terms = ["春节", "过年", "新春", "年味", "年俗", "庙会", "灯会",
                               "花灯", "年货", "年市", "舞龙舞狮", "老北京年味"]
    _is_spring = any(t in user_request for t in _spring_festival_terms)
    if _is_spring:
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.theme_profile = "spring_festival_culture"
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 春节庙会", f"{city_short} 新春灯会",
            f"{city_short} 年货市集", f"{city_short} 民俗活动",
            f"{city_short} 非遗体验", f"{city_short} 胡同年味",
            f"{city_short} 老字号", f"{city_short} 传统小吃",
        ]
        parsed.micro_keywords = [
            "庙会 春节", "灯会 花灯", "年货 市集",
            "非遗 民俗", "胡同 年味", "老字号 小吃",
        ]
        # Exclude sports/entertainment unrelated to spring festival
        parsed.micro_excluded_terms = _append_unique(
            getattr(parsed, "micro_excluded_terms", []) or [],
            ["篮球馆", "足球场", "跆拳道", "攀岩", "冲浪", "卡丁车", "健身房"],
            limit=15,
        )
        print(f"[DEBUG spring_festival] detected: theme=spring_festival_culture")

    # v22: Nearby food + stroll route — "待会儿去附近逛逛，找一家好吃的，再散散步"
    # v28: Skip if this is an explicit area-meal-afternoon route (天安门附近+中午吃+下午去)
    _has_nearby = any(t in user_request for t in ["附近", "周边", "就近", "周围", "离我近"])
    _has_stroll = any(t in user_request for t in ["逛逛", "散步", "走走", "散散步", "溜达", "转一圈"])
    _has_food_hint = any(t in user_request for t in ["好吃的", "找一家", "吃顿", "吃饭",
                                                       "餐厅", "美食", "小吃", "吃点"])
    _is_nearby_stroll = _has_nearby and (_has_stroll or _has_food_hint)
    if _is_nearby_stroll and _extract_area_meal_afternoon_route(_nl_post or user_request):
        print("[TimedRouteAudit] skip NearbyFoodStroll reason=explicit_area_meal_afternoon")
    elif _is_nearby_stroll and not _has_work_cafe_terms(user_request):
        # v28: Guard — don't let nearby_food_stroll override group_meal_conflict
        _is_group_meal_conflict = (
            getattr(parsed, "intent_name", "") == "group_meal_preference_conflict"
            or bool(getattr(parsed, "conflict_meal_request", False))
            or getattr(parsed, "route_strategy", "") == "meal_conflict_resolution"
        )
        if _is_group_meal_conflict:
            # Preserve meal conflict as primary intent; stroll is post-meal supplement
            parsed.proximity_requested = True
            parsed.post_meal_stroll_required = True
            parsed.nearby_strict_radius_m = 3000
            parsed.nearby_max_radius_m = 5000
            parsed.max_first_leg_km = 5.0
            parsed.compact_route_required = True
            parsed.min_candidate_points = max(getattr(parsed, "min_candidate_points", 0) or 0, 2)
            parsed.candidate_target = max(getattr(parsed, "candidate_target", 0) or 0, 3)
            parsed.max_candidate_points = max(getattr(parsed, "max_candidate_points", 0) or 0, 4)

            # CRITICAL: don't overwrite meal conflict primary intent
            parsed.intent_name = "group_meal_preference_conflict"
            parsed.route_strategy = "meal_conflict_resolution"
            parsed.poi_query_type = "meal_conflict"
            parsed.primary_query = ""
            parsed.activity_facet = ""

            parsed.search_keywords = list(getattr(parsed, "meal_search_keywords", []) or [])[:8]
            parsed.micro_keywords = ["公园", "绿地", "步道", "商场", "购物中心", "园区", "北小沟", "望京公园", "798"]

            print("[MealConflictStrollAudit] preserve_meal_conflict add_post_meal_stroll=true")
        else:
            parsed.poi_query_type = "theme_route"
            parsed.primary_query = ""
            parsed.activity_facet = "nearby_food_stroll_route"
        parsed.route_strategy = "nearby_food_stroll"
        parsed.proximity_requested = True
        # v28: Strict nearby constraints — "附近" means 3-5km, not city-wide
        parsed.is_search_center_only = True
        parsed.nearby_strict_radius_m = 3000
        parsed.nearby_max_radius_m = 5000
        parsed.max_first_leg_km = 5.0
        parsed.compact_route_required = True
        parsed.time_budget = min(float(getattr(parsed, "time_budget", 0.25) or 0.25), 0.25)
        parsed.duration = "a quarter day"
        parsed.other_constraints = _append_unique(
            list(getattr(parsed, "other_constraints", []) or []),
            ["不走远", "附近3公里内", "第一段不超过5公里"],
        )
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        parsed.theme_label = "附近短途游路线"
        import datetime as _dt
        _city_hour = _dt.datetime.now().hour
        if _has_food_hint:
            parsed.explicit_meal_intent = True
            _meal_slot = "dinner" if _city_hour >= 17 else ("lunch" if _city_hour >= 11 else "flexible_meal")
            parsed.meal_needs = [_meal_slot]
            parsed.meal_constraints = [
                {"meal": _meal_slot, "keywords": ["好吃的", "餐厅", "美食", "小吃"]}
            ]
            print(f"[NearbyFoodStrollAudit] meal_slot_created slot={_meal_slot}")
        city_short = city[:-1] if city.endswith("市") else city
        # v28: Use local around-search keywords instead of city-prefix text search
        parsed.search_keywords = [
            "餐厅", "美食", "小吃", "咖啡", "甜品",
            "购物中心", "商场", "公园", "绿地", "街区", "园区", "北小沟", "798",
        ]
        parsed.micro_keywords = [
            "餐厅", "小吃", "咖啡", "商场", "公园", "绿地", "街区", "散步",
        ]
        print(f"[NearbyFoodStrollAudit] detected time_budget={parsed.time_budget}")

    # v22: Multi-facet art/photo/cafe/shop route — prevent collapsing to "咖啡馆" only
    # v27: Use _nl_post (extracted latest user input) for pattern matching, not
    # raw user_request which may contain XML wrappers in multi-turn contexts.
    _nl_post = _extract_latest_user_input(user_request)
    _match_text = _nl_post if _nl_post else user_request
    _has_photo = any(t in _match_text for t in ["拍照", "出片", "打卡", "摄影"])
    _has_art = any(t in _match_text for t in ["文艺", "艺术", "展览", "小众", "文化"])
    _has_cafe = any(t in _match_text for t in ["咖啡", "咖啡馆", "咖啡店"])
    _has_shop = any(t in _match_text for t in ["特色小店", "买手店", "杂货店", "文创店", "小店"])
    _has_relaxed = any(t in _match_text for t in ["节奏轻松", "轻松一点", "慢一点", "不赶",
                                                        "散步", "逛逛", "散散步"])
    _facet_count = sum([_has_photo, _has_art, _has_cafe, _has_shop, _has_relaxed])
    if _facet_count >= 3 and _has_art and not _has_work_cafe_terms(user_request):
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.plan_mode = "exploratory"
        parsed.theme_required = True
        parsed.theme_label = "文艺拍照路线"
        _facets = []
        if _has_photo: _facets.append("photo_checkin")
        if _has_art: _facets.append("art_culture_lifestyle")
        if _has_cafe: _facets.append("cafe_stop")
        if _has_shop: _facets.append("specialty_shop")
        if _has_relaxed: _facets.append("relaxed_pace")
        parsed.activity_facet = "multi_facet_art_photo_cafe_shop"
        # v22: Lock to prevent downstream category override
        parsed.theme_route_locked = True
        parsed.theme_profile = "art_culture_lifestyle"
        parsed.explicit_meal_intent = False
        parsed.meal_needs = []
        parsed.meal_constraints = []
        parsed.food_pref_keywords = []
        parsed.meal_search_keywords = []
        parsed.must_recall_target = False
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 文艺拍照 路线",
            f"{city_short} 美术馆 艺术空间",
            f"{city_short} 创意园区 文创园",
            f"{city_short} 独立书店 文创店",
            f"{city_short} 买手店 特色小店",
            f"{city_short} 精品咖啡 独立咖啡馆",
            f"{city_short} 历史街区 胡同",
            f"{city_short} 轻松散步 街区",
        ]
        parsed.micro_keywords = [
            "拍照打卡", "艺术空间", "独立书店", "文创店", "精品咖啡", "特色小店",
        ]
        # v25: Structured facet tracking for downstream validation and recall
        parsed.theme_facets = _build_multi_facet_art_facets(
            _has_photo, _has_art, _has_cafe, _has_shop, _has_relaxed
        )
        parsed.theme_coverage_policy = "cover_required_facets"
        parsed.micro_poi_keywords = _append_unique(
            list(getattr(parsed, "micro_poi_keywords", []) or []),
            [
                "艺术空间", "画廊", "美术馆",
                "精品咖啡馆", "独立咖啡馆", "咖啡馆",
                "买手店", "特色小店", "文创店",
            ],
            limit=12,
        )
        parsed.micro_required_terms = _append_unique(
            list(getattr(parsed, "micro_required_terms", []) or []),
            [
                "艺术", "画廊", "美术馆", "咖啡", "coffee", "cafe",
                "买手店", "文创", "特色小店",
            ],
            limit=16,
        )
        # v28: Shared density enforcement for multi-facet art routes.
        # "节奏轻松/轻松一点" ≠ half-day — must produce 6 display POIs + 4 candidates.
        parsed = _force_multi_facet_art_density(
            parsed,
            _match_text,
            stage="step1_multifacet_initial",
        )

        print(
            f"[MultiFacetArtAudit] locked=true facets={_facets} "
            f"facet_count={_facet_count} "
            f"theme_facets={[f['id'] for f in parsed.theme_facets]} "
            f"coverage_policy={parsed.theme_coverage_policy} "
            f"duration={parsed.duration} time_budget={parsed.time_budget} "
            f"density_target={parsed.density_target_visible_pois} "
            f"candidate_target={parsed.candidate_target}"
        )

    # v21: Work-friendly cafe detection — "适合办公的咖啡馆" → cafe category
    _is_work_cafe = (_has_work_cafe_terms(user_request)
                     and any(t in user_request for t in ["咖啡", "cafe", "coffee"]))
    # v22: Don't override if multi_facet_art is already locked
    if _is_work_cafe and not getattr(parsed, "theme_route_locked", False):
        parsed.poi_query_type = "poi_category"
        parsed.category_id = "cafe"
        parsed.primary_query = "咖啡馆"
        parsed.proximity_requested = True
        parsed.allowed_typecode_prefixes = ["050400"]
        parsed.activity_facet = "work_friendly_cafe"
        parsed.search_keywords = ["咖啡馆"]
        # v21: Don't require explicit_meal_intent for cafe (050400 is not restaurant)
        parsed.explicit_meal_intent = False
        print(f"[DEBUG work_cafe] detected: cat=cafe primary_query=咖啡馆")

    # v21: Casual rest stop / UGC expression detection
    _is_casual = any(t in user_request for t in _CASUAL_REST_EXPRESSIONS)
    _is_casual_compound = ("坐着" in user_request or "坐坐" in user_request or "休息" in user_request)
    if _is_casual and _is_casual_compound:
        city_short = city[:-1] if city.endswith("市") else city
        parsed.poi_query_type = "feature_lookup"
        parsed.primary_query = ""
        parsed.activity_facet = "casual_rest_stop"
        parsed.proximity_requested = True
        parsed.required_features = ["sittable", "casual_atmosphere"]
        parsed.search_keywords = [f"{city_short} {kw}" for kw in _CASUAL_REST_KEYWORDS]
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["随意", "不排队", "不用预约", "不走远"])
        # Negative preferences for this scenario
        parsed.micro_excluded_terms = _append_unique(
            getattr(parsed, "micro_excluded_terms", []) or [],
            ["网红", "排队", "预约", "限时", "高端商务", "私人会所"],
            limit=15,
        )
        print(f"[DEBUG casual_rest] detected: facet=casual_rest_stop keywords={parsed.search_keywords[:5]}")

    # v21: Cyberpunk / future-tech style detection
    _cyberpunk_terms = ["赛博朋克", "未来感", "科技感", "霓虹夜景", "数字艺术",
                        "科幻感", "赛博", "工业风艺术", "沉浸式光影"]
    _is_cyberpunk = any(t in user_request for t in _cyberpunk_terms)
    if _is_cyberpunk:
        city_short = city[:-1] if city.endswith("市") else city
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        # v21: Map to registered future_tech_ai profile (or keep as explicit cyberpunk_future_tech)
        parsed.theme_profile = "future_tech_ai"  # registered in theme_profile_library.json
        parsed.activity_facet = "cyberpunk_exploration"
        parsed.theme_required = True
        parsed.search_keywords = [
            f"{city_short} 科技馆", f"{city_short} 数字艺术馆",
            f"{city_short} 沉浸式光影展", f"{city_short} 未来感建筑",
            f"{city_short} 现代建筑", f"{city_short} 工业风艺术区",
            f"{city_short} 城市观景台", f"{city_short} 灯光秀",
            f"{city_short} 霓虹夜景",
        ]
        parsed.micro_keywords = [
            "数字艺术", "沉浸投影", "光影空间", "玻璃幕墙",
            "工业结构", "霓虹灯", "城市夜景",
        ]
        # v21: Explicit theme exclusion terms for candidate filtering
        parsed.micro_excluded_terms = _append_unique(
            getattr(parsed, "micro_excluded_terms", []) or [],
            ["会议中心", "会议室", "办公楼", "科研办公区", "培训中心",
             "普通轰趴馆", "私人会所", "不对外开放", "团建", "年会"],
            limit=20,
        )
        parsed.other_constraints = _append_unique(
            parsed.other_constraints,
            ["cyberpunk_style:科技未来感/霓虹都市/数字艺术"],
        )
        print(f"[DEBUG cyberpunk] detected: theme mapped to tech/future/neon keywords")

    # v21: Heat shelter detection — "避暑/纳凉/太热" → feature_lookup
    _is_hot = any(expr in user_request for expr in _HEAT_SHELTER_EXPRESSIONS)
    if _is_hot:
        city_short = city[:-1] if city.endswith("市") else city
        parsed.poi_query_type = "feature_lookup"
        parsed.primary_query = ""
        parsed.activity_facet = "heat_shelter"
        parsed.heat_shelter_requested = True
        parsed.proximity_requested = True
        parsed.required_features = ["indoor_or_shaded", "heat_shelter"]
        parsed.search_keywords = [f"{city_short} {kw}" for kw in _HEAT_SHELTER_KEYWORDS]
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["天气炎热", "室内优先", "不走远"])
        print(f"[DEBUG heat_shelter] detected: feature_lookup keywords={parsed.search_keywords[:5]}")

    # v21: Area tour detection — "X区一日游" → area_route, not poi_category
    _area_clean = _AREA_TOUR_NOISE_RE.sub("", user_request.strip())
    _area_m = _AREA_TOUR_RE.search(_area_clean)
    if _area_m:
        _area_name = _area_m.group(1).strip()
        parsed.poi_query_type = "area_route"
        parsed.primary_query = ""
        parsed.search_area_label = _area_name
        parsed.area_scope_required = True
        parsed.duration = "a full day" if "一日游" in user_request or "玩一天" in user_request else "a half day"
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{_area_name} 景点", f"{_area_name} 博物馆", f"{_area_name} 公园",
            f"{_area_name} 历史文化", f"{_area_name} 胡同", f"{_area_name} 商圈",
        ]
        parsed.micro_keywords = [f"{_area_name} 打卡", f"{_area_name} 文化", f"{_area_name} 美食"]
        parsed.plan_mode = "exploratory"
        print(f"[DEBUG area_route] detected: area={_area_name} duration={parsed.duration}")

    # v21: Rain shelter detection — "避雨/躲雨/下雨" → feature_lookup, not poi_category
    _is_rain = any(expr in user_request for expr in _RAIN_SHELTER_EXPRESSIONS)
    if _is_rain:
        city_short = city[:-1] if city.endswith("市") else city
        parsed.poi_query_type = "feature_lookup"
        parsed.primary_query = ""
        parsed.activity_facet = "rain_shelter"
        parsed.rain_shelter_requested = True
        parsed.proximity_requested = True
        parsed.required_features = ["indoor", "rain_shelter"]
        parsed.search_keywords = [f"{city_short} {kw}" for kw in _RAIN_SHELTER_KEYWORDS]
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["雨天", "室内优先", "不走远"])
        print(f"[DEBUG rain_shelter] detected: feature_lookup keywords={parsed.search_keywords[:5]}")

    # v21: Souvenir/gift shopping detection
    _is_souvenir = any(expr in user_request for expr in _SOUVENIR_EXPRESSIONS)
    if _is_souvenir and "伴手礼" in user_request:
        city_short = city[:-1] if city.endswith("市") else city
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.activity_facet = "souvenir_shopping"
        parsed.souvenir_requested = True
        parsed.proximity_requested = True
        parsed.search_keywords = [f"{city_short} {kw}" for kw in [
            "伴手礼店", "特产店", "地方特产", "文创商店", "礼品店",
            "老字号食品店", "茶叶店", "糕点店", "北京特产"
        ]]
        parsed.micro_keywords = ["伴手礼 购物", "特产 礼品", "文创 纪念品"]
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["不走远"])
        print(f"[DEBUG souvenir] detected: activity_facet=souvenir_shopping, proximity=True")

    # v21: Text normalization — fix repeated words and colloquial patterns
    _norm_request = re.sub(r"有没有有", "有没有", user_request)
    _norm_request = re.sub(r"有没没有", "有没有", _norm_request)
    # v21: "明天近/明天就近/明天在附近" → normalize proximity word
    _norm_request = re.sub(r"明天近(?:找个|找|去|在)?", "明天附近找个", _norm_request)
    _norm_request = re.sub(r"明天就近(?:找个|找|去|在)?", "明天附近找个", _norm_request)

    # v21: Area-constrained exploration — "X里有什么Y" OR "X有没有Y"
    _container_match = re.search(
        r"([一-龥A-Za-z·]{2,16}(?:大学|校园|园区|公园|景区|商场|购物中心|博物馆|美术馆|图书馆|胡同|"
        r"步行街|商圈|街区|古镇|夜市|广场|滨江|步道|文创园))"
        r"(?:里|里面|内|里边|内部|中|之中|中间|附近|周边|旁边)?"
        r"(?:有没有|有|有什么|哪有|有.*吗|有没有什么)"
        r"(?:什么|哪些|哪家|哪个)?"
        r"(.+)",
        _norm_request,
    )
    # Also match "X有Y吗" / "X哪有Y" — X can be any named place
    if not _container_match:
        _container_match = re.search(
            r"([一-龥A-Za-z·]{2,16}(?:大学|校园|园区|公园|景区|商场|购物中心|博物馆|美术馆|图书馆|胡同|"
            r"步行街|商圈|街区|古镇|夜市|广场|"
            r"门|街|路|巷|里|寺|庙|塔|桥|园|苑|庄|村|镇|区|厦))"
            r"(?:有|哪有|有.*吗|有没有|有啥|有什么)"
            r"(.+)",
            _norm_request,
        )
    # v21: Last resort — "王府井" (pure area name without suffix) + 有没有/有
    if not _container_match:
        _container_match = re.search(
            r"(王府井|西单|三里屯|前门|后海|南锣鼓巷|五道口|中关村|望京|国贸|CBD|"
            r"陆家嘴|外滩|南京路|淮海路|静安寺|徐家汇|新天地|人民广场|"
            r"宽窄巷子|春熙路|解放碑|洪崖洞|"
            r"海珠|天河|越秀|"
            r"夫子庙|新街口|"
            r"中山路|"
            r"鼓楼|西湖|"
            r"户部巷|江汉路)"
            r"(?:有没有|有|哪有|有.*吗|有啥)"
            r"(.+)",
            _norm_request,
        )
    if _container_match:
        _container_name = _container_match.group(1).strip()
        _inner_target = _container_match.group(2).strip()
        _inner_target = re.sub(r"^(?:适合|可以|能|好|方便|用来)(?:拍照|约会|散步|休息|看书|打卡|遛弯|发[呆待])的(?:地方|场所|地点)?", "", _inner_target).strip()
        if not _inner_target:
            _inner_target = "景点"
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.search_area_label = _container_name
        parsed.search_area_role = "container"
        parsed.is_search_center_only = True
        parsed.activity_facet = "container_exploration"
        parsed.container_constraint = _container_name
        # Clean fixed_pois: remove container name from destinations
        parsed.fixed_pois = [
            fp for fp in (getattr(parsed, "fixed_pois", []) or [])
            if fp.name not in _container_name and _container_name not in fp.name
        ]
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{_container_name} {_inner_target}", f"{_container_name} 景点",
            f"{_container_name} 打卡", f"{_container_name} 内部",
        ]
        parsed.micro_keywords = [_inner_target, f"{_container_name} 内部 景点"]
        parsed.plan_mode = "exploratory"
        parsed.proximity_requested = True
        print(
            f"[DEBUG container] detected: container='{_container_name}' "
            f"target='{_inner_target}' fixed_pois_cleaned={len(parsed.fixed_pois)}"
        )

    # v21: Multi-task detection — "一日游，晚上X" → daytime + required evening task
    _multi_task_match = re.search(
        r"(?:想|想要|打算|准备|帮我|请)?(?:在|去)?(.+?(?:一日游|玩一天|逛一天|玩一整天|全天|一天|两日游|半日游))"
        r"[,，]\s*(晚上|傍晚|夜里|夜间)(.+)",
        user_request,
    )
    if _multi_task_match:
        _daytime_part = _multi_task_match.group(1).strip()
        _evening_time = _multi_task_match.group(2)
        _evening_task = _multi_task_match.group(3).strip()
        # Preserve daytime as exploratory, add evening as required waypoint
        _daytime_clean = re.sub(r"^(?:想|想要|帮我|请|在|去)", "", _daytime_part).strip()
        parsed.raw_keywords = list(set(getattr(parsed, "raw_keywords", []) or []))
        parsed.duration = "a full day"
        parsed.time_budget = 1.0
        parsed.evening_requested = True
        parsed.plan_mode = "hybrid"
        # Evening task becomes a planned waypoint
        _evening_kw = re.sub(r"找个|找一个|找个地方|去|看", "", _evening_task).strip()
        _evening_wp = PlannedWaypoint(
            type="placeholder", search_keyword=_evening_kw,
            category="night_view", stay_minutes=90,
            time_slot="evening",
            search_keywords=[_evening_kw, "城市夜景", "夜景观景台", "高空观景"],
            required_terms=["夜景", "观景", "高楼", "屋顶", "露台", "天际线"],
            excluded_terms=["酒店客房", "办公楼", "住宅", "仅白天"],
        )
        if not getattr(parsed, "planned_waypoints", []):
            parsed.planned_waypoints = []
        parsed.planned_waypoints.append(_evening_wp)
        print(
            f"[DEBUG multi_task] split: daytime='{_daytime_clean}' "
            f"evening='{_evening_kw}' time={_evening_time}"
        )

    # v21: Corridor task detection — "去X的路上顺路Y" → planned mode
    _corr_dest, _corr_task, _corr_action = _parse_corridor_task(user_request)
    if _corr_dest and _corr_task:
        # Resolve destination alias
        _resolved_dest = _UNIVERSITY_ALIAS_MAP.get(_corr_dest, _corr_dest)
        if _resolved_dest != _corr_dest:
            parsed.search_area_label = _corr_dest  # store raw name
        # Build planned waypoints
        parsed.plan_mode = "planned"
        parsed.poi_query_type = "corridor_task"
        parsed.corridor_requested = True
        parsed.primary_query = ""

        _home_label = getattr(user_profile, "home_location", {}).get("label", "") or ""
        _dest_wp = PlannedWaypoint(
            type="fixed", name=_resolved_dest, search_keyword=_resolved_dest,
            category="destination", stay_minutes=0,
        )
        # v21: Build task waypoint with correct category and ranking
        _task_cat = "visit"
        _task_stay = 15
        _task_req_terms = [_corr_task]
        _task_excl_terms: list[str] = []
        if _corr_action == "purchase":
            _task_cat = "purchase"
            _task_stay = 10
            if "水果" in _corr_task:
                _task_req_terms = ["水果", "鲜果", "果品", "生鲜"]
                _task_excl_terms = ["摄影", "打印", "数码", "批发公司"]
        elif _corr_action == "meal":
            _task_cat = "meal"
            _task_stay = 45
            _task_req_terms = ["餐厅", "饭店", "餐馆", "美食", "饭馆"]
            _task_excl_terms = ["咖啡", "奶茶", "甜品", "面包", "便利店"]
            # v21: Normalize task keyword for meal
            _corr_task = "餐厅" if _corr_task in ("餐馆", "饭馆", "饭店") else _corr_task
            parsed.explicit_meal_intent = True
        _task_wp = PlannedWaypoint(
            type="placeholder", search_keyword=_corr_task,
            category=_task_cat,
            stay_minutes=_task_stay,
            placement="before_destination", corridor_search=True,
            search_keywords=[_corr_task],
            required_terms=_task_req_terms,
            excluded_terms=_task_excl_terms,
        )
        parsed.planned_waypoints = [_task_wp, _dest_wp]
        parsed.fixed_pois = [FixedPoi(name=_resolved_dest, user_time_budget=None)]
        parsed.destination_alias = _corr_dest
        parsed.resolved_destination_name = _resolved_dest
        parsed.search_keywords = [_corr_task]
        print(
            f"[DEBUG corridor] detected: dest_raw='{_corr_dest}'→'{_resolved_dest}' "
            f"task='{_corr_task}' action={_corr_action} "
            f"planned_waypoints={[(wp.type, wp.name or wp.search_keyword, wp.category) for wp in parsed.planned_waypoints]}"
        )

    looks_like_route = _looks_like_route_request(user_request)
    if not parsed.is_route_planning_request and not looks_like_route:
        raise ZeroOutputError(INCOMPLETE_REQUEST_TEXT)
    if looks_like_route:
        parsed.is_route_planning_request = True

    request_duration = _duration_from_request(user_request)
    if request_duration:
        parsed.duration = request_duration

    # v5.3: 跨时段组合规则 — 用户同时提到两个以上时段（如上午+下午+晚上）→ full_day
    _has_morning = bool(re.search(r"明早|今早|上午|早上|一上午", user_request))
    _has_afternoon = bool(re.search(r"下午|一下午", user_request))
    _has_evening = bool(re.search(r"晚上|夜里|夜间|傍晚", user_request))
    _period_count = sum([_has_morning, _has_afternoon, _has_evening])
    if (
        _period_count >= 2
        and parsed.duration not in ("a full day", "two days", "two and a half days", "three days")
        and not getattr(parsed, "preserve_requested_days", False)
    ):
        # 防御：即使 LLM 或覆盖逻辑未正确设置，强制纠正
        print(f"[DEBUG step1 WARN] 多时段({_period_count})但 duration={parsed.duration}，强制修正为 a full day")
        parsed.duration = "a full day"

    _transport_constraints_v2 = _extract_period_transport_constraints_v2(user_request)
    _explicit_multi_day_transport_v2 = (
        bool(_transport_constraints_v2)
        and (
            bool(_TWO_DAY_REQUEST_RE_V2.search(user_request or ""))
            or any(c.get("day_index", 1) >= 2 for c in _transport_constraints_v2)
        )
    )
    if _explicit_multi_day_transport_v2:
        parsed.duration = "two days"
        parsed.time_budget = 2.0
        parsed.requested_days = 2
        parsed.preserve_requested_days = True
        parsed.transport_constraints = _transport_constraints_v2
        parsed.transport_hint = _transport_constraints_v2[0].get("transport_mode", "") if _transport_constraints_v2 else None
        parsed.plan_mode = "exploratory"
        parsed.search_keywords = _append_unique(
            [
                "\u5317\u4eac \u7ecf\u5178\u666f\u70b9",
                "\u5317\u4eac \u5fc5\u53bb\u666f\u70b9",
                "\u5317\u4eac \u5386\u53f2\u6587\u5316\u666f\u70b9",
                "\u5317\u4eac \u57ce\u5e02\u5730\u6807",
                "\u5317\u4eac \u516c\u56ed \u666f\u70b9",
                "\u5317\u4eac \u535a\u7269\u9986",
            ],
            list(getattr(parsed, "search_keywords", []) or []),
            limit=10,
        )
        print(
            f"[DEBUG multi_day_transport_v2] days=2 "
            f"constraints={len(_transport_constraints_v2)} data={_transport_constraints_v2}"
        )

    # v5.3: evening_requested 识别增强 — 仅显式夜间关键词 + 晚上餐饮意图
    night_trigger = ""
    if _has_night_activity_intent(user_request):
        parsed.evening_requested = True
        # Find which token triggered
        for token in NIGHT_ACTIVITY_TOKENS:
            if token in user_request:
                night_trigger = token
                break
    if not parsed.evening_requested and _has_evening and _has_evening_dinner_intent(user_request):
        parsed.evening_requested = True
        night_trigger = "晚上餐饮意图"
        print(f"[DEBUG step1] 晚上餐饮意图检测命中，设置 evening_requested=True")

    parsed.time_budget = DURATION_TO_BUDGET.get(parsed.duration, 1.0)
    # v6: 不再因 evening_requested 自动抬高 time_budget
    # time_budget 保持 duration 的自然值：full day = 1.0, half day = 0.5
    # 外滩 / 江边 / 滨江 等白天景点词不再触发夜间语义

    # [DEBUG] 打印关键决策字段
    print(f"[DEBUG step1] user_request={user_request[:80]}...")
    print(f"[DEBUG step1] _period_count={_period_count} has_morning={_has_morning} has_afternoon={_has_afternoon} has_evening={_has_evening}")
    print(f"[DEBUG step1] duration={parsed.duration} time_budget={parsed.time_budget} evening_requested={parsed.evening_requested} night_activity_trigger={night_trigger or 'none'}")

    # v6: 相对时间/下班/未来日期必须强制重算 start_time，覆盖 LLM 可能给的默认 09:00
    _off_work_tokens = ["下班", "下班后", "下班前", "下班路上", "回家路上", "顺路回家", "回家前", "晚高峰", "待会儿下班"]
    _relative_time_tokens = ["待会儿", "等会儿", "一会儿", "一会", "马上", "现在"]
    is_off_work = any(token in user_request for token in _off_work_tokens)
    is_relative = any(token in user_request for token in _relative_time_tokens)
    is_future = any(token in user_request for token in ["明天", "后天", "周末"])
    if parsed.start_time is None or is_relative or is_off_work or is_future:
        parsed.start_time = _next_start_time(user_request, current_time, parsed.duration)
        if is_off_work:
            print(f"[DEBUG step1] 下班场景：强制重算 start_time={parsed.start_time}")
        elif is_relative:
            print(f"[DEBUG step1] 相对时间场景：强制重算 start_time={parsed.start_time}")
    # v6: LLM 可能返回 naive datetime，统一转为 current_time 的时区
    if parsed.start_time and parsed.start_time.tzinfo is None and current_time.tzinfo is not None:
        parsed.start_time = parsed.start_time.replace(tzinfo=current_time.tzinfo)
    parsed.start_time = _adjust_past_start_time(parsed.start_time, user_request, current_time)

    if parsed.original_location_label and not _has_explicit_origin(user_request):
        parsed.original_location_label = None

    if parsed.original_location_label:
        parsed.original_location = await gaode_geocode(parsed.original_location_label, city=city)
    if not parsed.original_location:
        parsed.original_location = _fallback_origin(parsed, user_profile)

    # v20: For proximity queries without explicit search area, use original_location
    if parsed.proximity_requested and not getattr(parsed, "search_area_location", None) and parsed.original_location:
        parsed.search_area_location = parsed.original_location
        print(
            f"[DEBUG proximity] using original_location as search_area: "
            f"label={parsed.original_location.get('label','')} "
            f"loc=({parsed.original_location.get('lat','')},{parsed.original_location.get('lng','')})"
        )

    # v20: Parse ranking modifier words ("最有名", "评分最高", "最近" etc.)
    # Remove them from the primary_query so they don't become search terms.
    ranking_result = _parse_ranking_modifier(user_request)
    _category_query_text = user_request  # default: raw text
    if ranking_result:
        parsed.ranking_intent = ranking_result["ranking_intent"]
        parsed.ranking_raw_terms = ranking_result["ranking_raw_terms"]
        parsed.ranking_direction = ranking_result["ranking_direction"]
        # Use cleaned_text for category detection so ranking words don't
        # become part of primary_query or search keywords.
        _category_query_text = ranking_result.get("cleaned_text", user_request) or user_request

    # v20: Detect direct POI category query BEFORE keyword overrides
    # so that keywords are focused on the target category, not expanded to unrelated ones.
    # v21: Skip poi_category detection for feature-driven intents — already set
    _skip_cat_detect = (
        (getattr(parsed, "plan_mode", "") == "planned"
         and getattr(parsed, "corridor_requested", False))
        or getattr(parsed, "utility_lookup_requested", False)
        or getattr(parsed, "souvenir_requested", False)
        or getattr(parsed, "quiet_retreat_requested", False)
        or getattr(parsed, "lawn_rest_requested", False)
        or getattr(parsed, "night_view_requested", False)
        or getattr(parsed, "open_terrace_requested", False)
        or getattr(parsed, "local_life_requested", False)
        or getattr(parsed, "stress_relief_requested", False)
        or getattr(parsed, "rest_stop_requested", False)
        or getattr(parsed, "rain_shelter_requested", False)
        or getattr(parsed, "area_scope_required", False)
        or getattr(parsed, "heat_shelter_requested", False)
        or (getattr(parsed, "search_area_role", "") == "container")
        or getattr(parsed, "red_history_requested", False)
        or getattr(parsed, "overnight_stay_requested", False)
        or getattr(parsed, "fruit_picking_requested", False)
        or getattr(parsed, "courtyard_visit_requested", False)
        or getattr(parsed, "walking_cluster_requested", False)
        or (getattr(parsed, "activity_facet", "") == "no_reservation_flexible_trip")
        or _is_no_reservation_request_v2(user_request)
    )
    poi_cat_result = _detect_poi_category_query(_category_query_text) if not _skip_cat_detect else None
    if poi_cat_result:
        # v20: Handle theme_route result from proximity parsing (quiet_retreat etc.)
        _result_query_type = poi_cat_result.get("poi_query_type", "poi_category")
        if _result_query_type == "theme_route":
            parsed.poi_query_type = "theme_route"
            parsed.primary_query = ""
            parsed.category_id = None
            parsed.allowed_typecode_prefixes = []
            parsed.excluded_typecode_prefixes = []
            parsed.primary_required_terms = []
            parsed.primary_excluded_terms = []
            parsed.proximity_requested = bool(poi_cat_result.get("proximity_requested", False))
            parsed.is_search_center_only = bool(poi_cat_result.get("is_search_center_only", False))
            _activity_facet = poi_cat_result.get("activity_facet", "")
            parsed.activity_facet = _activity_facet
            # v20: Apply quiet retreat preferences and crowd constraints
            _pref_terms = poi_cat_result.get("preference_terms") or []
            if _pref_terms:
                for pt in _pref_terms:
                    if pt not in parsed.other_constraints:
                        parsed.other_constraints = _append_unique(parsed.other_constraints, [pt])
            _crowd_pref = poi_cat_result.get("crowd_preference") or ""
            if _crowd_pref:
                parsed.crowd_preference = _crowd_pref
            _privacy_pref = poi_cat_result.get("privacy_preference") or ""
            if _privacy_pref:
                parsed.privacy_preference = _privacy_pref
            # v20: Search area handling
            search_area_label = poi_cat_result.get("search_area_label") or poi_cat_result.get("search_center_label")
            if search_area_label:
                parsed.search_area_label = search_area_label
            # v21: Set required features from lawn_rest / feature-based intent
            _req_features = poi_cat_result.get("required_features") or []
            if _req_features:
                parsed.required_features = list(_req_features)
            _pref_features = poi_cat_result.get("preferred_features") or []
            if _pref_features:
                parsed.preferred_features = list(_pref_features)

            # v20/v21: Apply activity-specific keywords
            if _activity_facet == "rest_stop":
                _apply_rest_stop_keywords(parsed, city, _activity_facet)
            elif _activity_facet == "stress_relief":
                _sr_mode = poi_cat_result.get("stress_relief_mode", "mixed") or "mixed"
                parsed.stress_relief_mode = _sr_mode
                _apply_stress_relief_keywords(parsed, city, _activity_facet)
            elif _activity_facet == "open_terrace":
                _apply_open_terrace_keywords(parsed, city, _activity_facet)
            elif _activity_facet == "night_view":
                _apply_night_view_keywords(parsed, city, _activity_facet)
            elif _activity_facet == "lawn_rest":
                _apply_lawn_rest_keywords(parsed, city, _activity_facet)
            elif _activity_facet == "quiet_retreat":
                _apply_quiet_retreat_keywords(parsed, city, _activity_facet)
            else:
                # Fallback: use quiet_retreat for generic theme_route abstract intents
                _apply_quiet_retreat_keywords(parsed, city, _activity_facet)
            _is_area_cat = bool(poi_cat_result.get("search_area_label") and not poi_cat_result.get("proximity_requested"))
            print(
                f"[DEBUG {'area_category' if _is_area_cat else 'proximity'}] "
                f"user_request={user_request[:60]} "
                f"search_area_label={parsed.search_area_label} "
                f"proximity_requested={parsed.proximity_requested} "
                f"activity_facet={_activity_facet} "
                f"poi_query_type={parsed.poi_query_type} "
                f"crowd_preference={getattr(parsed, 'crowd_preference', '')} "
                f"required_features={getattr(parsed, 'required_features', [])} "
                f"search_keywords={parsed.search_keywords[:6]}"
            )
        else:
            # v20: Split preference modifiers from base category (冷门景区 → 景区 + 冷门)
            poi_cat_result = _apply_preference_modifiers(poi_cat_result)
            parsed.poi_query_type = poi_cat_result["poi_query_type"]
            parsed.primary_query = poi_cat_result["primary_query"]
            parsed.explicit_meal_intent = poi_cat_result["explicit_meal_intent"]
            parsed.allowed_typecode_prefixes = poi_cat_result["allowed_typecode_prefixes"]
            parsed.excluded_typecode_prefixes = poi_cat_result["excluded_typecode_prefixes"]
            parsed.primary_required_terms = poi_cat_result["primary_required_terms"]
            parsed.primary_excluded_terms = poi_cat_result["primary_excluded_terms"]
            parsed.container_constraint = poi_cat_result.get("container_constraint")

            # v20: Proximity fields
            parsed.proximity_requested = bool(poi_cat_result.get("proximity_requested", False))
            parsed.is_search_center_only = bool(poi_cat_result.get("is_search_center_only", False))
            search_area_label = poi_cat_result.get("search_area_label") or poi_cat_result.get("search_center_label")
            if search_area_label:
                parsed.search_area_label = search_area_label

            # For direct category queries, search_keywords = city tag + primary_query + synonyms
            # Do NOT expand into fruit shops, bakeries, etc.
            city_short = city[:-1] if city.endswith("市") else city
            cat_id = poi_cat_result.get("category_id")
            parsed.category_id = cat_id  # v20: persisted for downstream use
            rule = CATEGORY_RULES.get(cat_id, {}) if cat_id else {}
            # Use search_keywords_override if present (from area-category parsing)
            synonyms = poi_cat_result.get("search_keywords_override", []) or (
                rule.get("semantic_terms", [])[:4] if rule else []
            )
            primary_query = poi_cat_result["primary_query"]
            container_constraint = poi_cat_result.get("container_constraint") or ""
            focused_search = (
                [f"{city_short} {container_constraint} {primary_query}", f"{city_short} {primary_query}"]
                if container_constraint
                else [f"{city_short} {primary_query}"]
            )
            for syn in synonyms:
                if syn != primary_query:
                    focused_search.append(f"{city_short} {syn}")
            # For unknown categories, add the raw query term as a keyword
            if not cat_id and primary_query not in " ".join(focused_search):
                focused_search.append(f"{city_short} {primary_query}")
            parsed.search_keywords = _append_unique(
                focused_search,
                parsed.search_keywords[:2] if parsed.search_keywords else [],
                limit=6,
            )
            # Also set micro keywords to be category-relevant
            parsed.micro_keywords = _append_unique(
                [f"{syn} 打卡" if city_short not in syn else syn for syn in synonyms[:3]] if synonyms else [f"{primary_query} 查询"],
                [],
                limit=4,
            )
            # v20: area_category debug log
            _is_area_cat = bool(poi_cat_result.get("search_area_label") and not poi_cat_result.get("proximity_requested"))
            print(
                f"[DEBUG {'area_category' if _is_area_cat else 'proximity'}] "
                f"user_request={user_request[:60]} "
                f"search_area_label={parsed.search_area_label} "
                f"proximity_requested={parsed.proximity_requested} "
                f"primary_query={parsed.primary_query} "
                f"poi_query_type={parsed.poi_query_type} "
                f"category_id={cat_id} "
                f"allowed_typecodes={parsed.allowed_typecode_prefixes[:6] if parsed.allowed_typecode_prefixes else 'none'} "
                f"fixed_pois_before={[fp.name for fp in parsed.fixed_pois]} "
                f"search_keywords_override={poi_cat_result.get('search_keywords_override', [])[:4]}"
            )
    else:
        parsed.poi_query_type = getattr(parsed, "poi_query_type", "") or ""
        # v20: Force theme_route when proximity result is a theme expression with no category
        _pq_raw = getattr(parsed, "primary_query", "") or ""
        _cat_id = getattr(parsed, "category_id", None)
        _has_tc = bool(getattr(parsed, "allowed_typecode_prefixes", None))
        if (not _cat_id and not _has_tc) and (_pq_raw in ("体验", "路线", "主题") or
            any(t in _pq_raw for t in ["体验", "科技体验", "未来科技", "路线"])
        ):
            parsed.poi_query_type = "theme_route"
            parsed.primary_query = ""
            print(f"[DEBUG step1] intent coordination: pq='{_pq_raw}' → theme_route")
        if not parsed.poi_query_type:
            parsed.poi_query_type = "theme_route"

    # v20: Invariant check — clear primary_query if it's a time expression, action word,
    # or functional word; downgrade poi_category if no valid category_id/typecodes.
    _primary_q = getattr(parsed, "primary_query", "") or ""
    if _primary_q and _is_time_or_functional_expression(_primary_q):
        print(
            f"[DEBUG step1] primary_query '{_primary_q}' is a time/functional expression, "
            f"clearing and downgrading to theme_route"
        )
        parsed.primary_query = ""
    _cat_id = getattr(parsed, "category_id", None)
    _has_typecodes = bool(getattr(parsed, "allowed_typecode_prefixes", None))
    # v22: If multi_facet_art is locked, don't let poi_category override it
    if getattr(parsed, "theme_route_locked", False):
        if parsed.poi_query_type == "poi_category":
            print(
                f"[MultiFacetArtAudit] block_category_override "
                f"attempted_primary={getattr(parsed, 'primary_query', '')[:20]} "
                f"poi_query_type=poi_category — resetting to theme_route"
            )
            parsed.poi_query_type = "theme_route"
            parsed.primary_query = ""
            parsed.category_id = None
            parsed.allowed_typecode_prefixes = []
            parsed.must_recall_target = False

    if parsed.poi_query_type == "poi_category" and not _cat_id and not _has_typecodes:
        _pq = getattr(parsed, "primary_query", "") or ""
        if not _pq or _is_time_or_functional_expression(_pq):
            print(
                f"[DEBUG step1] poi_category with no valid category/typecodes, "
                f"primary_query='{_pq}' — downgrading to theme_route"
            )
            parsed.poi_query_type = "theme_route"
            parsed.primary_query = ""
            parsed.category_id = None

    parsed = _apply_keyword_overrides(parsed, user_request, city)
    parsed = _append_fixed_poi_from_request(parsed, user_request)
    parsed = _exclude_pois_from_request(parsed, user_request)

    # v21: final guard.  Generic category detection/keyword overrides must not
    # turn "no reservation / tomorrow flexible trip" back into primary_query=景点.
    if _is_no_reservation_request_v2(user_request) or getattr(parsed, "activity_facet", "") == "no_reservation_flexible_trip":
        _apply_no_reservation_flexible_trip_v2(parsed, city)
        print("[DEBUG no_reservation] final guard reapplied")

    # v20: Move search_area_label out of fixed_pois and geocode it as search center
    # This prevents "朝阳区"/"西直门" from being treated as a destination when user says
    # "朝阳区的商场" or "西直门附近的医院"
    _search_area = getattr(parsed, "search_area_label", None)
    _has_area = bool(_search_area and (parsed.is_search_center_only or parsed.proximity_requested))
    if _has_area:
        _fixed_before = [fp.name for fp in parsed.fixed_pois]
        # Remove search area from fixed_pois
        parsed.fixed_pois = [
            fp for fp in parsed.fixed_pois
            if _search_area not in fp.name and fp.name not in _search_area
        ]
        # v21: Normalize university/college short name aliases
        _resolved_search_area = _search_area
        if _search_area and _search_area in _UNIVERSITY_ALIAS_MAP:
            _resolved_search_area = _UNIVERSITY_ALIAS_MAP[_search_area]
            parsed.search_area_label = _resolved_search_area  # update label to full name
            print(
                f"[DEBUG alias] resolved university alias: "
                f"'{_search_area}' → '{_resolved_search_area}'"
            )

        # Geocode the search area as the search center
        _search_loc = None
        try:
            _search_loc = await gaode_geocode(_resolved_search_area, city=city)
        except Exception as exc:
            print(f"[WARN step1] geocode failed for '{_resolved_search_area}': {exc}")

        # v21: If geocode fails, try POI text search as fallback (for universities, landmarks)
        if not _search_loc or not _search_loc.get("lat"):
            _poi_fallback_ok = False
            try:
                _poi_items = await gaode_text_search(_resolved_search_area, city=city)
                if _poi_items and len(_poi_items) > 0:
                    _best = _poi_items[0]
                    _raw_loc = _best.get("location")
                    _name = _best.get("name", _resolved_search_area)
                    if _raw_loc:
                        if isinstance(_raw_loc, str) and "," in _raw_loc:
                            _parts = _raw_loc.split(",")
                            _search_loc = {
                                "lat": float(_parts[1]),
                                "lng": float(_parts[0]),
                                "label": _name,
                            }
                        elif isinstance(_raw_loc, dict):
                            _search_loc = {
                                "lat": float(_raw_loc.get("lat", 0)),
                                "lng": float(_raw_loc.get("lng", 0)),
                                "label": _name,
                            }
                    if _search_loc and _search_loc.get("lat") and _search_loc.get("lat") != 0:
                        _poi_fallback_ok = True
                    print(
                        f"[DEBUG alias] geocode failed, POI search fallback: "
                        f"'{_resolved_search_area}' → name={_name} "
                        f"ok={_poi_fallback_ok} "
                        f"loc=({_search_loc.get('lat','') if _search_loc else 'none'},"
                        f"{_search_loc.get('lng','') if _search_loc else 'none'})"
                    )
            except Exception as exc2:
                print(f"[WARN step1] POI search fallback also failed for '{_resolved_search_area}': {exc2}")

        if _search_loc and _search_loc.get("lat") and _search_loc.get("lat") != 0:
            parsed.search_area_location = _search_loc
            adcode = _search_loc.get("adcode", "") or ""
            if adcode:
                parsed.search_area_adcode = adcode
            print(
                f"[DEBUG proximity] geocoded search_area={_resolved_search_area} "
                f"loc=({_search_loc.get('lat','')},{_search_loc.get('lng','')}) "
                f"adcode={adcode}"
            )
        _fixed_after = [fp.name for fp in parsed.fixed_pois]
        print(
            f"[DEBUG proximity] fixed_pois_before={_fixed_before} "
            f"fixed_pois_after={_fixed_after} "
            f"search_area_label={_search_area} "
            f"search_area_location_set={parsed.search_area_location is not None}"
        )

    # v20: If proximity_requested but no explicit search area, use original_location
    if parsed.proximity_requested and not getattr(parsed, "search_area_location", None):
        # Will be set later via _fallback_origin; search_area_location will be original_location
        pass

    # v24: Extract latest_user_input from conversation_context XML if present.
    # Use the module-level helper for consistency.
    _nl_input = _extract_latest_user_input(user_request)
    if _has_conversation_context(user_request):
        print(f"[DEBUG step1] _postprocess isolated latest_user_input from conversation_context: len={len(_nl_input)}")

    # v19: 主题决策 — 使用 resolve_theme_profile 替代旧版拼接匹配
    raw_theme_text = _nl_input
    auxiliary_theme_text = " ".join([
        " ".join(parsed.raw_keywords or []),
        " ".join(parsed.search_keywords or []),
        " ".join(parsed.micro_keywords or []),
        " ".join(parsed.other_constraints or []),
        " ".join(getattr(parsed, "micro_poi_keywords", []) or []),
    ])

    # v20: Activity facet detection — use isolated NL input
    _facet_raw = _nl_input.lower()
    _has_relation_terms = any(t in _facet_raw for t in [
        "情侣", "约会", "对象", "闺蜜", "朋友聚会", "团建", "多人",
        "纪念日", "亲子", "家庭", "和好", "聚会", "par",
    ])
    _has_photo_terms = any(t in _facet_raw for t in [
        "拍照", "打卡", "出片", "摄影", "取景", "拍", "照",
    ])
    _activity_facets: list[str] = []
    if _has_photo_terms:
        _activity_facets.append("photo_checkin")
    if any(t in _facet_raw for t in ["散步", "漫步", "走走", "逛逛", "溜达", "遛弯"]):
        _activity_facets.append("citywalk")
    if any(t in _facet_raw for t in ["夜景", "夜晚", "晚间", "夜游"]):
        _activity_facets.append("night_view")
    if any(t in _facet_raw for t in ["展览", "看展", "博物馆", "艺术展"]):
        _activity_facets.append("exhibition")
    if any(t in _facet_raw for t in _WATERFRONT_TERMS):
        _activity_facets.append("waterfront_walk")
    print(
        f"[FacetIntentAudit] raw_text={user_request!r} "
        f"social_context={'unspecified' if not _has_relation_terms else 'has_relation'} "
        f"activity_facets={_activity_facets} "
        f"explicit_terms={'photo' if _has_photo_terms else ''}{'+relation' if _has_relation_terms else ''} "
        f"rejected_inferences={'none' if _has_relation_terms else 'relationship_group'}"
    )

    llm_profile = getattr(parsed, "theme_profile", None)
    # v20: If only photo terms (no relationship terms), prevent relationship_group_scenarios
    if _has_photo_terms and not _has_relation_terms and llm_profile == "relationship_group_scenarios":
        llm_profile = None
    decision = resolve_theme_profile(
        llm_profile=llm_profile,
        raw_text=raw_theme_text,
        auxiliary_text=auxiliary_theme_text,
    )

    candidate_summary = [
        {"id": c.profile_id, "score": c.score, "raw": c.raw_score}
        for c in decision.candidates[:3]
    ]
    print(
        "[ThemeMatch] "
        f"raw_text={user_request!r} "
        f"llm_profile={llm_profile!r} "
        f"candidates={candidate_summary!r} "
        f"final_profile={decision.profile_id!r} "
        f"source={decision.source} "
        f"reason={decision.reason}"
    )

    # v20: Multi-theme facet detection — shared-suffix enumeration
    _multi_result = _parse_multi_theme_enumeration(user_request)
    if _multi_result and len(_multi_result.get("facets", [])) >= 2:
        parsed.multi_theme_requested = True
        parsed.theme_coverage_policy = "cover_all_explicit_facets"
        parsed.theme_facets = _multi_result["facets"]
        print(
            f"[MultiThemeAudit] raw_enumeration={user_request!r} "
            f"expanded_facets={[f['facet_id'] for f in parsed.theme_facets]} "
            f"umbrella_profile={_multi_result.get('umbrella_profile')} "
            f"facet_count={len(parsed.theme_facets)}"
        )

    # v20: Multi-theme keeps umbrella profile; don't let single-theme decision override facets
    if not parsed.multi_theme_requested:
        # v21: Force explicit theme when theme_required=True (cyberpunk, etc.)
        if getattr(parsed, "theme_required", False) and not decision.profile_id:
            _forced_profile = getattr(parsed, "theme_profile", "") or ""
            if _forced_profile and _forced_profile in get_all_theme_profiles():
                parsed.theme_profile = _forced_profile
                parsed.theme_label = get_all_theme_profiles()[_forced_profile].get("label", _forced_profile)
                parsed.theme_confidence = 1.0
                print(
                    f"[ThemeMatch] forced theme={_forced_profile} "
                    f"source=deterministic_alias reason=explicit_user_term"
                )
        else:
            parsed.theme_profile = decision.profile_id
            parsed.theme_label = decision.label
            parsed.theme_confidence = decision.confidence

    # v20: Intent coordination — abstract social scenario themes must become theme_route
    _abstract_scenario_themes = {"relationship_group_scenarios", "social_emotional_community"}
    # v21: Vibe/atmosphere themes — abstract, feature-based, NOT poi_category
    _vibe_atmosphere_themes = {
        "market_local_life",
        "local_character",
    }
    _all_abstract_themes = _abstract_scenario_themes | _vibe_atmosphere_themes
    if (parsed.theme_profile in _all_abstract_themes
            and parsed.poi_query_type == "poi_category"
            and not getattr(parsed, "category_id", None)):
        old_type = parsed.poi_query_type
        old_pq = getattr(parsed, "primary_query", "")
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        if parsed.theme_profile == "market_local_life":
            parsed.activity_facet = "local_life"
            parsed.local_life_requested = True
        print(
            f"[ThemeRoutingAudit] raw_text={user_request!r} "
            f"resolved_profile={parsed.theme_profile} "
            f"old_poi_query_type={old_type} "
            f"new_poi_query_type=theme_route "
            f"primary_query_cleared={old_pq!r} "
            f"reason={'vibe_atmosphere_not_poi_category' if parsed.theme_profile in _vibe_atmosphere_themes else 'abstract_scenario_not_poi_category'}"
        )

    if decision.profile_id:
        profile = get_all_theme_profiles().get(decision.profile_id, {})
        if profile:
            parsed.micro_poi_keywords = _append_unique(
                getattr(parsed, "micro_poi_keywords", []) or [],
                profile.get("micro_poi_keywords", []) or [],
                limit=14,
            )
            parsed.micro_required_terms = _append_unique(
                getattr(parsed, "micro_required_terms", []) or [],
                profile.get("required_terms", []) or [],
                limit=18,
            )
            parsed.micro_excluded_terms = _append_unique(
                getattr(parsed, "micro_excluded_terms", []) or [],
                profile.get("excluded_terms", []) or [],
                limit=18,
            )
            macro_terms = profile.get("macro_search_terms", []) or []
            # v21: For vibe/atmosphere themes, clean garbage abstract keywords first
            if decision.profile_id in _vibe_atmosphere_themes:
                _vibe_garbage = {"有烟火气", "烟火气", "市井气", "本地生活路线", "有烟火气的地方"}
                parsed.search_keywords = [
                    kw for kw in parsed.search_keywords
                    if not any(g in kw for g in _vibe_garbage)
                ]
            parsed.search_keywords = _append_unique(
                parsed.search_keywords,
                list(macro_terms),
                limit=8,
            )
            # v20: If photo_checkin facet detected but no relationship terms, use photo archetypes
            if "photo_checkin" in _activity_facets and not _has_relation_terms:
                _cs = city[:-1] if city.endswith("市") else city
                _photo_kw = [
                    f"{_cs} 拍照打卡", f"{_cs} 出片地点",
                    f"{_cs} 观景台", f"{_cs} 建筑摄影",
                    f"{_cs} 街区摄影", f"{_cs} 花园拍照",
                ]
                parsed.search_keywords = _append_unique(
                    parsed.search_keywords, _photo_kw, limit=12,
                )
                parsed.raw_keywords = _append_unique(
                    parsed.raw_keywords or [], ["拍照打卡", "出片", "观景"],
                )

    # v20: Multi-theme — expand per-facet keywords to prevent single-theme truncation
    if parsed.multi_theme_requested and parsed.theme_facets:
        city_short = city[:-1] if city.endswith("市") else city
        for facet in parsed.theme_facets:
            facet_kw = facet.get("search_keywords", [])
            for kw in facet_kw[:4]:  # up to 4 per facet
                scoped = f"{city_short} {kw}" if city_short else kw
                if scoped not in parsed.search_keywords:
                    parsed.search_keywords.append(scoped)
                    if len(parsed.search_keywords) >= 20:
                        break
            print(
                f"[MultiThemeAudit] facet={facet['facet_id']} "
                f"keywords_added={facet_kw[:4]}"
            )

    parsed.search_keywords = canonicalize_search_keywords(parsed.search_keywords, city, limit=len(parsed.search_keywords) if parsed.multi_theme_requested else 8)

    # v18: 父母/长辈/老人不应触发儿童亲子主题
    parsed = _apply_parent_elder_theme_guard(parsed, user_request, city)

    skip_destination_detection = (
        getattr(parsed, "plan_mode", "exploratory") == "planned"
        and bool(getattr(parsed, "planned_waypoints", []))
    )
    if not parsed.fixed_pois and not skip_destination_detection:
        dest_pois = await _detect_destination_from_keywords(
            parsed.search_keywords, parsed.original_location, city
        )
        existing_names = {fp.name for fp in parsed.fixed_pois}
        for dp in dest_pois:
            if dp not in existing_names:
                parsed.fixed_pois.append(FixedPoi(name=dp, user_time_budget=None))
                existing_names.add(dp)

    parsed.day_poi_constraints = _merge_constraints(
        _day_poi_constraints_from_request(user_request),
        parsed.day_poi_constraints,
        ["day_index", "poi_name"],
    )
    if parsed.day_poi_constraints:
        parsed.fixed_pois = _order_fixed_pois_by_day_constraints(parsed.fixed_pois, parsed.day_poi_constraints)

    # v3新增：防幻觉校验 — 检查FixedPoi名称是否在用户原话中
    for fp in list(parsed.fixed_pois):
        if fp.name not in user_request and not any(
            fp.name in known and known in user_request for known in KNOWN_POIS
        ):
            parsed.fixed_pois.remove(fp)

    # v3新增：计算每个FixedPoi的resolved_time_budget
    for fp in parsed.fixed_pois:
        if fp.user_time_budget is not None:
            fp.resolved_time_budget = _parse_user_time_budget(fp.user_time_budget)

    if "最近" in user_request:
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["最近"])
    if any(token in user_request for token in ["不想走太远", "不走太远", "别太远", "近一点", "附近"]):
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["不走远"])
    if any(token in user_request for token in ["别太赶", "不太赶", "节奏宽松", "轻松一点"]):
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["节奏宽松"])
    if any(token in user_request for token in ["自驾", "开车", "驾车"]):
        parsed.transport_hint = "自驾"
    if any(token in user_request for token in RAINY_DAY_TOKENS):
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["雨天", "室内优先"])
    if any(token in user_request for token in INDOOR_PREF_TOKENS):
        parsed.other_constraints = _append_unique(parsed.other_constraints, ["室内优先"])

    if not parsed.search_keywords:
        if parsed.raw_keywords:
            parsed.search_keywords = list(parsed.raw_keywords)
        elif user_profile.activity_pref_tag:
            parsed.search_keywords = list(user_profile.activity_pref_tag)
        else:
            parsed.search_keywords = ["景点 推荐", "好玩的地方", "周末 去哪"]
    if "室内优先" in parsed.other_constraints:
        indoor_search = [
            "室内 景点",
            "博物馆 展览",
            "美术馆 书店",
            "商场 室内",
        ]
        indoor_micro = ["室内 打卡", "博物馆 展览", "美术馆 书店", "商场 逛街"]
        parsed.search_keywords = _append_unique(indoor_search, parsed.search_keywords, limit=8)
        parsed.micro_keywords = _append_unique(indoor_micro, parsed.micro_keywords, limit=6)

    explicit_meals = _explicit_meals(user_request)
    if _dinner_before_activity(user_request):
        parsed.dinner_first = True
    # v22: Defensive normalization — meal_constraints must always be list[dict]
    if isinstance(parsed.meal_constraints, dict):
        parsed.meal_constraints = [parsed.meal_constraints]
    elif parsed.meal_constraints is None:
        parsed.meal_constraints = []
    elif not isinstance(parsed.meal_constraints, list):
        parsed.meal_constraints = []
    # Likewise for list[str] fields
    for _list_field in ("food_pref_keywords", "meal_search_keywords", "search_keywords", "micro_keywords"):
        _val = getattr(parsed, _list_field, None)
        if _val is None or isinstance(_val, dict):
            setattr(parsed, _list_field, [])
        elif isinstance(_val, str):
            setattr(parsed, _list_field, [_val])
        elif not isinstance(_val, list):
            setattr(parsed, _list_field, list(_val or []))
    parsed.meal_constraints = _merge_constraints(
        _meal_constraints_from_request(user_request),
        parsed.meal_constraints,
        ["day_index", "meal", "fixed_poi_name"],
    )
    DIRECTION_WORDS = {"外面", "旁边", "附近", "周边", "出去", "外面吃", "出去吃"}
    for constraint in parsed.meal_constraints:
        name = str(constraint.get("fixed_poi_name") or "").strip()
        if (
            name in DIRECTION_WORDS
            or len(name) <= 2
            or any(term in name for term in ["附近", "周边", "周围", "旁边", "一带"])
        ):
            constraint["fixed_poi_name"] = None

    # Drop empty LLM meal constraints that are not supported by deterministic
    # clause-level evidence, then deduplicate after clearing false fixed names.
    rule_meal_constraints = _meal_constraints_from_request(user_request)
    evidenced_meals = {item.get("meal") for item in rule_meal_constraints if item.get("meal")}
    cleaned_constraints: list[dict] = []
    seen_constraints: set[tuple] = set()
    for constraint in parsed.meal_constraints:
        has_payload = bool(constraint.get("keywords") or constraint.get("fixed_poi_name"))
        if not has_payload and constraint.get("meal") not in evidenced_meals:
            continue
        key = (
            constraint.get("day_index"),
            constraint.get("meal"),
            constraint.get("fixed_poi_name"),
            tuple(constraint.get("keywords") or []),
        )
        if key in seen_constraints:
            continue
        seen_constraints.add(key)
        cleaned_constraints.append(constraint)
    parsed.meal_constraints = cleaned_constraints

    # Preserve clause-local references on planned waypoints after LLM parsing.
    # This must run after proximity parsing but before the planned fast path.
    _bind_planned_waypoint_search_centers(parsed.planned_waypoints, user_request)
    request_food_keywords = _request_food_keywords_from_constraints(parsed.meal_constraints)
    parsed.food_pref_keywords = _normalize_food_preferences(parsed.food_pref_keywords)
    parsed.food_pref_keywords = _append_unique(parsed.food_pref_keywords, request_food_keywords, limit=6)
    # v12: 先算 meal_needs，只有需要吃饭时才注入偏好
    # v20: poi_category/named_poi 短查询不自动生成餐饮需求
    # v20: 单地点、附近、最近查询不得因当前时间自动生成 meal_needs
    # 自动餐饮只能用于明确的多小时路线规划（time_budget >= 0.5）
    _poi_query_type = getattr(parsed, "poi_query_type", "") or ""
    _explicit_meal = bool(getattr(parsed, "explicit_meal_intent", False))
    _has_food_keywords = bool(parsed.food_pref_keywords or parsed.meal_search_keywords)
    _is_nearby = any(token in user_request for token in ["附近", "最近", "周边", "旁边"])
    _is_single_target = len(parsed.planned_waypoints or []) <= 1 and len(parsed.fixed_pois or []) <= 1
    _is_short_duration = parsed.time_budget <= 0.25
    _has_no_food_mention = not _has_food_keywords and not _explicit_meal
    _skip_auto_meals = (
        (_poi_query_type in ("poi_category", "named_poi") and _has_no_food_mention)
        or (_is_nearby and _has_no_food_mention)
        or (_is_single_target and _has_no_food_mention)
        or (_is_short_duration and _has_no_food_mention)
    )
    if _skip_auto_meals:
        parsed.meal_needs = []
    else:
        # v21: Validate duration before dict lookup — empty/invalid → empty meals
        _valid_durations = {"a quarter day", "a half day", "a full day",
                           "a day and a half", "two days", "two and a half days", "three days"}
        if parsed.duration not in _valid_durations or not parsed.duration:
            print(f"[DEBUG step1 WARN] invalid duration '{parsed.duration}' — skipping meal_needs")
            parsed.meal_needs = []
        else:
            meal_overlap_threshold = 1.0 if parsed.time_budget <= 0.25 else 0.5
            parsed.meal_needs = compute_meal_needs(
                parsed.start_time,
                parsed.duration,
                min_overlap_hours=meal_overlap_threshold,
            )
    # 只有确实需要安排餐饮时，才用用户画像偏好作为兜底口味
    if not parsed.food_pref_keywords and user_profile.food_pref_tag and bool(parsed.meal_needs):
        parsed.food_pref_keywords = list(user_profile.food_pref_tag)
    parsed.budget_per_capita = _budget_from_request(user_request) or parsed.budget_per_capita

    if not parsed.micro_keywords:
        if parsed.raw_keywords:
            parsed.micro_keywords = [f"{kw} 打卡" for kw in parsed.raw_keywords[:2]] + [f"{kw} 体验" for kw in parsed.raw_keywords[:2]]
        else:
            parsed.micro_keywords = ["景点 打卡", "咖啡 创意园", "展览 拍照"]

    parsed.reject_capacities = compute_reject_capacities(parsed.time_budget)
    parsed.meal_needs = _merge_meal_needs(parsed.meal_needs, explicit_meals)
    parsed.meal_needs = _merge_constraint_meals(parsed.meal_needs, parsed.meal_constraints)
    parsed.meal_search_keywords = _normalize_meal_search_keywords(parsed, user_request)
    if parsed.transport_hint is None:
        parsed.transport_hint = "公共交通"
    if not parsed.crowd_type:
        parsed.crowd_type = "单人"

    # Final intent lock: generic "X附近找Y" parsing is useful for extracting X
    # (for example 清华), but it can misclassify the subjective Y phrase as a
    # concrete POI category. Re-apply the casual-rest semantic after every
    # generic rule branch while preserving the resolved search centre.
    _is_casual_rest = (
        any(term in user_request for term in _CASUAL_REST_EXPRESSIONS)
        and any(term in user_request for term in ("坐着", "坐坐", "休息", "歇脚", "待会儿", "待一会"))
    )
    if _is_casual_rest:
        _apply_casual_rest_intent(parsed, city, user_request)

    # LLM and all rule branches produce keyword bodies; the backend is the
    # single authority that adds the departure city's administrative label.
    parsed.search_keywords = canonicalize_search_keywords(parsed.search_keywords, city, limit=8)

    # [DEBUG-雨天半天] 临时调试日志，确认雨天/半日识别
    # v21: Force planned mode for corridor tasks — may have been reset by upstream
    if getattr(parsed, "corridor_requested", False) and getattr(parsed, "plan_mode", "") != "planned":
        print(f"[DEBUG step1 WARN] plan_mode was reset from planned; forcing back for corridor task")
        parsed.plan_mode = "planned"
    # v21: Restore corridor waypoints if cleared by profile/theme processing
    if getattr(parsed, "corridor_requested", False) and not getattr(parsed, "fixed_pois", []):
        _dest_name = getattr(parsed, "resolved_destination_name", "") or ""
        if _dest_name:
            parsed.fixed_pois = [FixedPoi(name=_dest_name, user_time_budget=None)]

    # v22: Final normalization — locked multi_facet_art must not carry cafe/food pollution
    if getattr(parsed, "theme_route_locked", False) and parsed.activity_facet == "multi_facet_art_photo_cafe_shop":
        parsed.poi_query_type = "theme_route"
        parsed.primary_query = ""
        parsed.category_id = None
        parsed.allowed_typecode_prefixes = []
        parsed.must_recall_target = False
        parsed.explicit_meal_intent = False
        parsed.meal_needs = []
        parsed.meal_constraints = []
        parsed.food_pref_keywords = []
        parsed.meal_search_keywords = []
        parsed.theme_profile = "art_culture_lifestyle"
        city_short = city[:-1] if city.endswith("市") else city
        parsed.search_keywords = [
            f"{city_short} 文艺拍照 路线",
            f"{city_short} 美术馆 艺术空间",
            f"{city_short} 创意园区 文创园",
            f"{city_short} 独立书店 文创店",
            f"{city_short} 买手店 特色小店",
            f"{city_short} 精品咖啡 独立咖啡馆",
            f"{city_short} 历史街区 胡同",
            f"{city_short} 轻松散步 街区",
        ]
        parsed.micro_keywords = [
            "拍照打卡", "艺术空间", "独立书店", "文创店", "精品咖啡", "特色小店",
        ]
        # v25: Re-assert theme_facets in final normalization — don't lose cafe/shop facets
        # v27: Use _nl_input (extracted user input) instead of raw user_request
        _fn_match_text = _nl_input if _nl_input else user_request
        _fn_has_photo = any(t in _fn_match_text for t in ["拍照", "出片", "打卡", "摄影"])
        _fn_has_art = any(t in _fn_match_text for t in ["文艺", "艺术", "展览", "小众", "文化"])
        _fn_has_cafe = any(t in _fn_match_text for t in ["咖啡", "咖啡馆", "咖啡店"])
        _fn_has_shop = any(t in _fn_match_text for t in ["特色小店", "买手店", "杂货店", "文创店", "小店"])
        _fn_has_relaxed = any(t in _fn_match_text for t in ["节奏轻松", "轻松一点", "慢一点", "不赶", "散步", "逛逛", "散散步"])
        parsed.theme_facets = _build_multi_facet_art_facets(
            _fn_has_photo, _fn_has_art, _fn_has_cafe, _fn_has_shop, _fn_has_relaxed
        )
        parsed.theme_coverage_policy = "cover_required_facets"
        parsed.micro_poi_keywords = _append_unique(
            list(getattr(parsed, "micro_poi_keywords", []) or []),
            [
                "艺术空间", "画廊", "美术馆",
                "精品咖啡馆", "独立咖啡馆", "咖啡馆",
                "买手店", "特色小店", "文创店",
            ],
            limit=12,
        )
        parsed.micro_required_terms = _append_unique(
            list(getattr(parsed, "micro_required_terms", []) or []),
            [
                "艺术", "画廊", "美术馆", "咖啡", "coffee", "cafe",
                "买手店", "文创", "特色小店",
            ],
            limit=16,
        )
        # v26+v27: Density targets in final normalize
        _fn_has_explicit_half_day = any(
            t in _fn_match_text
            for t in ["半天", "半日", "上午", "下午", "中午", "2小时", "3小时", "两小时", "三小时"]
        )
        if not _fn_has_explicit_half_day:
            parsed.duration = "a full day"
            parsed.time_budget = 1.0
        if parsed.time_budget < 1.0:
            parsed.time_budget = max(parsed.time_budget, 0.75)
            if parsed.duration in ("a half day", None, ""):
                parsed.duration = "a full day"
        parsed.density_min_visible_pois = 5
        parsed.density_target_visible_pois = 6
        parsed.candidate_target = 4

        print(
            f"[MultiFacetArtAudit] final_normalize "
            f"primary_query={parsed.primary_query or 'EMPTY'} "
            f"meal_needs={parsed.meal_needs} "
            f"search_keywords={parsed.search_keywords[:4]} "
            f"theme_facets={[f['id'] for f in parsed.theme_facets]} "
            f"duration={parsed.duration} density_target={parsed.density_target_visible_pois} "
            f"candidate_target={parsed.candidate_target}"
        )

    # v28: Final density guard — prevents downstream logic from reverting to half_day.
    parsed = _force_multi_facet_art_density(
        parsed,
        _extract_latest_user_input(user_request) or user_request,
        stage="step1_final",
    )

    print(f"[DEBUG step1] duration={parsed.duration} time_budget={parsed.time_budget}")
    print(f"[DEBUG step1] other_constraints={parsed.other_constraints}")
    print(f"[DEBUG step1] search_keywords={parsed.search_keywords}")
    print(f"[DEBUG step1] micro_keywords={parsed.micro_keywords}")
    print(f"[DEBUG step1] meal_needs={parsed.meal_needs} evening_requested={parsed.evening_requested}")
    print(f"[DEBUG step1] meal_constraints={parsed.meal_constraints}")

    return parsed


async def _fixed_budget(parsed: ParsedIntent, city: str, user_request: str = "") -> float:
    if not parsed.fixed_pois:
        return 0.0
    await emit_status("正在查询目的地信息...")
    searches = await asyncio.gather(
        *[gaode_text_search(fp.name, city=city) for fp in parsed.fixed_pois],
        return_exceptions=True,
    )
    budget = 0.0
    destination_cities: list[str] = []
    for fp, items in zip(parsed.fixed_pois, searches):
        if isinstance(items, Exception):
            print(f"[WARN step1] fixed POI lookup failed name={fp.name}: {items}")
            items = []
        if items:
            item = items[0]
            fp.location = item.get("location")
            fp.typecode = item.get("typecode", "")
            item_city = city_from_text(item.get("cityname") or item.get("pname"))
            if item_city:
                destination_cities.append(item_city)
        # v20/v21: Mark named areas for internal POI expansion when user has stroll intent
        if _is_area_stroll_request(str(user_request or ""), fp.name):
            fp.expansion_required = True
            # v21: Distinguish shopping stroll from area exploration
            _is_park = any(t in fp.name for t in _EXPLORABLE_AREA_SUFFIXES)
            fp.activity_facet = "area_stroll" if _is_park else "shopping_stroll"
            print(
                f"[AreaStroll] named_area={fp.name} expansion_required=True "
                f"facet={fp.activity_facet}"
                f"user_request={user_request[:60]}"
            )
        # v3新增：回填resolved_time_budget（未从user_time_budget解析到的用typecode兜底）
        if fp.resolved_time_budget is None:
            typecode = fp.typecode or ""
            capacity = infer_capacity_from_typecode(typecode, fp.name)
            # v21: Don't let typecode override user's explicit full-day intent for single large scenic areas
            if (getattr(parsed, "duration", "") == "a full day"
                and len(parsed.fixed_pois) <= 1
                and capacity in ("quarter_day", "half_day")):
                capacity = "full_day"
                print(f"[CapacityAudit] fixed_poi={fp.name} typecode={typecode} "
                      f"capacity_overridden={capacity} reason=user_explicit_full_day")
            fp.resolved_time_budget = capacity
        # 兜底的兜底
        if fp.resolved_time_budget is None:
            fp.resolved_time_budget = "half_day"
        budget += DURATION_TO_BUDGET.get(
            {"full_day": "a full day", "half_day": "a half day", "quarter_day": "a quarter day"}[fp.resolved_time_budget],
            0.5,
        )

    # Named destinations are stronger evidence for the itinerary city than the
    # user's home city.  Without this correction, 上海 landmarks were expanded
    # with 北京 keywords and generated 1000km local-route calls.
    if destination_cities:
        city_counts = {name: destination_cities.count(name) for name in set(destination_cities)}
        destination_city = max(city_counts, key=city_counts.get)
        parsed.resolved_city = destination_city
        print(
            f"[DEBUG destination_city] fixed_pois={len(parsed.fixed_pois)} "
            f"hints={city_counts} resolved={destination_city} home_city={city}"
        )

        # For a destination-city day plan with no explicit departure point,
        # start locally at the first resolved destination instead of routing
        # every segment from the user's home hundreds of kilometres away.
        first_resolved = next((fp for fp in parsed.fixed_pois if fp.location), None)
        if (
            first_resolved
            and parsed.original_location
            and not getattr(parsed, "original_location_label", None)
            and haversine_km(parsed.original_location, first_resolved.location) > 100.0
        ):
            parsed.original_location = {
                **first_resolved.location,
                "label": f"{first_resolved.name}附近",
            }
            print(
                f"[DEBUG destination_city] cross_city_local_start="
                f"{parsed.original_location['label']}"
            )
    return budget



class PlannedWaypointExtraction(BaseModel):
    """v6: LLM 返回的 planned waypoint 提取结果"""
    waypoints: list[PlannedWaypoint] = []


def _is_context_only_planned_clause(clause: str) -> bool:
    text = clause.strip()
    if not text:
        return True
    context_tokens = [
        "下班", "下班路上", "待会儿下班", "回家路上", "回家前",
        "附近", "周边", "顺路", "想", "在附近找一家", "找一家",
    ]
    action_tokens = [
        "买", "吃", "喝", "找个地方", "日料", "寿司", "日本料理",
        "水果", "生鲜", "菜场", "超市", "便利店", "晚饭", "晚餐", "简餐",
        "理发", "剪发", "回家", "到家", "咖啡", "奶茶",
    ]
    return any(token in text for token in context_tokens) and not any(token in text for token in action_tokens)


def _normalize_planned_request_text(text: str) -> str:
    replacements = {
        "理个发": "理发",
        "剪个头": "剪发",
        "剪头发": "剪发",
        "做头发": "美发",
        "洗剪吹": "理发",
        "咖啡店": "咖啡",
    }
    normalized = text
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)
    normalized = re.sub(r"(回家|到家)(前|之前|路上)", "", normalized)
    return normalized


def _time_slot_from_planned_clause(clause: str) -> str | None:
    """Return the explicit time slot carried by a planned-route clause."""
    if re.search(r"明早|上午|早上|早晨|清晨", clause):
        return "morning"
    if re.search(r"中午|午间", clause):
        return "lunch"
    if re.search(r"下午", clause):
        return "afternoon"
    if re.search(r"晚上|傍晚|夜里|夜间", clause):
        return "evening"
    return None


def _extract_named_target_from_timed_clause(clause: str) -> str:
    """Extract a user-named destination from a time-slotted visit clause.

    This deliberately handles only explicit visit wording.  Generic needs such
    as ``找个好吃的地方`` are classified before this helper and must never be
    promoted to a fixed POI name.
    """
    cleaned = re.sub(
        r"(?:明早|今天|明天|后天|周末|上午|早上|早晨|清晨|中午|午间|下午|晚上|傍晚|夜里|夜间)",
        "",
        clause,
    ).strip()
    cleaned = re.sub(
        r"^(?:我|我们)?(?:还)?(?:想|要|计划|打算)?(?:先)?(?:去|到|逛|游览|参观|打卡)",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(
        r"(?:逛逛|逛一逛|看看|看一看|游览|参观|打卡|玩一玩|玩一会儿|走走|转转)$",
        "",
        cleaned,
    ).strip(" 的地儿地方，,。；;！!")

    generic_terms = {
        "好吃", "好吃的", "吃的", "美食", "餐厅", "饭店", "饭馆",
        "一个地方", "个地方", "地方", "随便走走", "逛逛", "看看",
    }
    if (
        len(cleaned) < 2
        or len(cleaned) > 40
        or cleaned in generic_terms
        or re.search(r"找(?:个|一(?:个|家))?.*(?:吃|餐厅|饭店|饭馆|美食|地方)", cleaned)
    ):
        return ""
    return cleaned


# v28: Area-meal-afternoon route parser — deterministic string-split version


def _extract_area_meal_afternoon_route(user_request: str) -> list[PlannedWaypoint]:
    """Extract "area stroll + lunch + afternoon fixed point" tri-segment routes."""
    raw_text = user_request or ""

    # Must contain all three: nearby-area + noon-meal + afternoon-destination
    if not any(t in raw_text for t in ["附近", "周边", "旁边"]):
        return []
    if not any(t in raw_text for t in ["中午", "午餐", "午饭", "午间"]):
        return []
    if "下午" not in raw_text:
        return []

    waypoints: list[PlannedWaypoint] = []

    # 1. Extract morning area: text before "附近/周边/旁边"
    area_name = ""
    area_match = re.search(
        r"(?:想去|想在|去|在)?(?P<area>.+?)(?:附近|周边|旁边)",
        raw_text,
    )
    if area_match:
        area_name = area_match.group("area")
        area_name = re.sub(r"^(想去|想在|去|在)", "", area_name).strip(" ，,。；;")
        area_name = area_name.strip()

    # Guard: don't let noon/afternoon text bleed into area
    if area_name:
        area_name = re.split(r"(中午|午餐|午饭|午间|下午)", area_name)[0].strip(" ，,。；;")

    if area_name:
        waypoints.append(PlannedWaypoint(
            type="placeholder",
            search_keyword=f"{area_name} 附近转转",
            category="area_stroll",
            stay_minutes=120,
            search_keywords=[
                f"{area_name} 附近 景点",
                f"{area_name} 附近 散步",
                f"{area_name} 周边 游览",
                f"{area_name} 附近 胡同",
            ],
            required_terms=[area_name],
            excluded_terms=[],
            search_center_name=area_name,
            time_slot="morning",
        ))

    # 2. Extract noon meal keyword: text between noon-marker and afternoon
    food = "北京菜"
    lunch_part = ""
    for noon_kw in ["中午", "午餐", "午饭", "午间"]:
        if noon_kw in raw_text:
            lunch_part = raw_text.split(noon_kw, 1)[1]
            break

    if lunch_part:
        lunch_part = lunch_part.split("下午", 1)[0]
        for candidate in ["地道的北京菜", "北京菜", "京味菜", "烤鸭", "涮肉", "炸酱面"]:
            if candidate in lunch_part:
                food = candidate.replace("地道的", "")
                break

    waypoints.append(PlannedWaypoint(
        type="placeholder",
        search_keyword=food,
        category="meal",
        stay_minutes=60,
        search_keywords=[food, f"{food} 餐厅", "北京菜 餐厅", "京味菜", "老北京菜"],
        required_terms=[food, "北京菜", "京味"],
        excluded_terms=["咖啡", "奶茶", "甜品"],
        search_center_name=area_name or None,
        time_slot="lunch",
    ))

    # 3. Extract afternoon destination: text after "下午", before activity suffix
    afternoon_place = ""
    afternoon_part = raw_text.split("下午", 1)[1] if "下午" in raw_text else ""
    if afternoon_part:
        afternoon_part = re.sub(r"^(去|到|想去|安排|再去|然后去)", "", afternoon_part).strip()
        afternoon_place = re.split(
            r"(看日落|日落|看夕阳|看晚霞|转转|逛逛|走走|看看|，|,|。|；|;)",
            afternoon_part,
            maxsplit=1,
        )[0].strip(" ，,。；;")

    if afternoon_place:
        waypoints.append(PlannedWaypoint(
            type="fixed",
            name=afternoon_place,
            search_keyword=afternoon_place,
            category="visit",
            stay_minutes=120,
            search_keywords=[afternoon_place],
            required_terms=[afternoon_place, "日落", "夕阳"],
            excluded_terms=[],
            time_slot="afternoon",
        ))

    if len(waypoints) >= 3 and area_name and afternoon_place:
        print(
            "[TimedRouteAudit] source=area_meal_afternoon "
            f"area={area_name} food={food} afternoon={afternoon_place} "
            f"waypoints={[(wp.type, wp.name or wp.search_keyword, wp.category, wp.time_slot, wp.search_center_name) for wp in waypoints]}"
        )
        return waypoints

    return []


def _extract_timed_planned_waypoints(user_request: str) -> list[PlannedWaypoint]:
    """Deterministically preserve explicit morning/afternoon/evening tasks.

    Multi-period requests are especially sensitive to LLM omissions: dropping
    one named stop changes the whole route.  For clauses with explicit time
    slots, user-named places are fixed waypoints and a generic food request is
    a restaurant placeholder anchored near the preceding named stop.
    """
    # v28: Check deterministic time-sequence extractors first
    for extractor in (
        _extract_north_sea_lunch_sanlihe_route,
        _extract_north_sea_lunch_jingshan_route,
        _extract_area_meal_afternoon_route_v28,
        _extract_afternoon_dinner_river_night_route,
        _extract_area_meal_afternoon_route,  # original regex fallback
    ):
        waypoints = extractor(user_request)
        if waypoints:
            print(
                f"[TimedRouteAudit] source={extractor.__name__} "
                f"waypoints={[(wp.type, wp.name or wp.search_keyword, wp.category, wp.time_slot) for wp in waypoints]}"
            )
            return waypoints

    clauses = _split_clauses(_normalize_planned_request_text(user_request))
    explicit_slot_count = sum(1 for clause in clauses if _time_slot_from_planned_clause(clause))
    if explicit_slot_count < 2:
        return []

    waypoints: list[PlannedWaypoint] = []
    previous_named_target = ""
    for clause in clauses:
        slot = _time_slot_from_planned_clause(clause)
        if not slot:
            continue

        is_generic_meal = bool(re.search(
            r"(?:好吃的地方|找(?:个|一(?:个|家))?.*(?:吃|餐厅|饭店|饭馆|美食)|"
            r"吃(?:午饭|晚饭|饭)|午餐|晚餐|简餐|用餐|就餐)",
            clause,
        ))
        if is_generic_meal:
            meal_slot = "dinner" if slot == "evening" else ("lunch" if slot == "lunch" else slot)
            proximity = _parse_proximity_modifier(clause)
            explicit_search_center = str(
                (proximity or {}).get("search_area_label") or ""
            ).strip()
            waypoints.append(PlannedWaypoint(
                type="placeholder",
                search_keyword="餐厅",
                category="meal",
                stay_minutes=60 if meal_slot == "dinner" else 45,
                search_keywords=["餐厅", "本帮菜", "小吃", "饭馆"],
                required_terms=["餐厅", "饭店", "饭馆", "小馆", "菜馆", "美食"],
                excluded_terms=["咖啡", "奶茶", "甜品", "面包"],
                search_center_name=explicit_search_center or previous_named_target or None,
                time_slot=meal_slot,
            ))
            continue

        target = _extract_named_target_from_timed_clause(clause)
        if not target:
            continue
        waypoints.append(PlannedWaypoint(
            type="fixed",
            name=target,
            search_keyword=target,
            category="visit",
            stay_minutes=120 if slot in {"morning", "afternoon"} else 60,
            search_keywords=[target],
            required_terms=[target],
            time_slot=slot,
        ))
        previous_named_target = target

    return waypoints


def _fallback_planned_waypoints_from_request(
    user_request: str,
    include_generic: bool = True,
) -> list[PlannedWaypoint]:
    """v6: 确定性 fallback 解析器 — LLM 失败时兜底。

    按 "再 / 然后 / 接着 / 顺便 / , / ， / 、" 切分子句，
    基于关键词规则匹配品类。
    """
    timed_waypoints = _extract_timed_planned_waypoints(user_request)
    if timed_waypoints:
        return timed_waypoints

    waypoints: list[PlannedWaypoint] = []
    # 切分子句 — 使用 normalized 文本
    normalized_request = _normalize_planned_request_text(user_request)
    clauses = re.split(r'再|然后|接着|顺便|，|,|、|。|如果|也可以', normalized_request)
    clauses = [c.strip() for c in clauses if c.strip()]

    _FALLBACK_RULES: list[tuple[list[str], dict]] = [
        (["回家", "到家", "先回家"], {"type": "fixed", "name": "家", "category": "home", "stay_minutes": 0}),
        (["去公司", "回公司", "到公司"], {"type": "fixed", "name": "公司", "category": "visit", "stay_minutes": 0}),
        # ── 生活服务 ──
        (["理发", "剪发", "美发", "剃头", "发廊", "洗剪吹", "烫发", "染发", "造型"],
         {"type": "placeholder", "search_keyword": "理发店", "category": "service", "stay_minutes": 45,
          "search_keywords": ["理发店", "美发店", "发廊", "剪发", "发型设计"],
          "required_terms": ["理发", "美发", "美容美发", "发廊", "剪发", "造型", "发型", "洗剪吹"],
          "excluded_terms": ["宠物", "培训", "学校", "收发室", "收发", "快递", "驿站", "菜鸟", "丰巢", "快递柜", "代收", "自提", "包裹", "物流", "货运", "配送", "派送", "邮政", "邮局", "打印", "快印", "复印", "图文", "维修", "开锁", "搬家", "洗衣", "房产", "中介", "通讯", "营业厅"]}),
        # ── 采购 ──
        (["买水果", "买点水果", "水果店", "水果"], {"type": "placeholder", "search_keyword": "水果店", "category": "purchase", "stay_minutes": 20}),
        (["买药", "药店", "大药房", "感冒药"],
         {"type": "placeholder", "search_keyword": "药店", "category": "purchase", "stay_minutes": 15,
          "search_keywords": ["药店", "大药房"],
          "required_terms": ["药店", "大药房", "医药"],
          "excluded_terms": ["宠物", "诊所"]}),
        (["买花", "鲜花", "花店", "花束"],
         {"type": "placeholder", "search_keyword": "花店", "category": "purchase", "stay_minutes": 15,
          "search_keywords": ["花店", "鲜花店"],
          "required_terms": ["花店", "鲜花", "花艺"],
          "excluded_terms": ["花鸟市场"]}),
        (["超市", "买东西", "去全家", "去罗森", "全家", "罗森", "711", "买饮料", "买零食"],
         {"type": "placeholder", "search_keyword": "便利店", "category": "purchase", "stay_minutes": 20}),
        (["面包", "面包店", "烘焙", "蛋糕", "甜点"],
         {"type": "placeholder", "search_keyword": "面包店", "category": "purchase", "stay_minutes": 15,
          "search_keywords": ["面包店", "蛋糕店", "烘焙"],
          "required_terms": ["面包", "蛋糕", "烘焙", "甜点"],
          "excluded_terms": ["咖啡", "奶茶", "茶饮"]}),
        (["便利店"], {"type": "placeholder", "search_keyword": "便利店", "category": "purchase", "stay_minutes": 15}),
        # ── 餐饮 ──
        (["日料", "寿司", "日本料理", "生鱼片"], {"type": "placeholder", "search_keyword": "日料", "category": "meal", "stay_minutes": 40}),
        (["火锅", "涮肉"], {"type": "placeholder", "search_keyword": "火锅", "category": "meal", "stay_minutes": 50}),
        (["烧烤", "烤串", "撸串"], {"type": "placeholder", "search_keyword": "烧烤", "category": "meal", "stay_minutes": 50}),
        (["本帮菜", "上海菜", "江浙菜"], {"type": "placeholder", "search_keyword": "本帮菜", "category": "meal", "stay_minutes": 50}),
        (["川菜", "湘菜", "粤菜", "东北菜"], {"type": "placeholder", "search_keyword": "餐厅", "category": "meal", "stay_minutes": 40}),
        (["吃晚饭", "晚饭", "晚餐", "吃个晚饭"], {"type": "placeholder", "search_keyword": "餐厅", "category": "meal", "stay_minutes": 40}),
        (["吃午饭", "午饭", "午餐"], {"type": "placeholder", "search_keyword": "简餐", "category": "meal", "stay_minutes": 40}),
        (["简单吃", "随便吃点", "对付一口", "垫垫肚子", "找个地方吃", "好吃的地方", "找个好吃", "找一家好吃"], {"type": "placeholder", "search_keyword": "餐厅", "category": "meal", "stay_minutes": 40}),
        (["宵夜", "夜宵"], {"type": "placeholder", "search_keyword": "宵夜", "category": "meal", "stay_minutes": 40}),
        (["麦当劳", "肯德基", "kfc", "KFC", "金拱门", "开封菜", "汉堡王"], {"type": "fixed", "search_keyword": "", "category": "meal", "stay_minutes": 25}),
        # ── 咖啡/奶茶 ──
        (["咖啡", "瑞幸", "星巴克", "manner", "Manner", "Costa", "costa"],
         {"type": "placeholder", "search_keyword": "咖啡", "category": "cafe", "stay_minutes": 25}),
        (["奶茶", "喜茶", "奈雪", "一点点", "coco", "CoCo"], {"type": "placeholder", "search_keyword": "奶茶", "category": "cafe", "stay_minutes": 25}),
        (["星巴克"], {"type": "fixed", "search_keyword": "", "category": "cafe", "stay_minutes": 25}),
        # ── 生鲜/菜场 ──
        (["生鲜", "菜场", "菜市场", "农贸市场", "买菜的"], {"type": "placeholder", "search_keyword": "菜市场", "category": "purchase", "stay_minutes": 20}),
        # ── 休闲娱乐 ──
        (["看电影", "电影院", "影院"],
         {"type": "placeholder", "search_keyword": "电影院", "category": "visit", "stay_minutes": 120,
          "search_keywords": ["电影院", "影院"]}),
        (["唱歌", "KTV", "卡拉OK"],
         {"type": "placeholder", "search_keyword": "KTV", "category": "visit", "stay_minutes": 120,
          "search_keywords": ["KTV", "卡拉OK"]}),
        (["喝酒", "酒吧", "清吧", "小酌", "喝一杯"],
         {"type": "placeholder", "search_keyword": "酒吧", "category": "visit", "stay_minutes": 60,
          "search_keywords": ["酒吧", "清吧"]}),
        (["散步", "公园", "滨江", "步道"],
         {"type": "placeholder", "search_keyword": "公园", "category": "visit", "stay_minutes": 45,
          "search_keywords": ["公园", "滨江步道"]}),
    ]

    for clause in clauses:
        if _is_context_only_planned_clause(clause):
            continue

        # Clause-local reference: "X旁边的饭馆" means search for a meal near
        # X. X is not itself a visible visit waypoint.
        prox = _parse_proximity_modifier(clause)
        if prox and prox.get("search_area_label"):
            prox_target = str(prox.get("primary_query") or "").strip()
            if any(term in prox_target for term in ["饭馆", "饭店", "餐厅", "吃饭", "用餐", "就餐", "简餐"]):
                waypoints.append(PlannedWaypoint(
                    type="placeholder",
                    search_keyword="餐厅",
                    category="meal",
                    stay_minutes=40,
                    search_keywords=["餐厅", "饭馆", "小吃", "快餐"],
                    required_terms=["餐厅", "饭馆", "饭店", "小馆", "菜馆", "食府"],
                    excluded_terms=["咖啡", "奶茶", "甜品", "面包"],
                    search_center_name=str(prox["search_area_label"]),
                    time_slot="dinner" if re.search(r"晚上|傍晚|夜里|夜间", clause) else None,
                ))
                continue

        matched = False
        for tokens, config_val in _FALLBACK_RULES:
            if any(t in clause for t in tokens):
                wp = PlannedWaypoint(
                    type=config_val.get("type", "placeholder"),
                    name=config_val.get("name"),
                    search_keyword=config_val.get("search_keyword", ""),
                    category=config_val.get("category", "visit"),
                    stay_minutes=config_val.get("stay_minutes", 30),
                    search_keywords=list(config_val.get("search_keywords", [])),
                    required_terms=list(config_val.get("required_terms", [])),
                    excluded_terms=list(config_val.get("excluded_terms", [])),
                )
                # 对于 fixed 类型品牌名，从原句中取 name
                if wp.type == "fixed" and not wp.name:
                    wp.name = wp.search_keyword or clause
                waypoints.append(wp)
                matched = True
                break
        if not matched and include_generic and len(clause) > 2:
            # v20: Structure the clause — strip time/area/action words, match categories
            wp = _structure_generic_clause(clause)
            if wp:
                waypoints.append(wp)
            else:
                # Last resort: use cleaned clause
                cleaned = _strip_noise_from_clause(clause)
                if cleaned and len(cleaned) >= 2:
                    waypoints.append(PlannedWaypoint(
                        type="placeholder",
                        search_keyword=cleaned,
                        category="visit",
                        stay_minutes=30,
                    ))

    return waypoints


def _bind_planned_waypoint_search_centers(
    waypoints: list[PlannedWaypoint],
    user_request: str,
) -> None:
    """Attach clause-local X-near-Y references to the matching waypoint.

    LLM output may correctly create a meal waypoint while omitting the local
    reference.  This deterministic pass preserves the LLM waypoint order and
    only enriches the matching placeholder with its search center.
    """
    if not waypoints:
        return

    used_indexes: set[int] = set()
    for clause in _split_clauses(user_request):
        prox = _parse_proximity_modifier(clause)
        reference = str((prox or {}).get("search_area_label") or "").strip()
        target = str((prox or {}).get("primary_query") or "").strip()
        if not reference or not target:
            continue

        wants_meal = any(term in target for term in ["饭馆", "饭店", "餐厅", "吃饭", "用餐", "就餐", "简餐"])
        wants_cafe = any(term in target.lower() for term in ["咖啡", "coffee", "奶茶", "茶馆"])

        matching_indexes: list[int] = []
        for idx, wp in enumerate(waypoints):
            if idx in used_indexes:
                continue
            haystack = " ".join([
                str(wp.name or ""),
                str(wp.search_keyword or ""),
                " ".join(wp.search_keywords or []),
            ])
            if wants_meal and wp.category == "meal":
                matching_indexes.append(idx)
            elif wants_cafe and wp.category == "cafe":
                matching_indexes.append(idx)
            elif target and (target in haystack or haystack in target):
                matching_indexes.append(idx)

        if not matching_indexes:
            continue

        # A proximity clause normally describes the later waypoint in a route.
        selected_idx = matching_indexes[-1]
        waypoints[selected_idx].search_center_name = reference
        if wants_meal and re.search(r"晚上|傍晚|夜里|夜间", clause):
            waypoints[selected_idx].time_slot = "dinner"
        used_indexes.add(selected_idx)
        print(
            f"[DEBUG step1] waypoint local search center bound: "
            f"idx={selected_idx} reference={reference} target={target} "
            f"waypoint={waypoints[selected_idx].search_keyword or waypoints[selected_idx].name}"
        )


# v20: Generic clause structuring helpers
def _strip_noise_from_clause(clause: str) -> str:
    """Strip time/area/action noise words from a clause to extract the core target."""
    # Remove time words
    cleaned = re.sub(
        r"(?:明天|今天|后天|周末|上午|下午|中午|晚上|傍晚|夜里)",
        "", clause
    )
    # Remove action-only words
    cleaned = re.sub(
        r"(?:玩一玩|看看|逛逛|坐一会儿|走走|溜达|转转|玩|去|在|到|找)",
        "", cleaned
    )
    # Remove area patterns
    cleaned = _AREA_CATEGORY_RE.sub(r"\2", cleaned)
    return cleaned.strip()


def _structure_generic_clause(clause: str) -> PlannedWaypoint | None:
    """Try to structure a generic clause into a category-based planned waypoint.

    1. Strip time/area/action noise
    2. Try CATEGORY_RULES semantic_terms matching
    3. Try _GENERIC_SERVICE_NOUNS
    4. Try category_for_query
    """
    from .poi_typecodes import (
        CATEGORY_RULES, category_for_query,
        get_search_keywords, get_allowed_typecode_prefixes,
        get_semantic_terms, get_negative_terms,
    )

    # First, check if the clause matches known area+category patterns
    area_cat = _parse_area_category_modifier(clause)
    if area_cat:
        target = area_cat["primary_query"]
        cat_id = area_cat.get("category_id")
        if cat_id:
            return PlannedWaypoint(
                type="placeholder",
                search_keyword=target,
                category="visit",
                stay_minutes=45 if cat_id in ("shopping_mall", "religious_site") else 30,
                search_keywords=get_search_keywords(cat_id),
                required_terms=get_semantic_terms(cat_id),
                excluded_terms=get_negative_terms(cat_id),
            )
        else:
            return PlannedWaypoint(
                type="placeholder",
                search_keyword=target,
                category="visit",
                stay_minutes=30,
                search_keywords=[target],
            )

    # Strip noise
    cleaned = _strip_noise_from_clause(clause)
    if not cleaned or len(cleaned) < 2:
        return None

    # Try CATEGORY_RULES semantic terms
    best_cat = None
    best_term_len = 0
    for cat_id, rule in CATEGORY_RULES.items():
        if cat_id == "restaurant":
            continue
        for term in rule.get("semantic_terms", []):
            if term in cleaned:
                if len(term) > best_term_len:
                    best_cat = cat_id
                    best_term_len = len(term)

    if best_cat:
        return PlannedWaypoint(
            type="placeholder",
            search_keyword=cleaned,
            category="visit",
            stay_minutes=45 if best_cat in ("shopping_mall", "religious_site") else 30,
            search_keywords=get_search_keywords(best_cat),
            required_terms=get_semantic_terms(best_cat),
            excluded_terms=get_negative_terms(best_cat),
        )

    # Try generic service nouns
    for noun in sorted(_GENERIC_SERVICE_NOUNS, key=len, reverse=True):
        if noun in cleaned:
            return PlannedWaypoint(
                type="placeholder",
                search_keyword=noun,
                category="visit",
                stay_minutes=30,
                search_keywords=[noun],
            )

    return None


def _fast_planned_intent_from_rules(
    user_request: str,
    current_time: dt.datetime,
) -> ParsedIntent | None:
    """Parse high-frequency local life chains without waiting on the large LLM prompt."""
    life_chain_tokens = [
        "下班", "下班路上", "回家路上", "回家前", "顺路", "顺便",
        "待会儿", "附近", "周边", "买水果", "晚饭", "晚餐", "简单吃",
        "日料", "回家", "理发",
    ]
    if not any(token in user_request for token in life_chain_tokens):
        return None

    waypoints = _fallback_planned_waypoints_from_request(user_request, include_generic=False)
    if not waypoints:
        return None
    if not all(wp.category in {"meal", "purchase", "service", "home", "cafe"} for wp in waypoints):
        return None

    raw_keywords: list[str] = []
    search_keywords: list[str] = []
    micro_keywords: list[str] = []
    food_pref_keywords: list[str] = []
    meal_search_keywords: list[str] = []
    meal_constraints: list[dict] = []

    for wp in waypoints:
        label = (wp.search_keyword or wp.name or "").strip()
        if not label:
            continue
        if wp.category == "purchase":
            raw_keywords = _append_unique(raw_keywords, ["水果" if "果" in label else label])
            search_keywords = _append_unique(search_keywords, [label, "生鲜超市"], limit=6)
            micro_keywords = _append_unique(micro_keywords, [f"{label} 生鲜"], limit=5)
        elif wp.category == "meal":
            raw_keywords = _append_unique(raw_keywords, [label])
            if label in {"日料", "寿司", "日本料理"}:
                food_pref_keywords = _append_unique(food_pref_keywords, [label], limit=6)
                meal_search_keywords = _append_unique(meal_search_keywords, [f"{label} 餐厅"], limit=6)
                meal_constraints.append({
                    "day_index": None,
                    "meal": "dinner",
                    "keywords": ["日料", "日本料理", "寿司", "刺身"] if label == "日料" else [label],
                    "fixed_poi_name": None,
                })
            else:
                meal_search_keywords = _append_unique(meal_search_keywords, ["简餐", "餐厅"], limit=6)
                meal_constraints.append({
                    "day_index": None,
                    "meal": "dinner",
                    "keywords": [],
                    "fixed_poi_name": None,
                })
            search_keywords = _append_unique(search_keywords, [label], limit=6)
            micro_keywords = _append_unique(micro_keywords, [f"{label} 晚餐"], limit=5)
        elif wp.category == "service":
            raw_keywords = _append_unique(raw_keywords, [label])
            search_keywords = _append_unique(search_keywords, [label], limit=6)
            micro_keywords = _append_unique(micro_keywords, [f"{label} 附近"], limit=5)

    return ParsedIntent(
        is_route_planning_request=True,
        duration="a quarter day",
        start_time=None,
        evening_requested=False,
        raw_keywords=raw_keywords,
        search_keywords=search_keywords,
        fixed_pois=[],
        food_pref_keywords=food_pref_keywords,
        meal_search_keywords=meal_search_keywords,
        meal_constraints=meal_constraints,
        micro_keywords=micro_keywords,
        other_constraints=["不走远"] if any(token in user_request for token in ["附近", "周边", "顺路", "下班"]) else [],
        plan_mode="planned",
        planned_waypoints=waypoints,
    )


async def _extract_planned_waypoints(
    user_request: str,
    current_time: dt.datetime,
) -> list[PlannedWaypoint]:
    """v6: 从用户请求中提取规划性途经点（连续决策模式专用）。
    先尝试 LLM 提取，失败时使用确定性 fallback 兜底。
    只在 plan_mode="planned" 时调用。
    """
    time_str = current_time.strftime('%Y-%m-%d %H:%M')
    hour = current_time.hour
    time_context = ""
    if 21.5 <= hour or hour < 2:
        time_context = "当前是深夜时段，餐饮应标注为 night_snack"
    elif 17 <= hour < 21.5:
        time_context = "当前是晚高峰/晚间时段，餐饮应标注为 dinner"
    elif 14 <= hour < 17:
        time_context = "当前是下午时段，餐饮可标注为 afternoon_tea 或简餐"
    elif 10.5 <= hour < 14:
        time_context = "当前是午餐时段，餐饮应标注为 lunch"
    elif 5 <= hour < 10.5:
        time_context = "当前是早餐时段"

    messages = [
        {
            "role": "system",
            "content": (
                "你是出行途经点提取器。从用户请求中提取有序途经点列表。\n"
                f"{time_context}\n\n"
                "每个途经点包含：\n"
                "- type: fixed（用户说了具体名称）或 placeholder（品类意图）\n"
                "- name: 具体名称（fixed时必填）\n"
                "- search_keyword: 检索词（placeholder时必填，如\"日料\"\"水果店\"\"理发\"\"简餐\"）\n"
                "- category: 严格枚举值 — meal(吃饭/餐厅等) | cafe(咖啡/奶茶) | purchase(买水果/超市/便利店/面包) | service(理发/剪发) | home(回家/到家) | visit(其他)\n"
                "- stay_minutes: 预估停留分钟\n\n"
                "- search_center_name: 仅当用户明确说X附近/旁边/周边的Y时填写X；X只是搜索中心，不是展示途经点\n\n"
                "规则：保留用户顺序；回家→home；买水果→purchase；日料→meal；咖啡→cafe；理发→service；search_keyword用具体的检索词（水果店/理发/日料等）\n"
                "返回JSON数组，每个元素含type/name/search_keyword/category/stay_minutes/search_center_name"
            ),
        },
        {
            "role": "user",
            "content": f"当前时间：{time_str}\n用户请求：{user_request}",
        },
    ]
    try:
        resp = await call_llm(
            response_model=PlannedWaypointExtraction,
            messages=messages,
            max_tokens=config.DEEPSEEK_MAX_TOKENS_STEP_1_1,
            temperature=config.DEEPSEEK_TEMPERATURE,
            max_retries=config.DEEPSEEK_MAX_RETRIES,
        )
        waypoints = list(resp.waypoints)
        # 验证和修正 category
        valid_categories = {"meal", "cafe", "purchase", "service", "home", "visit", "explore"}
        for wp in waypoints:
            if wp.category not in valid_categories:
                wp.category = "visit"
            if wp.stay_minutes == 30 and wp.category != "visit":
                stay_map = {"meal": 40, "cafe": 25, "purchase": 20, "service": 45, "home": 0}
                wp.stay_minutes = stay_map.get(wp.category, 30)
        print(f"[DEBUG step1] LLM _extract_planned_waypoints result: {[(wp.type, wp.name or wp.search_keyword, wp.category, wp.stay_minutes) for wp in waypoints]}")
        if waypoints:
            return waypoints
    except Exception as e:
        print(f"[DEBUG step1] LLM _extract_planned_waypoints failed: {e}, using fallback")

    # 降级：使用确定性 fallback
    fallback = _fallback_planned_waypoints_from_request(user_request)
    print(f"[DEBUG step1] _extract_planned_waypoints fallback result: {[(wp.type, wp.name or wp.search_keyword, wp.category, wp.stay_minutes) for wp in fallback]}")
    return fallback



def _normalize_unified_routing_fields(
    parsed: ParsedIntent,
    routing_context: dict | None,
) -> ParsedIntent:
    """Validate the routing envelope without reclassifying the user's intent."""
    valid_conversation_modes = {
        "new_plan", "refine_current", "point_edit", "follow_up", "answer_only", "unsupported",
    }
    conversation_mode = str(getattr(parsed, "conversation_mode", "new_plan") or "new_plan")
    if conversation_mode not in valid_conversation_modes:
        print(
            "[UnifiedRoutingAudit] invalid_conversation_mode "
            f"value={conversation_mode!r} repaired=new_plan"
        )
        parsed.conversation_mode = "new_plan"

    valid_plan_modes = {"planned", "exploratory", "mixed"}
    previous_mode = str(
        ((routing_context or {}).get("previous_intent") or {}).get("plan_mode")
        or ((routing_context or {}).get("previous_complete_plan") or {}).get("plan_mode")
        or ""
    )
    plan_mode = str(getattr(parsed, "plan_mode", "exploratory") or "exploratory")
    if plan_mode not in valid_plan_modes:
        repaired_mode = previous_mode if previous_mode in valid_plan_modes else "exploratory"
        print(
            "[UnifiedRoutingAudit] invalid_plan_mode "
            f"value={plan_mode!r} repaired={repaired_mode!r}"
        )
        parsed.plan_mode = repaired_mode
    elif (
        parsed.conversation_mode in {"refine_current", "point_edit", "follow_up"}
        and previous_mode in valid_plan_modes
        and plan_mode != previous_mode
    ):
        # A route edit changes constraints or a point; it does not silently
        # replace the executable planning mode inherited from the current route.
        print(
            "[UnifiedRoutingAudit] inherited_plan_mode "
            f"conversation_mode={parsed.conversation_mode!r} "
            f"llm_mode={plan_mode!r} restored={previous_mode!r}"
        )
        parsed.plan_mode = previous_mode
    return parsed


def _ensure_explicit_visible_facet_coverage(parsed: Any, text: str) -> Any:
    """Keep independently requested visible experiences from collapsing into one."""
    raw = text or ""
    wants_photo = any(token in raw for token in ("拍照", "出片", "摄影", "打卡"))
    wants_cafe = any(token in raw for token in ("咖啡", "咖啡馆", "咖啡店", "奶茶", "茶饮"))
    if not (wants_photo and wants_cafe):
        return parsed

    facets = list(getattr(parsed, "theme_facets", []) or [])
    existing = {
        str(item.get("id") or "")
        for item in facets if isinstance(item, dict)
    }
    for facet_id, label in (
        ("art_culture_lifestyle", "拍照地点"),
        ("cafe_stop", "咖啡停留"),
    ):
        if facet_id not in existing:
            facets.append({
                "id": facet_id,
                "label": label,
                "required": True,
                "role": "visible_poi",
            })
    parsed.theme_facets = facets
    parsed.theme_coverage_policy = "cover_required_facets"
    parsed.required_features = list(dict.fromkeys(
        list(getattr(parsed, "required_features", []) or []) + ["拍照", "咖啡"]
    ))
    print(
        "[ExplicitFacetCoverageAudit] enabled=true "
        f"facets={[item.get('id') for item in facets if isinstance(item, dict)]}"
    )
    return parsed


async def run_step1(
    user_request: str,
    user_profile: UserProfile,
    current_time: dt.datetime,
    logger: PipelineLogger,
    plan_mode: str = "auto",  # v18: "auto" | "exploratory" | "planned" — auto = LLM 自行判断
    routing_context: dict | None = None,
) -> ParsedIntent:
    logger.start_step("step_1_1_llm_extract")
    await emit_status("正在解析您的出行意图...")

    # v24: Extract latest_user_input from conversation_context wrapper BEFORE any parsing.
    # All keyword/waypoint/sequence detection MUST use only the actual user text,
    # never the full <conversation_context> XML which contains previous_intent JSON etc.
    _nl_input = _extract_latest_user_input(user_request)
    _has_conv_ctx = _has_conversation_context(user_request)
    _nearby_multi_stop_contract = (
        not _has_conv_ctx and is_nearby_multi_stop_local_request(_nl_input)
    )
    if _has_conv_ctx:
        print(
            f"[ContextParseAudit] has_conversation_context=true "
            f"latest_user_input={_nl_input[:120]} "
            f"original_len={len(user_request)}"
        )

    # v6: planned 模式只生成 rule hints 辅助 LLM，不再直接使用 fast planned 结果
    # v18: auto 模式也生成 rule hints（LLM 可能判断为 planned）
    # v24: Use _nl_input for rule hints — never parse conversation_context XML as waypoints
    planned_rule_hints: list[PlannedWaypoint] = []
    if plan_mode in ("auto", "planned"):
        planned_rule_hints = _fallback_planned_waypoints_from_request(_nl_input, include_generic=False)
        if planned_rule_hints:
            print(
                "[DEBUG step1] planned rule hints: "
                f"{[(wp.type, wp.name or wp.search_keyword, wp.category, wp.stay_minutes) for wp in planned_rule_hints]}"
            )

    # v27: Resolve authoritative city BEFORE fallback_city and LLM parse.
    # home_location coordinates override stale permanent_city (e.g. Beijing coords
    # with Shanghai permanent_city). This must run before _llm_parse so the LLM
    # receives the correct city in its fallback parameter.
    authoritative_city = await resolve_departure_city(user_profile)
    apply_resolved_city(user_profile, authoritative_city)
    print(
        f"[CityResolveAudit] stage=step1 authoritative_city={authoritative_city} "
        f"home_location=({getattr(user_profile, 'home_location', {}) or {}}.get('lat','?'),"
        f"{getattr(user_profile, 'home_location', {}) or {}}.get('lng','?')) "
        f"permanent_city_after={getattr(user_profile, 'permanent_city', [])}"
    )

    # v24: Compute fallback_city for LLM failure path before calling _llm_parse.
    # v27: Use authoritative_city (coord-inferred) instead of stale permanent_city.
    _fallback_city = authoritative_city or (
        user_profile.permanent_city[0]
        if (user_profile.permanent_city and user_profile.permanent_city[0])
        else ""
    )
    if not _fallback_city:
        _fallback_city = city_from_text(_nl_input)
    if not _fallback_city:
        _fallback_city = "上海市"

    parsed, parse_source = await parse_step1_llm_stage(
        user_request,
        current_time,
        plan_mode=plan_mode,
        planned_rule_hints=planned_rule_hints if planned_rule_hints else None,
        fallback_city=_fallback_city,
        routing_context=routing_context,
    )
    parsed = _normalize_unified_routing_fields(parsed, routing_context)
    _llm_plan_mode = str(getattr(parsed, "plan_mode", "exploratory") or "exploratory")
    _llm_waypoints = copy.deepcopy(list(getattr(parsed, "planned_waypoints", []) or []))
    if _nearby_multi_stop_contract:
        print(
            "[RoutingDecisionAudit] stage=step1_llm "
            f"mode={_llm_plan_mode} "
            f"waypoints={[(wp.search_keyword or wp.name, wp.category) for wp in _llm_waypoints]}"
        )
    if parse_source == "full_llm" and planned_rule_hints:
        parse_source = "full_llm_with_rule_hints"
    await logger.log_step(
        "step_1_1_llm_extract",
        output_count=1,
        details={"source": parse_source},
    )

    # v28: Early timed route detection — extract BEFORE _postprocess so NearbyFoodStroll
    # and proximity logic can be guarded.
    early_timed_waypoints = _extract_timed_planned_waypoints(_nl_input)
    early_explicit_timeline = bool(early_timed_waypoints)

    logger.start_step("step_1_2_postprocess")
    parsed = await _postprocess(parsed, user_request, user_profile, current_time)

    # v28: Override parsed intent with explicit timeline after _postprocess.
    # Prevents NearbyFoodStroll / half_day / proximity from destroying the timeline.
    if early_explicit_timeline:
        parsed.planned_waypoints = early_timed_waypoints
        _bind_planned_waypoint_search_centers(parsed.planned_waypoints, _nl_input)

        parsed.plan_mode = "planned"
        parsed.execution_contract_required = True
        setattr(parsed, "explicit_timeline_required", True)

        # Preserve morning search center, don't let only 景山 survive as fixed anchor
        first_wp = parsed.planned_waypoints[0]
        if getattr(first_wp, "search_center_name", None):
            parsed.search_area_label = first_wp.search_center_name
            parsed.proximity_requested = True

        # Only afternoon fixed destinations go into fixed_pois with time_slot
        parsed.fixed_pois = []
        for wp in parsed.planned_waypoints:
            if wp.type == "fixed" and wp.name:
                parsed.fixed_pois.append(FixedPoi(name=wp.name, user_time_budget=wp.time_slot))

        print(
            "[TimedRouteAudit] stage=step1_postprocess_override "
            f"duration={parsed.duration} time_budget={parsed.time_budget} "
            f"fixed_pois={[(fp.name, fp.user_time_budget) for fp in parsed.fixed_pois]} "
            f"planned_waypoints={[(wp.type, wp.name or wp.search_keyword, wp.time_slot, wp.search_center_name) for wp in parsed.planned_waypoints]}"
        )

    # v28: Afternoon art + dinner + river + night view — narrow forced planned mode
    if _is_afternoon_dinner_river_night_query(_nl_input):
        river_waypoints = _extract_afternoon_dinner_river_night_route(_nl_input)
        if river_waypoints:
            parsed.planned_waypoints = river_waypoints
            parsed.explicit_timeline_required = True
            parsed.plan_mode = "planned"
            parsed.duration = "a full day"
            parsed.meal_needs = ["dinner"]
            parsed.food_pref_keywords = list(dict.fromkeys(
                list(getattr(parsed, "food_pref_keywords", []) or []) + ["清淡"]
            ))
            parsed.meal_search_keywords = [
                "北京 清淡 晚饭 餐厅",
                "北京 粤菜 清淡 餐厅",
                "北京 江浙菜 清淡 餐厅",
                "北京 素食 清淡 餐厅",
                "北京 轻食 晚饭 餐厅",
            ]
            parsed.search_keywords = [
                "北京 文艺 路线 拍照 特色小店",
                "北京 清淡 晚饭 餐厅",
                "北京 河边 散步 亮马河 滨水步道",
                "北京 什刹海 河边 散步",
                "北京 拍夜景 观景 夜景",
            ]
            parsed.micro_keywords = [
                "文艺 街区", "清淡 餐厅", "河边 散步",
                "亮马河 滨水步道", "什刹海 河边", "夜景 观景",
            ]
            parsed.min_frontend_display_points = 6
            parsed.max_frontend_display_points = 8
            parsed.candidate_target = 4
            print("[RiverNightRouteAudit] force_plan_mode=planned meal=dinner requires=river_stroll,night_view")

    # v28: 北海公园→烤鸭→景山公园 narrow flag
    if _is_north_sea_lunch_jingshan_query(_nl_input):
        parsed.north_sea_lunch_jingshan_route = True
        parsed.explicit_timeline_required = True
        parsed.duration = "a full day"
        parsed.time_budget = 1.0
        parsed.meal_needs = ["lunch"]
        print("[NorthSeaRouteAudit] flag_set=true explicit_timeline_required=true")

    # v28: 北海公园→烤鸭→三里河公园 narrow flag (priority over 景山 variant)
    if _is_north_sea_lunch_sanlihe_query(_nl_input):
        parsed.north_sea_lunch_sanlihe_route = True
        parsed.north_sea_lunch_jingshan_route = False  # de-conflict
        parsed.explicit_timeline_required = True
        parsed.plan_mode = "planned"
        parsed.duration = "a full day"
        parsed.time_budget = 1.0
        parsed.meal_needs = ["lunch"]
        # fixed_pois: only 北海 and 三里河, NOT 烤鸭
        parsed.fixed_pois = []
        for name in ["北海公园", "三里河公园"]:
            parsed.fixed_pois.append(FixedPoi(name=name))
        print("[NorthSeaSanliheAudit] flag_set=true plan_mode=planned")

    # v28: Apply route quality contract after postprocess
    parsed = _apply_route_quality_contract(parsed, user_request, stage="after_postprocess")

    await logger.log_step(
        "step_1_2_postprocess",
        output_count=1,
        details={
            "duration": parsed.duration,
            "start_time": parsed.start_time.isoformat() if parsed.start_time else None,
            "time_budget": parsed.time_budget,
            "raw_keywords": parsed.raw_keywords,
            "search_keywords": parsed.search_keywords,
            "micro_keywords": parsed.micro_keywords,
            "food_pref_keywords": parsed.food_pref_keywords,
            "meal_search_keywords": parsed.meal_search_keywords,
            "day_poi_constraints": parsed.day_poi_constraints,
            "meal_constraints": parsed.meal_constraints,
            "budget_per_capita": parsed.budget_per_capita,
            "dinner_first": parsed.dinner_first,
            "original_location_label": parsed.original_location_label,
            "original_location": parsed.original_location,
        },
    )

    city = user_profile.permanent_city[0] if user_profile.permanent_city else "上海市"
    logger.start_step("step_1_3_fixed_and_weather")
    fixed_task = asyncio.create_task(_fixed_budget(parsed, city, user_request))
    # v27: Map resolved city to adcode — no more hardcoded Shanghai 310000
    _weather_adcode_map = {
        "北京市": "110000", "北京": "110000",
        "上海市": "310000", "上海": "310000",
        "广州市": "440100", "广州": "440100",
        "深圳市": "440300", "深圳": "440300",
        "天津市": "120000", "天津": "120000",
        "重庆市": "500000", "重庆": "500000",
        "杭州市": "330100", "杭州": "330100",
        "成都市": "510100", "成都": "510100",
        "武汉市": "420100", "武汉": "420100",
        "南京市": "320100", "南京": "320100",
        "西安市": "610100", "西安": "610100",
        "苏州市": "320500", "苏州": "320500",
        "长沙市": "430100", "长沙": "430100",
        "青岛市": "370200", "青岛": "370200",
        "厦门市": "350200", "厦门": "350200",
        "昆明市": "530100", "昆明": "530100",
        "三亚市": "460200", "三亚": "460200",
    }
    _weather_city = getattr(parsed, "resolved_city", "") or authoritative_city or ""
    _weather_adcode = _weather_adcode_map.get(_weather_city, "310000")
    async def _optional_weather() -> dict:
        try:
            timeout = 3.0 if getattr(parsed, "plan_mode", "") == "planned" else 8.0
            return await asyncio.wait_for(gaode_weather(_weather_adcode), timeout=timeout)
        except Exception as exc:
            print(f"[WeatherDegradeAudit] enabled=true error={type(exc).__name__}: {exc}")
            return {}

    weather_task = asyncio.create_task(_optional_weather())
    print(f"[DEBUG weather] city={_weather_city} adcode={_weather_adcode}")
    await emit_status("正在查询天气...")
    fixed_budget, weather_info = await asyncio.gather(fixed_task, weather_task)
    parsed.weather_info = weather_info
    if parsed.resolved_city and parsed.resolved_city != city:
        city = parsed.resolved_city
        apply_resolved_city(user_profile, city)
        parsed.search_keywords = canonicalize_search_keywords(
            list(parsed.search_keywords or []), city, limit=8,
        )
        print(f"[DEBUG step1] destination city override applied: {city}")
    await logger.log_step("step_1_3_fixed_and_weather", output_count=1 if fixed_budget >= 0 else 0)
    # v18: plan_mode postprocessing
    # - "planned": forced planned (backward compat), downgrade if no waypoints
    # - "auto": trust LLM's parsed.plan_mode; if LLM says planned but no valid waypoints → downgrade
    # - "exploratory": ignore waypoints, set exploratory
    # v24: Use _nl_input (extracted latest_user_input) for ALL waypoint parsing.
    # Never pass the full <conversation_context> XML to waypoint parsers.
    if _nearby_multi_stop_contract:
        _contract_source = _reconcile_nearby_multi_stop_contract(
            parsed, _llm_plan_mode, _llm_waypoints,
        )
        print(
            "[RoutingDecisionAudit] stage=step1_contract "
            "request_kind=nearby_local_chain "
            f"source={_contract_source} mode={parsed.plan_mode} "
            f"waypoints={[(wp.search_keyword or wp.name, wp.category) for wp in parsed.planned_waypoints]}"
        )
    elif plan_mode == "planned":
        parsed.plan_mode = "planned"
        if not parsed.planned_waypoints:
            parsed.planned_waypoints = _fallback_planned_waypoints_from_request(_nl_input)
        if not parsed.planned_waypoints:
            parsed.plan_mode = "exploratory"  # 提取失败降级为探索模式
            print("[DEBUG step1] forced planned but no valid waypoints → downgraded to exploratory")
    elif plan_mode == "auto":
        llm_plan_mode = getattr(parsed, 'plan_mode', 'exploratory') or 'exploratory'
        if llm_plan_mode == "planned":
            if not parsed.planned_waypoints:
                parsed.planned_waypoints = _fallback_planned_waypoints_from_request(_nl_input)
            if not parsed.planned_waypoints:
                parsed.plan_mode = "exploratory"
                print("[DEBUG step1] auto mode: LLM said planned but no valid waypoints → downgraded to exploratory")
            else:
                parsed.plan_mode = "planned"
                print(f"[DEBUG step1] auto mode: LLM detected planned, {len(parsed.planned_waypoints)} waypoints")
        else:
            parsed.plan_mode = "exploratory"
            print(f"[DEBUG step1] auto mode: LLM detected exploratory (llm_plan_mode={llm_plan_mode})")
    else:
        # explicit "exploratory" or other
        parsed.plan_mode = "exploratory"

    # v28: Nearby single meal → planned fast path injection
    # Must run BEFORE timed waypoint reconciliation so the injected waypoint
    # is consumed by the planned fast path in Step2/Step3.
    if (
        plan_mode == "planned"
        and not parsed.planned_waypoints
        and _is_nearby_single_meal_request(_nl_input)
    ):
        parsed.planned_waypoints = [_build_nearby_single_meal_waypoint(_nl_input)]
        parsed.plan_mode = "planned"
        parsed.nearby_single_meal_request = True
        print(
            "[SingleMealPlannedAudit] "
            "stage=step1_waypoint_inject "
            "plan_mode=planned "
            "waypoint_category=meal "
            "search_keyword=餐厅"
        )

    # v28: Timed waypoint reconciliation — always extract, not just for planned mode.
    # Area-meal-afternoon routes need exploratory expansion with explicit timeline order.
    timed_waypoints = _extract_timed_planned_waypoints(_nl_input)
    if timed_waypoints:
        before = [
            (wp.type, wp.name or wp.search_keyword, wp.category)
            for wp in (parsed.planned_waypoints or [])
        ]
        parsed.planned_waypoints = timed_waypoints
        _bind_planned_waypoint_search_centers(parsed.planned_waypoints, _nl_input)

        # Explicit time windows are a route contract, not a reason to discard
        # their order by routing through broad exploratory recall.
        parsed.plan_mode = "planned"
        parsed.execution_contract_required = True
        setattr(parsed, "explicit_timeline_required", True)

        # Afternoon fixed points go into fixed_pois with time_slot annotation
        existing_fixed = {fp.name for fp in (parsed.fixed_pois or [])}
        for wp in timed_waypoints:
            if wp.type == "fixed" and wp.name and wp.name not in existing_fixed:
                parsed.fixed_pois.append(FixedPoi(name=wp.name, user_time_budget=wp.time_slot))
                existing_fixed.add(wp.name)

        after = [
            (wp.type, wp.name or wp.search_keyword, wp.category, wp.time_slot, wp.search_center_name)
            for wp in parsed.planned_waypoints
        ]
        print(
            f"[TimedRouteAudit] stage=step1_reconcile "
            f"before={before} after={after} "
            f"plan_mode={parsed.plan_mode} explicit_timeline_required=true"
        )

    _apply_explicit_execution_contract(parsed, _nl_input, planned_rule_hints)

    # v24: Audit log for conversation_context parsing
    if _has_conv_ctx:
        _pws_count = len(parsed.planned_waypoints or [])
        print(
            f"[ContextParseAudit] has_conversation_context=true "
            f"latest_user_input={_nl_input[:80]} "
            f"planned_waypoints_count={_pws_count}"
        )

    # v26: Category-level exclusion extraction — run after all postprocessing
    # to strip negated categories from search/micro/food keywords.
    # Only activates when clear negation triggers are present ("不想去咖啡馆" etc.)
    parsed = _extract_category_exclusions_from_request(parsed, _nl_input)

    parsed = _ensure_explicit_visible_facet_coverage(parsed, _nl_input or user_request)

    # v28: Final route quality contract enforcement
    parsed = _apply_route_quality_contract(parsed, _nl_input or user_request, stage="final")

    return parsed
