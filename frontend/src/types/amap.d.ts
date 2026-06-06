/* eslint-disable @typescript-eslint/no-explicit-any */
declare namespace AMap {
  class Map {
    constructor(container: string | HTMLElement, options?: MapOptions);
    add(overlay: any): void;
    remove(overlay: any): void;
    addControl(control: any): void;
    setCenter(center: [number, number]): void;
    setZoom(zoom: number): void;
    setFitView(overlays?: any, immediately?: boolean, avoid?: number[]): void;
    setBounds(bounds: Bounds, immediately?: boolean, avoid?: number[]): void;
    getBounds(): Bounds;
    destroy(): void;
    on(event: string, handler: (...args: any[]) => void): void;
    getAllOverlays(type?: string): any[];
    getSize(): Size;
  }

  interface MapOptions {
    zoom?: number;
    center?: [number, number];
    viewMode?: string;
    resizeEnable?: boolean;
    zooms?: [number, number];
    features?: string[];
    mapStyle?: string;
    showLabel?: boolean;
    scrollWheel?: boolean;
    doubleClickZoom?: boolean;
    keyboardEnable?: boolean;
    dragEnable?: boolean;
    touchZoom?: boolean;
    zoomEnable?: boolean;
    rotateEnable?: boolean;
    pitchEnable?: boolean;
  }

  class Marker {
    constructor(options?: MarkerOptions);
    on(event: string, handler: () => void): void;
    setPosition(pos: [number, number]): void;
    getPosition(): any;
    setMap(map: Map | null): void;
  }

  interface MarkerOptions {
    position?: [number, number] | LngLat;
    title?: string;
    content?: string;
    offset?: Pixel;
    zIndex?: number;
    label?: {
      content: string;
      direction?: string;
      offset?: Pixel;
    };
    icon?: Icon | string;
    extData?: any;
    clickable?: boolean;
    draggable?: boolean;
    visible?: boolean;
    map?: Map;
  }

  class Polyline {
    constructor(options?: PolylineOptions);
    setOptions(options: Partial<PolylineOptions>): void;
    getPath(): [number, number][] | LngLat[];
    setPath(path: [number, number][] | LngLat[]): void;
    getLength(): number;
    setMap(map: Map | null): void;
  }

  interface PolylineOptions {
    path?: [number, number][] | LngLat[];
    strokeColor?: string;
    strokeWeight?: number;
    strokeOpacity?: number;
    strokeStyle?: string;
    strokeDasharray?: number[];
    lineJoin?: string;
    lineCap?: string;
    showDir?: boolean;
    extData?: any;
    zIndex?: number;
    map?: Map;
  }

  class InfoWindow {
    constructor(options?: InfoWindowOptions);
    setContent(content: string): void;
    open(map: Map, position: [number, number] | LngLat): void;
    close(): void;
  }

  interface InfoWindowOptions {
    isCustom?: boolean;
    offset?: Pixel;
    content?: string;
  }

  class Pixel {
    constructor(x: number, y: number);
  }

  class Size {
    constructor(width: number, height: number);
    getWidth(): number;
    getHeight(): number;
  }

  class Icon {
    constructor(options?: IconOptions);
  }

  interface IconOptions {
    size?: Size;
    image?: string;
    imageSize?: Size;
  }

  class LngLat {
    constructor(lng: number, lat: number);
    getLng(): number;
    getLat(): number;
  }

  class Bounds {
    constructor(southWest: LngLat, northEast: LngLat);
    getSouthWest(): LngLat;
    getNorthEast(): LngLat;
    contains(point: LngLat): boolean;
  }

  class Scale {
    constructor(options?: any);
  }

  class ToolBar {
    constructor(options?: ToolBarOptions);
  }

  interface ToolBarOptions {
    position?: string;
  }

  class MapType {
    constructor(options?: any);
  }

  namespace TileLayer {
    class Traffic {
      constructor(options?: any);
    }
  }

  class Driving {
    constructor(options?: any);
    search(origin: any, destination: any, callback: (status: string, result: any) => void): void;
    clear(): void;
  }

  class Walking {
    constructor(options?: any);
    search(origin: any, destination: any, callback: (status: string, result: any) => void): void;
    clear(): void;
  }

  class Transfer {
    constructor(options?: any);
    search(origin: any, destination: any, callback: (status: string, result: any) => void): void;
    clear(): void;
  }

  class Riding {
    constructor(options?: any);
    search(origin: any, destination: any, callback: (status: string, result: any) => void): void;
    clear(): void;
  }

  class MoveAnimation {
    // Animation class
  }

  class CanvasRenderer {
    // Renderer class
  }

  // 地图截图插件
  class MapScreenShot {
    constructor(map: Map, options?: MapScreenShotOptions);
    capture(callback: (err: any, canvas: HTMLCanvasElement) => void): void;
  }

  interface MapScreenShotOptions {
    width?: number;
    height?: number;
  }

  // GeometryUtil - 几何计算工具
  namespace GeometryUtil {
    function distance(point1: LngLat | [number, number], point2: LngLat | [number, number]): number;
    function ringArea(path: LngLat[] | [number, number][]): number;
    function isPointInRing(point: LngLat | [number, number], ring: LngLat[] | [number, number][]): boolean;
    function doesRingRingIntersect(ring1: LngLat[] | [number, number][], ring2: LngLat[] | [number, number][]): boolean;
  }
}

interface Window {
  AMap: typeof AMap;
  Amap: typeof AMap;
  _AMapSecurityConfig?: { securityJsCode: string };
  __mapInstance?: any;
}
