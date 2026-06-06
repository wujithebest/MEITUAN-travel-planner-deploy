import React, { useState, useCallback, useMemo } from 'react';
import { ArrowLeftRight, Heart, ThumbsDown, Trash2 } from 'lucide-react';
import styles from './POIPopup.module.css';
import type { AlternativePoi } from '@/api/poi';

// ==================== 类型定义 ====================

/** 标签类型 */
export type TagType = 'unesco' | 'mustVisit' | 'custom';

/** 标签数据 */
export interface Tag {
  label: string;
  type: TagType;
  backgroundColor?: string;
  color?: string;
}

/** POI 弹窗数据 */
export interface POIData {
  poiId?: string;
  gaodePoiId?: string;
  category?: string;
  typecode?: string;
  photoSource?: string;
  recommendReason?: string;
  avgCost?: number | string | null;
  location?: string;
  /** 编号（显示在圆圈中） */
  index: number;
  /** 英文名称 */
  nameEn: string;
  /** 中文名称 */
  nameCn?: string;
  /** 图片 URL */
  imageUrl: string;
  /** 评分（0-5），hasRating=false 时显示"暂无评分" */
  rating: number;
  /** 是否有真实评分（false 时不显示数值，显示"暂无评分"） */
  hasRating?: boolean;
  /** 评分人数 */
  reviewCount: number;
  /** 排名文本，如 "No.4 of 1,251 things to do in Beijing" */
  ranking: string;
  /** 开放时间 */
  openHours?: string;
  /** 平均排队时间 */
  queueTime?: string;
  /** 地址 */
  address?: string;
  /** 标签列表 */
  tags?: Tag[];
}

export interface POIPopupProps {
  /** POI 数据 */
  data: POIData;
  /** 是否显示弹窗（用于高德 InfoWindow 控制） */
  visible?: boolean;
  /** 模式: route(黄色路线点) | candidate(蓝色候选点) */
  mode?: 'route' | 'candidate';
  /** 主题色 */
  theme?: 'yellow' | 'blue';
  /** 收藏状态变化回调 */
  onFavoriteChange?: (data: POIData, isFavorited: boolean) => void;
  onDelete?: (data: POIData) => void;
  onReplaceOpen?: (data: POIData) => Promise<AlternativePoi[]> | AlternativePoi[];
  onReplaceSelect?: (data: POIData, alternative: AlternativePoi) => void;
  onAlternativeLike?: (alternative: AlternativePoi, liked: boolean) => void;
  /** 候选模式：增加到路线（蓝色→黄色） */
  onAdd?: (data: POIData) => void;
  /** 候选模式：替换路线 POI */
  onReplace?: (data: POIData) => void;
  /** 点击弹窗回调 */
  onClick?: (data: POIData) => void;
  /** 关闭弹窗回调 */
  onClose?: () => void;
}

// ==================== 默认数据 ====================

const DEFAULT_TAGS: Tag[] = [
  { label: 'UNESCO', type: 'unesco' },
  { label: 'Must Visit', type: 'mustVisit' },
];

const DEFAULT_DATA: POIData = {
  index: 1,
  nameEn: 'Forbidden City',
  nameCn: '故宫博物院',
  imageUrl: '',  // No default placeholder — POIs without real images show "暂无图片"
  rating: 4.8,
  reviewCount: 68123,
  ranking: 'No.4 of 1,251 things to do in Beijing',
  openHours: '08:30 – 17:00',
  queueTime: '20 – 30 min',
  address: '4 Jingshan Front St, Beijing, China',
  tags: DEFAULT_TAGS,
};

// ==================== 工具函数 ====================

/** 格式化评分人数：68123 -> "68,123" */
const formatReviewCount = (count: number): string => {
  return count.toLocaleString();
};

/** 渲染星星图标 */
const renderStarIcon = (): React.ReactNode => (
  <svg 
    className={styles.starIcon} 
    width="16" 
    height="16" 
    viewBox="0 0 24 24" 
    fill="currentColor"
  >
    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
  </svg>
);

/** 渲染心形图标 */
const renderHeartIcon = (isFavorited: boolean): React.ReactNode => (
  <svg 
    className={`${styles.heartIcon} ${isFavorited ? styles.favorited : ''}`}
    width="20" 
    height="20" 
    viewBox="0 0 24 24" 
    fill={isFavorited ? 'currentColor' : 'none'}
    stroke="currentColor"
    strokeWidth="2"
  >
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
  </svg>
);

/** 渲染时钟图标 */
const renderClockIcon = (): React.ReactNode => (
  <svg 
    className={styles.infoIcon} 
    width="14" 
    height="14" 
    viewBox="0 0 24 24" 
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

/** 渲染人群图标 */
const renderCrowdIcon = (): React.ReactNode => (
  <svg 
    className={styles.infoIcon} 
    width="14" 
    height="14" 
    viewBox="0 0 24 24" 
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);

/** 渲染定位图标 */
const renderLocationIcon = (): React.ReactNode => (
  <svg 
    className={styles.infoIcon} 
    width="14" 
    height="14" 
    viewBox="0 0 24 24" 
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
    <circle cx="12" cy="10" r="3" />
  </svg>
);

/** 获取标签样式类名 */
const getTagClassName = (tag: Tag): string => {
  switch (tag.type) {
    case 'unesco':
      return `${styles.tag} ${styles.tagUnesco}`;
    case 'mustVisit':
      return `${styles.tag} ${styles.tagMustVisit}`;
    default:
      return `${styles.tag} ${styles.tagDefault}`;
  }
};

// ==================== 主组件 ====================

const POIPopup: React.FC<POIPopupProps> = ({
  data = DEFAULT_DATA,
  visible = true,
  mode = 'route',
  theme = 'yellow',
  onFavoriteChange,
  onDelete,
  onReplaceOpen,
  onReplaceSelect,
  onAlternativeLike,
  onAdd,
  onReplace,
  onClick,
  onClose,
}) => {
  const [isFavorited, setIsFavorited] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  const [alternativesOpen, setAlternativesOpen] = useState(false);
  const [alternativesLoading, setAlternativesLoading] = useState(false);
  const [alternatives, setAlternatives] = useState<AlternativePoi[]>([]);

  // 处理收藏按钮点击
  const handleFavoriteClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    const newFavorited = !isFavorited;
    setIsFavorited(newFavorited);
    onFavoriteChange?.(data, newFavorited);
  }, [isFavorited, data, onFavoriteChange]);

  const handleDeleteClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (isRemoving) return;
    setIsRemoving(true);
    window.setTimeout(() => {
      onDelete?.(data);
    }, 300);
  }, [data, isRemoving, onDelete]);

  const handleReplaceClick = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    const nextOpen = !alternativesOpen;
    setAlternativesOpen(nextOpen);
    if (!nextOpen || alternatives.length > 0 || !onReplaceOpen) return;
    setAlternativesLoading(true);
    try {
      const items = await onReplaceOpen(data);
      setAlternatives(items || []);
    } finally {
      setAlternativesLoading(false);
    }
  }, [alternatives.length, alternativesOpen, data, onReplaceOpen]);

  const handleAlternativeSelect = useCallback((e: React.MouseEvent, alternative: AlternativePoi) => {
    e.stopPropagation();
    onReplaceSelect?.(data, alternative);
  }, [data, onReplaceSelect]);

  const handleAlternativeLike = useCallback((e: React.MouseEvent, alternative: AlternativePoi, liked: boolean) => {
    e.stopPropagation();
    onAlternativeLike?.(alternative, liked);
  }, [onAlternativeLike]);

  // 处理弹窗点击
  const handleCardClick = useCallback(() => {
    onClick?.(data);
  }, [data, onClick]);

  // 处理图片加载错误
  const handleImageError = useCallback(() => {
    setImageError(true);
  }, []);

  // 计算显示的图片 URL
  // On image load error, return empty string so the "暂无图片" placeholder is shown.
  // Never use SVG/fallback placeholders.
  const displayImageUrl = useMemo(() => {
    if (imageError) {
      return '';
    }
    // Also treat known fallback URLs as empty
    const url = data.imageUrl || '';
    if (url.includes('/images/shanghai.jpg') || url.includes('unsplash.com/photo-1508804185872')) {
      return '';
    }
    return url;
  }, [imageError, data.imageUrl]);

  // 获取标签列表
  const tags = data.tags || DEFAULT_TAGS;

  const isCandidateMode = mode === 'candidate' || theme === 'blue';

  // v6: Candidate action handlers
  const handleAddClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onAdd?.(data);
  }, [data, onAdd]);

  const handleReplaceCandidateClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    // Close popup and signal replacement intent
    onReplace?.(data);
  }, [data, onReplace]);

  // 如果不显示，返回 null
  if (!visible) {
    return null;
  }

  return (
    <div className={`${styles.poiPopup} ${isCandidateMode ? styles.blueTheme : ''} ${isRemoving ? styles.removing : ''}`} onClick={handleCardClick}>
      <div className={styles.card}>
        {/* 顶部行：编号圆圈 + 地点名称 + 操作按钮 */}
        <div className={styles.header}>
          <div className={`${styles.indexCircle} ${isCandidateMode ? styles.blueIndexCircle : ''}`}>
            {isCandidateMode ? '' : data.index}
          </div>
          <div className={styles.nameContainer}>
            <div className={styles.nameEn}>{data.nameEn}</div>
            {data.nameCn && <div className={styles.nameCn}>{data.nameCn}</div>}
          </div>
          {isCandidateMode ? (
            <>
              <button
                className={styles.iconBtn}
                onClick={handleDeleteClick}
                title="删除"
                aria-label="删除"
              >
                <Trash2 size={18} />
              </button>
              <button
                className={styles.iconBtn}
                onClick={handleAddClick}
                title="增加"
                aria-label="增加"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
              </button>
              <button
                className={`${styles.iconBtn} ${styles.iconBtnActiveBlue}`}
                onClick={handleReplaceCandidateClick}
                title="替换"
                aria-label="替换"
              >
                <ArrowLeftRight size={18} />
              </button>
            </>
          ) : (
            <>
              <button
                className={styles.favoriteBtn}
                onClick={handleFavoriteClick}
                title={isFavorited ? '取消收藏' : '添加收藏'}
              >
                {renderHeartIcon(isFavorited)}
              </button>
              <button
                className={styles.iconBtn}
                onClick={handleDeleteClick}
                title="删除"
                aria-label="删除"
              >
                <Trash2 size={18} />
              </button>
              <button
                className={`${styles.iconBtn} ${alternativesOpen ? styles.iconBtnActiveBlue : ''}`}
                onClick={handleReplaceClick}
                title="替换"
                aria-label="替换"
              >
                <ArrowLeftRight size={18} />
              </button>
            </>
          )}
        </div>

        {/* 图片 */}
        <div className={styles.imageContainer}>
          {displayImageUrl ? (
            <img
              className={styles.image}
              src={displayImageUrl}
              alt={data.nameEn}
              onError={handleImageError}
              loading="lazy"
            />
          ) : (
            <div className={styles.noImage}>暂无图片</div>
          )}
        </div>

        {/* 评分行 */}
        <div className={styles.ratingRow}>
          {renderStarIcon()}
          <span className={styles.ratingScore}>
            {data.hasRating === false ? '暂无评分' : data.rating.toFixed(1)}
          </span>
          {data.reviewCount > 0 && (
            <span className={styles.ratingCount}>({formatReviewCount(data.reviewCount)})</span>
          )}
        </div>

        {/* 排名 */}
        <div className={styles.ranking}>
          {data.ranking}
        </div>

        {/* 信息行 */}
        <div className={styles.infoSection}>
          {data.openHours && (
            <div className={styles.infoRow}>
              {renderClockIcon()}
              <span className={styles.infoText}>Open Hours {data.openHours}</span>
            </div>
          )}
          {data.queueTime && (
            <div className={styles.infoRow}>
              {renderCrowdIcon()}
              <span className={styles.infoText}>Average Queue {data.queueTime}</span>
            </div>
          )}
          <div className={styles.infoRow}>
            {renderLocationIcon()}
            <span className={styles.infoText}>{data.address || '暂无地址'}</span>
          </div>
        </div>

        {/* 标签行 */}
        {tags.length > 0 && (
          <div className={styles.tagsRow}>
            {tags.map((tag, idx) => (
              <span
                key={idx}
                className={getTagClassName(tag)}
                style={tag.backgroundColor ? {
                  backgroundColor: tag.backgroundColor,
                  color: tag.color
                } : undefined}
              >
                {tag.label}
              </span>
            ))}
          </div>
        )}

        {/* v6: 候选模式不显示替代池；路线模式保持原有逻辑 */}
        {!isCandidateMode && alternativesOpen && (
          <div className={styles.alternativePool} onClick={(e) => e.stopPropagation()}>
            {alternativesLoading ? (
              <div className={styles.alternativeEmpty}>加载中...</div>
            ) : alternatives.length === 0 ? (
              <div className={styles.alternativeEmpty}>暂无备选地点</div>
            ) : (
              <div className={styles.alternativeScroller}>
                {alternatives.map((item) => (
                  <div className={styles.alternativeCard} key={item.poi_id || item.name}>
                    <img
                      className={styles.alternativeImage}
                      src={item.photo_url || displayImageUrl}
                      alt={item.name}
                      loading="lazy"
                    />
                    <div className={styles.alternativeBody}>
                      <div className={styles.alternativeName} title={item.name}>{item.name}</div>
                      <div className={styles.alternativeMeta}>
                        {item.rating ? Number(item.rating).toFixed(1) : '推荐'} · {Math.round(item.score)}
                      </div>
                      <div className={styles.alternativeActions}>
                        <button
                          className={styles.alternativeActionBtn}
                          onClick={(e) => handleAlternativeSelect(e, item)}
                          title="替换到路线"
                          aria-label="替换到路线"
                        >
                          <ArrowLeftRight size={15} />
                        </button>
                        <button
                          className={styles.alternativeActionBtn}
                          onClick={(e) => handleAlternativeLike(e, item, true)}
                          title="喜欢"
                          aria-label="喜欢"
                        >
                          <Heart size={15} />
                        </button>
                        <button
                          className={styles.alternativeActionBtn}
                          onClick={(e) => handleAlternativeLike(e, item, false)}
                          title="不喜欢"
                          aria-label="不喜欢"
                        >
                          <ThumbsDown size={15} />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// ==================== 导出 ====================

export default POIPopup;

// 导出工具函数供外部使用
export { formatReviewCount, DEFAULT_DATA, DEFAULT_TAGS };
