import { create } from 'zustand';
import type { Diary, DiaryEntry, Achievement } from '@/api/types';

interface DiaryState {
  diary: Diary | null;
  diaryId: string | null;
  generating: boolean;
  photos: string[];
  entries: DiaryEntry[];
  achievements: Achievement[];
  shareLink: string | null;
  
  // 导出弹窗状态
  exportModalVisible: boolean;
  mapScreenshot: string | null;  // base64
  isGeneratingImage: boolean;
  isGenerating: boolean;  // 防止重复触发生成

  setDiary: (diary: Diary) => void;
  setDiaryId: (id: string | null) => void;
  setGenerating: (v: boolean) => void;
  addPhoto: (url: string, entryId: string) => void;
  removePhoto: (url: string) => void;
  addEntry: (entry: DiaryEntry) => void;
  updateEntry: (id: string, entry: Partial<DiaryEntry>) => void;
  removeEntry: (id: string) => void;
  setShareLink: (link: string | null) => void;
  
  // 导出弹窗 actions
  showExportModal: () => void;
  hideExportModal: () => void;
  setMapScreenshot: (screenshot: string | null) => void;
  saveDiaryImage: () => Promise<void>;
  
  reset: () => void;
}

export const useDiaryStore = create<DiaryState>((set, get) => ({
  diary: null,
  diaryId: null,
  generating: false,
  photos: [],
  entries: [],
  achievements: [],
  shareLink: null,
  
  // 导出弹窗初始状态
  exportModalVisible: false,
  mapScreenshot: null,
  isGeneratingImage: false,
  isGenerating: false,

  setDiary: (diary) =>
    set({
      diary,
      diaryId: diary.id,
      photos: diary.entries.flatMap((entry) => entry.photos),
      entries: diary.entries,
      achievements: diary.achievements,
    }),

  setDiaryId: (diaryId) => set({ diaryId }),
  setGenerating: (generating) => set({ generating }),

  addPhoto: (url, entryId) =>
    set((s) => {
      const appendPhoto = (entry: DiaryEntry) =>
        entry.id === entryId ? { ...entry, photos: [...entry.photos, url] } : entry;
      const entries = s.entries.map(appendPhoto);
      return {
        photos: [...s.photos, url],
        entries,
        diary: s.diary
          ? {
              ...s.diary,
              entries: s.diary.entries.map(appendPhoto),
              stats: {
                ...s.diary.stats,
                total_photos: s.diary.stats.total_photos + 1,
              },
            }
          : null,
      };
    }),
  removePhoto: (url) => set((s) => ({ photos: s.photos.filter((p) => p !== url) })),

  addEntry: (entry) =>
    set((s) => ({
      entries: [...s.entries, entry],
      diary: s.diary ? { ...s.diary, entries: [...s.diary.entries, entry] } : null,
    })),

  updateEntry: (id, entry) =>
    set((s) => ({
      entries: s.entries.map((e) => (e.id === id ? { ...e, ...entry } : e)),
      diary: s.diary
        ? {
            ...s.diary,
            entries: s.diary.entries.map((e) => (e.id === id ? { ...e, ...entry } : e)),
          }
        : null,
    })),

  removeEntry: (id) =>
    set((s) => ({
      entries: s.entries.filter((e) => e.id !== id),
      diary: s.diary
        ? { ...s.diary, entries: s.diary.entries.filter((e) => e.id !== id) }
        : null,
    })),

  setShareLink: (shareLink) => set({ shareLink }),
  
  // 导出弹窗 actions 实现
  showExportModal: () => set({ exportModalVisible: true }),
  hideExportModal: () => set({ exportModalVisible: false }),
  setMapScreenshot: (screenshot) => set({ mapScreenshot: screenshot }),
  
  saveDiaryImage: async () => {
    // 这个函数将在组件中实现，因为需要访问DOM元素
    // 这里只是占位
  },

  reset: () =>
    set({
      diary: null,
      diaryId: null,
      generating: false,
      photos: [],
      entries: [],
      achievements: [],
      shareLink: null,
      exportModalVisible: false,
      mapScreenshot: null,
      isGeneratingImage: false,
      isGenerating: false,
    }),
}));
