import React from 'react';
import RouteOverview from './RouteOverview';

// Example usage of RouteOverview component
const RouteOverviewExample: React.FC = () => {
  const stats = {
    totalDistance: 12500, // meters
    totalDuration: 480, // minutes (8 hours)
    estimatedCost: 350,
    totalStops: 6
  };

  const weather = {
    city: 'Beijing',
    temperature: 23,
    condition: 'Sunny'
  };

  const handleViewPlanB = () => {
    console.log('Viewing Plan B...');
  };

  return (
    <div style={{ 
      minHeight: '100vh', 
      background: '#f0f0f0',
      position: 'relative'
    }}>
      <RouteOverview
        stats={stats}
        weather={weather}
        crowdLevel="Moderate"
        onViewPlanB={handleViewPlanB}
      />
    </div>
  );
};

export default RouteOverviewExample;
