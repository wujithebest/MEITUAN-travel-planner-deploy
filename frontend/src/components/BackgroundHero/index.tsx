import React from 'react';
import { motion } from 'framer-motion';

interface BackgroundHeroProps {
  children: React.ReactNode;
}

const BackgroundHero: React.FC<BackgroundHeroProps> = ({ children }) => {
  return (
    <div className="relative w-full h-screen overflow-hidden">
      {/* 背景图片层 */}
      <motion.div
        className="absolute inset-0 w-full h-full"
        initial={{ scale: 1.1 }}
        animate={{ scale: 1 }}
        transition={{ duration: 1.5, ease: 'easeOut' }}
      >
        <div
          className="absolute inset-0 w-full h-full bg-cover bg-center bg-no-repeat animate-scale-slow"
          style={{
            backgroundImage: "url('/images/shanghai.jpg')",
          }}
        />
      </motion.div>

      {/* 渐变遮罩层 - 增强文字可读性 */}
      <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-black/30 to-black/60" />

      {/* 顶部微光效果 */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent" />

      {/* 内容层 */}
      <div className="relative z-10 w-full h-full flex flex-col items-center justify-center">
        {children}
      </div>

      {/* 底部渐变 */}
      <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-black/50 to-transparent" />
    </div>
  );
};

export default BackgroundHero;
