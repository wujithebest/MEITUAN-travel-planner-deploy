import React, { useState, useEffect } from 'react';
import { Modal, List, Button, Spin, Popconfirm, message } from 'antd';
import { Heart, Trash2, MapPin, Calendar, Navigation } from 'lucide-react';
import { useUserStore } from '../../store/userStore';
import { useRouteStore } from '../../store/routeStore';
import favoriteRoutesService, { FavoriteRoute } from '@/services/favoriteRoutes';
import styles from './ProfileModal.module.css';

interface ProfileModalProps {
  open: boolean;
  onClose: () => void;
  onNavigateToPlan?: () => void;
  onLoadFavorite?: (favorite: FavoriteRoute) => void;
}

const EmptyState: React.FC<{ onNavigate?: () => void }> = ({ onNavigate }) => (
  <div className={styles.emptyState}>
    <div className={styles.emptyIcon}>
      <Heart size={48} color="#ccc" />
    </div>
    <p className={styles.emptyText}>暂无收藏路线</p>
    <p className={styles.emptyHint}>规划完成后，点击行程面板右上角星标即可收藏</p>
    {onNavigate && (
      <Button
        type="primary"
        icon={<Navigation size={14} />}
        onClick={onNavigate}
        className={styles.planButton}
      >
        去规划路线
      </Button>
    )}
  </div>
);

const ProfileModal: React.FC<ProfileModalProps> = ({ open, onClose, onNavigateToPlan, onLoadFavorite }) => {
  const [favorites, setFavorites] = useState<FavoriteRoute[]>([]);
  const [loading, setLoading] = useState(false);
  const { isGuest } = useUserStore();

  useEffect(() => {
    if (open) {
      fetchFavorites();
    }
  }, [open]);

  const fetchFavorites = async () => {
    setLoading(true);
    try {
      const list = await favoriteRoutesService.listFavorites(isGuest);
      setFavorites(list);
    } catch (error) {
      console.error('获取收藏列表失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (fav: FavoriteRoute) => {
    try {
      await favoriteRoutesService.deleteFavorite(isGuest, fav);
      setFavorites(prev => prev.filter(f => (f.favorite_id || f.id) !== (fav.favorite_id || fav.id)));
      message.success('已删除');
    } catch {
      message.error('删除失败');
    }
  };

  const handleLoadFavorite = (fav: FavoriteRoute) => {
    // 校验：必须有 route_data 或 map_route_data
    if (!fav.route_data && !fav.map_route_data) {
      message.warning('该收藏缺少路线轨迹数据，请重新生成并收藏');
      return;
    }
    // 仅通过回调通知 PlannerPage 作为唯一加载入口（避免双重加载）
    onLoadFavorite?.(fav);
    message.success(`已加载：${fav.title}`);
    onClose();
  };

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    } catch {
      return dateStr;
    }
  };

  return (
    <Modal
      title="个人收藏"
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
      centered
      className={styles.modal}
    >
      <div className={styles.tabContent}>
        <Spin spinning={loading}>
          {favorites.length > 0 ? (
            <List
              itemLayout="horizontal"
              dataSource={favorites}
              renderItem={(item) => {
                const poiCount = item.summary?.poi_count
                  || item.panel_days?.reduce((sum: number, d: any) =>
                    sum + (d.slots?.reduce((s: number, slot: any) => s + (slot.pois?.length || 0), 0) || 0), 0)
                  || 0;
                return (
                  <List.Item
                    className={styles.listItem}
                    onClick={() => handleLoadFavorite(item)}
                    style={{ cursor: 'pointer' }}
                    actions={[
                      <Popconfirm
                        key="delete"
                        title="确认删除该收藏路线？"
                        onConfirm={(e) => {
                          e?.stopPropagation();
                          handleDelete(item);
                        }}
                        onCancel={(e) => e?.stopPropagation()}
                        okText="确认"
                        cancelText="取消"
                      >
                        <Button
                          type="text"
                          danger
                          icon={<Trash2 size={14} />}
                          onClick={(e) => e.stopPropagation()}
                          size="small"
                        />
                      </Popconfirm>,
                    ]}
                  >
                    <List.Item.Meta
                      avatar={
                        <div className={styles.favAvatar}>
                          <MapPin size={18} color="#FFD100" />
                        </div>
                      }
                      title={
                        <span className={styles.itemTitle}>{item.title || `${item.destination} ${item.days}日游`}</span>
                      }
                      description={
                        <div className={styles.tripInfo}>
                          <Calendar size={12} />
                          <span>{formatDate(item.created_at)}</span>
                          <span className={styles.tripDays}>{item.days} 天</span>
                          {poiCount > 0 && (
                            <>
                              <MapPin size={12} />
                              <span>{poiCount} 个地点</span>
                            </>
                          )}
                        </div>
                      }
                    />
                  </List.Item>
                );
              }}
            />
          ) : (
            !loading && <EmptyState onNavigate={onNavigateToPlan} />
          )}
        </Spin>
      </div>
    </Modal>
  );
};

export default ProfileModal;
