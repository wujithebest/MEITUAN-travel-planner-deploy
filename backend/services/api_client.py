from __future__ import annotations
import asyncio
import json
import math
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel

from . import config
from .day_slots import infer_capacity_from_typecode
from .utils import ConfigurationError, DependencyMissingError, ExternalAPIError, LLMCallError, emit_status, parse_coord_param, safe_float


try:
    import instructor  # type: ignore
    from openai import OpenAI, AsyncOpenAI
except Exception:  # pragma: no cover - optional dependency
    instructor = None
    OpenAI = None
    AsyncOpenAI = None


API_TIMEOUT = float(os.getenv("ROUTE_PLANNER_API_TIMEOUT", "15"))
_gaode_rate_lock = None
_gaode_last_request_at = 0.0
_gaode_semaphore = None
GAODE_MAX_CONCURRENCY = int(os.getenv("GAODE_MAX_CONCURRENCY", str(getattr(config, "GAODE_MAX_CONCURRENCY", 3))))


def _get_gaode_semaphore() -> asyncio.Semaphore:
    global _gaode_semaphore
    if _gaode_semaphore is None:
        _gaode_semaphore = asyncio.Semaphore(GAODE_MAX_CONCURRENCY)
    return _gaode_semaphore
_prefer_curl_get = False
_bocha_rate_lock = None
_bocha_last_request_at = 0.0
_bocha_semaphore = None


def _get_gaode_rate_lock() -> asyncio.Lock:
    global _gaode_rate_lock
    if _gaode_rate_lock is None:
        _gaode_rate_lock = asyncio.Lock()
    return _gaode_rate_lock


def _get_bocha_rate_lock() -> asyncio.Lock:
    global _bocha_rate_lock
    if _bocha_rate_lock is None:
        _bocha_rate_lock = asyncio.Lock()
    return _bocha_rate_lock


def _get_bocha_semaphore() -> asyncio.Semaphore:
    global _bocha_semaphore
    if _bocha_semaphore is None:
        _bocha_semaphore = asyncio.Semaphore(config.BOCHA_MAX_CONCURRENCY)
    return _bocha_semaphore


def _usable_key(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return not any(token in lowered for token in ["xxx", "your", "replace", "placeholder"])


def _require_key(service_name: str, env_name: str, value: str) -> None:
    if not _usable_key(value):
        raise ConfigurationError(f"缺少有效的 {service_name} 配置：请在 .env 中设置 {env_name}")


def _http_json(
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = API_TIMEOUT,
    bypass_proxy: bool = False,
) -> dict[str, Any]:
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        url = f"{url}?{query}"
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if bypass_proxy else None
    open_fn = opener.open if opener else urllib.request.urlopen
    with open_fn(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _requests_json(
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = API_TIMEOUT,
) -> dict[str, Any]:
    try:
        import requests  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise DependencyMissingError("缺少 Python 依赖 requests，无法使用 requests 直连博查。") from exc

    session = requests.Session()
    session.trust_env = False
    resp = session.request(
        method,
        url,
        params={k: v for k, v in (params or {}).items() if v not in (None, "")},
        json=payload,
        headers=headers or {},
        timeout=timeout,
    )
    try:
        return resp.json()
    except ValueError as exc:
        raise ExternalAPIError(f"接口返回内容不是合法 JSON：HTTP {resp.status_code} {resp.text[:200]}") from exc


def _curl_path() -> str:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise DependencyMissingError("Python TLS 连接失败，且系统未找到 curl。请安装 curl 或升级 Python/OpenSSL。")
    return curl


def _proxyless_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]:
        env.pop(key, None)
    return env


def _curl_get_json(url: str, params: dict[str, Any], timeout: float = API_TIMEOUT) -> dict[str, Any]:
    curl = _curl_path()
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        url = f"{url}?{query}"

    connect_timeout = max(8, int(timeout * 0.6))
    max_time = int(timeout)
    try:
        result = subprocess.run(
            [curl, "-sS", "--connect-timeout", str(connect_timeout), "--max-time", str(max_time), url],
            capture_output=True,
            timeout=timeout + 5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExternalAPIError(f"curl GET 请求超时：{timeout}s") from exc

    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise ExternalAPIError(f"curl GET 请求失败：{stderr or result.returncode}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ExternalAPIError(f"接口返回内容不是合法 JSON：{stdout[:200]}") from exc


def _curl_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float = API_TIMEOUT,
    bypass_proxy: bool = False,
) -> dict[str, Any]:
    curl = _curl_path()

    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    connect_timeout = max(8, int(timeout * 0.6))
    max_time = int(timeout)
    cmd = [curl, "-sS", "--connect-timeout", str(connect_timeout), "--max-time", str(max_time), "-X", "POST", url]
    if bypass_proxy:
        cmd[1:1] = ["--noproxy", "*"]
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    cmd.extend(["--data-binary", "@-"])

    try:
        result = subprocess.run(
            cmd,
            input=payload_bytes,
            capture_output=True,
            timeout=timeout + 5,
            check=False,
            env=_proxyless_env() if bypass_proxy else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExternalAPIError(f"curl 调用博查超时：{timeout}s") from exc

    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise ExternalAPIError(f"curl 调用博查失败：{stderr or result.returncode}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ExternalAPIError(f"博查返回内容不是合法 JSON：{stdout[:200]}") from exc


_instructor_client = None
_async_instructor_client = None

# DeepSeek LLM 调用限流：防止 api.longcat.chat 代理 429
_llm_rate_lock = None
_llm_last_call_at = 0.0


def _get_llm_rate_lock() -> asyncio.Lock:
    global _llm_rate_lock
    if _llm_rate_lock is None:
        _llm_rate_lock = asyncio.Lock()
    return _llm_rate_lock


def _get_instructor_client():
    global _instructor_client
    if _instructor_client is not None:
        return _instructor_client
    if instructor is None:
        raise DependencyMissingError("缺少 Python 依赖 instructor，请先安装：pip install instructor")
    if OpenAI is None:
        raise DependencyMissingError("缺少 Python 依赖 openai，请先安装：pip install openai")
    _require_key("DeepSeek", "DEEPSEEK_API_KEY", config.DEEPSEEK_API_KEY)
    _instructor_client = instructor.from_openai(
        OpenAI(base_url=config.DEEPSEEK_BASE_URL, api_key=config.DEEPSEEK_API_KEY),
        mode=instructor.Mode.JSON,
    )
    return _instructor_client


def _get_async_instructor_client():
    """获取异步 instructor 客户端，用于非阻塞 LLM 调用"""
    global _async_instructor_client
    if _async_instructor_client is not None:
        return _async_instructor_client
    if instructor is None:
        raise DependencyMissingError("缺少 Python 依赖 instructor，请先安装：pip install instructor")
    if AsyncOpenAI is None:
        raise DependencyMissingError("缺少 Python 依赖 openai，请先安装：pip install openai")
    _require_key("DeepSeek", "DEEPSEEK_API_KEY", config.DEEPSEEK_API_KEY)
    # 设置超时时间，避免无限等待
    async_openai_client = AsyncOpenAI(
        base_url=config.DEEPSEEK_BASE_URL,
        api_key=config.DEEPSEEK_API_KEY,
        timeout=config.DEEPSEEK_TIMEOUT,
    )
    _async_instructor_client = instructor.from_openai(
        async_openai_client,
        mode=instructor.Mode.JSON,
    )
    return _async_instructor_client


def _format_llm_error(exc: Exception) -> str:
    raw = str(exc)
    lowered = raw.lower()
    if "connection error" in lowered or "connect" in lowered:
        return "DeepSeek 调用失败：网络连接失败。请检查本机网络、代理设置，以及 https://api.deepseek.com 是否可访问。"
    if "timeout" in lowered or "timed out" in lowered:
        return f"DeepSeek 调用失败：请求超过 {config.DEEPSEEK_TIMEOUT}s。请稍后重试，或适当调大 DEEPSEEK_TIMEOUT。"
    if "401" in lowered or "unauthorized" in lowered or "invalid api key" in lowered:
        return "DeepSeek 调用失败：API Key 鉴权失败。请检查 .env 中的 DEEPSEEK_API_KEY 是否正确。"
    if "429" in lowered or "rate limit" in lowered or "quota" in lowered:
        return "DeepSeek 调用失败：接口限流或额度不足。请稍后重试，或检查 DeepSeek 账号额度。"
    clean = " ".join(raw.split())
    if len(clean) > 300:
        clean = clean[:300] + "..."
    return f"DeepSeek 调用失败：{clean}"


async def call_llm(
    response_model: type[BaseModel],
    messages: list[dict],
    max_tokens: int = 1200,
    temperature: float = 0.3,
    max_retries: int = 2,
) -> BaseModel:
    """异步调用 LLM，使用 AsyncOpenAI 客户端避免阻塞
    
    修复说明：
    - 原实现使用同步 OpenAI 客户端 + asyncio.to_thread，导致大响应时阻塞
    - 新实现使用 AsyncOpenAI 客户端，真正异步非阻塞
    - 新增限流保护：每次 LLM 调用间隔至少 2 秒，防止 api.longcat.chat 代理返回 429
    """
    global _llm_last_call_at

    # 限流保护：确保两次 LLM 调用之间有最小间隔
    _min_interval = 2.0  # 每次 LLM 调用间隔至少 2 秒
    async with _get_llm_rate_lock():
        now = time.monotonic()
        elapsed = now - _llm_last_call_at
        if elapsed < _min_interval:
            wait = _min_interval - elapsed
            print(f"[DEBUG] LLM rate limit: waiting {wait:.2f}s")
            await asyncio.sleep(wait)
        _llm_last_call_at = time.monotonic()

    async def _async_call() -> BaseModel:
        client = _get_async_instructor_client()
        return await client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            response_model=response_model,
            max_retries=max_retries,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"thinking": {"type": "disabled"}},
            messages=messages,
        )

    try:
        # 使用 asyncio.wait_for 设置超时，比客户端内置超时更可控
        result = await asyncio.wait_for(_async_call(), timeout=config.DEEPSEEK_TIMEOUT)
        # v9: 收集 token 消耗统计
        try:
            from .utils import get_pipeline_stats
            stats = get_pipeline_stats()
            if stats is not None:
                stats.deepseek_calls += 1
                usage = getattr(getattr(result, '_raw_response', None), 'usage', None)
                if usage:
                    stats.deepseek_prompt_tokens += getattr(usage, 'prompt_tokens', 0) or 0
                    stats.deepseek_completion_tokens += getattr(usage, 'completion_tokens', 0) or 0
        except Exception:
            pass
        return result
    except asyncio.TimeoutError:
        raise LLMCallError(
            f"DeepSeek 调用失败：请求超过 {config.DEEPSEEK_TIMEOUT}s。"
            "请稍后重试，或适当调大 DEEPSEEK_TIMEOUT。"
        )
    except (ConfigurationError, DependencyMissingError):
        raise
    except LLMCallError:
        raise
    except Exception as exc:
        raise LLMCallError(_format_llm_error(exc)) from exc


def parse_coord_location(location: str) -> dict[str, float] | None:
    try:
        lng, lat = location.split(",", 1)
        return {"lat": float(lat), "lng": float(lng)}
    except (AttributeError, ValueError):
        return None


def _parse_gaode_polyline(polyline: Any) -> list[list[float]]:
    if not isinstance(polyline, str) or not polyline.strip():
        return []
    coords: list[list[float]] = []
    for item in polyline.split(";"):
        parts = item.split(",")
        if len(parts) < 2:
            continue
        lng = safe_float(parts[0])
        lat = safe_float(parts[1])
        if lat is None or lng is None:
            continue
        coords.append([lat, lng])
    return coords


def _coord_distance_m(a: list[float], b: list[float]) -> float:
    """两点间距离（米），坐标格式 [lat, lng]"""
    if not a or not b or len(a) < 2 or len(b) < 2:
        return float("inf")
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def _merge_polyline_chunks(
    chunks: list[list[list[float]]],
    snap_threshold_m: float = 5.0,
    max_join_gap_m: float | None = None,
) -> list[list[float]]:
    """拼接多段polyline，用距离阈值去除接缝处重合/抖动点。

    snap_threshold_m: 距离小于此值(米)的相邻点视为重合，跳过。
    max_join_gap_m: 若前段末端与后段首端距离超过此值，判定 chunk 不连续，返回 []。
    """
    coords: list[list[float]] = []
    snap_deg = snap_threshold_m / 111000
    snap_deg_sq = snap_deg * snap_deg
    for chunk in chunks:
        valid = [c for c in chunk if len(c) >= 2]
        if not valid:
            continue
        if coords and max_join_gap_m is not None:
            gap_m = _coord_distance_m(coords[-1], valid[0])
            if gap_m > max_join_gap_m:
                print(f"[RouteDebug] discontinuous polyline chunks: gap={gap_m:.0f}m limit={max_join_gap_m:.0f}m")
                return []
        for coord in valid:
            if len(coord) < 2:
                continue
            if coords:
                dlat = coord[0] - coords[-1][0]
                dlng = coord[1] - coords[-1][1]
                if dlat * dlat + dlng * dlng < snap_deg_sq:
                    continue
            coords.append(coord)
    return coords


def _extract_steps_polyline(value: dict[str, Any]) -> list[list[float]]:
    steps = value.get("steps") or []
    return _merge_polyline_chunks(
        [_parse_gaode_polyline(step.get("polyline")) for step in steps],
        max_join_gap_m=120,
    )


def _collect_nested_polylines(value: Any) -> list[list[list[float]]]:
    if isinstance(value, dict):
        chunks: list[list[list[float]]] = []
        polyline = _parse_gaode_polyline(value.get("polyline"))
        if polyline:
            chunks.append(polyline)
        for key, child in value.items():
            if key != "polyline":
                chunks.extend(_collect_nested_polylines(child))
        return chunks
    if isinstance(value, list):
        chunks = []
        for item in value:
            chunks.extend(_collect_nested_polylines(item))
        return chunks
    return []


def _extract_path_polyline(path: dict[str, Any]) -> list[list[float]]:
    steps_polyline = _extract_steps_polyline(path)
    if steps_polyline:
        return steps_polyline
    return _merge_polyline_chunks(_collect_nested_polylines(path), max_join_gap_m=200)


def _extract_transit_polyline(transit: dict[str, Any]) -> list[list[float]]:
    chunks: list[list[list[float]]] = []
    for segment in transit.get("segments") or []:
        walking = segment.get("walking") or {}
        walking_polyline = _extract_steps_polyline(walking)
        if walking_polyline:
            chunks.append(walking_polyline)

        bus = segment.get("bus") or {}
        for busline in bus.get("buslines") or []:
            busline_polyline = _parse_gaode_polyline(busline.get("polyline"))
            if busline_polyline:
                chunks.append(busline_polyline)

        railway = segment.get("railway") or {}
        railway_polyline = _merge_polyline_chunks(_collect_nested_polylines(railway))
        if railway_polyline:
            chunks.append(railway_polyline)

    if chunks:
        result = _merge_polyline_chunks(chunks, max_join_gap_m=350)
        if result:
            return result
        # 显式拼接失败，尝试 nested fallback 但同样做连续性校验
        nested = _merge_polyline_chunks(_collect_nested_polylines(transit), max_join_gap_m=350)
        return nested if nested else []
    return _merge_polyline_chunks(_collect_nested_polylines(transit), max_join_gap_m=350)


def _normalize_poi(raw: dict[str, Any]) -> dict[str, Any] | None:
    location = raw.get("location")
    if isinstance(location, str):
        parsed = parse_coord_location(location)
    elif isinstance(location, dict) and "lat" in location and "lng" in location:
        parsed = {"lat": float(location["lat"]), "lng": float(location["lng"])}
    else:
        parsed = None
    if not parsed:
        return None

    biz_ext = raw.get("biz_ext") or {}
    poiweight_raw = raw.get("poiweight")
    if isinstance(poiweight_raw, list) and len(poiweight_raw) > 0:
        poiweight = safe_float(poiweight_raw[0])
    else:
        poiweight = safe_float(poiweight_raw) if not isinstance(poiweight_raw, list) else None
    photos_raw = raw.get("photos") or []
    photos = []
    if isinstance(photos_raw, list):
        for photo in photos_raw:
            if not isinstance(photo, dict):
                continue
            url = photo.get("url") or photo.get("contentUrl")
            if url:
                photos.append({
                    "title": photo.get("title") or photo.get("name") or "",
                    "url": url,
                })

    return {
        "name": raw.get("name", ""),
        "typecode": raw.get("typecode", ""),
        "location": parsed,
        "id": raw.get("id") or raw.get("gaode_poi_id") or raw.get("uid") or raw.get("name", ""),
        "address": raw.get("address") or raw.get("formatted_address") or "",
        "rating": raw.get("rating") or biz_ext.get("rating") or "",
        "biz_ext": {"cost": biz_ext.get("cost") if isinstance(biz_ext, dict) else None},
        "poiweight": poiweight,
        "indoor_map": raw.get("indoor_map", ""),
        "photos": photos,
    }


def _check_gaode_response(data: dict[str, Any], api_name: str) -> None:
    if str(data.get("status", "1")) == "0":
        info = data.get("info") or data.get("infocode") or "未知错误"
        raise ExternalAPIError(f"高德 {api_name} 接口返回失败：{info}")


def _is_gaode_qps_error(data: dict[str, Any]) -> bool:
    if str(data.get("status", "1")) != "0":
        return False
    info = str(data.get("info") or "")
    infocode = str(data.get("infocode") or "")
    text = f"{info} {infocode}".upper()
    return "QPS" in text or "EXCEEDED_THE_LIMIT" in text


async def _gaode_rate_limit() -> None:
    global _gaode_last_request_at
    async with _get_gaode_rate_lock():
        now = time.monotonic()
        wait = config.GAODE_RATE_SLEEP - (now - _gaode_last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _gaode_last_request_at = time.monotonic()


async def _bocha_rate_limit() -> None:
    global _bocha_last_request_at
    async with _get_bocha_rate_lock():
        now = time.monotonic()
        wait = config.BOCHA_RATE_SLEEP - (now - _bocha_last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _bocha_last_request_at = time.monotonic()


async def _gaode_get_json(api_name: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
    global _prefer_curl_get
    last_qps_error = None
    last_network_error = None
    semaphore = _get_gaode_semaphore()
    async with semaphore:
        for attempt in range(config.GAODE_QPS_MAX_RETRIES):
            try:
                await _gaode_rate_limit()
                if _prefer_curl_get:
                    data = await asyncio.to_thread(_curl_get_json, url, params, min(config.GAODE_TIMEOUT, API_TIMEOUT))
                else:
                    try:
                        data = await asyncio.to_thread(_http_json, "GET", url, params, None, None, min(config.GAODE_TIMEOUT, API_TIMEOUT))
                    except Exception:
                        _prefer_curl_get = True
                        data = await asyncio.to_thread(_curl_get_json, url, params, min(config.GAODE_TIMEOUT, API_TIMEOUT))
                if _is_gaode_qps_error(data):
                    last_qps_error = data
                    if attempt < config.GAODE_QPS_MAX_RETRIES - 1:
                        await asyncio.sleep(config.GAODE_QPS_RETRY_SLEEP * (attempt + 1))
                        continue
                _check_gaode_response(data, api_name)
                # v9: 高德 API 调用计数
                try:
                    from .utils import get_pipeline_stats
                    stats = get_pipeline_stats()
                    if stats is not None:
                        stats.gaode_calls += 1
                except Exception:
                    pass
                return data
            except Exception as exc:
                last_network_error = exc
                if attempt < config.GAODE_QPS_MAX_RETRIES - 1:
                    sleep_time = 0.6 * (attempt + 1)  # 更快恢复：0.6s / 1.2s
                    await asyncio.sleep(sleep_time)
                    continue
                raise ExternalAPIError(f"高德 {api_name} 请求失败（已重试{config.GAODE_QPS_MAX_RETRIES}次）：{exc}") from exc

        _check_gaode_response(last_qps_error or {}, api_name)
        raise ExternalAPIError(f"高德 {api_name} 接口返回失败：CUQPS_HAS_EXCEEDED_THE_LIMIT")


async def gaode_around_search(
    location: str,
    keywords: str,
    radius: int = 20000,
    types: str = "",
    show_fields: str = "biz_ext",
    offset: int = 20,
    sortrule: str = "",
) -> list[dict]:
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["around_search"]
    params = {
        "key": config.GAODE_API_KEY,
        "location": location,
        "keywords": keywords,
        "radius": radius,
        "types": types,
        "show_fields": show_fields,
        "page_size": offset,
    }
    if sortrule:
        params["sortrule"] = sortrule
    try:
        data = await _gaode_get_json("周边搜索", url, params)
        pois = data.get("pois") or data.get("data", {}).get("pois") or []
        normalized = [_normalize_poi(item) for item in pois]
        return [item for item in normalized if item]
    except (ConfigurationError, ExternalAPIError):
        raise
    except Exception as exc:
        raise ExternalAPIError(f"高德周边搜索失败：{exc}") from exc


async def gaode_text_search(keywords: str, city: str = "", show_fields: str = "") -> list[dict]:
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["text_search"]
    params = {"key": config.GAODE_API_KEY, "keywords": keywords, "city": city, "offset": 10, "extensions": "all"}
    if show_fields:
        params["show_fields"] = show_fields
    try:
        data = await _gaode_get_json("关键词搜索", url, params)
        normalized = [_normalize_poi(item) for item in data.get("pois", [])]
        return [item for item in normalized if item]
    except (ConfigurationError, ExternalAPIError):
        raise
    except Exception as exc:
        raise ExternalAPIError(f"高德关键词搜索失败：{exc}") from exc


async def gaode_place_detail(poi_id: str, show_fields: str = "business,photos") -> dict | None:
    """查询高德 POI 详情，优先使用 v5 detail 接口，兼容 v3 返回格式。"""
    if not poi_id:
        return None
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    candidates = [
        config.GAODE_BASE_URL + "/v5/place/detail",
        config.GAODE_BASE_URL + config.GAODE_ENDPOINTS.get("place_detail", "/v3/place/detail"),
    ]
    for url in candidates:
        params = {"key": config.GAODE_API_KEY, "id": poi_id, "show_fields": show_fields, "extensions": "all"}
        try:
            data = await _gaode_get_json("POI详情", url, params)
            pois = data.get("pois") or data.get("data", {}).get("pois") or []
            if isinstance(pois, dict):
                pois = [pois]
            normalized = [_normalize_poi(item) for item in pois]
            normalized = [item for item in normalized if item]
            if normalized:
                return normalized[0]
        except Exception:
            continue
    return None


async def gaode_geocode(address: str, city: str = "") -> dict | None:
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["geocode"]
    params = {"key": config.GAODE_API_KEY, "address": address, "city": city}
    try:
        data = await _gaode_get_json("地理编码", url, params)
        geocodes = data.get("geocodes") or []
        if not geocodes:
            raise ExternalAPIError(f"高德地理编码未找到地址：{address}")
        location = parse_coord_location(geocodes[0].get("location", ""))
        if not location:
            raise ExternalAPIError(f"高德地理编码返回坐标格式异常：{address}")
        location["label"] = geocodes[0].get("formatted_address") or address
        return location
    except (ConfigurationError, ExternalAPIError):
        raise
    except Exception as exc:
        raise ExternalAPIError(f"高德地理编码失败：{exc}") from exc


async def gaode_weather(city_adcode: str = "") -> dict:
    if not city_adcode:
        return {}
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["weather"]
    params = {"key": config.GAODE_API_KEY, "city": city_adcode, "extensions": "all"}
    try:
        data = await _gaode_get_json("天气", url, params)
        casts = (data.get("forecasts") or [{}])[0].get("casts") or []
        if not casts:
            raise ExternalAPIError("高德天气接口未返回 forecast.casts")
        result = {}
        for idx, cast in enumerate(casts[:3], start=1):
            temp = f"{cast.get('nighttemp', '')}-{cast.get('daytemp', '')}℃"
            result[f"day{idx}"] = {"weather": cast.get("dayweather") or "", "temp": temp}
        return result
    except (ConfigurationError, ExternalAPIError):
        raise
    except Exception as exc:
        raise ExternalAPIError(f"高德天气查询失败：{exc}") from exc


async def gaode_weather_live(city_adcode: str = "") -> dict | None:
    """调用高德天气实况接口（extensions=base），返回 lives[0] 实时天气"""
    if not city_adcode:
        return None
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["weather"]
    params = {"key": config.GAODE_API_KEY, "city": city_adcode, "extensions": "base", "output": "JSON"}
    try:
        data = await _gaode_get_json("天气实况", url, params)
        lives = data.get("lives") or []
        if not lives:
            return None
        return lives[0]
    except Exception as exc:
        raise ExternalAPIError(f"高德天气实况查询失败：{exc}") from exc


async def gaode_transit_route(
    origin: str,
    destination: str,
    city: str = "",
    strategy: int = 0,
    require_polyline: bool = True,
    departure_time: Any = None,
) -> dict | None:
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["transit_route"]
    params: dict[str, Any] = {
        "key": config.GAODE_API_KEY,
        "origin": origin,
        "destination": destination,
        "city": city,
        "strategy": strategy,
    }
    if departure_time is not None:
        try:
            params["date"] = departure_time.strftime("%Y-%m-%d")
            params["time"] = departure_time.strftime("%H:%M")
        except (AttributeError, ValueError):
            pass
    try:
        data = await _gaode_get_json("公交路线", url, params)
        transits = data.get("route", {}).get("transits") or []
        if not transits:
            raise ExternalAPIError("高德公交路线接口未返回可用路线")
        item = transits[0]
        polyline = _extract_transit_polyline(item)
        if require_polyline and len(polyline) < 2:
            raise ExternalAPIError("高德公交路线接口未返回可绘制路线坐标")
        return {
            "duration_min": round((safe_float(item.get("duration")) or 0) / 60, 1),
            "distance_km": round((safe_float(item.get("distance")) or 0) / 1000, 2),
            "transport": "地铁/公交",
            "polyline": polyline,
        }
    except (ConfigurationError, ExternalAPIError):
        raise
    except Exception as exc:
        raise ExternalAPIError(f"高德公交路线查询失败：{exc}") from exc


async def gaode_driving_route(origin: str, destination: str) -> dict | None:
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["driving_route"]
    params = {"key": config.GAODE_API_KEY, "origin": origin, "destination": destination}
    try:
        data = await _gaode_get_json("驾车路线", url, params)
        paths = data.get("route", {}).get("paths") or []
        if not paths:
            raise ExternalAPIError("高德驾车路线接口未返回可用路线")
        path = paths[0]
        polyline = _extract_path_polyline(path)
        if len(polyline) < 2:
            raise ExternalAPIError("高德驾车路线接口未返回可绘制路线坐标")
        return {
            "duration_min": round((safe_float(path.get("duration")) or 0) / 60, 1),
            "distance_km": round((safe_float(path.get("distance")) or 0) / 1000, 2),
            "transport": "自驾",
            "polyline": polyline,
        }
    except (ConfigurationError, ExternalAPIError):
        raise
    except Exception as exc:
        raise ExternalAPIError(f"高德驾车路线查询失败：{exc}") from exc


async def gaode_walking_route(origin: str, destination: str, require_polyline: bool = True) -> dict | None:
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["walking_route"]
    params = {"key": config.GAODE_API_KEY, "origin": origin, "destination": destination}
    try:
        data = await _gaode_get_json("步行路线", url, params)
        paths = data.get("route", {}).get("paths") or []
        if not paths:
            raise ExternalAPIError("高德步行路线接口未返回可用路线")
        path = paths[0]
        polyline = _extract_path_polyline(path)
        if require_polyline and len(polyline) < 2:
            raise ExternalAPIError("高德步行路线接口未返回可绘制路线坐标")
        return {
            "duration_min": round((safe_float(path.get("duration")) or 0) / 60, 1),
            "distance_km": round((safe_float(path.get("distance")) or 0) / 1000, 2),
            "transport": "步行",
            "polyline": polyline,
        }
    except (ConfigurationError, ExternalAPIError):
        raise
    except Exception as exc:
        raise ExternalAPIError(f"高德步行路线查询失败：{exc}") from exc


def _is_bocha_rate_limit(data: dict[str, Any]) -> bool:
    code = str(data.get("code", ""))
    msg = str(data.get("msg") or data.get("message") or "")
    lowered = msg.lower()
    return code == "429" or "429" in msg or "rate" in lowered or "limit" in lowered or "qps" in lowered


def _bocha_code(data: dict[str, Any]) -> str:
    return str(data.get("code", "")).strip()


def _is_bocha_success(data: dict[str, Any]) -> bool:
    return _bocha_code(data) in {"", "0", "200"}


def _format_bocha_error(data: dict[str, Any]) -> str:
    code = _bocha_code(data)
    msg = str(data.get("msg") or data.get("message") or "").strip()
    suffix = f"{code}：{msg}" if msg else code or "未知错误"
    if code in {"401", "403"}:
        return (
            f"博查搜索鉴权或权限失败（{suffix}）。请检查 BOCHA_API_KEY 是否正确、"
            "是否已写入 .env、账号是否开通该接口且额度未耗尽。"
        )
    return f"博查搜索接口返回失败：{suffix}"


async def bocha_search(query: str, count: int | None = None, summary: bool = True, freshness: str = "noLimit") -> list[dict]:
    _require_key("博查搜索", "BOCHA_API_KEY", config.BOCHA_API_KEY)
    url = config.BOCHA_BASE_URL + config.BOCHA_ENDPOINT
    headers = {"Authorization": f"Bearer {config.BOCHA_API_KEY}", "Content-Type": "application/json"}
    payload = {"query": query, "summary": summary, "count": count or config.BOCHA_COUNT, "freshness": freshness}
    async with _get_bocha_semaphore():
        last_rate_limit: dict[str, Any] | None = None
        for attempt in range(config.BOCHA_MAX_RETRIES):
            await _bocha_rate_limit()
            try:
                transport_errors: list[str] = []
                try:
                    data = await asyncio.to_thread(
                        _http_json,
                        "POST",
                        url,
                        None,
                        payload,
                        headers,
                        config.BOCHA_TIMEOUT,
                        True,
                    )
                except Exception as exc:
                    transport_errors.append(f"urllib直连失败：{exc}")
                    try:
                        data = await asyncio.to_thread(_requests_json, "POST", url, None, payload, headers, API_TIMEOUT)
                    except Exception as requests_exc:
                        transport_errors.append(f"requests直连失败：{requests_exc}")
                        try:
                            data = await asyncio.to_thread(_curl_post_json, url, payload, headers, API_TIMEOUT, True)
                        except Exception as curl_exc:
                            transport_errors.append(f"curl直连失败：{curl_exc}")
                            raise ExternalAPIError(
                                "博查搜索直连失败（已绕过 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY）。"
                                "如果正在开启 VPN/代理，请尝试为 api.bocha.cn 设置直连或临时关闭 VPN。"
                                f" 细节：{' | '.join(transport_errors)}"
                            ) from curl_exc
                if not _is_bocha_success(data):
                    if _is_bocha_rate_limit(data):
                        last_rate_limit = data
                        if attempt < config.BOCHA_MAX_RETRIES - 1:
                            await asyncio.sleep(config.BOCHA_429_RETRY_SLEEP)
                            continue
                        error = data.get("msg") or data.get("message") or data.get("code")
                        raise ExternalAPIError(f"博查搜索接口返回失败：{error}；已按当前 BOCHA_MAX_CONCURRENCY / BOCHA_RATE_SLEEP 配置限流并重试")
                    raise ExternalAPIError(_format_bocha_error(data))
                # v9: 博查 API 调用计数
                try:
                    from .utils import get_pipeline_stats
                    stats = get_pipeline_stats()
                    if stats is not None:
                        stats.bocha_calls += 1
                except Exception:
                    pass
                results = data.get("data", {}).get("webPages", {}).get("value") or []
                return [
                    {
                        "name": item.get("name", ""),
                        "snippet": item.get("summary") or item.get("snippet", ""),
                        "url": item.get("url", ""),
                        "siteName": item.get("siteName", ""),
                    }
                    for item in results
                ]
            except (ConfigurationError, ExternalAPIError):
                raise
            except Exception as exc:
                raise ExternalAPIError(f"博查搜索失败：{exc}") from exc

    error = last_rate_limit.get("msg") or last_rate_limit.get("code") if last_rate_limit else "429"
    raise ExternalAPIError(f"博查搜索接口返回失败：{error}；已按当前 BOCHA_MAX_CONCURRENCY / BOCHA_RATE_SLEEP 配置限流并重试")


def _collect_bocha_image_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"contentUrl", "thumbnailUrl", "imageUrl"} and isinstance(child, str):
                urls.append(child)
            elif key == "url" and isinstance(child, str) and any(token in child.lower() for token in [".jpg", ".jpeg", ".png", ".webp"]):
                urls.append(child)
            else:
                urls.extend(_collect_bocha_image_urls(child))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_collect_bocha_image_urls(item))
    return urls


async def bocha_image_search(query: str, count: int = 5) -> list[str]:
    """从博查搜索结果中提取图片 URL，兼容 images.value / webPages.value 等多种结构。"""
    _require_key("博查搜索", "BOCHA_API_KEY", config.BOCHA_API_KEY)
    url = config.BOCHA_BASE_URL + config.BOCHA_ENDPOINT
    headers = {"Authorization": f"Bearer {config.BOCHA_API_KEY}", "Content-Type": "application/json"}
    payload = {"query": query, "summary": False, "count": count, "freshness": "noLimit"}
    async with _get_bocha_semaphore():
        await _bocha_rate_limit()
        try:
            data = await asyncio.to_thread(
                _http_json,
                "POST",
                url,
                None,
                payload,
                headers,
                API_TIMEOUT,
                True,
            )
        except Exception:
            data = await asyncio.to_thread(_curl_post_json, url, payload, headers, API_TIMEOUT, True)
    if not _is_bocha_success(data):
        return []
    deduped: list[str] = []
    seen = set()
    for image_url in _collect_bocha_image_urls(data):
        if image_url not in seen:
            deduped.append(image_url)
            seen.add(image_url)
    return deduped[:count]


async def gaode_around_search_batch(requests: list[dict]) -> list[list[dict]]:
    async def _one(req: dict) -> list[dict]:
        return await gaode_around_search(**req)

    return await asyncio.gather(*[_one(req) for req in requests])


async def gaode_reverse_geocode(location: str) -> dict | None:
    """逆地理编码，返回 addressComponent"""
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + "/v3/geocode/regeo"
    params = {"key": config.GAODE_API_KEY, "location": location, "extensions": "all"}
    try:
        data = await _gaode_get_json("逆地理编码", url, params)
        return data.get("regeocode", {}).get("addressComponent")
    except Exception:
        return None


async def gaode_get_district_boundary(keywords: str, max_points: int = 40) -> str | None:
    """获取行政区边界多边形的简化版本，用于多边形搜索"""
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + "/v3/config/district"
    params = {"key": config.GAODE_API_KEY, "keywords": keywords, "subdistrict": 0, "extensions": "all"}
    try:
        data = await _gaode_get_json("行政区划", url, params)
        districts = data.get("districts") or []
        if not districts:
            return None
        polyline = districts[0].get("polyline", "")
        if not polyline:
            return None
        pts = polyline.split(";")
        if len(pts) <= max_points:
            return polyline
        # 等间隔采样简化
        step = max(1, len(pts) // max_points)
        simplified = ";".join(pts[::step])
        # 确保闭合：最后一个点与首点相同
        if simplified.split(";")[-1] != pts[-1]:
            simplified += ";" + pts[-1]
        return simplified
    except Exception:
        return None


async def gaode_polygon_search(
    polygon: str,
    keywords: str = "",
    types: str = "",
    offset: int = 20,
    show_fields: str = "",
) -> list[dict]:
    """多边形范围内搜索POI"""
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + "/v3/place/polygon"
    params: dict[str, Any] = {
        "key": config.GAODE_API_KEY,
        "polygon": polygon,
        "offset": offset,
        "extensions": "all",
    }
    if keywords:
        params["keywords"] = keywords
    if types:
        params["types"] = types
    if show_fields:
        params["show_fields"] = show_fields
    try:
        data = await _gaode_get_json("多边形搜索", url, params)
        normalized = [_normalize_poi(item) for item in data.get("pois", [])]
        return [item for item in normalized if item]
    except ExternalAPIError:
        return []


async def gaode_polygon_search_batch(requests: list[dict]) -> list[list[dict]]:
    async def _one(req: dict) -> list[dict]:
        return await gaode_polygon_search(**req)

    return await asyncio.gather(*[_one(req) for req in requests])


async def bocha_search_batch(queries: list[str]) -> list[list[dict]]:
    return await asyncio.gather(*[bocha_search(query) for query in queries])


async def gaode_transit_batch(pairs: list[tuple[str, str]], city: str = "") -> list[dict | None]:
    return await asyncio.gather(*[gaode_transit_route(pair[0], pair[1], city=city) for pair in pairs])


# ═══════════════════════════════════════════════════════════════
# v4: 先路后点架构所需 API
# ═══════════════════════════════════════════════════════════════

async def gaode_regeo_road(location: str, roadlevel: int = 1) -> dict | None:
    """v4: 逆地理编码并附带 roads / roadinters。
    返回字段: {"roads": [...], "roadinters": [...], "formatted_address": str,
              "primary_road": str | None, "city": str, "adcode": str}
    主路名优先取距离最近的"主干道"，找不到则取 roads[0]。
    """
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + "/v3/geocode/regeo"
    params = {
        "key": config.GAODE_API_KEY,
        "location": location,
        "extensions": "all",
        "roadlevel": roadlevel,
    }
    try:
        data = await _gaode_get_json("逆地理编码(主路)", url, params)
        regeo = data.get("regeocode", {})
        addr_comp = regeo.get("addressComponent") or {}
        roads = regeo.get("roads") or []
        roadinters = regeo.get("roadinters") or []
        primary = None
        if roads:
            with_dist = []
            for r in roads:
                try:
                    d = float(r.get("distance", 9999))
                except (TypeError, ValueError):
                    d = 9999.0
                if r.get("name"):
                    with_dist.append((d, r.get("name")))
            with_dist.sort()
            if with_dist:
                primary = with_dist[0][1]
        return {
            "roads": [r.get("name", "") for r in roads if r.get("name")],
            "roadinters": roadinters,
            "formatted_address": regeo.get("formatted_address") or "",
            "primary_road": primary,
            "city": addr_comp.get("city") or addr_comp.get("province") or "",
            "citycode": addr_comp.get("citycode") or "",
            "adcode": addr_comp.get("adcode") or "",
        }
    except (ConfigurationError, ExternalAPIError):
        return None
    except Exception:
        return None


async def gaode_road_polyline(road_name: str, city: str = "") -> list[list[float]]:
    """v4: 用文本搜索接口在城市内查询道路 POI，从结果中合并 polyline。
    高德 v3 没有公开的 "road by name" 端点；用 place/text + types=190301(道路)
    或直接关键词搜索得到 polyline 字段。
    返回 [[lat, lng], ...] 形式的有序点列；查不到返回 []。
    """
    if not road_name:
        return []
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["text_search"]
    params = {
        "key": config.GAODE_API_KEY,
        "keywords": road_name,
        "city": city,
        "types": "190301|190302|190303|190304",
        "extensions": "all",
        "offset": 5,
        "citylimit": "true" if city else None,
    }
    # Remove None values
    params = {k: v for k, v in params.items() if v is not None}
    try:
        data = await _gaode_get_json("道路查询", url, params)
        pois = data.get("pois") or []
        chunks: list[list[list[float]]] = []
        for poi in pois:
            poly_str = poi.get("polyline") or ""
            if not poly_str:
                continue
            chunk = _parse_gaode_polyline(poly_str)
            if chunk:
                chunks.append(chunk)
        merged = _merge_polyline_chunks(chunks)
        return merged
    except (ConfigurationError, ExternalAPIError):
        return []
    except Exception:
        return []


async def gaode_walking_route_waypoints(
    origin: str,
    destination: str,
    waypoints: list[str] | None = None,
) -> dict | None:
    """v4: 步行路线 + 可选途经点。
    waypoints: ["lng,lat", "lng,lat", ...] 高德 v3 walking 不支持 waypoints，
    所以走分段调用 + 拼接 polyline。
    返回 {transport, duration_min, distance_km, polyline, steps}
    """
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    points = [origin]
    if waypoints:
        points.extend(waypoints)
    points.append(destination)

    seg_tasks = []
    for i in range(len(points) - 1):
        seg_tasks.append(_gaode_walking_segment(points[i], points[i + 1]))
    segments = await asyncio.gather(*seg_tasks)
    if not all(segments):
        return None

    merged: list[list[float]] = []
    total_dur = 0.0
    total_dist = 0.0
    all_steps: list[dict[str, Any]] = []
    for seg in segments:
        if not seg:
            continue
        total_dur += seg.get("duration_min", 0.0)
        total_dist += seg.get("distance_km", 0.0)
        polyline = seg.get("polyline") or []
        for pt in polyline:
            if len(pt) < 2:
                continue
            if merged:
                dlat = pt[0] - merged[-1][0]
                dlng = pt[1] - merged[-1][1]
                # 5m阈值去重，避免接缝处重合/抖动线
                if dlat * dlat + dlng * dlng < (5.0 / 111000) ** 2:
                    continue
            merged.append(pt)
        for step in seg.get("steps") or []:
            all_steps.append(step)

    return {
        "transport": "步行",
        "duration_min": round(total_dur, 1),
        "distance_km": round(total_dist, 3),
        "polyline": merged,
        "steps": all_steps,
    }


async def _gaode_walking_segment(origin: str, destination: str) -> dict | None:
    """内部：单段步行路线，含 steps 详情。"""
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + config.GAODE_ENDPOINTS["walking_route"]
    params = {"key": config.GAODE_API_KEY, "origin": origin, "destination": destination}
    try:
        data = await _gaode_get_json("步行路线(分段)", url, params)
        paths = data.get("route", {}).get("paths") or []
        if not paths:
            return None
        path = paths[0]
        polyline = _extract_path_polyline(path)
        steps_raw = path.get("steps") or []
        steps_out = []
        for s in steps_raw:
            steps_out.append({
                "road_name": s.get("road") or "",
                "distance": safe_float(s.get("distance")) or 0.0,
                "polyline": _parse_gaode_polyline(s.get("polyline") or ""),
                "instruction": s.get("instruction") or "",
                "action": s.get("action") or s.get("assistant_action") or "",
            })
        return {
            "transport": "步行",
            "duration_min": round((safe_float(path.get("duration")) or 0) / 60, 1),
            "distance_km": round((safe_float(path.get("distance")) or 0) / 1000, 3),
            "polyline": polyline,
            "steps": steps_out,
        }
    except Exception:
        return None


async def gaode_bicycling_route(origin: str, destination: str) -> dict | None:
    """v4: 骑行路线（1~2km 跨段使用）。"""
    _require_key("高德地图", "GAODE_API_KEY", config.GAODE_API_KEY)
    url = config.GAODE_BASE_URL + "/v4/direction/bicycling"
    params = {"key": config.GAODE_API_KEY, "origin": origin, "destination": destination}
    try:
        data = await _gaode_get_json("骑行路线", url, params)
        paths = ((data.get("data") or {}).get("paths") or [])
        if not paths:
            return None
        path = paths[0]
        polyline = _extract_path_polyline(path)
        if len(polyline) < 2:
            return None
        return {
            "transport": "骑行",
            "duration_min": round((safe_float(path.get("duration")) or 0) / 60, 1),
            "distance_km": round((safe_float(path.get("distance")) or 0) / 1000, 3),
            "polyline": polyline,
        }
    except Exception:
        return None


def raw_to_place(raw: dict[str, Any]) -> dict[str, Any]:
    rating = safe_float(raw.get("rating"))
    cost = safe_float((raw.get("biz_ext") or {}).get("cost"))
    pw = raw.get("poiweight")
    poiweight = safe_float(pw[0] if isinstance(pw, list) and pw else pw)
    return {
        "name": raw.get("name", ""),
        "time_capacity": infer_capacity_from_typecode(raw.get("typecode", ""), raw.get("name", "")),
        "typecode": raw.get("typecode", ""),
        "location": raw.get("location") or {},
        "gaode_poi_id": raw.get("id") or raw.get("name", ""),
        "address": raw.get("address", ""),
        "gaode_rating": rating,
        "avg_cost": cost,
        "poiweight": poiweight,
        "indoor_map": raw.get("indoor_map", ""),
        "photo_url": ((raw.get("photos") or [{}])[0] or {}).get("url") if isinstance(raw.get("photos"), list) and raw.get("photos") else "",
    }
