import React, { useState } from 'react';
import { Tag, Carousel, Modal } from 'antd';
import { MapPin, Clock, Train, Phone, DollarSign, Home, TreePine } from 'lucide-react';
import type { POI } from '@/api/types';
import styles from './POICard.module.css';

interface POICardProps {
  poi: POI;
  index: number;
  isStart?: boolean;
  isEnd?: boolean;
  onClick?: () => void;
  isRecommended?: boolean; // 是否推荐POI
}

const POICard: React.FC<POICardProps> = ({ poi, index, isStart, isEnd, onClick, isRecommended = false }) => {
  const [photoVisible, setPhotoVisible] = useState(false);
  const color = isStart ? '#52c41a' : isEnd ? '#f5222d' : '#FFD100';

  return (
    <>
      <div className={styles.card} onClick={onClick} style={{ borderLeftColor: color }}>
        {/* 照片轮播 */}
        {poi.photos && poi.photos.length > 0 && (
          <div className={styles.photoSection}>
            <Carousel dots={poi.photos.length > 1} arrows={poi.photos.length > 1}>
              {poi.photos.map((photo, idx) => (
                <div key={idx}>
                  <img
                    src={photo.url}
                    alt={photo.title || poi.name}
                    className={styles.photo}
                    onClick={(e) => {
                      e.stopPropagation();
                      setPhotoVisible(true);
                    }}
                  />
                </div>
              ))}
            </Carousel>
          </div>
        )}

        <div className={styles.header}>
          <span className={styles.index} style={{ background: color }}>{index}</span>
          <span className={styles.name}>{poi.name}</span>
          {isStart && <Tag color="green">起点</Tag>}
          {isEnd && <Tag color="red">终点</Tag>}
          {isRecommended && <Tag color="purple">推荐</Tag>}
        </div>

        <div className={styles.info}>
          {poi.address && (
            <div className={styles.row}>
              <MapPin size={14} />
              <span>{poi.address}</span>
            </div>
          )}
          
          {poi.open_time && (
            <div className={styles.row}>
              <Clock size={14} />
              <span>{poi.open_time}</span>
            </div>
          )}
          
          {poi.price && (
            <div className={styles.row}>
              <DollarSign size={14} />
              <span>{poi.price}</span>
            </div>
          )}
          
          {poi.tel && (
            <div className={styles.row}>
              <Phone size={14} />
              <a href={`tel:${poi.tel}`} onClick={(e) => e.stopPropagation()}>
                {poi.tel}
              </a>
            </div>
          )}
          
          {poi.indoor !== null && poi.indoor !== undefined && (
            <div className={styles.row}>
              {poi.indoor ? <Home size={14} /> : <TreePine size={14} />}
              <span>{poi.indoor ? '室内' : '室外'}</span>
            </div>
          )}
          
          {poi.metro_hint && (
            <div className={styles.row}>
              <Train size={14} />
              <span>{poi.metro_hint}</span>
            </div>
          )}
        </div>

        {/* 标签 */}
        {poi.tag && poi.tag.length > 0 && (
          <div className={styles.tags}>
            {poi.tag.map((tag, idx) => (
              <Tag key={idx} color="blue">{tag}</Tag>
            ))}
          </div>
        )}

        {/* 子POI（如商场内的店铺） */}
        {poi.children && poi.children.length > 0 && (
          <details className={styles.childrenSection}>
            <summary className={styles.childrenSummary}>
              内部店铺 ({poi.children.length})
            </summary>
            <div className={styles.childrenList}>
              {poi.children.map((child, idx) => (
                <div key={idx} className={styles.childItem}>
                  <span className={styles.childName}>{child.name}</span>
                  {child.rating && <span className={styles.childRating}>⭐ {child.rating.toFixed(1)}</span>}
                </div>
              ))}
            </div>
          </details>
        )}

        {poi.rating && poi.rating > 0 && (
          <div className={styles.rating}>⭐ {poi.rating.toFixed(1)}</div>
        )}
        {poi.district && (
          <div className={styles.district}>{poi.district}</div>
        )}
      </div>

      {/* 照片预览弹窗 */}
      <Modal
        open={photoVisible}
        footer={null}
        onCancel={() => setPhotoVisible(false)}
        centered
        width={800}
      >
        <Carousel arrows>
          {(poi.photos || []).map((photo, idx) => (
            <div key={idx} style={{ textAlign: 'center' }}>
              <img
                src={photo.url}
                alt={photo.title || poi.name}
                style={{ maxWidth: '100%', maxHeight: '70vh' }}
              />
              {photo.title && (
                <p style={{ marginTop: 8, color: '#666' }}>{photo.title}</p>
              )}
            </div>
          ))}
        </Carousel>
      </Modal>
    </>
  );
};

export default React.memo(POICard);
