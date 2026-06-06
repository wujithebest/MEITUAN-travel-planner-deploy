import React, { useRef, useState } from 'react';
import { Button, Input, Tooltip } from 'antd';
import {
  SendOutlined,
  PictureOutlined,
  EnvironmentOutlined,
  SmileOutlined,
  AudioOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import MessageBubble from '../MessageBubble';
import { ChatMessage } from '../../types/chat';
import styles from './ChatArea.module.css';

const { TextArea } = Input;

interface ChatAreaProps {
  messages: ChatMessage[];
  inputText: string;
  setInputText: (text: string) => void;
  onSend: () => void;
  isTyping: boolean;
  messagesEndRef: React.RefObject<HTMLDivElement>;
  roomName?: string;
  wsConnected?: boolean;
}

const ChatArea: React.FC<ChatAreaProps> = ({
  messages,
  inputText,
  setInputText,
  onSend,
  isTyping,
  messagesEndRef,
  roomName = '聊天室',
  wsConnected = false,
}) => {
  const [showEmoji, setShowEmoji] = useState(false);
  const inputRef = useRef<any>(null);

  const handleSend = () => {
    console.log('[ChatArea] handleSend 被调用');
    console.log('[ChatArea] inputText:', JSON.stringify(inputText));
    console.log('[ChatArea] inputText.trim():', JSON.stringify(inputText.trim()));
    
    if (!inputText.trim()) {
      console.log('[ChatArea] 输入为空，不发送');
      return;
    }
    
    console.log('[ChatArea] 调用 onSend');
    onSend();
    console.log('[ChatArea] onSend 调用完成');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const emojis = ['😊', '😂', '🥰', '😍', '🤔', '👍', '❤️', '🎉', '✈️', '🏖️', '🌍', '📍'];

  return (
    <div className={styles.chatArea}>
      {/* 头部 */}
      <div className={styles.header}>
        <div className={styles.roomInfo}>
          <h2 className={styles.roomName}>{roomName}</h2>
          <span className={`${styles.connectionStatus} ${wsConnected ? styles.connected : styles.disconnected}`}>
            {wsConnected ? '🟢 已连接' : '🔴 未连接'}
          </span>
        </div>
      </div>

      {/* 消息列表 */}
      <div className={styles.messageList}>
        {messages.length === 0 ? (
          <div className={styles.emptyMessages}>
            <span className={styles.emptyIcon}>💬</span>
            <p>开始聊天，规划你的旅行吧！</p>
            <p className={styles.hint}>@旅行助手 获取AI建议</p>
          </div>
        ) : (
          messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))
        )}

        {/* AI正在输入 */}
        {isTyping && (
          <div className={styles.typingIndicator}>
            <div className={styles.typingAvatar}>🤖</div>
            <div className={styles.typingBubble}>
              <span>旅行助手正在输入</span>
              <div className={styles.dots}>
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 输入框 */}
      <div className={styles.inputArea}>
        <div className={styles.toolbar}>
          <Tooltip title="发送图片">
            <Button icon={<PictureOutlined />} type="text" size="small" />
          </Tooltip>
          <Tooltip title="发送位置">
            <Button icon={<EnvironmentOutlined />} type="text" size="small" />
          </Tooltip>
          <Tooltip title="语音输入">
            <Button icon={<AudioOutlined />} type="text" size="small" />
          </Tooltip>
          <div className={styles.emojiBtn}>
            <Button
              icon={<SmileOutlined />}
              type="text"
              size="small"
              onClick={() => setShowEmoji(!showEmoji)}
            />
            {showEmoji && (
              <div className={styles.emojiPanel}>
                {emojis.map((emoji) => (
                  <span
                    key={emoji}
                    className={styles.emojiItem}
                    onClick={() => {
                      setInputText(inputText + emoji);
                      setShowEmoji(false);
                      inputRef.current?.focus();
                    }}
                  >
                    {emoji}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className={styles.inputRow}>
          <TextArea
            ref={inputRef}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="@旅行助手 问问怎么玩，或直接讨论..."
            autoSize={{ minRows: 1, maxRows: 5 }}
            onKeyDown={handleKeyDown}
            className={styles.textInput}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={!inputText.trim()}
            className={styles.sendBtn}
          >
            发送
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ChatArea;
