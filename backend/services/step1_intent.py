from __future__ import annotations
import asyncio
import datetime as dt
import json
import re

from pydantic import BaseModel

from . import config
from .api_client import call_llm, gaode_geocode, gaode_text_search, gaode_weather
from .data_schema import FixedPoi, ParsedIntent, PlannedWaypoint, PlanSegment, UserProfile
from .day_slots import DURATION_TO_BUDGET, compute_meal_needs, compute_reject_capacities, infer_capacity_from_typecode
from .utils import PipelineLogger, ZeroOutputError, emit_status, haversine_km


INCOMPLETE_REQUEST_TEXT = "消息似乎不全面，可以再说得详细一点吗~"
LATE_NEARBY_REQUEST_TEXT = (
    "现在时间比较晚，附近可逛地点可能较少。"
    "可以补充夜景、夜宵或散步等夜间偏好，或者改成明天白天出发。"
)
PAST_TIME_TOLERANCE_MINUTES = 15
LATE_NEARBY_START_HOUR = 22
LATE_NEARBY_END_HOUR = 7

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
    "带孩子", "遛娃", "带娃", "亲子",
    "约会", "聚餐", "团建", "聚会",
    "一个人", "独处", "放空", "发呆",
    "散步", "慢跑", "跑步", "健身",
]
# === v6 扩展：季节天气类 ===
WEATHER_SCENE_TOKENS = [
    "下雨", "雨天", "阴雨", "有雨", "下雨天", "避雨",
    "刮风", "大风", "降温", "冷", "热", "暴晒",
    "春天", "夏天", "秋天", "冬天", "梅雨",
]
KNOWN_POIS = [
    "外滩",
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
        "typecodes": ["060400", "060401", "060402"],
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
        "tokens": ["带孩子", "遛娃", "带娃", "亲子",
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
                  "一个人", "独处", "放空", "发呆",
                  "散步", "慢跑", "跑步", "健身"],
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


def _duration_hint_for_llm(user_request: str) -> str:
    duration = _duration_from_request(user_request)
    if duration:
        return f'用户原文包含关键词，duration应为"{duration}"'
    return "未检测到明确的时长关键词，请从上下文推断"


def _duration_from_request(user_request: str) -> str | None:
    # ── v5.2: 多时段检测优先——用户同时提到上午+下午/晚上，说明要玩一整天 ──
    has_morning = bool(re.search(r"上午|早上|一上午", user_request))
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


def _is_late_nearby_hour(value: dt.datetime) -> bool:
    hour = _hour_value(value)
    return hour >= LATE_NEARBY_START_HOUR or hour < LATE_NEARBY_END_HOUR


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


def _enforce_late_nearby_guard(parsed: ParsedIntent, user_request: str, current_time: dt.datetime) -> None:
    if not parsed.start_time:
        return
    if not _is_late_nearby_hour(parsed.start_time):
        return
    if _is_casual_nearby_request(user_request):
        raise ZeroOutputError(LATE_NEARBY_REQUEST_TEXT)


def _apply_keyword_overrides(parsed: ParsedIntent, user_request: str, city: str) -> ParsedIntent:
    city_short = city[:-1] if city.endswith("市") else city
    lowered = user_request.lower()

    # v6 Layer 2: 检测强餐饮意图 — 有明确就餐需求时，不追加快闪游玩关键词
    has_explicit_meal = (
        bool(parsed.food_pref_keywords)
        or bool(parsed.meal_search_keywords)
        or any(token.lower() in lowered for token in STRONG_MEAL_TOKENS)
    )

    # v6: 检测"附近/待会儿"距离约束
    has_nearby_distance = any(token in lowered for token in ["附近", "周边", "待会儿", "一会儿", "马上", "现在"])
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
        if profile.get("meal"):
            parsed.meal_search_keywords = _append_unique(parsed.meal_search_keywords, profile["meal"], limit=6)
    return parsed


def _append_fixed_poi_from_request(parsed: ParsedIntent, user_request: str) -> ParsedIntent:
    existing_names = {fp.name for fp in parsed.fixed_pois}
    for poi in sorted(KNOWN_POIS, key=len, reverse=True):
        if poi in user_request and not any(poi in en or en in poi for en in existing_names):
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
        for pattern in NEGATIVE_POI_PATTERNS:
            if re.search(pattern, window):
                parsed.fixed_pois = [fp for fp in parsed.fixed_pois if fp.name != poi]
                if poi not in parsed.delete_list:
                    parsed.delete_list.append(poi)
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
    if any(token in name for token in ["附近", "周边", "餐厅请帮我找", "帮我找", "找一家"]):
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
    if any(token in user_request for token in ["晚饭", "晚餐", "晚间吃", "吃个晚饭", "吃晚饭"]):
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
    # v5.2 r5: 本地生活路线规划始终优先设备位置（nearby visit），与time_budget无关
    device_location = getattr(user_profile, "current_device_location", None)
    home_location = getattr(user_profile, "home_location", None)
    permanent_city_coord = getattr(user_profile, "permanent_city_coord", None)
    return device_location or home_location or permanent_city_coord


async def _llm_parse(
    user_request: str,
    current_time: dt.datetime,
    plan_mode: str = "exploratory",
    planned_rule_hints: list[PlannedWaypoint] | None = None,
) -> ParsedIntent:
    time_str = current_time.strftime("%Y-%m-%d %H:%M")

    # v6: 构造 rule hints 文本，帮助 LLM 更稳定地提取 planned_waypoints
    planned_rule_hints_text = ""
    if plan_mode == "planned" and planned_rule_hints:
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
    planned_waypoints_section = ""
    planned_waypoints_field = ""
    planned_waypoints_step = ""
    if plan_mode == "planned":
        planned_waypoints_field = (
            "\n"
            "14. planned_waypoints (object[]) — 有序途经点列表 ⚠️ 精准规划/连续决策时必填\n"
            '   用户表达了一系列按顺序执行的动作时（如"先X，然后Y，再Z"），提取为有序途经点。\n'
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
            '   通用提取原则：先识别用户真正想完成的动作，再映射成可搜索POI类型。不要把语气词、路线词、位置词当成POI。\n'
            '   生活服务映射：理发/理个发/剪头发/美发/洗剪吹→category=service，search_keyword="理发店"，search_keywords=["理发店","美发店","发廊","剪发","发型设计"]，required_terms 必须包含理发/美发/发廊/剪发/造型/发型，excluded_terms 必须排除快递、收发室、驿站、菜鸟、丰巢、代收、物流、打印快印、维修、开锁、洗衣、房产中介等泛生活服务。\n'
            '   采购映射：买药→"药店"；买花→"花店"；买蛋糕/面包→"蛋糕店"/"面包店"；买饮料零食→"便利店"；买菜/生鲜→"生鲜超市"/"菜市场"。\n'
            '   餐饮映射：简单吃饭→"餐厅/小吃/面馆/快餐"；夜宵→"夜宵/烧烤/小吃"；明确菜系如日料/火锅/川菜则保留菜系。\n'
            '   休闲映射：看电影→"电影院"；唱歌→"KTV"；散步→"公园/滨江步道"；喝咖啡→category=cafe；喝酒小坐→"酒吧/清吧"。\n'
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
            'search_keywords: ["上海 日料", "上海 日本料理", "上海 寿司"]\n'
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
            'search_keywords: ["上海 水果店", "上海 生鲜超市", "上海 餐厅", "上海 小吃", "上海 面馆"]\n'
            'planned_waypoints: [{"type":"placeholder","search_keyword":"水果店","category":"purchase","stay_minutes":20,"search_keywords":["水果店","生鲜超市","超市"],"required_terms":["水果","鲜果","生鲜","超市"],"excluded_terms":["快印","打印","数码","摄影","复印"]},{"type":"placeholder","search_keyword":"餐厅","category":"meal","stay_minutes":40,"search_keywords":["餐厅","小吃","面馆","快餐"],"required_terms":["餐厅","饭店","小吃","面馆","快餐"],"excluded_terms":["咖啡","奶茶","茶饮","甜品","面包"]}]\n'
            '说明："买点水果"和"简单吃晚饭"是两个独立途经点；不要把咖啡茶饮当作正餐，不要把快印数码店当作水果采购。\n'
            "\n"
            "【示例7 — planned 生活服务+短休】\n"
            '输入："回家前想理个发，附近如果有不错的咖啡店也可以坐一会儿"\n'
            'raw_keywords: ["理发", "咖啡"]\n'
            'search_keywords: ["上海 理发店", "上海 美发店", "上海 咖啡店"]\n'
            'planned_waypoints: [{"type":"placeholder","search_keyword":"理发店","category":"service","stay_minutes":45,"search_keywords":["理发店","美发店","发廊","剪发","发型设计"],"required_terms":["理发","美发","美容美发","发廊","剪发","造型","发型","洗剪吹"],"excluded_terms":["宠物","培训","学校","收发室","收发","快递","驿站","菜鸟","丰巢","快递柜","代收","自提","包裹","物流","货运","配送","派送","邮政","邮局","打印","快印","复印","图文","维修","开锁","搬家","洗衣","房产","中介","通讯","营业厅"]},{"type":"placeholder","search_keyword":"咖啡","category":"cafe","stay_minutes":25,"search_keywords":["咖啡店","咖啡"],"required_terms":["咖啡","Coffee","星巴克","瑞幸","Manner"],"excluded_terms":["奶茶","茶饮"]}]\n'
            '说明："回家前/附近"是路线语境，不要提取成"家"；真实需求是理发店和咖啡店。\n'
            "\n"
            "【示例8 — planned 多生活任务】\n"
            '输入："下班后先去药店买点感冒药，再买束花，最后回家"\n'
            'raw_keywords: ["药店", "花店", "回家"]\n'
            'planned_waypoints: [{"type":"placeholder","search_keyword":"药店","category":"purchase","stay_minutes":15,"search_keywords":["药店","大药房"],"required_terms":["药店","大药房","医药"],"excluded_terms":["宠物","诊所"]},{"type":"placeholder","search_keyword":"花店","category":"purchase","stay_minutes":15,"search_keywords":["花店","鲜花店"],"required_terms":["花店","鲜花","花艺"],"excluded_terms":["花鸟市场"]},{"type":"fixed","name":"家","category":"home","stay_minutes":0}]\n'
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
                "<critical_rules>\n"
                "1. 严禁推断、联想或补全用户未明确表达的内容。用户没说吃的，raw_keywords/food_pref_keywords/meal_search_keywords 必须为空。\n"
                "2. duration 严格遵守枚举值映射：用户说\"一天/1天/一日/玩一天\"→\"a full day\"，说\"两天/周末\"→\"two days\"。不允许根据\"晚上\"推断多天。\n"
                "3. search_keywords 只能基于 raw_keywords 展开，不能凭空生成用户没提到的类别。\n"
                "4. 排除项提取：当用户明确说\"不去XX\"\"不要有XX\"\"排除XX\"\"XX去过了/别再安排\"\"XX不用了\"\"跳过XX\"\"把XX去掉\"\"XX别安排了\"等否定表达时，必须把被排除的地点/景区/餐厅名提取到 delete_list 中。这是强约束——如果漏提 exclude 项，后续路线规划会错误地包含用户明确拒绝的地点。\n"
                "</critical_rules>"
            ),
        },
        {
            "role": "user",
            "content": (
                f"<context>当前时间：{time_str}。"
                f"系统预检测：{_duration_hint_for_llm(user_request)}"
                f"当前模式：{plan_mode}（{'精准规划，需提取planned_waypoints' if plan_mode == 'planned' else '自由探索，无需planned_waypoints'}）</context>\n"
                + planned_rule_hints_text +
                "\n"
                f"<user_input>{user_request}</user_input>\n"
                "\n"
                "<task>从用户输入中提取以下字段，用于后续POI检索和路线规划。</task>\n"
                "\n"
                "<field_definitions>\n"
                "1. is_route_planning_request (bool)\n"
                "   用户是否在请求出行/游玩/餐饮/路线/行程规划。闲聊、命令、乱码、问候、天气闲聊、事实问答返回 false。\n"
                "\n"
                "2. duration (string) — 严格枚举值\n"
                "   a quarter day | a half day | a full day | a day and a half | two days | two and a half days | three days\n"
                "   判断依据：逛一会儿/转转→a quarter day；半天→a half day；一天/出去玩→a full day；两天/周末→two days\n"
                '   ⚠️ 多时段组合规则：用户同时提到两个以上时段（如"上午+下午""上午+晚上""下午+晚上"）→a full day，不要拆成多个half_day。\n'
                "\n"
                "3. raw_keywords (string[]) — 用户原词 ⚠️ 只提取用户明确说出的，严禁推断\n"
                '   "逛古镇"→["古镇"]，"二次元"→["二次元"]。只保留实义词，去掉"逛/去/玩玩"等虚词。\n'
                '   "我想去外滩拍夜景"→["外滩","夜景"]，不要添加用户没说的词如"美食""本帮菜"。\n'
                '   如果用户只说景点/拍照，raw_keywords中不要出现餐饮类词汇。\n'
                "\n"
                "4. search_keywords (string[]) — 地图POI检索词 ⚠️ 见下方&lt;examples&gt;\n"
                '   把出行意图转成"城市+类目/场景"格式的可检索关键词。\n'
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
                + planned_waypoints_field +
                "</field_definitions>\n"
                "\n"
                "<examples>\n"
                "以下展示 search_keywords 的生成规则——把出行意图转成具体可检索的\"城市+类目/场景\"：\n"
                "\n"
                "【示例1】\n"
                '输入："周末想去上海逛古镇"\n'
                'search_keywords: ["上海 古镇 推荐", "上海 古镇 攻略", "上海 水乡", "上海 老街"]\n'
                'micro_keywords: ["古镇 手工艺品", "老街 小吃", "古镇 拍照打卡"]\n'
                '说明：古镇→展开为"古镇推荐/攻略/水乡/老街/手工艺品/小吃/拍照打卡"\n'
                "\n"
                "【示例2】\n"
                '输入："想去商场购物逛街买东西"\n'
                'search_keywords: ["上海 购物中心", "上海 商场", "上海 商圈", "上海 商业广场"]\n'
                'micro_keywords: ["商场 逛街", "购物中心 打卡"]\n'
                '说明：购物→"购物中心/商场/商圈/商业广场"，只用购物类词，不混入餐饮\n'
                "\n"
                "【示例3】\n"
                '输入："找好吃的餐厅，顺便逛逛拍照打卡的地方"\n'
                'search_keywords: ["上海 美食", "上海 餐饮", "上海 拍照 打卡", "上海 网红打卡"]\n'
                'micro_keywords: ["美食 探店", "网红打卡 拍照"]\n'
                "说明：吃喝+拍照→餐饮类+\"拍照打卡/网红打卡\"，两类意图分别生成\n"
                "\n"
                "【示例4 — 反例】\n"
                '输入："明天想去外滩玩一天，晚上在外滩拍夜景"\n'
                'duration: "a full day"  ← 注意：晚上是同一天的晚间，不是第二天！\n'
                'evening_requested: true\n'
                'raw_keywords: ["外滩", "夜景"]  ← 用户没提餐饮，不出现"本帮菜""美食"等\n'
                'search_keywords: ["上海 外滩 攻略", "上海 夜景 拍照", "上海 黄浦江 观景"]\n'
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
                'search_keywords: ["上海 旅游 攻略", "上海 景点 推荐", "上海 打卡", "上海 美食"]\n'
                "说明：用户明确排除外滩——已去过+不要包含→delete_list=[\"外滩\"]。duration=两天周末。\n"
                "\n"
                "【示例6 — 多排除项+餐饮偏好】\n"
                '输入："三天上海深度游，迪士尼、东方明珠、城隍庙都去过了，别安排了，想去没去过的地方，尤其想吃地道本帮菜。"\n'
                'duration: "three days"\n'
                'is_route_planning_request: true\n'
                'delete_list: ["迪士尼","东方明珠","城隍庙"]\n'
                'food_pref_keywords: ["本帮菜"]\n'
                'raw_keywords: ["上海","深度游","本帮菜","没去过的地方"]\n'
                'search_keywords: ["上海 深度游 攻略","上海 小众景点","上海 本帮菜 餐厅","上海 老街 弄堂","上海 博物馆"]\n'
                "说明：三个地点明确排除；餐饮偏好提取本帮菜；\"没去过的地方\"→search_keywords偏小众/深度。\n"
                "\n"
                "规则总结：\n"
                '- 使用"城市+具体地点类型/场景/活动"，不用"开心/放松/随便逛"等抽象词\n'
                "- 不编造用户未提到的具体POI名称\n"
                "- 只说购物→只生成购物类词；只说吃喝→只生成餐饮类词；两者都提→同时包含\n"
                "</examples>\n"
                "\n"
                "<thinking_steps>\n"
                "按以下顺序逐步提取：\n"
                "1. 判断 is_route_planning_request：是否涉及出行/路线/游玩/餐饮\n"
                "2. 识别 duration：根据时长描述词选择枚举值\n"
                "3. 提取 raw_keywords（用户原词）和 fixed_pois（具体地名）\n"
                "4. 检测排除项 delete_list：扫描整段话中所有否定表达，识别被排除的具体地名。地名不在用户原话中出现的不要编造。\n"
                "5. 按&lt;examples&gt;规则生成 search_keywords 和 micro_keywords\n"
                + planned_waypoints_step +
                "6. 依次提取 start_time、original_location_label、food_pref_keywords、meal_search_keywords、meal_constraints、budget_per_capita、day_poi_constraints\n"
                "7. 注意：不执行任何计算（时间预算、餐点窗口、容量过滤均交给后续工具）\n"
                "</thinking_steps>\n"
                "\n"
                "<format>\n"
                "严格按 response_model (ParsedIntent) 返回结构化JSON。\n"
                '若 is_route_planning_request=false，duration填"a quarter day"，其余可空字段填null或[]。\n'
                "</format>"
            ),
        },
    ]
    return await call_llm(
        response_model=ParsedIntent,
        messages=messages,
        max_tokens=config.DEEPSEEK_MAX_TOKENS_STEP_1_1,
        temperature=config.DEEPSEEK_TEMPERATURE,
        max_retries=config.DEEPSEEK_MAX_RETRIES,
    )


CATEGORY_TOKENS = {
    "美食", "餐厅", "小吃", "推荐", "攻略", "打卡", "拍照", "游玩", "购物", "逛街",
    "周边", "手工艺品", "特色美食", "景点", "公园", "博物馆", "特产", "一日游",
    "商场", "商圈", "步行街", "古镇", "老街", "水乡", "夜景", "网红", "探店",
    "火锅", "日料", "本帮菜", "咖啡", "下午茶", "酒吧", "书店", "创意",
    "展览", "演出", "话剧", "音乐剧", "科技馆", "天文馆",
}


async def _detect_destination_from_keywords(search_keywords: list[str], origin: dict, city: str) -> list[str]:
    """从search_keywords中检测地名前缀，geocode后若离origin够远则加入fixed_pois"""
    if not search_keywords or not origin:
        return []
    detected = []
    seen: set[str] = set()
    for kw in search_keywords[:8]:
        tokens = kw.split()
        for n in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:n])
            if candidate in CATEGORY_TOKENS:
                continue
            if candidate in seen:
                break
            seen.add(candidate)
            try:
                loc = await gaode_geocode(candidate, city=city)
                if loc:
                    dist = haversine_km(origin, loc)
                    if dist > 5.0:
                        detected.append(candidate)
                break
            except Exception:
                continue
        if len(detected) >= 3:
            break
    return detected


async def _postprocess(parsed: ParsedIntent, user_request: str, user_profile: UserProfile, current_time: dt.datetime) -> ParsedIntent:
    city = user_profile.permanent_city[0] if user_profile.permanent_city else "上海市"
    looks_like_route = _looks_like_route_request(user_request)
    if not parsed.is_route_planning_request and not looks_like_route:
        raise ZeroOutputError(INCOMPLETE_REQUEST_TEXT)
    if looks_like_route:
        parsed.is_route_planning_request = True

    request_duration = _duration_from_request(user_request)
    if request_duration:
        parsed.duration = request_duration

    # v5.3: 跨时段组合规则 — 用户同时提到两个以上时段（如上午+下午+晚上）→ full_day
    _has_morning = bool(re.search(r"上午|早上|一上午", user_request))
    _has_afternoon = bool(re.search(r"下午|一下午", user_request))
    _has_evening = bool(re.search(r"晚上|夜里|夜间|傍晚", user_request))
    _period_count = sum([_has_morning, _has_afternoon, _has_evening])
    if _period_count >= 2 and parsed.duration != "a full day":
        # 防御：即使 LLM 或覆盖逻辑未正确设置，强制纠正
        print(f"[DEBUG step1 WARN] 多时段({_period_count})但 duration={parsed.duration}，强制修正为 a full day")
        parsed.duration = "a full day"

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
    _enforce_late_nearby_guard(parsed, user_request, current_time)

    if parsed.original_location_label and not _has_explicit_origin(user_request):
        parsed.original_location_label = None

    if parsed.original_location_label:
        parsed.original_location = await gaode_geocode(parsed.original_location_label, city=city)
    if not parsed.original_location:
        parsed.original_location = _fallback_origin(parsed, user_profile)

    parsed = _apply_keyword_overrides(parsed, user_request, city)
    parsed = _append_fixed_poi_from_request(parsed, user_request)
    parsed = _exclude_pois_from_request(parsed, user_request)

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
            parsed.search_keywords = [f"{city} {kw}" for kw in parsed.raw_keywords]
        elif user_profile.activity_pref_tag:
            parsed.search_keywords = [f"{city} {tag}" for tag in user_profile.activity_pref_tag]
        else:
            parsed.search_keywords = [f"{city} 景点 推荐", f"{city} 好玩的地方", f"{city} 周末 去哪"]
    if "室内优先" in parsed.other_constraints:
        city_short = city[:-1] if city.endswith("市") else city
        indoor_search = [
            f"{city_short} 室内 景点",
            f"{city_short} 博物馆 展览",
            f"{city_short} 美术馆 书店",
            f"{city_short} 商场 室内",
        ]
        indoor_micro = ["室内 打卡", "博物馆 展览", "美术馆 书店", "商场 逛街"]
        parsed.search_keywords = _append_unique(indoor_search, parsed.search_keywords, limit=8)
        parsed.micro_keywords = _append_unique(indoor_micro, parsed.micro_keywords, limit=6)

    explicit_meals = _explicit_meals(user_request)
    if _dinner_before_activity(user_request):
        parsed.dinner_first = True
    parsed.meal_constraints = _merge_constraints(
        _meal_constraints_from_request(user_request),
        parsed.meal_constraints,
        ["day_index", "meal", "fixed_poi_name"],
    )
    DIRECTION_WORDS = {"外面", "旁边", "附近", "周边", "出去", "外面吃", "出去吃"}
    for constraint in parsed.meal_constraints:
        name = str(constraint.get("fixed_poi_name") or "").strip()
        if name in DIRECTION_WORDS or len(name) <= 2:
            constraint["fixed_poi_name"] = None
    request_food_keywords = _request_food_keywords_from_constraints(parsed.meal_constraints)
    parsed.food_pref_keywords = _normalize_food_preferences(parsed.food_pref_keywords)
    parsed.food_pref_keywords = _append_unique(parsed.food_pref_keywords, request_food_keywords, limit=6)
    if not parsed.food_pref_keywords and user_profile.food_pref_tag:
        parsed.food_pref_keywords = list(user_profile.food_pref_tag)
    parsed.budget_per_capita = _budget_from_request(user_request) or parsed.budget_per_capita

    if not parsed.micro_keywords:
        if parsed.raw_keywords:
            parsed.micro_keywords = [f"{kw} 打卡" for kw in parsed.raw_keywords[:2]] + [f"{kw} 体验" for kw in parsed.raw_keywords[:2]]
        else:
            parsed.micro_keywords = ["景点 打卡", "咖啡 创意园", "展览 拍照"]

    parsed.reject_capacities = compute_reject_capacities(parsed.time_budget)
    parsed.meal_needs = compute_meal_needs(parsed.start_time, parsed.duration)
    parsed.meal_needs = _merge_meal_needs(parsed.meal_needs, explicit_meals)
    parsed.meal_needs = _merge_constraint_meals(parsed.meal_needs, parsed.meal_constraints)
    parsed.meal_search_keywords = _normalize_meal_search_keywords(parsed, user_request)
    if parsed.transport_hint is None:
        parsed.transport_hint = "公共交通"
    if not parsed.crowd_type:
        parsed.crowd_type = "单人"

    # [DEBUG-雨天半天] 临时调试日志，确认雨天/半日识别
    print(f"[DEBUG step1] duration={parsed.duration} time_budget={parsed.time_budget}")
    print(f"[DEBUG step1] other_constraints={parsed.other_constraints}")
    print(f"[DEBUG step1] search_keywords={parsed.search_keywords}")
    print(f"[DEBUG step1] micro_keywords={parsed.micro_keywords}")
    print(f"[DEBUG step1] meal_needs={parsed.meal_needs} evening_requested={parsed.evening_requested}")
    print(f"[DEBUG step1] meal_constraints={parsed.meal_constraints}")

    return parsed


async def _fixed_budget(parsed: ParsedIntent, city: str) -> float:
    if not parsed.fixed_pois:
        return 0.0
    await emit_status("正在查询目的地信息...")
    searches = await asyncio.gather(*[gaode_text_search(fp.name, city=city) for fp in parsed.fixed_pois])
    budget = 0.0
    for fp, items in zip(parsed.fixed_pois, searches):
        if items:
            item = items[0]
            fp.location = item.get("location")
            fp.typecode = item.get("typecode", "")
        # v3新增：回填resolved_time_budget（未从user_time_budget解析到的用typecode兜底）
        if fp.resolved_time_budget is None:
            typecode = fp.typecode or ""
            capacity = infer_capacity_from_typecode(typecode, fp.name)
            fp.resolved_time_budget = capacity
        # 兜底的兜底
        if fp.resolved_time_budget is None:
            fp.resolved_time_budget = "half_day"
        budget += DURATION_TO_BUDGET.get(
            {"full_day": "a full day", "half_day": "a half day", "quarter_day": "a quarter day"}[fp.resolved_time_budget],
            0.5,
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


def _fallback_planned_waypoints_from_request(
    user_request: str,
    include_generic: bool = True,
) -> list[PlannedWaypoint]:
    """v6: 确定性 fallback 解析器 — LLM 失败时兜底。

    按 "再 / 然后 / 接着 / 顺便 / , / ， / 、" 切分子句，
    基于关键词规则匹配品类。
    """
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
        (["简单吃", "随便吃点", "对付一口", "垫垫肚子", "找个地方吃"], {"type": "placeholder", "search_keyword": "餐厅", "category": "meal", "stay_minutes": 40}),
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
            # 未匹配的从句，尝试作为 visit
            waypoints.append(PlannedWaypoint(
                type="placeholder",
                search_keyword=clause,
                category="visit",
                stay_minutes=30,
            ))

    return waypoints


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
                "规则：保留用户顺序；回家→home；买水果→purchase；日料→meal；咖啡→cafe；理发→service；search_keyword用具体的检索词（水果店/理发/日料等）\n"
                "返回JSON数组，每个元素含type/name/search_keyword/category/stay_minutes"
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



async def run_step1(
    user_request: str,
    user_profile: UserProfile,
    current_time: dt.datetime,
    logger: PipelineLogger,
    plan_mode: str = "exploratory",  # v5.2 r3: "exploratory" | "planned" — 前端切换按钮传入
) -> ParsedIntent:
    logger.start_step("step_1_1_llm_extract")
    await emit_status("正在解析您的出行意图...")
    # v6: planned 模式只生成 rule hints 辅助 LLM，不再直接使用 fast planned 结果
    planned_rule_hints: list[PlannedWaypoint] = []
    if plan_mode == "planned":
        planned_rule_hints = _fallback_planned_waypoints_from_request(user_request, include_generic=False)
        if planned_rule_hints:
            print(
                "[DEBUG step1] planned rule hints: "
                f"{[(wp.type, wp.name or wp.search_keyword, wp.category, wp.stay_minutes) for wp in planned_rule_hints]}"
            )

    parsed = await _llm_parse(
        user_request,
        current_time,
        plan_mode=plan_mode,
        planned_rule_hints=planned_rule_hints if planned_rule_hints else None,
    )
    parse_source = "llm_with_rule_hints" if planned_rule_hints else "llm"
    await logger.log_step(
        "step_1_1_llm_extract",
        output_count=1,
        details={"source": parse_source},
    )

    logger.start_step("step_1_2_postprocess")
    parsed = await _postprocess(parsed, user_request, user_profile, current_time)
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
    fixed_task = asyncio.create_task(_fixed_budget(parsed, city))
    weather_task = asyncio.create_task(gaode_weather("310000"))
    await emit_status("正在查询天气...")
    fixed_budget, weather_info = await asyncio.gather(fixed_task, weather_task)
    parsed.weather_info = weather_info
    await logger.log_step("step_1_3_fixed_and_weather", output_count=1 if fixed_budget >= 0 else 0)
    # v5.2 r3: 规划性意图处理 — 不再额外调用 LLM
    # planned_waypoints 优先使用 _llm_parse() 第一次提取的结果
    # 若 LLM 未提取（空列表），使用确定性 fallback 兜底，绝不再调第二次 LLM
    if plan_mode == "planned":
        parsed.plan_mode = "planned"
        if not parsed.planned_waypoints:
            parsed.planned_waypoints = _fallback_planned_waypoints_from_request(user_request)
        if not parsed.planned_waypoints:
            parsed.plan_mode = "exploratory"  # 提取失败降级为探索模式
    else:
        parsed.plan_mode = "exploratory"

    return parsed
