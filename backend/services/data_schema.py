from __future__ import annotations
import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from .day_slots import (
    DURATION_TO_BUDGET, compute_meal_needs, WEATHER_PENALTY,
    WEATHER_LOW_SCORE_THRESHOLD, MAX_TRANSIT_MIN,
    compute_reject_capacities, infer_capacity_from_typecode,
)


###step0 用户个人信息

# v21: Structured user preference profile for UGC reranking
class UserPreferenceProfile(BaseModel):
    interests: list[str] = Field(default_factory=list)          # 历史/自然/美食/购物/艺术/夜景/摄影/城市漫游等
    cuisine_preferences: list[str] = Field(default_factory=list) # 川菜/粤菜/日料/咖啡甜品等
    dietary_restrictions: list[str] = Field(default_factory=list) # 素食/清真/忌辣/低糖等
    ambience_preferences: list[str] = Field(default_factory=list) # 安静松弛/烟火气/浪漫/适合拍照/社区感等
    travel_pace: str = "moderate"                                 # relaxed / moderate / intensive
    crowd_tolerance: str = "moderate"                             # avoid_crowds / moderate / popular_ok
    walking_tolerance: str = "moderate"                           # low / moderate / high
    companion_types: list[str] = Field(default_factory=list)      # 独自/情侣/朋友/亲子/陪父母
    avoid_tags: list[str] = Field(default_factory=list)           # 网红排队店/嘈杂/高消费/过度商业化等


'''用户个人信息，部分变量作为poi筛选的一个参考值'''
class UserProfile(BaseModel):
    nickname: str
    gender: str
    age: int
    activity_pref_tag: list[str]  #这里提供兴趣标签类型，如："二次元""拍照""美食""户外""热门景点""安静""文化"等等。不能填写"亲子""宠物"，这些需要显式地在用户request中提出。
    #如未能从用户request中提取到有效活动标签，则自动传入activity_pref_tag。
    #这里在后面产品完成的时候，要做成固定标签供用户点击选择的方式，而不是让用户自己输入。

    food_pref_tag: list[str]
    #当用户未在request中显示传入其他口味偏好的时候，在搜索餐饮相关poi时，主动传入food_pref_tag。

    permanent_city: list[str]
    #这里提供自动定位，取城市所在地，取到县/区一级。也提供用户自己选择相应的地址。
    #当意图识别为nearby_visit时，传入permanent_city。

    permanent_city_coord: dict[str, float]
    #异步处理：这里基于高德api读取permanent_city的经纬度信息，只读取一次，自动读取并存储。只有当用户主动在设置中进行修改的时候才修改。

    current_device_location: Optional[dict[str, float | str]] = None
    # v18: 保留字段但不再参与路线出发地决策。用户未显式指定出发地时，original_location 固定由 user_profile.home_location 注入。
    home_location: Optional[dict[str, float | str]] = None
    # v18: 唯一路线出发地来源。用户长期规划的默认出发点（家/常驻地址）。未指定时统一由此字段注入 original_location。

    # v21: Structured preference profile
    preference_profile: Optional[UserPreferenceProfile] = None

    #transport_pref这个变量就不需要了，默认公共交通，除非用户在request中说"自驾"或其他驾驶方式，否则默认公共交通。
    
    budget_per_capita: float  #人均消费预算（元），如100.0表示人均100元。作为POI筛选依据，高德返回avg_cost时过滤超预算项，阈值=budget_per_capita*1.5
    poi_likes: list[dict] = Field(default_factory=list)
    poi_dislikes: list[dict] = Field(default_factory=list)
    poi_removes: list[dict] = Field(default_factory=list)


###step1 用户意图解析

'''
── 传递给LLM的prompt ──
输入：user_request + current_time（当前时间，供LLM推断start_time）
不需要传入user_profile，LLM只从用户原话提取字段，不做任何补全判断。

使用instructor库 + Pydantic response_model，输出格式由ParsedIntent的Schema自动注入，无需手写JSON模板。

要求LLM输出以下字段：

【必填字段】
- duration：活动时长，从以下枚举值中选择：
  "a quarter day" / "a half day" / "a full day" / "a day and a half" /
  "two days" / "two and a half days" / "three days"
  提取规则：用户说"逛一会儿"→"a quarter day"，"半天"→"a half day"，
  "一天/出去玩一天"→"a full day"，"两天/周末"→"two days"，以此类推

- crowd_type：出行人群，从以下枚举值中选择：
  "单人" / "情侣" / "家庭" / "朋友" / "团建"
  提取规则：用户说"和家人"→"家庭"，"和闺蜜/哥们"→"朋友"，未提及→"单人"

【可空字段（提取不到则输出null或空列表）】
- start_time：出发时间，格式"YYYY-MM-DD HH:MM"
  提取规则：用户说"下午出发"→当天14:00，"明天早上"→次日09:00，"晚上"→当天19:00，未提及→null

- fixed_pois：用户明确指定的必去地点名列表
  提取规则：用户说"想去外滩"→["外滩"]，"外滩和城隍庙"→["外滩","城隍庙"]，未提及→[]

- raw_keywords：从用户原话中提取的具体意图词（不做大类映射，保留原词）
  提取规则：用户说"逛古镇"→["古镇"]，"二次元文化"→["二次元"]，未提及→[]

- search_keywords：基于raw_keywords+城市直接生成的搜索词（4-6个）
  提取规则：raw_keywords=["古镇"]+城市="上海" → ["上海 古镇 推荐","上海 古镇 攻略","上海 水乡","上海 老街"]
  raw_keywords为空时→[]（由代码兜底）

- food_pref_keywords：用户在request中提到的口味/餐饮偏好
  提取规则：用户说"想吃本帮菜"→["本帮菜"]，"日料"→["日料"]，"随便吃吃"→[]，未提及→[]

- meal_search_keywords：专门用于餐饮POI检索的关键词
  提取规则：用户说"吃吃喝喝/逛吃/探店"→["餐厅","美食","小吃"]，有口味偏好时可生成["本帮菜 餐厅"]

- budget_per_capita：用户在request中明确提出的人均预算上限（元）
  提取规则：用户说"人均150以内"/"餐厅人均消费需要在150元以内"→150.0，未提及时返回null，后续由UserProfile兜底

- micro_keywords：微观POI搜索词，更具体的打卡/体验类关键词（2-4个）
  不同于search_keywords的片区级搜索（"去哪"），micro_keywords用于锚点周边2km内的细节搜索（"玩什么"）
  提取规则：
    "想去逛古镇" → ["古镇 手工艺品", "老街 小吃", "古镇 拍照打卡"]
    "二次元" → ["二次元 周边店", "动漫 主题咖啡", "手办 潮玩店"]
    "想拍照" → ["网红打卡 拍照", "创意园 涂鸦墙", "天台 观景"]
    "带孩子玩" → ["亲子 体验馆", "儿童 手工坊", "室内 游乐"]
    "文艺一点" → ["独立书店", "艺术 展览", "咖啡馆 氛围"]
    "就想逛吃逛吃" → ["网红小吃", "老字号", "夜市 零食"]
    "逛商场" → ["潮牌 买手店", "商场 亲子乐园", "美妆 体验店"]
    未提及具体偏好 → []

- transport_hint：用户提到的交通偏好
  提取规则：用户说"自驾/开车"→"自驾"，未提及→null

- evening_requested：用户是否明确要求晚上活动
  提取规则：用户说"晚上也想去"/"夜景"→true，未提及→false

- other_constraints：其他约束
  提取规则：用户说"不排队""便宜""人少"→对应字符串，未提及→[]

- original_location_label：用户明确指定的出发地名称
  提取规则：用户说"从公司出发"→"公司"，"从同济大学走"→"同济大学"，未提及→null


── LLM输出后的代码后处理（伪代码）──
# 以下所有补全逻辑均由代码负责，LLM不参与判断

# 1. start_time：未提取到则注入当前时间
if parsed_intent.start_time is None:
    parsed_intent.start_time = datetime.datetime.now()

# 2. original_location：未提取到则逐级降级
if parsed_intent.original_location_label is not None:
    parsed_intent.original_location = gaode_geocode(original_location_label)
elif user_profile.current_device_location is not None:
    parsed_intent.original_location = user_profile.current_device_location
else:
    parsed_intent.original_location = user_profile.permanent_city_coord  # 降级为常驻城市坐标
# 若仍为None → 输出"无法获取您的出发位置，请开启定位或指定出发地"

# 3. search_keywords：为空时逐级兜底
if len(parsed_intent.search_keywords) == 0:
    if len(parsed_intent.raw_keywords) > 0:
        city = user_profile.permanent_city[0]
        parsed_intent.search_keywords = [f"{city} {kw}" for kw in parsed_intent.raw_keywords]
    elif len(user_profile.activity_pref_tag) > 0:
        city = user_profile.permanent_city[0]
        parsed_intent.search_keywords = [f"{city} {tag}" for tag in user_profile.activity_pref_tag]
    else:
        # 最终兜底：广普搜索词
        city = user_profile.permanent_city[0]
        parsed_intent.search_keywords = [f"{city} 景点 推荐", f"{city} 好玩的地方", f"{city} 周末 去哪"]

# 4. food_pref_keywords：为空时注入food_pref_tag（供Step3餐饮搜索使用）
if len(parsed_intent.food_pref_keywords) == 0 and len(user_profile.food_pref_tag) > 0:
    parsed_intent.food_pref_keywords = user_profile.food_pref_tag

# 5. micro_keywords：为空时基于raw_keywords生成兜底词
if len(parsed_intent.micro_keywords) == 0:
    if len(parsed_intent.raw_keywords) > 0:
        parsed_intent.micro_keywords = [f"{kw} 打卡" for kw in parsed_intent.raw_keywords[:2]] + \
                                        [f"{kw} 体验" for kw in parsed_intent.raw_keywords[:2]]
    else:
        parsed_intent.micro_keywords = ["景点 打卡", "咖啡 创意园", "展览 拍照"]

# 6. fixed_pois容量预查询（Pipeline分支判断需要）
# 对每个fixed_poi调用高德查询，获取typecode → 推算time_capacity → 计算fixed_budget
fixed_budget = 0.0
for poi_name in parsed_intent.fixed_pois:
    poi_info = gaode_text_search(poi_name, city)
    if poi_info:
        capacity = infer_capacity_from_typecode(poi_info.typecode)
        fixed_budget += DURATION_TO_BUDGET.get(capacity, 0.5)

# 7. time_budget + reject_capacities：代码映射
parsed_intent.time_budget = DURATION_TO_BUDGET[parsed_intent.duration]
parsed_intent.reject_capacities = compute_reject_capacities(parsed_intent.time_budget)

# 8. meal_needs：代码计算
parsed_intent.meal_needs = compute_meal_needs(parsed_intent.start_time, parsed_intent.duration)

# 9. transport_hint：未指定则默认公共交通
if parsed_intent.transport_hint is None:
    parsed_intent.transport_hint = "公共交通"

# 10. 天气约束（Step1.5）— 惩罚方案，不做硬杀
weather = gaode_weather(city, date)
parsed_intent.weather_info = {"day1": {"weather": weather.dayweather, "temp": weather.temp}}
# 评分时对户外POI施加WEATHER_PENALTY惩罚系数，室内POI和fixed_pois不受影响
# 若所有户外POI的final_score均低于WEATHER_LOW_SCORE_THRESHOLD → 输出"当前天气恶劣，建议选择室内活动或改日出行"


═══════════════════════════════════════════════════════════════
Pipeline分支（数据驱动，基于remaining_budget）
═══════════════════════════════════════════════════════════════

remaining_budget = time_budget - fixed_budget

if len(fixed_pois) > 0 and remaining_budget <= 0:
    ── Case A: fixed_pois已填满时间预算 ──
    例："明天想去外滩玩"（外滩=half_day, duration=half_day → 刚好填满）
    → 跳过Step2
    → search_centrality = fixed_pois的位置
    → 直接Step3微观展开

elif len(fixed_pois) > 0 and remaining_budget > 0:
    ── Case B: fixed_pois未填满，需补充 ──
    例："外滩一定要去，其他你来规划"（外滩=half_day, duration=full_day → 还差half_day）
    → Step2: 高德周边搜索(original_location, keywords, radius)
       排除fixed_pois已占的容量类型，避免同类重复
    → 博查排序 + 过滤
    → search_centrality = fixed_pois + 补充的宏观POI
    → Step3微观展开

else:  # len(fixed_pois) == 0
    ── Case C: 无明确目的地，全量搜索 ──
    例："周末想逛古镇" / "出去逛一会儿"
    → Step2: 高德周边搜索(original_location, keywords, radius)
       radius: duration ≤ half_day → 20km, 否则 → MAX_TRANSIT_MIN对应距离
    → 博查排序 + 过滤
    → search_centrality = 筛选通过的宏观POI
    → Step3微观展开

── 零输出保护 ──
# Step2搜索后若过滤结果为0，逐级放宽条件：
# 1. 放宽reject_capacities（如允许half_day的POI）
# 2. 扩大搜索半径
# 3. 仍为0 → 输出"未检索到符合条件的路线，请调整需求后重试"

变量职责：
- original_location：出发点，约束宏观搜索范围（"宏观点不能离出发地太远"）
- search_centrality：Step2输出的宏观锚点列表（list[SearchCentralityItem]），驱动Step3微观搜索
  （以这些点为中心、2km半径检索更小层级POI，进行详细路线规划）
  两者是上下游关系：original_location → 约束宏观搜索 → search_centrality → 驱动微观搜索
'''

class FixedPoi(BaseModel):
    """v3新增：用户指定的固定地点，支持时间预算"""
    name: str                                                        # 地点名，如"外滩"
    user_time_budget: Optional[str] = None                          # v5.2: 用户时间表述，如"一天"/"半天"/"上午"/"下午"/"晚上"；由_parse_user_time_budget解析为resolved_time_budget
    resolved_time_budget: Optional[str] = None                       # 枚举值 quarter_day/half_day/full_day；来源：user_time_budget解析 > typecode映射兜底
    location: Optional[dict] = None                                  # Step1.3预查询后填充 {"lat":float,"lng":float}
    typecode: Optional[str] = None                                   # Step1.3预查询后填充
    # v20: Area stroll expansion
    expansion_required: bool = False                                  # 步行街/商圈 + 逛逛 → 展开内部店铺
    activity_facet: Optional[str] = None                              # "shopping_stroll" | "citywalk" etc.
    # v21: Gaode search backfill fields
    gaode_poi_id: str = ""                                            # 高德POI ID
    address: str = ""                                                 # 高德地址
    district: str = ""                                                # 行政区
    poi_rating: Optional[float] = None                                # 高德评分
    photo_url: str = ""                                               # 高德照片URL
    photo_source: str = ""                                            # 照片来源


class PlannedWaypoint(BaseModel):
    """v5.2 r3: 规划性意图中的有序途经点。支持固定点和占位符两种类型。
    固定点：用户明确指定名称（如麦当劳），直接搜索定位。
    占位符：用户描述品类意图（如买水果），基于上一站终点检索。
    """
    type: str = "fixed"                # "fixed": 有明确名称 | "placeholder": 需搜索定位
    name: Optional[str] = None          # fixed时有值，如麦当劳
    search_keyword: Optional[str] = None  # placeholder时的检索词，如水果；fixed时也可用（搜索辅助）
    category: str = "visit"            # "visit"|"meal"|"cafe"|"purchase"|"service"|"home"|"explore" — 影响停留时间和类型过滤
    stay_minutes: int = 30              # 预估停留时间（分钟）
    search_keywords: list[str] = Field(default_factory=list)  # LLM 为该途经点生成的地图检索词，优先于 search_keyword 使用
    required_terms: list[str] = Field(default_factory=list)    # POI 名称/类型/地址中优先匹配的正向词，用于排序加分
    excluded_terms: list[str] = Field(default_factory=list)    # POI 名称/类型/地址中命中即排除的负向词
    resolved_location: Optional[dict] = None  # 搜索解析后的坐标 {"lat":float,"lng":float}
    resolved_name: Optional[str] = None       # 搜索解析后的实际POI名
    resolved_poi: Optional[dict] = None       # 搜索解析后的完整POI信息，供 planned 快速通道构建 route_data
    # v20: Local reference for X附近的Y patterns — the search center is X, not previous waypoint
    search_center_name: Optional[str] = None  # e.g. "首都医科大学" for "首都医科大学旁边的饭馆"
    search_center_location: Optional[dict] = None  # geocoded location of search_center_name
    time_slot: Optional[str] = None  # morning/afternoon/evening/lunch/dinner
    # v21: Corridor task fields
    placement: str = ""               # "before_destination" | "after_destination" | ""
    corridor_search: bool = False     # True if this task needs corridor search
    role: str = ""                    # "destination" | "corridor_task" | ""


# v21: Structured multi-turn conversation context
class ConversationContext(BaseModel):
    """Pass structured conversation history to LLM without polluting NL text."""
    current_user_request: str = ""
    recent_turns: list[dict] = Field(default_factory=list)  # last N conversation turns
    current_route: dict = Field(default_factory=dict)        # compact route snapshot
    previous_intent: dict = Field(default_factory=dict)      # last ParsedIntent key fields
    structured_params: dict = Field(default_factory=dict)    # include_constraints, intent_patch


class PlanSegment(BaseModel):
    """v5.2 r3: 行程时间线上的一个段，区分探索性和规划性。
    一条完整行程由多个PlanSegment按顺序组成。
    """
    intent: str = "exploratory"         # "exploratory" | "planned"
    # exploratory段字段
    anchor_name: Optional[str] = None   # 探索性锚点名，如南京路步行街
    time_budget: Optional[str] = None   # "half_day" / "quarter_day"
    # planned段字段
    waypoints: list[PlannedWaypoint] = []  # 规划性途经点有序列表


class SubAnchor(BaseModel):
    """v3新增：锚点拆解后的子区域，Step3所有流程以SubAnchor为基本单位"""
    parent_name: str                                                 # 原始锚点名，如"外滩"
    name: str                                                        # 子锚点显示名："外滩南段"/"外滩核心区"；未拆时等于parent_name
    location: dict                                                   # 子锚点中心坐标 {"lat":float,"lng":float}
    time_budget_min: int = 200                                       # 分配的时间预算（分钟）
    capacity: str = "half_day"                                        # 原始锚点容量: full_day/half_day/quarter_day
    internal_pois: list[dict] = []                                   # 锚点内子POI列表（高德搜索+筛选+排序后）
    degradation_level: str = "normal"                                # rich/normal/sparse/free
    degradation_hint: Optional[str] = None                           # 降级提示文本
    variance_ratio: float = 0.0                                      # PCA方差比，用于判断区域形状
    original_anchor_index: int = 0                                   # 原始锚点在day_anchors中的索引
    # Preserve Step2 identity/evidence when an anchor has no internal POIs.
    # Without these fields the visible fallback loses the metadata required by
    # PlanReality and the frontend detail card.
    gaode_poi_id: str = ""
    typecode: str = ""
    category: str = ""
    address: str = ""
    rating: Optional[float] = None
    avg_cost: Optional[float] = None
    photo_url: str = ""
    photo_source: str = ""
    enrichment_text: str = ""
    recall_source: str = ""


class ParsedIntent(BaseModel):
    """
    Step1 LLM意图解析输出 + 代码后处理 + Step1.5天气约束。

    字段分为五类：
    1. LLM提取：duration / start_time / fixed_pois / raw_keywords / search_keywords /
       crowd_type / transport_hint / evening_requested / other_constraints / 
       original_location_label / food_pref_keywords / meal_search_keywords / budget_per_capita /
       day_poi_constraints / meal_constraints / micro_keywords
    2. 代码计算：time_budget / reject_capacities / meal_needs / original_location
    3. Step1.5填充：weather_info
    4. Step2输出：search_centrality

    双框架设计（详见 day_slots.py）：
    1. 时间框架：start_time + duration → 计算meal_needs、查询天气、定位活动时段
    2. Slot框架：time_budget → POI容量匹配（仅统计活动slot，餐饮slot排除不计）
    """

    # ── LLM提取字段 ──
    is_route_planning_request: bool = True             # 是否为出行/游玩/餐饮路线规划请求；无关消息或乱码应为False

    # 时间框架
    duration: str                                      # 必填。活动时长枚举："a quarter day"/"a half day"/"a full day"/组合
    start_time: Optional[datetime.datetime] = None     # 可空。出发时间datetime格式。未提及→代码注入datetime.datetime.now()
    evening_requested: bool = False                    # 是否明确要求晚上活动。未提及→false
    dinner_first: bool = False                         # 是否明确要求先晚餐再活动，如"吃晚饭，然后再去看夜景"

    # 搜索关键词
    raw_keywords: list[str] = []         # 可空。从原话提取的具体意图词，如["古镇","二次元"]。空→代码用activity_pref_tag兜底
    search_keywords: list[str] = []      # 可空。LLM基于raw_keywords扩展的搜索词。总数不超过5个。检索用这个list中的对象进行检索。

    # 人群/偏好
    crowd_type: str = "单人"             # 出行人群："单人"/"情侣"/"家庭"/"朋友"/"团建"，默认"单人"
    fixed_pois: list[FixedPoi] = []      # v3变更：可空。用户明确指定的必去地点，含时间预算。不受天气/容量过滤影响
    delete_list: list[str] = Field(default_factory=list)  # 用户明确排除的POI名称，如"外滩"
    excluded_areas: list[str] = Field(default_factory=list)  # LLM 提取的排除区域/片区，如["外滩片区","陆家嘴"]
    transport_hint: Optional[str] = None # 可空。用户提到的交通偏好，默认公共交通。未提及→代码注入"公共交通"
    other_constraints: list[str] = []    # 可空。其他约束，由LLM提取（如"不排队""便宜"），作为补充关键词，不参与检索，但参与打分。
    day_poi_constraints: list[dict] = []  # 可空。分天固定地点，如{"day_index":2,"poi_name":"中山公园"}，用于Step2按天放置锚点

    # 出发地
    original_location_label: Optional[str] = None  # v18: 可空。用户明确说的出发地名。未指定时统一由 user_profile.home_location 注入；permanent_city_coord 仅兼容兜底；current_device_location 不再参与出发地决策
    resolved_city: Optional[str] = None  # 由后端根据路线出发地/行政区解析并写入；LLM 不得生成

    # 餐饮偏好
    food_pref_keywords: list[str] = []  # 可空。LLM从原话提取的口味/餐饮偏好，如["本帮菜","日料"]。空→代码注入UserProfile.food_pref_tag
    meal_search_keywords: list[str] = []  # 可空。专门用于餐饮POI检索，如["餐厅","美食","本帮菜 餐厅"]。空→代码兜底
    meal_constraints: list[dict] = []  # 可空。餐饮约束，如{"day_index":2,"meal":"lunch","keywords":["日料"],"fixed_poi_name":null}
    budget_per_capita: Optional[float] = None  # 可空。用户request中明确提出的人均预算上限；未提及→后续用UserProfile.budget_per_capita兜底

    # 微观POI搜索词
    micro_keywords: list[str] = []      # 可空。LLM从原话提取的微观体验类搜索词（2-4个），如["古镇 手工艺品","老街 小吃"]。空→代码兜底

    # v14: 主题画像字段
    theme_profile: Optional[str] = None          # LLM 输出的主题枚举 id 或 null
    theme_label: Optional[str] = None             # 用户原始主题中文标签
    theme_route_locked: bool = False             # v22: prevent downstream override of theme_route
    must_recall_target: bool = False             # v22: force recall of a specific target POI type
    theme_confidence: float = 0.0                 # 置信度 0-1
    micro_poi_keywords: list[str] = Field(default_factory=list)     # 微观POI检索类别词
    micro_required_terms: list[str] = Field(default_factory=list)   # 正向命中加分词
    micro_excluded_terms: list[str] = Field(default_factory=list)   # 负向排除词
    micro_diversity_hint: list[str] = Field(default_factory=list)   # 子簇多样性提示
    custom_theme_profile: dict[str, Any] = Field(default_factory=dict)  # 自定义兜底主题

    # ── v20: Multi-theme facet support ──
    multi_theme_requested: bool = False
    theme_facets: list[dict[str, Any]] = Field(default_factory=list)
    theme_coverage_policy: str = ""  # "cover_all_explicit_facets" / "cover_best_effort" / ""

    # ── 代码计算字段 ──

    time_budget: float = 0.0            # 活动slot总预算（天），= DURATION_TO_BUDGET[duration]
    reject_capacities: list[str] = []   # 因time_budget不足而排除的POI容量类型，= compute_reject_capacities(time_budget)
    meal_needs: list[str] | list[list[str]] = []  # 餐点需求，= compute_meal_needs(start_time, duration)
    original_location: Optional[dict] = None      # 出发点坐标 {"lat":float,"lng":float,"label":str}，代码通过高德geocode或短期/长期兜底位置填充，最终降级取permanent_city_coord

    # ── Step1.5天气约束 ──

    weather_info: dict[str, dict] = {}  # 按天存储 {"day1": {"weather":"中雨","temp":"18-22℃"}, ...}
    # 评分时对户外POI施加WEATHER_PENALTY惩罚，不做硬杀。室内POI和fixed_pois不受影响。
    # 若所有户外POI的final_score均低于WEATHER_LOW_SCORE_THRESHOLD → 输出天气恶劣提示

    # ── v5.2 r3: 规划性意图 ──
    plan_mode: str = "exploratory"      # "exploratory" | "planned" | "mixed"
    planned_waypoints: list[PlannedWaypoint] = []  # 规划性途经点有序列表（仅planned/mixed模式）
    # 通用行程段（v5.2 r3）：exploratory和planned统一为有序段列表
    plan_segments: list[PlanSegment] = []  # 按时间顺序排列的行程段

    # ── v20: POI category query fields ──
    poi_query_type: str = ""                        # "theme_route" | "poi_category" | "named_poi" | ""
    category_id: Optional[str] = None               # registered CATEGORY_RULES key (e.g. "restaurant", "repair_shop")
    primary_query: str = ""                         # 用户主查询词，如 "古玩市场"、"附近便利店"
    explicit_meal_intent: bool = False              # 是否明确有餐饮意图
    allowed_typecode_prefixes: list[str] = Field(default_factory=list)  # 允许的typecode前缀
    excluded_typecode_prefixes: list[str] = Field(default_factory=list) # 排除的typecode前缀
    primary_required_terms: list[str] = Field(default_factory=list)     # 主POI必须包含的词
    primary_excluded_terms: list[str] = Field(default_factory=list)     # 主POI必须排除的词

    # ── v20: Proximity / location-context fields ──
    # Distinguishes "search center" (X附近的医院) from "destination" (去西直门逛逛).
    search_area_label: Optional[str] = None          # 搜索区域名称，如 "西直门"、"人民广场"
    search_area_location: Optional[dict] = None      # 搜索区域坐标 {"lat":..., "lng":...}
    proximity_requested: bool = False                # 用户是否表达了"附近/周边/旁边"
    proximity_radius_m: Optional[int] = None         # 附近搜索半径（米），默认根据品类决定
    is_search_center_only: bool = False              # search_area 只是搜索中心，不是目的地
    container_constraint: Optional[str] = None        # 容器场景，如“商场里的电玩城”中的商场

    # ── v20: Administrative district constraints ──
    search_area_adcode: Optional[str] = None         # 搜索区域的 adcode（用于行政区硬过滤）
    search_area_scope_type: Optional[str] = None     # administrative_district / business_zone / null
    search_area_hard_constraint: bool = False        # 是否必须严格限制在行政区内

    # ── v20: Ranking modifier ──
    ranking_intent: Optional[str] = None             # popularity / rating / distance / scale / history
    ranking_direction: Optional[str] = None          # asc / desc
    ranking_raw_terms: list[str] = Field(default_factory=list)  # ["最有名", "最热门"]

    # ── v20: Quiet retreat / solitude / relaxation ──
    activity_facet: str = ""                         # "quiet_retreat" | "lawn_rest" | "citywalk" | "photo_checkin" | "waterfront_walk" etc.
    crowd_preference: str = ""                       # "low" | "medium" | "high" — user's crowd density preference
    privacy_preference: str = ""                     # "soft" | "hard" — need for privacy/not being disturbed
    quiet_retreat_requested: bool = False            # Set True when quiet_retreat activity_facet is active

    # ── v21: Feature-based intent (lawn_rest, night_view, shade, water_view etc.) ──
    required_features: list[str] = Field(default_factory=list)  # ["lawn", "sittable", "night_view"] — hard requirements
    preferred_features: list[str] = Field(default_factory=list) # ["shade", "water_view"] — soft preferences
    lawn_rest_requested: bool = False                            # Set True when lawn_rest activity_facet is active
    night_view_requested: bool = False                           # Set True when night_view activity_facet is active
    open_terrace_requested: bool = False                         # Set True when open_terrace activity_facet is active
    local_life_requested: bool = False                           # Set True when local_life / market_local_life is active
    stress_relief_requested: bool = False                        # Set True when stress_relief activity_facet is active
    stress_relief_mode: str = ""                                 # "quiet" | "active" | "creative" | "mixed"
    rest_stop_requested: bool = False                            # Set True when rest_stop activity_facet is active
    corridor_requested: bool = False                             # Set True when corridor task detected
    destination_alias: str = ""                                  # Raw user destination name (e.g., "北航")
    resolved_destination_name: str = ""                          # Resolved destination (e.g., "北京航空航天大学")
    utility_lookup_requested: bool = False                       # Set True when restroom utility lookup
    souvenir_requested: bool = False                             # Set True when souvenir/gift shopping
    rain_shelter_requested: bool = False                         # Set True when rain_shelter activity_facet
    area_scope_required: bool = False                            # Set True for area_route district tours
    search_area_role: str = ""                                   # "container" | "destination" | ""
    heat_shelter_requested: bool = False                         # Set True when heat_shelter activity_facet
    theme_required: bool = False                                 # v21: True when theme must not fallback to generic
    optimization_profile: str = ""                               # v21: "multi_day_fixed_anchor_enhanced" or ""
    requested_days: int = 1                                      # v21: user-requested day count
    preserve_requested_days: bool = False                        # v21: don't compress to fewer days
    red_history_requested: bool = False                          # v21: revolutionary/red history theme
    courtyard_visit_requested: bool = False                      # v21: courtyard/hutong visit
    non_commercial_requested: bool = False                       # v21: non-commercial preference
    overnight_stay_requested: bool = False                       # v21: overnight lodging required
    lodging_required: bool = False                               # v21: lodging/hotel anchor required
    stargazing_requested: bool = False                           # v21: stargazing activity requested
    great_wall_anchor_requested: bool = False                    # v21: Great Wall anchor required
    fruit_picking_requested: bool = False                        # v21: fruit picking requested
    scenic_combo_requested: bool = False                         # v21: scenic combo with picking
    district_recommendation_requested: bool = False              # v21: district recommendation needed
    # ── intent classification ──
    intent_name: str = ""                                        # v22: deterministic intent label (e.g. group_meal_preference_conflict)
    walking_cluster_requested: bool = False                      # v21: walking cluster route
    max_walk_between_pois_min: int = 0                           # v21: max walking minutes between POIs
    route_strategy: str = ""                                     # v21: "walking_cluster_multi_day" / "station_based_itinerary" / "auto_budget_downgrade" / etc.
    transport_constraints: list[dict] = Field(default_factory=list)  # v21: per-period transport constraints
    # ── v22: auto-degrade / clarification control ──
    auto_degrade_required: bool = False                          # v22: skip multi-turn clarification, degrade automatically
    needs_clarification: bool = False                            # v22: set to False to suppress clarification loop
    clarification_required: bool = False                         # v22: explicitly mark that no clarification is needed
    strong_meal_intent: bool = False                             # v22: meal is the primary (or only) intent
    meal_only_request: bool = False                              # v22: user only wants a meal, no sightseeing
    strict_transport_mode: bool = False                          # v22: enforce exact transport (no fallback to taxi/bus)
    station_walk_radius_min: int = 0                             # v22: max walk min from station to POI
    station_anchors: list[str] = Field(default_factory=list)     # v22: metro station anchor names for station_based_itinerary
    conflict_meal_request: bool = False                          # v22: group meal preference conflict
    meal_conflict_detail: dict = Field(default_factory=dict)     # v22: structured meal conflict info
    budget_contradiction_detected: bool = False                  # v22: free route + paid anchors conflict
    budget_mode: str = ""                                        # v22: "free" / "low" / etc.
    conflict_items: list[str] = Field(default_factory=list)      # v22: paid items conflicting with free budget
    paid_items_degraded: list[str] = Field(default_factory=list) # v22: degraded alternatives for paid items
    optional_anchor_candidates: list[str] = Field(default_factory=list)  # v21: optional park/resort anchors
    relaxation_after_route: bool = False                             # v21: hot spring after main itinerary
    hotel_hopping_requested: bool = False                           # v21: multi-area hotel hopping
    early_morning_event_required: bool = False                      # v21: flag-raising/early morning event

    # ── Step2输出 ──

    search_centrality: list["SearchCentralityItem"] = Field(default_factory=list)
    # Step2筛选通过的宏观锚点列表，驱动Step3微观搜索
    # 以这些点为中心、2km半径检索更小层级POI，进行详细路线规划


### step2 搜索与评分

class ExtractedPlace(BaseModel):
    """Step2.1 高德周边搜索返回的原始POI"""
    name: str
    time_capacity: str           # 基于typecode判断：full_day/half_day/quarter_day
    typecode: str
    location: dict               # {"lat": float, "lng": float}
    gaode_poi_id: str
    address: str = ""
    gaode_rating: Optional[float] = None
    avg_cost: Optional[float] = None  # 高德返回的人均消费（元），需show_fields=biz_ext，仅餐饮/酒店/景点/影院类POI返回
    poiweight: Optional[float] = None  # v3新增：高德综合热度权重(0-1)，越高越热门/重要
    photo_url: str = ""
    photo_source: str = ""
    # ── 博查enrichment填充 ──
    has_event: bool = False
    event_name: Optional[str] = None
    event_period: Optional[str] = None
    event_status: str = "none"
    enrichment_text: str = ""
    enrichment_heat: float = 0.0
    bocha_keywords: list[str] = Field(default_factory=list)  # v9: 博查搜索结果中提取的关键词，供微观POI评分使用
    # ── v15: 主题召回与角色分层 ──
    recall_source: str = ""
    poi_role: str = "route_waypoint"
    theme_recall_score: float = 0.0
    theme_subcluster: str = ""
    generic_theme_penalty: float = 0.0
    # ── v20: District/region metadata for administrative filtering ──
    district: str = ""        # adname / district name
    adcode: str = ""          # Gaode adcode
    cityname: str = ""        # city name from Gaode
    pname: str = ""           # province name from Gaode


class ScoredPlace(ExtractedPlace):
    """Step2.2 评分排序后的POI，继承ExtractedPlace所有字段"""
    # ── 评分 ──
    anchor_score: float = 0.0
    enrichment_score: float = 0.0
    weather_penalty: float = 1.0
    final_score: float = 0.0        # = (anchor_score + enrichment_score) * weather_penalty
    # ── 标记 ──
    fixed: bool = False
    final_capacity: str = ""
    transit_from_origin_min: Optional[float] = None


class AnchorPlan(ScoredPlace):
    """Step2输出给用户的推荐锚点，继承ScoredPlace所有字段"""
    final_time_budget: str = ""            # v3新增：quarter_day/half_day/full_day
    recommend_reason: str = ""
    origin_transit: Optional[str] = None  # "从出发点约XX分钟"
    fixed: bool = False                    # v20: 是否为用户明确指定的固定锚点
    primary_target: bool = False           # v20: 是否为主要目标（fixed anchor with explicit name）


class DayPlan(BaseModel):
    day_index: int
    anchors: list[AnchorPlan]
    meal_slots: list[dict] = Field(default_factory=list)
    # 餐饮占位，如[{"meal":"lunch","time_range":[11.5,13.5],"poi_name":None}]
    # Step3搜索餐饮POI时填充poi_name
    anchor_transit_min: dict = Field(default_factory=dict)


class CompletePlan(BaseModel):
    time_budget: float
    fixed_budget: float = 0.0
    remaining_budget: float = 0.0
    day_plans: list[DayPlan]
    delete_list: list[str] = Field(default_factory=list)
    city: str = ""
    transport: str = "公共交通"
    budget_threshold: float = 0.0       # 实际消费过滤阈值。request明确预算时用request；未提及时用用户画像预算*余量系数
    request_budget_per_capita: Optional[float] = None


### Step3 微观POI与路线

class MicroPOI(BaseModel):
    """Step3 搜索到的微观POI（锚点周边2km内的小景点/打卡点）或餐饮POI"""
    name: str
    location: dict
    typecode: str
    gaode_poi_id: str                    # 高德POI ID，后续详情查询或路线规划用
    address: str = ""
    gaode_rating: Optional[float] = None
    avg_cost: Optional[float] = None     # 高德返回的人均消费（元），需show_fields=biz_ext
    photo_url: str = ""
    photo_source: str = ""
    visit_duration_min: int = 60         # 预计游玩时长（分钟）
    is_meal: bool = False                # 是否为餐饮POI
    parent_anchor: str = ""              # 所属锚点名
    indoor_map: str = ""                 # 高德室内地图标记，"1"表示室内POI


### Step2输出的辅助模型

class SearchCentralityItem(BaseModel):
    """Step2筛选通过的宏观锚点项，驱动Step3微观搜索"""
    name: str                           # 锚点名称，如"新天地"
    score: float                        # final_score，用于排序
    location: dict                      # {"lat": float, "lng": float}


class RouteSegment(BaseModel):
    """两个POI之间的路程段"""
    from_poi: str
    to_poi: str
    day_index: int = 0
    transport: str                       # 交通方式，如"步行"/"地铁"/"公交"/"骑行"等，不限于上述几种
    duration_min: float
    distance_km: float
    polyline: list[list[float]] = Field(default_factory=list)  # Folium坐标序列：[lat, lng]
    degraded: bool = False               # v6: 路线获取失败时为 True，polyline 为直线占位
    polyline_source: str = ""            # v6: 路线来源，"fallback_straight" 表示降级直线
    route_error: str = ""                # v7: 路线错误描述，"real_route_unavailable" 等
    transport_options: list[dict[str, Any]] = Field(default_factory=list)  # v18: 首段多交通方案


### v4 新增：先路后点架构数据模型

class RoadSegment(BaseModel):
    """v4: 步行主干线中的一段道路"""
    road_name: str = ""                                            # 道路名称（高德返回，可能为空）
    distance: float = 0.0                                          # 该段距离(米)
    polyline: list[list[float]] = Field(default_factory=list)      # [[lat,lng],...] Folium坐标
    instruction: str = ""                                          # 导航指令文本，如"右转进入XX路"
    action: str = ""                                               # straight/left/right/arrive
    search_center: list[float] = Field(default_factory=list)       # [lng,lat] 沿线POI搜索中心
