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
  const navigate = useNavigate();
  const { user, isLoggedIn, logout } = useUserStore();
  const [open, setOpen] = useState(false);

  const handleLogout = () => {
    logout();
    setOpen(false);
    navigate('/login');
  };

  const handleLogin = () => {
    navigate('/login');
  };

  const handleRegister = () => {
    navigate('/register');
  };

  // 未登录状态
  if (!isLoggedIn || !user) {
    return (
      <Space>
        <Button 
          type="text" 
          icon={<LogIn size={16} />}
          onClick={handleLogin}
          className={styles.authBtn}
        >
          登录
        </Button>
        <Button 
          type="primary" 
          icon={<UserPlus size={16} />}
          onClick={handleRegister}
          className={styles.authBtn}
        >
          注册
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
