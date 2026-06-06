import React, { useState } from 'react';
import { Modal, Input, message } from 'antd';
import { ChatRoom } from '../../types/chat';

const API_URL = '';  // 使用相对路径（通过Vite代理）

interface CreateRoomModalProps {
  visible: boolean;
  onCancel: () => void;
  onSuccess: (room: ChatRoom) => void;
}

const CreateRoomModal: React.FC<CreateRoomModalProps> = ({
  visible,
  onCancel,
  onSuccess,
}) => {
  const [roomName, setRoomName] = useState('');
  const [loading, setLoading] = useState(false);

  const handleOk = async () => {
    if (!roomName.trim()) {
      message.warning('请输入群聊名称');
      return;
    }

    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_URL}/api/chat/rooms`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: roomName.trim(),
        }),
      });

      const data = await res.json();
      if (data.success && data.data) {
        message.success('群聊创建成功');
        onSuccess(data.data);
        setRoomName('');
      } else {
        message.error(data.message || '创建失败');
      }
    } catch (err) {
      console.error('Create room error:', err);
      message.error('创建失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    setRoomName('');
    onCancel();
  };

  return (
    <Modal
      title="创建新群聊"
      open={visible}
      onOk={handleOk}
      onCancel={handleCancel}
      confirmLoading={loading}
      okText="创建"
      cancelText="取消"
    >
      <Input
        placeholder="输入群聊名称"
        value={roomName}
        onChange={(e) => setRoomName(e.target.value)}
        maxLength={50}
        showCount
        onPressEnter={handleOk}
      />
    </Modal>
  );
};

export default CreateRoomModal;
