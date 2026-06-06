/**
 * 消息渲染层单元测试
 */

import { MessageRenderer, createMessage, Message } from '../utils/messageRenderer';

describe('MessageRenderer', () => {
  let renderer: MessageRenderer;

  beforeEach(() => {
    renderer = new MessageRenderer();
  });

  describe('消息去重机制', () => {
    test('应该基于 message_id 去重', () => {
      const message1 = createMessage('user1', '你好', { message_id: 'msg_001' });
      const message2 = createMessage('user1', '你好', { message_id: 'msg_001' });

      expect(renderer.sendMessage(message1)).toBe(true);
      expect(renderer.sendMessage(message2)).toBe(false);
    });

    test('应该基于内容+用户ID+时间戳去重', () => {
      const now = Date.now();
      const message1 = createMessage('user1', '你好', { timestamp: now });
      const message2 = createMessage('user1', '你好', { timestamp: now });

      expect(renderer.sendMessage(message1)).toBe(true);
      expect(renderer.sendMessage(message2)).toBe(false);
    });

    test('5秒窗口外的消息不应去重', () => {
      const message1 = createMessage('user1', '你好', { timestamp: Date.now() - 6000 });
      const message2 = createMessage('user1', '你好', { timestamp: Date.now() });

      expect(renderer.sendMessage(message1)).toBe(true);
      expect(renderer.sendMessage(message2)).toBe(true);
    });
  });

  describe('状态同步规则', () => {
    test('发送消息应该先进入pending状态', () => {
      const message = createMessage('user1', '你好');
      renderer.sendMessage(message);

      const pendingMessages = renderer.getPendingMessages();
      expect(pendingMessages.length).toBe(1);
      expect(pendingMessages[0].status).toBe('pending');
    });

    test('收到ACK后应该转为confirmed状态', () => {
      const message = createMessage('user1', '你好', { message_id: 'msg_001' });
      renderer.sendMessage(message);

      const serverMessage = { ...message, status: 'confirmed' as const };
      renderer.receiveServerMessage(serverMessage);

      const pendingMessages = renderer.getPendingMessages();
      expect(pendingMessages.length).toBe(0);
    });
  });

  describe('群聊特殊处理', () => {
    test('群消息应该基于group_id + sender_id去重', () => {
      const message1 = createMessage('user1', '大家好', {
        message_id: 'group_msg_001',
        group_id: 'group1',
        sender_id: 'user1'
      });
      const message2 = createMessage('user1', '大家好', {
        message_id: 'group_msg_001',
        group_id: 'group1',
        sender_id: 'user1'
      });

      expect(renderer.sendMessage(message1)).toBe(true);
      expect(renderer.sendMessage(message2)).toBe(false);
    });

    test('不同群的消息不应去重', () => {
      const message1 = createMessage('user1', '大家好', {
        group_id: 'group1',
        sender_id: 'user1'
      });
      const message2 = createMessage('user1', '大家好', {
        group_id: 'group2',
        sender_id: 'user1'
      });

      expect(renderer.sendMessage(message1)).toBe(true);
      expect(renderer.sendMessage(message2)).toBe(true);
    });
  });

  describe('异常兜底', () => {
    test('连续3条相同内容应该触发告警', () => {
      const dispatchEventSpy = jest.spyOn(window, 'dispatchEvent');
      
      // 发送3条相同内容的消息
      for (let i = 0; i < 3; i++) {
        const message = createMessage('user1', '重复消息', { timestamp: Date.now() });
        renderer.sendMessage(message);
      }

      expect(dispatchEventSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'message-duplicate-alert'
        })
      );

      dispatchEventSpy.mockRestore();
    });
  });

  describe('消息队列管理', () => {
    test('应该正确获取所有消息', () => {
      const message1 = createMessage('user1', '消息1');
      const message2 = createMessage('user2', '消息2');

      renderer.sendMessage(message1);
      renderer.sendMessage(message2);

      const messages = renderer.getMessages();
      expect(messages.length).toBe(2);
    });

    test('应该正确获取待确认消息', () => {
      const message1 = createMessage('user1', '消息1');
      const message2 = createMessage('user2', '消息2');

      renderer.sendMessage(message1);
      renderer.sendMessage(message2);

      // 确认一条消息
      renderer.confirmLocalMessage(message1.message_id);

      const pendingMessages = renderer.getPendingMessages();
      expect(pendingMessages.length).toBe(1);
      expect(pendingMessages[0].message_id).toBe(message2.message_id);
    });
  });
});

describe('createMessage', () => {
  test('应该创建带有默认值的消息', () => {
    const message = createMessage('user1', '你好');

    expect(message.user_id).toBe('user1');
    expect(message.content).toBe('你好');
    expect(message.status).toBe('pending');
    expect(message.message_id).toBeDefined();
    expect(message.timestamp).toBeDefined();
  });

  test('应该允许覆盖默认值', () => {
    const options = {
      message_id: 'custom_id',
      status: 'confirmed' as const,
      sender_id: 'sender1',
      group_id: 'group1'
    };

    const message = createMessage('user1', '你好', options);

    expect(message.message_id).toBe('custom_id');
    expect(message.status).toBe('confirmed');
    expect(message.sender_id).toBe('sender1');
    expect(message.group_id).toBe('group1');
  });
});
