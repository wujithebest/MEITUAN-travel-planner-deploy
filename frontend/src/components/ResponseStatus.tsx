/**
 * 响应状态组件
 * 显示AI助手处理状态，确保用户始终知道系统正在工作
 * 
 * 状态类型：
 * - processing: 正在处理
 * - success: 处理成功
 * - failed: 处理失败
 * - timeout: 处理超时
 * - needs_clarification: 需要更多信息
 */

import React from 'react';
import './ResponseStatus.css';

export type ResponseStatusType = 'processing' | 'success' | 'failed' | 'timeout' | 'needs_clarification';

interface ResponseStatusProps {
  status: ResponseStatusType;
  message?: string;
  traceId?: string;
  processingTimeMs?: number;
  onRetry?: () => void;
  onClarify?: () => void;
}

const statusConfig: Record<ResponseStatusType, { icon: string; label: string; color: string }> = {
  processing: {
    icon: '⏳',
    label: '正在处理',
    color: '#CC9900'
  },
  success: {
    icon: '✅',
    label: '处理完成',
    color: '#52c41a'
  },
  failed: {
    icon: '❌',
    label: '处理失败',
    color: '#ff4d4f'
  },
  timeout: {
    icon: '⏱️',
    label: '处理超时',
    color: '#CC9900'
  },
  needs_clarification: {
    icon: '❓',
    label: '需要更多信息',
    color: '#722ed1'
  }
};

export const ResponseStatus: React.FC<ResponseStatusProps> = ({
  status,
  message,
  traceId,
  processingTimeMs,
  onRetry,
  onClarify
}) => {
  const config = statusConfig[status];

  return (
    <div className="response-status" style={{ borderLeftColor: config.color }}>
      <div className="response-status-header">
        <span className="response-status-icon">{config.icon}</span>
        <span className="response-status-label" style={{ color: config.color }}>
          {config.label}
        </span>
        {processingTimeMs !== undefined && (
          <span className="response-status-time">
            {processingTimeMs < 1000 ? `${processingTimeMs}ms` : `${(processingTimeMs / 1000).toFixed(1)}s`}
          </span>
        )}
      </div>
      
      {message && (
        <div className="response-status-message">
          {message}
        </div>
      )}
      
      {traceId && (
        <div className="response-status-trace">
          <span className="trace-label">追踪ID:</span>
          <span className="trace-id">{traceId}</span>
        </div>
      )}
      
      <div className="response-status-actions">
        {(status === 'failed' || status === 'timeout') && onRetry && (
          <button 
            className="status-action-btn retry-btn"
            onClick={onRetry}
          >
            🔄 重试
          </button>
        )}
        
        {status === 'needs_clarification' && onClarify && (
          <button 
            className="status-action-btn clarify-btn"
            onClick={onClarify}
          >
            💬 补充信息
          </button>
        )}
      </div>
      
      {status === 'processing' && (
        <div className="response-status-loading">
          <div className="loading-dot"></div>
          <div className="loading-dot"></div>
          <div className="loading-dot"></div>
        </div>
      )}
    </div>
  );
};

/**
 * 处理中状态组件（简化版）
 */
export const ProcessingIndicator: React.FC<{ message?: string }> = ({ 
  message = '正在处理，请稍候...' 
}) => {
  return (
    <div className="processing-indicator">
      <div className="processing-spinner"></div>
      <span className="processing-message">{message}</span>
    </div>
  );
};

/**
 * 错误提示组件
 */
export const ErrorAlert: React.FC<{
  message: string;
  onRetry?: () => void;
  traceId?: string;
}> = ({ message, onRetry, traceId }) => {
  return (
    <div className="error-alert">
      <div className="error-alert-icon">⚠️</div>
      <div className="error-alert-content">
        <div className="error-alert-message">{message}</div>
        {traceId && (
          <div className="error-alert-trace">追踪ID: {traceId}</div>
        )}
      </div>
      {onRetry && (
        <button className="error-alert-retry" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
};

export default ResponseStatus;
