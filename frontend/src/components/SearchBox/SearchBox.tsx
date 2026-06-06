import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Search, MapPin, Plus, X } from 'lucide-react';
import { searchPOI, parseLocation, GaodePOI } from '@/api/gaode';
import styles from './SearchBox.module.css';

interface SearchBoxProps {
  onSelectPOI?: (poi: GaodePOI) => void;
  onAddToTrip?: (poi: GaodePOI) => void;
  mapInstance?: any; // 高德地图实例
}

const SearchBox: React.FC<SearchBoxProps> = ({ onSelectPOI, onAddToTrip, mapInstance }) => {
  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState<GaodePOI[]>([]);
  const [loading, setLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedPOI, setSelectedPOI] = useState<GaodePOI | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 防抖搜索
  const handleSearch = useCallback(
    (value: string) => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }

      if (!value.trim()) {
        setResults([]);
        setShowDropdown(false);
        return;
      }

      debounceTimerRef.current = setTimeout(async () => {
        setLoading(true);
        try {
          const pois = await searchPOI(value);
          setResults(pois);
          setShowDropdown(true);
        } catch (error) {
          console.error('搜索失败:', error);
          setResults([]);
        } finally {
          setLoading(false);
        }
      }, 500); // 500ms 防抖
    },
    []
  );

  // 输入变化
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setKeyword(value);
    setSelectedPOI(null); // 清除选中状态
    handleSearch(value);
  };

  // 点击结果项
  const handleSelectResult = (poi: GaodePOI) => {
    setKeyword(poi.name);
    setSelectedPOI(poi);
    setShowDropdown(false);

    // 地图定位并添加标记
    if (mapInstance) {
      const coords = parseLocation(poi.location);
      if (coords) {
        // 设置地图中心
        mapInstance.setCenter([coords.lng, coords.lat]);
        mapInstance.setZoom(15);

        // 添加标记
        // @ts-ignore
        const AMap = window.AMap;
        if (AMap) {
          const marker = new AMap.Marker({
            position: [coords.lng, coords.lat],
            title: poi.name,
          });
          mapInstance.add(marker);
        }
      }
    }

    // 回调
    if (onSelectPOI) {
      onSelectPOI(poi);
    }
  };

  // 添加到行程
  const handleAddToTrip = () => {
    if (selectedPOI && onAddToTrip) {
      onAddToTrip(selectedPOI);
      // 清除选中状态
      setSelectedPOI(null);
      setKeyword('');
    }
  };

  // 清除输入
  const handleClear = () => {
    setKeyword('');
    setResults([]);
    setShowDropdown(false);
    setSelectedPOI(null);
  };

  // 点击外部关闭下拉
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // 清理定时器
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  return (
    <div className={styles.searchBox} ref={containerRef}>
      <div className={styles.inputWrapper}>
        <Search size={16} className={styles.searchIcon} />
        <input
          type="text"
          className={styles.input}
          placeholder="搜索地点、景点、餐厅..."
          value={keyword}
          onChange={handleInputChange}
          onFocus={() => {
            if (results.length > 0) {
              setShowDropdown(true);
            }
          }}
        />
        {keyword && (
          <button className={styles.clearBtn} onClick={handleClear}>
            <X size={14} />
          </button>
        )}
        {loading && <div className={styles.spinner} />}
      </div>

      {/* 下拉结果列表 */}
      {showDropdown && results.length > 0 && (
        <div className={styles.dropdown}>
          {results.map((poi) => (
            <div
              key={poi.id}
              className={styles.resultItem}
              onClick={() => handleSelectResult(poi)}
            >
              <MapPin size={14} className={styles.resultIcon} />
              <div className={styles.resultContent}>
                <div className={styles.resultName}>{poi.name}</div>
                <div className={styles.resultMeta}>
                  <span className={styles.resultType}>{poi.type}</span>
                  {poi.address && (
                    <span className={styles.resultAddress}>{poi.address}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 选中后显示"添加到行程"按钮 */}
      {selectedPOI && (
        <button className={styles.addToTripBtn} onClick={handleAddToTrip}>
          <Plus size={14} />
          <span>添加到行程</span>
        </button>
      )}
    </div>
  );
};

export default SearchBox;
