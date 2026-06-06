import React from 'react';
import { Button, Space, Badge, Avatar, Dropdown } from 'antd';
import { 
  Menu, 
  Bell, 
  Settings, 
  User, 
  LogOut, 
  Map,
  MessageSquare,
  BookOpen
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import styles from './TopBar.module.css';

interface TopBarProps {
  onToggleSidebar: () => void;
  onToggleRightPanel: () => void;
  isRightPanelVisible: boolean;
}

const TopBar: React.FC<TopBarProps> = ({ 
  onToggleSidebar, 
  onToggleRightPanel,
  isRightPanelVisible 
}) => {
  const navigate = useNavigate();

  const userMenuItems = [
    {
      key: 'profile',
      icon: <User size={14} />,
      label: '个人中心',
    },
    {
      key: 'settings',
      icon: <Settings size={14} />,
      label: '设置',
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'logout',
      icon: <LogOut size={14} />,
      label: '退出登录',
      danger: true,
    },
  ];

  const handleMenuClick = ({ key }: { key: string }) => {
    switch (key) {
      case 'profile':
        // navigate('/profile');
        break;
      case 'settings':
        // navigate('/settings');
        break;
      case 'logout':
        localStorage.removeItem('token');
        navigate('/login');
        break;
    }
  };

  return (
    <header className={styles.topBar}>
      <div className={styles.leftSection}>
        <Button
          type="text"
          icon={<Menu size={20} />}
          className={styles.menuButton}
          onClick={onToggleSidebar}
          aria-label="切换侧边栏"
        />
        <div className={styles.logo}>
          <Map size={24} className={styles.logoIcon} />
          <div className={styles.logoTextContainer}>
            <span className={styles.logoTitle}>本地生活路线规划</span>
            <span className={styles.logoSubtitle}></span>
          </div>
        </div>
      </div>

      <div className={styles.centerSection}>
        <div className={styles.searchBar}>
          <input
            type="text"
            placeholder="搜索景点、活动..."
            className={styles.searchInput}
          />
        </div>
      </div>

      <div className={styles.rightSection}>
        <Space size={8}>
          <Button
            type="text"
            icon={<MessageSquare size={18} />}
            className={styles.iconButton}
            onClick={() => navigate('/chat')}
            title="多人协作"
          />
          
          <Badge count={3} size="small">
            <Button
              type="text"
              icon={<Bell size={18} />}
              className={styles.iconButton}
              title="通知"
            />
          </Badge>

          <Button
            type="text"
            icon={<BookOpen size={18} />}
            className={styles.iconButton}
            onClick={() => navigate('/diary/1')}
            title="我的日记"
          />

          <Button
            type="text"
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <line x1="3" y1="9" x2="21" y2="9" />
                <line x1="9" y1="3" x2="9" y2="21" />
              </svg>
            }
            className={`${styles.iconButton} ${!isRightPanelVisible ? styles.active : ''}`}
            onClick={onToggleRightPanel}
            title={isRightPanelVisible ? '隐藏行程面板' : '显示行程面板'}
          />

          <Dropdown
            menu={{ items: userMenuItems, onClick: handleMenuClick }}
            placement="bottomRight"
            trigger={['click']}
          >
            <Button type="text" className={styles.avatarButton}>
              <Avatar 
                size={32} 
                style={{ backgroundColor: 'var(--primary-yellow)' }}
              >
                <User size={16} color="var(--text-primary)" />
              </Avatar>
            </Button>
          </Dropdown>
        </Space>
      </div>
    </header>
  );
};

export default TopBar;
