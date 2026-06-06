"""
协作服务
WebSocket管理、Redis Pub/Sub广播、乐观锁、权限控制
"""

import json
import logging
import uuid
from typing import Optional
from datetime import datetime
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect

from config import get_settings
from models.collab import (
    CollaborationRoom, RoomMember, Operation, WSMessage,
    OperationType, Permission
)
from models.base import POI
from exceptions import CollabError

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        # room_id -> {user_id: WebSocket}
        self.active_connections: dict[str, dict[str, WebSocket]] = defaultdict(dict)
        # room_id -> CollaborationRoom（内存缓存）
        self.rooms: dict[str, CollaborationRoom] = {}

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str) -> None:
        """建立WebSocket连接"""
        await websocket.accept()
        self.active_connections[room_id][user_id] = websocket
        logger.info(f"用户{user_id}连接到房间{room_id}")

        # 广播加入消息
        join_msg = WSMessage(
            type="join",
            data={"user_id": user_id},
            room_id=room_id,
            user_id=user_id
        )
        await self.broadcast(room_id, join_msg, exclude_user=user_id)

    async def disconnect(self, room_id: str, user_id: str) -> None:
        """断开WebSocket连接"""
        if room_id in self.active_connections:
            self.active_connections[room_id].pop(user_id, None)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

        logger.info(f"用户{user_id}断开房间{room_id}")

        # 广播离开消息
        leave_msg = WSMessage(
            type="leave",
            data={"user_id": user_id},
            room_id=room_id,
            user_id=user_id
        )
        await self.broadcast(room_id, leave_msg)

    async def broadcast(
        self,
        room_id: str,
        message: WSMessage,
        exclude_user: Optional[str] = None
    ) -> None:
        """广播消息到房间内所有连接"""
        if room_id not in self.active_connections:
            return

        message_data = json.dumps(message.model_dump(), default=str)

        disconnected = []
        for user_id, connection in self.active_connections[room_id].items():
            if user_id == exclude_user:
                continue
            try:
                await connection.send_text(message_data)
            except Exception as e:
                logger.warning(f"发送消息失败: user={user_id}, error={str(e)}")
                disconnected.append(user_id)

        # 清理断开的连接
        for user_id in disconnected:
            await self.disconnect(room_id, user_id)

    async def send_personal(self, room_id: str, user_id: str, message: WSMessage) -> None:
        """发送个人消息"""
        if room_id in self.active_connections and user_id in self.active_connections[room_id]:
            try:
                await self.active_connections[room_id][user_id].send_text(
                    json.dumps(message.model_dump(), default=str)
                )
            except Exception as e:
                logger.warning(f"个人消息发送失败: {str(e)}")

    def get_online_users(self, room_id: str) -> list[str]:
        """获取房间内在线用户"""
        return list(self.active_connections.get(room_id, {}).keys())


class CollaborationService:
    """协作服务"""

    def __init__(self):
        self.settings = get_settings()
        self.connection_manager = ConnectionManager()
        self._redis: Optional[object] = None

    async def _get_redis(self):
        """获取Redis连接（延迟初始化）"""
        if self._redis is None:
            try:
                import redis.asyncio as redis_lib
                self._redis = redis_lib.from_url(
                    self.settings.redis_url,
                    decode_responses=True
                )
            except Exception as e:
                logger.warning(f"Redis连接失败，使用内存模式: {str(e)}")
                self._redis = None
        return self._redis

    async def create_room(
        self, name: str, owner_id: str, route_id: str = ""
    ) -> CollaborationRoom:
        """创建协作房间"""
        room_id = str(uuid.uuid4())[:8]
        room = CollaborationRoom(
            room_id=room_id,
            route_id=route_id,
            name=name or f"房间-{room_id}",
            owner_id=owner_id,
            members=[
                RoomMember(
                    user_id=owner_id,
                    username=owner_id,
                    permission=Permission.OWNER,
                    is_online=True
                )
            ],
            version=0
        )
        self.connection_manager.rooms[room_id] = room

        # 尝试持久化到Redis
        try:
            r = await self._get_redis()
            if r:
                await r.setex(
                    f"collab:room:{room_id}",
                    86400,
                    json.dumps(room.model_dump(), default=str)
                )
        except Exception:
            pass

        logger.info(f"创建房间: {room_id}, 房主: {owner_id}")
        return room

    async def join_room(
        self, room_id: str, user_id: str, username: str
    ) -> CollaborationRoom:
        """加入协作房间"""
        room = await self.get_room(room_id)
        if not room:
            raise CollabError(f"房间不存在: {room_id}")

        # 检查是否已在房间中
        for member in room.members:
            if member.user_id == user_id:
                return room

        # 添加新成员
        room.members.append(RoomMember(
            user_id=user_id,
            username=username or user_id,
            permission=Permission.EDITOR
        ))
        room.updated_at = datetime.now()

        # 更新Redis
        try:
            r = await self._get_redis()
            if r:
                await r.setex(
                    f"collab:room:{room_id}",
                    86400,
                    json.dumps(room.model_dump(), default=str)
                )
        except Exception:
            pass

        logger.info(f"用户{user_id}加入房间{room_id}")
        return room

    async def get_room(self, room_id: str) -> Optional[CollaborationRoom]:
        """获取房间信息"""
        # 先查内存
        if room_id in self.connection_manager.rooms:
            return self.connection_manager.rooms[room_id]

        # 再查Redis
        try:
            r = await self._get_redis()
            if r:
                data = await r.get(f"collab:room:{room_id}")
                if data:
                    room_dict = json.loads(data)
                    room = CollaborationRoom(**room_dict)
                    self.connection_manager.rooms[room_id] = room
                    return room
        except Exception:
            pass

        return None

    async def handle_operation(
        self, room_id: str, user_id: str, operation_data: dict
    ) -> Operation:
        """
        处理协作操作
        乐观锁version，Last-Write-Wins
        """
        room = await self.get_room(room_id)
        if not room:
            raise CollabError(f"房间不存在: {room_id}")

        # 权限检查
        if not self._check_permission(room, user_id, operation_data.get("operation_type", "")):
            raise CollabError("权限不足，无法执行此操作")

        # 乐观锁检查
        client_version = operation_data.get("version", 0)
        if client_version < room.version:
            logger.warning(f"版本冲突: client={client_version}, server={room.version}")

        # 创建操作记录
        operation = Operation(
            operation_id=str(uuid.uuid4())[:12],
            room_id=room_id,
            user_id=user_id,
            operation_type=OperationType(operation_data.get("operation_type", "add")),
            target_index=operation_data.get("target_index"),
            old_value=operation_data.get("old_value"),
            new_value=operation_data.get("new_value"),
            poi=POI(**operation_data["poi"]) if operation_data.get("poi") else None,
            version=room.version + 1
        )

        # 更新版本号
        room.version += 1
        room.operations.append(operation)
        room.updated_at = datetime.now()

        # 广播操作
        message = WSMessage(
            type="operation",
            data=json.loads(json.dumps(operation.model_dump(), default=str)),
            room_id=room_id,
            user_id=user_id
        )
        await self.connection_manager.broadcast(room_id, message)

        # 更新Redis
        await self._persist_room(room)

        logger.info(f"操作处理: {operation.operation_type} by {user_id} in {room_id}")
        return operation

    async def undo_operation(self, room_id: str, user_id: str, operation_id: str) -> None:
        """撤销操作"""
        room = await self.get_room(room_id)
        if not room:
            raise CollabError(f"房间不存在: {room_id}")

        for op in room.operations:
            if op.operation_id == operation_id:
                op.is_undone = True
                room.version += 1

                # 广播撤销
                message = WSMessage(
                    type="undo",
                    data={"operation_id": operation_id},
                    room_id=room_id,
                    user_id=user_id
                )
                await self.connection_manager.broadcast(room_id, message)
                await self._persist_room(room)
                return

        raise CollabError(f"操作不存在: {operation_id}")

    def _check_permission(
        self, room: CollaborationRoom, user_id: str, operation_type: str
    ) -> bool:
        """检查操作权限"""
        for member in room.members:
            if member.user_id == user_id:
                if member.permission == Permission.OWNER:
                    return True
                if member.permission == Permission.EDITOR:
                    return operation_type in [
                        OperationType.ADD,
                        OperationType.REMOVE,
                        OperationType.REORDER,
                        OperationType.UPDATE_TIME,
                        OperationType.ADD_NOTE,
                        OperationType.CHANGE_TRANSPORT
                    ]
                if member.permission == Permission.VIEWER:
                    return operation_type in [OperationType.ADD_NOTE]
        return False

    async def _persist_room(self, room: CollaborationRoom) -> None:
        """持久化房间到Redis"""
        try:
            r = await self._get_redis()
            if r:
                await r.setex(
                    f"collab:room:{room.room_id}",
                    86400,
                    json.dumps(room.model_dump(), default=str)
                )
        except Exception:
            pass

    async def get_members(self, room_id: str) -> list[RoomMember]:
        """获取房间成员列表"""
        room = await self.get_room(room_id)
        if not room:
            raise CollabError(f"房间不存在: {room_id}")
        return room.members


# 单例
_collab_service: Optional[CollaborationService] = None


def get_collab_service() -> CollaborationService:
    """获取协作服务单例"""
    global _collab_service
    if _collab_service is None:
        _collab_service = CollaborationService()
    return _collab_service
