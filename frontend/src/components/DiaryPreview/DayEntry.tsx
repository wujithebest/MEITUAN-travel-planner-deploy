import React, { useState } from 'react';
import { Image, Tag, Button, Space, Tooltip, message, Spin } from 'antd';
import { Palette, RefreshCw, Download, Eye } from 'lucide-react';
import type { DiaryEntry } from '@/api/types';
import styles from './DiaryPreview.module.css';

// 地图风格配置
const MAP_STYLES = [
  { id: 'cartoon', name: '卡通', icon: '🎨', description: '经典卡通风格' },
  { id: 'sketch', name: '素描', icon: '✏️', description: '铅笔素描风格' },
  { id: 'watercolor', name: '水彩', icon: '🖌️', description: '水彩画风格' },
  { id: 'pixel', name: '像素', icon: '👾', description: '像素艺术风格' },
];

interface DayEntryProps {
  entry: DiaryEntry;
  diaryId: string;
  dayIndex: number;
  mapSnapshot?: string;
  onStyleChange?: (style: string) => void;
}

const DayEntry: React.FC<DayEntryProps> = ({
  entry,
  diaryId,
  dayIndex,
  mapSnapshot,
  onStyleChange,
}) => {
  const [currentStyle, setCurrentStyle] = useState('cartoon');
  const [mapImage, setMapImage] = useState<string | undefined>(mapSnapshot);
  const [loading, setLoading] = useState(false);
  const [showStyleSelector, setShowStyleSelector] = useState(false);

  // 切换地图风格
  const handleStyleChange = async (style: string) => {
    if (style === currentStyle && mapImage) {
      setShowStyleSelector(false);
      return;
    }

    setLoading(true);
    setCurrentStyle(style);
    setShowStyleSelector(false);

    try {
      // 调用后端API生成新风格的地图
      const response = await fetch(
        `/api/diary/${diaryId}/day/${dayIndex}/map?style=${style}&regenerate=true`,
        { method: 'GET' }
      );

      const result = await response.json();

      if (result.success && result.data?.map_snapshot) {
        setMapImage(result.data.map_snapshot);
        message.success(`已切换至${MAP_STYLES.find(s => s.id === style)?.name}风格`);
        onStyleChange?.(style);
      } else {
        message.error('地图风格切换失败');
      }
    } catch (error) {
      console.error('切换地图风格失败:', error);
      message.error('网络错误，请重试');
    } finally {
      setLoading(false);
    }
  };

  // 下载地图
  const handleDownload = () => {
    if (!mapImage) return;
    
    const link = document.createElement('a');
    link.href = mapImage;
    link.download = `day-${dayIndex}-${currentStyle}-map.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    message.success('地图已下载');
  };

  return (
    <div className={styles.entry}>
      {/* 条目头部 */}
      <div className={styles.entryHeader}>
        <span className={styles.entryDay}>第{entry.day}天</span>
        <h3 className={styles.entryTitle}>{entry.title}</h3>
      </div>

      {/* 条目内容 */}
      <p className={styles.entryContent}>{entry.content}</p>

      {/* 地图截图区域 */}
      {mapImage && (
        <div className={styles.mapContainer}>
          <div className={styles.mapHeader}>
            <span className={styles.mapTitle}>
              <Eye size={14} />
              路线图
            </span>
            <Space size={4}>
              {/* 风格选择器触发按钮 */}
              <Tooltip title="切换地图风格">
                <Button
                  type="text"
                  size="small"
                  icon={<Palette size={14} />}
                  onClick={() => setShowStyleSelector(!showStyleSelector)}
                  className={styles.styleButton}
                >
                  {MAP_STYLES.find(s => s.id === currentStyle)?.name}
                </Button>
              </Tooltip>

              {/* 下载按钮 */}
              <Tooltip title="下载地图">
                <Button
                  type="text"
                  size="small"
                  icon={<Download size={14} />}
                  onClick={handleDownload}
                />
              </Tooltip>
            </Space>
          </div>

          {/* 风格选择器 */}
          {showStyleSelector && (
            <div className={styles.styleSelector}>
              <div className={styles.styleGrid}>
                {MAP_STYLES.map((style) => (
                  <Tooltip key={style.id} title={style.description}>
                    <Button
                      type={currentStyle === style.id ? 'primary' : 'default'}
                      size="small"
                      onClick={() => handleStyleChange(style.id)}
                      className={styles.styleOption}
                    >
                      <span className={styles.styleIcon}>{style.icon}</span>
                      <span>{style.name}</span>
                    </Button>
                  </Tooltip>
                ))}
              </div>
            </div>
          )}

          {/* 地图图片 */}
          <div className={styles.mapImageWrapper}>
            <Spin spinning={loading} tip="生成中...">
              <Image
                src={mapImage}
                alt={`第${dayIndex}天地图`}
                preview={true}
                className={styles.mapImage}
                style={{ 
                  filter: loading ? 'blur(2px)' : 'none',
                  transition: 'filter 0.3s ease'
                }}
              />
            </Spin>
            
            {/* 风格标签 */}
            <div className={styles.styleTag}>
              {MAP_STYLES.find(s => s.id === currentStyle)?.icon}
              {MAP_STYLES.find(s => s.id === currentStyle)?.name}
            </div>
          </div>
        </div>
      )}

      {/* 照片区域 */}
      {entry.photos.length > 0 && (
        <div className={styles.entryPhotos}>
          {entry.photos.map((photo, i) => (
            <Image key={i} src={photo} className={styles.entryPhoto} />
          ))}
        </div>
      )}

      {/* 高光标签 */}
      {entry.highlights.length > 0 && (
        <div className={styles.highlights}>
          {entry.highlights.map((h, i) => (
            <Tag key={i} color="gold">⭐ {h}</Tag>
          ))}
        </div>
      )}
    </div>
  );
};

export default DayEntry;
