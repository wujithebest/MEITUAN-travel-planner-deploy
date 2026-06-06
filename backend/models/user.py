"""
用户数据模型 - Pydantic 模型定义
"""
from typing import Optional, List, Union, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class PoiInteractionRecord(BaseModel):
    """POI 交互记录"""
    poi_name: str = Field(..., description="POI 名称")
    poi_type: str = Field("", description="POI 分类")
    action: str = Field(..., description="like | dislike | remove | add | replace")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    hit_count: int = Field(default=1, description="累计命中次数")


class UserBase(BaseModel):
    """用户基础模型"""
    username: str = Field(..., min_length=2, max_length=20, description="用户名")
    email: str = Field(..., description="用户邮箱")
    gender: Optional[str] = Field(None, description="性别: male/female")
    birthday: Optional[str] = Field(None, description="生日: YYYY-MM-DD")


class HomeAddress(BaseModel):
    """用户常住地址"""
    name: Optional[str] = Field(None, description="地址名称")
    full_address: Optional[str] = Field(None, description="完整地址")
    lng: Optional[float] = Field(None, description="经度")
    lat: Optional[float] = Field(None, description="纬度")


class UserLocation(BaseModel):
    """用户位置信息"""
    province: Optional[str] = Field(None, description="省份")
    city: Optional[str] = Field(None, description="城市")
    district: Optional[str] = Field(None, description="区县")
    address: Optional[str] = Field(None, description="详细地址")
    latitude: Optional[float] = Field(None, description="纬度")
    longitude: Optional[float] = Field(None, description="经度")
    home_address: Optional[HomeAddress] = Field(None, description="常住地址")


class UserPreferences(BaseModel):
    """用户偏好设置"""
    transport_modes: List[str] = Field(default=[], description="偏好交通方式")
    interests: List[str] = Field(default=[], description="兴趣标签")
    budget_range: Optional[str] = Field(None, description="预算范围")
    travel_pace: Optional[str] = Field(None, description="旅行节奏：relaxed/moderate/intensive")
    dietary_restrictions: List[str] = Field(default=[], description="饮食限制")
    taste_preference: Optional[str] = Field(None, description="口味偏好: 百味皆爱/川菜/粤菜/湘菜/鲁菜/苏浙菜/日料/韩餐/西餐/东南亚菜/烧烤火锅/小吃快餐")
    # POI 交互记录
    poi_likes: List[PoiInteractionRecord] = Field(default=[], description="喜欢的 POI 记录")
    poi_dislikes: List[PoiInteractionRecord] = Field(default=[], description="不喜欢的 POI 记录")
    poi_removes: List[PoiInteractionRecord] = Field(default=[], description="从路线移除的 POI 记录")

    @field_validator('interests', 'transport_modes', 'dietary_restrictions', mode='before')
    @classmethod
    def filter_none_values(cls, v):
        """过滤列表中的 None 值"""
        if v is None:
            return []
        if isinstance(v, list):
            return [item for item in v if item is not None]
        return v

    @classmethod
    def from_list(cls, interests_list: List[str]) -> 'UserPreferences':
        """从兴趣列表创建 UserPreferences 对象"""
        return cls(interests=interests_list)


class UserProfile(BaseModel):
    """用户完整资料模型"""
    id: str = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    email: str = Field(..., description="邮箱")
    avatar: Optional[str] = Field(None, description="头像URL")
    bio: Optional[str] = Field(None, description="个人简介")
    gender: Optional[str] = Field(None, description="性别")
    birthday: Optional[str] = Field(None, description="生日")
    location: Optional[UserLocation] = Field(None, description="位置信息")
    preferences: Optional[UserPreferences] = Field(None, description="偏好设置")
    phone: Optional[str] = Field(None, description="手机号")
    created_at: Optional[str] = Field(None, description="创建时间")
    updated_at: Optional[str] = Field(None, description="更新时间")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "uuid-string",
                "username": "张三",
                "email": "zhangsan@example.com",
                "avatar": "https://example.com/avatar.jpg",
                "bio": "热爱旅行的上海人",
                "location": {
                    "city": "上海",
                    "district": "浦东新区",
                    "address": "陆家嘴金融中心",
                    "latitude": 31.2397,
                    "longitude": 121.4998
                },
                "preferences": {
                    "transport_modes": ["subway", "walking"],
                    "interests": ["美食", "历史", "艺术"],
                    "budget_range": "medium",
                    "travel_pace": "moderate",
                    "dietary_restrictions": ["vegetarian"]
                },
                "phone": "13800138000",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }
        }


class UserProfileUpdate(BaseModel):
    """用户资料更新请求模型"""
    username: Optional[str] = Field(None, min_length=2, max_length=20, description="用户名")
    bio: Optional[str] = Field(None, max_length=500, description="个人简介")
    avatar: Optional[str] = Field(None, description="头像URL")
    gender: Optional[str] = Field(None, description="性别")
    birthday: Optional[str] = Field(None, description="生日")
    location: Optional[UserLocation] = Field(None, description="位置信息")
    preferences: Optional[Union[UserPreferences, List[str], dict]] = Field(None, description="偏好设置")
    phone: Optional[str] = Field(None, description="手机号")

    @field_validator('preferences', mode='before')
    @classmethod
    def validate_preferences(cls, v):
        """验证并转换 preferences 字段
        
        支持三种格式：
        1. UserPreferences 对象 - 直接使用
        2. dict - 转换为 UserPreferences
        3. List[str] - 作为 interests 列表转换为 UserPreferences
        """
        if v is None:
            return v
        if isinstance(v, list):
            # 如果是列表，将其作为 interests 处理
            return UserPreferences(interests=v)
        if isinstance(v, dict):
            # 如果是字典，转换为 UserPreferences
            return UserPreferences(**v)
        return v

    @field_validator('username')
    @classmethod
    def username_valid(cls, v):
        if v is not None:
            if len(v) < 2:
                raise ValueError('用户名至少2个字符')
            if len(v) > 20:
                raise ValueError('用户名最多20字符')
            # 只允许字母、数字、中文、下划线
            import re
            if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9_]+$', v):
                raise ValueError('用户名只能包含字母、数字、中文和下划线')
        return v

    @field_validator('phone')
    @classmethod
    def phone_valid(cls, v):
        if v is not None:
            import re
            if not re.match(r'^1[3-9]\d{9}$', v):
                raise ValueError('手机号格式不正确')
        return v


class UsernameCheckResponse(BaseModel):
    """用户名检查响应"""
    available: bool = Field(..., description="是否可用")
    message: str = Field(..., description="提示信息")
