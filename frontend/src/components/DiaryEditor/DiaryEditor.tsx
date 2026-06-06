import React, { useEffect, useState } from 'react';
import { Input, Button, Upload, Space, message } from 'antd';
import { Save, Image, Star } from 'lucide-react';
import { useDiaryStore } from '@/store/diaryStore';
import { useDiary } from '@/hooks/useDiary';
import type { DiaryEntry } from '@/api/types';
import styles from './DiaryEditor.module.css';

const { TextArea } = Input;

interface DiaryEditorProps {
  entry?: DiaryEntry;
  day: number;
  onSave?: () => void;
}

const DiaryEditor: React.FC<DiaryEditorProps> = ({ entry, day, onSave }) => {
  const entries = useDiaryStore((s) => s.entries);
  const { addEntry, updateEntry, uploadPhoto } = useDiary();
  const activeEntry = entry || entries.find((item) => item.day === day);
  const [title, setTitle] = useState(activeEntry?.title || '');
  const [content, setContent] = useState(activeEntry?.content || '');
  const [highlights, setHighlights] = useState<string[]>(activeEntry?.highlights || []);
  const [newHighlight, setNewHighlight] = useState('');

  useEffect(() => {
    setTitle(activeEntry?.title || '');
    setContent(activeEntry?.content || '');
    setHighlights(activeEntry?.highlights || []);
  }, [activeEntry?.id]);

  const handleSave = async () => {
    if (activeEntry) {
      await updateEntry(activeEntry.id, { title, content, highlights });
    } else {
      await addEntry({ day, title, content, photos: [], highlights });
    }
    onSave?.();
  };

  const handleAddHighlight = () => {
    if (newHighlight.trim()) {
      setHighlights([...highlights, newHighlight.trim()]);
      setNewHighlight('');
    }
  };

  const handleUpload = async (file: File) => {
    if (!activeEntry) {
      message.warning('请先保存日记条目，再上传照片');
      return Upload.LIST_IGNORE;
    }
    await uploadPhoto(activeEntry.id, file);
    return false;
  };

  return (
    <div className={styles.container}>
      <div className={styles.field}>
        <label>标题</label>
        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="给今天起个标题..." />
      </div>
      <div className={styles.field}>
        <label>内容</label>
        <TextArea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="记录今天的旅行感悟..."
          rows={6}
        />
      </div>
      <div className={styles.field}>
        <label>高光时刻</label>
        <Space>
          <Input
            value={newHighlight}
            onChange={(e) => setNewHighlight(e.target.value)}
            placeholder="添加高光标记..."
            onPressEnter={handleAddHighlight}
          />
          <Button icon={<Star size={14} />} onClick={handleAddHighlight}>添加</Button>
        </Space>
        <div className={styles.highlights}>
          {highlights.map((h, i) => (
            <span key={i} className={styles.highlight}>⭐ {h}</span>
          ))}
        </div>
      </div>
      <div className={styles.field}>
        <label>照片</label>
        <Upload beforeUpload={handleUpload} listType="picture" maxCount={9}>
          <Button icon={<Image size={14} />}>上传照片</Button>
        </Upload>
      </div>
      <Button type="primary" icon={<Save size={14} />} onClick={handleSave}>
        保存
      </Button>
    </div>
  );
};

export default DiaryEditor;
