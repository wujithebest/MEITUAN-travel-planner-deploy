import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Dropdown, Avatar, Button, Space, message } from 'antd';
import { 
  User, 
  Heart, 
  Map, 
  LogOut, 
  UserPlus,
  LogIn
} from 'lucide-react';
import { useUserStore } from '@/store/userStore';
import styles from './UserMenu.module.css';

const UserMenu: React.FC = () => {
  const { user, isLoggedIn, logout, ensureGuestSession } = useUserStore();
  const [open, setOpen] = useState(false);

  const handleLogout = () => {
    logout();
    setOpen(false);
    ensureGuestSession();  // v18: 退出后重新进入游客模式
  };

  const handleLogin = () => {
    // v18: 统一走游客模式
    ensureGuestSession();
  };

  const handleRegister = () => {
    // v18: 统一走游客模式
    ensureGuestSession();
  };

  // v18: 封锁注册/登录 — 未登录时仅显示游客入口
  if (!isLoggedIn || !user) {
    return (
      <Space>
        <Button
          type="text"
          icon={<LogIn size={16} />}
          onClick={handleLogin}
          className={styles.authBtn}
        >
          游客进入
        </Button>
      </Space>
    );
  }

  // 已登录状态的下拉菜单
  const menuItems = [
    {
      key: 'header',
      label: (
        <div className={styles.userInfo}>
          <Avatar 
            size={40} 
            src={user.avatar}
            className={styles.avatar}
          >
            {user.username?.[0]?.toUpperCase()}
          </Avatar>
          <div className={styles.userDetails}>
            <div className={styles.username}>{user.username}</div>
            <div className={styles.email}>{user.email}</div>
          </div>
        </div>
      ),
      disabled: true,
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'profile',
      icon: <User size={16} />,
      label: '个人中心',
      onClick: () => {
        setOpen(false);
        message.info('个人中心功能开发中');
      },
    },
    {
      key: 'preferences',
      icon: <Heart size={16} />,
      label: '我的偏好',
      onClick: () => {
        setOpen(false);
        message.info('偏好设置功能开发中');
      },
    },
    {
      key: 'trips',
      icon: <Map size={16} />,
      label: '我的行程',
      onClick: () => {
        setOpen(false);
        message.info('我的行程功能开发中');
      },
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'logout',
      icon: <LogOut size={16} />,
      label: '退出登录',
      danger: true,
      onClick: handleLogout,
    },
  ];

  return (
    <Dropdown
      menu={{ items: menuItems }}
      open={open}
      onOpenChange={setOpen}
      trigger={['click']}
      placement="bottomRight"
      overlayClassName={styles.dropdown}
    >
      <div className={styles.userMenuTrigger}>
        <Avatar 
          size={32} 
          src={user.avatar}
          className={styles.avatarSmall}
        >
          {user.username?.[0]?.toUpperCase()}
        </Avatar>
        <span className={styles.usernameSmall}>{user.username}</span>
      </div>
    </Dropdown>
  );
};

export default UserMenu;
