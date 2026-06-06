import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MainLayout from './components/Layout/MainLayout';
import LandingPage from './pages/LandingPage/index';
import { PlannerPage } from './pages/PlannerPage';
import ChatPage from './pages/ChatPage/index';
import { DiaryPage } from './pages/DiaryPage';
import LoginPage from './pages/LoginPage/index';
import RegisterPage from './pages/RegisterPage/index';
import AuthGuard from './components/AuthGuard';
import ErrorBoundary from './components/ErrorBoundary';
import './App.css';
import './styles/global.css';

const App: React.FC = () => {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#FFD100',
          colorInfo: '#FFD100',
          colorLink: '#CC9900',
          colorLinkHover: '#FFE033',
          colorLinkActive: '#E6BC00',
          colorTextLightSolid: '#333333',
        },
        algorithm: theme.defaultAlgorithm,
      }}
    >
      <BrowserRouter>
        <ErrorBoundary>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/" element={<LandingPage />} />
          {/* /app 路由 - 登录后的主入口，默认显示 PlannerPage */}
          {/* PlannerPage 有自己的完整布局，不使用 MainLayout */}
          <Route
            path="/app"
            element={
              <AuthGuard>
                <PlannerPage />
              </AuthGuard>
            }
          />
          <Route
            path="/planner"
            element={
              <AuthGuard>
                <PlannerPage />
              </AuthGuard>
            }
          />
          <Route
            path="/chat"
            element={
              <AuthGuard>
                <MainLayout>
                  <ChatPage />
                </MainLayout>
              </AuthGuard>
            }
          />
          <Route
            path="/diary"
            element={
              <AuthGuard>
                <MainLayout>
                  <DiaryPage />
                </MainLayout>
              </AuthGuard>
            }
          />
        </Routes>
        </ErrorBoundary>
      </BrowserRouter>
    </ConfigProvider>
  );
};

export default App;
