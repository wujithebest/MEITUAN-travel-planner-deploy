import React, { useState } from 'react';
import { Button, Tabs, Badge, Tooltip } from 'antd';
import { 
  ChevronRight, 
  Route, 
  Calendar, 
  MapPin,
  Clock,
  MoreHorizontal
} from 'lucide-react';
import { RouteTimeline } from '@/components/RouteTimeline';
import styles from './RoutePanel.module.css';

interface RoutePanelProps {
  collapsed: boolean;
  onToggle: () => void;
}

const RoutePanel: React.FC<RoutePanelProps> = ({ collapsed, onToggle }) => {
  const [activeTab, setActiveTab] = useState('timeline');

  const tabItems = [
    {
      key: 'timeline',
      label: (
        <span className={styles.tabLabel}>
          <Calendar size={14} />
          行程
        </span>
      ),
      children: <RouteTimeline />,
    },
    {
      key: 'pois',
      label: (
        <span className={styles.tabLabel}>
          <MapPin size={14} />
          地点
        </span>
      ),
      children: (
        <div className={styles.poisContent}>
          <p className={styles.emptyText}>暂无地点数据</p>
        </div>
      ),
    },
    {
      key: 'routes',
      label: (
        <span className={styles.tabLabel}>
          <Route size={14} />
          路线
        </span>
      ),
      children: (
        <div className={styles.routesContent}>
          <p className={styles.emptyText}>暂无路线数据</p>
        </div>
      ),
    },
  ];

  return (
    <aside className={`${styles.panel} ${collapsed ? styles.collapsed : ''}`}>
      <Button
        type="text"
        icon={<ChevronRight size={16} className={collapsed ? '' : styles.chevronExpanded} />}
        className={styles.toggleBtn}
        onClick={onToggle}
        aria-label={collapsed ? '展开行程面板' : '折叠行程面板'}
      />

      {!collapsed && (
        <div className={styles.panelContent}>
          <div className={styles.panelHeader}>
            <div className={styles.headerLeft}>
              <Route size={18} className={styles.headerIcon} />
              <h3 className={styles.headerTitle}>行程概览</h3>
              <Badge count={7} className={styles.dayBadge} />
            </div>
            <Tooltip title="更多选项">
              <Button type="text" size="small" icon={<MoreHorizontal size={16} />} />
            </Tooltip>
          </div>

          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={tabItems}
            className={styles.tabs}
            size="small"
          />
        </div>
      )}

      {collapsed && (
        <div className={styles.collapsedContent}>
          <Tooltip title="行程概览" placement="left">
            <Button
              type="text"
              icon={<Route size={18} />}
              className={styles.collapsedIcon}
            />
          </Tooltip>
          <Badge count={7} className={styles.collapsedBadge} />
        </div>
      )}
    </aside>
  );
};

export default RoutePanel;
