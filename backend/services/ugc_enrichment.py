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


async def _search_one_platform(
    platform_key: str, name: str, city: str, district: str, address: str
) -> dict:
    from .api_client import bocha_search
    cfg = UGC_SOURCE_CONFIG.get(platform_key, {})
    domains = cfg.get("domains", [])
    label = cfg.get("label", platform_key)
    review_terms = cfg.get("review_terms", [])
    short_city = city.replace("市", "") if city else ""
    query = f'site:{domains[0]} "{name}" {short_city} {district} {address[:20]}'
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
    """Backward-compat wrapper."""
    return await enrich_route_with_network_ugc(route_points, city)


async def enrich_route_with_network_ugc(
    route_points: list[dict], city: str = "",
) -> list[dict]:
    if not route_points:
        return route_points
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

            # If it's an internal POI with a parent, search parent first
            search_targets = [(name, "poi")]
            if parent_name and parent_name != name:
                search_targets.insert(0, (parent_name, "parent_poi"))

            all_hits = []
            selected_platform = ""
            selected_scope = "poi"
            attempts = 0
            outcome = "no_search_result"

            for target_name, scope in search_targets:
                if all_hits:
                    break
                for pk in platforms[:3]:
                    attempts += 1
                    try:
                        res = await asyncio.wait_for(
                            _search_one_platform(pk, target_name, city, district, addr),
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
                summary = await _summarize_snippets(name, snippets)
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
                    poi["ugc_review_summary"] = f"所属景区的网络评价提到：{summary}"
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


async def _summarize_snippets(poi_name: str, snippets: list[str]) -> str:
    if not snippets:
        return ""
    text = " ".join(snippets)
    if len(text) < 30:
        return ""
    # Fallback: return first meaningful sentence
    for s in snippets[:2]:
        s = s.strip()[:100]
        if len(s) > 20:
            return s
    return ""
