import React, { useState } from 'react';
import { Layout, Button, Space, Alert } from 'antd';
import { MapContainer } from '@/components/MapContainer';
import styles from './PlannerPage/PlannerPage.module.css';

const { Header, Content } = Layout;

const SimpleMapTest: React.FC = () => {
  const [testResult, setTestResult] = useState<string>('');
  const [mapReady, setMapReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runTests = () => {
    const tests = [];

    // 测试容器存在性
    const container = document.getElementById('gaode-map');
    if (container) {
      tests.push('✅ 地图容器存在');

      // 测试容器尺寸
      const rect = container.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        tests.push(`✅ 容器尺寸正确: ${rect.width} × ${rect.height}`);
      } else {
        tests.push('❌ 容器尺寸为0');
      }
    } else {
      tests.push('❌ 地图容器不存在');
    }

    // 测试高德地图 API
    if (window.AMap) {
      tests.push('✅ 高德地图API已加载');
    } else {
      tests.push('❌ 高德地图API未加载');
    }

    // 测试地图配置
    const mapConfig = window.localStorage.getItem('mapConfig');
    if (mapConfig) {
      try {
        JSON.parse(mapConfig);
        tests.push('✅ 地图配置存在且有效');
      } catch {
        tests.push('❌ 地图配置无效');
      }
    } else {
      tests.push('⚠️ 地图配置不存在（使用默认配置）');
    }

    setTestResult(tests.join('\n'));
  };

  return (
    <Layout className={styles.layout}>
      <Header className={styles.header}>
        <h1 className={styles.title}>🗺️ 地图显示测试</h1>
      </Header>

      <Content style={{ padding: '20px', background: '#f5f5f5' }}>
        <div style={{
          maxWidth: '800px',
          margin: '0 auto',
          background: 'white',
          borderRadius: '8px',
          padding: '20px',
          boxShadow: '0 2px 12px rgba(0, 0, 0, 0.1)'
        }}>
          <h2>地图显示问题诊断</h2>

          <Space style={{ marginBottom: '20px' }}>
            <Button type="primary" onClick={runTests}>
              运行测试
            </Button>
            <Button onClick={() => window.location.reload()}>
              重新加载
            </Button>
          </Space>

          {testResult &&
            <Alert
              message="测试结果"
              description={testResult}
              type={testResult.includes('❌') ? 'error' : testResult.includes('⚠️') ? 'warning' : 'success'}
              showIcon
              style={{ marginBottom: '20px' }}
            />
          }

          {error &&
            <Alert
              message="错误信息"
              description={error}
              type="error"
              showIcon
              style={{ marginBottom: '20px' }}
            />
          }

          <div style={{
            height: '500px',
            border: '2px solid #ddd',
            borderRadius: '8px',
            overflow: 'hidden',
            position: 'relative'
          }}>
            <MapContainer containerId="gaode-map" />

            {!mapReady && !error && (
              <div style={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                textAlign: 'center',
                zIndex: 10
              }}>
                <div style={{
                  width: '32px',
                  height: '32px',
                  border: '3px solid #f0f0f0',
borderTopColor: '#FFD100',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                  margin: '0 auto 10px'
                }}></div>
                <p>地图加载中...</p>
              </div>
            )}
          </div>

          <div style={{ marginTop: '20px', fontSize: '14px', color: '#666' }}>
            <h3>常见问题排查：</h3>
            <ul>
              <li>确保右侧区域有足够的空间显示地图</li>
              <li>检查高德地图 API Key 是否正确配置</li>
              <li>确认网络连接正常，能够访问高德地图服务</li>
              <li>检查浏览器控制台是否有错误信息</li>
            </ul>
          </div>
        </div>
      </Content>
    </Layout>
  );
};

export default SimpleMapTest;
