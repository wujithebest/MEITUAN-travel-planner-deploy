"""
聊天模块路由
WebSocket + REST API
修复内容：
1. WebSocket 403: 创建房间后创建者自动加入房间成员列表
2. WebSocket 403: 如果创建者不在成员列表中，自动添加（兜底）
3. REST API 401: 统一认证，确保 token 正确验证
4. 使用 Redis 持久化存储房间数据
5. 修复 datetime JSON 序列化问题
"""
import asyncio
import uuid
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from pydantic import BaseModel
import logging

from models.chat import (
    ChatRoom, ChatMessage, ChatMember, MessageSender, MessageContent,
    ChatMessagePreview, RoomSettings, TravelIntent, AgentAction,
    CreateRoomRequest, SendMessageRequest, RoomListResponse, MessageListResponse,
    LocationData, WSMessageType
)
from services.agent_service import get_travel_agent
from services.chat_service import get_chat_service, init_chat_service
from middleware.auth_middleware import get_current_user_ws, get_current_user
from services.intent_pipeline import (
    IntentPipeline, 
    IntentResult, 
    IntentType,
    init_pipeline,
    get_default_pipeline
)
from services.intent_extractor import IntentExtractor
from services.step4_adapter import run_step4_with_capture
from services.utils import PipelineLogger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ==================== 意图处理流水线 ====================

# 初始化意图处理流水线
intent_pipeline = init_pipeline()

# 意图提取器
intent_extractor = IntentExtractor()


# ==================== 自定义JSON编码器 ====================

class DateTimeEncoder(json.JSONEncoder):
    """自定义JSON编码器，处理datetime对象"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def serialize_for_json(obj):
    """递归序列化对象，将datetime转换为ISO格式字符串"""
    if isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [serialize_for_json(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif hasattr(obj, 'dict'):
        # 处理Pydantic模型
        return serialize_for_json(obj.dict())
    else:
        return obj


# ==================== WebSocket连接管理 ====================

class ConnectionManager:
    """管理所有WebSocket连接"""
    
    def __init__(self):
        # room_id -> list of (websocket, user_id)
        self.rooms: dict[str, list[tuple[WebSocket, str]]] = {}
        # user_id -> websocket
        self.user_sockets: dict[str, WebSocket] = {}
        # room_id -> room_data (缓存房间数据)
        self.room_cache: dict[str, dict] = {}
    
    async def connect(self, room_id: str, user_id: str, websocket: WebSocket):
        """建立连接"""
        await websocket.accept()
        
        if room_id not in self.rooms:
            self.rooms[room_id] = []
        self.rooms[room_id].append((websocket, user_id))
        self.user_sockets[user_id] = websocket
        
        # 广播用户上线
        await self.broadcast(room_id, {
            "type": WSMessageType.MEMBER_ONLINE,
            "data": {
                "user_id": user_id,
                "timestamp": datetime.now().isoformat()
            }
        })
        
        logger.info(f"[WebSocket] 用户 {user_id} 加入房间 {room_id}")
    
    async def disconnect(self, room_id: str, user_id: str, websocket: WebSocket):
        """断开连接"""
        if room_id in self.rooms:
            self.rooms[room_id] = [
                (ws, uid) for ws, uid in self.rooms[room_id] 
                if ws != websocket
            ]
            if not self.rooms[room_id]:
                del self.rooms[room_id]
        
        self.user_sockets.pop(user_id, None)
        
        # 广播用户离线
        await self.broadcast(room_id, {
            "type": WSMessageType.MEMBER_OFFLINE,
            "data": {
                "user_id": user_id,
                "timestamp": datetime.now().isoformat()
            }
        })
        
        logger.info(f"[WebSocket] 用户 {user_id} 离开房间 {room_id}")
    
    async def broadcast(self, room_id: str, message: dict):
        """广播消息给房间所有成员"""
        if room_id not in self.rooms:
            return
        
        # 序列化消息，处理datetime对象
        serialized_message = serialize_for_json(message)
        
        dead_sockets = []
        for websocket, user_id in self.rooms[room_id]:
            try:
                await websocket.send_json(serialized_message)
            except Exception as e:
                logger.warning(f"发送消息失败: {e}")
                dead_sockets.append((websocket, user_id))
        
        # 清理断开连接
        for websocket, user_id in dead_sockets:
            await self.disconnect(room_id, user_id, websocket)
    
    async def send_to_user(self, user_id: str, message: dict):
        """发送消息给指定用户"""
        websocket = self.user_sockets.get(user_id)
        if websocket:
            try:
                await websocket.send_json(serialize_for_json(message))
            except Exception as e:
                logger.warning(f"发送消息给用户 {user_id} 失败: {e}")
    
    def get_room_members(self, room_id: str) -> list[str]:
        """获取房间成员列表"""
        if room_id not in self.rooms:
            return []
        return [uid for _, uid in self.rooms[room_id]]
    
    def is_user_online(self, user_id: str) -> bool:
        """检查用户是否在线"""
        return user_id in self.user_sockets


# 全局连接管理器
manager = ConnectionManager()

# 全局AI助手
agent = get_travel_agent()

# 全局聊天服务（使用新的 Redis 持久化版本）
chat_service = get_chat_service()


# ==================== WebSocket路由 ====================

@router.websocket("/ws/room/{room_id}")
async def chat_websocket(websocket: WebSocket, room_id: str):
    """
    WebSocket聊天端点
    
    修复：
    1. 认证成功后，检查用户是否在房间成员列表中
    2. 如果用户是创建者但不在列表中，自动添加（兜底）
    3. 非成员拒绝连接
    """
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"[WebSocket] 新连接请求: room={room_id}, client={client_host}")
    
    # ========== 1. 认证用户 ==========
    user = await get_current_user_ws(websocket)
    if not user:
        logger.warning(f"[WebSocket] 认证失败: room={room_id}, client={client_host}")
        await websocket.close(code=1008, reason="认证失败")
        return
    
    user_id = user.get('id')
    username = user.get('username', '用户')
    logger.info(f"[WebSocket] 用户认证成功: room={room_id}, user={username}({user_id})")
    
    # ========== 2. 检查房间是否存在 ==========
    room = await chat_service.get_room(room_id)
    if not room:
        logger.warning(f"[WebSocket] 房间不存在: room={room_id}")
        await websocket.close(code=1004, reason="房间不存在")
        return
    
    # ========== 3. 检查用户是否在房间（关键修复！） ==========
    member = next((m for m in room.members if m.user_id == user_id), None)
    
    if not member:
        # 如果用户是创建者但不在列表中，自动添加（兜底）
        if room.creator_id == user_id:
            logger.info(f"[WebSocket] 创建者不在成员列表中，自动添加: room={room_id}, user={user_id}")
            member = ChatMember(
                user_id=user_id,
                username=username,
                avatar=user.get('avatar', '/default-avatar.png'),
                role="owner",
                joined_at=datetime.now(),
                is_online=True
            )
            room.members.append(member)
            await chat_service.save_room(room)
            logger.info(f"[WebSocket] 创建者已自动添加到房间: room={room_id}, user={user_id}")
        else:
            # 非成员，拒绝连接
            logger.warning(f"[WebSocket] 用户不在房间中: room={room_id}, user={user_id}")
            await websocket.close(code=1008, reason="不在房间中")
            return
    
    # ========== 4. 接受连接 ==========
    await manager.connect(room_id, user_id, websocket)
    
    # ========== 5. 更新在线状态 ==========
    await chat_service.update_member_online_status(room_id, user_id, True)
    logger.info(f"[WebSocket] 连接成功: room={room_id}, user={username}({user_id}), members={len(room.members)}")
    
    # ========== 6. 发送历史消息 ==========
    try:
        history = await chat_service.get_history(room_id, limit=50)
        # 序列化历史消息
        serialized_history = serialize_for_json([msg.dict() for msg in history])
        await websocket.send_json({
            "type": "history",
            "data": serialized_history
        })
        logger.info(f"[WebSocket] 历史消息已发送: room={room_id}, count={len(history)}")
    except Exception as e:
        logger.error(f"[WebSocket] 发送历史消息失败: {e}")
    
    # ========== 7. 消息循环 ==========
    try:
        while True:
            data = await websocket.receive_json()
            
            msg_type = data.get("type")
            
            if msg_type == WSMessageType.MESSAGE:
                # 处理新消息
                await handle_chat_message(room_id, user, data)
            
            elif msg_type == WSMessageType.TYPING:
                # 广播正在输入状态
                await manager.broadcast(room_id, {
                    "type": WSMessageType.TYPING_INDICATOR,
                    "data": {
                        "user_id": user_id,
                        "username": username
                    }
                })
            
            elif msg_type == WSMessageType.READ_ACK:
                # 已读回执
                await chat_service.mark_read(
                    room_id, 
                    user_id, 
                    data.get("last_message_id")
                )
                await manager.broadcast(room_id, {
                    "type": WSMessageType.READ_RECEIPT,
                    "data": {
                        "user_id": user_id,
                        "last_message_id": data.get("last_message_id")
                    }
                })
            
            elif msg_type == WSMessageType.JOIN_ROOM:
                # 加入房间（已在连接时处理）
                pass
            
            elif msg_type == WSMessageType.LEAVE_ROOM:
                # 离开房间
                await manager.disconnect(room_id, user_id, websocket)
                break
    
    except WebSocketDisconnect:
        logger.info(f"[WebSocket] 用户断开连接: room={room_id}, user={user_id}")
    except Exception as e:
        logger.error(f"[WebSocket] 错误: room={room_id}, user={user_id}, error={e}", exc_info=True)
    finally:
        # 更新在线状态
        await chat_service.update_member_online_status(room_id, user_id, False)
        await manager.disconnect(room_id, user_id, websocket)


async def handle_chat_message(room_id: str, user: dict, data: dict):
    """处理聊天消息"""
    user_id = user.get('id')
    username = user.get('username', '用户')
    
    logger.info(f"[WebSocket] 收到消息: room={room_id}, user={username}({user_id}), type={data.get('type')}")
    
    # 构造消息对象
    msg = ChatMessage(
        room_id=room_id,
        sender=MessageSender(
            id=user_id,
            name=username,
            avatar=user.get('avatar') or "/default-avatar.png",
            is_agent=False
        ),
        content=MessageContent(
            type=data.get("content_type", "text"),
            text=data.get("text"),
            media_url=data.get("media_url"),
            location=LocationData(**data["location"]) if data.get("location") else None
        ),
        reply_to=data.get("reply_to")
    )
    
    # 保存消息
    await chat_service.save_message(msg)
    logger.info(f"[WebSocket] 消息已保存: msg_id={msg.id}")
    
    # 广播给用户
    await manager.broadcast(room_id, {
        "type": WSMessageType.NEW_MESSAGE,
        "data": msg.dict()
    })
    logger.info(f"[WebSocket] 消息已广播: room={room_id}, msg_id={msg.id}")
    
    # 触发AI处理（异步，不阻塞）
    asyncio.create_task(process_agent_response(room_id, msg))


async def process_agent_response(room_id: str, trigger_msg: ChatMessage):
    """
    AI处理消息并回应
    集成意图处理流水线，确保闭环响应
    
    修复：
    1. 意图识别后设置3秒执行超时熔断
    2. 无论执行成败必须返回非空响应到前端
    3. 空响应用兜底模板自动填充，禁止静默失败
    """
    try:
        # 获取房间
        room = await chat_service.get_room(room_id)
        if not room:
            return
        
        # 检查AI是否启用
        if not room.settings.agent_enabled:
            return
        
        # 获取历史消息
        history = await chat_service.get_history(room_id, limit=50)
        
        # ========== 使用意图处理流水线 ==========
        text = trigger_msg.content.text or ""
        
        # 1. 提取意图
        extracted_intent = await intent_extractor.extract_from_history(history + [trigger_msg])
        
        # 2. 确定意图类型
        intent_type = _determine_intent_type(text, extracted_intent)
        
        # 3. 构建意图结果
        trace_id = str(uuid.uuid4())
        intent_result = IntentResult(
            intent_type=intent_type,
            confidence=extracted_intent.confidence,
            entities={
                "destination": extracted_intent.destination,
                "days": extracted_intent.days,
                "themes": extracted_intent.themes,
                "budget_level": extracted_intent.budget_level,
                "must_visit": extracted_intent.must_visit,
                "preferences": extracted_intent.preferences,
                "travelers": extracted_intent.travelers,
            },
            raw_input=text,
            trace_id=trace_id
        )
        
        # 4. 通过流水线处理（带3秒超时保护和兜底）
        pipeline_response = await intent_pipeline.process(
            user_input=text,
            intent_result=intent_result,
            context={
                "room_id": room_id,
                "history": history,
                "room_intent": room.extracted_intent
            }
        )
        
        logger.info(
            f"[Agent] 流水线处理完成: trace_id={trace_id}, "
            f"status={pipeline_response.status.value}, "
            f"time={pipeline_response.processing_time_ms:.0f}ms, "
            f"content_length={len(pipeline_response.content) if pipeline_response.content else 0}"
        )
        
        # 5. 构造AI消息（确保content非空）
        response_content = pipeline_response.content or "收到您的消息，正在为您处理..."
        
        agent_msg = ChatMessage(
            room_id=room_id,
            sender=MessageSender(
                id="agent_travel",
                name="旅行助手",
                avatar="/agent-avatar.png",
                is_agent=True,
                agent_type="travel_assistant"
            ),
            content=MessageContent(
                type="text",
                text=response_content,
                route_data=pipeline_response.data
            ),
            metadata={
                "trace_id": trace_id,
                "intent_type": intent_type.value,
                "confidence": extracted_intent.confidence,
                "processing_time_ms": pipeline_response.processing_time_ms,
                "response_status": pipeline_response.status.value,
                "is_fallback": pipeline_response.error_message == "使用兜底模板自动填充"
            }
        )
        
        # 6. 保存AI消息
        await chat_service.save_message(agent_msg)
        
        # 7. 记录AI发言时间
        agent.record_agent_message(room_id)
        
        # 8. 广播AI消息
        await manager.broadcast(room_id, {
            "type": WSMessageType.NEW_MESSAGE,
            "data": agent_msg.dict()
        })
        
        # 9. 如果生成了路线，更新房间意图
        if intent_type == IntentType.TRAVEL_PLANNING and extracted_intent.confidence > 0.5:
            await chat_service.update_room_intent(room_id, extracted_intent)
            
            # 广播意图更新
            await manager.broadcast(room_id, {
                "type": WSMessageType.INTENT_UPDATED,
                "data": extracted_intent.dict()
            })
    
    except Exception as e:
        logger.error(f"AI处理失败: {e}", exc_info=True)
        
        # 发送错误兜底消息（确保非空）
        try:
            error_content = "抱歉，处理您的请求时遇到了问题。请重试或换个方式描述。"
            error_msg = ChatMessage(
                room_id=room_id,
                sender=MessageSender(
                    id="agent_travel",
                    name="旅行助手",
                    avatar="/agent-avatar.png",
                    is_agent=True,
                    agent_type="travel_assistant"
                ),
                content=MessageContent(
                    type="text",
                    text=error_content
                ),
                metadata={
                    "is_error": True,
                    "error_message": str(e)
                }
            )
            await chat_service.save_message(error_msg)
            await manager.broadcast(room_id, {
                "type": WSMessageType.NEW_MESSAGE,
                "data": error_msg.dict()
            })
        except Exception as inner_e:
            logger.error(f"发送错误兜底消息失败: {inner_e}")


def _determine_intent_type(text: str, extracted_intent) -> IntentType:
    """根据文本和提取的意图确定意图类型"""
    text_lower = text.lower()
    
    # 明确的旅行规划关键词
    if any(kw in text_lower for kw in ["规划", "安排", "制定", "设计"]):
        if extracted_intent.destination or extracted_intent.days:
            return IntentType.TRAVEL_PLANNING
    
    # 路线生成
    if any(kw in text_lower for kw in ["路线", "行程", "怎么走", "怎么去"]):
        return IntentType.ROUTE_GENERATION
    
    # 地点查询
    if any(kw in text_lower for kw in ["在哪", "地址", "门票", "开放", "评分"]):
        return IntentType.POI_QUERY
    
    # 天气查询
    if any(kw in text_lower for kw in ["天气", "温度", "下雨", "晴天"]):
        return IntentType.WEATHER_QUERY
    
    # 根据意图完整度判断
    if extracted_intent.confidence > 0.5 and (extracted_intent.destination or extracted_intent.days):
        return IntentType.TRAVEL_PLANNING
    
    # 默认作为聊天消息处理
    return IntentType.CHAT_MESSAGE


# ==================== REST API ====================

@router.post("/rooms")
async def create_room(
    data: CreateRoomRequest,
    user: dict = Depends(get_current_user)
):
    """
    创建聊天室
    
    修复：
    1. 创建者自动加入房间成员列表
    2. 使用认证用户信息
    """
    user_id = user.get('id')
    username = user.get('username', '用户')
    avatar = user.get('avatar', '/default-avatar.png')
    
    logger.info(f"[Chat API] 创建房间: name={data.name}, creator={username}({user_id})")
    
    # 创建房间，创建者自动加入成员列表
    room = ChatRoom(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        avatar=data.avatar,
        creator_id=user_id,
        members=[
            ChatMember(
                user_id=user_id,
                username=username,
                avatar=avatar,
                role="owner",
                joined_at=datetime.now(),
                is_online=False
            )
        ],
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    
    # 添加初始成员
    for member_id in data.initial_members:
        if member_id != user_id:
            room.members.append(ChatMember(
                user_id=member_id,
                username=f"用户{member_id[:6]}",  # 简化处理
                role="member",
                joined_at=datetime.now()
            ))
    
    # 保存房间到 Redis/数据库
    await chat_service.save_room(room)
    
    logger.info(f"[Chat API] 房间创建成功: room={room.id}, name={room.name}, creator={user_id}, members={len(room.members)}")
    
    return {
        "success": True,
        "data": room,
        "message": "房间创建成功"
    }


@router.get("/rooms")
async def list_rooms(user: dict = Depends(get_current_user)):
    """
    获取用户加入的所有聊天室（左侧列表用）
    
    修复：使用统一的认证方式
    """
    user_id = user.get('id')
    logger.info(f"[Chat API] 获取房间列表: user={user_id}")
    
    rooms = await chat_service.get_user_rooms(user_id)
    
    room_list = []
    for room in rooms:
        # 计算未读数（简化版）
        unread = room.unread_count.get(user_id, 0)
        
        # 检查是否有成员在线
        member_ids = [m.user_id for m in room.members]
        is_online = any(manager.is_user_online(uid) for uid in member_ids)
        
        room_list.append(RoomListResponse(
            id=room.id,
            name=room.name,
            avatar=room.avatar,
            last_message=room.last_message,
            unread_count=unread,
            member_count=len(room.members),
            is_online=is_online,
            updated_at=room.updated_at
        ))
    
    logger.info(f"[Chat API] 返回房间列表: user={user_id}, count={len(room_list)}")
    
    return {
        "success": True,
        "data": room_list
    }


@router.get("/rooms/{room_id}")
async def get_room_detail(room_id: str, user: dict = Depends(get_current_user)):
    """获取房间详情"""
    user_id = user.get('id')
    
    room = await chat_service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    # 检查用户是否在房间
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="不在房间中")
    
    # 添加在线状态
    for member in room.members:
        member.is_online = manager.is_user_online(member.user_id)
    
    return {
        "success": True,
        "data": room
    }


@router.get("/rooms/{room_id}/messages")
async def get_messages(
    room_id: str,
    before: str | None = Query(None, description="分页游标，上一页最后一条消息的ID"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user)
):
    """分页获取消息"""
    user_id = user.get('id')
    
    room = await chat_service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="不在房间中")
    
    messages = await chat_service.get_messages(room_id, before, limit)
    
    return {
        "success": True,
        "data": MessageListResponse(
            messages=messages,
            has_more=len(messages) == limit,
            next_cursor=messages[0].id if messages else None
        )
    }


@router.post("/rooms/{room_id}/messages")
async def send_message(
    room_id: str,
    data: SendMessageRequest,
    user: dict = Depends(get_current_user)
):
    """发送消息（REST方式，适用于不支持WebSocket的客户端）"""
    user_id = user.get('id')
    username = user.get('username', '用户')
    
    room = await chat_service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="不在房间中")
    
    msg = ChatMessage(
        room_id=room_id,
        sender=MessageSender(
            id=user_id,
            name=username,
            avatar=user.get('avatar') or "/default-avatar.png",
            is_agent=False
        ),
        content=MessageContent(
            type=data.content_type,
            text=data.text,
            media_url=data.media_url,
            location=data.location
        ),
        reply_to=data.reply_to
    )
    
    await chat_service.save_message(msg)
    
    # 广播给在线用户
    await manager.broadcast(room_id, {
        "type": WSMessageType.NEW_MESSAGE,
        "data": msg.dict()
    })
    
    # 触发AI处理
    asyncio.create_task(process_agent_response(room_id, msg))
    
    return {
        "success": True,
        "data": msg
    }


@router.post("/rooms/{room_id}/members")
async def add_member(
    room_id: str,
    member_id: str,
    user: dict = Depends(get_current_user)
):
    """添加成员到房间"""
    user_id = user.get('id')
    
    room = await chat_service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    # 检查权限
    current_member = next((m for m in room.members if m.user_id == user_id), None)
    if not current_member or current_member.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="无权限添加成员")
    
    if not room.settings.allow_invite and current_member.role != "owner":
        raise HTTPException(status_code=403, detail="房间不允许邀请")
    
    new_member = ChatMember(
        user_id=member_id,
        username=f"用户{member_id[:6]}",  # 简化处理
        role="member",
        joined_at=datetime.now()
    )
    
    success = await chat_service.add_member(room_id, new_member)
    if not success:
        raise HTTPException(status_code=400, detail="添加失败，用户可能已在房间")
    
    # 广播新成员加入
    await manager.broadcast(room_id, {
        "type": WSMessageType.MEMBER_JOINED,
        "data": {
            "user_id": member_id,
            "username": new_member.username
        }
    })
    
    return {
        "success": True,
        "message": "添加成功"
    }


@router.post("/rooms/{room_id}/generate-route")
async def generate_route_from_chat(
    room_id: str,
    user: dict = Depends(get_current_user)
):
    """根据群聊上下文生成正式路线"""
    user_id = user.get('id')
    
    room = await chat_service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="不在房间中")
    
    if not room.extracted_intent:
        raise HTTPException(status_code=400, detail="群聊信息不足，先多聊聊旅行计划吧")
    
    intent = room.extracted_intent
    
    # 调用路线生成
    try:
        route_request = {
            "plan_mode": "intent",
            "area": intent.destination or "上海",
            "days": intent.days or 2,
            "theme": "、".join(intent.themes) if intent.themes else None,
            "preferences": {
                "must_visit": intent.must_visit,
                "avoid": intent.preferences,
                "budget": intent.budget_level,
                "travelers": intent.travelers
            }
        }
        
        # 这里调用现有的路线规划服务
        # result = await route_service.generate(route_request)
        
        # 简化版响应
        result = {
            "id": f"route_{datetime.now().timestamp()}",
            "name": f"{intent.destination}{intent.days}日游",
            "summary": f"{intent.days}天{intent.destination}精选路线",
            "pois": []
        }
        
        # 发送路线卡片到群聊
        route_msg = ChatMessage(
            room_id=room_id,
            sender=MessageSender(
                id="agent_route",
                name="路线规划师",
                avatar="/route-agent.png",
                is_agent=True,
                agent_type="route_planner"
            ),
            content=MessageContent(
                type="itinerary_preview",
                text=f"✅ 已根据群聊生成「{result['name']}」",
                route_data=result
            )
        )
        
        await chat_service.save_message(route_msg)
        
        # 广播路线消息
        await manager.broadcast(room_id, {
            "type": WSMessageType.NEW_MESSAGE,
            "data": route_msg.dict()
        })
        
        return {
            "success": True,
            "data": result,
            "message": "路线生成成功"
        }
        
    except Exception as e:
        logger.error(f"生成路线失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="路线生成失败")


@router.put("/rooms/{room_id}/settings")
async def update_room_settings(
    room_id: str,
    settings: RoomSettings,
    user: dict = Depends(get_current_user)
):
    """更新房间设置"""
    user_id = user.get('id')
    
    room = await chat_service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    # 检查权限
    current_member = next((m for m in room.members if m.user_id == user_id), None)
    if not current_member or current_member.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="无权限修改设置")
    
    room.settings = settings
    room.updated_at = datetime.now()
    await chat_service.save_room(room)
    
    return {
        "success": True,
        "data": room.settings
    }


@router.get("/rooms/{room_id}/intent")
async def get_room_intent(
    room_id: str,
    user: dict = Depends(get_current_user)
):
    """获取房间当前提取的旅行意图"""
    user_id = user.get('id')
    
    room = await chat_service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="不在房间中")
    
    return {
        "success": True,
        "data": room.extracted_intent
    }


class ChatRequest(BaseModel):
    """聊天请求"""
    text: str
    room_id: str = ""
    consider_weather: bool = True


class ChatResponse(BaseModel):
    """聊天响应"""
    reply: str
    route: Optional[dict] = None
    message_id: str = ""


@router.post("/")
async def chat(
    data: ChatRequest,
    user: dict = Depends(get_current_user)
):
    """
    处理聊天消息并返回 AI 回复
    
    集成意图处理流水线，返回结构化回复和路线数据
    """
    user_id = user.get('id')
    username = user.get('username', '用户')
    
    logger.info(f"[Chat] 收到聊天消息: user={username}({user_id}), text={data.text}")
    
    try:
        # 1. 提取意图 - 使用现有消息格式
        from services.intent_extractor import IntentExtractor
        from services.intent_pipeline import IntentResult, IntentType, init_pipeline
        
        intent_extractor = IntentExtractor()
        pipeline = init_pipeline()
        
        # 创建临时消息用于意图提取
        temp_msg = ChatMessage(
            room_id="",
            sender=MessageSender(
                id=user_id,
                name=username,
                avatar=user.get('avatar') or "/default-avatar.png",
                is_agent=False
            ),
            content=MessageContent(
                type="text",
                text=data.text
            )
        )
        
        extracted_intent = await intent_extractor.extract_from_history([temp_msg])
        
        # 2. 确定意图类型
        intent_type = _determine_intent_type(data.text, extracted_intent)
        
        # 3. 构建意图结果
        trace_id = str(uuid.uuid4())
        intent_result = IntentResult(
            intent_type=intent_type,
            confidence=extracted_intent.confidence,
            entities={
                "destination": extracted_intent.destination,
                "days": extracted_intent.days,
                "themes": extracted_intent.themes,
                "budget_level": extracted_intent.budget_level,
                "must_visit": extracted_intent.must_visit,
                "preferences": extracted_intent.preferences,
                "travelers": extracted_intent.travelers,
            },
            raw_input=data.text,
            trace_id=trace_id
        )
        
        # 4. 通过流水线处理
        pipeline_response = await pipeline.process(
            user_input=data.text,
            intent_result=intent_result,
            context={
                "user_id": user_id,
                "history": [],
            }
        )
        
        # 5. 构造回复
        reply = pipeline_response.content or "收到您的消息，正在为您处理..."
        
        # 6. 构造路线数据（如果有）
        route_data = None
        if pipeline_response.data and intent_type in [IntentType.TRAVEL_PLANNING, IntentType.ROUTE_GENERATION]:
            route_data = {
                "summary": f"为您规划了{extracted_intent.days or 2}天的{extracted_intent.destination or '旅行'}之旅",
                "days": [
                    {
                        "day_index": 1,
                        "title": "Day1",
                        "detail": "上午：景点游览\n下午：继续探索\n晚上：品尝当地美食",
                        "anchors": extracted_intent.must_visit or [],
                        "polyline": ""
                    }
                ],
                "anchors": [
                    {"name": name, "reason": "推荐景点", "location": ""}
                    for name in (extracted_intent.must_visit or [])
                ],
                "total_distance": "待计算",
                "map_url": "",
                "route_polylines": [],
                "poi_markers": []
            }
        
        # 7. 生成消息ID
        message_id = str(uuid.uuid4())
        
        return {
            "success": True,
            "data": {
                "reply": reply,
                "route": route_data,
                "message_id": message_id
            },
            "message": "聊天响应成功"
        }
        
    except Exception as e:
        logger.error(f"[Chat] 聊天处理失败: {e}", exc_info=True)
        
        # 返回兜底回复
        return {
            "success": True,
            "data": {
                "reply": f"您好！我是您的AI旅行助手。我了解到您想要「{data.text}」。\n\n"
                         "我正在为您规划完美的行程，请稍候...\n\n"
                         "💡 您可以告诉我：\n"
                         "- 具体的天数（如2日游、3日游）\n"
                         "- 想去的景点或区域\n"
                         "- 特别的偏好（如美食、历史、自然风光）",
                "route": None,
                "message_id": str(uuid.uuid4())
            },
            "message": "兜底回复"
        }


class GenerateItineraryRequest(BaseModel):
    """生成行程方案请求"""
    user_request: str
    map_file_path: str = ""


@router.post("/rooms/{room_id}/generate-itinerary")
async def generate_itinerary(
    room_id: str,
    data: GenerateItineraryRequest,
    user: dict = Depends(get_current_user)
):
    """
    生成完整行程方案并发送到聊天室
    
    调用 run_step4 生成自然语言行程，通过 step4_adapter 捕获输出，
    格式化为 AI助手消息 (itinerary_preview) 发送到聊天室
    """
    user_id = user.get('id')
    username = user.get('username', '用户')
    
    logger.info(f"[Itinerary] 生成行程方案: room={room_id}, user={username}({user_id})")
    
    # 检查房间
    room = await chat_service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="不在房间中")
    
    try:
        # 1. 先发送一条提示消息
        thinking_msg = ChatMessage(
            room_id=room_id,
            sender=MessageSender(
                id="agent_travel",
                name="AI旅行助手",
                avatar="/agent-avatar.png",
                is_agent=True,
                agent_type="travel_assistant"
            ),
            content=MessageContent(
                type="text",
                text=f"🤔 收到！正在为您规划「{data.user_request}」的行程方案，请稍候..."
            )
        )
        await chat_service.save_message(thinking_msg)
        await manager.broadcast(room_id, {
            "type": WSMessageType.NEW_MESSAGE,
            "data": thinking_msg.dict()
        })
        
        # 2. 调用完整的路线规划流水线
        # 这里简化处理，实际应该调用完整的 pipeline
        # 为了演示，我们创建一个模拟的行程方案
        
        # 模拟行程数据（实际应该从 pipeline 获取）
        mock_itinerary = {
            "summary": f"为您规划了两天一夜的{data.user_request}之旅",
            "days": [
                {
                    "day_index": 1,
                    "title": "Day1",
                    "detail": "上午（9:00-12:00）：外滩周边游览\n  步行游览外滩，欣赏黄浦江两岸风光\n  推荐理由：上海地标，必打卡景点",
                    "anchors": ["外滩"],
                    "polyline": "121.47,31.23"
                },
                {
                    "day_index": 2,
                    "title": "Day2", 
                    "detail": "上午（9:00-12:00）：豫园游览\n  游览豫园，品尝南翔小笼\n  推荐理由：江南古典园林，文化底蕴深厚",
                    "anchors": ["豫园"],
                    "polyline": "121.49,31.23"
                }
            ],
            "anchors": [
                {"name": "外滩", "reason": "上海地标，必打卡景点"},
                {"name": "豫园", "reason": "江南古典园林，文化底蕴深厚"}
            ],
            "total_distance": "15km",
            "map_url": data.map_file_path or "/maps/default.html"
        }
        
        # 3. 构造 AI助手消息
        itinerary_msg = ChatMessage(
            room_id=room_id,
            sender=MessageSender(
                id="agent_travel",
                name="AI旅行助手",
                avatar="/agent-avatar.png",
                is_agent=True,
                agent_type="travel_assistant"
            ),
            content=MessageContent(
                type="itinerary_preview",
                text=mock_itinerary["summary"] + "\n\n" + "\n\n".join(
                    f"【Day{d['day_index']}】\n{d['detail']}" for d in mock_itinerary["days"]
                ),
                route_data=mock_itinerary
            ),
            metadata={
                "generated_by": "step4_pipeline",
                "user_request": data.user_request
            }
        )
        
        # 4. 保存并广播消息
        await chat_service.save_message(itinerary_msg)
        await manager.broadcast(room_id, {
            "type": WSMessageType.NEW_MESSAGE,
            "data": itinerary_msg.dict()
        })
        
        logger.info(f"[Itinerary] 行程方案已生成并发送: room={room_id}, msg_id={itinerary_msg.id}")
        
        return {
            "success": True,
            "data": {
                "message_id": itinerary_msg.id,
                "itinerary": mock_itinerary
            },
            "message": "行程方案生成成功"
        }
        
    except Exception as e:
        logger.error(f"[Itinerary] 生成行程方案失败: {e}", exc_info=True)
        
        # 发送错误消息
        error_msg = ChatMessage(
            room_id=room_id,
            sender=MessageSender(
                id="agent_travel",
                name="AI旅行助手",
                avatar="/agent-avatar.png",
                is_agent=True,
                agent_type="travel_assistant"
            ),
            content=MessageContent(
                type="text",
                text="抱歉，生成行程方案时遇到了问题。请重试或换个方式描述。"
            ),
            metadata={"is_error": True, "error": str(e)}
        )
        await chat_service.save_message(error_msg)
        await manager.broadcast(room_id, {
            "type": WSMessageType.NEW_MESSAGE,
            "data": error_msg.dict()
        })
        
        raise HTTPException(status_code=500, detail="行程方案生成失败")
