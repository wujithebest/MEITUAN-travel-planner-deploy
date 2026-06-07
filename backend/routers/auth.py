"""
用户认证路由 - 使用 MongoDB 存储用户信息
"""
from datetime import datetime, timedelta
from typing import Optional, Union
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, validator, Field
from jose import JWTError, jwt
from passlib.context import CryptContext
import uuid
import logging

from models.mongodb import UserMongoDB
from config import get_settings
from pymongo.errors import ServerSelectionTimeoutError, PyMongoError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["认证"])

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT 配置 - 统一从配置文件读取
settings = get_settings()
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

logger.info("[Auth] SECRET_KEY loaded")

# OAuth2 方案
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ============== 数据模型 ==============
class UserBase(BaseModel):
    username: str
    email: str


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str = Field(..., min_length=6)
    gender: Optional[str] = None
    birthday: Optional[str] = None
    preferences: Optional[Union[dict, list]] = {}
    location: Optional[dict] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    home_location: Optional[dict] = None

    @validator('username')
    def username_valid(cls, v):
        if len(v) < 2:
            raise ValueError('用户名至少2个字符')
        if len(v) > 20:
            raise ValueError('用户名最多20个字符')
        import re
        if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9_]+$', v):
            raise ValueError('用户名只能包含字母、数字、中文和下划线')
        return v

    @validator('birthday')
    def birthday_valid(cls, v):
        if v is not None and v != '':
            import re
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', v):
                raise ValueError('生日格式不正确，应为 YYYY-MM-DD')
        return v


class UserInDB(UserBase):
    id: str
    password_hash: str
    preferences: dict = {}
    avatar: Optional[str] = None
    created_at: Optional[str] = None


class UserResponse(UserBase):
    id: str
    avatar: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    birthday: Optional[str] = None
    location: Optional[dict] = None
    preferences: dict = {}


class Token(BaseModel):
    token: str
    user: UserResponse


class TokenData(BaseModel):
    user_id: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class PreferencesUpdate(BaseModel):
    preferences: dict


# ============== 辅助函数 ==============

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return pwd_context.hash(password)


async def get_user_by_email(email: str) -> Optional[dict]:
    """通过邮箱获取用户"""
    return await UserMongoDB.get_by_email(email)


async def get_user_by_id(user_id: str) -> Optional[dict]:
    """通过ID获取用户"""
    return await UserMongoDB.get_by_id(user_id)


async def authenticate_user(email: str, password: str) -> Optional[dict]:
    """认证用户"""
    try:
        user = await UserMongoDB.get_by_email_with_password(email)
        if not user:
            return None
        if not verify_password(password, user.get("password_hash", "")):
            return None
        return user
    except ServerSelectionTimeoutError:
        logger.exception("[Auth] MongoDB connection timeout during auth")
        raise HTTPException(status_code=503, detail="数据库连接超时，请检查 Atlas Network Access 与 MONGODB_URL")
    except PyMongoError:
        logger.exception("[Auth] MongoDB error during auth")
        raise HTTPException(status_code=503, detail="数据库暂时不可用，请稍后重试")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    
    logger.info(f"[Auth] 生成token, user={data.get('sub')}")
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    logger.info("[Auth] 验证token")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_data = TokenData(user_id=user_id)
    except JWTError as e:
        logger.error(f"[Auth] Token验证失败: {str(e)}")
        raise credentials_exception
    
    user = await get_user_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception
    
    logger.info(f"[Auth] Token验证成功, user_id={user_id}")
    return user


# ============== API 路由 ==============

@router.post("/auth/register", response_model=Token)
async def register(user_data: UserCreate):
    """
    用户注册 - 使用 MongoDB 存储
    """
    try:
        # 检查邮箱是否已注册
        existing = await UserMongoDB.user_exists(email=user_data.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该邮箱已被注册"
            )

        # 检查用户名是否已存在
        existing = await UserMongoDB.user_exists(username=user_data.username)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该用户名已被使用"
            )

        # 创建新用户
        user_id = str(uuid.uuid4())
        hashed_password = get_password_hash(user_data.password)

        new_user = await UserMongoDB.create_user(
            user_id=user_id,
            username=user_data.username,
            email=user_data.email,
            password_hash=hashed_password,
            gender=user_data.gender,
            birthday=user_data.birthday,
            preferences=user_data.preferences or {},
            location=user_data.location,
            bio=user_data.bio,
            phone=user_data.phone,
            avatar=None,
            home_location=user_data.home_location,
        )

        # 创建访问令牌
        access_token = create_access_token(data={"sub": user_id})

        return {
            "token": access_token,
            "user": {
                "id": new_user["id"],
                "username": new_user["username"],
                "email": new_user["email"],
                "avatar": new_user.get("avatar"),
                "bio": new_user.get("bio"),
                "phone": new_user.get("phone"),
                "gender": new_user.get("gender"),
                "birthday": new_user.get("birthday"),
                "location": new_user.get("location"),
                "preferences": new_user.get("preferences", {}),
                "home_location": new_user.get("home_location"),
            }
        }
    except ServerSelectionTimeoutError:
        logger.exception("[Auth] MongoDB connection timeout during register")
        raise HTTPException(status_code=503, detail="数据库连接超时，请检查 Atlas Network Access 与 MONGODB_URL")
    except PyMongoError as e:
        logger.exception("[Auth] MongoDB error during register")
        raise HTTPException(status_code=503, detail="数据库暂时不可用，请稍后重试")


@router.post("/auth/login", response_model=Token)
async def login(login_data: LoginRequest):
    """
    用户登录
    """
    # 认证用户
    user = await authenticate_user(login_data.email, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 创建访问令牌
    access_token = create_access_token(data={"sub": user["id"]})

    return {
        "token": access_token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "avatar": user.get("avatar"),
            "bio": user.get("bio"),
            "phone": user.get("phone"),
            "gender": user.get("gender"),
            "birthday": user.get("birthday"),
            "location": user.get("location"),
            "preferences": user.get("preferences", {}),
            "home_location": user.get("home_location"),
        }
    }


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    获取当前用户信息
    """
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "email": current_user["email"],
        "avatar": current_user.get("avatar"),
        "bio": current_user.get("bio"),
        "phone": current_user.get("phone"),
        "gender": current_user.get("gender"),
        "birthday": current_user.get("birthday"),
        "location": current_user.get("location"),
        "preferences": current_user.get("preferences", {}),
        "home_location": current_user.get("home_location"),
    }


@router.put("/auth/preferences")
async def update_preferences(
    prefs_data: PreferencesUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    更新用户偏好（已弃用，请使用 PUT /api/user/profile）
    """
    updated_user = await UserMongoDB.update_preferences(
        current_user["id"], 
        prefs_data.preferences if isinstance(prefs_data.preferences, dict) else {}
    )
    
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    return {
        "message": "偏好更新成功",
        "preferences": updated_user.get("preferences", {})
    }


@router.post("/auth/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """
    用户登出（前端删除token即可，这里只是接口占位）
    """
    return {"message": "登出成功"}


@router.post("/auth/forgot-password")
async def forgot_password(email: str):
    """
    忘记密码（占位接口，实际应发送重置邮件）
    """
    user = await get_user_by_email(email)
    if not user:
        # 为了安全，不透露邮箱是否存在
        return {"message": "如果该邮箱已注册，重置链接将发送到您的邮箱"}
    
    # TODO: 发送重置密码邮件
    return {"message": "重置密码链接已发送到您的邮箱"}
