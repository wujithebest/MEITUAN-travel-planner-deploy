from __future__ import annotations
import asyncio
import datetime as _dt
import json
import math
import time
from pathlib import Path
from typing import Any, Callable, Awaitable

from config import LOG_DIR, STATUS_CALLBACK_FORMAT


class RoutePlannerError(Exception):
    """Base exception for the route planner pipeline."""


class LLMCallError(RoutePlannerError):
    """Raised when the LLM call fails and no direct result is available."""


class DependencyMissingError(RoutePlannerError):
    """Raised when a required Python package is not installed."""


class ConfigurationError(RoutePlannerError):
    """Raised when required environment configuration is missing."""


class ExternalAPIError(RoutePlannerError):
    """Raised when an external API request fails."""


class ZeroOutputError(RoutePlannerError):
    """Raised when a required pipeline stage has no result."""


# SSE 事件类型
SSE_EVENT_STATUS = "status"
SSE_EVENT_RESULT = "result"
SSE_EVENT_DONE = "done"
SSE_EVENT_ERROR = "error"


sse_queue: asyncio.Queue | None = None
_recorded_outputs: list[str] = []


def init_sse_queue(queue: asyncio.Queue) -> None:
    global sse_queue, _recorded_outputs
    sse_queue = queue
    _recorded_outputs = []


def get_sse_queue() -> asyncio.Queue:
    if sse_queue is None:
        raise RuntimeError("SSE queue has not been initialized")
    return sse_queue


async def emit_status(message: str) -> None:
    """发送状态消息（进度更新）"""
    if sse_queue is not None:
        data = json.dumps({
            "type": "status",
            "msg": message,
            "progress": None,
        }, ensure_ascii=False)
        await sse_queue.put(f"event: status\ndata: {data}\n\n")


async def push_output(message: str) -> None:
    """推送输出消息（最终结果的一部分）"""
    _recorded_outputs.append(message)
    if sse_queue is not None:
        data = json.dumps({
            "type": "result",
            "msg": message,
            "progress": None,
        }, ensure_ascii=False)
        await sse_queue.put(f"event: result\ndata: {data}\n\n")


async def emit_result(result_data: dict) -> None:
    """发送最终结果数据"""
    if sse_queue is not None:
        data = json.dumps({
            "type": "result",
            "content": result_data,
            "progress": None,
        }, ensure_ascii=False)
        await sse_queue.put(f"event: result\ndata: {data}\n\n")


async def emit_done(
    map_paths: list[str] | None = None,
    full_plan: dict | None = None,
    route_data: dict | None = None,
) -> None:
    """发送完成标记，包含地图路径、完整计划和路线数据
    
    Args:
        map_paths: 地图 HTML 文件路径列表
        full_plan: 完整计划数据（summary, city, duration, days）
        route_data: 路线数据（points, segments, hints, waypoint_annotations）
    """
    if sse_queue is not None:
        data = json.dumps({
            "type": "complete",
            "content": {
                "map_paths": map_paths or [],
                "full_plan": full_plan or {},
                "route_data": route_data or {},
            },
            "progress": 100,
        }, ensure_ascii=False)
        await sse_queue.put(f"event: complete\ndata: {data}\n\n")


async def emit_error(error_message: str) -> None:
    """发送错误消息（兼容多种字段名，前端按 error/content/msg 优先级读取）"""
    if sse_queue is not None:
        data = json.dumps({
            "type": "error",
            "error": error_message,
            "content": error_message,
            "msg": error_message,
            "progress": None,
        }, ensure_ascii=False)
        await sse_queue.put(f"event: error\ndata: {data}\n\n")


def get_recorded_outputs() -> list[str]:
    return list(_recorded_outputs)


def model_to_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, list):
        return [model_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: model_to_dict(item) for key, item in value.items()}
    return value


class PipelineLogger:
    def __init__(self) -> None:
        self.start_time = _dt.datetime.now().astimezone()
        self._total_start = time.perf_counter()
        self._step_starts: dict[str, float] = {}
        self.steps: list[dict[str, Any]] = []

    def start_step(self, name: str) -> None:
        self._step_starts[name] = time.perf_counter()

    async def log_step(
        self,
        name: str,
        status: str = "success",
        output_count: int = 0,
        duration_ms: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        started = self._step_starts.pop(name, None)
        if duration_ms is None:
            if started is None:
                duration_ms = 0
            else:
                duration_ms = int((time.perf_counter() - started) * 1000)
        entry = {
            "name": name,
            "status": status,
            "duration_ms": duration_ms,
            "output_count": output_count,
        }
        if details is not None:
            entry["details"] = model_to_dict(details)
        self.steps.append(entry)

    async def save(
        self,
        final_output_count: dict[str, int] | None = None,
        final_outputs: list[str] | None = None,
    ) -> Path:
        log_dir = Path(__file__).parent / LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        filename = self.start_time.strftime("%Y%m%d_%H%M%S") + ".json"
        path = log_dir / filename
        payload = {
            "timestamp": self.start_time.isoformat(),
            "total_duration_ms": int((time.perf_counter() - self._total_start) * 1000),
            "steps": self.steps,
            "final_output_count": final_output_count or {},
            "final_outputs": final_outputs or [],
        }
        path.write_text(json.dumps(model_to_dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def coord_to_param(location: dict[str, Any] | None) -> str:
    if not location:
        return ""
    return f"{location.get('lng')},{location.get('lat')}"


def parse_coord_param(value: str) -> dict[str, float] | None:
    try:
        lng, lat = value.split(",", 1)
        return {"lng": float(lng), "lat": float(lat)}
    except (AttributeError, ValueError):
        return None


def haversine_km(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float:
    if not a or not b:
        return 0.0
    lat1, lng1 = math.radians(float(a["lat"])), math.radians(float(a["lng"]))
    lat2, lng2 = math.radians(float(b["lat"])), math.radians(float(b["lng"]))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def normalize_meal_needs(meal_needs: list[str] | list[list[str]]) -> list[list[str]]:
    if not meal_needs:
        return []
    if all(isinstance(item, str) for item in meal_needs):
        return [list(meal_needs)]  # type: ignore[arg-type]
    return [list(day) for day in meal_needs]  # type: ignore[arg-type]


def capacity_budget(capacity: str) -> float:
    return {"full_day": 1.0, "half_day": 0.5, "quarter_day": 0.25}.get(capacity, 0.25)


async def handle_zero_output(
    step_name: str,
    current_count: int,
    retry_fn: Callable[[dict[str, Any]], Awaitable[list[Any]]],
    context: dict[str, Any],
) -> list[Any]:
    if current_count > 0:
        return []

    relaxed = dict(context)
    reject_capacities = list(relaxed.get("reject_capacities", []))
    if reject_capacities:
        reject_capacities.pop(0)
        relaxed["reject_capacities"] = reject_capacities
        result = await retry_fn(relaxed)
        if result:
            return result

    widened = dict(relaxed)
    widened["radius"] = int(widened.get("radius", 20000) * 1.5)
    result = await retry_fn(widened)
    if result:
        return result

    raise ZeroOutputError(f"{step_name} produced zero output")
