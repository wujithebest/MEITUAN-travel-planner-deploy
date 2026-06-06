import React, { useState } from 'react';
import { Modal, Radio } from 'antd';
import type { POI } from '@/api/types';
import styles from './DisambiguationModal.module.css';

interface DisambiguationModalProps {
  visible: boolean;
  options: POI[];
  context: string;
  onConfirm: (poi: POI) => void;
  onCancel: () => void;
}

const DisambiguationModal: React.FC<DisambiguationModalProps> = ({
  visible, options, context, onConfirm, onCancel,
}) => {
  const [selected, setSelected] = useState<string>('');

  return (
    <Modal
      title="请选择具体地点"
      open={visible}
      onOk={() => {
        const poi = options.find((p) => p.id === selected);
        if (poi) onConfirm(poi);
      }}
      onCancel={onCancel}
      okButtonProps={{ disabled: !selected }}
      width={520}
    >
      {context && <p className={styles.context}>{context}</p>}
      <Radio.Group
        className={styles.group}
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
      >
        {options.map((poi) => (
          <Radio key={poi.id} value={poi.id} className={styles.option}>
            <div className={styles.poiName}>{poi.name}</div>
            <div className={styles.poiAddr}>{poi.address}</div>
            <div className={styles.poiMeta}>
              {poi.rating && <span>⭐ {poi.rating.toFixed(1)}</span>}
              {poi.category && <span className={styles.cat}>{poi.category}</span>}
            </div>
          </Radio>
        ))}
      </Radio.Group>
    </Modal>
  );
};

export default DisambiguationModal;
