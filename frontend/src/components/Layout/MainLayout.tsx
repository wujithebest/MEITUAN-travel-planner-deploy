import React, { useState, useMemo } from 'react';
import TopBar from '@/components/TopBar/TopBar';
import TravelSidebar from '@/components/TravelSidebar/TravelSidebar';
import RoutePanel from '@/components/RoutePanel/RoutePanel';
import BottomStats from '@/components/BottomStats/BottomStats';
import { useRouteStore } from '@/store/routeStore';
import styles from './MainLayout.module.css';

interface MainLayoutProps {
  children: React.ReactNode;
}

const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);

  const summary = useRouteStore((s) => s.summary);
  const loading = useRouteStore((s) => s.loading);

  const stats = useMemo(() => {
    if (!summary) return null;
    return {
      totalDistance: summary.total_distance,
      totalDuration: summary.total_duration,
      estimatedCost: 0,
      totalStops: summary.total_pois,
    };
  }, [summary]);

  return (
    <div className={styles.layout}>
      <TopBar
        onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
        onToggleRightPanel={() => setRightPanelCollapsed(!rightPanelCollapsed)}
        isRightPanelVisible={!rightPanelCollapsed}
      />

      <div className={styles.mainContainer}>
        <TravelSidebar
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        />

        <main className={styles.content}>
          {children}
        </main>

        <RoutePanel
          collapsed={rightPanelCollapsed}
          onToggle={() => setRightPanelCollapsed(!rightPanelCollapsed)}
        />
      </div>

      <BottomStats stats={stats} loading={loading} />
    </div>
  );
};

export default MainLayout;
