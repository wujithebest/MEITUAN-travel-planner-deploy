/**
 * 路线 Polyline 服务
 * 将后端高德地图 polyline 生成逻辑完整迁移到前端
 * 
 * 对应后端文件：
 * - api_client.py: _parse_gaode_polyline, _merge_polyline_chunks, 
 *                  _extract_path_polyline, _extract_transit_polyline,
 *                  _haversine_distance
 * - step3_micro.py: _route_between, _simplify_polyline, _render_single_day_map,
 *                   _merge_short_segments, _deduplicate_joints, _prune_branches,
 *                   _connect_gaps, _haversine_point_to_segment
 * 
 * 坐标系约定：
 * - 内部存储和计算全部使用 [lat, lng]（与后端一致）
 * - 仅在调用高德 API 时转换为 [lng, lat]
 */

import type {
  RouteSegment,
  DayRoute,
  POI,
  TransportMode,
} from '@/types/route';
import { TRANSPORT_STYLES } from '@/types/route';

/**
 * RoutePolylineService - 路线规划核心服务类
 * 
 * 职责：
 * 1. 调用高德 JS API 获取路线数据
 * 2. 解析和处理 polyline 数据
 * 3. 优化渲染性能（合并、去重、支路去除、简化）
 * 4. 地图渲染（Polyline + 方向箭头）
 */
export class RoutePolylineService {
  private map: AMap.Map | null = null;
  /** 当前渲染的 polyline 引用，用于清理 */
  private polylines: AMap.Polyline[] = [];
  /** 当前渲染的 marker 引用，用于清理 */
  private markers: AMap.Marker[] = [];
  /** 当前渲染的箭头引用，用于清理 */
  private arrows: AMap.Marker[] = [];

  constructor(map?: AMap.Map) {
    if (map) {
      this.map = map;
    }
  }

  /** 设置地图实例 */
  setMap(map: AMap.Map | null): void {
    this.map = map;
  }

  // ========================================================================
  // 1. 核心规划逻辑 - 对应后端 step3_micro.py _route_between()
  // ========================================================================

  /**
   * 智能选择交通方式规划两点间路线
   * 对应后端: step3_micro.py _route_between()
   * 
   * 规则（与后端完全一致）：
   * - <50m: 直接两点连线，transport="步行"
   * - sameSubAnchor=true: 步行导航
   * - 跨 sub-anchor: ≥2km 驾车, 1-2km 骑行, <1km 步行
   * 
   * @param origin 起点 POI
   * @param destination 终点 POI
   * @param options 规划选项
   * @returns RouteSegment 或 null
   */
  async planRoute(
    origin: POI,
    destination: POI,
    options: { sameSubAnchor?: boolean; forceTransport?: TransportMode } = {}
  ): Promise<RouteSegment | null> {
    const distance = this.haversineDistance(
      [origin.lat, origin.lng],
      [destination.lat, destination.lng]
    );

    // <50m: 直接两点连线，标记为步行
    if (distance < 50) {
      return {
        polyline: [[origin.lat, origin.lng], [destination.lat, destination.lng]],
        transport: '步行',
        distance: distance,
        duration: 0,
        fromName: origin.name,
        toName: destination.name,
      };
    }

    // 强制指定交通方式
    if (options.forceTransport) {
      return this.queryByTransport(
        options.forceTransport,
        origin,
        destination,
        distance
      );
    }

    // 同 sub-anchor: 步行导航
    if (
      options.sameSubAnchor ||
      (origin.subAnchorId &&
        destination.subAnchorId &&
        origin.subAnchorId === destination.subAnchorId)
    ) {
      return this.queryWalking(origin, destination);
    }

    // 跨 sub-anchor: 按距离选择交通方式
    if (distance >= 2000) {
      // ≥2km: 驾车
      return this.queryDriving(origin, destination);
    } else if (distance >= 1000) {
      // 1-2km: 骑行
      return this.queryRiding(origin, destination);
    } else {
      // <1km: 步行
      return this.queryWalking(origin, destination);
    }
  }

  /**
   * 按指定交通方式查询
   */
  private async queryByTransport(
    transport: TransportMode,
    origin: POI,
    destination: POI,
    _distance: number
  ): Promise<RouteSegment | null> {
    switch (transport) {
      case '步行':
        return this.queryWalking(origin, destination);
      case '自驾':
        return this.queryDriving(origin, destination);
      case '骑行':
        return this.queryRiding(origin, destination);
      case '地铁/公交':
        return this.queryTransit(origin, destination);
      default:
        return this.queryWalking(origin, destination);
    }
  }

  // ========================================================================
  // 2. 高德 API 查询 - 对应后端 api_client.py gaode_xxx_route()
  // ========================================================================

  /**
   * 查询步行路线
   * 对应后端: api_client.py gaode_walking_route()
   */
  async queryWalking(
    origin: POI,
    destination: POI
  ): Promise<RouteSegment | null> {
    return new Promise((resolve) => {
      try {
        const walking = new AMap.Walking({
          map: undefined,
          hideMarkers: true,
        });

        walking.search(
          [origin.lng, origin.lat],
          [destination.lng, destination.lat],
          (status: string, result: any) => {
            if (
              status === 'complete' &&
              result?.route?.paths?.[0]?.steps
            ) {
              const path = result.route.paths[0];
              const polyline = this.parseGaodePath(path.steps);

              resolve({
                polyline,
                transport: '步行',
                distance: Number(path.distance) || 0,
                duration: Number(path.duration) || 0,
                fromName: origin.name,
                toName: destination.name,
              });
            } else {
              // 降级为直线
              resolve(this.createStubSegment(origin, destination, '步行'));
            }
          }
        );
      } catch {
        resolve(this.createStubSegment(origin, destination, '步行'));
      }
    });
  }

  /**
   * 查询驾车路线
   * 对应后端: api_client.py gaode_driving_route()
   */
  async queryDriving(
    origin: POI,
    destination: POI
  ): Promise<RouteSegment | null> {
    return new Promise((resolve) => {
      try {
        const driving = new AMap.Driving({
          map: undefined,
          hideMarkers: true,
        });

        driving.search(
          [origin.lng, origin.lat],
          [destination.lng, destination.lat],
          (status: string, result: any) => {
            if (
              status === 'complete' &&
              result?.route?.paths?.[0]?.steps
            ) {
              const path = result.route.paths[0];
              const polyline = this.parseGaodePath(path.steps);

              resolve({
                polyline,
                transport: '自驾',
                distance: Number(path.distance) || 0,
                duration: Number(path.duration) || 0,
                fromName: origin.name,
                toName: destination.name,
              });
            } else {
              resolve(this.createStubSegment(origin, destination, '自驾'));
            }
          }
        );
      } catch {
        resolve(this.createStubSegment(origin, destination, '自驾'));
      }
    });
  }

  /**
   * 查询骑行路线
   * 对应后端: api_client.py gaode_bicycling_route()
   */
  async queryRiding(
    origin: POI,
    destination: POI
  ): Promise<RouteSegment | null> {
    return new Promise((resolve) => {
      try {
        const riding = new AMap.Riding({
          map: undefined,
          hideMarkers: true,
        });

        riding.search(
          [origin.lng, origin.lat],
          [destination.lng, destination.lat],
          (status: string, result: any) => {
            if (
              status === 'complete' &&
              result?.route?.paths?.[0]?.steps
            ) {
              const path = result.route.paths[0];
              const polyline = this.parseGaodePath(path.steps);

              resolve({
                polyline,
                transport: '骑行',
                distance: Number(path.distance) || 0,
                duration: Number(path.duration) || 0,
                fromName: origin.name,
                toName: destination.name,
              });
            } else {
              resolve(this.createStubSegment(origin, destination, '骑行'));
            }
          }
        );
      } catch {
        resolve(this.createStubSegment(origin, destination, '骑行'));
      }
    });
  }

  /**
   * 查询公交/地铁路线
   * 对应后端: api_client.py gaode_transit_route()
   */
  async queryTransit(
    origin: POI,
    destination: POI
  ): Promise<RouteSegment | null> {
    return new Promise((resolve) => {
      try {
        const transfer = new AMap.Transfer({
          map: undefined,
          hideMarkers: true,
          city: '上海',
        });

        transfer.search(
          [origin.lng, origin.lat],
          [destination.lng, destination.lat],
          (status: string, result: any) => {
            if (
              status === 'complete' &&
              result?.route?.transits?.[0]?.segments
            ) {
              const transit = result.route.transits[0];
              const polyline = this.parseTransitPath(transit.segments);

              resolve({
                polyline,
                transport: '地铁/公交',
                distance: Number(transit.distance) || 0,
                duration: Number(transit.duration) || 0,
                fromName: origin.name,
                toName: destination.name,
              });
            } else {
              resolve(this.createStubSegment(origin, destination, '地铁/公交'));
            }
          }
        );
      } catch {
        resolve(this.createStubSegment(origin, destination, '地铁/公交'));
      }
    });
  }

  /**
   * 创建两点间的 stub 路线（降级方案）
   * 当高德 API 调用失败时使用
   */
  private createStubSegment(
    origin: POI,
    destination: POI,
    transport: TransportMode
  ): RouteSegment {
    const dist = this.haversineDistance(
      [origin.lat, origin.lng],
      [destination.lat, destination.lng]
    );
    return {
      polyline: [[origin.lat, origin.lng], [destination.lat, destination.lng]],
      transport,
      distance: dist,
      duration: 0,
      fromName: origin.name,
      toName: destination.name,
    };
  }

  // ========================================================================
  // 3. Polyline 解析 - 对应后端 api_client.py
  // ========================================================================

  /**
   * 解析高德返回的 polyline 字符串
   * 对应后端: api_client.py _parse_gaode_polyline()
   * 
   * @param polylineStr - "lng,lat;lng,lat;..." 格式的字符串
   * @returns [[lat, lng], ...] 坐标数组
   */
  parseGaodePolyline(polylineStr: string | undefined | null): [number, number][] {
    if (!polylineStr || typeof polylineStr !== 'string' || !polylineStr.trim()) {
      return [];
    }

    const coords: [number, number][] = [];
    const items = polylineStr.split(';');

    for (const item of items) {
      if (!item) continue;
      const parts = item.split(',');
      if (parts.length < 2) continue;

      const lng = parseFloat(parts[0]);
      const lat = parseFloat(parts[1]);

      if (isNaN(lat) || isNaN(lng)) continue;

      // 转为 [lat, lng] 与后端一致
      coords.push([lat, lng]);
    }

    return coords;
  }

  /**
   * 解析高德步行/驾车/骑行路径
   * 对应后端: api_client.py _extract_path_polyline()
   * 
   * 处理 steps 数组，拼接所有 step 的 polyline
   * 支持两种格式：
   * 1. step.polyline: "lng,lat;lng,lat;..." 字符串
   * 2. step.path: AMap.LngLat[] 对象数组
   * 
   * @param steps 高德返回的 steps 数组
   * @returns [[lat, lng], ...] 坐标数组
   */
  parseGaodePath(steps: any[] | undefined): [number, number][] {
    if (!steps || !Array.isArray(steps) || steps.length === 0) {
      return [];
    }

    const chunks: [number, number][][] = [];

    for (const step of steps) {
      if (!step) continue;

      let chunk: [number, number][] = [];

      // 优先使用 polyline 字符串
      if (step.polyline && typeof step.polyline === 'string') {
        chunk = this.parseGaodePolyline(step.polyline);
      }
      // 其次使用 path 数组（AMap.LngLat 对象）
      else if (Array.isArray(step.path) && step.path.length > 0) {
        for (const p of step.path) {
          if (p && typeof p.getLng === 'function' && typeof p.getLat === 'function') {
            chunk.push([p.getLat(), p.getLng()]);
          } else if (typeof p.lng === 'number' && typeof p.lat === 'number') {
            chunk.push([p.lat, p.lng]);
          } else if (Array.isArray(p) && p.length >= 2) {
            chunk.push([p[1], p[0]]); // [lng, lat] -> [lat, lng]
          }
        }
      }

      if (chunk.length > 0) {
        chunks.push(chunk);
      }
    }

    if (chunks.length === 0) return [];
    if (chunks.length === 1) return chunks[0];

    return this.mergePolylineChunks(chunks, 5);
  }

  /**
   * 解析公交/地铁路径
   * 对应后端: api_client.py _extract_transit_polyline()
   * 
   * 处理 segments 数组，包含 walking 段和 bus 段
   * 
   * @param segments 高德公交路线 segments
   * @returns [[lat, lng], ...] 坐标数组
   */
  parseTransitPath(segments: any[] | undefined): [number, number][] {
    if (!segments || !Array.isArray(segments) || segments.length === 0) {
      return [];
    }

    const chunks: [number, number][][] = [];

    for (const segment of segments) {
      if (!segment) continue;

      // 步行段
      if (segment.walking?.steps) {
        const walkPoints = this.parseGaodePath(segment.walking.steps);
        if (walkPoints.length > 0) {
          chunks.push(walkPoints);
        }
      }

      // 公交段
      if (segment.bus?.buslines) {
        for (const line of segment.bus.buslines) {
          if (line?.polyline) {
            const busChunk = this.parseGaodePolyline(line.polyline);
            if (busChunk.length > 0) {
              chunks.push(busChunk);
            }
          }
        }
      }

      // 地铁/铁路段
      if (segment.railway) {
        const railwayChunks = this.collectNestedPolylines(segment.railway);
        for (const rc of railwayChunks) {
          if (rc.length > 0) {
            chunks.push(rc);
          }
        }
      }
    }

    if (chunks.length === 0) return [];
    if (chunks.length === 1) return chunks[0];

    return this.mergePolylineChunks(chunks, 5);
  }

  /**
   * 递归收集嵌套的 polyline
   * 对应后端: api_client.py _collect_nested_polylines()
   */
  private collectNestedPolylines(value: unknown): [number, number][][] {
    const chunks: [number, number][][] = [];

    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const obj = value as Record<string, unknown>;

      if (typeof obj.polyline === 'string') {
        const chunk = this.parseGaodePolyline(obj.polyline);
        if (chunk.length > 0) {
          chunks.push(chunk);
        }
      }

      for (const key of Object.keys(obj)) {
        if (key !== 'polyline') {
          chunks.push(...this.collectNestedPolylines(obj[key]));
        }
      }
    } else if (Array.isArray(value)) {
      for (const item of value) {
        chunks.push(...this.collectNestedPolylines(item));
      }
    }

    return chunks;
  }

  // ========================================================================
  // 4. Polyline 合并 - 对应后端 api_client.py _merge_polyline_chunks()
  // ========================================================================

  /**
   * 多段 polyline 拼接，去除接缝重合点
   * 对应后端: api_client.py _merge_polyline_chunks()
   * 
   * @param chunks 多段坐标数组
   * @param thresholdMeters 距离阈值（米），默认 5
   * @returns 拼接后的坐标数组
   */
  mergePolylineChunks(
    chunks: [number, number][][],
    thresholdMeters: number = 5
  ): [number, number][] {
    if (!chunks || chunks.length === 0) return [];
    if (chunks.length === 1) return chunks[0].slice();

    let merged = chunks[0].slice();

    for (let i = 1; i < chunks.length; i++) {
      const chunk = chunks[i];
      if (chunk.length === 0) continue;

      const lastPoint = merged[merged.length - 1];
      const firstPoint = chunk[0];
      const dist = this.haversineDistance(lastPoint, firstPoint);

      if (dist < thresholdMeters) {
        // 跳过重合的第一个点
        merged = merged.concat(chunk.slice(1));
      } else {
        merged = merged.concat(chunk);
      }
    }

    return merged;
  }

  // ========================================================================
  // 5. Douglas-Peucker 简化 - 对应后端 step3_micro.py _simplify_polyline()
  // ========================================================================

  /**
   * Douglas-Peucker 算法简化 polyline
   * 对应后端: step3_micro.py _simplify_polyline()
   * 
   * @param points [[lat, lng], ...] 坐标数组
   * @param tolerance 距离阈值（米）
   * @returns 简化后的坐标数组
   */
  simplifyPolyline(
    points: [number, number][],
    tolerance: number
  ): [number, number][] {
    if (!points || points.length <= 2) return points ? points.slice() : [];

    const result = this.douglasPeucker(
      points,
      0,
      points.length - 1,
      tolerance
    );

    // 确保首尾点保留
    if (result.length < 2) {
      return [points[0], points[points.length - 1]];
    }

    return result;
  }

  /**
   * Douglas-Peucker 递归实现
   * 对应后端: step3_micro.py _simplify_polyline() 内部 douglas_peucker()
   */
  private douglasPeucker(
    points: [number, number][],
    startIdx: number,
    endIdx: number,
    tolerance: number
  ): [number, number][] {
    if (endIdx - startIdx <= 1) {
      return [points[startIdx], points[endIdx]];
    }

    let maxDist = 0;
    let maxIdx = startIdx;

    for (let i = startIdx + 1; i < endIdx; i++) {
      const dist = this.pointToSegmentDistance(
        points[i],
        points[startIdx],
        points[endIdx]
      );
      if (dist > maxDist) {
        maxDist = dist;
        maxIdx = i;
      }
    }

    if (maxDist > tolerance) {
      const left = this.douglasPeucker(points, startIdx, maxIdx, tolerance);
      const right = this.douglasPeucker(points, maxIdx, endIdx, tolerance);
      // 避免重复 max_idx 点
      return left.slice(0, -1).concat(right);
    } else {
      return [points[startIdx], points[endIdx]];
    }
  }

  // ========================================================================
  // 6. 渲染前优化 - 对应后端 step3_micro.py _render_single_day_map()
  // ========================================================================

  /**
   * 单日路线渲染前优化
   * 对应后端: step3_micro.py _render_single_day_map()
   * 
   * 按顺序执行：
   * 1. 短段合并 (<500m, 同交通方式)
   * 2. 拼接处去重 (<15m)
   * 3. 支路去除 (投影回退>30m)
   * 4. 段间衔接 (<50m 空隙补接)
   * 5. Douglas-Peucker 简化 (步行5m, 其他30m)
   */
  optimizeForRender(segments: RouteSegment[]): RouteSegment[] {
    if (!segments || segments.length === 0) return [];

    // Step 1: 短段合并
    let result = this.mergeShortSegments(segments, 500);

    // Step 2: 拼接处去重
    result = this.deduplicateJoints(result, 15);

    // Step 3: 支路去除
    result = this.pruneBranches(result, 30);

    // Step 4: 段间衔接
    result = this.connectGaps(result, 50);

    // Step 5: Douglas-Peucker 简化
    for (const seg of result) {
      const tolerance = seg.transport === '步行' ? 5 : 30;
      seg.polyline = this.simplifyPolyline(seg.polyline, tolerance);
    }

    return result;
  }

  /**
   * 短段合并
   * 对应后端: step3_micro.py _merge_short_segments()
   * 
   * 相邻同交通方式且总距离 < threshold 的段合并
   */
  private mergeShortSegments(
    segments: RouteSegment[],
    threshold: number
  ): RouteSegment[] {
    if (!segments || segments.length === 0) return [];

    const merged: RouteSegment[] = [this.cloneSegment(segments[0])];

    for (let i = 1; i < segments.length; i++) {
      const seg = this.cloneSegment(segments[i]);
      const last = merged[merged.length - 1];

      if (
        last.transport === seg.transport &&
        last.distance + seg.distance < threshold
      ) {
        // 合并：polyline 拼接，去除接缝重合点
        last.polyline = this.mergePolylineChunks(
          [last.polyline, seg.polyline],
          5
        );
        last.distance += seg.distance;
        last.duration += seg.duration;
        last.toName = seg.toName;
      } else {
        merged.push(seg);
      }
    }

    return merged;
  }

  /**
   * 拼接处去重
   * 对应后端: step3_micro.py _deduplicate_joints()
   * 
   * 相邻段接缝处距离 < threshold 的去重
   */
  private deduplicateJoints(
    segments: RouteSegment[],
    threshold: number
  ): RouteSegment[] {
    if (!segments || segments.length < 2) return segments;

    for (let i = 1; i < segments.length; i++) {
      const prevSeg = segments[i - 1];
      const currSeg = segments[i];

      if (prevSeg.polyline.length === 0 || currSeg.polyline.length === 0) continue;

      const prevEnd = prevSeg.polyline[prevSeg.polyline.length - 1];
      const currStart = currSeg.polyline[0];

      if (this.haversineDistance(prevEnd, currStart) < threshold) {
        // 移除当前段的第一个点（与前一段末尾重合）
        currSeg.polyline = currSeg.polyline.slice(1);
      }
    }

    return segments;
  }

  /**
   * 支路去除
   * 对应后端: step3_micro.py _prune_branches()
   * 
   * 对于每个段，检查每个中间点。
   * 如果该点到其前后两点连线的投影回退距离 > threshold，视为支路点，移除。
   */
  private pruneBranches(
    segments: RouteSegment[],
    threshold: number
  ): RouteSegment[] {
    if (!segments) return [];

    for (const seg of segments) {
      if (seg.polyline.length < 3) continue;

      const pruned: [number, number][] = [seg.polyline[0]];

      for (let i = 1; i < seg.polyline.length - 1; i++) {
        const prev = pruned[pruned.length - 1];
        const next = seg.polyline[i + 1];
        const curr = seg.polyline[i];

        // 计算 curr 到 prev-next 连线的距离
        const dist = this.pointToSegmentDistance(curr, prev, next);
        if (dist <= threshold) {
          pruned.push(curr);
        }
        // 否则视为支路点，跳过
      }

      pruned.push(seg.polyline[seg.polyline.length - 1]);
      seg.polyline = pruned;
    }

    return segments;
  }

  /**
   * 段间空隙补接
   * 对应后端: step3_micro.py _connect_gaps()
   * 
   * 如果相邻段端点距离在 15m-threshold 之间，用直线连接
   */
  private connectGaps(
    segments: RouteSegment[],
    threshold: number
  ): RouteSegment[] {
    if (!segments || segments.length < 2) return segments;

    for (let i = 1; i < segments.length; i++) {
      const prevSeg = segments[i - 1];
      const currSeg = segments[i];

      if (prevSeg.polyline.length === 0 || currSeg.polyline.length === 0) continue;

      const prevEnd = prevSeg.polyline[prevSeg.polyline.length - 1];
      const currStart = currSeg.polyline[0];
      const dist = this.haversineDistance(prevEnd, currStart);

      if (15 < dist && dist < threshold) {
        // 在前一段末尾添加直线连接到当前段起点
        prevSeg.polyline.push(currStart);
      }
    }

    return segments;
  }

  // ========================================================================
  // 7. 地图渲染 - 对应后端 Folium → AMap
  // ========================================================================

  /**
   * 渲染单日路线到地图
   * 对应后端: step3_micro.py _render_single_day_map() 中的 Folium 渲染
   * 
   * 样式规则：
   * - 步行: strokeColor="#1890ff", strokeWeight=4, solid, showDir=true
   * - 地铁/公交: strokeColor="#52c41a", strokeWeight=5, dashed, dashArray=[10,10], showDir=true
   * - 自驾: strokeColor="#fa8c16", strokeWeight=5, dashed, dashArray=[10,10], showDir=true
   * - 骑行: strokeColor="#722ed1", strokeWeight=4, solid, showDir=true
   */
  renderDayRoute(dayRoute: DayRoute): AMap.Polyline[] {
    if (!this.map) return [];

    // 清除之前的覆盖物
    this.clearOverlays();

    const allPoints: [number, number][] = [];
    const newPolylines: AMap.Polyline[] = [];

    for (const segment of dayRoute.segments) {
      if (segment.polyline.length < 2) continue;

      const style = TRANSPORT_STYLES[segment.transport] || TRANSPORT_STYLES['步行'];

      // 转换坐标格式 [lat, lng] -> AMap.LngLat (需要 [lng, lat])
      const path = segment.polyline.map(
        ([lat, lng]) => new AMap.LngLat(lng, lat)
      );

      const polyline = new AMap.Polyline({
        path,
        strokeColor: style.strokeColor,
        strokeWeight: style.strokeWeight,
        strokeOpacity: 0.8,
        strokeStyle: style.isDashed ? 'dashed' : 'solid',
        strokeDasharray: style.dashArray,
        showDir: style.showDirection,
        zIndex: 50,
      });

      this.map.add(polyline);
      this.polylines.push(polyline);
      newPolylines.push(polyline);

      // 收集所有点用于计算边界
      allPoints.push(...segment.polyline);

      // 添加方向箭头
      if (style.showDirection) {
        this.addDirectionArrows(segment, style.strokeColor);
      }
    }

    // 自动调整视野
    if (allPoints.length > 0) {
      this.fitBounds(allPoints);
    }

    return newPolylines;
  }

  /**
   * 添加方向箭头
   * 对应后端: step3_micro.py 中的 folium.RegularPolygonMarker (三角形)
   * 
   * 使用 AMap.Marker + 自定义 SVG 三角形图标
   */
  addDirectionArrows(segment: RouteSegment, color: string): void {
    if (!this.map || segment.polyline.length < 2) return;

    // 在路线 1/4, 1/2, 3/4 处添加箭头
    const fractions = [0.25, 0.5, 0.75];

    for (const frac of fractions) {
      const point = this.getPointAtFraction(segment.polyline, frac);
      if (!point) continue;

      // 计算该点处的方向角度
      const idx = frac * (segment.polyline.length - 1);
      const fromIdx = Math.max(0, Math.floor(idx));
      const toIdx = Math.min(segment.polyline.length - 1, Math.ceil(idx));
      const angle = this.calculateAngle(
        segment.polyline[fromIdx],
        segment.polyline[toIdx]
      );

      // 创建 SVG 三角形箭头
      const svg = `
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
          <polygon points="8,2 14,14 2,14" fill="${color}" stroke="white" stroke-width="1"/>
        </svg>
      `;

      const marker = new AMap.Marker({
        position: [point[1], point[0]], // [lng, lat]
        content: `<div style="transform: rotate(${angle}deg); width: 16px; height: 16px;">${svg}</div>`,
        offset: new AMap.Pixel(-8, -8),
        zIndex: 60,
      });

      this.map.add(marker);
      this.arrows.push(marker);
    }
  }

  /**
   * 计算路线边界
   */
  calculateBounds(
    segments: RouteSegment[]
  ): { northEast: [number, number]; southWest: [number, number] } | null {
    if (!segments || segments.length === 0) return null;

    let minLat = Infinity,
      maxLat = -Infinity;
    let minLng = Infinity,
      maxLng = -Infinity;

    for (const seg of segments) {
      for (const [lat, lng] of seg.polyline) {
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
        if (lng < minLng) minLng = lng;
        if (lng > maxLng) maxLng = lng;
      }
    }

    if (minLat === Infinity) return null;

    return {
      northEast: [maxLat, maxLng],
      southWest: [minLat, minLng],
    };
  }

  /**
   * 调整地图视野以包含所有路线
   */
  fitBounds(points: [number, number][]): void {
    if (!this.map || points.length === 0) return;

    let minLat = Infinity,
      maxLat = -Infinity;
    let minLng = Infinity,
      maxLng = -Infinity;

    for (const [lat, lng] of points) {
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      if (lng < minLng) minLng = lng;
      if (lng > maxLng) maxLng = lng;
    }

    const bounds = new AMap.Bounds(
      new AMap.LngLat(minLng, minLat),
      new AMap.LngLat(maxLng, maxLat)
    );

    this.map.setBounds(bounds, true, [60, 60, 60, 60]);
  }

  /**
   * 清除所有地图覆盖物
   * 组件卸载时调用，避免内存泄漏
   */
  clearOverlays(): void {
    if (!this.map) return;

    for (const polyline of this.polylines) {
      this.map.remove(polyline);
    }
    for (const marker of this.markers) {
      this.map.remove(marker);
    }
    for (const arrow of this.arrows) {
      this.map.remove(arrow);
    }

    this.polylines = [];
    this.markers = [];
    this.arrows = [];
  }

  // ========================================================================
  // 8. 辅助方法 - 对应后端 api_client.py / step3_micro.py 中的工具函数
  // ========================================================================

  /**
   * Haversine 距离计算（米）
   * 对应后端: api_client.py _haversine_distance()
   * 
   * @param p1 [lat, lng]
   * @param p2 [lat, lng]
   * @returns 距离（米）
   */
  haversineDistance(
    p1: [number, number],
    p2: [number, number]
  ): number {
    const R = 6371000; // 地球半径（米）
    const dLat = this.toRad(p2[0] - p1[0]);
    const dLng = this.toRad(p2[1] - p1[1]);
    const lat1 = this.toRad(p1[0]);
    const lat2 = this.toRad(p2[0]);

    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1) * Math.cos(lat2) *
      Math.sin(dLng / 2) * Math.sin(dLng / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

    return R * c; // 返回米
  }

  /**
   * 点到线段的最短距离（米）
   * 对应后端: step3_micro.py _haversine_point_to_segment()
   * 
   * 用于 Douglas-Peucker 和支路去除
   */
  pointToSegmentDistance(
    point: [number, number],
    lineStart: [number, number],
    lineEnd: [number, number]
  ): number {
    // 将经纬度转换为近似笛卡尔坐标进行计算
    const latAvg = this.toRad(
      (point[0] + lineStart[0] + lineEnd[0]) / 3
    );
    const cosLat = Math.cos(latAvg);

    // 转换为米为单位的近似坐标
    const px = this.toRad(point[1]) * 6371000 * cosLat;
    const py = this.toRad(point[0]) * 6371000;
    const x1 = this.toRad(lineStart[1]) * 6371000 * cosLat;
    const y1 = this.toRad(lineStart[0]) * 6371000;
    const x2 = this.toRad(lineEnd[1]) * 6371000 * cosLat;
    const y2 = this.toRad(lineEnd[0]) * 6371000;

    const dx = x2 - x1;
    const dy = y2 - y1;

    if (dx === 0 && dy === 0) {
      // 线段退化为点
      return Math.sqrt((px - x1) ** 2 + (py - y1) ** 2);
    }

    // 计算投影参数 t
    const t = Math.max(
      0,
      Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy))
    );

    // 投影点
    const projX = x1 + t * dx;
    const projY = y1 + t * dy;

    // 返回点到投影点的距离（米）
    return Math.sqrt((px - projX) ** 2 + (py - projY) ** 2);
  }

  /**
   * 计算两点间角度（用于方向箭头旋转）
   * @param from [lat, lng]
   * @param to [lat, lng]
   * @returns 角度（度），正北为 0，顺时针
   */
  private calculateAngle(
    from: [number, number],
    to: [number, number]
  ): number {
    const dLng = this.toRad(to[1] - from[1]);
    const lat1 = this.toRad(from[0]);
    const lat2 = this.toRad(to[0]);

    const y = Math.sin(dLng) * Math.cos(lat2);
    const x =
      Math.cos(lat1) * Math.sin(lat2) -
      Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);

    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }

  /**
   * 获取线段上某比例的点（线性插值）
   */
  private getPointAtFraction(
    polyline: [number, number][],
    fraction: number
  ): [number, number] | null {
    if (!polyline || polyline.length < 2) return null;

    const n = polyline.length - 1;
    const exactIdx = fraction * n;
    const idx = Math.floor(exactIdx);
    const ratio = exactIdx - idx;

    if (idx >= n) return polyline[n];

    return [
      polyline[idx][0] + (polyline[idx + 1][0] - polyline[idx][0]) * ratio,
      polyline[idx][1] + (polyline[idx + 1][1] - polyline[idx][1]) * ratio,
    ];
  }

  /** 角度转弧度 */
  private toRad(deg: number): number {
    return (deg * Math.PI) / 180;
  }

  /** 深拷贝 RouteSegment */
  private cloneSegment(seg: RouteSegment): RouteSegment {
    return {
      polyline: seg.polyline.map(([lat, lng]) => [lat, lng]),
      transport: seg.transport,
      distance: seg.distance,
      duration: seg.duration,
      instructions: seg.instructions?.slice(),
      fromName: seg.fromName,
      toName: seg.toName,
    };
  }
}

/** 导出单例实例 */
export const routePolylineService = new RoutePolylineService();
