import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { useUserStore } from '@/store/userStore';

interface AuthGuardProps {
  children: React.ReactNode;
}

const AuthGuard: React.FC<AuthGuardProps> = ({ children }) => {
  const { isLoggedIn, token } = useUserStore();
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    // 已有登录态则立即放行（in-session 点击游客模式等场景）
    if (isLoggedIn || token) {
      setHydrated(true);
      return;
    }
    // 页面刷新场景：等待 zustand persist 微任务完成恢复状态
    const raf = requestAnimationFrame(() => {
      setHydrated(true);
    });
    return () => cancelAnimationFrame(raf);
  }, [isLoggedIn, token]);

  if (!hydrated) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <Spin size="large" />
        <span style={{ color: '#666' }}>正在加载...</span>
      </div>
    );
  }

  if (!isLoggedIn && !token) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
};

export default AuthGuard;
