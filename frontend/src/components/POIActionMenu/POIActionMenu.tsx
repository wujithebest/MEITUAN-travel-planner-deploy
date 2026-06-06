import React, { useState } from 'react';
import {
  Plus,
  ArrowLeftRight,
  Heart,
  HeartCrack,
  Minus,
} from 'lucide-react';
import styles from './POIActionMenu.module.css';

export interface POIActionMenuProps {
  /** POI 名称 */
  poiName: string;
  /** POI 类型/分类 */
  poiType: string;
  /** 是否是备选 POI（非路线内） */
  isEnroute: boolean;
  /** 是否处于替换模式 */
  replaceModeActive?: boolean;
  /** 加入到路线 */
  onAddToRoute?: () => void;
  /** 从路线删除 */
  onRemoveFromRoute?: () => void;
  /** 发起替换 */
  onSwap?: () => void;
  /** 标记喜欢 */
  onLike?: () => void;
  /** 标记不喜欢 */
  onDislike?: () => void;
  /** 关闭菜单 */
  onClose?: () => void;
}

function ActionButton({
  icon,
  label,
  tooltip,
  onClick,
  active,
}: {
  icon: React.ReactNode;
  label: string;
  tooltip: string;
  onClick?: () => void;
  active?: boolean;
}) {
  const [hover, setHover] = useState(false);

  return (
    <div className={styles.actionItem}>
      <button
        className={`${styles.actionBtn} ${active ? styles.actionBtnActive : ''}`}
        onClick={(e) => {
          e.stopPropagation();
          onClick?.();
        }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        aria-label={label}
      >
        {icon}
      </button>
      {hover && <span className={styles.tooltip}>{tooltip}</span>}
    </div>
  );
}

export default function POIActionMenu({
  poiName,
  isEnroute,
  replaceModeActive,
  onAddToRoute,
  onRemoveFromRoute,
  onSwap,
  onLike,
  onDislike,
  onClose,
}: POIActionMenuProps) {
  return (
    <div className={styles.menu} onClick={(e) => e.stopPropagation()}>
      <div className={styles.header}>
        <span className={styles.poiName} title={poiName}>{poiName}</span>
        <button className={styles.closeBtn} onClick={onClose}>x</button>
      </div>
      <div className={styles.actions}>
        {isEnroute ? (
          <>
            <ActionButton
              icon={<Plus size={18} />}
              label="加入路线"
              tooltip="加入既有路线"
              onClick={onAddToRoute}
            />
            <ActionButton
              icon={<ArrowLeftRight size={18} />}
              label="替换"
              tooltip="替换既有点"
              onClick={onSwap}
              active={replaceModeActive}
            />
            <ActionButton
              icon={<HeartCrack size={18} />}
              label="不喜欢"
              tooltip="标记不喜欢"
              onClick={onDislike}
            />
          </>
        ) : (
          <>
            <ActionButton
              icon={<Minus size={18} />}
              label="删除"
              tooltip="从既有路线中删除"
              onClick={onRemoveFromRoute}
            />
            <ActionButton
              icon={<ArrowLeftRight size={18} />}
              label="替换"
              tooltip="替换备选点"
              onClick={onSwap}
              active={replaceModeActive}
            />
            <ActionButton
              icon={<Heart size={18} />}
              label="喜欢"
              tooltip="标记为喜欢"
              onClick={onLike}
            />
          </>
        )}
      </div>
    </div>
  );
}
