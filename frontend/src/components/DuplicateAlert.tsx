/**
 * 重复消息告警组件
 */

import React, { useEffect, useState } from 'react';

interface DuplicateAlertProps {
  show: boolean;
  onClear: () => void;
}

export const DuplicateAlert: React.FC<DuplicateAlertProps> = ({ show, onClear }) => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (show) {
      setVisible(true);
      // 3秒后自动隐藏
      const timer = setTimeout(() => {
        setVisible(false);
        onClear();
      }, 3000);

      return () => clearTimeout(timer);
    }
  }, [show, onClear]);

  if (!visible) {
    return null;
  }

  return (
    <div className="duplicate-alert">
      <div className="alert-content">
        <span className="alert-icon">⚠️</span>
        <span className="alert-message">检测到重复消息，已自动过滤</span>
        <button 
          className="alert-close"
          onClick={() => {
            setVisible(false);
            onClear();
          }}
        >
          ×
        </button>
      </div>
    </div>
  );
};

export default DuplicateAlert;
