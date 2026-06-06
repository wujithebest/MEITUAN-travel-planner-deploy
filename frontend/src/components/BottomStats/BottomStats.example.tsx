import React from 'react';
import BottomStats from './BottomStats';

// Example usage of BottomStats component
const BottomStatsExample: React.FC = () => {
  const stats = {
    totalDistance: 12500, // meters
    totalDuration: 480, // minutes (8 hours)
    estimatedCost: 350,
    totalStops: 6,
    bestTime: '08:00',
    crowdLevel: 'Moderate',
    weather: '23°C'
  };

  const handleStartNavigation = () => {
    console.log('Starting navigation...');
  };

  return (
    <div style={{ 
      minHeight: '100vh', 
      background: '#f0f0f0',
      position: 'relative',
      paddingBottom: '56px'
    }}>
      <div style={{ padding: '20px' }}>
        <h1>Page Content</h1>
        <p>The BottomStats component is fixed at the bottom of the screen.</p>
      </div>
      
      <BottomStats
        stats={stats}
        onStartNavigation={handleStartNavigation}
      />
    </div>
  );
};

export default BottomStatsExample;
