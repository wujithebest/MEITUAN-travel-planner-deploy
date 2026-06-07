"""
MongoDB 数据库连接和配置
使用 Motor 异步驱动操作 MongoDB
"""

import os
import re
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from config import get_settings

settings = get_settings()

# MongoDB 连接配置
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "travel_planner")

# 超时配置（避免注册/登录卡 30 秒以上）
MONGODB_SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000"))
MONGODB_CONNECT_TIMEOUT_MS = int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "5000"))
MONGODB_SOCKET_TIMEOUT_MS = int(os.getenv("MONGODB_SOCKET_TIMEOUT_MS", "10000"))


def sanitize_mongo_url(url: str) -> str:
    """脱敏 MongoDB URL，只保留 scheme + host，隐藏用户名密码"""
    try:
        return re.sub(r"://[^@]+@", r"://<credentials>@", url)
    except Exception:
        return "<invalid-url>"


# 创建 MongoDB 客户端（带显式超时）
client = AsyncIOMotorClient(
    MONGODB_URL,
    serverSelectionTimeoutMS=MONGODB_SERVER_SELECTION_TIMEOUT_MS,
    connectTimeoutMS=MONGODB_CONNECT_TIMEOUT_MS,
    socketTimeoutMS=MONGODB_SOCKET_TIMEOUT_MS,
    uuidRepresentation="standard",
)
db = client[DATABASE_NAME]

# 集合引用
users_collection = db.users


class PyObjectId(ObjectId):
    """自定义 ObjectId 类型，用于 Pydantic 模型"""
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("无效的 ObjectId")
        return ObjectId(v)
    
    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")


def get_database():
    """获取 MongoDB 数据库实例"""
    return db


async def init_mongodb():
    """初始化 MongoDB 数据库，创建索引"""
    try:
        # 先验证连接
        await client.admin.command('ping')
        # 再创建索引
        await users_collection.create_index("email", unique=True)
        await users_collection.create_index("username", unique=True)
        print(f"[OK] MongoDB connected: {sanitize_mongo_url(MONGODB_URL)}")
        print(f"[OK] Database initialized: {DATABASE_NAME}")
    except Exception as e:
        print(f"[ERROR] MongoDB connection failed: {e}")
        print(f"  target: {sanitize_mongo_url(MONGODB_URL)}")
        print(f"  database: {DATABASE_NAME}")
        raise


async def close_mongodb():
    """关闭 MongoDB 连接"""
    client.close()
    print("[OK] MongoDB connection closed")


class UserMongoDB:
    """用户 MongoDB 数据模型"""
    
    @staticmethod
    async def create_user(user_id: str, username: str, email: str,
                          password_hash: str, preferences: dict = None,
                          avatar: str = None, location: dict = None,
                          bio: str = None, phone: str = None,
                          gender: str = None, birthday: str = None) -> dict:
        """创建新用户"""
        # 检查邮箱是否已存在
        existing_user = await users_collection.find_one({"email": email})
        if existing_user:
            raise ValueError("邮箱已被注册")
        
        # 检查用户名是否已存在
        existing_user = await users_collection.find_one({"username": username})
        if existing_user:
            raise ValueError("用户名已被使用")
        
        # 确保 preferences 是字典
        if preferences is None:
            preferences = {}
        elif isinstance(preferences, list):
            # 兼容旧格式：列表转换为字典
            preferences = {"interests": preferences}
        elif not isinstance(preferences, dict):
            preferences = {}

        # 创建用户文档
        user_doc = {
            "_id": user_id,
            "username": username,
            "email": email,
            "password_hash": password_hash,
            "avatar": avatar,
            "bio": bio,
            "phone": phone,
            "gender": gender,
            "birthday": birthday,
            "location": location or {},
            "preferences": preferences,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = await users_collection.insert_one(user_doc)
        
        # 返回创建的用户（不包含密码）
        user_doc.pop("password_hash")
        user_doc["id"] = str(user_doc.pop("_id"))
        user_doc["created_at"] = user_doc["created_at"].isoformat()
        user_doc["updated_at"] = user_doc["updated_at"].isoformat()
        
        return user_doc
    
    @staticmethod
    async def get_by_email(email: str) -> dict | None:
        """通过邮箱获取用户"""
        user = await users_collection.find_one({"email": email})
        if user:
            user["id"] = str(user.pop("_id"))
            user["created_at"] = user["created_at"].isoformat() if user.get("created_at") else None
            user["updated_at"] = user["updated_at"].isoformat() if user.get("updated_at") else None
        return user
    
    @staticmethod
    async def get_by_id(user_id: str) -> dict | None:
        """通过ID获取用户"""
        try:
            user = await users_collection.find_one({"_id": user_id})
            if user:
                user["id"] = str(user.pop("_id"))
                user["created_at"] = user["created_at"].isoformat() if user.get("created_at") else None
                user["updated_at"] = user["updated_at"].isoformat() if user.get("updated_at") else None
            return user
        except Exception:
            return None
    
    @staticmethod
    async def get_by_email_with_password(email: str) -> dict | None:
        """通过邮箱获取用户（包含密码，用于认证）"""
        user = await users_collection.find_one({"email": email})
        if user:
            user["id"] = str(user.pop("_id"))
            user["created_at"] = user["created_at"].isoformat() if user.get("created_at") else None
            user["updated_at"] = user["updated_at"].isoformat() if user.get("updated_at") else None
        return user
    
    @staticmethod
    async def update_user_profile(user_id: str, update_data: dict) -> dict | None:
        """更新用户资料（通用方法）"""
        # 不允许直接更新这些字段
        forbidden_fields = {"_id", "id", "email", "password_hash", "created_at"}
        update_data = {k: v for k, v in update_data.items() if k not in forbidden_fields}
        
        # 确保 preferences 是字典
        if "preferences" in update_data:
            prefs = update_data["preferences"]
            if prefs is None:
                update_data["preferences"] = {}
            elif isinstance(prefs, list):
                # 兼容旧格式：列表转换为字典
                update_data["preferences"] = {"interests": prefs}
            elif not isinstance(prefs, dict):
                update_data["preferences"] = {}
        
        if not update_data:
            return await UserMongoDB.get_by_id(user_id)
        
        update_data["updated_at"] = datetime.utcnow()
        
        result = await users_collection.find_one_and_update(
            {"_id": user_id},
            {"$set": update_data},
            return_document=True
        )
        if result:
            result["id"] = str(result.pop("_id"))
            result["created_at"] = result["created_at"].isoformat() if result.get("created_at") else None
            result["updated_at"] = result["updated_at"].isoformat() if result.get("updated_at") else None
        return result
    
    @staticmethod
    async def update_preferences(user_id: str, preferences: dict) -> dict | None:
        """更新用户偏好"""
        return await UserMongoDB.update_user_profile(user_id, {"preferences": preferences})
    
    @staticmethod
    async def update_avatar(user_id: str, avatar: str) -> dict | None:
        """更新用户头像"""
        return await UserMongoDB.update_user_profile(user_id, {"avatar": avatar})
    
    @staticmethod
    async def update_location(user_id: str, location: dict) -> dict | None:
        """更新用户位置"""
        return await UserMongoDB.update_user_profile(user_id, {"location": location})
    
    @staticmethod
    async def check_username_exists(username: str, exclude_user_id: str = None) -> bool:
        """检查用户名是否已存在（可排除特定用户）"""
        query = {"username": username}
        if exclude_user_id:
            query["_id"] = {"$ne": exclude_user_id}
        count = await users_collection.count_documents(query)
        return count > 0
    
    @staticmethod
    async def update_password(user_id: str, new_password_hash: str) -> bool:
        """更新用户密码"""
        result = await users_collection.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "password_hash": new_password_hash,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        return result.modified_count > 0
    
    @staticmethod
    async def delete_user(user_id: str) -> bool:
        """删除用户"""
        result = await users_collection.delete_one({"_id": user_id})
        return result.deleted_count > 0
    
    @staticmethod
    async def user_exists(email: str = None, username: str = None) -> bool:
        """检查用户是否存在"""
        if email:
            count = await users_collection.count_documents({"email": email})
            if count > 0:
                return True
        if username:
            count = await users_collection.count_documents({"username": username})
            if count > 0:
                return True
        return False

    # ═══════════════════════════════════════════════════════════════
    # 路线收藏
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def get_favorite_routes(user_id: str) -> list[dict]:
        """获取用户收藏的路线列表（按 updated_at 倒序）"""
        user = await users_collection.find_one({"_id": user_id})
        if not user:
            return []
        favorites = user.get("favorite_routes", []) or []
        favorites.sort(key=lambda f: f.get("updated_at", f.get("created_at", "")), reverse=True)
        return favorites

    @staticmethod
    async def add_favorite_route(user_id: str, favorite: dict) -> dict:
        """添加或更新路线收藏。route_hash 已存在时更新 updated_at，不重复插入。"""
        import uuid
        now = datetime.utcnow().isoformat()
        route_hash = favorite.get("route_hash", "")
        route_id = favorite.get("route_id", "")

        user = await users_collection.find_one({"_id": user_id})
        favorites = (user.get("favorite_routes") or []) if user else []

        # 去重：按 route_hash 或 route_id 查找已存在项
        existing_idx = None
        for i, f in enumerate(favorites):
            if route_hash and f.get("route_hash") == route_hash:
                existing_idx = i
                break
            if route_id and f.get("route_id") == route_id:
                existing_idx = i
                break

        if existing_idx is not None:
            # 更新已有收藏的 updated_at 和内容
            favorites[existing_idx].update(favorite)
            favorites[existing_idx]["updated_at"] = now
        else:
            # 新增收藏
            favorite["favorite_id"] = str(uuid.uuid4())
            favorite["created_at"] = now
            favorite["updated_at"] = now
            favorites.append(favorite)

        await users_collection.update_one(
            {"_id": user_id},
            {"$set": {"favorite_routes": favorites}}
        )
        return favorites[existing_idx]

    @staticmethod
    async def delete_favorite_route(user_id: str, favorite_id: str) -> bool:
        """删除指定收藏路线"""
        user = await users_collection.find_one({"_id": user_id})
        if not user:
            return False
        favorites = user.get("favorite_routes", []) or []
        new_favorites = [f for f in favorites if f.get("favorite_id") != favorite_id]
        if len(new_favorites) == len(favorites):
            return False  # 未找到
        await users_collection.update_one(
            {"_id": user_id},
            {"$set": {"favorite_routes": new_favorites}}
        )
        return True

    # ==================== 规划历史 ====================

    @staticmethod
    async def get_route_histories(user_id: str) -> list[dict]:
        """获取用户规划历史列表（按 created_at 倒序）"""
        user = await users_collection.find_one({"_id": user_id})
        if not user:
            return []
        histories = user.get("route_histories", []) or []
        histories.sort(key=lambda h: h.get("created_at", ""), reverse=True)
        return histories

    @staticmethod
    async def add_route_history(user_id: str, history: dict) -> dict:
        """添加一条规划历史记录。不按 route_hash 去重，每次成功规划都保存。"""
        import uuid
        from datetime import datetime
        history_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        history["history_id"] = history_id
        history["created_at"] = now
        history["updated_at"] = now

        user = await users_collection.find_one({"_id": user_id})
        histories = (user.get("route_histories") or []) if user else []
        histories.append(history)

        await users_collection.update_one(
            {"_id": user_id},
            {"$set": {"route_histories": histories}}
        )
        return history

    @staticmethod
    async def delete_route_history(user_id: str, history_id: str) -> bool:
        """删除指定规划历史"""
        user = await users_collection.find_one({"_id": user_id})
        if not user:
            return False
        histories = user.get("route_histories", []) or []
        new_histories = [h for h in histories if h.get("history_id") != history_id]
        if len(new_histories) == len(histories):
            return False
        await users_collection.update_one(
            {"_id": user_id},
            {"$set": {"route_histories": new_histories}}
        )
        return True

    @staticmethod
    async def clear_route_histories(user_id: str) -> bool:
        """清空所有规划历史"""
        user = await users_collection.find_one({"_id": user_id})
        if not user:
            return False
        await users_collection.update_one(
            {"_id": user_id},
            {"$set": {"route_histories": []}}
        )
        return True
