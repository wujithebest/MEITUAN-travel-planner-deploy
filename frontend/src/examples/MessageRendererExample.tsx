/**
 * 消息渲染层使用示例
 */

import React, { useState } from 'react';
import { useMessageRenderer } from '../hooks/useMessageRenderer';
import { MessageList } from '../components/MessageList';
import { DuplicateAlert } from '../components/DuplicateAlert';
import '../styles/messageRenderer.css';

export const MessageRendererExample: React.FC = () => {
  const [inputValue, setInputValue] = useState('');
  const [currentUserId] = useState('user1'); // 模拟当前用户ID
  const [groupId, setGroupId] = useState(''); // 模拟群聊ID
  
  const {
    messages,
    sendMessage,
    receiveMessage,
    confirmMessage,
    pendingMessages,
    showDuplicateAlert,
    clearDuplicateAlert
  } = useMessageRenderer();

  // 处理发送消息
  const handleSendMessage = () => {
    if (!inputValue.trim()) return;

    const options = groupId ? {
      group_id: groupId,
      sender_id: currentUserId
    } : {};

    const success = sendMessage(currentUserId, inputValue, options);
    
    if (success) {
      setInputValue('');
      
      // 模拟服务端ACK（实际应用中这是从WebSocket或API响应中获得的）
      setTimeout(() => {
        const pendingMsg = pendingMessages.find(msg => msg.content === inputValue);
        if (pendingMsg) {
          confirmMessage(pendingMsg.message_id);
        }
      }, 1000);
    }
  };

  // 模拟接收服务端消息
  const handleReceiveMessage = () => {
    const mockMessage = {
      message_id: `server_${Date.now()}`,
      user_id: 'user2',
      content: '这是服务端消息',
      timestamp: Date.now(),
      status: 'confirmed' as const,
      ...(groupId ? { group_id: groupId, sender_id: 'user2' } : {})
    };
    
    receiveMessage(mockMessage);
  };

  // 模拟发送重复消息（用于测试去重）
  const handleSendDuplicate = () => {
    const content = '重复消息测试';
    
    // 快速发送3条相同内容的消息
    for (let i = 0; i < 3; i++) {
      sendMessage(currentUserId, content);
    }
  };

  return (
    <div className="message-renderer-example">
      <h2>消息渲染层示例</h2>
      
      {/* 重复消息告警 */}
      <DuplicateAlert show={showDuplicateAlert} onClear={clearDuplicateAlert} />
      
      {/* 控制面板 */}
      <div className="control-panel">
        <div className="input-group">
          <label>
            当前用户ID: <strong>{currentUserId}</strong>
          </label>
        </div>
        
        <div className="input-group">
          <label>
            群聊ID (可选):
            <input
              type="text"
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              placeholder="输入群聊ID或留空"
            />
          </label>
        </div>
        
        <div className="input-group">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
            placeholder="输入消息内容..."
          />
          <button onClick={handleSendMessage}>发送消息</button>
        </div>
        
        <div className="button-group">
          <button onClick={handleReceiveMessage}>模拟接收服务端消息</button>
          <button onClick={handleSendDuplicate}>测试重复消息去重</button>
        </div>
      </div>
      
      {/* 状态信息 */}
      <div className="status-info">
        <p>总消息数: {messages.length}</p>
        <p>待确认消息数: {pendingMessages.length}</p>
        <p>当前模式: {groupId ? '群聊' : '私聊'}</p>
      </div>
      
      {/* 消息列表 */}
      <div className="message-container">
        <h3>消息列表</h3>
        <MessageList messages={messages} currentUserId={currentUserId} />
      </div>
      
      {/* 使用说明 */}
      <div className="usage-guide">
        <h3>功能说明</h3>
        <ul>
          <li><strong>消息去重:</strong> 5秒内相同内容+相同发送者的消息会被自动过滤</li>
          <li><strong>状态同步:</strong> 消息发送后显示"发送中..."，收到ACK后状态更新</li>
          <li><strong>群聊处理:</strong> 输入群聊ID后，消息会基于group_id + sender_id进行去重</li>
          <li><strong>异常检测:</strong> 连续3条相同内容消息会触发告警提示</li>
        </ul>
      </div>
    </div>
  );
};

export default MessageRendererExample;
