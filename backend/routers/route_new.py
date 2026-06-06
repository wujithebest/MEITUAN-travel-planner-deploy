"""
新框架路线规划路由
POST /api/route/generate - 生成路线（上海内规划）
使用 meituan_competition_backened_527 4 阶段管道 + route_dto 转换
"""

import logging
import traceback
import uuid
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from models.route import RouteResponse
from models.base import ApiResponse, LocationInput
from services.main import run_pipeline_structured
from services.route_dto import build_gaode_route_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/route", tags=["路线规划（新框架）"])

# 内存存储路线
_route_store: dict[str, RouteResponse] = {}

def generate_route_id() -> str:
    return f"route_{uuid.uuid4().hex[:8]}"


@router.post("/generate", summary="生成旅行路线（新框架）")
async def generate_route(input_data: LocationInput):
    """
    根据自然语言输入生成旅行路线。
    使用 4 阶段管道（意图解析 → 宏观搜索 → 微观路线 → 输出）并返回前端可用格式。
    """
    logger.info("=" * 50)
    logger.info(f"[route_new] 收到请求, input={input_data.text}, days={input_data.days}")

    try:
        result = await run_pipeline_structured(input_data.text, plan_mode=input_data.plan_mode or "exploratory")

        if result is None:
            return ApiResponse(
                success=False,
                data=None,
                message="路线规划失败，请稍后重试或调整需求",
            )

        route_id = generate_route_id()

        # 使用 route_dto 构建高德前端格式
        gaode_response = build_gaode_route_json(
            points=result["points"],
            route_segments=result["route_segments"],
            hints=result["anchor_hints"],
            waypoint_annotations=result["waypoint_annotations"],
            text_summary=f"为您规划了{len(result['complete_plan'].day_plans)}天的上海之旅",
            map_paths=result.get("map_path") or [],
            complete_plan=result["complete_plan"],
        )

        logger.info(f"[route_new] 路线生成完成! route_id={route_id}, days={gaode_response.total_days}, points={sum(len(d.points) for d in gaode_response.days)}, distance={gaode_response.total_distance_km}km")

        return ApiResponse(
            success=True,
            data={
                "route_id": route_id,
                **gaode_response.model_dump(),
            },
            message="路线生成成功",
        )

    except Exception as e:
        logger.error(f"[route_new] 致命错误: {str(e)}")
        logger.error(f"[route_new] 堆栈: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                    "detail": traceback.format_exc(),
                },
            },
        )
