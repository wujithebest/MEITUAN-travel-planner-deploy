"""Unified Gaode typecode handling — composite codes, prefix matching, category rules."""

from __future__ import annotations

import re
from typing import Any


# ── Split & match ──────────────────────────────────────
def split_typecodes(raw: Any) -> list[str]:
    """Parse a single or composite typecode string into individual codes.

    Accepts ``'061202'``, ``'061202|080500'``, ``['061202','080500']``.
    """
    if isinstance(raw, list):
        codes: list[str] = []
        for item in raw:
            codes.extend(split_typecodes(item))
        return codes
    text = str(raw or "").strip()
    if not text:
        return []
    return [c.strip() for c in re.split(r"[|,;]+", text) if c.strip()]


def matches_typecode(raw: Any, prefixes: list[str]) -> bool:
    """True if ANY individual code matches ANY prefix.

    Supports parent-class matching:
    - 050000 matches 050100 (same family 0500)
    - 060000 matches 060306 (same family 0600)
    - 050100 matches 050102 (same family 0501)
    Per-code startswith, with family-based fallback.
    """
    codes = split_typecodes(raw)
    if not codes:
        return False
    for code in codes:
        code6 = code[:6] if len(code) >= 6 else code.ljust(6, "0")
        for prefix in prefixes:
            # Exact startswith
            if code6.startswith(prefix):
                return True
            # Parent-class: strip trailing zeros from prefix, match family
            pfx_trimmed = prefix.rstrip("0")
            if pfx_trimmed and len(pfx_trimmed) >= 2 and code6.startswith(pfx_trimmed):
                return True
    return False


# ── Category rules (data-driven, no city/POI names) ─────────────────────
# Each entry maps a category family to:
#   - allowed: list of typecode prefixes that represent the correct class
#   - semantic_terms: name/category text that must also be present (>0 means required)
#   - excluded: typecode prefixes that are always wrong for this family
#   - wide_fallback: broader prefix for initial wide recall (still needs semantic check)
#   - note: human-readable explanation

CATEGORY_RULES: dict[str, dict[str, Any]] = {
    "convenience_store": {
        "label": "便利店",
        "allowed": ["060200", "060201"],  # Gaode: 0602xx = 便利店/小卖部
        "wide_fallback": ["060000"],
        "semantic_terms": ["便利店", "便利", "超市", "小卖部", "士多", "杂货"],
        "excluded": ["050000", "110000"],
        # 060400 is primarily bookstore/stationery — only accept if name has convenience terms
        "conditional_allow": {
            "060400": ["便利店", "便利", "超市", "小卖部", "士多"],
        },
        "note": "060400 is bookstore/stationery; only accept if name contains convenience terms",
    },
    "antique_market": {
        "label": "古玩/收藏品市场",
        "allowed": ["061200", "190700"],
        "wide_fallback": ["060000"],
        "semantic_terms": ["古玩", "文玩", "旧货", "收藏品", "古董", "钱币", "邮票", "古玩城", "收藏品市场"],
        "excluded": ["050000", "110000", "080000"],
        "note": "typecode 0612 must be accompanied by name/category evidence",
    },
    "handcraft_intangible": {
        "label": "非遗手作/手工艺",
        "allowed": ["080500", "061202"],
        "wide_fallback": ["080000", "060000"],
        "semantic_terms": ["非遗", "手作", "手工", "工坊", "体验坊", "手工艺", "传统工艺", "DIY", "陶艺", "扎染", "木版", "刺绣"],
        "excluded": ["050000", "110000"],
        "note": "typecode alone insufficient; need name/category match",
    },
    "flower_market": {
        "label": "花艺/鲜花市场",
        "allowed": ["061100"],  # 花鸟鱼虫市场
        "wide_fallback": ["060000"],
        "semantic_terms": ["花店", "花市", "花艺", "鲜花", "花卉", "花鸟", "盆栽", "插花", "花坊"],
        "excluded": ["050000", "110000", "080000"],
        # Also accept flower-related shopping typecodes if name matches
        "conditional_allow": {
            "061000": ["花店", "花市", "花艺", "鲜花", "花卉", "花坊"],
        },
    },
    "wood_craft": {
        "label": "木材工作坊/木艺",
        "allowed": ["080500", "061200"],
        "wide_fallback": ["080000", "060000"],
        "semantic_terms": ["木工坊", "木作", "木艺", "木工体验", "木工", "木器", "木制品", "木艺工作室", "木工工作室"],
        "excluded": ["050000", "110000"],
        "note": "strict name check required; do not accept general craft shops without wood terms",
    },
    # ── v20: Science/Tech museums ──
    "science_museum": {
        "label": "科技馆/天文馆",
        "allowed": ["140600", "140700"],
        "wide_fallback": ["140000"],
        "semantic_terms": [
            "科技馆", "天文馆", "科学技术馆", "科学中心", "科学宫",
            "科技中心", "科学博物馆", "天文台", "气象馆",
        ],
        "negative_semantic_terms": [
            "艺术馆", "美术馆", "金丝楠", "古董", "珠宝",
        ],
        "excluded": ["050000", "060000"],
        "note": "140600=科技馆, 140700=天文馆; 140000 wide_fallback with semantic check",
    },
    # ── v20: Parks (separate from generic scenic_area) ──
    "park": {
        "label": "公园",
        "allowed": ["110100", "110101", "110102", "110103", "110104", "110105"],
        "wide_fallback": ["110000", "110200"],
        "semantic_terms": [
            "公园", "城市公园", "森林公园", "湿地公园", "郊野公园",
            "体育公园", "文化公园", "植物园",
        ],
        "negative_semantic_terms": [
            "入口", "停车场", "厕所", "雕塑", "如意湖",
            "广场", "管理中心", "售票处", "服务站",
        ],
        "excluded": ["050000", "060000", "080000"],
        "note": "1101xx = parks; excludes entrances, parking lots, internal sub-features",
    },
    # ── v20: Scenic areas / tourist attractions ──
    "scenic_area": {
        "label": "景区/景点",
        "allowed": ["110000", "110100", "110200"],
        "wide_fallback": ["110000"],
        "semantic_terms": [
            "景区", "景点", "风景区", "名胜", "公园", "旅游景点",
            "名胜古迹", "风景区", "游览区",
        ],
        "negative_semantic_terms": [
            "餐厅", "饭馆", "火锅", "小吃", "零售", "便利店",
            "公司", "企业", "停车场", "住宅",
        ],
        "excluded": ["050000", "060000", "080000", "090000"],
        "note": "110000=风景名胜, 110100=公园广场, 110200=景点/景区",
    },
    # ── v20: Entertainment venues ──
    "arcade": {
        "label": "电玩城/游戏厅",
        "allowed": ["080300", "080305", "080306", "080307"],
        "wide_fallback": ["080000"],
        "semantic_terms": [
            "电玩城", "游戏厅", "动漫城", "电玩中心", "街机厅",
            "街机", "电玩", "游戏机", "投篮机", "跳舞机",
        ],
        "negative_semantic_terms": [
            "棋牌", "麻将", "台球", "彩票", "网吧",
        ],
        "excluded": ["050000"],
        "note": "0803xx = 娱乐场所-游戏厅/电玩城; excludes 棋牌室 and lottery shops",
    },
    "bookstore": {
        "label": "书店/文具",
        "allowed": ["061205"],  # Gaode: 061205 = 书店 (actual bookstore code, NOT 060400)
        "wide_fallback": ["060000"],
        "semantic_terms": ["书店", "书局", "书城", "城市书房", "独立书店", "概念书店", "图书馆"],
        "excluded": ["050000", "080500"],
        "note": "061205 is the correct Gaode code for bookstores; 060400 is general stationery/cultural supplies",
    },
    # ── v20: Sports venues ──
    "sports_venue": {
        "label": "运动场馆",
        "allowed": [
            "080100", "080101", "080102", "080103", "080104", "080105",
            "080106", "080107", "080108", "080109", "080110", "080111",
            "080112", "080113", "080114", "080115", "080116", "080117",
        ],
        "wide_fallback": ["080000"],
        "semantic_terms": [
            "运动场馆", "体育馆", "体育中心", "运动中心",
            "健身房", "游泳馆", "篮球场", "足球场", "网球场",
            "羽毛球馆", "乒乓球馆", "攀岩馆", "滑雪场", "滑冰场",
            "保龄球馆", "运动", "体育场", "运动场",
            "健身", "瑜伽", "舞蹈室",
        ],
        "negative_semantic_terms": [
            "培训学校", "教练培训", "运动用品", "体育器材", "体育用品",
            "比赛报名", "团建轰趴", "轰趴馆", "私人会所",
            "学校内部", "已停业",
        ],
        "excluded": ["050000", "060000"],
        "note": "0801xx = sports venues; excludes training schools, equipment shops, private clubs",
    },
    # ── v20: Campus / education ──
    "university_campus": {
        "label": "大学/高等院校校园",
        "allowed": ["141201"],  # Gaode: 141201 = 高等院校
        "wide_fallback": ["141200", "140000"],
        "forbidden_typecodes": ["141206"],  # 成人教育 — always reject for normal university requests
        "semantic_terms": [
            "大学", "高校", "高等院校", "大学校园", "大学校区",
            "学院", "校园",
        ],
        "negative_semantic_terms": [
            # Vocational / adult / training — must be rejected for normal "大学" requests
            "职工大学", "职业大学", "职业学院", "职业技术学院",
            "成人大学", "成人教育", "老年大学", "继续教育",
            "开放大学分校", "开放大学",
            "研修学院", "培训学院", "培训学校", "培训中心",
            "临床医学系", "实验教学中心", "技能教学中心",
            "电化教育馆", "社会主义学院",
            # Non-campus facilities
            "附属医院", "大学附属", "大学餐厅", "大学食堂", "大学商店",
            "驾校",
            # K-12 schools
            "小学", "中学", "初中", "高中", "幼儿园",
            # Internal departments only
            "分校",  # branch campus — weak signal, needs extra evidence
        ],
        "excluded": ["050000", "060000"],
        "note": "normal 大学 requests: 141206 forbidden; 141200/140000 need 2+ evidence; 学院 alone insufficient",
    },
    # ── v20: Healthcare ──
    "hospital": {
        "label": "三甲/综合医院",
        "allowed": ["090100", "090101", "090102", "090103"],  # 综合医院/三级甲等
        "wide_fallback": ["090000"],
        "semantic_terms": ["三甲医院", "综合医院", "医院", "医疗中心", "人民医院", "附属医院"],
        "excluded": ["050000", "110000"],
        "conditional_allow": {
            "090200": ["医院", "综合医院", "专科医院"],  # 专科医院 — only when name says 医院
        },
        "note": "0902xx = 专科医院; only accept when name has 医院 evidence",
    },
    "hospital_general": {
        "label": "医院（通用）",
        "allowed": ["090100", "090101", "090102", "090103", "090200", "090201", "090202"],
        "wide_fallback": ["090000"],
        "semantic_terms": ["医院", "卫生院", "卫生站", "医疗中心", "诊疗中心", "社区卫生"],
        "excluded": ["050000", "110000"],
        # Must NOT match: pet hospital, beauty hospital (整形), retirement home
        "negative_terms": ["宠物", "兽医", "整形", "美容", "养老", "敬老", "颐养"],
        "note": "excludes pet hospitals, cosmetic surgery, retirement homes via name check",
    },
    "pharmacy": {
        "label": "药店",
        "allowed": ["090500", "090501", "090502"],  # 药房/药店
        "wide_fallback": ["090000"],
        "semantic_terms": ["药房", "药店", "大药房", "医药", "中药房", "西药房"],
        "excluded": ["050000", "110000"],
        "negative_terms": ["宠物", "兽医"],
        "note": "pharmacy/drugstore, excludes pet pharmacy",
    },
    # ── v20: Finance ──
    "bank": {
        "label": "银行",
        "allowed": ["160100", "160101", "160102", "160200", "160300", "160400"],
        "wide_fallback": ["160000"],
        "semantic_terms": ["银行", "储蓄所", "ATM", "atm", "自动取款机", "存款", "取款"],
        "excluded": ["050000"],
    },
    # ── v20: Auto/Transport ──
    "gas_station": {
        "label": "加油站",
        "allowed": ["150100", "150101", "150200"],
        "wide_fallback": ["150000"],
        "semantic_terms": ["加油站", "加气站", "充电站", "充电桩", "石化"],
        "excluded": ["050000"],
    },
    "parking": {
        "label": "停车场",
        "allowed": ["150300", "150301", "150302"],
        "wide_fallback": ["150000"],
        "semantic_terms": ["停车场", "停车库", "地下车库"],
        "excluded": ["050000"],
    },
    # ── v20: Entertainment ──
    "cinema": {
        "label": "电影院",
        "allowed": ["080200", "080201", "080202"],
        "wide_fallback": ["080000"],
        "semantic_terms": ["电影院", "影院", "电影城", "IMAX"],
        "excluded": ["050000"],
    },
    # ── v20: Retail/Building ──
    "building_materials": {
        "label": "建材市场",
        "allowed": ["061500", "061501", "061502", "061503", "061504"],
        "wide_fallback": ["060000"],
        "semantic_terms": ["建材", "五金", "灯具", "家具", "卫浴", "瓷砖", "地板"],
        "excluded": ["050000", "110000"],
    },
    "supermarket_market": {
        "label": "超市/菜市场",
        "allowed": ["060100", "060101", "060200", "060300"],
        "wide_fallback": ["060000"],
        "semantic_terms": ["超市", "菜市场", "农贸市场", "生鲜", "市场"],
        "excluded": ["050000", "110000"],
    },
    # ── v20: Shopping malls ──
    "shopping_mall": {
        "label": "商场/购物中心",
        "allowed": ["060100", "060101", "060102", "060103", "060400", "060900", "061000"],
        "wide_fallback": ["060000"],
        "semantic_terms": ["购物中心", "商场", "商业广场", "商业中心", "商业综合体",
                          "百货商场", "百货", "shopping mall", "mall"],
        # search_keywords for planned waypoint expansion — category-relevant, no city names
        "search_keywords": ["购物中心", "商场", "商业广场", "商业综合体", "购物广场"],
        "excluded": ["050000", "110000"],
        "negative_terms": ["停车场", "出入口", "写字楼", "物业", "公交站", "批发", "商贸公司",
                          "办事处", "招商", "租赁", "售楼", "样板间"],
        "note": "shopping mall body, NOT parking lots, office towers, or single shops",
    },
    # ── v20: Religious sites ──
    "religious_site": {
        "label": "寺庙/宗教场所",
        "allowed": ["110200", "110201", "110202", "110203", "110204", "110205"],
        "wide_fallback": ["110000"],
        "semantic_terms": ["寺庙", "寺院", "佛寺", "禅寺", "道观", "教堂", "宗教场所", "参拜", "祈福"],
        # For "寺庙" queries, prefer Buddhist temples; for "宗教场所" allow broader
        "search_keywords": ["寺庙", "寺院", "佛寺", "禅寺"],
        "excluded": ["050000"],
        "negative_terms": ["停车场", "售票处", "公交站", "出入口", "培训", "素食餐厅"],
        "note": "prefers Buddhist temples for 寺庙 queries; church/mosque only for explicit requests",
    },
    # ── v20: Personal services ──
    "repair_shop": {
        "label": "维修店",
        "allowed": ["071200", "071300", "070000"],
        "wide_fallback": ["070000", "071000", "060000"],
        "conditional_allow": {
            "060306": ["电脑维修", "手机维修", "笔记本维修", "数码维修", "售后服务", "客户服务中心", "授权服务中心"],
        },
        "semantic_terms": ["维修", "修理", "电脑维修", "笔记本维修", "手机维修", "数码维修", "售后服务", "客户服务中心"],
        "negative_semantic_terms": ["销售", "专卖店", "零售", "批发"],
        "excluded": ["050000"],
        "note": "0712xx/0713xx = computer/phone repair; 060306 only with repair evidence in name",
    },
    "hair_salon": {
        "label": "理发店",
        "allowed": ["070100", "070101", "070102"],
        "wide_fallback": ["070000"],
        "semantic_terms": ["理发", "美发", "发廊", "剪发", "洗剪吹", "烫发"],
        "excluded": ["050000", "110000"],
        "negative_terms": ["宠物", "培训", "学校"],
    },
    "restroom": {
        "label": "公共厕所",
        "allowed": ["200300", "200301", "200302"],
        "wide_fallback": ["200000"],
        "semantic_terms": ["卫生间", "公共厕所", "洗手间", "厕所"],
        "excluded": ["050000"],
    },
    "postal": {
        "label": "邮局/快递",
        "allowed": ["170300", "170301"],
        "wide_fallback": ["170000"],
        "semantic_terms": ["快递", "邮政", "邮局", "顺丰", "菜鸟", "驿站"],
        "excluded": ["050000"],
    },
    "restaurant": {
        "label": "餐饮",
        "allowed": ["050000"],
        "wide_fallback": ["050000"],
        "semantic_terms": ["餐厅", "饭馆", "饭店", "美食", "小吃", "火锅", "川菜", "粤菜", "面馆"],
        "excluded": [],
        "note": "only used when explicit_meal_intent=True",
    },
}

# v20: Negative terms for hospital validation — configurable per category
HOSPITAL_NEGATIVE_TERMS = [
    "宠物", "兽医", "整形", "美容", "养老", "敬老", "颐养",
    "体检推销", "医疗器械", "宿舍", "食堂", "公交站", "出入口",
    "停车场", "停车场入口",
]


def category_for_query(query: str) -> str | None:
    """Given a primary_query like '古玩市场', return the best-matching category rule id."""
    q = query.lower()
    best: tuple[int, str] | None = None
    for cat_id, rule in CATEGORY_RULES.items():
        if cat_id == "restaurant":
            continue
        for term in rule.get("semantic_terms", []):
            if term.lower() in q:
                score = len(term)
                if best is None or score > best[0]:
                    best = (score, cat_id)
                # Don't break — check all terms for longest match
    return best[1] if best else None


def validate_poi_category(
    poi: dict[str, Any],
    cat_id: str,
    require_two_evidence: bool = False,
) -> tuple[bool, list[str]]:
    """Check if a POI matches a category rule. Returns (pass, reasons).

    Args:
        poi: POI dict with name, typecode, category fields.
        cat_id: Category rule ID to validate against.
        require_two_evidence: If True, need at least 2 of {name, category, typecode} evidence.
    """
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return True, []

    reasons: list[str] = []
    name = str(poi.get("name", "") or "").lower()
    category = str(poi.get("category", "") or "").lower()
    combined = f"{name} {category}"

    # Check excluded typecodes
    raw_tc = poi.get("typecode", "")
    if matches_typecode(raw_tc, rule.get("excluded", [])):
        reasons.append(f"excluded_typecode={raw_tc}")
        return False, reasons

    # v20: Check forbidden typecodes (always reject, even in compound codes)
    for fb_prefix in rule.get("forbidden_typecodes", []):
        if matches_typecode(raw_tc, [fb_prefix]):
            reasons.append(f"forbidden_typecode={fb_prefix}")
            return False, reasons

    # v20: Check negative_semantic_terms (strong negative filter)
    for neg_term in rule.get("negative_semantic_terms", []):
        if neg_term.lower() in combined:
            reasons.append(f"negative_semantic_term={neg_term}")
            return False, reasons

    # Check legacy negative_terms
    for neg_term in rule.get("negative_terms", []) + (HOSPITAL_NEGATIVE_TERMS if cat_id.startswith("hospital") else []):
        if neg_term.lower() in combined:
            reasons.append(f"negative_term_matched={neg_term}")
            return False, reasons

    # v20: Collect POSITIVE evidence (multiple categories)
    found_semantic: list[str] = []
    for term in rule.get("semantic_terms", []):
        if term.lower() in combined:
            found_semantic.append(term)
    found_name_semantic: list[str] = []
    name_only = str(poi.get("name", "") or "").lower()
    for term in rule.get("semantic_terms", []):
        if term.lower() in name_only:
            found_name_semantic.append(term)

    # Check allowed typecodes (strict allowed list)
    tc_ok = matches_typecode(raw_tc, rule.get("allowed", []))
    # v20: wide_fallback only counts as half evidence, needs semantic backing
    tc_wide = matches_typecode(raw_tc, rule.get("wide_fallback", []))

    # Check conditional allows (e.g., 060400 only if name has "便利店")
    tc_conditional = False
    for prefix, terms in rule.get("conditional_allow", {}).items():
        if matches_typecode(raw_tc, [prefix]):
            for term in terms:
                if term.lower() in combined:
                    tc_conditional = True
                    break
            if tc_conditional:
                break

    tc_match = tc_ok or tc_conditional
    name_match = bool(found_semantic)

    # Evidence counting
    evidence_count = sum([
        1 if tc_match else 0,
        1 if name_match else 0,
        1 if category and any(t.lower() in category for t in rule.get("semantic_terms", [])) else 0,
    ])

    if require_two_evidence and evidence_count < 2:
        reasons.append(
            f"insufficient_evidence({evidence_count}/2): "
            f"tc={tc_match} name={name_match or found_semantic} cat={category[:30]}"
        )
        return False, reasons

    if not tc_match and not name_match:
        reasons.append(f"no_allowed_typecode({raw_tc})_and_no_semantic_match")
        return False, reasons

    # v20: Entity role classification for university/campus
    entity_role = "generic"
    if cat_id == "university_campus":
        has_college = any(t in name_only for t in ["大学", "学院"])
        is_vocational = any(t in combined for t in [
            "职工", "职业", "成人", "老年", "继续教育", "开放大学",
            "研修", "培训", "教学中心", "实验中心",
        ])
        is_branch = any(t in combined for t in ["分校", "教学点", "函授站"])
        if not is_vocational and not is_branch and has_college:
            entity_role = "main_university_campus" if "大学" in name_only else "conventional_college_campus"
        elif is_vocational:
            entity_role = "adult_or_vocational_school"
        elif is_branch:
            entity_role = "branch_or_department"
        elif any(t in combined for t in ["食堂", "商店", "医院", "附属"]):
            entity_role = "campus_internal_facility"

    # v20: Enhanced audit log for university/college candidates
    if cat_id in ("university_campus",):
        print(
            f"[CategoryAudit] candidate={poi.get('name','')} "
            f"cat_id={cat_id} "
            f"all_typecodes={raw_tc} "
            f"tc_ok={tc_ok} tc_wide={tc_wide} "
            f"semantic_hits={found_name_semantic} "
            f"evidence_count={evidence_count} "
            f"entity_role={entity_role} "
            f"accepted={True} "
            f"reasons={reasons}"
        )

    return True, []


def classify_university_role(poi: dict[str, Any]) -> str:
    """Return entity_role for a university candidate (for ranking priority)."""
    name = str(poi.get("name", "") or "").lower()
    combined = f"{name} {str(poi.get('category','') or '').lower()}"
    is_vocational = any(t in combined for t in [
        "职工", "职业", "成人", "老年", "继续教育", "开放大学",
        "研修", "培训", "教学中心", "实验中心", "技能",
    ])
    if is_vocational:
        return "adult_or_vocational_school"
    if any(t in combined for t in ["分校", "教学点", "函授站"]):
        return "branch_or_department"
    if any(t in combined for t in ["食堂", "商店", "附属医院", "附属"]):
        return "campus_internal_facility"
    if "大学" in name:
        return "main_university_campus"
    if "学院" in name:
        return "conventional_college_campus"
    return "generic"


def get_allowed_typecode_prefixes(cat_id: str) -> list[str]:
    """Return the allowed typecode prefixes for a given category, including conditionals."""
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return []
    allowed = list(rule.get("allowed", []))
    for cond in rule.get("conditional_allow", {}).keys():
        allowed.append(cond)
    return allowed


def get_semantic_terms(cat_id: str) -> list[str]:
    """Return the semantic terms for a given category."""
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return []
    return list(rule.get("semantic_terms", []))


def get_search_keywords(cat_id: str) -> list[str]:
    """Return recommended search keywords for a category, or semantic_terms as fallback."""
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return []
    return list(rule.get("search_keywords", []) or rule.get("semantic_terms", [])[:4])


def get_negative_terms(cat_id: str) -> list[str]:
    """Return negative/exclusion terms for a category."""
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return []
    terms = list(rule.get("negative_terms", []))
    if cat_id.startswith("hospital"):
        terms.extend(HOSPITAL_NEGATIVE_TERMS)
    return terms


def get_typecodes_for_planned(cat_id: str) -> str:
    """Return Gaode 'types' filter string for planned waypoint category search.
    Uses allowed typecodes joined by |, or empty string for no filter."""
    allowed = get_allowed_typecode_prefixes(cat_id)
    if not allowed:
        return ""
    # Use 4-digit prefixes for broader matching in Gaode API
    types = sorted(set(p[:4] for p in allowed if len(p) >= 4))
    return "|".join(f"{t}00" if len(t) == 4 else t for t in types) if types else ""


def build_category_waypoint(raw_target: str, cat_id: str) -> dict[str, Any]:
    """Build a structured planned waypoint config from category rule.

    Returns dict with search_keyword, search_keywords, required_terms,
    excluded_terms, allowed_typecodes, category suitable for PlannedWaypoint.
    No city or POI names hardcoded.
    """
    rule = CATEGORY_RULES.get(cat_id, {})
    return {
        "search_keyword": raw_target,
        "search_keywords": get_search_keywords(cat_id) or [raw_target],
        "required_terms": get_semantic_terms(cat_id),
        "excluded_terms": get_negative_terms(cat_id),
        "allowed_typecodes": get_allowed_typecode_prefixes(cat_id),
        "category": "visit" if cat_id not in ("restaurant",) else "meal",
        "category_id": cat_id,
    }
    return list(rule.get("semantic_terms", []))


def get_excluded_typecode_prefixes(cat_id: str) -> list[str]:
    """Return the excluded typecode prefixes for a given category."""
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return []
    return list(rule.get("excluded", []))
