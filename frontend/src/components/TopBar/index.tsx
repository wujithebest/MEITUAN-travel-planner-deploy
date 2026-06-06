import React, { useState } from 'react';
import { Search, Mic, Sun, Car, ChevronDown } from 'lucide-react';
import styles from './TopBar.module.css';

const TopBar: React.FC = () => {
  const [searchValue, setSearchValue] = useState('');

  return (
    <header className={styles.topBar}>
      {/* 左侧 Logo */}
      <div className={styles.leftSection}>
        <div className={styles.logo}>
          <div className={styles.logoIcon}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"
                fill="#FFD700"
                stroke="#FFD700"
                strokeWidth="1"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div className={styles.logoTextContainer}>
            <span className={styles.logoTitle}>本地生活路线规划</span>
            <span className={styles.logoSubtitle}></span>
          </div>
        </div>
      </div>

      {/* 中间搜索框 */}
      <div className={styles.centerSection}>
        <div className={styles.searchBar}>
          <Search size={18} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="Search for places, attractions, or activities..."
            className={styles.searchInput}
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
          />
          <Mic size={18} className={styles.micIcon} />
        </div>
      </div>

      {/* 右侧工具区 */}
      <div className={styles.rightSection}>
        {/* 天气 */}
        <div className={styles.weatherWidget}>
          <Sun size={20} className={styles.weatherIcon} />
          <div className={styles.weatherInfo}>
            <span className={styles.temperature}>23°C</span>
            <span className={styles.city}>Beijing</span>
          </div>
        </div>

        {/* 交通 */}
        <div className={styles.trafficWidget}>
          <Car size={20} className={styles.trafficIcon} />
          <span className={styles.trafficLabel}>Traffic</span>
          <span className={styles.trafficBadge}>Moderate</span>
        </div>

        {/* 用户信息 */}
        <div className={styles.userWidget}>
          <div className={styles.avatar}>
            <span>AC</span>
          </div>
          <span className={styles.userName}>Alex Chen</span>
          <ChevronDown size={16} className={styles.dropdownIcon} />
        </div>
      </div>
    </header>
  );
};

export default TopBar;
