/**
 * 消息列表组件 - 展示消息并处理状态显示
 */

import React from 'react';
import { Message } from '../utils/messageRenderer';

interface MessageListProps {
  messages: Message[];
  currentUserId: string;
}

export const MessageList: React.FC<MessageListProps> = ({ messages, currentUserId }) => {
  const renderMessageStatus = (message: Message) => {
    switch (message.status) {
      case 'pending':
        return <span className="message-status pending">发送中...</span>;
      case 'failed':
        return <span className="message-status failed">发送失败</span>;
      case 'confirmed':
        return null;
      default:
        return null;
    }
  };

  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  return (
    <div className="message-list">
      {messages.map((message) => (
        <div
          key={message.message_id}
          className={`message-item ${
            message.user_id === currentUserId ? 'own-message' : 'other-message'
          }`}
        >
          <div className="message-content">
            <div className="message-text">{message.content}</div>
            <div className="message-meta">
              <span className="message-time">{formatTime(message.timestamp)}</span>
              {renderMessageStatus(message)}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default MessageList;
