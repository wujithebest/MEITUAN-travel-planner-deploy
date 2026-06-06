import React, { useState } from 'react';
import { Avatar, Image, Tag, Button, Collapse } from 'antd';
import { 
  EnvironmentOutlined, 
  DownOutlined, 
  UpOutlined, 
  ReloadOutlined,
  ClockCircleOutlined,
  InfoCircleOutlined,
  QuestionCircleOutlined
} from '@ant-design/icons';
import dayjs from 'dayjs';
import RouteCard from '../RouteCard';
import { 
  ChatMessage, 
  POICardData, 
  ItineraryPreviewData,
  RouteCardData 
} from '../../types/chat';
import styles from './MessageBubble.module.css';

interface MessageBubbleProps {
  message: ChatMessage;
  onApplyToMap?: (data: ItineraryPreviewData) => void;
  onRegenerate?: () => void;
}

const currentUser = {
  id: 'current_user',
  name: '我',
  avatar: '',
};

// 简化的地点卡片组件
const SimplePOICard: React.FC<{ data: POICardData }> = ({ data }) => {
  return (
    <div className={styles.poiCard}>
      {data.image_url && (
        <div className={styles.poiImage}>
          <img src={data.image_url} alt={data.name} />
        </div>
      )}
      <div className={styles.poiInfo}>
        <div className={styles.poiName}>{data.name}</div>
        <div className={styles.poiAddress}>{data.address}</div>
        <div className={styles.poiMeta}>
          <Tag color="blue">{data.category}</Tag>
          {data.rating && <span className={styles.poiRating}>⭐ {data.rating.toFixed(1)}</span>}
        </div>
        {data.description && (
          <div className={styles.poiDescription}>{data.description}</div>
        )}
      </div>
    </div>
  );
};

// 行程预览卡片组件
const ItineraryPreviewCard: React.FC<{ 
  data: ItineraryPreviewData;
  onApply?: () => void;
  onRegenerate?: () => void;
}> = ({ data, onApply, onRegenerate }) => {
  const [expandedDays, setExpandedDays] = useState<number[]>([1]);

  const toggleDay = (dayIndex: number) => {
    setExpandedDays(prev => 
      prev.includes(dayIndex) 
        ? prev.filter(d => d !== dayIndex)
        : [...prev, dayIndex]
    );
  };

  return (
    <div className={styles.itineraryCard}>
      {/* 摘要 */}
      <div className={styles.itineraryHeader}>
        <div className={styles.itineraryTitle}>
          <EnvironmentOutlined className={styles.itineraryIcon} />
          <span>{data.summary}</span>
        </div>
        {data.total_distance && (
          <Tag color="blue" className={styles.distanceTag}>
            总距离: {data.total_distance}
          </Tag>
        )}
      </div>

      {/* 每日行程 */}
      <div className={styles.itineraryDays}>
        {data.days.map((day) => (
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
      {data.anchors.length > 0 && (
        <div className={styles.reasonsSection}>
          <div className={styles.reasonsTitle}>
            <InfoCircleOutlined /> 推荐理由
          </div>
          {data.anchors.map((anchor, idx) => (
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
          onClick={onApply}
          className={styles.applyButton}
        >
          应用到地图
        </Button>
        <Button 
          icon={<ReloadOutlined />}
          onClick={onRegenerate}
          className={styles.regenerateButton}
        >
          重新规划
        </Button>
      </div>
    </div>
  );
};

// 澄清消息组件 - 新增：展示缺失字段
const ClarificationCard: React.FC<{ 
  text: string;
  missing?: string[];
  received?: string[];
}> = ({ text, missing = [], received = [] }) => {
  return (
    <div className={styles.clarificationCard}>
      <div className={styles.clarificationHeader}>
        <QuestionCircleOutlined className={styles.clarificationIcon} />
        <span>需要补充信息</span>
      </div>
      
      <div className={styles.clarificationText}>
        {text}
      </div>
      
      {/* 已收到的信息 */}
      {received.length > 0 && (
        <div className={styles.infoSection}>
          <div className={styles.infoSectionTitle}>✅ 已收到</div>
          <div className={styles.infoTags}>
            {received.map((item, idx) => (
              <Tag key={idx} color="success">{item}</Tag>
            ))}
          </div>
        </div>
      )}
      
      {/* 缺失的信息 */}
      {missing.length > 0 && (
        <div className={styles.infoSection}>
          <div className={styles.infoSectionTitle}>❓ 还需要</div>
          <div className={styles.infoTags}>
            {missing.map((item, idx) => (
              <Tag key={idx} color="warning">{item}</Tag>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const MessageBubble: React.FC<MessageBubbleProps> = ({ 
  message, 
  onApplyToMap,
  onRegenerate 
}) => {
  const isSelf = message.sender.id === currentUser?.id;
  const isAgent = message.sender.is_agent;

  const handleApplyToMap = () => {
    if (message.content.type === 'itinerary_preview' && message.content.route_data) {
      onApplyToMap?.(message.content.route_data as ItineraryPreviewData);
    }
  };

  const handleRegenerate = () => {
    onRegenerate?.();
  };

  // 从消息元数据中获取澄清信息
  const clarificationData = message.metadata?.clarification || message.content.clarification_data;
  const missingFields = clarificationData?.missing || message.metadata?.missing_fields || [];
  const receivedFields = clarificationData?.received || message.metadata?.received_fields || [];

  return (
    <div
      className={`${styles.messageBubble} ${isSelf ? styles.self : ''} ${
        isAgent ? styles.agent : ''
      }`}
    >
      {!isSelf && (
        <Avatar
          src={message.sender.avatar}
          size={36}
          className={styles.avatar}
        >
          {isAgent ? '🤖' : message.sender.name.charAt(0)}
        </Avatar>
      )}

      <div className={styles.contentWrapper}>
        {!isSelf && (
          <div className={styles.senderName}>
            {message.sender.name}
            {isAgent && <span className={styles.agentBadge}>AI助手</span>}
          </div>
        )}

        <div className={styles.bubble}>
          {/* 澄清消息 - 新增 */}
          {message.content.type === 'clarification' || message.metadata?.response_status === 'needs_clarification' ? (
            <ClarificationCard 
              text={message.content.text || ''}
              missing={missingFields}
              received={receivedFields}
            />
          ) : /* 文本消息 */
          message.content.type === 'text' && (
            <div className={styles.textContent}>{message.content.text}</div>
          )}

          {/* 路线卡片 */}
          {message.content.type === 'route_card' && message.content.route_data && (
            <RouteCard data={message.content.route_data as RouteCardData} />
          )}

          {/* 行程预览卡片 */}
          {message.content.type === 'itinerary_preview' && message.content.route_data && (
            <ItineraryPreviewCard 
              data={message.content.route_data as ItineraryPreviewData}
              onApply={handleApplyToMap}
              onRegenerate={handleRegenerate}
            />
          )}

          {/* 地点卡片 */}
          {message.content.type === 'poi_card' && message.content.poi_data && (
            <SimplePOICard data={message.content.poi_data} />
          )}

          {/* 图片 */}
          {message.content.type === 'image' && message.content.media_url && (
            <Image
              src={message.content.media_url}
              alt="图片"
              className={styles.imageContent}
              preview
            />
          )}

          {/* 位置 */}
          {message.content.type === 'location' && message.content.location && (
            <div className={styles.locationCard}>
              <div className={styles.locationIcon}>📍</div>
              <div className={styles.locationInfo}>
                <div className={styles.locationName}>
                  {message.content.location.name}
                </div>
                <div className={styles.locationAddress}>
                  {message.content.location.address}
                </div>
              </div>
            </div>
          )}
        </div>

        <div className={styles.time}>
          {dayjs(message.timestamp).format('HH:mm')}
        </div>
      </div>

      {isSelf && (
        <Avatar
          src={currentUser?.avatar}
          size={36}
          className={styles.avatar}
        >
          {currentUser?.name.charAt(0)}
        </Avatar>
      )}
    </div>
  );
};

export default MessageBubble;
