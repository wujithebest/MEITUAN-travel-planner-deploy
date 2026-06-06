import React from 'react';
import { Lightbulb } from 'lucide-react';
import styles from './IntentBanner.module.css';

interface IntentBannerProps {
  reason: string;
  onRefresh: () => void;
  planMode?: 'precise' | 'intent';
}

const IntentBanner: React.FC<IntentBannerProps> = ({ 
  reason, 
  onRefresh, 
  planMode = 'intent' 
}) => {
  if (planMode !== 'intent') {
    return null; // 只显示意图模式的横幅
  }

  return (
    <div className={styles.intent_banner}>
      <div className={styles.content}>
        <Lightbulb className={styles.icon} />
        <span className={styles.reason_text}>{reason}</span>
      </div>
      <button 
        className={styles.refresh_button}
        onClick={onRefresh}
        aria-label="重新推荐"
      >
        重新推荐
      </button>
    </div>
  );
};

export default IntentBanner;
