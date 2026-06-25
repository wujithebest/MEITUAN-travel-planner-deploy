import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
  const navigate = useNavigate();
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
          {/* v18: 封锁注册/登录 — 仅保留游客进入 */}
          <p className="text-white/60 text-center text-sm mb-6">无需注册，直接开始探索</p>

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
