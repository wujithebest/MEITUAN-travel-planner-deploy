from __future__ import annotations
"""
一天的Slot与时间窗口定义

双框架设计：
1. 时间框架：一天划分为6个时间窗口（早餐/上午/午餐/下午/晚餐/晚上），
   用于餐点判断、天气检索、活动时段定位
2. Slot框架：仅统计活动窗口（上午/下午/晚上），用于POI容量匹配
   餐饮slot独立存在，不计入time_budget

关键原则：活动slot和餐饮slot完全解耦
- time_budget只统计活动slot，不包含餐饮时间
- 餐饮POI插入时独立占位，不压缩景点游玩时间


完整一天 = 6个窗口 = 8个quarter单位

 ┌──────────┬────────────┬──────────┬────────────┬──────────┬──────────┐
 │ 早餐(1q) │  上午(2q)  │ 午餐(1q) │  下午(2q)  │ 晚餐(1q) │ 晚上(1q) │
 │  7:00    │   9:00     │  12:00   │   14:00    │  18:00   │  20:00   │
 │  -9:00   │  -12:00    │  -14:00  │  -18:00    │  -20:00  │  -22:00  │
 │  餐饮    │   活动     │  餐饮    │   活动     │  餐饮    │  活动*   │
 └──────────┴────────────┴──────────┴────────────┴──────────┴──────────┘
 q = quarter_day单位(约2-3h)    *晚上slot默认不提供，需用户明确要求

 时间框架用途：餐点判断、天气查询、活动时段定位
 Slot框架用途：POI容量匹配（仅统计活动slot，餐饮slot排除）
 ──────────────────────────────────────────────────────────────
 活动 slot 总量：上午(2q) + 下午(2q) + 晚上(1q, opt-in)
 → 不含晚上 = 4q = 1.0 time_budget（对应"a full day"）
 → 含晚上   = 5q = 1.25 time_budget
"""

import datetime
from typing import Optional
from enum import Enum
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════════
# Slot类别 & 时间窗口模型
# ═══════════════════════════════════════════════════════════════

class SlotCategory(str, Enum):
    """Slot类别：决定是否计入time_budget"""
    MEAL = "meal"           # 餐饮slot（早餐/午餐/晚餐），独立占位，不计入time_budget
    ACTIVITY = "activity"   # 活动slot（上午/下午/晚上），计入time_budget


class DaySlot(BaseModel):
    """一天中的单个时间窗口"""
    name: str                           # breakfast / morning / lunch / afternoon / dinner / evening
    time_range: tuple[float, float]     # 时间范围（24h制），如(9.0, 12.0)
    category: SlotCategory              # 餐饮 or 活动
    capacity: Optional[str] = None      # 活动slot可容纳的最大POI容量："half_day" / "quarter_day"
    opt_in: bool = False                # 是否需要用户明确要求才分配（仅evening和breakfast）
    quarter_units: int                  # 该窗口占用的quarter_day单位数


# ── 一天的标准slot模板 ──
STANDARD_DAY_SLOTS: list[DaySlot] = [
    # name         time_range   category           capacity      opt_in  quarters
    DaySlot(name="breakfast",  time_range=(7, 9),    category=SlotCategory.MEAL,     capacity=None,         opt_in=True,  quarter_units=1),
    DaySlot(name="morning",    time_range=(9, 12),   category=SlotCategory.ACTIVITY, capacity="half_day",    opt_in=False, quarter_units=2),
    DaySlot(name="lunch",      time_range=(12, 14),  category=SlotCategory.MEAL,     capacity=None,         opt_in=False, quarter_units=1),
    DaySlot(name="afternoon",  time_range=(14, 18),  category=SlotCategory.ACTIVITY, capacity="half_day",    opt_in=False, quarter_units=2),
    DaySlot(name="dinner",     time_range=(18, 20),  category=SlotCategory.MEAL,     capacity=None,         opt_in=False, quarter_units=1),
    DaySlot(name="evening",    time_range=(20, 22),  category=SlotCategory.ACTIVITY, capacity="quarter_day", opt_in=True,  quarter_units=1),
]


# ═══════════════════════════════════════════════════════════════
# 通勤约束
# ═══════════════════════════════════════════════════════════════

MAX_TRANSIT_MIN: int = 45   # original_location到POI的单程通勤上限（分钟），用于高德周边搜索半径


# ═══════════════════════════════════════════════════════════════
# Duration → Slot映射
# ═══════════════════════════════════════════════════════════════

# duration → time_budget（仅活动slot，餐饮slot排除）
# "a full day" = 上午(half_day) + 下午(half_day) = 0.5 + 0.5 = 1.0
DURATION_TO_BUDGET: dict[str, float] = {
    "a quarter day":       0.25,
    "a half day":          0.5,
    "a full day":          1.0,
    "a day and a half":    1.5,
    "two days":            2.0,
    "two and a half days": 2.5,
    "three days":          3.0,
}

# duration → 小时数（用于餐点窗口计算）
DURATION_HOURS: dict[str, float] = {
    "a quarter day":       2.5,
    "a half day":          5.0,
    "a full day":          9.0,
    "a day and a half":   14.0,
    "two days":           18.0,
    "two and a half days": 23.0,
    "three days":         27.0,
}


# ═══════════════════════════════════════════════════════════════
# 餐点自动计算
# ═══════════════════════════════════════════════════════════════

# 餐点时间窗口（小时），用于自动判断是否需要安排餐点
# 注意：breakfast不自动安排（通常在家吃），仅当用户明确提到早餐需求时才触发
MEAL_WINDOWS: dict[str, tuple[float, float]] = {
    "lunch":   (11.5, 13.5),   # 11:30-13:30
    "dinner":  (17.5, 19.5),   # 17:30-19:30
}


def compute_meal_needs(start_time: datetime.datetime, duration: str) -> list[str] | list[list[str]]:
    """
    基于时间框架自动计算餐点需求。纯计算，零LLM调用。

    逻辑：活动时间范围与餐点窗口有交集 → 需安排该餐点。
    - 13:00 + quarter_day(2.5h) → 13:00-15:30 → 无交集 → []
    - 13:00 + half_day(5h)      → 13:00-18:00 → 交集dinner → ["dinner"]
    - 10:00 + half_day(5h)      → 10:00-15:00 → 交集lunch  → ["lunch"]
    - 09:00 + full_day(9h)      → 09:00-18:00 → 交集lunch+dinner → ["lunch","dinner"]

    多天场景：每天独立计算，结果为嵌套列表
    - "two days" starting 9:00 → [["lunch","dinner"], ["lunch","dinner"]]
    """
    start_hour = start_time.hour + start_time.minute / 60
    hours = DURATION_HOURS[duration]
    days = int(hours // 9) or 1
    result = []
    for day in range(days):
        day_start = start_hour if day == 0 else 9.0
        day_end = day_start + min(hours - day * 9, 9.0)
        day_meals = [meal for meal, (ws, we) in MEAL_WINDOWS.items()
                     if day_start < we and day_end > ws]
        result.append(day_meals)
    return result if len(result) > 1 else result[0]


# ═══════════════════════════════════════════════════════════════
# 天气惩罚
# ═══════════════════════════════════════════════════════════════

# 天气描述 → 户外POI评分惩罚系数（1.0=无惩罚，0.3=重罚但不硬杀）
# 室内POI不受影响，fixed_pois不受任何惩罚
WEATHER_PENALTY: dict[str, float] = {
    "晴":      1.0,
    "多云":    1.0,
    "阴":      1.0,
    "小雨":    0.7,
    "中雨":    0.5,
    "大雨":    0.3,
    "暴雨":    0.2,
    "雷阵雨":  0.4,
    "小雪":    0.7,
    "中雪":    0.5,
    "大雪":    0.3,
}

# 天气惩罚后，所有户外POI的final_score低于此阈值时，输出天气恶劣提示
WEATHER_LOW_SCORE_THRESHOLD: float = 10.0


# ═══════════════════════════════════════════════════════════════
# Typecode → Time Capacity 推断
# ═══════════════════════════════════════════════════════════════

# 高德typecode前缀 → 时间容量推断（与YAML Appendix-C一致）
TYPECODE_CAPACITY_MAP: dict[str, str] = {
    # full_day（≥6h）
    "080500": "full_day",  # 游乐园
    "080300": "full_day",  # 度假村
    "080400": "full_day",  # 动植物园
    # half_day（3-5h）
    "110200": "half_day",  # 风景名胜区
    "110000": "half_day",  # 风景名胜
    "140100": "half_day",  # 博物馆
    "050500": "quarter_day",  # 餐饮（饭店/餐厅/咖啡厅等）— 餐饮走独立meal slot，不计入活动容量
    "080600": "quarter_day",  # 休闲场所
    # quarter_day（1-3h）
    "110100": "quarter_day",  # 公园广场
    "140200": "quarter_day",  # 展览馆
    "190100": "quarter_day",  # 创意园区
}

# 名称关键词 → 容量覆盖（当typecode不确定时，名称命中关键词则覆盖）
CAPACITY_KEYWORDS: dict[str, list[str]] = {
    "full_day": ["迪士尼", "欢乐谷", "乐园", "主题公园", "度假区", "野生动物园", "海洋公园", "环球影城"],
    "half_day": ["博物馆", "动物园", "景区", "滨江", "商圈", "老街", "古街"],
    "quarter_day": ["公园", "广场", "展览馆", "创意园", "路", "街", "咖啡", "谷子", "手办", "潮玩", "卡牌", "一番赏", "书屋", "寄售", "店"],
}


def infer_capacity_from_typecode(typecode: str, poi_name: str = "") -> str:
    """
    根据高德typecode推断POI时间容量。
    名称关键词优先于typecode（高德分类常有偏差），冲突时取更高的容量（宁可高估）。

    与YAML Appendix-C保持一致，供Step1.3 fixed_poi预查询和Step2.2过滤使用。
    """
    # 1. 名称关键词匹配（按 full > half > quarter 优先级，首次命中即停）
    kw_capacity = None
    for capacity in ("full_day", "half_day", "quarter_day"):
        for kw in CAPACITY_KEYWORDS[capacity]:
            if kw in poi_name:
                kw_capacity = capacity
                break
        if kw_capacity:
            break

    # 2. typecode前缀匹配（取前6位）
    tc_capacity = TYPECODE_CAPACITY_MAP.get(typecode[:6])

    # 3. 取两者中容量更高的（宁可高估）
    capacity_order = {"full_day": 3, "half_day": 2, "quarter_day": 1}
    candidates = [c for c in [tc_capacity, kw_capacity] if c is not None]
    if candidates:
        return max(candidates, key=lambda c: capacity_order.get(c, 0))

    return "quarter_day"  # 默认保守估计


def compute_reject_capacities(time_budget: float) -> list[str]:
    """
    根据time_budget计算需要排除的POI容量类型。

    与YAML Appendix-B保持一致：
    - time_budget < 0.5 → 排除full_day和half_day
    - time_budget < 1.0 → 排除full_day
    - time_budget >= 1.0 → 不排除

    供Step1.2后处理和Step2.2过滤使用。
    """
    if time_budget < 0.5:
        return ["full_day", "half_day"]
    elif time_budget < 1.0:
        return ["full_day"]
    else:
        return []
