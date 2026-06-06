"""
配置管理模块
合并自 Pydantic Settings 和新框架 config.py
强制限定上海城市服务
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import Literal
import sys
from pydantic import AliasChoices, Field

# 尝试导入 Pydantic Settings，如果失败则使用 dotenv
try:
    from pydantic_settings import BaseSettings
    USE_PYDANTIC = True
except ImportError:
    USE_PYDANTIC = False
    from dotenv import load_dotenv

# 加载环境变量
_MODULE_DIR = Path(__file__).parent
_PROJECT_DIR = _MODULE_DIR.parent
if not USE_PYDANTIC:
    load_dotenv(_PROJECT_DIR / ".env", override=False)
    load_dotenv(_MODULE_DIR / ".env", override=True)

if USE_PYDANTIC:
    class Settings(BaseSettings):
        """应用配置类，强制限定上海城市服务"""

        # 城市限定（强制上海）
        city: Literal["上海"] = "上海"
        city_adcode: str = "310000"  # 上海行政区划代码
        city_location: str = "121.4737,31.2304"  # 上海中心坐标（人民广场）

        # 高德地图API
        gaode_key: str = Field(
            default="",
            validation_alias=AliasChoices("GAODE_API_KEY", "GAODE_KEY"),
        )

        # LLM API配置
        llm_api_key: str = Field(
            default="",
            validation_alias=AliasChoices("DEEPSEEK_API_KEY", "LLM_API_KEY"),
        )
        llm_base_url: str = Field(
            default="https://api.deepseek.com",
            validation_alias=AliasChoices("DEEPSEEK_BASE_URL", "LLM_BASE_URL"),
        )
        llm_model: str = Field(
            default="deepseek-v4-pro",
            validation_alias=AliasChoices("DEEPSEEK_MODEL", "LLM_MODEL"),
        )

        # Redis配置
        redis_url: str = Field("redis://localhost:6379/0", validation_alias="REDIS_URL")

        # 天气API Key (和风天气)
        weather_key: str = Field("", validation_alias="WEATHER_KEY")

        # 服务端口
        app_port: int = Field(8002, validation_alias=AliasChoices("PORT", "APP_PORT"))

        # JWT 密钥 - 必须从环境变量读取，不允许默认值
        SECRET_KEY: str = ""

        class Config:
            env_file = (_PROJECT_DIR / ".env", _MODULE_DIR / ".env")
            env_file_encoding = "utf-8"
            case_sensitive = True
            extra = "allow"

    @lru_cache()
    def get_settings() -> Settings:
        """获取配置单例"""
        settings = Settings()
        
        if not settings.SECRET_KEY:
            print("[FATAL] SECRET_KEY 未配置！请在 .env 中设置 SECRET_KEY")
            sys.exit(1)
        
        insecure_keys = [
            "your-secret-key-change-in-production",
            "your-secret-key",
            "secret",
            "123456",
            "password",
        ]
        
        if settings.SECRET_KEY.lower() in insecure_keys:
            print("[FATAL] SECRET_KEY 使用了不安全的默认值")
            sys.exit(1)
        
        print("[Config] SECRET_KEY loaded")
        return settings
else:
    class Settings:
        """应用配置类，强制限定上海城市服务（Fallback）"""
        def __init__(self):
            self.city: Literal["上海"] = "上海"
            self.city_adcode: str = "310000"
            self.city_location: str = "121.4737,31.2304"
            self.gaode_key: str = os.getenv("GAODE_API_KEY", "") or os.getenv("GAODE_KEY", "")
            self.llm_api_key: str = os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("LLM_API_KEY", "")
            self.llm_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "") or os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
            self.llm_model: str = os.getenv("DEEPSEEK_MODEL", "") or os.getenv("LLM_MODEL", "deepseek-v4-pro")
            self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self.weather_key: str = os.getenv("WEATHER_KEY", "")
            self.app_port: int = int(os.getenv("PORT") or os.getenv("APP_PORT", 8002))
            self.SECRET_KEY: str = os.getenv("SECRET_KEY", "")

    @lru_cache()
    def get_settings() -> Settings:
        """获取配置单例"""
        settings = Settings()
        
        if not settings.SECRET_KEY:
            print("[FATAL] SECRET_KEY 未配置！请在 .env 中设置 SECRET_KEY")
            sys.exit(1)
        
        insecure_keys = [
            "your-secret-key-change-in-production",
            "your-secret-key",
            "secret",
            "123456",
            "password",
        ]
        
        if settings.SECRET_KEY.lower() in insecure_keys:
            print("[FATAL] SECRET_KEY 使用了不安全的默认值")
            sys.exit(1)
        
        print("[Config] SECRET_KEY loaded")
        return settings

# 上海各郊区行政区划代码
DISTRICT_ADMCODES = {
    "黄浦区": "310101",
    "徐汇区": "310104",
    "长宁区": "310105",
    "静安区": "310106",
    "普陀区": "310107",
    "虹口区": "310109",
    "杨浦区": "310110",
    "浦东新区": "310115",
    "闵行区": "310112",
    "宝山区": "310113",
    "嘉定区": "310114",
    "金山区": "310116",
    "松江区": "310117",
    "青浦区": "310118",
    "奉贤区": "310120",
    "崇明区": "310151",
}

SHANGHAI_LAST_METRO_TIME = "22:30"
MUSEUM_CLOSED_DAY = 1  # 周一

SHANGHAI_CENTER = {
    "lng": 121.4737,
    "lat": 31.2304,
    "name": "人民广场"
}

# ═══════════════════════════════════════════════════════════════
# 新框架配置 (从 services/config.py 合并)
# ═══════════════════════════════════════════════════════════════

try:
    from services.day_slots import MAX_TRANSIT_MIN, WEATHER_LOW_SCORE_THRESHOLD
except ImportError:
    MAX_TRANSIT_MIN = 60
    WEATHER_LOW_SCORE_THRESHOLD = 0.5

# ═══════════════════════════════════════════════════════════════
# DeepSeek LLM
# ═══════════════════════════════════════════════════════════════
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-pro"
DEEPSEEK_MAX_TOKENS = 4096
DEEPSEEK_TEMPERATURE = 0.3
# 修复超时问题：默认超时从 15 秒改为 120 秒
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "120"))
DEEPSEEK_INSTRUCTOR_MODE = "JSON"
DEEPSEEK_MAX_RETRIES = 2

DEEPSEEK_MAX_TOKENS_STEP_1_1 = 1200  # 意图解析
DEEPSEEK_MAX_TOKENS_STEP_2_3 = 1500  # enrichment提取

# ═══════════════════════════════════════════════════════════════
# 高德地图 API
# ═══════════════════════════════════════════════════════════════
GAODE_API_KEY = os.getenv("GAODE_API_KEY", "")
GAODE_BASE_URL = "https://restapi.amap.com"
GAODE_TIMEOUT = int(os.getenv("GAODE_TIMEOUT", os.getenv("ROUTE_PLANNER_API_TIMEOUT", "15")))
GAODE_RATE_SLEEP = float(os.getenv("GAODE_RATE_SLEEP", "0.36"))
GAODE_QPS_RETRY_SLEEP = float(os.getenv("GAODE_QPS_RETRY_SLEEP", "2.0"))
GAODE_QPS_MAX_RETRIES = int(os.getenv("GAODE_QPS_MAX_RETRIES", "5"))
GAODE_SHOW_FIELDS = "biz_ext"

GAODE_ENDPOINTS = {
    "around_search": "/v5/place/around",
    "text_search": "/v3/place/text",
    "place_detail": "/v3/place/detail",
    "geocode": "/v3/geocode/geo",
    "weather": "/v3/weather/weatherInfo",
    "transit_route": "/v3/direction/transit/integrated",
    "driving_route": "/v3/direction/driving",
    "walking_route": "/v3/direction/walking",
}

GAODE_RADIUS_CASE_B = 20000
GAODE_RADIUS_NEARBY = int(os.getenv("GAODE_RADIUS_NEARBY", "3000"))
GAODE_RADIUS_CASE_C_SHORT = 20000
GAODE_RADIUS_CASE_C_LONG = 30000
GAODE_RADIUS_MICRO = 2000
GAODE_RADIUS_MEAL = 1800
MEAL_MAX_ROUTE_KM = float(os.getenv("MEAL_MAX_ROUTE_KM", "1.0"))

# ═══════════════════════════════════════════════════════════════
# 博查搜索 API
# ═══════════════════════════════════════════════════════════════
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
BOCHA_BASE_URL = "https://api.bocha.cn/v1"
BOCHA_ENDPOINT = "/web-search"
BOCHA_COUNT = 10
BOCHA_FRESHNESS = "noLimit"
BOCHA_MAX_CONCURRENCY = int(os.getenv("BOCHA_MAX_CONCURRENCY", "10"))
BOCHA_RATE_SLEEP = float(os.getenv("BOCHA_RATE_SLEEP", "0.13"))  # 约 7.7 QPS / 462 QPM，低于 10 QPS / 500 QPM，留安全余量
BOCHA_429_RETRY_SLEEP = float(os.getenv("BOCHA_429_RETRY_SLEEP", "2.0"))
BOCHA_MAX_RETRIES = int(os.getenv("BOCHA_MAX_RETRIES", "3"))
BOCHA_DAILY_LIMIT = int(os.getenv("BOCHA_DAILY_LIMIT", "100000"))

# ═══════════════════════════════════════════════════════════════
# 评分公式参数
# ═══════════════════════════════════════════════════════════════
GAODE_RATING_WEIGHT = 30
TRANSIT_SCORE_WEIGHT = 20

EVENT_SCORES = {
    "ongoing": 15,
    "uncertain": 8,
    "ended": -5,
    "none": 0,
}
HEAT_SCORE_WEIGHT = 20
PREFERENCE_SCORE_WEIGHT = 15
BUDGET_MULTIPLIER = 1.5

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
ANCHOR_INTERNAL_EXCLUDE_TYPES = {"01", "04", "06", "09", "10", "12", "15", "17"}
FULL_DAY_SPLIT_BUDGET_MIN = 240
DEGRADATION_THRESHOLDS = {"rich": 6, "normal": 4, "sparse": 2, "free": 0}
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
