/**
 * 路线数据一致性验证面板组件
 * 显示验证结果和统计信息
 */

import React from 'react';
import type { VerificationResult } from '../hooks/useRouteVerification';

interface Props {
  result: VerificationResult | null;
  backendData: any;
  frontendData: any;
  isVisible: boolean;
  onToggle: () => void;
}

export const RouteVerificationPanel: React.FC<Props> = ({
  result,
  backendData,
  frontendData,
  isVisible,
  onToggle,
}) => {
  if (!result) {
    return (
      <div style={{
        position: 'fixed',
        bottom: 10,
        right: 10,
        zIndex: 10000,
        background: 'rgba(0,0,0,0.7)',
        color: '#fff',
        padding: '8px 12px',
        borderRadius: 4,
        fontSize: 12,
        cursor: 'pointer',
      }} onClick={onToggle}>
        🔍 点击验证路线数据
      </div>
    );
  }

  return (
    <div style={{
      position: 'fixed',
      bottom: 10,
      right: 10,
      zIndex: 10000,
      background: 'rgba(255,255,255,0.95)',
      padding: 12,
      borderRadius: 8,
      boxShadow: '0 2px 12px rgba(0,0,0,0.3)',
      fontSize: 12,
      fontFamily: 'Monaco, Consolas, monospace',
      maxWidth: 350,
      maxHeight: '80vh',
      overflow: 'auto',
    }}>
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center',
        marginBottom: 8,
        borderBottom: '1px solid #ddd',
        paddingBottom: 8,
      }}>
        <h3 style={{ margin: 0, fontSize: 14 }}>🔍 路线数据一致性验证</h3>
        <button 
          onClick={onToggle}
          style={{
            background: 'none',
            border: 'none',
            fontSize: 16,
            cursor: 'pointer',
            padding: '2px 6px',
          }}
        >
          {isVisible ? '▼' : '▲'}
        </button>
      </div>

      {isVisible && (
        <>
          {/* 验证状态 */}
          <div style={{ 
            marginBottom: 8,
            padding: '6px 10px',
            borderRadius: 4,
            background: result.passed ? '#d4edda' : '#f8d7da',
            color: result.passed ? '#155724' : '#721c24',
            fontWeight: 'bold',
          }}>
            {result.passed ? '✅ 验证通过' : `❌ 发现 ${result.errors.length} 个问题`}
          </div>

          {/* 统计信息 */}
          <div style={{ marginBottom: 8 }}>
            <h4 style={{ margin: '0 0 4px 0', fontSize: 12 }}>统计</h4>
            <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
              <tbody>
                <tr>
                  <td style={{ padding: '2px 4px', color: '#666' }}>后端 POI 数</td>
                  <td style={{ padding: '2px 4px', textAlign: 'right' }}>{result.stats.totalBackendPoints}</td>
                </tr>
                <tr>
                  <td style={{ padding: '2px 4px', color: '#666' }}>前端 Marker 数</td>
                  <td style={{ padding: '2px 4px', textAlign: 'right' }}>{result.stats.totalFrontendPoints}</td>
                </tr>
                <tr>
                  <td style={{ padding: '2px 4px', color: '#666' }}>后端路线段数</td>
                  <td style={{ padding: '2px 4px', textAlign: 'right' }}>{result.stats.totalBackendSegments}</td>
                </tr>
                <tr>
                  <td style={{ padding: '2px 4px', color: '#666' }}>前端 Polyline 数</td>
                  <td style={{ padding: '2px 4px', textAlign: 'right' }}>{result.stats.totalFrontendSegments}</td>
                </tr>
                <tr>
                  <td style={{ padding: '2px 4px', color: '#666' }}>起点</td>
                  <td style={{ padding: '2px 4px', textAlign: 'right' }}>{result.stats.startPoints}</td>
                </tr>
                <tr>
                  <td style={{ padding: '2px 4px', color: '#666' }}>途经点</td>
                  <td style={{ padding: '2px 4px', textAlign: 'right' }}>{result.stats.waypointPoints}</td>
                </tr>
                <tr>
                  <td style={{ padding: '2px 4px', color: '#666' }}>餐饮点</td>
                  <td style={{ padding: '2px 4px', textAlign: 'right' }}>{result.stats.mealPoints}</td>
                </tr>
                <tr>
                  <td style={{ padding: '2px 4px', color: '#666' }}>提示点(不画marker)</td>
                  <td style={{ padding: '2px 4px', textAlign: 'right' }}>{result.stats.hintPoints}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 错误详情 */}
          {result.errors.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <h4 style={{ margin: '0 0 4px 0', fontSize: 12 }}>错误详情</h4>
              {result.errors.map((err, idx) => (
                <div key={idx} style={{
                  padding: '4px 6px',
                  marginBottom: 4,
                  background: '#fff3cd',
                  borderRadius: 4,
                  fontSize: 11,
                }}>
                  <span style={{
                    display: 'inline-block',
                    padding: '1px 4px',
                    background: '#ffc107',
                    borderRadius: 3,
                    fontSize: 10,
                    marginRight: 4,
                  }}>
                    {err.type}
                  </span>
                  <span>{err.message}</span>
                </div>
              ))}
            </div>
          )}

          {/* 原始数据预览 */}
          <details style={{ fontSize: 11 }}>
            <summary style={{ cursor: 'pointer', color: '#666' }}>后端原始数据 (前3个点)</summary>
            <pre style={{
              background: '#f5f5f5',
              padding: 6,
              borderRadius: 4,
              overflow: 'auto',
              maxHeight: 100,
              fontSize: 10,
            }}>
              {JSON.stringify(backendData?.points?.slice(0, 3), null, 2)}
            </pre>
          </details>

          <details style={{ fontSize: 11, marginTop: 4 }}>
            <summary style={{ cursor: 'pointer', color: '#666' }}>前端渲染数据 (前3个标记)</summary>
            <pre style={{
              background: '#f5f5f5',
              padding: 6,
              borderRadius: 4,
              overflow: 'auto',
              maxHeight: 100,
              fontSize: 10,
            }}>
              {JSON.stringify(frontendData?.markers?.slice(0, 3), null, 2)}
            </pre>
          </details>
        </>
      )}
    </div>
  );
};

export default RouteVerificationPanel;
