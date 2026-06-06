/**
 * 消息渲染层 - 处理消息去重、状态同步和异常检测
 * 修复：增强去重机制，支持message_id去重和5秒窗口去重
 */

// 消息状态类型
export type MessageStatus = 'pending' | 'confirmed' | 'failed';

// 消息接口
export interface Message {
  message_id: string;
  user_id: string;
  content: string;
  timestamp: number;
  status: MessageStatus;
  sender_id?: string;
  group_id?: string;
}

// 消息指纹生成
function generateMessageFingerprint(userId: string, content: string, timestamp: number): string {
  const str = `${userId}-${content}-${timestamp}`;
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32-bit integer
  }
  return Math.abs(hash).toString(36);
}

// 生成内容指纹（用于5秒窗口去重）
function generateContentFingerprint(userId: string, content: string): string {
  const str = `${userId}-${content}`;
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return Math.abs(hash).toString(36);
}

// 消息去重管理器
class MessageDeduplicationManager {
  private messageIds: Set<string> = new Set();
  private messageFingerprints: Map<string, number> = new Map();
  private duplicateCount: Map<string, number> = new Map();
  private lastDuplicateAlert: number = 0;
  private readonly DEDUPLICATION_WINDOW = 5000; // 5秒窗口
  private readonly DUPLICATE_ALERT_THRESHOLD = 3;

  // 检查消息是否重复（增强版：支持5秒窗口+相同sender+相同内容过滤）
  isDuplicate(message: Message): boolean {
    // 优先使用 message_id 去重
    if (message.message_id && this.messageIds.has(message.message_id)) {
      console.log(`[去重] message_id重复: ${message.message_id}`);
      return true;
    }

    // 生成内容指纹（基于sender+content，用于5秒窗口去重）
    const contentFingerprint = generateContentFingerprint(
      message.sender_id || message.user_id, 
      message.content
    );
    
    const lastSeen = this.messageFingerprints.get(contentFingerprint);
    const now = Date.now();

    // 检查是否在5秒窗口内（相同sender+相同内容）
    if (lastSeen && (now - lastSeen) < this.DEDUPLICATION_WINDOW) {
      // 记录重复次数
      const key = `${message.sender_id || message.user_id}-${message.content}`;
      const count = (this.duplicateCount.get(key) || 0) + 1;
      this.duplicateCount.set(key, count);

      console.log(`[去重] 5秒内重复消息: sender=${message.sender_id || message.user_id}, content=${message.content.substring(0, 20)}..., 重复次数=${count}`);

      // 检查是否需要触发异常告警
      if (count >= this.DUPLICATE_ALERT_THRESHOLD) {
        this.triggerDuplicateAlert();
        this.duplicateCount.set(key, 0); // 重置计数
      }

      return true;
    }

    // 记录消息
    if (message.message_id) {
      this.messageIds.add(message.message_id);
    }
    this.messageFingerprints.set(contentFingerprint, now);

    return false;
  }

  // 触发重复消息告警
  private triggerDuplicateAlert(): void {
    const now = Date.now();
    // 防止频繁告警，至少间隔10秒
    if (now - this.lastDuplicateAlert > 10000) {
      this.lastDuplicateAlert = now;
      console.warn('检测到重复消息，已自动过滤');
      // 这里可以触发UI通知
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('message-duplicate-alert', {
          detail: { message: '检测到重复消息，已自动过滤' }
        }));
      }
    }
  }

  // 清理过期记录
  cleanup(): void {
    const now = Date.now();
    for (const [fingerprint, timestamp] of this.messageFingerprints.entries()) {
      if (now - timestamp > this.DEDUPLICATION_WINDOW) {
        this.messageFingerprints.delete(fingerprint);
      }
    }
  }
}

// 消息状态管理器
class MessageStatusManager {
  private pendingMessages: Map<string, Message> = new Map();

  // 添加待确认消息
  addPendingMessage(message: Message): void {
    message.status = 'pending';
    this.pendingMessages.set(message.message_id, message);
  }

  // 确认消息
  confirmMessage(messageId: string): Message | null {
    const message = this.pendingMessages.get(messageId);
    if (message) {
      message.status = 'confirmed';
      this.pendingMessages.delete(messageId);
      return message;
    }
    return null;
  }

  // 标记消息失败
  markMessageFailed(messageId: string): void {
    const message = this.pendingMessages.get(messageId);
    if (message) {
      message.status = 'failed';
    }
  }

  // 获取待确认消息
  getPendingMessage(messageId: string): Message | undefined {
    return this.pendingMessages.get(messageId);
  }
}

// 群聊消息处理器
class GroupMessageHandler {
  private groupMessageIds: Map<string, Set<string>> = new Map();

  // 处理群聊消息
  processGroupMessage(message: Message): boolean {
    if (!message.group_id || !message.sender_id) {
      return true; // 非群聊消息，正常处理
    }

    const groupKey = `${message.group_id}-${message.sender_id}`;
    
    if (!this.groupMessageIds.has(groupKey)) {
      this.groupMessageIds.set(groupKey, new Set());
    }

    const groupMessages = this.groupMessageIds.get(groupKey)!;
    
    // 检查是否已存在相同消息
    if (message.message_id && groupMessages.has(message.message_id)) {
      return false; // 重复消息
    }

    // 记录消息
    if (message.message_id) {
      groupMessages.add(message.message_id);
    }

    return true;
  }
}

// 消息渲染器
export class MessageRenderer {
  private deduplicationManager: MessageDeduplicationManager;
  private statusManager: MessageStatusManager;
  private groupMessageHandler: GroupMessageHandler;
  private messageQueue: Message[] = [];

  constructor() {
    this.deduplicationManager = new MessageDeduplicationManager();
    this.statusManager = new MessageStatusManager();
    this.groupMessageHandler = new GroupMessageHandler();

    // 定期清理过期记录
    setInterval(() => {
      this.deduplicationManager.cleanup();
    }, 10000);
  }

  // 发送消息
  sendMessage(message: Message): boolean {
    // 检查去重
    if (this.deduplicationManager.isDuplicate(message)) {
      return false;
    }

    // 处理群聊消息
    if (!this.groupMessageHandler.processGroupMessage(message)) {
      return false;
    }

    // 添加到待确认队列
    this.statusManager.addPendingMessage(message);
    this.messageQueue.push(message);

    return true;
  }

  // 接收服务端消息（修复：本地pending消息收到服务端ACK后再确认显示）
  receiveServerMessage(message: Message): boolean {
    // 检查是否是确认本地pending消息
    const pendingMessage = this.statusManager.getPendingMessage(message.message_id);
    
    if (pendingMessage) {
      // 收到服务端ACK，确认本地消息
      this.statusManager.confirmMessage(message.message_id);
      
      // 更新消息队列中的状态
      const index = this.messageQueue.findIndex(m => m.message_id === message.message_id);
      if (index !== -1) {
        this.messageQueue[index].status = 'confirmed';
        // 如果服务端消息内容更完整，更新内容
        if (message.content && message.content !== pendingMessage.content) {
          this.messageQueue[index].content = message.content;
        }
      }
      
      console.log(`[消息确认] 本地pending消息已确认: ${message.message_id}`);
      return true;
    }

    // 非pending消息，检查去重
    if (this.deduplicationManager.isDuplicate(message)) {
      return false;
    }

    // 处理群聊消息
    if (!this.groupMessageHandler.processGroupMessage(message)) {
      return false;
    }

    // 添加到消息队列
    message.status = 'confirmed';
    this.messageQueue.push(message);

    return true;
  }

  // 确认本地消息
  confirmLocalMessage(messageId: string): void {
    this.statusManager.confirmMessage(messageId);
  }

  // 获取消息列表
  getMessages(): Message[] {
    return [...this.messageQueue];
  }

  // 获取待确认消息
  getPendingMessages(): Message[] {
    return this.messageQueue.filter(msg => msg.status === 'pending');
  }
}

// 导出单例实例
export const messageRenderer = new MessageRenderer();

// 导出工具函数
export function createMessage(
  userId: string,
  content: string,
  options?: Partial<Message>
): Message {
  return {
    message_id: options?.message_id || generateMessageFingerprint(userId, content, Date.now()),
    user_id: userId,
    content,
    timestamp: options?.timestamp || Date.now(),
    status: options?.status || 'pending',
    sender_id: options?.sender_id,
    group_id: options?.group_id,
    ...options
  };
}
