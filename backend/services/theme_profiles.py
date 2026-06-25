from __future__ import annotations

from typing import Any

from .theme_profile_matcher import (
    get_all_theme_profiles,
    normalize_theme_profile_id,
    build_effective_theme_profile_from_library,
)


def _unique(values: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        clean = str(value).strip()
        if clean and clean not in seen:
            result.append(clean)
            seen.add(clean)
        if limit is not None and len(result) >= limit:
            break
    return result


OFFICIAL_THEME_PROFILES: dict[str, dict[str, Any]] = {
    "art_culture_lifestyle": {
        "label": "文艺 / 艺术文化 / 生活方式",
        "triggers": ["文艺", "文艺感", "艺术感", "艺术氛围", "文化气息", "有氛围", "氛围感", "精神漫游", "城市漫游", "松弛感", "小资", "有格调"],
        "search_terms": ["文艺街区", "艺术展览", "美术馆", "当代艺术中心", "独立书店", "概念书局", "文创园区", "创意街区", "历史风貌区"],
        "recall_queries": [
            "{city} 文艺路线 推荐 M50 武康路 衡复风貌区 西岸 上生新所 田子坊 思南公馆 愚园路",
            "{city} 独立书店 美术馆 电影资料馆 Vintage买手店 精品咖啡 手作市集 推荐",
            "{city} 小众文艺街区 创意园区 艺术空间 买手店 推荐"
        ],
        "destination_anchor_terms": ["M50", "M50创意园", "武康路", "衡复风貌区", "西岸", "西岸美术馆",
            "上生新所", "田子坊", "思南公馆", "愚园路", "新华路", "1933老场坊", "当代艺术博物馆",
            "西岸艺术中心", "龙美术馆", "余德耀美术馆", "复星艺术中心", "上海当代艺术馆"],
        "high_value_micro_terms": ["独立书店", "概念书局", "美术馆", "当代艺术中心", "电影资料馆",
            "艺术影院", "小剧场", "Livehouse", "精品咖啡", "新中式茶馆", "中古店", "Vintage买手店",
            "手作市集", "陶艺工坊", "版画工作室", "黑胶馆", "胶片相机冲洗店"],
        "generic_penalty_terms": ["文化广场", "活动中心", "公园", "广场", "中心", "办公室", "多功能厅"],
        "micro_keywords": ["独立书店", "概念书局", "美术馆", "当代艺术中心", "非遗博物馆", "小剧场", "Livehouse", "黑匣子剧场", "艺术影院", "电影资料馆", "精品咖啡馆", "新中式茶馆", "社区老茶室", "陶艺工坊", "金工工坊", "皮具工坊", "版画工作室", "插花工作室", "中古店", "Vintage买手店", "香氛集合店", "植物集合店", "设计师家居杂货店", "文创园区", "旧改创意街区", "历史风貌区", "老街巷", "城市公园驿站", "滨水绿道驿站", "独立唱片店", "黑胶馆", "胶片相机冲洗店", "暗房", "独立杂志发行点", "设计改造菜市场", "手作市集", "农夫市集"],
        "required_terms": ["书店", "书局", "艺术", "美术馆", "展览", "展馆", "画廊", "剧场", "影院", "电影", "资料馆", "Livehouse", "咖啡", "茶馆", "陶艺", "金工", "皮具", "版画", "插花", "中古", "Vintage", "香氛", "植物", "家居", "杂货", "文创", "创意", "历史风貌", "老街", "巷", "唱片", "黑胶", "胶片", "暗房", "杂志", "市集"],
        "excluded_terms": ["攀岩", "网球", "羽毛球", "乒乓", "篮球", "足球", "保龄球", "游泳", "健身", "瑜伽", "拳击", "台球", "射箭", "滑雪", "体育", "球馆", "学校", "培训", "维修", "快递", "收发室"],
        "typecode_prefixes": ["11", "14", "05"],
        "excluded_typecode_prefixes": ["08"],
        "diversity_hint": ["艺术文化", "阅读出版", "剧场音乐电影", "手作体验", "生活方式", "城市空间"],
        "subclusters": {
            "art_core": ["美术馆", "当代艺术中心", "画廊", "非遗博物馆", "博物馆"],
            "reading_publish": ["独立书店", "概念书局", "杂志", "黑胶", "唱片", "暗房", "胶片"],
            "film_theatre_music": ["电影资料馆", "艺术影院", "小剧场", "Livehouse", "黑匣子剧场"],
            "craft_workshop": ["陶艺", "金工", "皮具", "版画", "插花", "手作"],
            "lifestyle_shop": ["精品咖啡", "新中式茶馆", "中古店", "Vintage", "买手店", "香氛", "植物", "设计师家居"],
            "urban_space": ["文创园", "旧改街区", "历史风貌区", "老街巷", "市集", "滨水绿道"],
        },
    },
    "outdoor_nature": {
        "label": "户外 / 自然 / 城市绿地",
        "triggers": ["户外", "自然", "自然景色", "绿地", "公园", "滨江", "江边", "绿道", "散步", "骑行", "露营", "看风景"],
        "search_terms": ["公园", "滨江步道", "绿道", "湿地", "植物园", "观景台", "城市公园", "骑行道"],
        "micro_keywords": ["城市公园", "滨水绿道", "滨江步道", "湿地公园", "植物园", "观景平台", "公园驿站", "露营地", "骑行道", "亲水平台"],
        "required_terms": ["公园", "绿地", "绿道", "滨江", "江边", "湿地", "植物", "观景", "亲水", "步道", "骑行", "露营"],
        "excluded_terms": ["商场", "购物中心", "培训", "学校", "写字楼", "健身房"],
        "typecode_prefixes": ["11"],
        "excluded_typecode_prefixes": [],
        "diversity_hint": ["公园绿地", "滨水空间", "观景点", "休憩驿站"],
    },
    "history_heritage": {
        "label": "历史 / 文化遗产 / 老建筑",
        "triggers": ["历史", "历史感", "历史文化", "文化底蕴", "老建筑", "旧址", "遗址", "名人故居", "纪念馆", "老街", "风貌区"],
        "search_terms": ["历史建筑", "名人故居", "纪念馆", "旧址", "历史风貌区", "老街", "博物馆"],
        "micro_keywords": ["历史建筑", "名人故居", "纪念馆", "旧址", "历史风貌区", "老街巷", "博物馆", "文化遗址", "里弄", "老洋房"],
        "required_terms": ["历史", "旧址", "遗址", "故居", "纪念馆", "博物馆", "风貌", "老街", "里弄", "弄堂", "老建筑", "文化"],
        "excluded_terms": ["游乐", "电玩城", "健身", "球馆", "培训", "学校"],
        "typecode_prefixes": ["11", "14"],
        "excluded_typecode_prefixes": ["08"],
        "diversity_hint": ["历史建筑", "纪念馆旧址", "老街里弄", "博物馆"],
    },
    "local_character": {
        "label": "本地特色 / 市井 / 在地生活",
        "triggers": ["本地特色", "当地特色", "在地", "市井", "老上海", "老字号", "弄堂", "非遗", "传统", "烟火气"],
        "search_terms": ["老字号", "弄堂", "老街区", "本帮菜", "菜市场", "非遗", "社区茶室"],
        "micro_keywords": ["老字号", "本帮菜", "社区茶室", "老茶室", "菜市场", "弄堂", "老街区", "非遗", "传统手作", "小吃街", "城市更新街区"],
        "required_terms": ["老字号", "本帮", "上海菜", "弄堂", "里弄", "老街", "菜市场", "茶室", "非遗", "传统", "小吃", "社区"],
        "excluded_terms": ["全国连锁", "快餐", "健身", "球馆", "培训", "学校"],
        "typecode_prefixes": ["05", "11", "14", "06"],
        "excluded_typecode_prefixes": ["08"],
        "diversity_hint": ["老字号餐饮", "市井街区", "传统文化", "社区生活"],
    },
    "family_friendly": {
        "label": "亲子 / 家庭友好",
        "triggers": ["亲子", "带孩子", "带娃", "小朋友", "儿童", "家人"],
        "search_terms": ["亲子景点", "儿童博物馆", "公园", "科技馆", "动物园", "亲子餐厅"],
        "micro_keywords": ["儿童博物馆", "科技馆", "公园", "亲子餐厅", "儿童乐园", "自然教育", "动物园"],
        "required_terms": ["儿童", "亲子", "科技馆", "博物馆", "公园", "自然", "教育"],
        "excluded_terms": ["酒吧", "夜店", "密室", "剧本杀"],
        "typecode_prefixes": ["11", "14", "08", "05"],
        "excluded_typecode_prefixes": [],
        "diversity_hint": ["亲子场馆", "户外公园", "轻餐饮"],
    },
    "night_view": {
        "label": "夜景 / 夜游",
        "triggers": ["夜景", "夜游", "晚上", "夜晚", "灯光", "看灯", "江景"],
        "search_terms": ["夜景", "观景台", "江景", "灯光秀", "夜游"],
        "micro_keywords": ["观景台", "江景步道", "夜景拍照", "灯光秀", "夜游码头", "清吧"],
        "required_terms": ["夜景", "观景", "江景", "灯光", "码头", "步道"],
        "excluded_terms": ["培训", "学校", "维修"],
        "typecode_prefixes": ["11", "05"],
        "excluded_typecode_prefixes": [],
        "diversity_hint": ["观景点", "滨水夜游", "夜间休息点"],
    },
    "shopping_lifestyle": {
        "label": "购物 / 生活方式",
        "triggers": ["购物", "逛街", "买手店", "潮牌", "设计师", "生活方式", "商场"],
        "search_terms": ["购物中心", "买手店", "潮牌", "设计师品牌", "生活方式集合店"],
        "micro_keywords": ["买手店", "潮牌店", "设计师品牌", "生活方式集合店", "家居杂货", "中古店", "香氛店"],
        "required_terms": ["买手", "潮牌", "设计师", "生活方式", "家居", "杂货", "中古", "香氛", "购物"],
        "excluded_terms": ["培训", "维修", "快递"],
        "typecode_prefixes": ["06", "05", "11"],
        "excluded_typecode_prefixes": ["08"],
        "diversity_hint": ["购物空间", "生活方式", "休息点"],
    },
}


THEME_ALIASES = {
    "art": "art_culture_lifestyle", "culture": "art_culture_lifestyle",
    "art_culture": "art_culture_lifestyle", "art_culture_lifestyle": "art_culture_lifestyle",
    "outdoor": "outdoor_nature", "nature": "outdoor_nature", "outdoor_nature": "outdoor_nature",
    "history": "history_heritage", "heritage": "history_heritage", "history_heritage": "history_heritage",
    "local": "local_character", "local_character": "local_character",
    "family": "family_friendly", "family_friendly": "family_friendly",
    "night": "night_view", "night_view": "night_view",
    "shopping": "shopping_lifestyle", "shopping_lifestyle": "shopping_lifestyle",
}

# v16: 从 theme_profile_library.json 合并完整 profile
try:
    _LIBRARY_PROFILES = get_all_theme_profiles()
    for _pid, _profile in _LIBRARY_PROFILES.items():
        merged = dict(OFFICIAL_THEME_PROFILES.get(_pid, {}))
        merged.update(_profile)
        OFFICIAL_THEME_PROFILES[_pid] = merged
except Exception as exc:
    print(f"[WARN theme_profiles] failed to load theme_profile_library.json: {exc}")


def normalize_theme_profile(value: str | None, text: str = "") -> str | None:
    matched = normalize_theme_profile_id(value, text)
    if matched:
        return matched
    raw = (value or "").strip()
    if raw in OFFICIAL_THEME_PROFILES:
        return raw
    if raw in THEME_ALIASES:
        return THEME_ALIASES[raw]
    merged = text or raw
    for key, profile in OFFICIAL_THEME_PROFILES.items():
        if any(t and t in merged for t in profile.get("triggers", [])):
            return key
        if any(t and t in merged for t in profile.get("seed_keywords", [])):
            return key
    return None
    raw = (value or "").strip()
    if raw in OFFICIAL_THEME_PROFILES:
        return raw
    if raw in THEME_ALIASES:
        return THEME_ALIASES[raw]
    merged = text or raw
    for key, profile in OFFICIAL_THEME_PROFILES.items():
        if any(t and t in merged for t in profile.get("triggers", [])):
            return key
    return None


def build_effective_theme_profile(parsed_intent: Any) -> dict[str, Any]:
    # v16: 优先使用 theme_profile_library.json 的完整 profile
    lib_profile = build_effective_theme_profile_from_library(parsed_intent)
    if lib_profile.get("active"):
        return lib_profile

    text = " ".join([
        str(getattr(parsed_intent, "theme_label", "") or ""),
        " ".join(getattr(parsed_intent, "raw_keywords", []) or []),
        " ".join(getattr(parsed_intent, "search_keywords", []) or []),
        " ".join(getattr(parsed_intent, "micro_keywords", []) or []),
        " ".join(getattr(parsed_intent, "other_constraints", []) or []),
        " ".join(getattr(parsed_intent, "micro_poi_keywords", []) or []),
    ])

    profile_id = normalize_theme_profile(getattr(parsed_intent, "theme_profile", None), text)
    base: dict[str, Any] = {}
    if profile_id:
        base = dict(OFFICIAL_THEME_PROFILES[profile_id])
        base["id"] = profile_id
        base["official"] = True
    else:
        custom = getattr(parsed_intent, "custom_theme_profile", {}) or {}
        confidence = float(getattr(parsed_intent, "theme_confidence", 0.0) or custom.get("confidence") or 0.0)
        if custom and confidence >= 0.6:
            base = {
                "id": "custom",
                "official": False,
                "label": str(custom.get("theme_label") or getattr(parsed_intent, "theme_label", "") or "自定义主题"),
                "search_terms": _unique(list(custom.get("micro_poi_keywords", [])) + list(custom.get("search_terms", [])), 8),
                "micro_keywords": _unique(list(custom.get("micro_poi_keywords", [])), 16),
                "required_terms": _unique(list(custom.get("micro_required_terms", [])), 16),
                "excluded_terms": _unique(list(custom.get("micro_excluded_terms", [])), 16),
                "typecode_prefixes": [],
                "excluded_typecode_prefixes": [],
                "diversity_hint": _unique(list(custom.get("micro_diversity_hint", [])), 8),
            }

    if not base:
        return {"active": False}

    base["search_terms"] = _unique(base.get("search_terms", []) + getattr(parsed_intent, "micro_poi_keywords", []), 10)
    base["micro_keywords"] = _unique(base.get("micro_keywords", []) + getattr(parsed_intent, "micro_poi_keywords", []) + getattr(parsed_intent, "micro_keywords", []), 20)
    base["required_terms"] = _unique(base.get("required_terms", []) + getattr(parsed_intent, "micro_required_terms", []), 24)
    base["excluded_terms"] = _unique(base.get("excluded_terms", []) + getattr(parsed_intent, "micro_excluded_terms", []), 24)
    base["diversity_hint"] = _unique(base.get("diversity_hint", []) + getattr(parsed_intent, "micro_diversity_hint", []), 10)
    base["active"] = True
    return base
