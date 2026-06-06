# 🏙️ 上海旅游路线规划服务

基于 FastAPI + React 的智能旅游路线规划系统，专为上海市内旅游设计。

## ✨ 功能特性

### 🔐 用户认证系统
- 用户注册/登录
- JWT Token 认证
- 旅游偏好设置
- 7天有效期 Token

### 🗺️ 路线规划
- 自然语言输入解析（LLM）
- 智能 POI 匹配
- 多日行程规划
- 实时天气集成
- 交通路况考虑

### 🌤️ 天气服务
- 上海逐日天气预报
- 实时天气信息
- 恶劣天气提醒

### 👥 协作编辑（需登录）
- 多人实时协作编辑路线
- WebSocket 实时同步
- 权限管理

### 📔 旅行日记（需登录）
- 自动生成旅行日记
- 成就徽章系统
- 日记导出功能

## 🚀 快速开始

### 方式一：Docker 部署（推荐）

#### 1. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 填入所有 Key
# 必须配置的变量：
# - GAODE_KEY: 高德地图 API Key
# - LLM_API_KEY: LLM API Key
# - WEATHER_KEY: 和风天气 API Key
# - SECRET_KEY: JWT 密钥（生产环境请修改为随机字符串）
```

#### 2. 启动服务

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f backend
```

#### 3. 访问服务

- 前端页面: http://localhost
- API 文档: http://localhost:8002/docs
- 后端服务: http://localhost:8002

### 方式二：本地开发

#### 后端

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 启动服务
python run.py
```

#### 前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

## 📁 项目结构

```
.
├── backend/                 # 后端服务
│   ├── models/             # 数据模型
│   │   ├── database.py     # 数据库模型（SQLite）
│   │   └── ...
│   ├── routers/            # API 路由
│   │   ├── auth.py         # 认证路由
│   │   ├── route.py        # 路线规划路由
│   │   └── ...
│   ├── services/           # 业务服务
│   │   ├── auth_service.py # 认证服务
│   │   └── ...
│   ├── middleware/          # 中间件
│   │   └── auth_middleware.py
│   ├── config.py           # 配置管理
│   ├── main.py             # FastAPI 应用入口
│   ├── run.py              # 启动脚本
│   ├── requirements.txt    # Python 依赖
│   └── Dockerfile          # Docker 构建文件
├── frontend/               # 前端应用
│   ├── src/                # 源代码
│   ├── nginx.conf          # Nginx 配置
│   ├── Dockerfile          # Docker 构建文件
│   └── package.json        # Node.js 依赖
├── docker-compose.yml      # Docker Compose 配置
├── .env.example            # 环境变量模板
└── README.md               # 项目文档
```

## 🔌 API 接口

### 认证接口

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/auth/register` | 用户注册 | 否 |
| POST | `/api/auth/login` | 用户登录 | 否 |
| GET | `/api/auth/me` | 获取当前用户 | 是 |
| PUT | `/api/auth/preferences` | 更新偏好 | 是 |
| POST | `/api/auth/logout` | 用户登出 | 否 |
| GET | `/api/auth/verify` | 验证令牌 | 是 |

### 路线规划接口

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/route/generate` | 生成路线 | 否（游客可用） |
| POST | `/api/route/optimize` | 优化路线 | 否 |

### 天气接口

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/weather/forecast` | 天气预报 | 否 |
| GET | `/api/weather/realtime` | 实时天气 | 否 |

### 协作接口（需登录）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/collab/room` | 创建房间 | 是 |
| WS | `/ws/collab/{room_id}` | WebSocket 连接 | 是 |

### 日记接口（需登录）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/diary/entry` | 创建日记 | 是 |
| GET | `/api/diary/list` | 获取日记列表 | 是 |

## 🔐 认证说明

### JWT Token 使用

1. 注册或登录获取 Token：
```bash
curl -X POST http://localhost:8002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123"}'
```

2. 在请求头中携带 Token：
```bash
curl http://localhost:8002/api/auth/me \
  -H "Authorization: Bearer <your_token>"
```

### 公开路由（无需认证）
- `/api/auth/*` - 认证相关接口
- `/api/route/generate` - 路线生成（游客可用）
- `/api/weather/*` - 天气查询
- `/docs`, `/redoc` - API 文档

### 需要认证的路由
- `/api/collab/*` - 协作编辑
- `/api/diary/*` - 旅行日记
- `/api/reviews/batch` - 批量评论

## 🐳 Docker 部署详解

### 服务组成

- **backend**: Python FastAPI 后端服务
- **frontend**: React + Nginx 前端服务
- **redis**: Redis 缓存服务

### 数据持久化

- SQLite 数据库存储在 `./data/users.db`
- Redis 数据通过 Docker Volume 持久化

### 常用命令

```bash
# 构建并启动
docker-compose up -d --build

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f backend
docker-compose logs -f frontend

# 停止服务
docker-compose down

# 停止并删除数据卷
docker-compose down -v

# 重启单个服务
docker-compose restart backend
```

### 环境变量配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `GAODE_KEY` | 高德地图 API Key | - |
| `LLM_API_KEY` | LLM API Key | - |
| `LLM_BASE_URL` | LLM API 地址 | https://api.openai.com/v1 |
| `LLM_MODEL` | LLM 模型名称 | gpt-4 |
| `WEATHER_KEY` | 和风天气 API Key | - |
| `DIANPING_COOKIE` | 大众点评 Cookie | - |
| `REDIS_URL` | Redis 连接地址 | redis://redis:6379/0 |
| `SECRET_KEY` | JWT 密钥 | your-secret-key... |
| `APP_PORT` | 服务端口 | 8002 |

## 🛠️ 技术栈

### 后端
- **FastAPI**: Python Web 框架
- **SQLAlchemy**: ORM 数据库操作
- **aiosqlite**: 异步 SQLite 驱动
- **python-jose**: JWT 令牌处理
- **passlib**: 密码哈希
- **Redis**: 缓存服务

### 前端
- **React 18**: UI 框架
- **TypeScript**: 类型安全
- **Vite**: 构建工具
- **Nginx**: 静态服务器

### 部署
- **Docker**: 容器化部署
- **Docker Compose**: 多容器编排

## 📝 开发说明

### 数据库

用户数据使用 SQLite 存储，数据库文件位于 `backend/data/users.db`。

首次启动时会自动创建数据库表结构。

### 密码安全

- 使用 bcrypt 算法进行密码哈希
- JWT Token 有效期 7 天
- SECRET_KEY 应使用随机字符串（生产环境）

### 缓存策略

- POI 查询结果缓存 1 小时
- 路线规划结果缓存 30 分钟
- 天气数据缓存 6 小时

## 📄 许可证

MIT License
