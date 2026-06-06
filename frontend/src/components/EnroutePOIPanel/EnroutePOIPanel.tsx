import React, { useState } from 'react';
import { Card, Button, Carousel, Modal } from 'antd';
import { MapPin, Star, MessageCircle } from 'lucide-react';
import styles from './EnroutePOIPanel.module.css';

interface EnroutePOIPanelProps {
  enroutePOIs: any[];
  onPoiClick?: (poi: any) => void;
}

const EnroutePOIPanel: React.FC<EnroutePOIPanelProps> = ({ enroutePOIs, onPoiClick }) => {
  const [photoVisible, setPhotoVisible] = useState(false);
  const [selectedPoi, setSelectedPoi] = useState<any>(null);

  if (!enroutePOIs || enroutePOIs.length === 0) {
    return null;
  }

  const formatDistance = (distance: number): string => {
    if (distance < 1000) {
      return `${Math.round(distance)}米`;
    }
    return `${(distance / 1000).toFixed(1)}公里`;
  };

  const truncateText = (text: string, maxLength: number): string => {
    return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
  };

  const handleCardClick = (poi: any) => {
    if (onPoiClick) {
      onPoiClick(poi);
    }
  };

  const handlePhotoClick = (poi: any, e: React.MouseEvent) => {
    e.stopPropagation();
    if (poi.photos && poi.photos.length > 0) {
      setSelectedPoi(poi);
      setPhotoVisible(true);
    }
  };

  return (
    <>
      <div className={styles.container}>
        <h3 className={styles.title}>沿途还会经过</h3>
        <div className={styles.poiList}>
          {enroutePOIs.slice(0, 6).map((poi, index) => (
            <Card
              key={poi.id || index}
              className={styles.poiCard}
              hoverable
              onClick={() => handleCardClick(poi)}
            >
              {/* 照片显示 */}
              {poi.photos && poi.photos.length > 0 && (
                <div className={styles.photoSection}>
                  <img
                    src={poi.photos[0].url}
                    alt={poi.photos[0].title || poi.name}
                    className={styles.photo}
                    onClick={(e) => handlePhotoClick(poi, e)}
                  />
                  {poi.photos.length > 1 && (
                    <span className={styles.photoCount}>
                      +{poi.photos.length - 1}
                    </span>
                  )}
                </div>
              )}

              <div className={styles.cardHeader}>
                <h4 className={styles.poiName}>{poi.name}</h4>
                <div className={styles.rating}>
<Star size={14} color="#FFD100" fill="#FFD100" />
                  <span>{poi.rating?.toFixed(1) || '暂无'}</span>
                </div>
              </div>
              
              <p className={styles.address}>{truncateText(poi.address, 30)}</p>
              
              <div className={styles.infoRow}>
                <span className={styles.type}>{poi.type}</span>
                <span className={styles.distance}>
                  距路线 {formatDistance(poi.distance_from_route)}
                </span>
              </div>
              
              {poi.reviews && poi.reviews.length > 0 && (
                <div className={styles.reviewPreview}>
                  <MessageCircle size={12} />
                  <span className={styles.reviewText}>
                    "{truncateText(poi.reviews[0]?.content || '', 15)}"
                  </span>
                </div>
              )}
            </Card>
          ))}
        </div>
      </div>

      {/* 照片预览弹窗 */}
      <Modal
        open={photoVisible}
        footer={null}
        onCancel={() => setPhotoVisible(false)}
        centered
        width={800}
      >
        {selectedPoi && (
          <Carousel arrows>
            {selectedPoi.photos.map((photo: any, idx: number) => (
              <div key={idx} style={{ textAlign: 'center' }}>
                <img
                  src={photo.url}
                  alt={photo.title || selectedPoi.name}
                  style={{ maxWidth: '100%', maxHeight: '70vh' }}
                />
                {photo.title && (
                  <p style={{ marginTop: 8, color: '#666' }}>{photo.title}</p>
                )}
              </div>
            ))}
          </Carousel>
        )}
      </Modal>
    </>
  );
};

export default EnroutePOIPanel;
