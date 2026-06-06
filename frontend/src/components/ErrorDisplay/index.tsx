import React from 'react';
import { Button, Alert } from 'antd';
import { ReloadOutlined, ToolOutlined } from '@ant-design/icons';
import type { PlanError } from '@/api/plan';
import styles from './ErrorDisplay.module.css';

export interface ErrorDisplayProps {
  error: PlanError;
  onRetry?: () => void;
  onRetrySimplified?: () => void;
  onViewDiagnostics?: () => void;
  showDiagnostics?: boolean;
}

const ErrorDisplay: React.FC<ErrorDisplayProps> = ({
  error,
  onRetry,
  onRetrySimplified,
  onViewDiagnostics,
  showDiagnostics = false,
}) => {
  const getErrorIcon = () => {
    switch (error.type) {
      case 'connection':
        return '🔌';
      case 'timeout':
        return '⏱️';
      case 'server':
        return '🔧';
      case 'parse':
        return '📄';
      default:
        return '❌';
    }
  };

  const getErrorTitle = () => {
    switch (error.type) {
      case 'connection':
        return '无法连接到规划服务';
      case 'timeout':
        return '请求超时';
      case 'server':
        return '服务器错误';
      case 'parse':
        return '数据解析错误';
      default:
        return '发生错误';
    }
  };

  const getAlertType = (): 'error' | 'warning' | 'info' => {
    switch (error.type) {
      case 'connection':
      case 'server':
        return 'error';
      case 'timeout':
        return 'warning';
      default:
        return 'info';
    }
  };

  return (
    <div className={styles.errorContainer}>
      <Alert
        type={getAlertType()}
        showIcon={false}
        className={styles.errorAlert}
        message={
          <div className={styles.errorContent}>
            <div className={styles.errorHeader}>
              <span className={styles.errorIcon}>{getErrorIcon()}</span>
              <span className={styles.errorTitle}>{getErrorTitle()}</span>
            </div>

            {error.details && (
              <div className={styles.errorDetails}>
                <p className={styles.errorMessage}>{error.details}</p>
              </div>
            )}

            {error.suggestions && error.suggestions.length > 0 && (
              <div className={styles.suggestions}>
                <p className={styles.suggestionsTitle}>可能的原因和解决方案：</p>
                <ul className={styles.suggestionsList}>
                  {error.suggestions.map((suggestion, index) => (
                    <li key={index} className={styles.suggestionItem}>
                      {suggestion}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className={styles.errorActions}>
              {onRetry && (
                <Button
                  type="primary"
                  icon={<ReloadOutlined />}
                  onClick={onRetry}
                  className={styles.actionButton}
                >
                  重试
                </Button>
              )}

              {error.type === 'timeout' && onRetrySimplified && (
                <Button
                  type="default"
                  onClick={onRetrySimplified}
                  className={styles.actionButton}
                >
                  简化需求重试
                </Button>
              )}

              {showDiagnostics && onViewDiagnostics && (
                <Button
                  type="default"
                  icon={<ToolOutlined />}
                  onClick={onViewDiagnostics}
                  className={styles.actionButton}
                >
                  查看诊断
                </Button>
              )}
            </div>
          </div>
        }
      />
    </div>
  );
};

export default ErrorDisplay;
