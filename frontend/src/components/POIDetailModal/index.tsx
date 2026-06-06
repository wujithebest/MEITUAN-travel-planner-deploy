import React, { useState, useEffect } from 'react';
import { Modal, List, Rate, Carousel, Spin, Image, Typography, Space, Tag, Divider } from 'antd';
import { LikeOutlined, CalendarOutlined, UserOutlined, PictureOutlined } from '@ant-design/icons';
import axios from 'axios';

const { Title, Text, Paragraph } = Typography;

// 使用Vite的环境变量语法 - 使用相对路径通过代理访问
const API_URL = import.meta.env.VITE_API_BASE_URL || '/api';

interface Review {
    author: string;
    rating: number;
    content: string;
    date: string;
    likes: number;
    photos: string[];
}

interface POIReviews {
    poi_name: string;
    avg_rating: number;
    review_count: number;
    reviews: Review[];
}

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
    photos: POIPhoto[];  // 高德MCP返回的照片列表
    [key: string]: any;
}

interface POIDetailModalProps {
    visible: boolean;
    poi: POI | null;
    onClose: () => void;
}

const POIDetailModal: React.FC<POIDetailModalProps> = ({ visible, poi, onClose }) => {
    const [reviews, setReviews] = useState<POIReviews | null>(null);
    const [loading, setLoading] = useState(false);
    const [imageLoadErrors, setImageLoadErrors] = useState<Set<string>>(new Set());

    useEffect(() => {
        if (visible && poi) {
            fetchReviews();
        } else {
            setReviews(null);
            setImageLoadErrors(new Set());
        }
    }, [visible, poi]);

    const fetchReviews = async () => {
        if (!poi) return;
        
        setLoading(true);
        try {
            const res = await axios.get(
                `${API_URL}/api/reviews/${encodeURIComponent(poi.name)}?city=上海`,
                { timeout: 5000 }
            );
            if (res.data.success) {
                setReviews(res.data.data);
            } else {
                // 静默处理，使用默认数据
                console.log('评论加载返回:', res.data.message);
            }
        } catch (e) {
            console.error('获取评论失败:', e);
            // 静默处理，不显示错误消息
        } finally {
            setLoading(false);
        }
    };

    const handleImageError = (url: string) => {
        setImageLoadErrors(prev => new Set(prev).add(url));
    };

    const displayRating = reviews?.avg_rating || poi?.rating || 0;
    const displayReviewCount = reviews?.review_count || 0;

    // 获取照片列表 - 优先使用高德MCP返回的照片
    const photoList = (poi?.photos || []).filter(p => !imageLoadErrors.has(p.url));

    return (
        <Modal
            visible={visible}
            onCancel={onClose}
            width={800}
            footer={null}
            title={null}
            bodyStyle={{ padding: 0 }}
        >
            {poi && (
                <div style={{ maxHeight: '80vh', overflow: 'auto' }}>
                    {/* POI 照片轮播 - 直接使用高德MCP的照片 */}
                    {photoList.length > 0 && (
                        <div style={{ position: 'relative' }}>
                            <Carousel autoplay dots>
                                {photoList.map((photo, i) => (
                                    <div key={i}>
                                        <Image
                                            src={photo.url}
                                            alt={photo.title || `${poi.name} 照片 ${i + 1}`}
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
                            <Title level={3} style={{ margin: 0 }}>{poi.name}</Title>
                            
                            <Space size={16}>
                                <Space>
                                    <Rate disabled allowHalf value={displayRating / 2} />
                                    <Text strong style={{ fontSize: 16 }}>
                                        {displayRating.toFixed(1)}
                                    </Text>
                                </Space>
                                <Text type="secondary">
                                    {displayReviewCount} 条点评
                                </Text>
                            </Space>

                            {poi.address && (
                                <Text type="secondary">📍 {poi.address}</Text>
                            )}

                            {poi.type && (
                                <Tag color="blue">{poi.type}</Tag>
                            )}
                        </Space>

                        <Divider />

                        {/* 评论列表 */}
                        <Title level={4}>
                            用户评价
                            {loading && <Spin size="small" style={{ marginLeft: 8 }} />}
                        </Title>

                        {reviews?.reviews && reviews.reviews.length > 0 ? (
                            <List
                                dataSource={reviews.reviews}
                                renderItem={(review, index) => (
                                    <List.Item
                                        key={index}
                                        style={{ padding: '16px 0' }}
                                    >
                                        <div style={{ width: '100%' }}>
                                            {/* 评论头部 */}
                                            <div
                                                style={{
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: 12,
                                                    marginBottom: 8
                                                }}
                                            >
                                                <Space>
                                                    <UserOutlined />
                                                    <Text strong>{review.author}</Text>
                                                </Space>
                                                <Rate
                                                    disabled
                                                    allowHalf
                                                    value={review.rating / 2}
                                                    style={{ fontSize: 14 }}
                                                />
                                                <Space>
                                                    <CalendarOutlined />
                                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                                        {review.date}
                                                    </Text>
                                                </Space>
                                            </div>

                                            {/* 评论内容 */}
                                            <Paragraph
                                                style={{
                                                    marginBottom: 8,
                                                    color: '#333'
                                                }}
                                            >
                                                {review.content}
                                            </Paragraph>

                                            {/* 评论图片 */}
                                            {review.photos && review.photos.length > 0 && (
                                                <div
                                                    style={{
                                                        display: 'flex',
                                                        gap: 8,
                                                        marginBottom: 8
                                                    }}
                                                >
                                                    <Image.PreviewGroup>
                                                        {review.photos.map((url, i) => (
                                                            <Image
                                                                key={i}
                                                                src={url}
                                                                alt={`评论图片 ${i + 1}`}
                                                                style={{
                                                                    width: 80,
                                                                    height: 80,
                                                                    objectFit: 'cover',
                                                                    borderRadius: 4,
                                                                    cursor: 'pointer'
                                                                }}
                                                            />
                                                        ))}
                                                    </Image.PreviewGroup>
                                                </div>
                                            )}

                                            {/* 点赞数 */}
                                            {review.likes > 0 && (
                                                <Space>
                                                    <LikeOutlined />
                                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                                        {review.likes}
                                                    </Text>
                                                </Space>
                                            )}
                                        </div>
                                    </List.Item>
                                )}
                            />
                        ) : (
                            !loading && (
                                <div
                                    style={{
                                        textAlign: 'center',
                                        padding: '40px 0',
                                        color: '#999'
                                    }}
                                >
                                    {reviews ? '暂无评论' : '评论加载中...'}
                                </div>
                            )
                        )}
                    </div>
                </div>
            )}
        </Modal>
    );
};

export default POIDetailModal;
