from __future__ import annotations
import asyncio
import datetime as dt
import os
import sys
from collections.abc import AsyncGenerator

from .data_schema import CompletePlan, MicroPOI, RouteSegment
from .mock_profile import get_mock_profile
from .step1_intent import run_step1
from .step2_macro import run_step2
from .step3_micro import run_step3
from .step4_output import run_step4
from .utils import (
    ConfigurationError,
    DependencyMissingError,
    ExternalAPIError,
    LLMCallError,
    PipelineLogger,
    ZeroOutputError,
    emit_status,
    get_recorded_outputs,
    get_sse_queue,
    init_sse_queue,
    push_output,
)


INCOMPLETE_REQUEST_MESSAGE = "[ROUTE_PLANNER]: 消息似乎不全面，可以再说得详细一点吗~"


def _is_exit_command(user_input: str) -> bool:
    return user_input.strip().lower() == "quit"


def _is_incomplete_request(user_request: str) -> bool:
    text = user_request.strip()
    lowered = text.lower()
    if not text:
        return True
    if lowered in {"quit", "exit", "q", "/quit", "/exit", "/q"}:
        return True
    if text.startswith("/") and len(text) <= 24:
        return True
    return len(text) <= 2


async def _run_pipeline(user_request: str, logger: PipelineLogger, plan_mode: str = "exploratory") -> dict[str, int]:
    complete_plan: CompletePlan | None = None
    micro_pois: list[MicroPOI] = []
    route_segments: list[RouteSegment] = []
    try:
        await emit_status("正在加载用户信息...")
        user_profile = await get_mock_profile()
        current_time = dt.datetime.now().astimezone()
        parsed_intent = await run_step1(user_request, user_profile, current_time, logger, plan_mode=plan_mode)
        complete_plan = await run_step2(parsed_intent, user_profile, logger)
        micro_pois, route_segments, map_path, anchor_hints, waypoint_annotations, points = await run_step3(parsed_intent, complete_plan, logger)
        await run_step4(parsed_intent, complete_plan, micro_pois, route_segments, map_path, logger, anchor_hints, waypoint_annotations)
    except LLMCallError as exc:
        await logger.log_step("pipeline_error", status="error", details={"type": type(exc).__name__, "message": str(exc)})
        await push_output(f"[ROUTE_PLANNER]: {exc}")
    except (ConfigurationError, DependencyMissingError, ExternalAPIError, ZeroOutputError) as exc:
        await logger.log_step("pipeline_error", status="error", details={"type": type(exc).__name__, "message": str(exc)})
        await push_output(f"[ROUTE_PLANNER]: {exc}")
    except Exception as exc:
        await logger.log_step("pipeline_error", status="error", details={"type": type(exc).__name__, "message": str(exc)})
        await push_output(f"[ROUTE_PLANNER]: 路线规划暂时失败：{exc}")

    return {
        "anchors": sum(len(day.anchors) for day in complete_plan.day_plans) if complete_plan else 0,
        "micro_pois": len(micro_pois),
        "route_segments": len(route_segments),
    }


async def run_pipeline_structured(
    user_request: str,
    plan_mode: str = "exploratory",
) -> dict:
    """
    运行完整管道并返回结构化数据。
    不通过 SSE 流式输出，直接将结果返回给调用方用于构建前端 JSON。

    Returns:
        {
            "parsed_intent": ParsedIntent,
            "complete_plan": CompletePlan,
            "micro_pois": list[MicroPOI],
            "route_segments": list[RouteSegment],
            "points": list[dict],
            "map_path": str,
            "anchor_hints": dict[str, str],
            "waypoint_annotations": dict[str, dict],
        }
        如果管道失败，返回 None。
    """
    from .step1_intent import run_step1 as _step1
    from .step2_macro import run_step2 as _step2
    from .step3_micro import run_step3 as _step3
    from .mock_profile import get_mock_profile as _get_mock

    logger = PipelineLogger()

    try:
        user_profile = await _get_mock()
        current_time = dt.datetime.now().astimezone()
        parsed_intent = await _step1(user_request, user_profile, current_time, logger, plan_mode=plan_mode)
        complete_plan = await _step2(parsed_intent, user_profile, logger)
        micro_pois, route_segments, map_path, anchor_hints, waypoint_annotations, points = await _step3(parsed_intent, complete_plan, logger)

        return {
            "parsed_intent": parsed_intent,
            "complete_plan": complete_plan,
            "micro_pois": micro_pois,
            "route_segments": route_segments,
            "points": points,
            "map_path": map_path,
            "anchor_hints": anchor_hints,
            "waypoint_annotations": waypoint_annotations,
        }
    except Exception as exc:
        import logging
        _log = logging.getLogger(__name__)
        _log.error(f"[run_pipeline_structured] 管道执行失败: {exc}")
        return None


async def plan_route(user_request: str, plan_mode: str = "exploratory") -> AsyncGenerator[str, None]:
    if _is_incomplete_request(user_request):
        yield INCOMPLETE_REQUEST_MESSAGE
        return

    queue: asyncio.Queue = asyncio.Queue()
    init_sse_queue(queue)
    logger = PipelineLogger()

    async def _runner() -> None:
        try:
            final_counts = await _run_pipeline(user_request, logger, plan_mode=plan_mode)
            await logger.save(final_counts, final_outputs=get_recorded_outputs())
        except asyncio.CancelledError:
            await push_output("[ROUTE_PLANNER]: 请求中断，API 无响应或网络异常，请稍后重试")
            try:
                await logger.save({}, final_outputs=get_recorded_outputs())
            except Exception:
                pass
        except Exception as exc:
            await push_output(f"[ROUTE_PLANNER]: 内部异常：{exc}")
            try:
                await logger.save({}, final_outputs=get_recorded_outputs())
            except Exception:
                pass
        finally:
            await get_sse_queue().put(None)

    pipeline_task = asyncio.create_task(_runner())
    while True:
        try:
            idle_timeout = float(os.getenv("ROUTE_PLANNER_IDLE_TIMEOUT", "120"))
            msg = await asyncio.wait_for(queue.get(), timeout=idle_timeout)
        except asyncio.TimeoutError:
            timeout_msg = "[ROUTE_PLANNER]: 响应超时，API 可能无响应，已输出部分结果"
            await push_output(timeout_msg)
            pipeline_task.cancel()
            break
        if msg is None:
            break
        yield msg

    # Wait for runner to finish (handles CancelledError from cancel, or normal completion)
    await asyncio.gather(pipeline_task, return_exceptions=True)
    # Drain any remaining messages pushed during cleanup
    while True:
        try:
            msg = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if msg is None:
            break
        yield msg


async def _main() -> None:
    print("[ROUTE_PLANNER]: 欢迎使用路线规划系统！")
    print("[ROUTE_PLANNER]: 请选择规划模式：")
    print("[ROUTE_PLANNER]:   1 - 自由探索（系统推荐路线）")
    print("[ROUTE_PLANNER]:   2 - 连续决策（指定途经点，逐步规划）")
    while True:
        mode_input = input("请输入模式编号（默认1）：").strip()
        if _is_exit_command(mode_input):
            print("[ROUTE_PLANNER]: 已退出。")
            return
        if mode_input in ("", "1"):
            plan_mode = "exploratory"
            print("[ROUTE_PLANNER]: 已选择【自由探索】模式")
            break
        elif mode_input == "2":
            plan_mode = "planned"
            print("[ROUTE_PLANNER]: 已选择【连续决策】模式（请描述您的有序途经点，如：去百联又一城逛→找麦当劳吃晚饭→顺路买水果）")
            break
        else:
            print("[ROUTE_PLANNER]: 无效输入，请输入1或2")

    while True:
        user_input = input("请输入您的出行需求（输入 quit 退出）：").strip()
        if _is_exit_command(user_input):
            print("[ROUTE_PLANNER]: 已退出。")
            return
        if not user_input:
            print("[ROUTE_PLANNER]: 输入为空，请重新输入。")
            continue
        async for chunk in plan_route(user_input, plan_mode=plan_mode):
            print(chunk)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_main())
