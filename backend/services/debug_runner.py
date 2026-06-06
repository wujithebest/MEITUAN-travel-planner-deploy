"""Quick debug runner for failing test cases."""
import asyncio
import sys
from .main import _run_pipeline
from .utils import PipelineLogger, init_sse_queue, get_recorded_outputs

FAILING_CASES = [
    # TEST #4
    "想去上海的二次元主题店逛逛，看看有没有谷子和手办，玩两天",
    # TEST #5
    "带父母去上海旅游两天，想去外滩看看，吃点本帮菜",
    # TEST #7
    "想去外滩和城隍庙，但外滩已经去过了就不要了，玩一天",
]


async def run_one(request: str, index: int):
    init_sse_queue(asyncio.Queue())
    logger = PipelineLogger()
    print(f"\n{'='*60}")
    print(f"DEBUG #{index}: {request}")
    print(f"{'='*60}")
    try:
        counts = await _run_pipeline(request, logger)
        await logger.save(counts, final_outputs=get_recorded_outputs())
        print(f"RESULT: anchors={counts['anchors']}, micro_pois={counts.get('meal_pois', counts.get('micro_pois', 0))}, route_segments={counts['route_segments']}")
    except Exception as e:
        import traceback
        print(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()


async def main():
    for i, request in enumerate(FAILING_CASES):
        await run_one(request, i + 1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main())
