"""
v21: Multi-platform UGC enrichment via Bocha search snippets.
Platform priority by POI type, max 3 platform attempts per POI, 0.75 identity threshold.
"""
from __future__ import annotations
import asyncio
import re
import time
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel


class UgcSummaryResponse(BaseModel):
    summary: str = ""


# ── Platform config ──
UGC_SOURCE_CONFIG: dict[str, dict] = {
    "dianping": {
        "label": "大众点评", "domains": ["dianping.com"],
        "review_terms": ["口味", "环境", "服务", "排队", "性价比"],
    },
    "ctrip": {
        "label": "携程", "domains": ["ctrip.com"],
        "review_terms": ["游客点评", "游玩体验", "景色", "交通", "排队"],
    },
    "qunar": {
        "label": "去哪儿", "domains": ["qunar.com"],
        "review_terms": ["点评", "游览", "门票", "交通", "体验"],
    },
    "mafengwo": {
        "label": "马蜂窝", "domains": ["mafengwo.cn"],
        "review_terms": ["游记", "体验", "攻略", "推荐", "避坑"],
    },
    "xiaohongshu": {
        "label": "小红书", "domains": ["xiaohongshu.com"],
        "review_terms": ["真实体验", "打卡", "拍照", "避坑", "推荐"],
    },
    "tripadvisor": {
        "label": "TripAdvisor", "domains": ["tripadvisor.com", "tripadvisor.cn"],
        "review_terms": ["review", "traveler", "experience", "rating", "点评"],
    },
}

# ── POI type → platform priority ──
def _classify_ugc_poi_type(poi: dict) -> str:
    kind = str(poi.get("kind", ""))
    tc = str(poi.get("typecode", ""))
    name = str(poi.get("name", ""))
    cat = str(poi.get("category", ""))
    text = f"{name} {cat}"
    if kind in ("meal", "restaurant", "cafe") or tc.startswith("05") or any(
        t in text for t in ["餐厅", "饭店", "小吃", "咖啡", "茶饮", "甜品"]):
        return "dining"
    if any(t in text for t in ["夜景", "灯光", "观景台"]):
        return "night_view"
    if any(t in text for t in ["博物馆", "美术馆", "历史", "文化", "纪念馆", "故居"]):
        return "cultural"
    if any(t in text for t in ["购物", "商场", "步行街", "商圈", "商业"]):
        return "shopping"
    if re.search(r"[a-zA-Z]{3,}", name):
        return "overseas"
    return "scenic"


_PLATFORM_PRIORITY: dict[str, list[str]] = {
    "dining": ["dianping", "xiaohongshu", "mafengwo"],
    "scenic": ["ctrip", "qunar", "mafengwo"],
    "cultural": ["mafengwo", "ctrip", "xiaohongshu"],
    "night_view": ["xiaohongshu", "mafengwo", "ctrip"],
    "shopping": ["xiaohongshu", "dianping", "ctrip"],
    "overseas": ["tripadvisor", "ctrip", "mafengwo"],
}


def _check_domain(url: str, domains: list[str]) -> bool:
    hostname = (urlparse(str(url)).hostname or "").lower()
    return any(hostname == d or hostname.endswith("." + d) for d in domains)


def _normalize_poi_identity(name: str) -> str:
    name = re.sub(r"（[^）]*打卡点[^）]*）", "", name)
    name = re.sub(r"[（(].*?[）)]", "", name).strip()
    name = name.replace("北京市", "北京").replace("上海市", "上海")
    name = re.sub(r"\s+", "", name)
    return name


def _match_score(result: dict, poi_name: str, city: str, district: str, address: str) -> float:
    score = 0.0
    text = f"{result.get('name','')} {result.get('snippet','')} {result.get('siteName','')}"
    core = _normalize_poi_identity(poi_name)
    if core and core in text:
        score += 0.55
    elif poi_name and poi_name in text:
        score += 0.35
    if city and city in text:
        score += 0.10
    if district and district in text:
        score += 0.20
    if address and any(a.strip() and a.strip() in text for a in [address[:10], address[-10:]]):
        score += 0.20
    return min(score, 1.0)


def _has_review_evidence(snippet: str, terms: list[str]) -> bool:
    return any(t in snippet for t in terms)


# ── Activity keywords extractable from child POI names ──
_CHILD_ACTIVITY_TERMS = [
    "码头", "游船", "湖", "夜景", "观景台", "食堂", "咖啡", "餐厅", "展览", "拍照",
    "灯光", "剧场", "演出", "登山", "徒步", "骑行", "滑雪", "温泉", "沙滩",
    "观鸟", "花园", "草坪", "广场", "喷泉", "寺庙", "教堂", "塔", "桥",
    "老街", "胡同", "弄堂", "市集", "夜市", "早市", "集市", "缆车", "索道",
    "栈道", "步道", "骑行道", "古道", "城墙", "宫殿", "陵园", "故居", "书院",
    "画展", "摄影", "手工", "陶艺", "茶室", "酒吧", "露台", "阳台",
]


def _extract_child_activity_keywords(name: str) -> str:
    """Extract activity-related terms from a child POI name for parent+child searches."""
    found = [t for t in _CHILD_ACTIVITY_TERMS if t in name]
    return " ".join(found) if found else ""


async def _search_one_platform(
    platform_key: str, name: str, city: str, district: str, address: str,
    parent_name: str = "", extra_terms: str = "",
) -> dict:
    from .api_client import bocha_search
    cfg = UGC_SOURCE_CONFIG.get(platform_key, {})
    domains = cfg.get("domains", [])
    label = cfg.get("label", platform_key)
    review_terms = cfg.get("review_terms", [])
    short_city = city.replace("市", "") if city else ""
    # Build query based on search context
    if extra_terms:
        # Tier 2: parent name + child keywords
        query = f'site:{domains[0]} "{parent_name or name}" "{name}" {extra_terms} {short_city} 评论 体验 推荐 真实评价'
    elif parent_name:
        # Tier 1: child POI with parent context
        query = f'site:{domains[0]} "{name}" "{parent_name}" {short_city} {district} 评论 体验 推荐 真实评价'
    else:
        # Tier 3: standalone (parent pure fallback or no parent)
        query = f'site:{domains[0]} "{name}" {short_city} {district} 评论 体验 推荐 真实评价'
    raw = 0
    domain_results = []
    try:
        items = await bocha_search(query)
        raw = len(items or [])
        for item in (items or [])[:8]:
            if _check_domain(str(item.get("url", "")), domains):
                domain_results.append({
                    "name": item.get("name", ""), "url": item.get("url", ""),
                    "siteName": item.get("siteName", label), "snippet": item.get("snippet", ""),
                    "summary": item.get("summary", ""),
                })
    except Exception as exc:
        return {"platform": platform_key, "raw": raw, "domain": 0, "hits": [], "error": str(exc)}

    identity_hits = []
    for r in domain_results[:6]:
        score = _match_score(r, name, city, district, address)
        ev = _has_review_evidence(str(r.get("snippet", "")), review_terms)
        if score >= 0.75 and ev:
            identity_hits.append({"result": r, "score": score})
        elif score >= 0.75:
            pass  # identity matched but no review evidence

    return {
        "platform": platform_key, "raw": raw, "domain": len(domain_results),
        "identity_matches": sum(1 for r in domain_results if _match_score(r, name, city, district, address) >= 0.75),
        "review_evidence": sum(1 for r in domain_results if _has_review_evidence(str(r.get("snippet", "")), review_terms)),
        "hits": identity_hits[:3], "error": "",
    }


async def enrich_route_with_dianping(route_points, city=""):
    """Backward-compat wrapper — UGC disabled in v22."""
    return enrich_route_with_network_ugc_stub(route_points)


async def enrich_route_with_network_ugc_stub(route_points: list[dict]) -> list[dict]:
    """v22: UGC enrichment is disabled. Populate empty fields for compatibility."""
    if not route_points:
        return route_points
    for p in route_points:
        p["ugc_review_summary"] = ""
        p["ugc_label"] = ""
        p["ugc_status"] = "disabled"
        p["ugc_source"] = ""
        p["ugc_source_url"] = ""
        p["ugc_source_name"] = ""
        p["ugc_scope"] = ""
        p["ugc_evidence_count"] = 0
        p["ugc_match_confidence"] = 0.0
    print("[UGC] disabled — returning empty stubs")
    return route_points


async def enrich_route_with_network_ugc(
    route_points: list[dict], city: str = "",
) -> list[dict]:
    """v22: UGC search disabled. Returns stubs immediately."""
    return await enrich_route_with_network_ugc_stub(route_points)


# Legacy entry point preserved for backward compat — no-op
async def _legacy_ugc(_route_points: list[dict], _city: str = "") -> list[dict]:
    _start = time.monotonic()
    display_pois = [
        p for p in route_points
        if p.get("is_display_poi") or (p.get("is_waypoint") and p.get("kind")
            not in ("start", "origin", "hint", "free_explore", "route_only", "traffic"))
    ][:8]

    sem = asyncio.Semaphore(4)

    async def _enrich_one(poi: dict):
        async with sem:
            name = str(poi.get("name", ""))
            if not name:
                return
            addr = str(poi.get("address", ""))
            district = str(poi.get("district", "") or "")
            parent_name = str(poi.get("parent_anchor") or poi.get("sub_anchor_name") or "").strip()
            poi_type = _classify_ugc_poi_type(poi)
            platforms = _PLATFORM_PRIORITY.get(poi_type, ["ctrip", "mafengwo", "xiaohongshu"])

            # ── 3-tier search: child-first, then parent+keywords, then parent pure fallback ──
            child_keywords = _extract_child_activity_keywords(name) if parent_name and parent_name != name else ""
            search_tiers: list[tuple[str, str, str, str]] = [
                # (query_name, scope, parent_arg, extra_terms)
                (name, "poi", parent_name if parent_name != name else "", ""),
            ]
            if parent_name and parent_name != name:
                if child_keywords:
                    search_tiers.append((name, "parent_with_child_hint", parent_name, child_keywords))
                search_tiers.append((parent_name, "parent_poi", "", ""))

            all_hits = []
            selected_platform = ""
            selected_scope = "poi"
            attempts = 0
            outcome = "no_search_result"

            for target_name, scope, parent_arg, extra_terms in search_tiers:
                if all_hits:
                    break
                for pk in platforms[:3]:
                    attempts += 1
                    try:
                        res = await asyncio.wait_for(
                            _search_one_platform(
                                pk, target_name, city, district, addr,
                                parent_name=parent_arg, extra_terms=extra_terms,
                            ),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        outcome = "timeout" if not all_hits else outcome
                        continue
                    except Exception:
                        continue

                    if res.get("raw", 0) == 0:
                        outcome = "no_search_result"
                        continue
                    if res.get("domain", 0) == 0:
                        outcome = "no_source_result"
                        continue
                    hits = res.get("hits", [])
                    if hits:
                        all_hits = hits
                        selected_platform = pk
                        selected_scope = scope
                        outcome = "verified"
                        break
                    if res.get("review_evidence", 0) > 0:
                        outcome = "identity_mismatch"
                    elif res.get("identity_matches", 0) > 0:
                        outcome = "no_review_evidence"

                if all_hits:
                    break

            poi["ugc_search_attempts"] = attempts
            if all_hits:
                best = sorted(all_hits, key=lambda x: -x["score"])[:2]
                snippets = [b["result"].get("snippet", "")[:200] for b in best]
                summary = await _summarize_snippets(name, snippets, selected_scope)
                platform_label = UGC_SOURCE_CONFIG.get(selected_platform, {}).get("label", selected_platform)
                poi["ugc_review_summary"] = summary or ""
                poi["ugc_label"] = "网络UGC数据聚合摘要"
                poi["ugc_status"] = "verified"
                poi["ugc_source"] = platform_label
                poi["ugc_source_url"] = best[0]["result"].get("url", "")
                poi["ugc_evidence_count"] = len(all_hits)
                poi["ugc_match_confidence"] = round(best[0]["score"], 2)
                poi["ugc_scope"] = selected_scope
                if selected_scope == "parent_poi" and summary:
                    poi["ugc_review_summary"] = f"所属景区评论提到：{summary}"
                elif selected_scope == "parent_with_child_hint" and summary:
                    poi["ugc_review_summary"] = f"所属景区中与该子点相关的评论提到：{summary}"
            else:
                poi["ugc_review_summary"] = ""
                poi["ugc_status"] = outcome
                poi["ugc_source"] = ""
                poi["ugc_source_url"] = ""
                poi["ugc_evidence_count"] = 0
                poi["ugc_match_confidence"] = 0.0
                poi["ugc_scope"] = "poi"

            print(f"[UGCSourceAudit] poi={name[:20]} type={poi_type} attempts={attempts} outcome={outcome}")

    tasks = [_enrich_one(p) for p in display_pois]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=30.0)
    except asyncio.TimeoutError:
        print("[UGCSearchAudit] phase timeout")
    elapsed = time.monotonic() - _start
    verified = sum(1 for p in route_points if p.get("ugc_status") == "verified")
    print(f"[UGCSearchAudit] complete elapsed={elapsed:.1f}s verified={verified}/{len(display_pois)}")
    return route_points


def _prefilter_snippets(snippets: list[str]) -> list[str]:
    """快速预过滤：剔除明显非评论型 snippet，减少无效 LLM 调用。"""
    REVIEW_SIGNALS = [
        "评论", "评价", "体验", "游记", "避坑", "推荐", "不推荐",
        "排队", "服务", "环境", "口味", "拍照", "游客", "用户",
        "亲测", "好吃", "好玩", "好看", "值得", "不建议",
        "感觉", "适合", "不太", "很", "非常", "特别",
    ]
    INVALID_DOMINATORS = [
        "地址", "电话", "营业时间", "公交", "地铁", "导航", "地图",
        "门票价格", "人均", "工商注册", "注册资本", "经营范围",
        "查看地图", "立即预订", "附近商户", "展开全文",
    ]
    valid: list[str] = []
    for s in snippets:
        has_review = any(sig in s for sig in REVIEW_SIGNALS)
        invalid_count = sum(1 for sig in INVALID_DOMINATORS if sig in s)
        if has_review and invalid_count <= 2:
            valid.append(s)
    return valid


_UGC_SUMMARIZE_SYSTEM_PROMPT = """你是旅游产品中的 UGC 评论清洗与摘要助手。

输入是一组搜索结果摘要 snippets。请只提取"真实用户评论/体验"相关内容，并生成前端展示用的"网络UGC数据聚合摘要"。

严格规则：
1. 只保留评论、游记、体验、避坑、推荐、不推荐、排队、服务、环境、口味、拍照、亲子、情侣、交通体验等用户感受。
2. 必须删除以下信息：
   - 地址、电话、营业时间、门票价格、等级、评分、人均消费
   - 公交/地铁线路、导航、地图信息
   - 商户简介、百科介绍、工商注册、经营范围
   - 平台按钮文案，例如"查看地图""展开全文""立即预订""附近商户"
   - SEO 摘要、黄页信息、行政区划信息
3. 如果没有足够评论证据，返回空字符串，不要编造。
4. 不要输出"地址""电话""等级""评分""营业时间"等字段。
5. 不要复述 POI 基础信息，只总结用户怎么评价。
6. 摘要控制在 40-90 字，语气自然，适合展示在路线右侧卡片。

在生成 UGC 摘要前，先判断每条 snippet 是否有效：
- 有效 snippet 必须至少满足一个条件：包含"评论/评价/体验/游记/避坑/推荐/不推荐/排队/服务/环境/口味/拍照/游客/用户/亲测"等评论信号；明显来自用户体验表达，例如"去了之后""感觉""适合""不太建议""排队很久""拍照好看""服务不错"。
- 无效 snippet 命中任一条件即丢弃：主要内容是"地址、电话、营业时间、公交、地铁、导航、地图、路线、门票、价格、等级、评分、人均"；主要内容是"公司、工商、注册资本、经营范围、许可、法人"；主要内容是"景点介绍、百科、开放时间、官方公告"；没有任何主观体验表达。

如果过滤后没有有效评论，返回空字符串。

输出格式：只输出一段中文摘要，不要标题，不要项目符号，不要 JSON。"""


async def _summarize_snippets(poi_name: str, snippets: list[str], scope: str = "poi") -> str:
    if not snippets:
        return ""
    text = " ".join(snippets)
    if len(text) < 30:
        return ""

    # 预过滤：剔除明显非评论型 snippet
    filtered = _prefilter_snippets(snippets)
    if not filtered:
        return ""

    scope_note = ""
    if scope == "parent_poi":
        scope_note = '\n注意：以下搜索结果来自该 POI 的上级景区，摘要开头应写"所属景区评论提到："。'
    elif scope == "parent_with_child_hint":
        scope_note = '\n注意：以下搜索结果来自该 POI 的上级景区中与子点相关的评论，摘要开头应写"所属景区中与该子点相关的评论提到："。'

    user_prompt = f"""POI：{poi_name}
搜索摘要：
{chr(10).join(f"{i+1}. {s}" for i, s in enumerate(filtered))}
{scope_note}"""

    try:
        from .api_client import call_llm

        result = await asyncio.wait_for(
            call_llm(
                UgcSummaryResponse,
                [
                    {"role": "system", "content": _UGC_SUMMARIZE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=200,
                temperature=0.2,
            ),
            timeout=8.0,
        )
        summary = (result.summary or "").strip()
        # 校验长度：太短或太长都不合格
        if len(summary) < 10:
            return ""
        if len(summary) > 100:
            summary = summary[:100]
        return summary
    except Exception as exc:
        print(f"[UGCSummarize] LLM summarize failed for {poi_name}: {exc}")
        # 兜底：取第一个 snippet 截断
        for s in snippets[:2]:
            s = s.strip()[:100]
            if len(s) > 20:
                return s
        return ""
