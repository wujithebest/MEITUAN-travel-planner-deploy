import { create } from 'zustand';
import { ChatRoom, ChatMessage, TravelIntent } from '../types/chat';

interface ChatState {
  // 房间列表
  rooms: ChatRoom[];
  setRooms: (rooms: ChatRoom[]) => void;
  addRoom: (room: ChatRoom) => void;
  updateRoom: (roomId: string, updates: Partial<ChatRoom>) => void;
  
  // 当前房间
  currentRoomId: string | null;
  setCurrentRoomId: (roomId: string | null) => void;
  
  // 消息列表
  messages: ChatMessage[];
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  updateMessage: (messageId: string, updates: Partial<ChatMessage>) => void;
  
  // 输入状态
  inputText: string;
  setInputText: (text: string) => void;
  
  // 打字状态
  isTyping: boolean;
  setIsTyping: (typing: boolean) => void;
  
  // 在线成员
  onlineMembers: string[];
  setOnlineMembers: (members: string[]) => void;
  addOnlineMember: (memberId: string) => void;
  removeOnlineMember: (memberId: string) => void;
  
  // AI助手面板
  showAgentPanel: boolean;
  setShowAgentPanel: (show: boolean) => void;
  toggleAgentPanel: () => void;
  
  // 提取的意图
  extractedIntent: TravelIntent | null;
  setExtractedIntent: (intent: TravelIntent | null) => void;
  updateExtractedIntent: (updates: Partial<TravelIntent>) => void;
  
  // WebSocket连接
  wsConnected: boolean;
  setWsConnected: (connected: boolean) => void;
  
  // 加载状态
  loading: boolean;
  setLoading: (loading: boolean) => void;
  
  // 错误状态
  error: string | null;
  setError: (error: string | null) => void;
  
  // 创建房间弹窗
  createModalVisible: boolean;
  setCreateModalVisible: (visible: boolean) => void;
  
  // 重置状态
  reset: () => void;
  
  // 切换房间时清理
  switchRoom: (roomId: string | null) => void;
}

const initialState = {
  rooms: [],
  currentRoomId: null,
  messages: [],
  inputText: '',
  isTyping: false,
  onlineMembers: [],
  showAgentPanel: false,
  extractedIntent: null,
  wsConnected: false,
  loading: false,
  error: null,
  createModalVisible: false,
};

export const useChatStore = create<ChatState>((set, get) => ({
  ...initialState,

  // 房间操作
  setRooms: (rooms) => set({ rooms }),
  
  addRoom: (room) => set((state) => ({
    rooms: [...state.rooms, room],
  })),
  
  updateRoom: (roomId, updates) => set((state) => ({
    rooms: state.rooms.map((room) =>
      room.id === roomId ? { ...room, ...updates } : room
    ),
  })),
  
  // 当前房间
  setCurrentRoomId: (roomId) => set({ currentRoomId: roomId }),
  
  // 消息操作
  setMessages: (messages) => set({ messages }),
  
  addMessage: (message) => set((state) => {
    // 检查消息是否已存在（避免重复）
    const exists = state.messages.some((msg) => msg.id === message.id);
    if (exists) {
      return state;
    }
    return { messages: [...state.messages, message] };
  }),
  
  updateMessage: (messageId, updates) => set((state) => ({
    messages: state.messages.map((msg) =>
      msg.id === messageId ? { ...msg, ...updates } : msg
    ),
  })),
  
  // 输入状态
  setInputText: (inputText) => set({ inputText }),
  
  // 打字状态
  setIsTyping: (isTyping) => set({ isTyping }),
  
  // 在线成员
  setOnlineMembers: (onlineMembers) => set({ onlineMembers }),
  
  addOnlineMember: (memberId) => set((state) => ({
    onlineMembers: [...new Set([...state.onlineMembers, memberId])],
  })),
  
  removeOnlineMember: (memberId) => set((state) => ({
    onlineMembers: state.onlineMembers.filter((id) => id !== memberId),
  })),
  
  // AI助手面板
  setShowAgentPanel: (showAgentPanel) => set({ showAgentPanel }),
  
  toggleAgentPanel: () => set((state) => ({
    showAgentPanel: !state.showAgentPanel,
  })),
  
  // 意图提取
  setExtractedIntent: (extractedIntent) => set({ extractedIntent }),
  
  updateExtractedIntent: (updates) => set((state) => ({
    extractedIntent: state.extractedIntent
      ? { ...state.extractedIntent, ...updates }
      : {
          destination: '',
          themes: [],
          ...updates,
        },
  })),
  
  // WebSocket状态
  setWsConnected: (wsConnected) => set({ wsConnected }),
  
  // 加载状态
  setLoading: (loading) => set({ loading }),
  
  // 错误状态
  setError: (error) => set({ error }),
  
  // 创建房间弹窗
  setCreateModalVisible: (createModalVisible) => set({ createModalVisible }),
  
  // 重置所有状态
  reset: () => set(initialState),
  
  // 切换房间时清理相关状态
  switchRoom: (roomId) => set({
    currentRoomId: roomId,
    messages: [],
    isTyping: false,
    extractedIntent: null,
    error: null,
  }),
}));

// 选择器
export const selectCurrentRoom = (state: ChatState) =>
  state.rooms.find((room) => room.id === state.currentRoomId);

export const selectUnreadCount = (state: ChatState) =>
  state.rooms.reduce((sum, room) => sum + room.unread_count, 0);

export const selectAgentMessages = (state: ChatState) =>
  state.messages.filter((msg) => msg.sender.is_agent);

export const selectHasValidIntent = (state: ChatState) => {
  const intent = state.extractedIntent;
  return intent && intent.destination && intent.themes.length > 0;
};
