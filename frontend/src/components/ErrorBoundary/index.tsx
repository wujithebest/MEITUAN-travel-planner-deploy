/**
 * ErrorBoundary - React 错误边界
 * 捕获子组件树中未处理的异常，防止整个页面白屏
 */

import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** 自定义 fallback 消息 */
  message?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo });
    console.error('[ErrorBoundary] 捕获到未处理异常:', error, errorInfo);
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    window.location.reload();
  };

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100vh',
            width: '100vw',
            background: '#FFFDF2',
            fontFamily: 'system-ui, -apple-system, sans-serif',
            padding: 24,
            boxSizing: 'border-box',
          }}
        >
          <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1f1f1f', margin: '0 0 8px' }}>
            {this.props.message || '页面出了点问题'}
          </h1>
          <p style={{ fontSize: 14, color: '#666', margin: '0 0 20px', textAlign: 'center', maxWidth: 400 }}>
            应用遇到了一个意外错误。请尝试刷新页面恢复。
          </p>
          <div style={{ display: 'flex', gap: 12 }}>
            <button
              onClick={this.handleReload}
              style={{
                padding: '10px 24px',
                background: '#FFD100',
                color: '#1f1f1f',
                border: 'none',
                borderRadius: 8,
                fontSize: 14,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              刷新页面
            </button>
            <button
              onClick={this.handleReset}
              style={{
                padding: '10px 24px',
                background: '#fff',
                color: '#666',
                border: '1px solid #ddd',
                borderRadius: 8,
                fontSize: 14,
                cursor: 'pointer',
              }}
            >
              尝试恢复
            </button>
          </div>
          {this.state.error && (
            <details style={{ marginTop: 20, maxWidth: 600, width: '100%' }}>
              <summary style={{ cursor: 'pointer', color: '#999', fontSize: 12 }}>
                错误详情
              </summary>
              <pre
                style={{
                  marginTop: 8,
                  padding: 12,
                  background: '#f5f5f5',
                  borderRadius: 8,
                  fontSize: 11,
                  overflow: 'auto',
                  maxHeight: 300,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {this.state.error?.stack || this.state.error?.message || String(this.state.error)}
              </pre>
              {this.state.errorInfo?.componentStack && (
                <pre
                  style={{
                    marginTop: 8,
                    padding: 12,
                    background: '#fff0f0',
                    borderRadius: 8,
                    fontSize: 11,
                    overflow: 'auto',
                    maxHeight: 200,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                  }}
                >
                  {this.state.errorInfo.componentStack}
                </pre>
              )}
            </details>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
