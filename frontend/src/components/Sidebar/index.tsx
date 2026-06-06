import React, { useState, useEffect } from 'react';
import { DatePicker, message, Switch, Card, Tag, Space, Divider } from 'antd';
import { Map, Trash2, Menu, Car, Bus, Footprints, Bike, CloudSun, Calendar, Route } from 'lucide-react';
import dayjs from 'dayjs';
import { generateRoute } from '@/api/route';
import type { DailyRoute } from '@/api/types';
import { useRouteStore } from '@/store/routeStore';
import styles from './Sidebar.module.css';

type TabType = 'plan' | 'itineraries';
type TransportMode = 'driving' | 'transit' | 'walking' | 'riding';

interface Itinerary {
  id: string;
  name: string;
  date: string;
  thumbnail?: string;
}

const Sidebar: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('plan');
  const [travelDescription, setTravelDescription] = useState('');
  const [transportMode, setTransportMode] = useState<TransportMode>('riding');
  const [travelDate, setTravelDate] = useState(dayjs().format('YYYY-MM-DD'));
  const [isGenerating, setIsGenerating] = useState(false);
  const [weatherAware, setWeatherAware] = useState(true);

  // 模拟行程数据（实际应从 store 获取）
  const [itineraries] = useState<Itinerary[]>([]);

  // 从 store 获取状态和方法
  const setRoute = useRouteStore((s) => s.setRoute);
  const setLoading = useRouteStore((s) => s.setLoading);
  const setError = useRouteStore((s) => s.setError);
  const routeId = useRouteStore((s) => s.routeId);
  const dailyRoutes = useRouteStore((s) => s.dailyRoutes);
  const weatherData = useRouteStore((s) => s.weatherData);
  const summary = useRouteStore((s) => s.summary);

  // 当路线生成成功后，保存用户输入的信息到 store
  useEffect(() => {
    if (routeId && dailyRoutes.length > 0) {
      // 路线已生成，保存用户输入的信息
      useRouteStore.getState().setTravelDescription(travelDescription);
      useRouteStore.getState().setTransportMode(transportMode);
      useRouteStore.getState().setTravelDate(travelDate);
    }
  }, [routeId, dailyRoutes.length, travelDescription, transportMode, travelDate]);

  const transportOptions: { value: TransportMode; label: string; icon: React.ReactNode }[] = [
    { value: 'driving', label: '驾车', icon: <Car size={16} /> },
    { value: 'transit', label: '公交', icon: <Bus size={16} /> },
    { value: 'walking', label: '步行', icon: <Footprints size={16} /> },
    { value: 'riding', label: '骑行', icon: <Bike size={16} /> },
  ];

  const getTransportIcon = (mode: TransportMode) => {
    const option = transportOptions.find(o => o.value === mode);
    return option?.icon || <Car size={16} />;
  };

  const handleGenerate = async () => {
    if (!travelDescription.trim()) {
      message.warning('请输入旅行描述');
      return;
    }

    setIsGenerating(true);
    setLoading(true);
    setError(null);

    try {
      console.log('生成路线', {
        input: travelDescription,
        options: {
          transport: transportMode,
          start_time: travelDate,
          consider_weather: weatherAware,
        },
      });

      const response = await generateRoute({
        text: travelDescription,
        transport_mode: transportMode,
        start_date: travelDate,
        consider_weather: weatherAware,
      });

      if (response.success && response.daily_routes) {
        // 直接使用 API 返回的 DailyRoute[] 类型
        const dailyRoutes: DailyRoute[] = response.daily_routes;
        
        setRoute(response.intent?.area || 'route', dailyRoutes, response.summary);
        message.success('路线生成成功！');
      } else {
        setError(response.message || '路线生成失败');
        message.error(response.message || '路线生成失败');
      }
    } catch (error: any) {
      console.error('生成路线失败:', error);
      setError(error.message || '生成路线时发生错误');
      message.error('生成路线失败，请稍后重试');
    } finally {
      setIsGenerating(false);
      setLoading(false);
    }
  };

  const handleDateChange = (date: dayjs.Dayjs | null) => {
    if (date) {
      setTravelDate(date.format('YYYY-MM-DD'));
    }
  };

  // 检查是否有已生成的路线
  const hasGeneratedRoute = routeId && dailyRoutes.length > 0;

  return (
    <aside className={styles.sidebar}>
      {/* 顶部标题栏 */}
      <div className={styles.header}>
        <button className={styles.hamburgerBtn} aria-label="菜单">
          <Menu size={20} />
        </button>
        <h1 className={styles.title}>本地生活路线规划</h1>
      </div>

      {/* 标签页切换 */}
      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${activeTab === 'plan' ? styles.active : ''}`}
          onClick={() => setActiveTab('plan')}
        >
          规划路线
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'itineraries' ? styles.active : ''}`}
          onClick={() => setActiveTab('itineraries')}
        >
          我的行程
        </button>
      </div>

      {/* 规划路线面板 */}
      {activeTab === 'plan' && (
        <div className={styles.panel}>
          {/* 如果有已生成的路线，显示路线信息摘要 */}
          {hasGeneratedRoute && (
            <>
              <Card 
                title={
                  <Space>
                    <Route size={16} />
                    <span>当前路线信息</span>
                  </Space>
                }
                size="small"
                className={styles.routeInfoCard}
              >
                {/* 旅行描述 */}
                <div className={styles.infoSection}>
                  <div className={styles.infoLabel}>
                    <Map size={14} />
                    <span>旅行描述</span>
                  </div>
                  <div className={styles.infoValue}>
                    {travelDescription || '未设置'}
                  </div>
                </div>

                <Divider style={{ margin: '12px 0' }} />

                {/* 交通方式 */}
                <div className={styles.infoSection}>
                  <div className={styles.infoLabel}>
                    <Car size={14} />
                    <span>交通方式</span>
                  </div>
                  <div className={styles.infoValue}>
                    <Tag icon={getTransportIcon(transportMode)} color="blue">
                      {transportOptions.find(o => o.value === transportMode)?.label}
                    </Tag>
                  </div>
                </div>

                <Divider style={{ margin: '12px 0' }} />

                {/* 出行日期 */}
                <div className={styles.infoSection}>
                  <div className={styles.infoLabel}>
                    <Calendar size={14} />
                    <span>出行日期</span>
                  </div>
                  <div className={styles.infoValue}>
                    <Tag icon={<Calendar size={12} />} color="green">
                      {travelDate}
                    </Tag>
                  </div>
                </div>

                <Divider style={{ margin: '12px 0' }} />

                {/* 天气感知 */}
                <div className={styles.infoSection}>
                  <div className={styles.infoLabel}>
                    <CloudSun size={14} />
                    <span>天气感知</span>
                  </div>
                  <div className={styles.infoValue}>
                    <Tag color={weatherAware ? 'success' : 'default'}>
                      {weatherAware ? '已开启' : '已关闭'}
                    </Tag>
                    {weatherAware && Object.keys(weatherData).length > 0 && (
                      <span className={styles.weatherHint}>
                        • 已获取 {Object.keys(weatherData).length} 天天气数据
                      </span>
                    )}
                  </div>
                </div>

                {/* 路线统计 */}
                {summary && (
                  <>
                    <Divider style={{ margin: '12px 0' }} />
                    <div className={styles.statsGrid}>
                      <div className={styles.statItem}>
                        <span className={styles.statValue}>
                          {(summary.total_distance / 1000).toFixed(1)}
                        </span>
                        <span className={styles.statLabel}>公里</span>
                      </div>
                      <div className={styles.statItem}>
                        <span className={styles.statValue}>
                          {Math.round(summary.total_duration / 60)}
                        </span>
                        <span className={styles.statLabel}>分钟</span>
                      </div>
                      <div className={styles.statItem}>
                        <span className={styles.statValue}>
                          {summary.total_pois}
                        </span>
                        <span className={styles.statLabel}>个地点</span>
                      </div>
                    </div>
                  </>
                )}
              </Card>

              <Divider style={{ margin: '16px 0' }} />
            </>
          )}

          {/* 旅行描述输入 */}
          <div className={styles.fieldGroup}>
            <label className={styles.label}>旅行描述</label>
            <textarea
              className={styles.textarea}
              placeholder="我想去外滩看夜景然后..."
              value={travelDescription}
              onChange={(e) => setTravelDescription(e.target.value)}
              rows={4}
            />
          </div>

          {/* 交通方式 */}
          <div className={styles.fieldGroup}>
            <label className={styles.label}>交通方式</label>
            <div className={styles.transportGroup}>
              {transportOptions.map((option) => (
                <button
                  key={option.value}
                  className={`${styles.transportBtn} ${
                    transportMode === option.value ? styles.active : ''
                  }`}
                  onClick={() => setTransportMode(option.value)}
                >
                  <span className={styles.transportIcon}>{option.icon}</span>
                  <span>{option.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 出行日期 */}
          <div className={styles.fieldGroup}>
            <label className={styles.label}>出行日期</label>
            <DatePicker
              className={styles.datePicker}
              value={dayjs(travelDate)}
              onChange={handleDateChange}
              format="YYYY-MM-DD"
              allowClear={false}
              suffixIcon={<span className={styles.calendarIcon}>📅</span>}
            />
          </div>

          {/* 天气感知 */}
          <div className={styles.fieldGroup}>
            <div className={styles.weatherAwareRow}>
              <Switch
                checked={weatherAware}
                onChange={setWeatherAware}
                className={styles.weatherSwitch}
                size="small"
              />
              <div className={styles.weatherText}>
                <span className={styles.weatherLabel}>天气感知</span>
                <span className={styles.weatherHint}>结合实时天气优化路线</span>
              </div>
            </div>
          </div>

          {/* 生成路线按钮 */}
          <button
            className={styles.generateButton}
            onClick={handleGenerate}
            disabled={isGenerating}
          >
            {isGenerating ? '生成中...' : (hasGeneratedRoute ? '✨ 重新生成路线' : '✨ 生成路线')}
          </button>
        </div>
      )}

      {/* 我的行程面板 */}
      {activeTab === 'itineraries' && (
        <div className={styles.panel}>
          {itineraries.length === 0 ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyIconWrapper}>
                <Map size={48} className={styles.emptyIcon} />
              </div>
              <p className={styles.emptyTitle}>暂无行程</p>
              <p className={styles.emptyText}>去规划一个吧</p>
              <button
                className={styles.emptyButton}
                onClick={() => setActiveTab('plan')}
              >
                去规划
              </button>
            </div>
          ) : (
            <div className={styles.itineraryList}>
              {itineraries.map((item) => (
                <div key={item.id} className={styles.itineraryCard}>
                  <div className={styles.itineraryThumbnail}>
                    {item.thumbnail ? (
                      <img src={item.thumbnail} alt={item.name} />
                    ) : (
                      <Map size={24} />
                    )}
                  </div>
                  <div className={styles.itineraryInfo}>
                    <span className={styles.itineraryName}>{item.name}</span>
                    <span className={styles.itineraryDate}>{item.date}</span>
                  </div>
                  <button className={styles.deleteButton}>
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
};

export default Sidebar;
