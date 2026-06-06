import React, { useState } from 'react';
import { Button, Tooltip } from 'antd';
import { 
  Route, 
  ChevronLeft, 
  ChevronRight
} from 'lucide-react';
import styles from './TravelSidebar.module.css';

interface TravelSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

interface NavItem {
  key: string;
  icon: React.ReactNode;
  label: string;
}

const TravelSidebar: React.FC<TravelSidebarProps> = ({ collapsed, onToggle }) => {
  const [activeNav, setActiveNav] = useState('plan');

  // 只保留规划路线功能
  const navItems: NavItem[] = [
    { key: 'plan', icon: <Route size={20} />, label: '规划路线' },
  ];

  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''}`}>
      <Button
        type="text"
        icon={collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        className={styles.collapseBtn}
        onClick={onToggle}
        aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
      />

      {!collapsed && (
        <nav className={styles.navigation}>
          {navItems.map((item) => (
            <Tooltip key={item.key} title={item.label} placement="right">
              <Button
                type="text"
                icon={item.icon}
                className={`${styles.navItem} ${activeNav === item.key ? styles.active : ''}`}
                onClick={() => setActiveNav(item.key)}
              >
                <span className={styles.navLabel}>{item.label}</span>
              </Button>
            </Tooltip>
          ))}
        </nav>
      )}

      {collapsed && (
        <nav className={styles.collapsedNav}>
          {navItems.map((item) => (
            <Tooltip key={item.key} title={item.label} placement="right">
              <Button
                type="text"
                icon={item.icon}
                className={`${styles.collapsedNavItem} ${activeNav === item.key ? styles.active : ''}`}
                onClick={() => setActiveNav(item.key)}
              />
            </Tooltip>
          ))}
        </nav>
      )}
    </aside>
  );
};

export default TravelSidebar;
