import React from 'react';
import RouteTimeline from './RouteTimelineSimple';

// Example usage of RouteTimeline component
const RouteTimelineExample: React.FC = () => {
  const nodes = [
    {
      id: '1',
      type: 'start' as const,
      time: '09:00',
      title: 'Grand Hyatt Beijing',
      subtitle: '北京君悦大酒店',
      rating: 4.8,
      reviewCount: 2341,
      duration: 'Check-in',
      imageUrl: 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=120'
    },
    {
      id: '2',
      type: 'transport' as const,
      time: '',
      title: '',
      transportInfo: {
        mode: 'Drive',
        duration: '1h 15m',
        distance: '66 km',
        arrivalTime: '10:15'
      }
    },
    {
      id: '3',
      type: 'poi' as const,
      time: '10:15',
      title: 'Great Wall of China',
      subtitle: '万里长城',
      rating: 4.9,
      reviewCount: 15678,
      duration: '3 hours',
      imageUrl: 'https://images.unsplash.com/photo-1508804185872-d7badad00f7d?w=120',
      index: 1
    },
    {
      id: '4',
      type: 'transport' as const,
      time: '',
      title: '',
      transportInfo: {
        mode: 'Drive',
        duration: '45m',
        distance: '32 km',
        arrivalTime: '14:00'
      }
    },
    {
      id: '5',
      type: 'poi' as const,
      time: '14:00',
      title: 'Summer Palace',
      subtitle: '颐和园',
      rating: 4.7,
      reviewCount: 8934,
      duration: '2.5 hours',
      imageUrl: 'https://images.unsplash.com/photo-1547981609-4b6bfe67ca0b?w=120',
      index: 2
    },
    {
      id: '6',
      type: 'transport' as const,
      time: '',
      title: '',
      transportInfo: {
        mode: 'Drive',
        duration: '30m',
        distance: '18 km',
        arrivalTime: '17:00'
      }
    },
    {
      id: '7',
      type: 'poi' as const,
      time: '17:00',
      title: 'Temple of Heaven',
      subtitle: '天坛',
      rating: 4.6,
      reviewCount: 6721,
      duration: '2 hours',
      imageUrl: 'https://images.unsplash.com/photo-1584450150050-4b9bdbd51f68?w=120',
      index: 3
    },
    {
      id: '8',
      type: 'transport' as const,
      time: '',
      title: '',
      transportInfo: {
        mode: 'Drive',
        duration: '25m',
        distance: '12 km',
        arrivalTime: '19:30'
      }
    },
    {
      id: '9',
      type: 'end' as const,
      time: '19:30',
      title: 'Duck de Chine',
      subtitle: '全聚德烤鸭店',
      rating: 4.5,
      reviewCount: 4532,
      duration: 'Dinner',
      imageUrl: 'https://images.unsplash.com/photo-1563245372-f21724e3856d?w=120'
    }
  ];

  const handleOptimize = () => {
    console.log('Optimizing route...');
  };

  const handleAddActivity = () => {
    console.log('Adding activity...');
  };

  const handleNodeClick = (node: any) => {
    console.log('Node clicked:', node);
  };

  return (
    <div style={{ 
      minHeight: '100vh', 
      background: '#f0f0f0',
      display: 'flex',
      justifyContent: 'flex-end'
    }}>
      <RouteTimeline
        nodes={nodes}
        onOptimize={handleOptimize}
        onAddActivity={handleAddActivity}
        onNodeClick={handleNodeClick}
      />
    </div>
  );
};

export default RouteTimelineExample;
