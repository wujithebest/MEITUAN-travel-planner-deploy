# 🗺️ 智能旅游路线规划前端

基于 React + TypeScript 的单页应用，自然语言输入 → 后端生成路线 → 渲染地图 + 按天时间轴。支持多人协作编辑、旅行日记生成。

## 技术栈

| 类别 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript + Vite |
| 状态管理 | Zustand |
| HTTP 客户端 | axios |
| 实时通信 | WebSocket (原生) |
| UI 组件库 | Ant Design 5 |
| 地图 | 高德地图 JS API 2.0 |
| 拖拽 | @dnd-kit |
| 导出 | html2canvas + jsPDF |
| 语音 | Web Speech API |
| 图标 | Lucide React |
| 样式 | CSS Modules |

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填写：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# FastAPI 后端地址
VITE_API_BASE_URL=http://localhost:8002

# WebSocket 地址
VITE_WS_URL=ws://localhost:8002

# 高德地图 JS API Key（前端专用，与后端 Key 不同！）
# 申请地址：https://console.amap.com/dev/key/app
# ⚠️ 重要：前端 Key 需要开通「Web 端(JS API)」服务
# ⚠️ 注意：前端 Key 和后端 Key 是不同的，不要混用！
VITE_GAODE_JSAPI_KEY=your_frontend_jsapi_key

# 高德地图安全密钥
# 在高德控制台 → 应用管理 → 配置安全密钥
VITE_GAODE_SECURITY_CONFIG=your_security_code
```

### 3. 高德地图 JS API Key 申请指南

1. 访问 [高德开放平台](https://console.amap.com/dev/key/app)
2. 创建新应用，选择「Web 端(JS API)」
3. 获取 Key 和安全密钥
4. ⚠️ **前端 Key 与后端 Key 不同**：后端使用「Web 服务」Key，前端使用「Web 端(JS API)」Key
5. 将前端 Key 填入 `VITE_GAODE_JSAPI_KEY`
6. 将安全密钥填入 `VITE_GAODE_SECURITY_CONFIG`

### 4. 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:3000

### 5. 构建生产版本

```bash
npm run build
```

## 项目结构

```
src/
├── api/              # API 客户端
│   ├── client.ts     # Axios 实例
│   ├── route.ts      # 路线 API
│   ├── weather.ts    # 天气 API
│   ├── collab.ts     # 协作 API
│   ├── diary.ts      # 日记 API
│   └── types.ts      # TypeScript 类型定义
├── components/       # 组件
│   ├── MapContainer/     # 高德地图容器
│   ├── RouteTimeline/    # 路线时间轴
│   ├── DailyTimeline/    # 每日时间轴（含拖拽）
│   ├── WeatherBar/       # 天气条
│   ├── TrafficLegend/    # 路况图例
│   ├── LocationInput/    # 地点输入（含语音）
│   ├── POICard/          # POI 卡片
│   ├── DisambiguationModal/  # POI 消歧义弹窗
│   ├── CollabPanel/      # 协作面板
│   ├── InviteModal/      # 邀请弹窗
│   ├── DiaryPreview/     # 日记预览
│   ├── DiaryEditor/      # 日记编辑器
│   ├── ExportModal/      # 导出弹窗
│   └── LoadingOverlay/   # 加载遮罩
├── pages/            # 页面
│   ├── PlannerPage/  # 规划页面（三栏布局）
│   └── DiaryPage/    # 日记页面
├── store/            # Zustand 状态
│   ├── routeStore.ts # 路线状态
│   ├── collabStore.ts# 协作状态
│   └── diaryStore.ts # 日记状态
├── hooks/            # 自定义 Hooks
│   ├── useGaodeMap.ts        # 高德地图集成
│   ├── useRouteGenerate.ts   # 路线生成
│   ├── useWebSocket.ts       # WebSocket 连接
│   ├── useCollab.ts         # 协作逻辑
│   ├── useDiary.ts          # 日记逻辑
│   └── useSpeechRecognition.ts # 语音识别
├── utils/            # 工具函数
│   ├── formatters.ts # 格式化
│   └── validators.ts # 验证
├── types/            # 类型声明
│   └── amap.d.ts     # 高德地图类型
├── App.tsx           # 应用入口
├── App.css           # 全局样式
└── main.tsx          # React 入口
```

## WebSocket 用法

前端通过原生 WebSocket 与后端实时通信：

```typescript
// 连接
const ws = new WebSocket('ws://localhost:8002/ws');

// 加入房间
ws.send(JSON.stringify({
  type: 'join',
  data: { room_id: 'xxx', user_id: 'xxx', username: 'xxx' }
}));

// 发送操作
ws.send(JSON.stringify({
  type: 'operation',
  data: { operation_type: 'add_poi', poi_id: 'xxx' },
  timestamp: new Date().toISOString()
}));

// 心跳（每 30 秒）
setInterval(() => {
  ws.send(JSON.stringify({ type: 'ping', data: {} }));
}, 30000);
```

消息类型：`join` | `leave` | `operation` | `cursor` | `sync` | `ping` | `pong`

## 语音输入兼容性

语音输入使用 Web Speech API，兼容性如下：

| 浏览器 | 支持 |
|--------|------|
| Chrome | ✅ 完全支持 |
| Edge | ✅ 完全支持 |
| Safari | ⚠️ 部分支持 |
| Firefox | ❌ 不支持 |

不支持的浏览器会自动隐藏语音输入按钮。

## Nginx 配置示例

```nginx
server {
    listen 80;
    server_name travel.example.com;

    root /var/www/travel-planner-frontend/dist;
    index index.html;

    # SPA 路由回退
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 代理到后端
    location /api/ {
        proxy_pass http://localhost:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket 代理
    location /ws {
        proxy_pass http://localhost:8002;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # 静态资源缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

## 核心功能

### 1. 地图展示
- 高德 JS API 2.0 动态加载
- 标记点：绿起点 / 蓝途经 / 红终点
- 路线按路况分段着色（绿/黄/红/深红）
- 实时路况图层叠加
- 路线动画效果
- 自适应视野

### 2. 天气展示
- 每日顶部显示天气图标、温度、降水概率、AQI
- 恶劣天气红底闪烁警告
- 点击展开逐小时预报

### 3. 时间轴
- 按天折叠展示
- 节点显示序号/名称/时间/停留/路况/天气提示
- @dnd-kit 拖拽重排（同天内 + 跨天）
- 点击节点地图居中

### 4. 多人协作
- 右侧折叠面板
- 在线成员头像（绿边标识）
- 操作日志实时显示
- 邀请链接/二维码
- WebSocket 实时同步

### 5. 旅行日记
- 自动生成封面/每日篇章/地图足迹/统计/成就徽章
- 用户添加照片/感悟/语音/高光标记
- 导出：长图/PDF/分享链接

## 性能优化

- polyline > 1000 点自动简化
- React.memo 优化组件渲染
- 图片懒加载
- WebSocket 心跳 30 秒

## 错误处理

- 网络错误：Ant Design message 提示
- 后端错误：显示错误详情
- 地图加载失败：显示错误信息
- WebSocket 断开：自动重连（最多 3 次）

## License

MIT
