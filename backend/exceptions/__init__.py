"""
自定义异常模块
定义所有业务异常类和全局异常处理器
"""

from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging

logger = logging.getLogger(__name__)


# ==================== 自定义异常类 ====================

class TravelPlannerError(Exception):
    """基础异常类"""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class LLMParseError(TravelPlannerError):
    """LLM解析失败"""
    def __init__(self, message: str = "LLM解析失败"):
        super().__init__(message, "LLM_PARSE_ERROR")


class POINotFoundError(TravelPlannerError):
    """POI未找到"""
    def __init__(self, poi_name: str = ""):
        message = f"未找到POI: {poi_name}" if poi_name else "未找到POI，请检查拼写"
        super().__init__(message, "POI_NOT_FOUND")


class GaodeAPIError(TravelPlannerError):
    """高德API调用失败"""
    def __init__(self, message: str = "高德API调用失败"):
        super().__init__(message, "GAODE_API_ERROR")


class RoutePlanningError(TravelPlannerError):
    """路线规划失败"""
    def __init__(self, message: str = "路线规划失败，建议更换交通方式"):
        super().__init__(message, "ROUTE_PLANNING_ERROR")


class WeatherAPIError(TravelPlannerError):
    """天气API调用失败"""
    def __init__(self, message: str = "天气数据获取失败"):
        super().__init__(message, "WEATHER_API_ERROR")


class CollabError(TravelPlannerError):
    """协作服务异常"""
    def __init__(self, message: str = "协作操作失败"):
        super().__init__(message, "COLLAB_ERROR")


class OutOfShanghaiError(TravelPlannerError):
    """外地地点错误 - 系统仅支持上海"""
    def __init__(self, location_name: str = ""):
        message = f"地点'{location_name}'不在上海市范围内" if location_name else "本系统仅支持上海市内旅游规划"
        super().__init__(message, "OUT_OF_SHANGHAI")


class DiaryError(TravelPlannerError):
    """日记服务异常"""
    def __init__(self, message: str = "日记生成失败"):
        super().__init__(message, "DIARY_ERROR")


# ==================== 全局异常处理器 ====================

def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器到FastAPI应用"""

    @app.exception_handler(TravelPlannerError)
    async def travel_planner_exception_handler(request: Request, exc: TravelPlannerError):
        logger.error(f"业务异常: [{exc.code}] {exc.message}")
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message
                }
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        from fastapi.encoders import jsonable_encoder
        logger.error(f"参数校验失败: {jsonable_encoder(exc.errors())}")
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求参数校验失败",
                    "details": jsonable_encoder(exc.errors())
                }
            }
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception(f"未处理异常: {str(exc)}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务器内部错误"
                }
            }
        )
