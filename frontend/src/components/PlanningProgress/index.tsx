/**
 * 规划进度浮层组件
 * 显示实时进度消息列表和进度指示器
 * 
 * 功能：
 * 1. 显示实时进度消息列表（流式更新）
 * 2. 带动画的进度指示器
 * 3. 完成后自动淡出
 */

import React, { useEffect, useRef, useState } from 'react';
import { Card, Progress, Typography, Space, Tag } from 'antd';
import {
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import type { PlanningProgress as PlanningProgressType } from '@/types/route';
import styles from './PlanningProgress.module.css';

const { Text, Paragraph } = Typography;

interface PlanningProgressProps {
  /** 规划进度状态 */
  progress: PlanningProgressType;
  /** 是否可见 */
  visible?: boolean;
  /** 完成后的自动隐藏延迟（毫秒），默认 3000，0 表示不自动隐藏 */
  autoHideDelay?: number;
  /** 关闭回调 */
  onClose?: () => void;
}

/**
 * 规划进度浮层组件
 * 
 * 功能：
 * 1. 显示实时进度消息列表
 * 2. 带动画的进度指示器
 * 3. 完成后自动消失
 */
export const PlanningProgress: React.FC<PlanningProgressProps> = ({
  progress,
  visible = true,
  autoHideDelay = 3000,
  onClose,
}) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const autoHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isFading, setIsFading] = useState(false);

  // 自动滚动到底部
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [progress.messages]);

  // 完成后自动隐藏
  useEffect(() => {
    if (!progress.isPlanning && progress.progress === 100 && autoHideDelay > 0) {
      // 先触发淡出动画
      autoHideTimerRef.current = setTimeout(() => {
        setIsFading(true);
      }, autoHideDelay - 500);

      // 然后关闭
      autoHideTimerRef.current = setTimeout(() => {
        onClose?.();
      }, autoHideDelay);
    }

    return () => {
      if (autoHideTimerRef.current) {
        clearTimeout(autoHideTimerRef.current);
      }
    };
  }, [progress.isPlanning, progress.progress, autoHideDelay, onClose]);

  if (!visible) return null;

  // 获取状态图标
  const getStatusIcon = (): React.ReactNode => {
    if (progress.isPlanning) {
      return <LoadingOutlined style={{ color: '#1890ff' }} />;
    }
    if (progress.progress === 100) {
      return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    }
    if (
      progress.message.includes('失败') ||
      progress.message.includes('取消')
    ) {
      return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    }
    return <LoadingOutlined style={{ color: '#1890ff' }} />;
  };

  // 获取状态颜色
  const getStatusColor = (): 'active' | 'success' | 'exception' => {
    if (progress.isPlanning) return 'active';
    if (progress.progress === 100) return 'success';
    if (
      progress.message.includes('失败') ||
      progress.message.includes('取消')
    )
      return 'exception';
    return 'active';
  };

  // 获取标签颜色
  const getTagColor = (): string => {
    if (progress.isPlanning) return 'processing';
    if (progress.progress === 100) return 'success';
    return 'error';
  };

  return (
    <Card
      className={`${styles.container} ${isFading ? styles.fadeOut : ''}`}
      size="small"
      bodyStyle={{ padding: '12px 16px' }}
    >
      {/* 头部：状态图标 + 标题 + 进度 */}
      <Space align="center" style={{ width: '100%', marginBottom: 8 }}>
        {getStatusIcon()}
        <Text strong style={{ fontSize: 14 }}>
          {progress.isPlanning ? '正在规划路线...' : progress.message}
        </Text>
        <Tag color={getTagColor()}>{progress.progress}%</Tag>
      </Space>

      {/* 进度条 */}
      <Progress
        percent={progress.progress}
        status={getStatusColor()}
        strokeColor={{
          from: '#108ee9',
          to: '#87d068',
        }}
        showInfo={false}
        style={{ marginBottom: 12 }}
      />

      {/* 消息列表 */}
      {progress.messages.length > 0 && (
        <div className={styles.messagesContainer}>
          {progress.messages.map((msg, index) => (
            <Paragraph
              key={index}
              className={styles.messageItem}
              style={{ marginBottom: 4, fontSize: 12 }}
            >
              {msg.startsWith('✓') ? (
                <Text type="success">{msg}</Text>
              ) : msg.startsWith('✗') ? (
                <Text type="danger">{msg}</Text>
              ) : msg.startsWith('===') ? (
                <Text strong style={{ color: '#1890ff' }}>
                  {msg}
                </Text>
              ) : (
                <Text type="secondary">{msg}</Text>
              )}
            </Paragraph>
          ))}
          <div ref={messagesEndRef} />
        </div>
      )}
    </Card>
  );
};

export default PlanningProgress;
