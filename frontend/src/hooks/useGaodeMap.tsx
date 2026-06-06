import { useEffect, useRef, useCallback, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { useRouteStore } from '@/store/routeStore';
import type { POI, DailyRoute, EnroutePOI, TrafficSegment } from '@/api/types';
import { FALLBACK_HOME_LOCATION } from '@/utils/locationDefaults';
import POIActionMenu from '@/components/POIActionMenu/POIActionMenu';

// 从环境变量获取高德地图配置
const GAODE_KEY = import.meta.env.VITE_GAODE_JSAPI_KEY;
const GAODE_SECURITY = import.meta.env.VITE_GAODE_SECURITY_CONFIG;

// 验证 API Key 是否配置
if (!GAODE_KEY) {
  console.error('[useGaodeMap] 错误: VITE_GAODE_JSAPI_KEY 未配置，请在 .env 文件中设置');
}

// 主POI颜色：起点绿/途经蓝/终点红
const MAIN_POI_COLORS: Record<string, string> = {
  start: '#52c41a',
  waypoint: '#FFD100',
  end: '#f5222d',
};

// 交通状态颜色
const TRAFFIC_COLORS: Record<string, string> = {
  smooth: '#52c41a',      // 绿
  slow: '#FFD100',        // 黄
  congested: '#f5222d',   // 红
  blocked: '#820014',     // 深红
};

export function useGaodeMap(containerId: string) {
  const mapRef = useRef<AMap.Map | null>(null);
  const markersRef = useRef<AMap.Marker[]>([]);
  const enrouteMarkersRef = useRef<AMap.Marker[]>([]);
  const polylinesRef = useRef<AMap.Polyline[]>([]);
  const trafficLayerRef = useRef<AMap.TileLayer.Traffic | null>(null);
  const infoWindowRef = useRef<AMap.InfoWindow | null>(null);
  const carMarkerRef = useRef<AMap.Marker | null>(null);
  const animationRef = useRef<number | null>(null);

  const dailyRoutes = useRouteStore((s) => s.dailyRoutes);
  const enroutePOIs = useRouteStore((s) => s.enroutePOIs);
  const hiddenEnrouteIds = useRouteStore((s) => s.hiddenEnrouteIds);
  const selectedPoiId = useRouteStore((s) => s.selectedPoiId);
  const setSelectedPoi = useRouteStore((s) => s.setSelectedPoi);
  const setMapConfig = useRouteStore((s) => s.setMapConfig);
  const mapConfig = useRouteStore((s) => s.mapConfig);
  const replaceMode = useRouteStore((s) => s.replaceMode);
  const setReplaceMode = useRouteStore((s) => s.setReplaceMode);
  const addPoiToRoute = useRouteStore((s) => s.addPoiToRoute);
  const removePoiFromRoute = useRouteStore((s) => s.removePoiFromRoute);
  const replacePoiInRoute = useRouteStore((s) => s.replacePoiInRoute);
  const recordPoiLike = useRouteStore((s) => s.recordPoiLike);
  const recordPoiDislike = useRouteStore((s) => s.recordPoiDislike);
  const recordPoiRemove = useRouteStore((s) => s.recordPoiRemove);

  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  // 解析位置字符串为坐标数组
  const parseLocation = useCallback((location: string): [number, number] | null => {
    if (!location) return null;
    const parts = location.split(',');
    if (parts.length === 2) {
      const lng = parseFloat(parts[0]);
      const lat = parseFloat(parts[1]);
      if (!isNaN(lng) && !isNaN(lat)) {
        return [lng, lat];
      }
    }
    return null;
  }, []);

  // 解析高德 polyline 字符串为坐标数组
  const parsePolyline = useCallback((polyline: string): [number, number][] => {
    if (!polyline) return [];
    return polyline.split(';').map((point) => {
      const [lng, lat] = point.split(',').map(Number);
      return [lng, lat] as [number, number];
    }).filter(([lng, lat]) => !isNaN(lng) && !isNaN(lat));
  }, []);

  // 抽稀 polyline（道格拉斯-普克算法简化版）
  const simplifyPolyline = useCallback((coords: [number, number][], tolerance: number = 0.0001): [number, number][] => {
    if (coords.length <= 2) return coords;
    
    // 简单的距离抽稀
    const result: [number, number][] = [coords[0]];
    for (let i = 1; i < coords.length - 1; i++) {
      const prev = result[result.length - 1];
      const curr = coords[i];
      const distance = Math.sqrt(
        Math.pow(curr[0] - prev[0], 2) + Math.pow(curr[1] - prev[1], 2)
      );
      if (distance > tolerance) {
        result.push(curr);
      }
    }
    result.push(coords[coords.length - 1]);
    return result;
  }, []);

  // 加载高德 JS API
  const loadGaodeAPI = useCallback((): Promise<void> => {
    return new Promise((resolve, reject) => {
      if (window.AMap) {
        resolve();
        return;
      }

      if (!GAODE_KEY) {
        reject(new Error('未配置高德地图 API Key，请在 .env 文件中设置 VITE_GAODE_JSAPI_KEY'));
        return;
      }

      if (GAODE_SECURITY) {
        window._AMapSecurityConfig = { securityJsCode: GAODE_SECURITY };
      }

      const script = document.createElement('script');
      script.src = `https://webapi.amap.com/maps?v=2.0&key=${GAODE_KEY}&plugin=AMap.Driving,AMap.Walking,AMap.Transfer,AMap.Riding,AMap.InfoWindow,AMap.Marker,AMap.Polyline,AMap.MoveAnimation,AMap.CanvasRenderer,AMap.Scale,AMap.ToolBar,AMap.MapType`;
      script.async = true;
      script.onload = () => {
        if (window.AMap) {
          resolve();
        } else {
          reject(new Error('高德地图 API 加载完成但未找到 AMap 对象'));
        }
      };
      script.onerror = () => reject(new Error('高德地图 API 加载失败，请检查网络连接和 API Key 是否正确'));
      document.head.appendChild(script);
    });
  }, []);

  // 打开 POI 操作菜单（替代 InfoWindow）
  const openPoiActionMenu = useCallback((
    poi: POI,
    position: [number, number],
    isEnroute: boolean,
    map: AMap.Map
  ) => {
    if (!infoWindowRef.current) return;

    const container = document.createElement('div');
    container.style.cssText = 'position:relative;overflow:visible;';

    const root = ReactDOM.createRoot(container);

    const handleClose = () => {
      if (infoWindowRef.current) {
        infoWindowRef.current.close();
      }
      root.unmount();
    };

    const handleReplace = () => {
      if (replaceMode && replaceMode.active) {
        // 替换模式已激活，执行替换
        if (replaceMode.sourceType === 'enroute' && !isEnroute) {
          // 备选替换路线内：source=enroute, target=route
          const sourcePoi = enroutePOIs.find(p => p.id === replaceMode.sourcePoiId);
          if (sourcePoi) {
            replacePoiInRoute(poi.id, sourcePoi as any);
          }
        } else if (replaceMode.sourceType === 'route' && isEnroute) {
          // 路线内替换为备选：source=route, target=enroute
          replacePoiInRoute(replaceMode.sourcePoiId, poi as any);
        }
        handleClose();
        return;
      }
      // 激活替换模式
      setReplaceMode({
        active: true,
        sourcePoiId: poi.id,
        sourceType: isEnroute ? 'enroute' : 'route',
      });
      handleClose();
    };

    const poitype = poi.type || poi.category || '';

    root.render(
      <POIActionMenu
        poiName={poi.name}
        poiType={poitype}
        isEnroute={isEnroute}
        replaceModeActive={replaceMode?.active && replaceMode.sourcePoiId === poi.id}
        onAddToRoute={isEnroute ? () => { addPoiToRoute(poi as any); handleClose(); } : undefined}
        onRemoveFromRoute={!isEnroute ? () => {
          removePoiFromRoute(poi.id);
          recordPoiRemove(poi.name, poitype);
          handleClose();
        } : undefined}
        onSwap={handleReplace}
        onLike={!isEnroute ? () => { recordPoiLike(poi.name, poitype); handleClose(); } : undefined}
        onDislike={isEnroute ? () => { recordPoiDislike(poi.name, poitype); handleClose(); } : undefined}
        onClose={handleClose}
      />
    );

    infoWindowRef.current.setContent(container as unknown as string);
    infoWindowRef.current.open(map, position);
  }, [replaceMode, enroutePOIs, setReplaceMode, addPoiToRoute, removePoiFromRoute, replacePoiInRoute, recordPoiLike, recordPoiDislike, recordPoiRemove]);

  // 创建主POI标记
  const createMainMarker = useCallback((
    poi: POI,
    index: number,
    totalCount: number,
    map: AMap.Map
  ): AMap.Marker | null => {
    const position = parseLocation(poi.location);
    if (!position) return null;

    const isFirst = index === 0;
    const isLast = index === totalCount - 1;
    const color = isFirst ? MAIN_POI_COLORS.start : isLast ? MAIN_POI_COLORS.end : MAIN_POI_COLORS.waypoint;
    const label = isFirst ? '起' : isLast ? '终' : `${index + 1}`;
    const textColor = isFirst ? '#fff' : isLast ? '#fff' : '#333';

    const marker = new window.AMap.Marker({
      position,
      title: poi.name,
      content: `
        <div style="
          width: 32px; height: 32px; border-radius: 50%;
          background: ${color}; border: 3px solid #fff;
          display: flex; align-items: center; justify-content: center;
          color: ${textColor}; font-size: 13px; font-weight: bold;
          box-shadow: 0 2px 8px rgba(0,0,0,0.4);
          cursor: pointer;
        ">${label}</div>
      `,
      offset: new window.AMap.Pixel(-16, -16),
      zIndex: 100 - index,
    });

    marker.on('click', () => {
      if (replaceMode?.active && replaceMode.sourceType === 'enroute') {
        // 替换模式：点击路线内 POI 作为替换目标
        const sourcePoi = enroutePOIs.find(p => p.id === replaceMode.sourcePoiId);
        if (sourcePoi) {
          replacePoiInRoute(poi.id, sourcePoi as any);
          setReplaceMode(null);
        }
        return;
      }
      setSelectedPoi(poi.id);
      if (infoWindowRef.current) {
        openPoiActionMenu(poi, position, false, map);
      }
    });

    return marker;
  }, [parseLocation, setSelectedPoi]);

  // 创建沿途POI标记（紫色菱形/星形）
  const createEnrouteMarker = useCallback((
    poi: EnroutePOI,
    index: number,
    map: AMap.Map
  ): AMap.Marker | null => {
    const position = parseLocation(poi.location);
    if (!position) return null;

    const label = `E${index + 1}`;

    const marker = new window.AMap.Marker({
      position,
      title: poi.name,
      content: `
        <div style="
          width: 20px; height: 20px;
          background: linear-gradient(135deg, #722ed1, #9254de);
          border: 2px solid rgba(255,255,255,0.7);
          transform: rotate(45deg);
          display: flex; align-items: center; justify-content: center;
          box-shadow: 0 1px 4px rgba(114,46,209,0.3);
          cursor: pointer;
          opacity: 0.85;
        ">
          <span style="
            transform: rotate(-45deg);
            color: #fff; font-size: 9px; font-weight: bold;
          ">${label}</span>
        </div>
      `,
      offset: new window.AMap.Pixel(-10, -10),
      zIndex: 70 - index,
    });

    marker.on('click', () => {
      if (replaceMode?.active && replaceMode.sourceType === 'route') {
        // 替换模式：点击备选 POI 作为替换来源
        replacePoiInRoute(replaceMode.sourcePoiId, poi as any);
        setReplaceMode(null);
        return;
      }
      setSelectedPoi(poi.id);
      if (infoWindowRef.current) {
        openPoiActionMenu(poi, position, true, map);
      }
    });

    return marker;
  }, [parseLocation, setSelectedPoi]);

  // 绘制带路况分段的 polyline
  const drawSegmentedPolyline = useCallback((
    polylineStr: string,
    trafficSegments: TrafficSegment[],
    map: AMap.Map
  ): AMap.Polyline[] => {
    const coords = parsePolyline(polylineStr);
    if (coords.length < 2) return [];

    const lines: AMap.Polyline[] = [];

    if (!trafficSegments || trafficSegments.length === 0) {
      // 无路况信息，绘制单色线
      const line = new window.AMap.Polyline({
        path: coords,
        strokeColor: '#FFD100',
        strokeWeight: 6,
        strokeOpacity: 0.9,
        strokeStyle: 'solid',
        zIndex: 50,
        showDir: true,
      });
      map.add(line);
      lines.push(line);
      return lines;
    }

    // 按路况分段绘制
    const sortedSegments = [...trafficSegments].sort((a, b) => a.start_index - b.start_index);
    
    let lastEndIndex = 0;
    
    sortedSegments.forEach((segment) => {
      // 绘制路段前的部分（默认绿色）
      if (segment.start_index > lastEndIndex) {
        const beforeCoords = coords.slice(lastEndIndex, segment.start_index + 1);
        if (beforeCoords.length >= 2) {
          const line = new window.AMap.Polyline({
            path: simplifyPolyline(beforeCoords, 0.0002),
            strokeColor: TRAFFIC_COLORS.smooth,
            strokeWeight: 6,
            strokeOpacity: 0.9,
            strokeStyle: 'solid',
            zIndex: 50,
            showDir: true,
          });
          map.add(line);
          lines.push(line);
        }
      }

      // 绘制路况路段
      const segmentCoords = coords.slice(segment.start_index, segment.end_index + 1);
      if (segmentCoords.length >= 2) {
        const line = new window.AMap.Polyline({
          path: simplifyPolyline(segmentCoords, 0.0002),
          strokeColor: TRAFFIC_COLORS[segment.status] || '#FFD100',
          strokeWeight: 6,
          strokeOpacity: 0.9,
          strokeStyle: 'solid',
          zIndex: 50,
          showDir: true,
        });
        map.add(line);
        lines.push(line);
      }

      lastEndIndex = segment.end_index;
    });

    // 绘制最后一段
    if (lastEndIndex < coords.length - 1) {
      const lastCoords = coords.slice(lastEndIndex);
      if (lastCoords.length >= 2) {
        const line = new window.AMap.Polyline({
          path: simplifyPolyline(lastCoords, 0.0002),
          strokeColor: TRAFFIC_COLORS.smooth,
          strokeWeight: 6,
          strokeOpacity: 0.9,
          strokeStyle: 'solid',
          zIndex: 50,
          showDir: true,
        });
        map.add(line);
        lines.push(line);
      }
    }

    return lines;
  }, [parsePolyline, simplifyPolyline]);

// 初始化地图 - 使用高德地图 complete 事件
  useEffect(() => {
    let destroyed = false;
    let mapInstance: AMap.Map | null = null;

    const init = async () => {
      try {
        await loadGaodeAPI();
        if (destroyed) return;

        console.log('开始初始化地图...');

        const container = document.getElementById(containerId);
        if (!container) {
          const errorMsg = `地图容器未找到: ${containerId}`;
          console.error(errorMsg);
          setMapError(errorMsg);
          return;
        }

        // 确保容器有正确的尺寸
        const rect = container.getBoundingClientRect();
        console.log('地图容器信息:', {
          id: containerId,
          width: rect.width,
          height: rect.height,
          styleWidth: container.style.width,
          styleHeight: container.style.height
        });

        if (rect.width === 0 || rect.height === 0) {
          console.warn('地图容器尺寸为0，尝试强制设置尺寸...');
          container.style.width = '100%';
          container.style.height = '100%';
          if (container.parentElement) {
            container.parentElement.style.width = '100%';
            container.parentElement.style.height = '100%';
          }
        }

        const mapOptions: AMap.MapOptions = {
          zoom: mapConfig.zoom || 12,
          center:
            typeof mapConfig.center === 'string'
              ? parseLocation(mapConfig.center) || [FALLBACK_HOME_LOCATION.lng, FALLBACK_HOME_LOCATION.lat]
              : mapConfig.center || [FALLBACK_HOME_LOCATION.lng, FALLBACK_HOME_LOCATION.lat],
          mapStyle: 'amap://styles/normal',
          showLabel: true,
          viewMode: '2D',
          resizeEnable: true,
          zooms: [3, 20],
          features: ['bg', 'road', 'building', 'point'],
        };

        console.log('创建地图实例，选项:', mapOptions);
        
        mapInstance = new window.AMap.Map(container, mapOptions);
        mapRef.current = mapInstance;

        mapInstance.on('complete', () => {
          console.log('高德地图加载完成事件触发！');
          if (!destroyed) {
            setMapReady(true);
            setMapError(null);
          }
        });

        setTimeout(() => {
          if (!destroyed && mapRef.current) {
            console.log('备用：强制设置地图就绪');
            setMapReady(true);
          }
        }, 3000);

        infoWindowRef.current = new window.AMap.InfoWindow({
          isCustom: true,
          offset: new window.AMap.Pixel(0, -30),
        });

        console.log('地图实例已创建');

      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : '地图初始化失败';
        console.error('地图初始化错误:', err);
        setMapError(errorMsg);
      }
    };

    init();

    return () => {
      destroyed = true;
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      if (mapRef.current) {
        console.log('销毁地图...');
        mapRef.current.destroy();
        mapRef.current = null;
        setMapReady(false);
      }
    };
  }, [containerId]);

  // 清除覆盖物
  const clearOverlays = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;

    markersRef.current.forEach((m) => map.remove(m));
    enrouteMarkersRef.current.forEach((m) => map.remove(m));
    polylinesRef.current.forEach((p) => map.remove(p));
    
    if (carMarkerRef.current) {
      map.remove(carMarkerRef.current);
      carMarkerRef.current = null;
    }
    
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }

    markersRef.current = [];
    enrouteMarkersRef.current = [];
    polylinesRef.current = [];
  }, []);

  // 渲染路线
  const renderRoute = useCallback(
    (routes: DailyRoute[]) => {
      const map = mapRef.current;
      if (!map || !mapReady) return;

      clearOverlays();

      const allBounds: [number, number][] = [];

      routes.forEach((dailyRoute) => {
        const points = dailyRoute.points || dailyRoute.pois.map((poi) => ({
          poi,
          poi_type: 'main' as const,
          polyline: '',
        }));
        const mainPois = dailyRoute.main_pois || points.filter(p => p.poi_type !== 'enroute').map(p => p.poi);
        const trafficSegments = dailyRoute.traffic_segments || [];

        mainPois.forEach((poi, poiIndex) => {
          const marker = createMainMarker(poi, poiIndex, mainPois.length, map);
          if (marker) {
            map.add(marker);
            markersRef.current.push(marker);
            
            const position = parseLocation(poi.location);
            if (position) allBounds.push(position);
          }
        });

        if (dailyRoute.polyline) {
          const lines = drawSegmentedPolyline(dailyRoute.polyline, trafficSegments, map);
          polylinesRef.current.push(...lines);
        } else {
          points.forEach((point) => {
            if (point.polyline) {
              const coords = parsePolyline(point.polyline);
              if (coords.length >= 2) {
                const line = new window.AMap.Polyline({
                  path: simplifyPolyline(coords, 0.0002),
                  strokeColor: '#FFD100',
                  strokeWeight: 6,
                  strokeOpacity: 0.9,
                  strokeStyle: 'solid',
                  zIndex: 50,
                  showDir: true,
                });
                map.add(line);
                polylinesRef.current.push(line);
              }
            }
          });
        }
      });

      if (allBounds.length > 0) {
        map.setFitView(markersRef.current, true, [60, 60, 60, 60]);
      }
    },
    [mapReady, clearOverlays, createMainMarker, drawSegmentedPolyline, parseLocation, parsePolyline, simplifyPolyline]
  );

  // 渲染沿途POI标记
  const renderEnroutePOIs = useCallback(
    (enroutePois: EnroutePOI[], hiddenIds: Set<string>) => {
      const map = mapRef.current;
      if (!map || !mapReady) return;

      enrouteMarkersRef.current.forEach((m) => map.remove(m));
      enrouteMarkersRef.current = [];

      const visiblePOIs = enroutePois.filter((p) => !hiddenIds.has(p.id));

      visiblePOIs.forEach((poi, index) => {
        const marker = createEnrouteMarker(poi, index, map);
        if (marker) {
          map.add(marker);
          enrouteMarkersRef.current.push(marker);
        }
      });
    },
    [mapReady, createEnrouteMarker]
  );

  // 路线动画
  const startRouteAnimation = useCallback((polylineStr: string, duration: number = 5000) => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const coords = parsePolyline(polylineStr);
    if (coords.length < 2) return;

    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
    }
    if (carMarkerRef.current) {
      map.remove(carMarkerRef.current);
    }

    const carMarker = new window.AMap.Marker({
      position: coords[0],
      content: `
        <div style="
          width: 28px; height: 28px;
          background: #FFD100;
          border-radius: 50%;
          border: 3px solid #fff;
          box-shadow: 0 2px 8px rgba(255,209,0,0.5);
          display: flex;
          align-items: center;
          justify-content: center;
        ">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="#333">
            <path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z"/>
          </svg>
        </div>
      `,
      offset: new window.AMap.Pixel(-14, -14),
      zIndex: 200,
    });

    map.add(carMarker);
    carMarkerRef.current = carMarker;

    const totalLength = coords.reduce((sum, coord, i) => {
      if (i === 0) return 0;
      const prev = coords[i - 1];
      return sum + Math.sqrt(Math.pow(coord[0] - prev[0], 2) + Math.pow(coord[1] - prev[1], 2));
    }, 0);

    let startTime: number | null = null;

    const animate = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const elapsed = timestamp - startTime;
      const progress = Math.min(elapsed / duration, 1);

      const targetDistance = progress * totalLength;
      let currentDistance = 0;
      let currentIndex = 0;

      for (let i = 1; i < coords.length; i++) {
        const prev = coords[i - 1];
        const curr = coords[i];
        const segmentLength = Math.sqrt(Math.pow(curr[0] - prev[0], 2) + Math.pow(curr[1] - prev[1], 2));
        
        if (currentDistance + segmentLength >= targetDistance) {
          currentIndex = i - 1;
          break;
        }
        currentDistance += segmentLength;
      }

      const segmentProgress = (targetDistance - currentDistance) / 
        (Math.sqrt(Math.pow(coords[currentIndex + 1][0] - coords[currentIndex][0], 2) + 
                    Math.pow(coords[currentIndex + 1][1] - coords[currentIndex][1], 2)) || 1);
      
      const lng = coords[currentIndex][0] + (coords[currentIndex + 1][0] - coords[currentIndex][0]) * segmentProgress;
      const lat = coords[currentIndex][1] + (coords[currentIndex + 1][1] - coords[currentIndex][1]) * segmentProgress;

      carMarker.setPosition([lng, lat]);

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate);
      }
    };

    animationRef.current = requestAnimationFrame(animate);
  }, [mapReady, parsePolyline]);

  const stopAnimation = useCallback(() => {
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }
    if (carMarkerRef.current && mapRef.current) {
      mapRef.current.remove(carMarkerRef.current);
      carMarkerRef.current = null;
    }
  }, []);

  const centerToPoi = useCallback((poi: POI) => {
    const map = mapRef.current;
    if (!map) return;

    const position = parseLocation(poi.location);
    if (!position) return;

    map.setCenter(position);
    map.setZoom(15);

    if (infoWindowRef.current) {
      infoWindowRef.current.setContent(`
        <div style="padding: 12px; min-width: 200px; border-radius: 8px; background: #fff; box-shadow: 0 2px 12px rgba(0,0,0,0.15);">
          <div style="font-weight: bold; font-size: 14px; margin-bottom: 4px;">${poi.name}</div>
          <div style="color: #666; font-size: 12px;">${poi.address}</div>
        </div>
      `);
      infoWindowRef.current.open(map, position);
    }
  }, [parseLocation]);

  const toggleTraffic = useCallback(
    (show: boolean) => {
      setMapConfig({ showTraffic: show });
    },
    [setMapConfig]
  );

  useEffect(() => {
    if (mapReady && dailyRoutes.length > 0) {
      renderRoute(dailyRoutes);
    }
  }, [mapReady, dailyRoutes]);

  useEffect(() => {
    if (mapReady && dailyRoutes.length > 0) {
      console.log('Rendering routes:', dailyRoutes.length);
      renderRoute(dailyRoutes);
    }
  }, [mapReady, renderRoute]);

  useEffect(() => {
    if (mapReady) {
      renderEnroutePOIs(enroutePOIs, hiddenEnrouteIds);
    }
  }, [mapReady, enroutePOIs, hiddenEnrouteIds, renderEnroutePOIs]);

  useEffect(() => {
    if (selectedPoiId && mapReady) {
      const pois = dailyRoutes.flatMap((d) => (d.points || d.pois.map((poi) => ({ poi }))).map((p) => p.poi));
      const enroutePoisList = dailyRoutes.flatMap((d) => d.enroute_pois || []);
      const allPois = [...pois, ...enroutePoisList];
      
      const poi = allPois.find((p) => p.id === selectedPoiId);
      if (poi) centerToPoi(poi);
    }
  }, [selectedPoiId, mapReady, dailyRoutes, centerToPoi]);

  return {
    map: mapRef.current,
    mapReady,
    mapError,
    renderRoute,
    renderEnroutePOIs,
    centerToPoi,
    toggleTraffic,
    clearOverlays,
    startRouteAnimation,
    stopAnimation,
  };
}
