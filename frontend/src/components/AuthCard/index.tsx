import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Mail, Lock, User, ArrowRight, Sparkles } from 'lucide-react';
import AnimatedButton from '../AnimatedButton';

interface AuthCardProps {
  onLogin?: (email: string, password: string) => Promise<void>;
  onRegister?: (username: string, email: string, password: string) => Promise<void>;
  onGuestMode?: () => void;
  isLoading?: boolean;
}

type AuthTab = 'login' | 'register';

const AuthCard: React.FC<AuthCardProps> = ({
  onLogin,
  onRegister,
  onGuestMode,
  isLoading = false,
}) => {
  const [activeTab, setActiveTab] = useState<AuthTab>('login');
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [registerUsername, setRegisterUsername] = useState('');
  const [registerEmail, setRegisterEmail] = useState('');
  const [registerPassword, setRegisterPassword] = useState('');

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (onLogin) {
      await onLogin(loginEmail, loginPassword);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (onRegister) {
      await onRegister(registerUsername, registerEmail, registerPassword);
    }
  };

  const tabVariants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: -10 },
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 30, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.6, delay: 0.3, ease: 'easeOut' }}
      className="w-full max-w-md"
    >
      {/* 玻璃拟态卡片 */}
      <div
        className="relative rounded-3xl overflow-hidden"
        style={{
          background: 'rgba(255, 255, 255, 0.08)',
          backdropFilter: 'blur(40px) saturate(180%)',
          WebkitBackdropFilter: 'blur(40px) saturate(180%)',
          border: '1px solid rgba(255, 255, 255, 0.15)',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1)',
        }}
      >
        {/* 顶部光泽效果 */}
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-white/40 to-transparent" />

        <div className="p-8">
          {/* Tab 切换 */}
          <div className="flex gap-2 mb-8 p-1 rounded-xl bg-white/5">
            <button
              onClick={() => setActiveTab('login')}
              className={`flex-1 py-2.5 px-4 rounded-lg text-sm font-medium transition-all duration-300 ${
                activeTab === 'login'
                  ? 'bg-white text-black shadow-lg'
                  : 'text-white/60 hover:text-white hover:bg-white/5'
              }`}
            >
              登录
            </button>
            <button
              onClick={() => setActiveTab('register')}
              className={`flex-1 py-2.5 px-4 rounded-lg text-sm font-medium transition-all duration-300 ${
                activeTab === 'register'
                  ? 'bg-white text-black shadow-lg'
                  : 'text-white/60 hover:text-white hover:bg-white/5'
              }`}
            >
              注册
            </button>
          </div>

          {/* 表单内容 */}
          <AnimatePresence mode="wait">
            {activeTab === 'login' ? (
              <motion.form
                key="login"
                variants={tabVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                transition={{ duration: 0.3 }}
                onSubmit={handleLogin}
                className="space-y-5"
              >
                {/* 邮箱输入 */}
                <div className="flex items-center gap-3 p-3.5 rounded-xl bg-white/5 border border-white/10 focus-within:border-white/30 focus-within:bg-white/10 transition-all duration-300 group">
                  <Mail className="w-5 h-5 text-white/40 group-focus-within:text-white/70 transition-colors flex-shrink-0" />
                  <input
                    type="email"
                    value={loginEmail}
                    onChange={(e) => setLoginEmail(e.target.value)}
                    placeholder="邮箱地址"
                    required
                    className="flex-1 bg-transparent border-none outline-none text-white placeholder-white/30 min-w-0"
                  />
                </div>

                {/* 密码输入 */}
                <div className="flex items-center gap-3 p-3.5 rounded-xl bg-white/5 border border-white/10 focus-within:border-white/30 focus-within:bg-white/10 transition-all duration-300 group">
                  <Lock className="w-5 h-5 text-white/40 group-focus-within:text-white/70 transition-colors flex-shrink-0" />
                  <input
                    type="password"
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    placeholder="密码"
                    required
                    minLength={6}
                    className="flex-1 bg-transparent border-none outline-none text-white placeholder-white/30 min-w-0"
                  />
                </div>

                {/* 登录按钮 */}
                <AnimatedButton
                  type="submit"
                  variant="primary"
                  size="lg"
                  loading={isLoading}
                  className="w-full"
                >
                  登录
                  <ArrowRight className="w-5 h-5" />
                </AnimatedButton>
              </motion.form>
            ) : (
              <motion.form
                key="register"
                variants={tabVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                transition={{ duration: 0.3 }}
                onSubmit={handleRegister}
                className="space-y-5"
              >
                {/* 用户名输入 */}
                <div className="flex items-center gap-3 p-3.5 rounded-xl bg-white/5 border border-white/10 focus-within:border-white/30 focus-within:bg-white/10 transition-all duration-300 group">
                  <User className="w-5 h-5 text-white/40 group-focus-within:text-white/70 transition-colors flex-shrink-0" />
                  <input
                    type="text"
                    value={registerUsername}
                    onChange={(e) => setRegisterUsername(e.target.value)}
                    placeholder="用户名"
                    required
                    className="flex-1 bg-transparent border-none outline-none text-white placeholder-white/30 min-w-0"
                  />
                </div>

                {/* 邮箱输入 */}
                <div className="flex items-center gap-3 p-3.5 rounded-xl bg-white/5 border border-white/10 focus-within:border-white/30 focus-within:bg-white/10 transition-all duration-300 group">
                  <Mail className="w-5 h-5 text-white/40 group-focus-within:text-white/70 transition-colors flex-shrink-0" />
                  <input
                    type="email"
                    value={registerEmail}
                    onChange={(e) => setRegisterEmail(e.target.value)}
                    placeholder="邮箱地址"
                    required
                    className="flex-1 bg-transparent border-none outline-none text-white placeholder-white/30 min-w-0"
                  />
                </div>

                {/* 密码输入 */}
                <div className="flex items-center gap-3 p-3.5 rounded-xl bg-white/5 border border-white/10 focus-within:border-white/30 focus-within:bg-white/10 transition-all duration-300 group">
                  <Lock className="w-5 h-5 text-white/40 group-focus-within:text-white/70 transition-colors flex-shrink-0" />
                  <input
                    type="password"
                    value={registerPassword}
                    onChange={(e) => setRegisterPassword(e.target.value)}
                    placeholder="密码"
                    required
                    minLength={6}
                    className="flex-1 bg-transparent border-none outline-none text-white placeholder-white/30 min-w-0"
                  />
                </div>

                {/* 注册按钮 */}
                <AnimatedButton
                  type="submit"
                  variant="primary"
                  size="lg"
                  loading={isLoading}
                  className="w-full"
                >
                  创建账户
                  <Sparkles className="w-5 h-5" />
                </AnimatedButton>
              </motion.form>
            )}
          </AnimatePresence>

          {/* 分隔线 */}
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-white/10" />
            </div>
            <div className="relative flex justify-center text-xs">
              <span className="px-4 text-white/40 bg-transparent">或</span>
            </div>
          </div>

          {/* 游客模式 */}
          <AnimatedButton
            type="button"
            variant="ghost"
            size="md"
            onClick={onGuestMode}
            className="w-full text-sm"
          >
            游客模式进入
            <ArrowRight className="w-4 h-4" />
          </AnimatedButton>
        </div>

        {/* 底部光泽 */}
        <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent" />
      </div>
    </motion.div>
  );
};

export default AuthCard;
