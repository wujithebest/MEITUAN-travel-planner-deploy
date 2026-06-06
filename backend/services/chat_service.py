"""
聊天服务 - Redis 持久化版本
提供房间管理、成员管理、消息存储等功能
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from models.chat import (
    ChatRoom, ChatMessage, ChatMember, ChatMessagePreview,
    MessageSender, MessageContent, LocationData, TravelIntent
)

logger = logging.getLogger(__name__)


class ChatService:
    """
    聊天服务 - 基于 Redis 的持久化存储
    
    功能：
    - 房间创建、获取、更新
    - 成员管理（添加、移除、检查）
    - 消息存储和检索
    - 房间意图管理
    """
    
    def __init__(self, redis_client=None):
        """
        初始化聊天服务
        
        Args:
            redis_client: Redis 客户端实例，如果为 None 则使用内存存储（开发模式）
        """
        self.redis = redis_client
        self._memory_rooms: dict[str, ChatRoom] = {}  # 内存存储（备用）
        self._memory_messages: dict[str, list[ChatMessage]] = {}  # 内存存储（备用）
        
        if self.redis:
            logger.info("[ChatService] 使用 Redis 持久化存储")
        else:
            logger.warning("[ChatService] Redis 未配置，使用内存存储（数据不会持久化）")
    
    # ==================== 房间操作 ====================
    
    async def save_room(self, room: ChatRoom) -> ChatRoom:
        """
        保存房间到存储
        
        Args:
            room: 房间对象
            
        Returns:
            保存后的房间对象
        """
        try:
            if self.redis:
                key = f"chat:room:{room.id}"
                room_json = room.json()
                await self.redis.set(key, room_json, ex=86400 * 7)  # 7天过期
                logger.info(f"[ChatService] 房间已保存到 Redis: {room.id}")
            else:
                # 内存存储
                self._memory_rooms[room.id] = room
                logger.info(f"[ChatService] 房间已保存到内存: {room.id}")
            
            return room
        except Exception as e:
            logger.error(f"[ChatService] 保存房间失败: {e}", exc_info=True)
            # 降级到内存存储
            self._memory_rooms[room.id] = room
            return room
    
    async def get_room(self, room_id: str) -> Optional[ChatRoom]:
        """
        获取房间
        
        Args:
            room_id: 房间ID
            
        Returns:
            房间对象，如果不存在返回 None
        """
        try:
            if self.redis:
                key = f"chat:room:{room_id}"
                data = await self.redis.get(key)
                if data:
                    room = ChatRoom.parse_raw(data)
                    logger.debug(f"[ChatService] 从 Redis 获取房间: {room_id}")
                    return room
                else:
                    logger.debug(f"[ChatService] Redis 中房间不存在: {room_id}")
                    return None
            else:
                # 内存存储
                return self._memory_rooms.get(room_id)
        except Exception as e:
            logger.error(f"[ChatService] 获取房间失败: {e}", exc_info=True)
            return self._memory_rooms.get(room_id)
    
    async def delete_room(self, room_id: str) -> bool:
        """
        删除房间
        
        Args:
            room_id: 房间ID
            
        Returns:
            是否删除成功
        """
        try:
            if self.redis:
                key = f"chat:room:{room_id}"
                await self.redis.delete(key)
            
            # 同时删除内存中的
            self._memory_rooms.pop(room_id, None)
            self._memory_messages.pop(room_id, None)
            
            logger.info(f"[ChatService] 房间已删除: {room_id}")
            return True
        except Exception as e:
            logger.error(f"[ChatService] 删除房间失败: {e}", exc_info=True)
            return False
    
    async def get_user_rooms(self, user_id: str) -> list[ChatRoom]:
        """
        获取用户加入的所有房间
        
        Args:
            user_id: 用户ID
            
        Returns:
            房间列表，按更新时间倒序
        """
        user_rooms = []
        
        try:
            if self.redis:
                # 扫描所有房间
                pattern = "chat:room:*"
                async for key in self.redis.scan_iter(match=pattern):
                    data = await self.redis.get(key)
                    if data:
                        room = ChatRoom.parse_raw(data)
                        if any(m.user_id == user_id for m in room.members):
                            user_rooms.append(room)
            else:
                # 内存存储
                for room in self._memory_rooms.values():
                    if any(m.user_id == user_id for m in room.members):
                        user_rooms.append(room)
            
            # 按更新时间倒序
            user_rooms.sort(key=lambda r: r.updated_at, reverse=True)
            logger.debug(f"[ChatService] 获取用户 {user_id} 的房间: {len(user_rooms)} 个")
            
        except Exception as e:
            logger.error(f"[ChatService] 获取用户房间失败: {e}", exc_info=True)
        
        return user_rooms
    
    # ==================== 成员操作 ====================
    
    async def add_member(self, room_id: str, member: ChatMember) -> bool:
        """
        添加成员到房间
        
        Args:
            room_id: 房间ID
            member: 成员对象
            
        Returns:
            是否添加成功
        """
        try:
            room = await self.get_room(room_id)
            if not room:
                logger.warning(f"[ChatService] 房间不存在: {room_id}")
                return False
            
            # 检查是否已在房间
            if any(m.user_id == member.user_id for m in room.members):
                logger.info(f"[ChatService] 用户已在房间中: {member.user_id}")
                return False
            
            # 添加成员
            room.members.append(member)
            room.updated_at = datetime.now()
            
            # 保存
            await self.save_room(room)
            
            logger.info(f"[ChatService] 成员已添加: room={room_id}, user={member.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"[ChatService] 添加成员失败: {e}", exc_info=True)
            return False
    
    async def remove_member(self, room_id: str, user_id: str) -> bool:
        """
        从房间移除成员
        
        Args:
            room_id: 房间ID
            user_id: 用户ID
            
        Returns:
            是否移除成功
        """
        try:
            room = await self.get_room(room_id)
            if not room:
                return False
            
            # 移除成员
            original_count = len(room.members)
            room.members = [m for m in room.members if m.user_id != user_id]
            
            if len(room.members) < original_count:
                room.updated_at = datetime.now()
                await self.save_room(room)
                logger.info(f"[ChatService] 成员已移除: room={room_id}, user={user_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"[ChatService] 移除成员失败: {e}", exc_info=True)
            return False
    
    async def is_member(self, room_id: str, user_id: str) -> bool:
        """
        检查用户是否在房间中
        
        Args:
            room_id: 房间ID
            user_id: 用户ID
            
        Returns:
            是否在房间中
        """
        room = await self.get_room(room_id)
        if not room:
            return False
        return any(m.user_id == user_id for m in room.members)
    
    async def update_member_online_status(self, room_id: str, user_id: str, is_online: bool) -> bool:
        """
        更新成员在线状态
        
        Args:
            room_id: 房间ID
            user_id: 用户ID
            is_online: 是否在线
            
        Returns:
            是否更新成功
        """
        try:
            room = await self.get_room(room_id)
            if not room:
                return False
            
            for member in room.members:
                if member.user_id == user_id:
                    member.is_online = is_online
                    break
            
            await self.save_room(room)
            return True
            
        except Exception as e:
            logger.error(f"[ChatService] 更新成员状态失败: {e}", exc_info=True)
            return False
    
    async def get_room_members(self, room_id: str) -> list[ChatMember]:
        """
        获取房间成员列表
        
        Args:
            room_id: 房间ID
            
        Returns:
            成员列表
        """
        room = await self.get_room(room_id)
        if not room:
            return []
        return room.members
    
    # ==================== 消息操作 ====================
    
    async def save_message(self, message: ChatMessage) -> ChatMessage:
        """
        保存消息
        
        Args:
            message: 消息对象
            
        Returns:
            保存后的消息对象
        """
        try:
            if self.redis:
                key = f"chat:messages:{message.room_id}"
                message_json = message.json()
                await self.redis.lpush(key, message_json)
                await self.redis.ltrim(key, 0, 499)  # 保留最近500条
                await self.redis.expire(key, 86400 * 7)  # 7天过期
            else:
                # 内存存储
                if message.room_id not in self._memory_messages:
                    self._memory_messages[message.room_id] = []
                self._memory_messages[message.room_id].append(message)
                # 只保留最近500条
                if len(self._memory_messages[message.room_id]) > 500:
                    self._memory_messages[message.room_id] = self._memory_messages[message.room_id][-500:]
            
            # 更新房间最后消息
            room = await self.get_room(message.room_id)
            if room:
                room.last_message = ChatMessagePreview(
                    text=message.content.text or f"[{message.content.type}]",
                    sender_name=message.sender.name,
                    timestamp=message.timestamp,
                    content_type=message.content.type
                )
                room.updated_at = datetime.now()
                await self.save_room(room)
            
            return message
            
        except Exception as e:
            logger.error(f"[ChatService] 保存消息失败: {e}", exc_info=True)
            # 降级到内存存储
            if message.room_id not in self._memory_messages:
                self._memory_messages[message.room_id] = []
            self._memory_messages[message.room_id].append(message)
            return message
    
    async def get_messages(
        self, 
        room_id: str, 
        before: Optional[str] = None, 
        limit: int = 20
    ) -> list[ChatMessage]:
        """
        获取消息历史
        
        Args:
            room_id: 房间ID
            before: 分页游标，上一页最后一条消息的ID
            limit: 返回消息数量
            
        Returns:
            消息列表
        """
        try:
            messages = await self._get_all_messages(room_id)
            
            if before:
                # 找到before消息的位置
                for i, msg in enumerate(messages):
                    if msg.id == before:
                        messages = messages[:i]
                        break
            
            # 返回最近的 limit 条
            return messages[-limit:]
            
        except Exception as e:
            logger.error(f"[ChatService] 获取消息失败: {e}", exc_info=True)
            return []
    
    async def get_history(self, room_id: str, limit: int = 50) -> list[ChatMessage]:
        """
        获取最近历史消息
        
        Args:
            room_id: 房间ID
            limit: 返回消息数量
            
        Returns:
            消息列表
        """
        try:
            messages = await self._get_all_messages(room_id)
            return messages[-limit:]
        except Exception as e:
            logger.error(f"[ChatService] 获取历史失败: {e}", exc_info=True)
            return []
    
    async def _get_all_messages(self, room_id: str) -> list[ChatMessage]:
        """获取房间所有消息"""
        messages = []
        
        try:
            if self.redis:
                key = f"chat:messages:{room_id}"
                data_list = await self.redis.lrange(key, 0, -1)
                for data in data_list:
                    try:
                        msg = ChatMessage.parse_raw(data)
                        messages.append(msg)
                    except Exception as e:
                        logger.warning(f"[ChatService] 解析消息失败: {e}")
            else:
                # 内存存储
                messages = self._memory_messages.get(room_id, [])
            
            # 按时间排序
            messages.sort(key=lambda m: m.timestamp)
            
        except Exception as e:
            logger.error(f"[ChatService] 获取所有消息失败: {e}", exc_info=True)
            messages = self._memory_messages.get(room_id, [])
        
        return messages
    
    # ==================== 意图操作 ====================
    
    async def update_room_intent(self, room_id: str, intent: TravelIntent) -> bool:
        """
        更新房间提取的旅行意图
        
        Args:
            room_id: 房间ID
            intent: 旅行意图
            
        Returns:
            是否更新成功
        """
        try:
            room = await self.get_room(room_id)
            if not room:
                return False
            
            room.extracted_intent = intent
            room.updated_at = datetime.now()
            await self.save_room(room)
            
            logger.info(f"[ChatService] 房间意图已更新: {room_id}")
            return True
            
        except Exception as e:
            logger.error(f"[ChatService] 更新意图失败: {e}", exc_info=True)
            return False
    
    async def get_room_intent(self, room_id: str) -> Optional[TravelIntent]:
        """
        获取房间提取的旅行意图
        
        Args:
            room_id: 房间ID
            
        Returns:
            旅行意图，如果不存在返回 None
        """
        room = await self.get_room(room_id)
        if not room:
            return None
        return room.extracted_intent
    
    # ==================== 已读操作 ====================
    
    async def mark_read(self, room_id: str, user_id: str, last_message_id: str) -> bool:
        """
        标记已读
        
        Args:
            room_id: 房间ID
            user_id: 用户ID
            last_message_id: 最后已读消息ID
            
        Returns:
            是否标记成功
        """
        try:
            room = await self.get_room(room_id)
            if not room:
                return False
            
            for member in room.members:
                if member.user_id == user_id:
                    member.last_read_at = datetime.now()
                    break
            
            await self.save_room(room)
            return True
            
        except Exception as e:
            logger.error(f"[ChatService] 标记已读失败: {e}", exc_info=True)
            return False


# ==================== 全局服务实例 ====================

_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """
    获取聊天服务实例（单例）
    
    Returns:
        ChatService 实例
    """
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service


def init_chat_service(redis_client=None) -> ChatService:
    """
    初始化聊天服务
    
    Args:
        redis_client: Redis 客户端实例
        
    Returns:
        ChatService 实例
    """
    global _chat_service
    _chat_service = ChatService(redis_client)
    return _chat_service
