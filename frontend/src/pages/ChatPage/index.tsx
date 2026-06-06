import React, { useEffect, useRef, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, message } from 'antd';
import { PlusOutlined, MessageOutlined } from '@ant-design/icons';
import ChatRoomSidebar from '../../components/ChatRoomSidebar';
import ChatArea from '../../components/ChatArea';
import AgentPanel from '../../components/AgentPanel';
import CreateRoomModal from '../../components/CreateRoomModal';
import { useChatStore, selectCurrentRoom } from '../../store/chatStore';
import { ChatRoom, ChatMessage, TravelIntent } from '../../types/chat';
import styles from './ChatPage.module.css';

// WebSocket URL 处理
const getWebSocketUrl = () => {
  const wsUrl = import.meta.env.VITE_WS_URL;
  if (wsUrl && wsUrl !== '') {
    console.log('[Config] 使用 VITE_WS_URL:', wsUrl);
    return wsUrl;
  }
  // 使用相对路径，通过 Vite 代理
  // 注意：Vite代理会处理 /api 路径，包括 WebSocket
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${window.location.host}`;
  console.log('[Config] 使用相对路径 WebSocket:', url);
  return url;
};

const WS_URL = getWebSocketUrl();
// 使用相对路径的API（通过Vite代理）
const API_URL = '';  // 空字符串表示使用相对路径

console.log('[Config] WebSocket URL:', WS_URL);
console.log('[Config] API URL:', API_URL || '(使用相对路径)');

const ChatPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // 使用 chatStore
  const {
    rooms,
    setRooms,
    addRoom,
    currentRoomId,
    setCurrentRoomId,
    switchRoom,
    messages,
    setMessages,
    addMessage,
    updateMessage,
    inputText,
    setInputText,
    isTyping,
    setIsTyping,
    showAgentPanel,
    setShowAgentPanel,
    extractedIntent,
    setExtractedIntent,
    wsConnected,
    setWsConnected,
    createModalVisible,
    setCreateModalVisible,
    error,
    setError,
  } = useChatStore();

  const currentRoom = selectCurrentRoom(useChatStore.getState());

  // 加载房间列表
  const fetchRooms = useCallback(async () => {
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_URL}/api/chat/rooms`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.success) {
        setRooms(data.data || []);
        return data.data || [];
      }
    } catch (err) {
      console.error('[API] 获取房间列表失败:', err);
    }
    return [];
  }, [setRooms]);

  // 初始化：加载房间列表
  useEffect(() => {
    fetchRooms();
  }, [fetchRooms]);

  // 处理 URL 中的 roomId 参数
  useEffect(() => {
    const roomId = searchParams.get('roomId');
    if (roomId && rooms.length > 0) {
      const roomExists = rooms.some((r) => r.id === roomId);
      if (roomExists && roomId !== currentRoomId) {
        handleSelectRoom(roomId);
      }
    }
  }, [searchParams, rooms, currentRoomId]);

  // 连接 WebSocket
  useEffect(() => {
    if (!currentRoomId) {
      console.log('[WebSocket] 未选择房间，跳过连接');
      return;
    }

    const token = localStorage.getItem('token');
    if (!token) {
      console.error('[WebSocket] 未找到 token，无法连接');
      setError('请先登录');
      return;
    }

    // 构建 WebSocket URL
    // 注意：后端路由是 /api/chat/ws/room/{room_id}
    const wsUrl = `${WS_URL}/api/chat/ws/room/${currentRoomId}?token=${encodeURIComponent(token)}`;
    console.log('[WebSocket] 正在连接:', wsUrl);

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WebSocket] 连接成功, room:', currentRoomId);
      setWsConnected(true);
      setError(null);
    };

    ws.onmessage = (event) => {
      console.log('[WebSocket] 收到消息:', event.data);
      try {
        const data = JSON.parse(event.data);
        console.log('[WebSocket] 解析后数据:', data);

        switch (data.type) {
          case 'new_message':
            addMessage(data.data);
            // AI消息如果是路线卡片，自动展开右侧面板
            if (
              data.data.sender.is_agent &&
              data.data.content.type === 'route_card'
            ) {
              setShowAgentPanel(true);
            }
            // 提取意图信息
            if (data.data.sender.is_agent && data.data.content.metadata?.intent) {
              setExtractedIntent(data.data.content.metadata.intent);
            }
            break;
          case 'typing':
          case 'typing_indicator':
            setIsTyping(true);
            setTimeout(() => setIsTyping(false), 3000);
            break;
          case 'member_online':
            console.log('[WebSocket] 成员上线:', data.data);
            break;
          case 'member_offline':
            console.log('[WebSocket] 成员离线:', data.data);
            break;
          case 'member_joined':
            console.log('[WebSocket] 新成员加入:', data.data);
            break;
          case 'member_left':
            console.log('[WebSocket] 成员离开:', data.data);
            break;
          case 'history':
            setMessages(data.data || []);
            break;
          case 'intent_update':
          case 'intent_updated':
            setExtractedIntent(data.data);
            break;
          case 'error':
            console.error('[WebSocket] 服务器错误:', data.data);
            message.error(data.data?.message || '服务器错误');
            break;
          default:
            console.log('[WebSocket] 未知消息类型:', data.type);
        }
      } catch (err) {
        console.error('[WebSocket] 解析消息失败:', err);
      }
    };

    ws.onerror = (error) => {
      console.error('[WebSocket] 连接错误:', error);
      setWsConnected(false);
      setError('连接失败，请检查后端服务');
    };

    ws.onclose = (event) => {
      console.log('[WebSocket] 连接关闭, code:', event.code, 'reason:', event.reason);
      setWsConnected(false);
      
      // 根据关闭代码给出提示
      if (event.code === 4001) {
        setError('认证失败，请重新登录');
      } else if (event.code === 4004) {
        setError('房间不存在');
      } else if (event.code === 4003) {
        setError('您不在该房间中');
      } else if (event.code !== 1000) {
        // 非正常关闭，尝试重连
        console.log('[WebSocket] 非正常关闭，3秒后尝试重连...');
        setTimeout(() => {
          if (currentRoomId) {
            // 触发重连
            setWsConnected(false);
          }
        }, 3000);
      }
    };

    return () => {
      console.log('[WebSocket] 清理连接');
      ws.close(1000, '组件卸载');
      wsRef.current = null;
      setWsConnected(false);
    };
  }, [currentRoomId, addMessage, setShowAgentPanel, setExtractedIntent, setIsTyping, setMessages, setWsConnected, setError]);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 选择房间
  const handleSelectRoom = (roomId: string) => {
    if (roomId === currentRoomId) return;
    switchRoom(roomId);
    setCurrentRoomId(roomId);
  };

  // 通过 REST API 发送消息（备用方案）
  const sendMessageViaRest = async (text: string, tempId: string) => {
    console.log('[sendMessage] 使用 REST API 发送消息');
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_URL}/api/chat/rooms/${currentRoomId}/messages`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text: text,
          content_type: 'text',
        }),
      });

      if (res.ok) {
        console.log('[sendMessage] REST API 发送成功');
        const data = await res.json();
        if (data.success && data.data) {
          updateMessage(tempId, data.data);
        }
      } else {
        console.error('[sendMessage] REST API 发送失败:', res.status);
        throw new Error('REST API 发送失败');
      }
    } catch (err) {
      console.error('[sendMessage] REST API 发送错误:', err);
      updateMessage(tempId, {
        ...messages.find((m) => m.id === tempId),
        content: { type: 'text', text: text + ' (发送失败)' },
      } as ChatMessage);
    }
  };

  // 发送消息
  const handleSendMessage = () => {
    const textToSend = inputText.trim();

    if (!textToSend || !currentRoomId) {
      console.log('[sendMessage] 输入为空或未选择房间');
      return;
    }

    console.log('[sendMessage] 发送消息:', textToSend);
    console.log('[sendMessage] WebSocket 状态:', wsRef.current?.readyState);
    console.log('[sendMessage] WebSocket OPEN 状态:', WebSocket.OPEN);

    // 创建本地消息对象（乐观更新）
    const currentUser = JSON.parse(localStorage.getItem('user') || '{}');
    const tempId = `temp-${Date.now()}`;
    const newMessage: ChatMessage = {
      id: tempId,
      room_id: currentRoomId,
      sender: {
        id: currentUser.id || 'unknown',
        name: currentUser.name || '我',
        avatar: currentUser.avatar || '',
        is_agent: false,
      },
      content: {
        type: 'text',
        text: textToSend,
      },
      timestamp: new Date().toISOString(),
    };

    // 立即添加到消息列表（乐观更新）
    addMessage(newMessage);

    // 清空输入框
    setInputText('');

    // 尝试通过 WebSocket 发送
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        const messageData = JSON.stringify({
          type: 'message',
          text: textToSend,
          content_type: 'text',
        });
        console.log('[sendMessage] WebSocket 发送数据:', messageData);
        wsRef.current.send(messageData);
        console.log('[sendMessage] WebSocket 发送成功');
      } catch (err) {
        console.error('[sendMessage] WebSocket 发送失败:', err);
        sendMessageViaRest(textToSend, tempId);
      }
    } else {
      console.warn('[sendMessage] WebSocket 未连接，使用 REST API');
      console.warn('[sendMessage] readyState:', wsRef.current?.readyState);
      sendMessageViaRest(textToSend, tempId);
    }
  };

  // 生成路线
  const handleGenerateRoute = async () => {
    if (!currentRoomId) return;

    try {
      const token = localStorage.getItem('token');
      const res = await fetch(
        `${API_URL}/api/chat/rooms/${currentRoomId}/generate-route`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            intent: extractedIntent,
          }),
        }
      );
      const data = await res.json();
      if (data.success) {
        message.success('路线生成中，请稍候...');
        setShowAgentPanel(true);
      } else {
        message.error(data.message || '路线生成失败');
      }
    } catch (err) {
      console.error('Generate route error:', err);
      message.error('路线生成失败，请重试');
    }
  };

  // 创建房间
  const handleCreateRoom = () => {
    setCreateModalVisible(true);
  };

  const handleCreateSuccess = (newRoom: ChatRoom) => {
    addRoom(newRoom);
    handleSelectRoom(newRoom.id);
    setCreateModalVisible(false);
  };

  // 关闭创建弹窗
  const handleCreateCancel = () => {
    setCreateModalVisible(false);
  };

  return (
    <div className={styles.chatPage}>
      {/* 左侧：房间列表 */}
      <ChatRoomSidebar
        rooms={rooms}
        currentRoom={currentRoomId}
        onSelect={handleSelectRoom}
        onCreateRoom={handleCreateRoom}
      />

      {/* 新建群聊弹窗 */}
      <CreateRoomModal
        visible={createModalVisible}
        onCancel={handleCreateCancel}
        onSuccess={handleCreateSuccess}
      />

      {/* 中间：聊天区域 */}
      {currentRoomId ? (
        <>
          <ChatArea
            messages={messages}
            inputText={inputText}
            setInputText={setInputText}
            onSend={handleSendMessage}
            isTyping={isTyping}
            messagesEndRef={messagesEndRef}
            roomName={currentRoom?.name}
            wsConnected={wsConnected}
          />

          {/* 右侧：AI助手面板 */}
          <AgentPanel
            visible={showAgentPanel}
            roomId={currentRoomId}
            messages={messages}
            extractedIntent={extractedIntent}
            onGenerateRoute={handleGenerateRoute}
            onGenerateItinerary={handleGenerateRoute}
            onClose={() => setShowAgentPanel(false)}
          />
        </>
      ) : (
        <div className={styles.emptyState}>
          <div className={styles.emptyContent}>
            <span className={styles.emptyIcon}>💬</span>
            <p>选择一个群聊开始旅行规划</p>
            <p className={styles.emptySubtext}>
              和朋友们一起讨论，AI助手会帮你们规划完美路线
            </p>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleCreateRoom}
              size="large"
            >
              创建新群聊
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatPage;
