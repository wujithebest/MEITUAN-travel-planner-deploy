import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Spin, message } from 'antd';
import { Camera } from 'lucide-react';

interface MapSnapshotProps {
  center: [number, number];
  zoom?: number;
  polylines?: Array<{
    path: [number, number][];
    color?: string;
  }>;
  markers?: Array<{
    position: [number, number];
    title?: string;
  }>;
  width?: number;
  height?: number;
  onCapture?: (base64: string) => void;
  onError?: (error: Error) => void;
}

// 高德地图截图插件 AMap.MapScreenShot
// 需要在 index.html 中加载: //webapi.amap.com/maps?v=2.0&key=YOUR_KEY&plugin=AMap.MapScreenShot

const MapSnapshot: React.FC<MapSnapshotProps> = ({
  center,
  zoom = 12,
  polylines = [],
  markers = [],
  width = 300,
  height = 400,
  onCapture,
  onError,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const [loading, setLoading] = useState(true);
  const [capturing, setCapturing] = useState(false);

  // 初始化小地图实例
  useEffect(() => {
    console.log('[MapSnapshot] 初始化地图...', { center, zoom, width, height });
    
    if (!containerRef.current) {
      console.error('[MapSnapshot] containerRef.current 为 null');
      return;
    }

    // 检查高德地图是否已加载
    if (typeof window.AMap === 'undefined') {
      console.error('[MapSnapshot] 高德地图 AMap 未加载');
      message.error('地图组件加载失败');
      setLoading(false);
      return;
    }

    try {
      // 创建独立的小地图实例
      const map = new window.AMap.Map(containerRef.current, {
        center,
        zoom,
        mapStyle: 'amap://styles/normal',
        showLabel: true,
        resizeEnable: false,
        scrollWheel: false,
        doubleClickZoom: false,
        keyboardEnable: false,
        dragEnable: false,
        touchZoom: false,
        zoomEnable: false,
        rotateEnable: false,
        pitchEnable: false,
        viewMode: '2D',
        features: ['bg', 'road', 'building', 'point'],
      });

      mapRef.current = map;

      // 等待地图加载完成
      map.on('complete', () => {
        console.log('[MapSnapshot] 地图加载完成');
        
        // 添加折线
        if (polylines.length > 0) {
          polylines.forEach((polyline, idx) => {
            if (polyline.path && polyline.path.length > 1) {
              new window.AMap.Polyline({
                path: polyline.path,
                strokeColor: polyline.color || '#FFD100',
                strokeWeight: 4,
                strokeOpacity: 0.8,
                map,
              });
            }
          });
        }

        // 添加标记点
        if (markers.length > 0) {
          markers.forEach((marker) => {
            new window.AMap.Marker({
              position: marker.position,
              title: marker.title,
              map,
            });
          });
        }

        // 自动调整视野
        if (polylines.length > 0 || markers.length > 0) {
          map.setFitView(null, false, [20, 20, 20, 20]);
        }

        setLoading(false);
      });

      // 错误处理
      map.on('error', (e: any) => {
        console.error('[MapSnapshot] 地图错误:', e);
        setLoading(false);
      });

    } catch (error) {
      console.error('[MapSnapshot] 创建地图失败:', error);
      setLoading(false);
      onError?.(error as Error);
    }

    // 清理函数
    return () => {
      console.log('[MapSnapshot] 销毁地图实例');
      if (mapRef.current) {
        mapRef.current.destroy();
        mapRef.current = null;
      }
    };
  }, [center, zoom, polylines, markers, onError]);

  // 截图功能
  const captureMap = useCallback(async () => {
    console.log('[MapSnapshot] 开始截图...');
    
    if (!mapRef.current) {
      console.error('[MapSnapshot] 地图实例不存在');
      message.error('地图未就绪');
      return;
    }

    setCapturing(true);

    try {
      // 检查是否支持 AMap.MapScreenShot 插件
      if (window.AMap.MapScreenShot) {
        console.log('[MapSnapshot] 使用 AMap.MapScreenShot 插件截图');
        
        const screenshot = new window.AMap.MapScreenShot(mapRef.current, {
          width,
          height,
        });

        screenshot.capture((err: any, canvas: HTMLCanvasElement) => {
          if (err) {
            console.error('[MapSnapshot] 截图失败:', err);
            message.error('截图失败');
            setCapturing(false);
            return;
          }

          console.log('[MapSnapshot] 截图成功:', {
            width: canvas.width,
            height: canvas.height
          });

          const base64 = canvas.toDataURL('image/png');
          onCapture?.(base64);
          setCapturing(false);
        });
      } else {
        // 备用方案：使用 html2canvas
        console.log('[MapSnapshot] MapScreenShot 不可用，使用 html2canvas');
        
        const html2canvas = (await import('html2canvas')).default;
        
        if (!containerRef.current) {
          throw new Error('容器不存在');
        }

        const canvas = await html2canvas(containerRef.current, {
          useCORS: true,
          allowTaint: true,
          scale: 2,
          width,
          height,
          backgroundColor: '#ffffff',
          logging: false,
        });

        console.log('[MapSnapshot] html2canvas 截图成功:', {
          width: canvas.width,
          height: canvas.height
        });

        if (canvas.width === 0 || canvas.height === 0) {
          throw new Error('截图尺寸为 0');
        }

        const base64 = canvas.toDataURL('image/png');
        onCapture?.(base64);
        setCapturing(false);
      }
    } catch (error) {
      console.error('[MapSnapshot] 截图失败:', error);
      message.error('截图失败');
      setCapturing(false);
      onError?.(error as Error);
    }
  }, [width, height, onCapture, onError]);

  return (
    <div className="map-snapshot-container" style={{ position: 'relative', width, height }}>
      <Spin spinning={loading} tip="地图加载中...">
        <div
          ref={containerRef}
          style={{
            width: `${width}px`,
            height: `${height}px`,
            borderRadius: '8px',
            overflow: 'hidden',
          }}
        />
      </Spin>
      
      {/* 截图按钮 */}
      {!loading && (
        <button
          onClick={captureMap}
          disabled={capturing}
          style={{
            position: 'absolute',
            bottom: '8px',
            right: '8px',
            padding: '4px 8px',
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            border: '1px solid #d9d9d9',
            borderRadius: '4px',
            cursor: capturing ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            fontSize: '12px',
          }}
        >
          <Camera size={14} />
          {capturing ? '截图中...' : '截图'}
        </button>
      )}
    </div>
  );
};

export default MapSnapshot;
