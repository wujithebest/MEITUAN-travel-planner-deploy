import React, { useState, useEffect } from 'react';
import { Layout, Button, Space, Alert } from 'antd';
import { MapContainer } from '@/components/MapContainer';
import styles from "./PlannerPage/PlannerPage.module.css";

const { Header, Content } = Layout;

const TestMapPage: React.FC = () => {
  const [mapReady, setMapReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <Layout className={styles.layout}>
      <Header className={styles.header}>
        <h1 className={styles.title}>🗺️ 地图显示测试</h1>
      </Header>

      <Content className={styles.mapSection}>
        <div style={{ 
          position: 'absolute', 
          top: 20, 
          left: 20, 
          zIndex: 1000,
          background: 'rgba(255, 255, 255, 0.9)',
          padding: '10px',
          borderRadius: '4px'
        }}>
          <Alert 
            message="地图容器调试信息" 
            type="info"
            showIcon
          />
        </div>
        
        <MapContainer containerId="test-gaode-map" />
        
        {!mapReady && !error && (
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            background: 'white',
            padding: '20px',
            borderRadius: '8px',
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.15)'
          }}>
<div style={{ width: '32px', height: '32px', border: '3px solid #f0f0f0', borderTopColor: '#FFD100', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 10px' }}></div>
            <p>地图加载中...</p>
          </div>
        )}
        
        {error && (
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            background: 'white',
            padding: '20px',
            borderRadius: '8px',
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.15)'
          }}>
            <p style={{ color: '#f5222d' }}>❌ {error}</p>
            <Button onClick={() => window.location.reload()}>重新加载</Button>
          </div>
        )}
      </Content>
    </Layout>
  );
};

export default TestMapPage;
