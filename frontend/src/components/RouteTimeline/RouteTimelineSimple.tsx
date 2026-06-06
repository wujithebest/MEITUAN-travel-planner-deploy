import React from 'react';
import { 
  Settings, 
  MapPin, 
  Car, 
  Star,
  Clock,
  Plus
} from 'lucide-react';
import styles from './RouteTimelineSimple.module.css';

interface TimelineNode {
  id: string;
  type: 'start' | 'poi' | 'transport' | 'end';
  time: string;
  title: string;
  subtitle?: string;
  rating?: number;
  reviewCount?: number;
  duration?: string;
  transportInfo?: {
    mode: string;
    duration: string;
    distance: string;
    arrivalTime: string;
  };
  imageUrl?: string;
  index?: number;
}

interface RouteTimelineProps {
  nodes: TimelineNode[];
  onOptimize?: () => void;
  onAddActivity?: () => void;
  onNodeClick?: (node: TimelineNode) => void;
}

const RouteTimeline: React.FC<RouteTimelineProps> = ({
  nodes,
  onOptimize,
  onAddActivity,
  onNodeClick
}) => {
  const renderNodeIcon = (node: TimelineNode) => {
    switch (node.type) {
      case 'start':
        return <div className={`${styles.nodeIcon} ${styles.startIcon}`} />;
      case 'poi':
        return (
          <div className={`${styles.nodeIcon} ${styles.poiIcon}`}>
            <span className={styles.nodeNumber}>{node.index}</span>
          </div>
        );
      case 'transport':
        return (
          <div className={`${styles.nodeIcon} ${styles.transportIcon}`}>
            <Car size={12} />
          </div>
        );
      case 'end':
        return <div className={`${styles.nodeIcon} ${styles.endIcon}`} />;
      default:
        return <div className={styles.nodeIcon} />;
    }
  };

  const renderCard = (node: TimelineNode) => {
    if (node.type === 'transport') {
      return (
        <div className={styles.transportCard} onClick={() => onNodeClick?.(node)}>
          <Car size={16} className={styles.transportCardIcon} />
          <span className={styles.transportText}>
            {node.transportInfo?.mode} {node.transportInfo?.duration} ({node.transportInfo?.distance})
          </span>
          <span className={styles.arrivalTime}>{node.transportInfo?.arrivalTime}</span>
        </div>
      );
    }

    return (
      <div className={styles.card} onClick={() => onNodeClick?.(node)}>
        <div className={styles.cardContent}>
          <div className={styles.cardHeader}>
            <span className={styles.cardTitle}>{node.title}</span>
            {node.subtitle && (
              <span className={styles.cardSubtitle}>{node.subtitle}</span>
            )}
          </div>
          
          {node.rating !== undefined && (
            <div className={styles.cardRating}>
              <Star size={14} className={styles.starIcon} fill="#FFD700" color="#FFD700" />
              <span className={styles.ratingValue}>{node.rating.toFixed(1)}</span>
              <span className={styles.reviewCount}>({node.reviewCount})</span>
            </div>
          )}
          
          {node.duration && (
            <div className={styles.cardDuration}>
              <Clock size={14} />
              <span>{node.duration}</span>
            </div>
          )}
        </div>
        
        {node.imageUrl && (
          <div className={styles.cardImage}>
            <img src={node.imageUrl} alt={node.title} />
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <h2 className={styles.title}>Your Itinerary</h2>
        <button className={styles.optimizeButton} onClick={onOptimize}>
          <Settings size={16} />
          <span>Optimize</span>
        </button>
      </div>

      {/* Timeline */}
      <div className={styles.timeline}>
        {/* Vertical Line */}
        <div className={styles.verticalLine} />

        {/* Nodes */}
        <div className={styles.nodesList}>
          {nodes.map((node, index) => (
            <div key={node.id} className={styles.timelineNode}>
              {/* Time */}
              <div className={styles.nodeTime}>{node.time}</div>
              
              {/* Icon */}
              <div className={styles.nodeIconWrapper}>
                {renderNodeIcon(node)}
              </div>
              
              {/* Content */}
              <div className={styles.nodeContent}>
                <div className={styles.nodeLabel}>
                  {node.type === 'start' && 'Start'}
                  {node.type === 'end' && 'End'}
                  {node.type === 'poi' && node.title}
                  {node.type === 'transport' && ''}
                </div>
                {renderCard(node)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Add Activity Button */}
      <button className={styles.addButton} onClick={onAddActivity}>
        <Plus size={18} />
        <span>Add Activity</span>
      </button>
    </div>
  );
};

export default RouteTimeline;
