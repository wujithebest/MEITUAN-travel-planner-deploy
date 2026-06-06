"""
协作相关模型
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from .base import OperationType, Permission
from .base import POI


class RoomMember(BaseModel):
    """房间成员模型"""
    user_id: str = Field(..., description="用户ID")
    username: str = Field("", description="用户名")
    permission: Permission = Field(Permission.VIEWER, description="权限")
    joined_at: datetime = Field(default_factory=datetime.now)
    is_online: bool = Field(False, description="是否在线")


class Operation(BaseModel):
    """协作操作模型"""
    operation_id: str = Field("", description="操作唯一标识")
    room_id: str = Field("", description="房间ID")
    user_id: str = Field("", description="操作用户ID")
    operation_type: OperationType = Field(..., description="操作类型")
    target_index: Optional[int] = Field(None, description="目标索引")
    old_value: Optional[str] = Field(None, description="旧值")
    new_value: Optional[str] = Field(None, description="新值")
    poi: Optional[POI] = Field(None, description="相关POI")
    version: int = Field(0, description="操作时版本号")
    timestamp: datetime = Field(default_factory=datetime.now)
    is_undone: bool = Field(False, description="是否已撤销")


class CollaborationRoom(BaseModel):
    """协作房间模型"""
    room_id: str = Field(..., description="房间唯一标识")
    route_id: str = Field("", description="关联路线ID")
    name: str = Field("", description="房间名称")
    owner_id: str = Field("", description="房主ID")
    members: List[RoomMember] = Field(default_factory=list, description="成员列表")
    version: int = Field(0, description="乐观锁版本号")
    operations: List[Operation] = Field(default_factory=list, description="操作历史")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class WSMessage(BaseModel):
    """WebSocket消息模型"""
    type: str = Field(..., description="消息类型: operation/join/leave/sync/error")
    data: Dict[str, Any] = Field(default_factory=dict, description="消息数据")
    room_id: str = Field("", description="房间ID")
    user_id: str = Field("", description="用户ID")
    timestamp: datetime = Field(default_factory=datetime.now)


class CreateRoomRequest(BaseModel):
    """创建房间请求"""
    name: str = Field("", description="房间名称")
    route_id: str = Field("", description="关联路线ID")


class JoinRoomRequest(BaseModel):
    """加入房间请求"""
    room_id: str = Field(..., description="房间ID")
    user_id: str = Field(..., description="用户ID")
    username: str = Field("", description="用户名")


class OperationRequest(BaseModel):
    """操作请求"""
    room_id: str = Field(..., description="房间ID")
    operation_type: OperationType = Field(..., description="操作类型")
    target_index: Optional[int] = Field(None, description="目标索引")
    poi: Optional[POI] = Field(None, description="相关POI")
    new_value: Optional[str] = Field(None, description="新值")
