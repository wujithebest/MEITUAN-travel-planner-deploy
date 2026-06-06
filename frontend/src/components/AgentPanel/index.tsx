import React, { useState, useEffect } from 'react';
import { Button, Tag, Drawer, Empty, Collapse, message } from 'antd';
import {
  CloseOutlined,
  EnvironmentOutlined,
  ShareAltOutlined,
  BulbOutlined,
  ReloadOutlined,
  ClockCircleOutlined,
  InfoCircleOutlined,
  DownOutlined,
  UpOutlined,
} from '@ant-design/icons';
import { 
  ChatMessage, 
  ExtractedPOI, 
  TravelIntent,
  ItineraryPreviewData 
} from '../../types/chat';
import styles from './AgentPanel.module.css';

interface AgentPanelProps {
  visible: boolean;
  roomId: string | null;
  messages: ChatMessage[];
  extractedIntent?: TravelIntent | null;
  onGenerateRoute: () => void;
  onGenerateItinerary: () => void;
  onClose: () => void;
}

const AgentPanel: React.FC<AgentPanelProps> = ({
  visible,
  roomId,
  messages,
  extractedIntent = null,
  onGenerateRoute,
  onGenerateItinerary,
  onClose,
}) => {
  const [extractedPOIs, setExtractedPOIs] = useState<ExtractedPOI[]>([]);
  const [intent, setIntent] = useState<TravelIntent | null>(extractedIntent);
  const [latestItinerary, setLatestItinerary] = useState<ItineraryPreviewData | null>(null);
  const [expandedDays, setExpandedDays] = useState<number[]>([1]);

  // 同步外部传入的intent
  useEffect(() => {
    setIntent(extractedIntent || null);
  }, [extractedIntent]);

  // 从消息中提取AI识别的地点、意图和行程方案
  useEffect(() => {
    const agentMessages = messages.filter((m) => m.sender.is_agent);
    const pois: ExtractedPOI[] = [];
    let detectedIntent: TravelIntent | null = null;
    let latestItin: ItineraryPreviewData | null = null;

    agentMessages.forEach((msg) => {
      if (msg.content.metadata?.extracted_pois) {
        pois.push(...msg.content.metadata.extracted_pois);
      }
      if (msg.content.metadata?.intent) {
        detectedIntent = msg.content.metadata.intent;
      }
      // 提取最新的行程预览
      if (msg.content.type === 'itinerary_preview' && msg.content.route_data) {
        latestItin = msg.content.route_data as ItineraryPreviewData;
      }
    });

    setExtractedPOIs(pois);
    if (detectedIntent) {
      setIntent(detectedIntent);
    }
    if (latestItin) {
      setLatestItinerary(latestItin);
    }
  }, [messages]);

  const toggleDay = (dayIndex: number) => {
    setExpandedDays(prev => 
      prev.includes(dayIndex) 
        ? prev.filter(d => d !== dayIndex)
        : [...prev, dayIndex]
    );
  };

  const handleApplyToMap = () => {
    if (latestItinerary) {
      // 这里应该调用地图组件的方法
      message.success('行程已应用到地图');
      console.log('Applying itinerary to map:', latestItinerary);
    }
  };

  const handleRegenerate = () => {
    onGenerateItinerary();
  };

  return (
    <Drawer
      title={null}
      placement="right"
      onClose={onClose}
      open={visible}
      width={360}
      className={styles.agentDrawer}
      styles={{
        body: { padding: 0 },
      }}
      closeIcon={null}
    >
      <div className={styles.agentPanel}>
        <div className={styles.panelHeader}>
          <h3>
            <img 
              src="/ai-travel-logo.png" 
              alt="AI旅行助手" 
              className={styles.headerLogo}
            />
            AI旅行助手
          </h3>
          <Button
            icon={<CloseOutlined />}
            type="text"
            size="small"
            onClick={onClose}
          />
        </div>

        {/* 行程方案卡片 (新增 - 优先显示) */}
        {latestItinerary && (
          <div className={styles.section}>
            <h4>📋 最新行程方案</h4>
            <div className={styles.itineraryCard}>
              {/* 摘要 */}
              <div className={styles.itineraryHeader}>
                <div className={styles.itineraryTitle}>
                  <EnvironmentOutlined className={styles.itineraryIcon} />
                  <span>{latestItinerary.summary}</span>
                </div>
                {latestItinerary.total_distance && (
                  <Tag color="blue" className={styles.distanceTag}>
                    总距离: {latestItinerary.total_distance}
                  </Tag>
                )}
              </div>

              {/* 每日行程 */}
              <div className={styles.itineraryDays}>
                {latestItinerary.days.map((day) => (
                  <div key={day.day_index} className={styles.dayCard}>
                    <div 
                      className={styles.dayHeader}
                      onClick={() => toggleDay(day.day_index)}
                    >
                      <div className={styles.dayTitle}>
                        <ClockCircleOutlined />
                        <span>{day.title}</span>
                      </div>
                      {expandedDays.includes(day.day_index) 
                        ? <UpOutlined /> 
                        : <DownOutlined />
                      }
                    </div>
                    
                    {expandedDays.includes(day.day_index) && (
                      <div className={styles.dayContent}>
                        <pre className={styles.dayDetail}>{day.detail}</pre>
                        {day.anchors.length > 0 && (
                          <div className={styles.dayAnchors}>
                            {day.anchors.map((anchor, idx) => (
                              <Tag key={idx} color="cyan">{anchor}</Tag>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* 推荐理由 */}
              {latestItinerary.anchors.length > 0 && (
                <div className={styles.reasonsSection}>
                  <div className={styles.reasonsTitle}>
                    <InfoCircleOutlined /> 推荐理由
                  </div>
                  {latestItinerary.anchors.map((anchor, idx) => (
                    <div key={idx} className={styles.reasonItem}>
                      <span className={styles.reasonName}>{anchor.name}：</span>
                      <span className={styles.reasonText}>{anchor.reason}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 操作按钮 */}
              <div className={styles.itineraryActions}>
                <Button 
                  type="primary" 
                  icon={<EnvironmentOutlined />}
                  onClick={handleApplyToMap}
                  className={styles.applyButton}
                >
                  应用到地图
                </Button>
                <Button 
                  icon={<ReloadOutlined />}
                  onClick={handleRegenerate}
                  className={styles.regenerateButton}
                >
                  重新规划
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* 意图识别状态 */}
        <div className={styles.section}>
          <h4>🎯 已识别的旅行意图</h4>
          {intent ? (
            <div className={styles.intentCard}>
              {intent.destination && <Tag color="blue">{intent.destination}</Tag>}
              {intent.days && <Tag color="green">{intent.days}天</Tag>}
              {intent.themes?.map((t) => (
                <Tag key={t} color="orange">
                  {t}
                </Tag>
              ))}
              {intent.budget && <Tag color="purple">{intent.budget}</Tag>}
            </div>
          ) : (
            <div className={styles.emptyState}>
              <BulbOutlined className={styles.emptyIcon} />
              <p>继续聊天，我会自动识别大家的旅行计划...</p>
            </div>
          )}
        </div>

        {/* 提取的地点 */}
        <div className={styles.section}>
          <h4>📍 讨论中提到的地点 ({extractedPOIs.length})</h4>
          {extractedPOIs.length > 0 ? (
            <div className={styles.poiList}>
              {extractedPOIs.map((poi) => (
                <div key={poi.id} className={styles.poiItem}>
                  <span className={styles.poiName}>{poi.name}</span>
                  <Tag
                    color={poi.confidence > 0.7 ? 'green' : 'orange'}
                    className={styles.confidenceTag}
                  >
                    {Math.round(poi.confidence * 100)}%
                  </Tag>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.emptyState}>
              <p>还没有识别到具体地点</p>
            </div>
          )}
        </div>

        {/* 快捷操作 */}
        <div className={styles.section}>
          <h4>⚡ 快捷操作</h4>
          <div className={styles.actions}>
            <Button
              type="primary"
              block
              icon={<EnvironmentOutlined />}
              onClick={onGenerateItinerary}
            >
              生成行程方案
            </Button>
            <Button 
              block 
              icon={<ReloadOutlined />}
              onClick={onGenerateRoute}
              disabled={extractedPOIs.length === 0}
            >
              生成路线预览
            </Button>
            <Button block icon={<ShareAltOutlined />}>
              分享到地图
            </Button>
          </div>
        </div>

        {/* 提示 */}
        <div className={styles.tips}>
          <p>💡 在聊天中@旅行助手 或直接讨论想去的地方，我会实时记录并规划</p>
        </div>
      </div>
    </Drawer>
  );
};

export default AgentPanel;
