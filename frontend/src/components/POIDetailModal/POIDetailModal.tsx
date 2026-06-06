/**
 * POI详情弹窗组件
 * 显示高德地图的POI信息和照片
 */

import React, { useState } from 'react';
import { Modal, Carousel, Image, Typography, Space, Tag, Divider, Rate } from 'antd';
import { PictureOutlined } from '@ant-design/icons';
import styles from './POIDetailModal.module.css';

const { Title, Text, Paragraph } = Typography;

// 高德POI照片模型
interface POIPhoto {
    title?: string;
    url: string;
}

// 高德POI模型
interface POI {
    id: string;
    name: string;
    location: string;
    address?: string;
    type: string;
    rating: number;
    photos: POIPhoto[];
    [key: string]: any;
}

interface POIDetailModalProps {
    isOpen: boolean;
    onClose: () => void;
    poiName: string;
    poiId?: string;
    location?: string;
    poi?: POI | null;  // 直接传入POI对象，包含高德照片
}

export default function POIDetailModal({
    isOpen,
    onClose,
    poiName,
    poiId,
    location,
    poi
}: POIDetailModalProps) {
    const [selectedImage, setSelectedImage] = useState<string | null>(null);
    const [imageLoadErrors, setImageLoadErrors] = useState<Set<string>>(new Set());

    // 获取照片列表 - 优先使用传入的POI对象中的照片
    const photoList = (poi?.photos || []).filter(p => !imageLoadErrors.has(p.url));

    const handleImageError = (url: string) => {
        setImageLoadErrors(prev => new Set(prev).add(url));
    };

    // 点击遮罩关闭
    const handleOverlayClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget) {
            onClose();
        }
    };

    // 图片点击放大
    const handleImageClick = (url: string) => {
        setSelectedImage(url);
    };

    // 渲染星级
    const renderStars = (rating: number) => {
        if (!rating) return null;
        return (
            <div className={styles.stars}>
                {[...Array(5)].map((_, i) => (
                    <span
                        key={i}
                        className={`${styles.star} ${i < Math.floor(rating) ? styles.full : ''}`}
                    >
                        ★
                    </span>
                ))}
            </div>
        );
    };

    if (!isOpen) return null;

    return (
        <>
            <Modal
                visible={isOpen}
                onCancel={onClose}
                width={800}
                footer={null}
                title={null}
                bodyStyle={{ padding: 0 }}
            >
                <div style={{ maxHeight: '80vh', overflow: 'auto' }}>
                    {/* POI 照片轮播 - 直接使用高德MCP的照片 */}
                    {photoList.length > 0 && (
                        <div style={{ position: 'relative' }}>
                            <Carousel autoplay dots>
                                {photoList.map((photo, i) => (
                                    <div key={i}>
                                        <Image
                                            src={photo.url}
                                            alt={photo.title || `${poiName} 照片 ${i + 1}`}
                                            style={{
                                                width: '100%',
                                                height: 300,
                                                objectFit: 'cover'
                                            }}
                                            preview={{
                                                mask: '查看大图'
                                            }}
                                            onError={() => handleImageError(photo.url)}
                                            fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                                        />
                                    </div>
                                ))}
                            </Carousel>
                        </div>
                    )}

                    {/* 无照片时的占位符 */}
                    {photoList.length === 0 && (
                        <div style={{
                            height: 200,
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            backgroundColor: '#f5f5f5',
                            color: '#999'
                        }}>
                            <PictureOutlined style={{ fontSize: 48, marginBottom: 16 }} />
                            <Text type="secondary">暂无照片</Text>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                照片由高德地图提供
                            </Text>
                        </div>
                    )}

                    <div style={{ padding: 24 }}>
                        {/* POI 基本信息 */}
                        <Space direction="vertical" size={8} style={{ width: '100%' }}>
                            <Title level={3} style={{ margin: 0 }}>{poi?.name || poiName}</Title>

                            <Space size={16}>
                                <Space>
                                    <Rate disabled allowHalf value={(poi?.rating || 0) / 2} />
                                    <Text strong style={{ fontSize: 16 }}>
                                        {poi?.rating ? poi.rating.toFixed(1) : '-'}
                                    </Text>
                                </Space>
                            </Space>

                            {poi?.address && (
                                <Text type="secondary">📍 {poi.address}</Text>
                            )}

                            {poi?.type && (
                                <Tag color="blue">{poi.type}</Tag>
                            )}

                            {poi?.open_time && (
                                <Text type="secondary">🕐 开放时间: {poi.open_time}</Text>
                            )}

                            {poi?.price && (
                                <Text type="secondary">💰 人均: {poi.price}</Text>
                            )}
                        </Space>

                        <Divider />

                        {/* 数据来源说明 */}
                        <div style={{
                            padding: 16,
                            backgroundColor: '#f0f7ff',
                            borderRadius: 8,
                            border: '1px solid #ffe58f'
                        }}>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                📌 数据由高德地图提供 | POI ID: {poi?.id || poiId || '未知'}
                            </Text>
                        </div>
                    </div>
                </div>
            </Modal>

            {/* 图片预览 */}
            {selectedImage && (
                <div
                    className={styles.imagePreview}
                    onClick={() => setSelectedImage(null)}
                >
                    <img src={selectedImage} alt="预览" />
                    <button
                        className={styles.previewClose}
                        onClick={() => setSelectedImage(null)}
                    >
                        ✕
                    </button>
                </div>
            )}
        </>
    );
}
