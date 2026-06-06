import React from 'react';
import { Spin } from 'antd';
import styles from './LoadingOverlay.module.css';

interface LoadingOverlayProps {
  visible: boolean;
  tip?: string;
}

const LoadingOverlay: React.FC<LoadingOverlayProps> = ({ visible, tip = '加载中...' }) => {
  if (!visible) return null;

  return (
    <div className={styles.overlay}>
      <div className={styles.content}>
        <Spin size="large" tip={tip} />
      </div>
    </div>
  );
};

export default LoadingOverlay;
