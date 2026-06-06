"""
聊天模块核心模型
支持多人协作的旅行群聊+AI助手模式
"""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field
from enum import Enum
import uuid


# ==================== 基础模型 ====================

class ChatMember(BaseModel):
    """聊天室成员"""
    user_id: str
    username: str
    avatar: str | None = None
    role: Literal["owner", "admin", "member"] = "member"
    joined_at: datetime = Field(default_factory=datetime.now)
    last_read_at: datetime | None = None
    is_online: bool = False


class MessageSender(BaseModel):
    """消息发送者"""
    id: str  # user_id 或 "agent"
    name: str  # "张三" 或 "旅行助手"
    avatar: str | None = None
    is_agent: bool = False
    agent_type: Literal["travel_assistant", "route_planner", "review_analyst"] | None = None


class LocationData(BaseModel):
    """位置数据"""
    name: str
    address: str
    latitude: float
    longitude: float
    poi_id: str | None = None


class RouteCardData(BaseModel):
    """路线卡片数据"""
    route_id: str
    name: str
    days: int
    pois_count: int
    preview_image: str | None = None
    summary: str


class POICardData(BaseModel):
    """POI卡片数据"""
    poi_id: str
    name: str
    category: str
    rating: float | None = None
    image_url: str | None = None
    address: str | None = None


class MessageContent(BaseModel):
    """消息内容 - 支持多类型"""
    type: Literal["text", "image", "location", "route_card", "poi_card", "itinerary_preview", "system_notice"]
    text: str | None = None
    media_url: str | None = None  # 图片/文件URL
    location: LocationData | None = None  # 位置分享
    route_data: RouteCardData | None = None  # 路线卡片
    poi_data: POICardData | None = None  # POI卡片
    metadata: dict = {}  # 额外元数据


class MessageReaction(BaseModel):
    """消息表情反应"""
    emoji: str
    user_ids: list[str] = []
    count: int = 0


class ChatMessage(BaseModel):
    """聊天消息"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    room_id: str
    sender: MessageSender  # 用户或AI
    content: MessageContent  # 支持多类型
    reply_to: str | None = None  # 回复某条消息
    timestamp: datetime = Field(default_factory=datetime.now)
    status: Literal["sending", "sent", "failed"] = "sent"
    reactions: list[MessageReaction] = []  # 表情回应


class ChatMessagePreview(BaseModel):
    """消息预览（用于房间列表显示）"""
    text: str
    sender_name: str
    timestamp: datetime
    content_type: str = "text"


class RoomSettings(BaseModel):
    """房间设置"""
    is_private: bool = False
    allow_invite: bool = True
    agent_enabled: bool = True  # 是否启用AI助手
    agent_personality: Literal["professional", "friendly", "humorous"] = "friendly"
    language: str = "zh-CN"


# ==================== 旅行意图模型 ====================

class TravelIntent(BaseModel):
    """AI从群聊中累计提取的旅行意图"""
    destination: str | None = None  # "上海徐汇区"
    days: int | None = None
    dates: tuple[datetime, datetime] | None = None
    themes: list[str] = []  # ["美食", "历史"]
    must_visit: list[str] = []  # 明确提到的地点
    preferences: list[str] = []  # ["不爬山", "少走路"]
    budget_level: Literal["经济", "中等", "高端"] | None = None
    travelers: list[str] = []  # ["亲子", "情侣", "老人"]
    extracted_from: list[str] = []  # 从哪些消息提取的（消息ID列表）
    confidence: float = 0.0  # 0-1 信息完整度
    last_updated: datetime = Field(default_factory=datetime.now)


# ==================== 聊天室模型 ====================

class ChatRoom(BaseModel):
    """聊天室"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str  # "五一上海游"
    avatar: str | None = None  # 群头像URL
    description: str | None = None
    creator_id: str
    members: list[ChatMember] = []
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_message: ChatMessagePreview | None = None  # 最后消息预览
    unread_count: dict[str, int] = {}  # user_id -> 未读数
    settings: RoomSettings = Field(default_factory=RoomSettings)
    extracted_intent: TravelIntent | None = None  # AI提取的累计意图
    tags: list[str] = []  # 标签，如 ["进行中", "已完成"]


# ==================== AI Agent 模型 ====================

class AgentAction(BaseModel):
    """AI助手触发的动作"""
    action: Literal["answer", "extract_intent", "suggest_route", "generate_route", "clarify"]
    content: str  # AI回复文本
    route_draft: dict | None = None  # 路线草稿
    questions: list[str] | None = None  # 需要澄清的问题
    metadata: dict = {}


class ItineraryDraft(BaseModel):
    """路线草稿"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    room_id: str
    name: str
    destination: str
    days: int
    pois: list[dict] = []
    summary: str
    created_at: datetime = Field(default_factory=datetime.now)
    status: Literal["draft", "confirmed", "rejected"] = "draft"


# ==================== WebSocket 消息类型 ====================

class WSMessageType(str, Enum):
    """WebSocket消息类型"""
    # 客户端发送
    MESSAGE = "message"
    TYPING = "typing"
    READ_ACK = "read_ack"
    JOIN_ROOM = "join_room"
    LEAVE_ROOM = "leave_room"
    
    # 服务端发送
    NEW_MESSAGE = "new_message"
    MEMBER_ONLINE = "member_online"
    MEMBER_OFFLINE = "member_offline"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    TYPING_INDICATOR = "typing_indicator"
    READ_RECEIPT = "read_receipt"
    INTENT_UPDATED = "intent_updated"
    ERROR = "error"


class WSMessage(BaseModel):
    """WebSocket消息封装"""
    type: WSMessageType
    data: dict
    timestamp: datetime = Field(default_factory=datetime.now)


# ==================== API 请求/响应模型 ====================

class CreateRoomRequest(BaseModel):
    """创建房间请求"""
    name: str
    description: str | None = None
    avatar: str | None = None
    initial_members: list[str] = []  # 初始成员user_id列表


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    content_type: Literal["text", "image", "location", "route_card", "poi_card"] = "text"
    text: str | None = None
    media_url: str | None = None
    location: LocationData | None = None
    reply_to: str | None = None


class RoomListResponse(BaseModel):
    """房间列表响应"""
    id: str
    name: str
    avatar: str | None = None
    last_message: ChatMessagePreview | None = None
    unread_count: int = 0
    member_count: int = 0
    is_online: bool = False  # 是否有成员在线
    updated_at: datetime


class MessageListResponse(BaseModel):
    """消息列表响应"""
    messages: list[ChatMessage]
    has_more: bool = False
    next_cursor: str | None = None
