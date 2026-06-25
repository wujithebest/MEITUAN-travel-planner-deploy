import React, { useEffect, useState } from 'react';
import { Spin } from 'antd';
import { useUserStore } from '@/store/userStore';

interface AuthGuardProps {
  children: React.ReactNode;
}

const AuthGuard: React.FC<AuthGuardProps> = ({ children }) => {
  const { isLoggedIn, isGuest, token, ensureGuestSession } = useUserStore();
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    // v18: 已有登录态则立即放行
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

  // v18: 水合完成后若未登录，自动进入游客模式
  useEffect(() => {
    if (hydrated && !isLoggedIn && !token) {
      ensureGuestSession();
    }
  }, [hydrated, isLoggedIn, token, ensureGuestSession]);

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

  // v18: 不再重定向到 /login — 未登录时自动游客会话已在上方 useEffect 处理
  return <>{children}</>;
};

export default AuthGuard;
