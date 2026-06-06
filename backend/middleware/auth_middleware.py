"""
认证中间件 - 统一 HTTP 和 WebSocket 的 Token 验证

修复内容：
1. 统一 HTTP 和 WebSocket 的 token 验证逻辑
2. 统一从 config.py 读取 SECRET_KEY
3. 支持从 query parameter 或 header 获取 token
4. 详细的日志输出，便于调试
5. 开发模式下提供默认用户（可选）
"""
from fastapi import Request, WebSocket, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from jose import jwt, JWTError
import logging
import os

from config import get_settings

logger = logging.getLogger(__name__)

# JWT 配置 - 统一从配置文件读取
settings = get_settings()
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

logger.info("[AuthMiddleware] SECRET_KEY loaded")


def decode_token(token: str) -> dict | None:
    """
    解码并验证 JWT token
    
    Args:
        token: JWT token 字符串
        
    Returns:
        解码后的 payload，验证失败返回 None
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.info(f"[AuthMiddleware] Token解码成功, user_id={payload.get('sub')}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("[AuthMiddleware] Token 已过期")
        return None
    except JWTError as e:
        logger.warning(f"[AuthMiddleware] Token 验证失败: {e}")
        return None


def extract_token_from_header(auth_header: str) -> str | None:
    """
    从 Authorization header 中提取 token
    
    Args:
        auth_header: Authorization header 值
        
    Returns:
        token 字符串，格式不正确返回 None
    """
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "")
    return None


async def get_current_user(request: Request) -> dict:
    """
    获取当前用户（HTTP）
    
    Args:
        request: FastAPI 请求对象
        
    Returns:
        用户信息字典
        
    Raises:
        HTTPException: 如果认证失败
    """
    # 从 header 获取 token
    auth_header = request.headers.get("Authorization", "")
    token = extract_token_from_header(auth_header)
    
    # 如果没有，尝试从 query parameter 获取（用于某些特殊情况）
    if not token:
        token = request.query_params.get("token")
    
    if not token:
        logger.warning(f"[AuthMiddleware] 未提供认证信息: {request.url.path}")
        raise HTTPException(status_code=401, detail="未提供认证信息")
    
    logger.info(f"[AuthMiddleware] 收到请求: {request.url.path}, Authorization={auth_header[:50]}...")
    
    # 验证 token
    payload = decode_token(token)
    if not payload:
        logger.warning(f"[AuthMiddleware] 无效的认证信息: {request.url.path}")
        raise HTTPException(status_code=401, detail="无效的认证信息")
    
    user_id = payload.get("sub")
    username = payload.get("username")
    email = payload.get("email")
    avatar = payload.get("avatar")
    
    if not user_id:
        logger.warning(f"[AuthMiddleware] Token 中缺少用户ID: {request.url.path}")
        raise HTTPException(status_code=401, detail="无效的认证信息")
    
    user = {
        "id": user_id,
        "username": username or email or "用户",
        "email": email,
        "avatar": avatar or "/default-avatar.png"
    }
    
    logger.info(f"[AuthMiddleware] 用户认证成功: {user['username']}({user['id']}) - {request.url.path}")
    return user


async def get_current_user_ws(websocket: WebSocket) -> dict | None:
    """
    获取当前用户（WebSocket）
    
    WebSocket认证方式：
    1. 从 query parameter 获取 token: ws://host/api/chat/ws/room/xxx?token=xxx
    2. 从 header 获取 token: Authorization: Bearer xxx
    3. 从 cookie 获取 token（如果支持）
    
    Args:
        websocket: WebSocket 连接对象
        
    Returns:
        用户信息字典，认证失败返回 None
    """
    token = None
    
    # 1. 尝试从 query parameter 获取 token
    token = websocket.query_params.get("token")
    if token:
        logger.debug("[AuthMiddleware] 从 query parameter 获取到 token")
    
    # 2. 如果没有，尝试从 header 获取
    if not token:
        authorization = websocket.headers.get("authorization")
        token = extract_token_from_header(authorization)
        if token:
            logger.debug("[AuthMiddleware] 从 header 获取到 token")
    
    # 3. 如果还没有，尝试从 cookie 获取
    if not token:
        cookies = websocket.headers.get("cookie", "")
        for cookie in cookies.split(";"):
            cookie = cookie.strip()
            if cookie.startswith("token="):
                token = cookie.split("=", 1)[1]
                logger.debug("[AuthMiddleware] 从 cookie 获取到 token")
                break
    
    # 开发模式：如果没有 token，返回默认用户
    if not token:
        env = os.getenv("ENV", "development")
        if env == "development":
            logger.warning("[AuthMiddleware] 开发模式：使用默认用户（无 token）")
            return {"id": "dev_user", "username": "开发者", "avatar": "/default-avatar.png"}
        else:
            logger.warning("[AuthMiddleware] WebSocket 认证失败：缺少 token")
            return None
    
    # 验证 token
    payload = decode_token(token)
    if not payload:
        env = os.getenv("ENV", "development")
        if env == "development":
            logger.warning("[AuthMiddleware] 开发模式：Token 无效，使用默认用户")
            return {"id": "dev_user", "username": "开发者", "avatar": "/default-avatar.png"}
        else:
            logger.warning("[AuthMiddleware] WebSocket 认证失败：Token 无效")
            return None
    
    user_id = payload.get("sub")
    username = payload.get("username")
    email = payload.get("email")
    avatar = payload.get("avatar")
    
    if not user_id:
        env = os.getenv("ENV", "development")
        if env == "development":
            logger.warning("[AuthMiddleware] 开发模式：Token 缺少用户ID，使用默认用户")
            return {"id": "dev_user", "username": "开发者", "avatar": "/default-avatar.png"}
        else:
            logger.warning("[AuthMiddleware] WebSocket 认证失败：Token 缺少用户ID")
            return None
    
    user = {
        "id": user_id,
        "username": username or email or "用户",
        "email": email,
        "avatar": avatar or "/default-avatar.png"
    }
    
    logger.info(f"[AuthMiddleware] WebSocket 用户认证成功: {user['username']}({user['id']})")
    return user


def get_user_from_request(request: Request) -> dict | None:
    """
    从请求中提取用户信息（不抛出异常）
    
    Args:
        request: FastAPI 请求对象
        
    Returns:
        用户信息字典，如果没有有效 token 则返回 None
    """
    try:
        # 从 Authorization header 获取 token
        auth_header = request.headers.get("Authorization", "")
        token = extract_token_from_header(auth_header)
        
        if not token:
            return None
        
        # 解析 token
        payload = decode_token(token)
        if not payload:
            return None
        
        user_id = payload.get("sub")
        email = payload.get("email")
        username = payload.get("username")
        avatar = payload.get("avatar")
        
        if not user_id:
            return None
        
        return {
            "id": user_id,
            "email": email,
            "username": username or email or "用户",
            "avatar": avatar or "/default-avatar.png"
        }
    except Exception as e:
        logger.debug(f"[AuthMiddleware] Token validation failed: {e}")
        return None


# 不需要认证的路径
PUBLIC_PATHS = [
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/forgot-password",
    "/api/weather",
    "/api/route",
    "/api/chat/ws/",  # WebSocket端点单独处理认证
    "/api/meituan/chat/stream",  # SSE流式端点（公开访问）
    "/api/meituan/health",  # 健康检查
]


class AuthMiddleware(BaseHTTPMiddleware):
    """
    认证中间件
    对非公开路径进行可选的 token 验证
    """
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # 公开路径直接放行
        if any(path.startswith(public_path) for public_path in PUBLIC_PATHS):
            response = await call_next(request)
            return response
        
        # 对于需要认证的路径，让路由自己处理认证
        # 这里只是记录日志
        response = await call_next(request)
        return response
