"""
协作路由
POST /api/collab/room - 创建房间
POST /api/collab/join - 加入房间
GET /api/collab/{room_id}/members - 获取成员
POST /api/collab/operation - 提交操作

注意：WebSocket路由需要在主应用中单独注册，因为WebSocket不支持prefix
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from models.base import ApiResponse
from models.collab import CreateRoomRequest, JoinRoomRequest, OperationRequest, WSMessage
from services.collaboration_service import get_collab_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collab", tags=["协作"])


@router.websocket("/ws/{room_id}")
async def websocket_collab(
    websocket: WebSocket,
    room_id: str,
    user_id: str = Query(..., description="用户ID")
):
    """
    WebSocket协作连接
    完整路径: /api/collab/ws/{room_id}?user_id={user_id}
    
    客户端连接后：
    - 发送操作: {"type": "operation", "data": {...}}
    - 请求同步: {"type": "sync", "data": {}}
    - 撤销操作: {"type": "undo", "data": {"operation_id": "xxx"}}
    """
    collab_service = get_collab_service()
    cm = collab_service.connection_manager

    try:
        await cm.connect(websocket, room_id, user_id)

        # 发送同步消息
        room = await collab_service.get_room(room_id)
        if room:
            sync_msg = WSMessage(
                type="sync",
                data=json.loads(json.dumps(room.model_dump(), default=str)),
                room_id=room_id,
                user_id="system"
            )
            await cm.send_personal(room_id, user_id, sync_msg)

        # 监听消息
        while True:
            raw_data = await websocket.receive_text()
            try:
                msg = json.loads(raw_data)
                msg_type = msg.get("type", "")
                data = msg.get("data", {})

                if msg_type == "operation":
                    # 处理协作操作
                    operation = await collab_service.handle_operation(
                        room_id=room_id,
                        user_id=user_id,
                        operation_data=data
                    )
                elif msg_type == "undo":
                    # 撤销操作
                    operation_id = data.get("operation_id", "")
                    await collab_service.undo_operation(room_id, user_id, operation_id)
                elif msg_type == "ping":
                    # 心跳
                    await cm.send_personal(
                        room_id, user_id,
                        WSMessage(type="pong", data={}, room_id=room_id, user_id="system")
                    )
                else:
                    logger.warning(f"未知消息类型: {msg_type}")

            except json.JSONDecodeError:
                logger.warning(f"无效的JSON消息: {raw_data[:100]}")
            except Exception as e:
                logger.error(f"处理消息异常: {str(e)}")
                error_msg = WSMessage(
                    type="error",
                    data={"message": str(e)},
                    room_id=room_id,
                    user_id="system"
                )
                await cm.send_personal(room_id, user_id, error_msg)

    except WebSocketDisconnect:
        logger.info(f"WebSocket断开: user={user_id}, room={room_id}")
    except Exception as e:
        logger.error(f"WebSocket异常: {str(e)}")
    finally:
        await cm.disconnect(room_id, user_id)


@router.post("/room", response_model=ApiResponse, summary="创建协作房间")
async def create_room(request: CreateRoomRequest, user_id: str = Query(..., description="房主用户ID")):
    """创建协作房间
    
    注意：user_id 应该通过认证中间件或前端传递
    这里使用 Query 参数是为了简化测试，生产环境应使用 JWT 认证
    """
    logger.info(f"创建房间请求: user_id={user_id}, name={request.name}, route_id={request.route_id}")
    
    try:
        if not user_id:
            logger.error("user_id 为空")
            return ApiResponse(
                success=False, data=None,
                message="user_id 不能为空", code="INVALID_PARAM"
            )
        
        collab_service = get_collab_service()
        room = await collab_service.create_room(
            name=request.name,
            owner_id=user_id,
            route_id=request.route_id
        )
        
        logger.info(f"房间创建成功: room_id={room.room_id}, owner={user_id}")
        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(room.model_dump(), default=str)),
            message="房间创建成功"
        )
    except Exception as e:
        logger.exception(f"创建房间异常: user_id={user_id}, error={str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"创建房间失败: {str(e)}", code="ERROR"
        )


@router.post("/join", response_model=ApiResponse, summary="加入协作房间")
async def join_room(request: JoinRoomRequest):
    """加入协作房间"""
    try:
        collab_service = get_collab_service()
        room = await collab_service.join_room(
            room_id=request.room_id,
            user_id=request.user_id,
            username=request.username
        )
        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(room.model_dump(), default=str)),
            message="加入房间成功"
        )
    except Exception as e:
        logger.exception(f"加入房间异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"加入房间失败: {str(e)}", code="ERROR"
        )


@router.get("/{room_id}/members", response_model=ApiResponse, summary="获取房间成员")
async def get_members(room_id: str):
    """获取房间成员列表"""
    try:
        collab_service = get_collab_service()
        members = await collab_service.get_members(room_id)
        # 添加在线状态
        online_users = collab_service.connection_manager.get_online_users(room_id)
        result = []
        for m in members:
            m_dict = m.model_dump()
            m_dict["is_online"] = m.user_id in online_users
            result.append(m_dict)

        return ApiResponse(
            success=True,
            data=result,
            message="获取成员列表成功"
        )
    except Exception as e:
        logger.exception(f"获取成员异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"获取成员失败: {str(e)}", code="ERROR"
        )


@router.post("/operation", response_model=ApiResponse, summary="提交操作")
async def submit_operation(
    request: OperationRequest,
    user_id: str = Query(..., description="操作用户ID")
):
    """提交协作操作"""
    try:
        collab_service = get_collab_service()
        operation = await collab_service.handle_operation(
            room_id=request.room_id,
            user_id=user_id,
            operation_data={
                "operation_type": request.operation_type.value,
                "target_index": request.target_index,
                "poi": request.poi.model_dump() if request.poi else None,
                "new_value": request.new_value
            }
        )
        return ApiResponse(
            success=True,
            data=json.loads(json.dumps(operation.model_dump(), default=str)),
            message="操作提交成功"
        )
    except Exception as e:
        logger.exception(f"操作提交异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"操作提交失败: {str(e)}", code="ERROR"
        )


@router.post("/{room_id}/undo", response_model=ApiResponse, summary="撤销操作")
async def undo_operation(
    room_id: str,
    operation_id: str = Query(..., description="要撤销的操作ID"),
    user_id: str = Query(..., description="操作用户ID")
):
    """撤销操作"""
    try:
        collab_service = get_collab_service()
        await collab_service.undo_operation(room_id, user_id, operation_id)
        return ApiResponse(success=True, data=None, message="撤销成功")
    except Exception as e:
        logger.exception(f"撤销操作异常: {str(e)}")
        return ApiResponse(
            success=False, data=None,
            message=f"撤销失败: {str(e)}", code="ERROR"
        )
