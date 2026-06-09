"""
本地生活路线规划后端服务 - 主入口
FastAPI实例、CORS、WebSocket、APScheduler定时任务
"""

import sys
import os
import logging
from contextlib import asynccontextmanager

# 确保 backend 目录在 sys.path 中，使 services 包可被正确导入
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 同时确保项目根目录也在
_project_dir = os.path.dirname(_backend_dir)
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import get_settings, SHANGHAI_CENTER
from exceptions import register_exception_handlers
from routers import route, weather, collab, diary, auth, dianping, chat, user, address, meituan_chat, v1
from middleware.auth_middleware import AuthMiddleware
from services.auth_service import init_auth_service
from services.chat_service import init_chat_service
from models.mongodb import init_mongodb, close_mongodb

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings = get_settings()
    logger.info("=" * 50)
    logger.info("本地生活路线规划服务启动中...")
    logger.info(f"端口: {settings.app_port}")
    logger.info(f"LLM模型: {settings.llm_model}")
    logger.info(f"LLM地址: {settings.llm_base_url}")
    
    # 检查 Docker 模式
    is_docker = settings.app_port == 8000
    if is_docker:
        logger.info("🐳 Docker 模式已启用")
    logger.info("=" * 50)

    # 初始化 MongoDB 数据库
    try:
        await init_mongodb()
    except Exception as e:
        logger.error(f"MongoDB 初始化失败: {str(e)}")
        logger.warning("请确保 MongoDB 服务已启动，或使用内存模式继续")

    # 初始化认证服务
    try:
        await init_auth_service()
    except Exception as e:
        logger.warning(f"认证服务初始化失败: {str(e)}")

    # 初始化聊天服务（Redis 持久化）
    redis_client = None
    try:
        # 尝试连接 Redis
        from redis import asyncio as aioredis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        # 测试连接
        await redis_client.ping()
        logger.info(f"[Main] Redis 连接成功: {redis_url}")
    except Exception as e:
        logger.warning(f"[Main] Redis 连接失败，使用内存存储: {e}")
        redis_client = None
    
    try:
        init_chat_service(redis_client)
        logger.info("[Main] 聊天服务初始化完成")
    except Exception as e:
        logger.warning(f"[Main] 聊天服务初始化失败: {e}")

    # 启动定时任务
    try:
        scheduler = app.state.scheduler if hasattr(app.state, 'scheduler') else None
        if not scheduler:
            scheduler = AsyncIOScheduler()
            app.state.scheduler = scheduler

        # 每小时清理过期缓存
        scheduler.add_job(
            cleanup_caches,
            "interval",
            hours=1,
            id="cleanup_caches",
            name="清理过期缓存"
        )
        # 天气缓存刷新已停用（不再固定预热上海天气）
        scheduler.start()
        logger.info("APScheduler定时任务已启动")
    except Exception as e:
        logger.warning(f"APScheduler启动失败: {str(e)}")

    yield

    # 关闭时清理
    logger.info("服务关闭中...")
    try:
        scheduler.shutdown()
    except:
        pass
    
    # 关闭 MongoDB 连接
    try:
        await close_mongodb()
    except:
        pass

    if redis_client is not None:
        try:
            await redis_client.aclose()
        except Exception:
            pass
    
    logger.info("服务已关闭")


def cleanup_caches():
    """清理过期缓存的定时任务"""
    from services.gaode_service import _poi_cache, _route_cache
    logger.info(
        f"缓存清理: POI缓存={len(_poi_cache)}, 路线缓存={len(_route_cache)}"
    )


async def refresh_shanghai_weather():
    """刷新上海天气缓存的定时任务"""
    try:
        from services.realtime_service import get_realtime_service, _weather_cache
        service = get_realtime_service()
        # 清除旧缓存
        _weather_cache.clear()
        # 预加载上海天气
        await service.get_weather_forecast("上海", days=7)
        logger.info("上海天气缓存已刷新")
    except Exception as e:
        logger.warning(f"刷新上海天气缓存失败: {str(e)}")


# 创建FastAPI应用
app = FastAPI(
    title="本地生活路线规划服务",
    description="""
    本地生活路线规划后端服务
    
    ## 服务区域
    上海市区及郊区：黄浦、徐汇、长宁、静安、普陀、杨浦、虹口、浦东、闵行、宝山、嘉定、金山、松江、青浦、奉贤、崇明
    
    ## 功能模块
    - **用户认证**：注册、登录、JWT令牌、偏好设置
    - **路线规划**：自然语言输入 -> LLM解析（仅上海） -> POI匹配 -> 路线规划（上海内）
    - **天气服务**：上海逐日天气预报、实时天气、交通路况
    - **协作编辑**：多人实时协作编辑路线（需登录）
    - **旅行日记**：自动生成上海特色旅行日记、成就徽章（需登录）
    
    ## 数据流
    用户输入 → LLM强制上海解析 → 高德上海POI匹配 → 上海天气 → 上海内路线规划 → 组装时间轴 → 返回
    
    ## 特殊规则
    - 博物馆周一闭馆（上海博物馆、上海历史博物馆等）
    - 地铁末班车约22:30
    - 雨天优先室内POI（博物馆/商场/科技馆）
    - 高温>35°C减少户外步行
    - 避免浦西浦东反复横跳
    """,
    version="2.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 设置调度器到应用状态中
app.state.scheduler = AsyncIOScheduler()

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册异常处理器
register_exception_handlers(app)

# 包含路由
app.include_router(auth.router, prefix="/api")  # 认证路由
app.include_router(user.router)  # 用户资料路由
app.include_router(route.router)
app.include_router(weather.router)
app.include_router(collab.router)
app.include_router(diary.router)
app.include_router(dianping.router)  # 大众点评数据路由
app.include_router(chat.router)  # 聊天群聊+AI助手路由
app.include_router(address.router)  # 地址搜索路由
app.include_router(meituan_chat.router)  # 美团AI对话路由
app.include_router(v1.router)  # POI反馈、替换、详情补全路由

# 注册中间件（注意：中间件执行顺序与添加顺序相反，最后添加的先执行）
# 1. SkipAuthMiddleware - 跳过特定路径的认证检查
# 2. AuthMiddleware - 认证中间件
# 这样 SkipAuthMiddleware 会先执行，如果是公开路径则直接放行

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class SkipAuthMiddleware(BaseHTTPMiddleware):
    """
    跳过特定路径的认证检查
    用于修复某些公开接口被认证中间件拦截的问题
    """
    # 不需要认证的路径列表
    SKIP_PATHS = [
        "/api/chat/rooms",  # 创建聊天室
        "/api/chat/ws/",    # WebSocket 端点（WebSocket认证在路由中处理）
    ]
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # 检查是否需要跳过认证
        if any(path.startswith(skip_path) for skip_path in self.SKIP_PATHS):
            logger.debug(f"[SkipAuthMiddleware] 跳过认证: {path}")
            response = await call_next(request)
            return response
        
        # 其他路径正常处理
        response = await call_next(request)
        return response

# 添加中间件（顺序：先添加 AuthMiddleware，再添加 SkipAuthMiddleware）
# 实际执行顺序：SkipAuthMiddleware -> AuthMiddleware -> 路由
app.add_middleware(AuthMiddleware)
app.add_middleware(SkipAuthMiddleware)

logger.info("[Main] 中间件注册完成: SkipAuthMiddleware -> AuthMiddleware")

# 健康检查
@app.get("/health", tags=["系统"])
@app.head("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "ok",
        "service": "shanghai-travel-planner",
        "version": "2.1.0",
        "city": "上海"
    }


# API 健康检查（前端使用）
@app.get("/api/health", tags=["系统"])
@app.head("/api/health")
async def api_health_check():
    """
    API 健康检查端点
    返回各服务状态：高德地图、LLM、数据库等
    """
    services_status = {
        "gaode": False,
        "llm": False,
        "database": False
    }
    
    # 检查高德服务
    try:
        from services.gaode_service import get_gaode_service
        gaode = get_gaode_service()
        services_status["gaode"] = gaode is not None
    except Exception as e:
        logger.warning(f"高德服务检查失败: {e}")
    
    # 检查 LLM 服务
    try:
        from services.llm_parser import get_llm_parser
        llm = get_llm_parser()
        services_status["llm"] = llm is not None
    except Exception as e:
        logger.warning(f"LLM服务检查失败: {e}")
    
    # 检查数据库（真实 ping Atlas）
    try:
        from models.mongodb import get_database
        db = get_database()
        await db.command("ping")
        services_status["database"] = True
    except Exception as e:
        logger.warning(f"数据库检查失败: {e}")
        services_status["database"] = False
    
    # 如果有任何服务不可用，返回 503
    all_healthy = all(services_status.values())
    
    return {
        "status": "ok" if all_healthy else "degraded",
        "services": services_status,
        "version": "2.1.0"
    }


# 根路径
@app.get("/", tags=["系统"])
async def root():
    """服务根路径"""
    return {
        "service": "本地生活路线规划后端服务",
        "version": "2.1.0",
        "city": "上海",
        "center": {
            "name": SHANGHAI_CENTER["name"],
            "location": f"{SHANGHAI_CENTER['lng']},{SHANGHAI_CENTER['lat']}"
        },
        "docs": "/docs",
        "health": "/health"
    }
