import { useCallback } from 'react';
import { useDiaryStore } from '@/store/diaryStore';
import {
  generateDiary,
  getDiary,
  addDiaryEntry,
  updateDiaryEntry,
  uploadPhoto,
  exportDiary,
  getShareLink,
} from '@/api/diary';
import { message } from 'antd';

export function useDiary() {
  const setDiary = useDiaryStore((s) => s.setDiary);
  const setGenerating = useDiaryStore((s) => s.setGenerating);
  const addPhoto = useDiaryStore((s) => s.addPhoto);
  const addEntry = useDiaryStore((s) => s.addEntry);
  const updateEntry = useDiaryStore((s) => s.updateEntry);
  const setShareLink = useDiaryStore((s) => s.setShareLink);
  const showExportModal = useDiaryStore((s) => s.showExportModal);
  const diaryId = useDiaryStore((s) => s.diaryId);
  const isGenerating = useDiaryStore((s) => s.isGenerating);

  const handleGenerate = useCallback(
    async (routeId: string) => {
      // 防止重复触发
      if (isGenerating) {
        console.log('[useDiary] 正在生成中，跳过重复请求');
        return;
      }
      
      console.log('[useDiary] 开始生成日记, routeId:', routeId);
      setGenerating(true);
      useDiaryStore.setState({ isGenerating: true });
      
      try {
        const diary = await generateDiary(routeId);
        console.log('[useDiary] 日记生成成功:', diary?.id);
        setDiary(diary);
        message.success('旅行日记已生成');
        
        // 自动弹出导出弹窗 - 延迟确保 DOM 已渲染
        setTimeout(() => {
          console.log('[useDiary] 显示导出弹窗');
          showExportModal();
        }, 800);
        
        return diary;
      } catch (error) {
        console.error('[useDiary] 日记生成失败:', error);
        message.error('日记生成失败');
      } finally {
        setGenerating(false);
        useDiaryStore.setState({ isGenerating: false });
        console.log('[useDiary] 生成状态已重置');
      }
    },
    [setDiary, setGenerating, showExportModal, isGenerating]
  );

  const handleLoad = useCallback(
    async (id: string) => {
      try {
        const diary = await getDiary(id);
        setDiary(diary);
        return diary;
      } catch {
        message.error('日记加载失败');
      }
    },
    [setDiary]
  );

  const handleAddEntry = useCallback(
    async (entry: Parameters<typeof addDiaryEntry>[1]) => {
      if (!diaryId) return;
      try {
        const newEntry = await addDiaryEntry(diaryId, entry);
        addEntry(newEntry);
        message.success('日记条目已添加');
        return newEntry;
      } catch {
        message.error('添加日记条目失败');
      }
    },
    [diaryId, addEntry]
  );

  const handleUpdateEntry = useCallback(
    async (entryId: string, entry: Parameters<typeof updateDiaryEntry>[2]) => {
      if (!diaryId) return;
      try {
        const updated = await updateDiaryEntry(diaryId, entryId, entry);
        updateEntry(entryId, updated);
        message.success('日记条目已更新');
        return updated;
      } catch {
        message.error('更新日记条目失败');
      }
    },
    [diaryId, updateEntry]
  );

  const handleUploadPhoto = useCallback(
    async (entryId: string, file: File) => {
      if (!diaryId) return;
      try {
        const result = await uploadPhoto(diaryId, file, entryId);
        addPhoto(result.url, entryId);
        message.success('照片上传成功');
        return result.url;
      } catch {
        message.error('照片上传失败');
      }
    },
    [diaryId, addPhoto]
  );

  const handleExport = useCallback(
    async (format: 'image' | 'pdf') => {
      if (!diaryId) return;
      try {
        const result = await exportDiary(diaryId, format);
        message.success(`导出${format === 'image' ? '长图' : 'PDF'}成功`);
        return result.url;
      } catch {
        message.error('导出失败');
      }
    },
    [diaryId]
  );

  const handleShare = useCallback(async () => {
    if (!diaryId) return;
    try {
      const result = await getShareLink(diaryId);
      setShareLink(result.link);
      return result.link;
    } catch {
      message.error('生成分享链接失败');
    }
  }, [diaryId, setShareLink]);

  return {
    generate: handleGenerate,
    load: handleLoad,
    addEntry: handleAddEntry,
    updateEntry: handleUpdateEntry,
    uploadPhoto: handleUploadPhoto,
    export: handleExport,
    share: handleShare,
  };
}
