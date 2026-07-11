import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { Sparkles, MapPin, Calendar, Camera } from 'lucide-react';
import BackgroundHero from '../../components/BackgroundHero';
import { useUserStore, clearClientSessionCache } from '../../store/userStore';

const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const { ensureGuestSession } = useUserStore();

  const [showGuestEntry, setShowGuestEntry] = useState(false);

  useEffect(() => {
    // Clean any stale logout marker
    sessionStorage.removeItem('just-logged-out');

    // If already authenticated (valid token), redirect straight to planner
    const { isLoggedIn, token } = useUserStore.getState();
    if (isLoggedIn || token) {
      navigate('/app', { replace: true });
      return;
    }

    // Otherwise stay on landing page — user must click guest entry
    setShowGuestEntry(true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGuestEnter = async () => {
    await clearClientSessionCache();
    ensureGuestSession();
    navigate('/app', { replace: true });
  };

  // v18: 所有入口统一走游客模式，不再展示 AuthCard
  return (
    <BackgroundHero>
      {/* 主标题区域 — 四行内容统一 flex-column 居中 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.1 }}
        className="flex flex-col items-center text-center"
      >
        {/* AI 标签 */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 mb-28 md:mb-32"
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
          className="text-6xl md:text-7xl lg:text-8xl font-bold text-white tracking-wider mb-4"
          style={{
            fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", Arial, sans-serif',
            letterSpacing: '0.05em',
            textShadow: '0 4px 30px rgba(0, 0, 0, 0.3)',
          }}
        >
          言途
        </motion.h1>

        {/* 主标题副行 */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
          className="text-2xl md:text-3xl lg:text-4xl text-white/65 font-light tracking-wide mb-16 md:mb-20"
        >
          ——本地生活路线规划
        </motion.p>

        {/* 副标题 */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.5 }}
          className="text-lg md:text-xl text-white/60 font-light tracking-wide max-w-xl mb-28 md:mb-32"
        >
          智能规划 · 沉浸体验 · 未来旅行
        </motion.p>

        {/* 退出登录后的游客入口按钮 */}
        {showGuestEntry && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.6 }}
          >
            <button
              onClick={handleGuestEnter}
              className="px-8 py-3 rounded-xl text-lg font-bold text-gray-900"
              style={{
                background: 'linear-gradient(135deg, #FFD100 0%, #FFE033 100%)',
                boxShadow: '0 4px 24px rgba(255, 209, 0, 0.45)',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              游客模式进入
            </button>
          </motion.div>
        )}
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
