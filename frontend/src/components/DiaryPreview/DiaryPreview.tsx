import React from 'react';
import { Image, Tag, Row, Col, Statistic } from 'antd';
import { MapPin, Camera, Award } from 'lucide-react';
import type { Diary } from '@/api/types';
import DayEntry from './DayEntry';
import styles from './DiaryPreview.module.css';

interface DiaryPreviewProps {
  diary: Diary;
  mapScreenshot?: string | null;
}

const DiaryPreview: React.FC<DiaryPreviewProps> = ({ diary, mapScreenshot }) => {
  // 按天分组条目
  const entriesByDay = diary.entries.reduce((acc, entry) => {
    const day = entry.day;
    if (!acc[day]) {
      acc[day] = [];
    }
    acc[day].push(entry);
    return acc;
  }, {} as Record<number, typeof diary.entries>);

  // 获取每天的地图截图（从条目中获取）
  const getMapSnapshotForDay = (day: number) => {
    const dayEntries = entriesByDay[day];
    if (dayEntries) {
      // 查找第一个有地图截图的条目
      const entryWithMap = dayEntries.find(e => (e as any).map_snapshot);
      return entryWithMap ? (entryWithMap as any).map_snapshot : undefined;
    }
    return undefined;
  };

  return (
    <div className={styles.container}>
      {/* 封面图 */}
      <div className={styles.cover}>
        {diary.cover_url && (
          <Image src={diary.cover_url} alt={diary.title} preview={false} />
        )}
        <div className={styles.coverOverlay}>
          <h2>{diary.title}</h2>
          {/* 地图截图槽位 */}
          {mapScreenshot && (
            <div className={styles.mapSlot}>
              <img src={mapScreenshot} alt="旅行地图" />
            </div>
          )}
        </div>
      </div>

      {/* 统计信息 */}
      <div className={styles.stats}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="天数" value={diary.stats.total_days} suffix="天" />
          </Col>
          <Col span={6}>
            <Statistic title="距离" value={diary.stats.total_distance} suffix="km" />
          </Col>
          <Col span={6}>
            <Statistic title="照片" value={diary.stats.total_photos} suffix="张" prefix={<Camera size={14} />} />
          </Col>
          <Col span={6}>
            <Statistic title="地点" value={diary.stats.pois_visited} suffix="个" prefix={<MapPin size={14} />} />
          </Col>
        </Row>
      </div>

      {/* 日记条目 - 按天展示 */}
      <div className={styles.entries}>
        {Object.entries(entriesByDay)
          .sort(([a], [b]) => Number(a) - Number(b))
          .map(([day, dayEntries]) => (
            <div key={day} className={styles.daySection}>
              {/* 天标题 */}
              <div className={styles.dayHeader}>
                <h2 className={styles.dayTitle}>第{day}天</h2>
              </div>

              {/* 使用 DayEntry 组件渲染每个条目 */}
              {dayEntries.map((entry, index) => (
                <DayEntry
                  key={entry.id || index}
                  entry={entry}
                  diaryId={diary.id}
                  dayIndex={Number(day)}
                  mapSnapshot={index === 0 ? getMapSnapshotForDay(Number(day)) : undefined}
                />
              ))}
            </div>
          ))}
      </div>

      {/* 成就徽章 */}
      {diary.achievements.length > 0 && (
        <div className={styles.achievements}>
          <h3><Award size={16} /> 成就徽章</h3>
          <div className={styles.badgeList}>
            {diary.achievements.map((a) => (
              <div key={a.id} className={styles.badge}>
                <span className={styles.badgeIcon}>{a.icon}</span>
                <span className={styles.badgeName}>{a.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default DiaryPreview;
