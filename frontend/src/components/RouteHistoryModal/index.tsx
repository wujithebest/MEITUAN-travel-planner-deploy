/**
 * 规划历史 Modal
 */

import React, { useEffect, useState, useCallback } from 'react';
import { Modal, message } from 'antd';
import { Trash2, Clock3 } from 'lucide-react';
import routeHistoryService, { type RouteHistory } from '@/services/routeHistory';
import { useUserStore } from '@/store/userStore';
import styles from './RouteHistoryModal.module.css';

interface RouteHistoryModalProps {
  open: boolean;
  onClose: () => void;
  onLoadHistory: (history: RouteHistory) => void;
  onDeleteHistory?: (historyId: string) => void;
}

const RouteHistoryModal: React.FC<RouteHistoryModalProps> = ({ open, onClose, onLoadHistory, onDeleteHistory }) => {
  const isGuest = useUserStore(state => state.isGuest);
  const [histories, setHistories] = useState<RouteHistory[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await routeHistoryService.listHistories(isGuest);
      setHistories(list);
    } catch {
      message.error('加载规划历史失败');
    } finally {
      setLoading(false);
    }
  }, [isGuest]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const handleDelete = async (e: React.MouseEvent, historyId: string) => {
    e.stopPropagation();
    try {
      await routeHistoryService.deleteHistory(isGuest, historyId);
      setHistories(prev => prev.filter(h => h.history_id !== historyId));
      onDeleteHistory?.(historyId);
      message.success('已删除');
    } catch {
      message.error('删除失败');
    }
  };

  const formatTime = (iso: string) => {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const pad = (n: number) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch {
      return iso;
    }
  };

  return (
    <Modal
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Clock3 size={18} />
          <span>规划历史</span>
        </div>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={480}
      destroyOnClose
    >
      <div className={styles.list}>
        {loading && <div className={styles.empty}>加载中...</div>}
        {!loading && histories.length === 0 && (
          <div className={styles.empty}>
            <Clock3 size={32} style={{ color: '#ccc', marginBottom: 8 }} />
            <p>暂无规划历史</p>
            <p className={styles.hint}>完成路线规划后将自动保存</p>
          </div>
        )}
        {!loading && histories.map(h => (
          <div
            key={h.history_id}
            className={styles.item}
            onClick={() => { onLoadHistory(h); onClose(); }}
          >
            <div className={styles.itemBody}>
              <div className={styles.itemTitle}>{h.title || `${h.destination} ${h.days}日游`}</div>
              <div className={styles.itemMeta}>
                <span>{formatTime(h.created_at)}</span>
                <span>·</span>
                <span>{h.summary?.poi_count || h.poi_details ? Object.keys(h.poi_details || {}).length : 0} 个地点</span>
                <span>·</span>
                <span>{h.destination || '上海'} {h.days || 1}日</span>
              </div>
            </div>
            <button
              className={styles.deleteBtn}
              onClick={(e) => handleDelete(e, h.history_id)}
              title="删除"
              aria-label="删除"
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>
    </Modal>
  );
};

export default RouteHistoryModal;
