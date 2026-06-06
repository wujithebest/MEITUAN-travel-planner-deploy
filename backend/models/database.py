"""
数据库模型和 SQLite 支持
使用 SQLAlchemy + aiosqlite 异步操作
"""

import os
import json
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select, update, delete

from config import get_settings

settings = get_settings()

# 确保数据目录存在
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 数据库路径
DATABASE_URL = f"sqlite+aiosqlite:///{os.path.join(DATA_DIR, 'users.db')}"

# 创建异步引擎
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

# 创建会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# 声明基类
Base = declarative_base()


class UserDB(Base):
    """用户数据库模型"""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    avatar = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    preferences = Column(Text, default="[]")  # JSON 字符串存储偏好列表
    home_address = Column(Text, nullable=True)  # JSON 字符串存储常住地址 {"name": "家", "location": "lng,lat"}
    
    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "password_hash": self.password_hash,
            "avatar": self.avatar,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "preferences": json.loads(self.preferences) if self.preferences else [],
            "home_address": json.loads(self.home_address) if self.home_address else None
        }


async def init_db():
    """初始化数据库，创建所有表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"[OK] Database initialized: {DATABASE_URL}")


async def get_db() -> AsyncSession:
    """获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


class UserRepository:
    """用户数据访问层"""
    
    @staticmethod
    async def create_user(user_id: str, username: str, email: str, 
                          password_hash: str, preferences: list = None,
                          avatar: str = None, home_address: dict = None) -> dict:
        """创建新用户"""
        async with AsyncSessionLocal() as session:
            # 检查邮箱是否已存在
            result = await session.execute(
                select(UserDB).where(UserDB.email == email)
            )
            if result.scalar_one_or_none():
                raise ValueError("邮箱已被注册")
            
            # 检查用户名是否已存在
            result = await session.execute(
                select(UserDB).where(UserDB.username == username)
            )
            if result.scalar_one_or_none():
                raise ValueError("用户名已被使用")
            
            # 创建用户
            user = UserDB(
                id=user_id,
                username=username,
                email=email,
                password_hash=password_hash,
                avatar=avatar,
                preferences=json.dumps(preferences or []),
                home_address=json.dumps(home_address) if home_address else None
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user.to_dict()
    
    @staticmethod
    async def get_by_email(email: str) -> dict | None:
        """通过邮箱获取用户"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB).where(UserDB.email == email)
            )
            user = result.scalar_one_or_none()
            return user.to_dict() if user else None
    
    @staticmethod
    async def get_by_id(user_id: str) -> dict | None:
        """通过ID获取用户"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB).where(UserDB.id == user_id)
            )
            user = result.scalar_one_or_none()
            return user.to_dict() if user else None
    
    @staticmethod
    async def update_preferences(user_id: str, preferences: list) -> dict | None:
        """更新用户偏好"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB).where(UserDB.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.preferences = json.dumps(preferences)
                await session.commit()
                await session.refresh(user)
                return user.to_dict()
            return None
    
    @staticmethod
    async def update_avatar(user_id: str, avatar: str) -> dict | None:
        """更新用户头像"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB).where(UserDB.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.avatar = avatar
                await session.commit()
                await session.refresh(user)
                return user.to_dict()
            return None
    
    @staticmethod
    async def update_home_address(user_id: str, home_address: dict) -> dict | None:
        """更新用户常住地址
        
        Args:
            user_id: 用户ID
            home_address: 地址字典，格式 {"name": "家", "location": "lng,lat"}
        
        Returns:
            更新后的用户字典，或None（用户不存在时）
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB).where(UserDB.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.home_address = json.dumps(home_address)
                await session.commit()
                await session.refresh(user)
                return user.to_dict()
            return None
