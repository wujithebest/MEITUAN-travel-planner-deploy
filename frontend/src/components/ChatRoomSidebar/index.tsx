import React from 'react';
import { Button, Empty } from 'antd';
import { MessageOutlined, PlusOutlined } from '@ant-design/icons';
import type { ChatRoom } from '@/types/chat';
import styles from './ChatRoomSidebar.module.css';

interface ChatRoomSidebarProps {
  rooms: ChatRoom[];
  currentRoom: string | null;
  onSelect: (roomId: string) => void;
  onCreateRoom: () => void;
}

const ChatRoomSidebar: React.FC<ChatRoomSidebarProps> = ({
  rooms,
  currentRoom,
  onSelect,
  onCreateRoom,
}) => (
  <aside className={styles.sidebar}>
    <header className={styles.header}>
      <div>
        <div className={styles.eyebrow}>TRAVEL CHAT</div>
        <h2 className={styles.title}>旅行群聊</h2>
      </div>
      <Button type="primary" shape="circle" icon={<PlusOutlined />} onClick={onCreateRoom} />
    </header>

    <div className={styles.rooms}>
      {rooms.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有群聊" />
      ) : (
        rooms.map((room) => (
          <button
            key={room.id}
            type="button"
            className={`${styles.room} ${room.id === currentRoom ? styles.active : ''}`}
            onClick={() => onSelect(room.id)}
          >
            <MessageOutlined className={styles.icon} />
            <span className={styles.roomBody}>
              <strong>{room.name}</strong>
              <span>{room.member_count} 位成员</span>
            </span>
            {room.unread_count > 0 && <span className={styles.unread}>{room.unread_count}</span>}
          </button>
        ))
      )}
    </div>
  </aside>
);

export default ChatRoomSidebar;
