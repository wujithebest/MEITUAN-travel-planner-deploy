"""
用户服务 - 处理用户资料业务逻辑
"""
import logging
from typing import Optional
from datetime import datetime

from models.mongodb import UserMongoDB
from models.user import UserProfile, UserProfileUpdate, UserLocation, UserPreferences, HomeAddress

logger = logging.getLogger(__name__)


class UserService:
    """用户服务类 - 处理用户资料相关逻辑"""
    
    @staticmethod
    async def get_user_profile(user_id: str) -> Optional[UserProfile]:
        """
        获取用户完整资料
        
        Args:
            user_id: 用户ID
            
        Returns:
            UserProfile 对象，如果用户不存在返回 None
        """
        try:
            user_data = await UserMongoDB.get_by_id(user_id)
            if not user_data:
                logger.warning(f"[UserService] 用户不存在: {user_id}")
                return None
            
            # 构建 UserProfile 对象
            return UserService._build_user_profile(user_data)
        except Exception as e:
            logger.error(f"[UserService] 获取用户资料失败: {e}")
            raise
    
    @staticmethod
    async def update_user_profile(
        user_id: str, 
        update_data: UserProfileUpdate
    ) -> Optional[UserProfile]:
        """
        更新用户资料（带验证）
        
        Args:
            user_id: 用户ID
            update_data: 更新的数据
            
        Returns:
            更新后的 UserProfile 对象
            
        Raises:
            ValueError: 用户名已被使用或其他验证错误
        """
        try:
            # 检查用户是否存在
            existing_user = await UserMongoDB.get_by_id(user_id)
            if not existing_user:
                logger.warning(f"[UserService] 用户不存在: {user_id}")
                return None
            
            # 准备更新数据
            update_dict = {}
            
            # 检查用户名唯一性
            if update_data.username is not None:
                username_exists = await UserMongoDB.check_username_exists(
                    update_data.username, 
                    exclude_user_id=user_id
                )
                if username_exists:
                    raise ValueError(f"用户名 '{update_data.username}' 已被使用")
                update_dict["username"] = update_data.username
            
            # 处理其他字段
            if update_data.bio is not None:
                update_dict["bio"] = update_data.bio
            
            if update_data.avatar is not None:
                update_dict["avatar"] = update_data.avatar
            
            if update_data.phone is not None:
                update_dict["phone"] = update_data.phone

            if update_data.gender is not None:
                update_dict["gender"] = update_data.gender

            if update_data.birthday is not None:
                update_dict["birthday"] = update_data.birthday
            
            # 处理位置信息
            if update_data.location is not None:
                location_dict = update_data.location.model_dump(exclude_none=True)
                if location_dict:
                    update_dict["location"] = location_dict
                else:
                    update_dict["location"] = {}
            
            # 处理偏好设置
            if update_data.preferences is not None:
                preferences_dict = update_data.preferences.model_dump(exclude_none=True)
                if preferences_dict:
                    update_dict["preferences"] = preferences_dict
                else:
                    update_dict["preferences"] = {}
            
            # 执行更新
            if not update_dict:
                logger.info(f"[UserService] 没有需要更新的字段")
                return UserService._build_user_profile(existing_user)
            
            updated_user = await UserMongoDB.update_user_profile(user_id, update_dict)
            if not updated_user:
                logger.error(f"[UserService] 更新用户资料失败")
                return None
            
            logger.info(f"[UserService] 用户资料更新成功: {user_id}")
            return UserService._build_user_profile(updated_user)
            
        except ValueError as e:
            raise e
        except Exception as e:
            logger.error(f"[UserService] 更新用户资料失败: {e}")
            raise
    
    @staticmethod
    async def check_username_availability(
        username: str, 
        exclude_user_id: str = None
    ) -> dict:
        """
        检查用户名是否可用
        
        Args:
            username: 要检查的用户名
            exclude_user_id: 排除的用户ID（用于更新时检查）
            
        Returns:
            dict: {"available": bool, "message": str}
        """
        # 验证用户名格式
        import re
        if len(username) < 2:
            return {"available": False, "message": "用户名至少2个字符"}
        if len(username) > 20:
            return {"available": False, "message": "用户名最多20个字符"}
        if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9_]+$', username):
            return {"available": False, "message": "用户名只能包含字母、数字、中文和下划线"}
        
        # 检查是否已存在
        exists = await UserMongoDB.check_username_exists(username, exclude_user_id)
        if exists:
            return {"available": False, "message": f"用户名 '{username}' 已被使用"}
        
        return {"available": True, "message": "用户名可用"}
    
    @staticmethod
    def _build_user_profile(user_data: dict) -> UserProfile:
        """
        从数据库数据构建 UserProfile 对象
        
        Args:
            user_data: 数据库中的用户数据
            
        Returns:
            UserProfile 对象
        """
        # 构建位置信息
        location = None
        if user_data.get("location"):
            loc_data = user_data["location"]
            if loc_data:
                # 构建常住地址
                home_address = None
                if loc_data.get("home_address"):
                    ha_data = loc_data["home_address"]
                    home_address = HomeAddress(
                        name=ha_data.get("name"),
                        full_address=ha_data.get("full_address"),
                        lng=ha_data.get("lng"),
                        lat=ha_data.get("lat")
                    )
                
                location = UserLocation(
                    province=loc_data.get("province"),
                    city=loc_data.get("city"),
                    district=loc_data.get("district"),
                    address=loc_data.get("address"),
                    latitude=loc_data.get("latitude"),
                    longitude=loc_data.get("longitude"),
                    home_address=home_address
                )
        
        # 构建偏好设置
        preferences = None
        if user_data.get("preferences"):
            pref_data = user_data["preferences"]
            if pref_data:
                # 兼容旧数据：如果 preferences 是列表，则将其作为 interests
                if isinstance(pref_data, list):
                    logger.warning(f"[UserService] 用户 {user_data.get('id', 'unknown')} 的 preferences 格式已过时（列表），正在转换为字典格式")
                    pref_data = {"interests": pref_data}
                
                # 确保 pref_data 是字典
                if not isinstance(pref_data, dict):
                    pref_data = {}
                
                preferences = UserPreferences(
                    transport_modes=pref_data.get("transport_modes", []),
                    interests=pref_data.get("interests", []),
                    budget_range=pref_data.get("budget_range"),
                    travel_pace=pref_data.get("travel_pace"),
                    dietary_restrictions=pref_data.get("dietary_restrictions", []),
                    taste_preference=pref_data.get("taste_preference"),
                    poi_likes=pref_data.get("poi_likes", []),
                    poi_dislikes=pref_data.get("poi_dislikes", []),
                    poi_removes=pref_data.get("poi_removes", [])
                )
        
        # 构建完整资料
        return UserProfile(
            id=user_data.get("id", ""),
            username=user_data.get("username", ""),
            email=user_data.get("email", ""),
            avatar=user_data.get("avatar"),
            bio=user_data.get("bio"),
            gender=user_data.get("gender"),
            birthday=user_data.get("birthday"),
            location=location,
            preferences=preferences,
            phone=user_data.get("phone"),
            created_at=user_data.get("created_at"),
            updated_at=user_data.get("updated_at")
        )


# 导出单例
user_service = UserService()
