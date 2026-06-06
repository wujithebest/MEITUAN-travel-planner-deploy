import os
from pathlib import Path
from dotenv import load_dotenv
from .day_slots import MAX_TRANSIT_MIN, WEATHER_LOW_SCORE_THRESHOLD  # 统一由day_slots.py定义，避免重复

_MODULE_DIR = Path(__file__).parent
_PROJECT_DIR = _MODULE_DIR.parent
load_dotenv(_PROJECT_DIR / ".env", override=False)
load_dotenv(_MODULE_DIR / ".env", override=True)

# ═══════════════════════════════════════════════════════════════
# DeepSeek LLM（兼容 LLM_API_KEY / LLM_BASE_URL 配置）
# ═══════════════════════════════════════════════════════════════
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("LLM_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "") or os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "") or os.getenv("LLM_MODEL", "deepseek-v4-pro")
DEEPSEEK_MAX_TOKENS = 4096          # 全局默认上限，子步骤按需覆盖
DEEPSEEK_TEMPERATURE = 0.3
# 修复超时问题：默认超时从 15 秒改为 120 秒
# 如果 .env 中有 DEEPSEEK_TIMEOUT 则使用该值，否则默认 120 秒
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "120"))
DEEPSEEK_INSTRUCTOR_MODE = "JSON"    # instructor.Mode.JSON
DEEPSEEK_MAX_RETRIES = 2            # Pydantic校验失败自动重试

# 子步骤max_tokens覆盖
DEEPSEEK_MAX_TOKENS_STEP_1_1 = 1200  # 意图解析
DEEPSEEK_MAX_TOKENS_STEP_2_3 = 1500  # enrichment提取

# ═══════════════════════════════════════════════════════════════
# 高德地图 API
# ═══════════════════════════════════════════════════════════════
GAODE_API_KEY = os.getenv("GAODE_API_KEY", "") or os.getenv("GAODE_KEY", "")    # 兼容 GAODE_KEY 和 GAODE_API_KEY
GAODE_BASE_URL = "https://restapi.amap.com"    # 不带版本号，各endpoint自行携带
GAODE_TIMEOUT = int(os.getenv("GAODE_TIMEOUT", os.getenv("ROUTE_PLANNER_API_TIMEOUT", "15")))  # 秒
GAODE_RATE_SLEEP = float(os.getenv("GAODE_RATE_SLEEP", "0.36"))  # 请求间隔（秒），留余量贴近3次/秒
GAODE_QPS_RETRY_SLEEP = float(os.getenv("GAODE_QPS_RETRY_SLEEP", "2.0"))
GAODE_QPS_MAX_RETRIES = int(os.getenv("GAODE_QPS_MAX_RETRIES", "5"))
GAODE_MAX_CONCURRENCY = int(os.getenv("GAODE_MAX_CONCURRENCY", "3"))  # 并发数上限
GAODE_SHOW_FIELDS = "biz_ext"                    # 请求时传此参数以获取人均消费等商业信息

# 高德端点路径
GAODE_ENDPOINTS = {
    "around_search": "/v5/place/around",                          # 周边搜索（v5）
    "text_search": "/v3/place/text",                               # 关键词搜索
    "place_detail": "/v3/place/detail",                            # POI详情
    "geocode": "/v3/geocode/geo",                                  # 地理编码
    "weather": "/v3/weather/weatherInfo",                           # 天气查询
    "transit_route": "/v3/direction/transit/integrated",            # 公交路线
    "driving_route": "/v3/direction/driving",                       # 驾车路线
    "walking_route": "/v3/direction/walking",                       # 步行路线
}

# 搜索半径（米）
GAODE_RADIUS_CASE_B = 20000          # Case B: ~20km
GAODE_RADIUS_NEARBY = int(os.getenv("GAODE_RADIUS_NEARBY", "3000"))
GAODE_RADIUS_CASE_C_SHORT = 20000    # Case C: duration ≤ half_day → 20km
GAODE_RADIUS_CASE_C_LONG = 30000     # Case C: duration > half_day → 30km
GAODE_RADIUS_MICRO = 2000            # Step3微观搜索: 2km
GAODE_RADIUS_MEAL = 1800             # Step3餐饮搜索: 餐前上一地点1.8km内
MEAL_MAX_ROUTE_KM = float(os.getenv("MEAL_MAX_ROUTE_KM", "1.0"))  # v4.1 F3: 餐饮最远1km（从1.8收紧）

# ═══════════════════════════════════════════════════════════════
# 博查搜索 API
# ═══════════════════════════════════════════════════════════════
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
BOCHA_BASE_URL = "https://api.bocha.cn/v1"
BOCHA_ENDPOINT = "/web-search"
BOCHA_COUNT = 10                     # 每次搜索返回结果数量
BOCHA_FRESHNESS = "noLimit"          # 时间范围不限
BOCHA_MAX_CONCURRENCY = int(os.getenv("BOCHA_MAX_CONCURRENCY", "10"))
BOCHA_RATE_SLEEP = float(os.getenv("BOCHA_RATE_SLEEP", "0.13"))  # 约 7.7 QPS / 462 QPM，低于 10 QPS / 500 QPM，留安全余量
BOCHA_429_RETRY_SLEEP = float(os.getenv("BOCHA_429_RETRY_SLEEP", "2.0"))
BOCHA_MAX_RETRIES = int(os.getenv("BOCHA_MAX_RETRIES", "3"))
BOCHA_DAILY_LIMIT = int(os.getenv("BOCHA_DAILY_LIMIT", "100000"))

# ═══════════════════════════════════════════════════════════════
# 评分公式参数
# ═══════════════════════════════════════════════════════════════
GAODE_RATING_WEIGHT = 30             # 高德评分归一化 * 30，满分30
TRANSIT_SCORE_WEIGHT = 20            # max(0, 1 - transit/MAX_TRANSIT) * 20，满分20

EVENT_SCORES = {
    "ongoing": 15,
    "uncertain": 8,
    "ended": -5,
    "none": 0,
}
HEAT_SCORE_WEIGHT = 20               # enrichment_heat * 20，满分20
PREFERENCE_SCORE_WEIGHT = 15         # (matched/total) * 15，满分15

BUDGET_MULTIPLIER = 1.5              # 人均消费阈值余量系数

# ═══════════════════════════════════════════════════════════════
# v3 新增：锚点内搜索与路线排布
# ═══════════════════════════════════════════════════════════════
ANCHOR_INTERNAL_SEARCH_RADIUS = 1500
ANCHOR_SEARCH_RADIUS_BY_CAPACITY = {
    "full_day": 4000,
    "half_day": 3000,
    "quarter_day": 1500,
}
ANCHOR_INTERNAL_TYPES = "110000|110200|080000|140000|050000"
ANCHOR_INTERNAL_EXCLUDE_TYPES = {
    "01", "04", "06", "09", "10", "12", "15", "17"
}
FULL_DAY_SPLIT_BUDGET_MIN = 240
DEGRADATION_THRESHOLDS = {
    "rich": 6,
    "normal": 4,
    "sparse": 2,
    "free": 0,
}
INTERNAL_POI_SCORE_THRESHOLD = 20
VISIT_DURATION_MAP = {
    "110200": 60,
    "140100": 60,
    "110100": 40,
    "140200": 40,
    "190100": 40,
}
DEFAULT_VISIT_DURATION_MIN = 40
WALK_SPEED_KPH = 4.5
WALK_TIME_MIN_FLOOR = 3.0
LINEAR_VARIANCE_THRESHOLD = 0.8

# ═══════════════════════════════════════════════════════════════
# 配对与路线参数
# ═══════════════════════════════════════════════════════════════
PAIRING_MAX_TRANSIT_MIN = 30
ANALYZE_SIZE = 5
POOL_SIZE = 10

# ═══════════════════════════════════════════════════════════════
# v4 新增：先路后点架构参数
# ═══════════════════════════════════════════════════════════════
ROUTE_BACKBONE_ENABLED = True
ROUTE_BACKBONE_MAX_TURNS = 3
ROUTE_BACKBONE_MIN_MAIN_ROAD_RATIO = 0.5
ROUTE_BACKBONE_MAX_WAYPOINTS = 2
ROUTE_BACKBONE_WAYPOINT_INTERVAL_M = 600
ROUTE_BACKBONE_TURN_ANGLE_DEG = 30.0

ROUTE_SEG_MIN_DISTANCE_M = 200
ROUTE_SEG_SEARCH_RADIUS_M = 250
ROUTE_SEG_MAX_PER_QUERY = 15
ROUTE_MAX_POIS_PER_SEGMENT = 6

ROUTE_POI_ALLOWED_TYPES = {
    "110000", "110100", "110200", "110201", "110202", "110203", "110204", "110205",
    "080000", "080100", "080300", "080301", "080302", "080303",
    "140000", "140100", "140200", "140300", "140400", "140500",
    "150000", "150100", "150200",
}

ROUTE_POI_EXCLUDED_TYPES = {
    "050000", "050100", "050200", "050300", "050500",
    "060000", "060100", "060200", "060300", "060400", "060500", "060600", "060700",
    "100000", "100100", "100200",
    "120000", "120100", "120200", "120300",
    "130000", "130100", "130200",
    "150300",
    "190000", "190100",
    "200000", "200100",
}

ROUTE_POI_MEAL_EXCLUDED_TYPES = {
    "060100", "060200", "060300", "060109", "060110", "060115",
}

ROUTE_POI_CAFE_ALLOWED_TYPES = set()

ROUTE_POI_NAME_BLACKLIST = [
    "停车场", "停车楼", "停车位",
    "公交站", "公交车站", "地铁站", "轻轨站",
    "ATM", "取款机",
    "公厕", "厕所", "卫生间",
    "出入口", "入口", "出口",
    "充电桩", "充电站",
    "快递柜", "丰巢",
    "物业", "门岗",
    "垃圾站", "变电站",
    "暂停营业", "已关闭", "已停业",
    "酒吧", "Whisky", "Lounge", "Club", "Bar",
    "停车", "公司",
    "电竞", "网咖", "网吧",
    "KTV", "ktv", "卡拉OK",
    "足浴", "按摩", "SPA", "spa", "洗浴", "采耳",
    "美容", "美发", "理发", "美甲", "纹身",
    "健身", "瑜伽", "拳击", "台球",
    "棋牌", "麻将",
    "脱口秀", "密室", "桌游", "剧本杀",
    "宠物",
    "药店", "药房", "诊所",
    "维修", "开锁", "搬家",
    "学校", "中学", "小学", "大学", "学院", "幼儿园", "托儿所",
    "培训", "教育", "补习", "辅导", "考前",
    "游泳馆", "体育馆", "体育场", "运动场", "球馆",
    "健身", "Fitness", "fitness", "瑜伽", "普拉提", "拳击",
    "医院", "卫生院", "诊所", "养老院", "敬老院",
]

ROUTE_POI_MEAL_NAME_KEYWORDS = [
    "菜馆", "餐厅", "饭馆", "面馆", "火锅", "烧烤",
    "快餐", "小吃", "食堂", "酒楼", "大排档",
    "小笼", "蟹粉", "蟹黄", "蟹点", "烧鸟", "居酒屋",
    "酒场", "本帮面", "点心", "牛排", "面道", "寿司",
    "串烧", "料理", "馄饨", "饺子", "拉面", "烤肉",
    "麻辣", "串串", "煲仔", "茶餐厅", "大酒家",
    "肯德基", "麦当劳", "汉堡王", "必胜客", "德克士", "华莱士",
    "宴", "膳", "苏宴", "酒家", "食府", "私房菜",
    "点心店", "糕点", "烘焙", "面包房",
    "自助", "自助餐", "海鲜", "日料", "铁板",
]

WATERFRONT_KEYWORDS = "滨水 亲水 江边 沿江 河畔 水岸 码头"
WATERFRONT_ANCHOR_KEYWORDS = ["外滩", "滨江", "滨水", "江边", "沿江", "河畔", "水岸", "陆家嘴", "北外滩", "西岸"]
WATERFRONT_WAYPOINT_LNG_SHIFT = 0.003

ROUTE_POI_PASSTHROUGH_TYPES = {"080300", "110201"}
PASSTHROUGH_VISIT_DURATION_MIN = 5
PASSTHROUGH_NAME_KEYWORDS = ["广场", "观景", "平台", "连廊", "长廊", "通道"]

TRANSIT_RATIO_LIMIT = {"full_day": 0.25, "half_day": 0.30, "quarter_day": 0.35}

TYPECODE_VISIT_DURATION = {
    "110000": 60, "110100": 50, "110200": 45,
    "140000": 75, "140100": 90, "140200": 60, "140300": 60, "140400": 75,
    "080000": 45, "080100": 50, "080300": 40,
    "050000": 30, "050100": 45, "050500": 45,
    "150000": 30, "150100": 35, "150200": 35,
    "170000": 40, "170100": 45,
    "060400": 20, "060500": 20, "060600": 15, "060700": 10,
    "DEFAULT": 30,
}

CROSS_RIVER_LNG_THRESHOLD = 0.007
ROUTE_MEAL_SEARCH_RADIUS_M = 1000
ROUTE_MEAL_MAX_STRAIGHT_KM = 1.0

INTER_SEG_DRIVE_KM = 2.0
INTER_SEG_BIKE_KM = 1.0

SUB_ANCHOR_BBOX_PADDING_DEG = 0.003
SUB_ANCHOR_CORRIDOR_WIDTH_KM = 0.3

GAODE_ENDPOINTS_V4 = {
    "regeo": "/v3/geocode/regeo",
    "roadname": "/v3/road/roadname",
    "bicycling_route": "/v4/direction/bicycling",
}

PLANNED_SEARCH_RADIUS_STEPS = [500, 1000, 2000, 3000]
PLANNED_DEFAULT_STAY_MINUTES = {"visit": 45, "meal": 50, "purchase": 15, "explore": 60}
PLANNED_MAX_WAYPOINTS = 10

LOG_DIR = "logs"
LOG_FILENAME_FORMAT = "{YYYYMMDD_HHMMSS}.json"
STATUS_CALLBACK_FORMAT = "[ROUTE_PLANNER]: {message}"

LINEAR_ANCHOR_KEYWORDS = ["步行街", "街", "路", "大道", "巷", "弄", "胡同", "弄堂"]

AREA_TYPECODE_PREFIXES = {"11", "08", "14", "19"}
AREA_NAME_KEYWORDS = ["外滩", "滨江", "古镇", "古街", "广场", "商圈", "海湾", "湿地", "度假区", "景区", "新城", "老街"]
