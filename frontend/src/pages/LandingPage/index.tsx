import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { Sparkles, MapPin, Calendar, Camera } from 'lucide-react';
import BackgroundHero from '../../components/BackgroundHero';
import { useUserStore } from '../../store/userStore';

const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const { ensureGuestSession } = useUserStore();

  useEffect(() => {
    // v18: 封锁登录 — 直接进入游客模式并跳转
    ensureGuestSession();
    navigate('/app', { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // v18: 所有入口统一走游客模式，不再展示 AuthCard
  return (
    <BackgroundHero>
      {/* 主标题区域 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.1 }}
        className="text-center mb-12"
      >
        {/* AI 标签 */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 mb-20 md:mb-24"
        >
          <Sparkles className="w-4 h-4 text-white/80" />
          <span className="text-sm text-white/80 font-medium tracking-wide">
            AI Travel Operating System
          </span>
        </motion.div>

        {/* 主标题 */}
        <motion.h1
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.3 }}
          className="text-6xl md:text-7xl lg:text-8xl font-bold text-white tracking-wider mb-12 md:mb-16"
          style={{
            fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", Arial, sans-serif',
            letterSpacing: '0.05em',
            textShadow: '0 4px 30px rgba(0, 0, 0, 0.3)',
          }}
        >
          本地生活路线规划
        </motion.h1>

        {/* 副标题 */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.5 }}
          className="text-lg md:text-xl text-white/60 font-light tracking-wide max-w-xl mx-auto mt-10 pt-6"
        >
          智能规划 · 沉浸体验 · 未来旅行
        </motion.p>
      </motion.div>

      {/* v18: 认证卡片已移除 — 统一游客模式 */}

      {/* 底部特性展示 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.8 }}
        className="absolute bottom-12 left-0 right-0"
      >
        <div className="flex items-center justify-center gap-8 md:gap-16">
          <div className="flex items-center gap-2 text-white/40">
            <MapPin className="w-5 h-5" />
            <span className="text-sm tracking-wide">智能路线</span>
          </div>
          <div className="flex items-center gap-2 text-white/40">
            <Calendar className="w-5 h-5" />
            <span className="text-sm tracking-wide">行程规划</span>
          </div>
          <div className="flex items-center gap-2 text-white/40">
            <Camera className="w-5 h-5" />
            <span className="text-sm tracking-wide">旅行日记</span>
          </div>
        </div>
      </motion.div>
    </BackgroundHero>
  );
};

export default LandingPage;
