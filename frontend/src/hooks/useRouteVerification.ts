/**
 * 路线数据一致性验证 Hook
 * 验证前端渲染数据与后端原始数据是否一致
 */

import { useCallback } from 'react';

/** 验证错误类型 */
export type VerificationErrorType = 
  | 'MISSING_POINT'      // 前端缺少标记点
  | 'COORD_MISMATCH'     // 坐标偏差过大
  | 'WRONG_KIND'         // 类型不匹配
  | 'MISSING_SEGMENT'    // 缺少路线段
  | 'COLOR_MISMATCH'     // 颜色不匹配
  | 'ORDER_MISMATCH';    // 数量不匹配

/** 验证错误 */
export interface VerificationError {
  type: VerificationErrorType;
  message: string;
  expected?: any;
  actual?: any;
}

/** 验证统计 */
export interface VerificationStats {
  totalBackendPoints: number;
  totalFrontendPoints: number;
  totalBackendSegments: number;
  totalFrontendSegments: number;
  startPoints: number;
  waypointPoints: number;
  enroutePoints: number;
  mealPoints: number;
  hintPoints: number;
}

/** 验证结果 */
export interface VerificationResult {
  passed: boolean;
  errors: VerificationError[];
  stats: VerificationStats;
}

/** 后端路线点 */
export interface BackendRoutePoint {
  name: string;
  location: { lat: number; lng: number };
  kind: string;
  day: number;
  is_waypoint: boolean;
  walk_from_route_min: number;
  route_annotation: string;
}

/** 后端路线段 */
export interface BackendRouteSegment {
  from_poi: string;
  to_poi: string;
  day_index: number;
  transport: string;
  duration_min: number;
  distance_km: number;
  polyline: [number, number][]; // [[lat, lng], ...]
}

/** 前端标记点 */
export interface FrontendMarker {
  name: string;
  position: [number, number]; // [lng, lat]
  kind: string;
}

/** 前端路线段 */
export interface FrontendPolyline {
  from: string;
  to: string;
  path: [number, number][]; // [[lng, lat], ...]
  color: string;
}

/** 时间段颜色映射 */
const PERIOD_COLORS: Record<string, string> = {
  morning: '#E67E22',
  lunch: '#D35400',
  afternoon: '#2980B9',
  dinner: '#C0392B',
  evening: '#8E44AD',
};

/**
 * 计算两点间距离（米）- Haversine 公式
 */
function haversineDistance(
  lat1: number, lng1: number,
  lat2: number, lng2: number
): number {
  const R = 6371000; // 地球半径（米）
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLng / 2) * Math.sin(dLng / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/**
 * 验证路线数据一致性
 * 
 * @param backendData 后端原始数据
 * @param frontendData 前端渲染数据
 * @returns 验证结果
 */
export function verifyRouteConsistency(
  backendData: {
    points: BackendRoutePoint[];
    segments: BackendRouteSegment[];
  } | null,
  frontendData: {
    markers: FrontendMarker[];
    polylines: FrontendPolyline[];
  } | null
): VerificationResult {
  const errors: VerificationError[] = [];

  // 数据为空检查
  if (!backendData || !frontendData) {
    return {
      passed: false,
      errors: [{
        type: 'MISSING_POINT',
        message: '后端或前端数据为空',
        expected: backendData ? '有数据' : '空',
        actual: frontendData ? '有数据' : '空',
      }],
      stats: {
        totalBackendPoints: 0,
        totalFrontendPoints: 0,
        totalBackendSegments: 0,
        totalFrontendSegments: 0,
        startPoints: 0,
        waypointPoints: 0,
        enroutePoints: 0,
        mealPoints: 0,
        hintPoints: 0,
      },
    };
  }

  const { points: backendPoints, segments: backendSegments } = backendData;
  const { markers: frontendMarkers, polylines: frontendPolylines } = frontendData;

  // 过滤掉 hint 和 free_explore 类型的点（这些不画 marker）
  const routableBackendPoints = backendPoints.filter(
    p => p.kind !== 'hint' && p.kind !== 'free_explore'
  );

  // 1. 验证 POI 数量
  const backendPointNames = new Set(routableBackendPoints.map(p => p.name));
  const frontendMarkerNames = new Set(frontendMarkers.map(m => m.name));

  // 检查后端有但前端没有的点
  for (const name of backendPointNames) {
    if (!frontendMarkerNames.has(name)) {
      errors.push({
        type: 'MISSING_POINT',
        message: `前端缺少标记点: ${name}`,
        expected: name,
        actual: null,
      });
    }
  }

  // 检查数量是否匹配
  if (frontendMarkers.length !== backendPointNames.size) {
    errors.push({
      type: 'ORDER_MISMATCH',
      message: `标记点数量不匹配: 后端${backendPointNames.size}个, 前端${frontendMarkers.length}个`,
      expected: backendPointNames.size,
      actual: frontendMarkers.length,
    });
  }

  // 2. 验证坐标一致性（允许50米误差）
  const COORD_THRESHOLD_M = 50;
  for (const point of routableBackendPoints) {
    const marker = frontendMarkers.find(m => m.name === point.name);
    if (!marker) continue;

    // 后端: {lat, lng}, 前端: [lng, lat]
    const beLat = point.location.lat;
    const beLng = point.location.lng;
    const [feLng, feLat] = marker.position;

    const distance = haversineDistance(beLat, beLng, feLat, feLng);
    if (distance > COORD_THRESHOLD_M) {
      errors.push({
        type: 'COORD_MISMATCH',
        message: `${point.name} 坐标偏差过大: ${distance.toFixed(1)}米`,
        expected: [beLng, beLat],
        actual: [feLng, feLat],
      });
    }
  }

  // 3. 验证类型一致性
  for (const point of routableBackendPoints) {
    const marker = frontendMarkers.find(m => m.name === point.name);
    if (!marker) continue;

    const expectedKind = point.kind;
    const actualKind = marker.kind;

    if (expectedKind !== actualKind) {
      errors.push({
        type: 'WRONG_KIND',
        message: `${point.name} 类型不匹配: 期望${expectedKind}, 实际${actualKind}`,
        expected: expectedKind,
        actual: actualKind,
      });
    }
  }

  // 4. 验证路线段数量
  if (frontendPolylines.length !== backendSegments.length) {
    errors.push({
      type: 'ORDER_MISMATCH',
      message: `路线段数量不匹配: 后端${backendSegments.length}个, 前端${frontendPolylines.length}个`,
      expected: backendSegments.length,
      actual: frontendPolylines.length,
    });
  }

  // 5. 验证路线段是否存在
  for (const segment of backendSegments) {
    const polyline = frontendPolylines.find(
      p => p.from === segment.from_poi && p.to === segment.to_poi
    );
    if (!polyline) {
      errors.push({
        type: 'MISSING_SEGMENT',
        message: `缺少路线段: ${segment.from_poi} → ${segment.to_poi}`,
        expected: `${segment.from_poi} → ${segment.to_poi}`,
        actual: null,
      });
    }
  }

  // 统计
  const stats: VerificationStats = {
    totalBackendPoints: backendPoints.length,
    totalFrontendPoints: frontendMarkers.length,
    totalBackendSegments: backendSegments.length,
    totalFrontendSegments: frontendPolylines.length,
    startPoints: backendPoints.filter(p => p.kind === 'start').length,
    waypointPoints: backendPoints.filter(p => p.kind === 'waypoint' || p.kind === 'anchor_internal').length,
    enroutePoints: backendPoints.filter(p => p.kind === 'enroute').length,
    mealPoints: backendPoints.filter(p => p.kind === 'meal').length,
    hintPoints: backendPoints.filter(p => p.kind === 'hint' || p.kind === 'free_explore').length,
  };

  return {
    passed: errors.length === 0,
    errors,
    stats,
  };
}

/**
 * 验证 Hook
 * 提供验证功能和状态管理
 */
export function useRouteVerification() {
  /**
   * 执行验证
   */
  const verify = useCallback((
    backendData: {
      points: BackendRoutePoint[];
      segments: BackendRouteSegment[];
    } | null,
    frontendData: {
      markers: FrontendMarker[];
      polylines: FrontendPolyline[];
    } | null
  ): VerificationResult => {
    return verifyRouteConsistency(backendData, frontendData);
  }, []);

  /**
   * 格式化验证结果为可读字符串
   */
  const formatResult = useCallback((result: VerificationResult): string => {
    const lines: string[] = [];
    
    lines.push(result.passed ? '✅ 验证通过' : `❌ 发现 ${result.errors.length} 个问题`);
    lines.push('');
    lines.push('统计:');
    lines.push(`  后端 POI 数: ${result.stats.totalBackendPoints}`);
    lines.push(`  前端 Marker 数: ${result.stats.totalFrontendPoints}`);
    lines.push(`  后端路线段数: ${result.stats.totalBackendSegments}`);
    lines.push(`  前端 Polyline 数: ${result.stats.totalFrontendSegments}`);
    lines.push(`  起点: ${result.stats.startPoints}`);
    lines.push(`  途经点: ${result.stats.waypointPoints}`);
    lines.push(`  餐饮点: ${result.stats.mealPoints}`);
    lines.push(`  提示点: ${result.stats.hintPoints}`);

    if (result.errors.length > 0) {
      lines.push('');
      lines.push('错误详情:');
      for (const err of result.errors) {
        lines.push(`  [${err.type}] ${err.message}`);
      }
    }

    return lines.join('\n');
  }, []);

  return {
    verify,
    formatResult,
  };
}

export default useRouteVerification;
