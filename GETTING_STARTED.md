# 快速启动指南

## 前置条件

- Node.js 18+
- Python 3.10+
- Docker & Docker Compose（可选）

## 开发环境启动

### 1. 启动后端

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 启动后端服务
python run.py
```

后端将在 http://localhost:8002 启动

### 2. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将在 http://localhost:5173 启动

### 3. 访问应用

- 前端：http://localhost:5173
- 后端 API：http://localhost:8002
- API 文档：http://localhost:8002/docs

## Docker 部署

### 使用 Docker Compose

```bash
# 构建并启动所有服务
docker-compose up --build

# 后台运行
docker-compose up -d --build

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 访问应用

- 前端：http://localhost
- 后端 API：http://localhost:8002
- API 文档：http://localhost:8002/docs

## 测试认证功能

### 使用测试脚本

```bash
# 确保后端正在运行
python test_auth.py
```

### 手动测试

1. 访问 http://localhost:5173/register
2. 填写注册表单：
   - 用户名：testuser
   - 邮箱：test@example.com
   - 密码：password123
3. 选择旅行偏好
4. 完成注册后自动登录

## 主要功能

### 登录页面 (`/login`)
- 邮箱/密码登录
- 表单验证
- 记住我功能

### 注册页面 (`/register`)
- 三步注册流程
- 密码强度检测
- 旅行偏好选择

### 用户菜单
- 未登录：显示登录/注册按钮
- 已登录：显示用户信息和下拉菜单

### 路由保护
- `/diary/:id` 需要登录
- 未登录自动跳转到登录页

## 项目结构

```
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── LoginPage/        # 登录页面
│   │   │   ├── RegisterPage/     # 注册页面
│   │   │   └── PlannerPage/      # 主页面（已添加用户菜单）
│   │   ├── components/
│   │   │   ├── AuthGuard/        # 路由守卫
│   │   │   └── UserMenu/         # 用户菜单
│   │   ├── store/
│   │   │   └── userStore.ts      # 用户状态管理
│   │   ├── api/
│   │   │   ├── auth.ts           # 认证 API
│   │   │   └── client.ts         # Axios 客户端（已添加拦截器）
│   │   └── App.tsx               # 路由配置（已更新）
│   └── .env.production           # 生产环境配置
│
├── backend/
│   ├── routers/
│   │   └── auth.py               # 认证路由
│   ├── middleware/
│   │   └── auth_middleware.py    # 认证中间件
│   └── services/
│       └── auth_service.py       # 认证服务
│
├── docker-compose.yml            # Docker 编排
├── requirements.txt              # Python 依赖（已更新）
└── test_auth.py                  # 认证测试脚本
```

## 常见问题和解决方案

### 1. 前端无法连接后端

检查 `frontend/.env` 中的 `VITE_API_BASE_URL` 是否正确：
- 开发环境：`http://localhost:8002`
- Docker 环境：`/api`

### 2. CORS 错误

确保后端 `main.py` 中的 CORS 配置正确。

### 3. Token 过期

Token 有效期为 30 天。过期后需要重新登录。

### 4. 密码要求

- 最少 6 个字符
- 建议使用大小写字母、数字和特殊字符组合

## API 接口列表

| 方法 | 路径 | 描述 | 需要认证 |
|------|------|------|----------|
| POST | /api/auth/register | 用户注册 | 否 |
| POST | /api/auth/login | 用户登录 | 否 |
| GET | /api/auth/me | 获取用户信息 | 是 |
| PUT | /api/auth/preferences | 更新偏好 | 是 |
| POST | /api/auth/logout | 用户登出 | 是 |
| POST | /api/auth/forgot-password | 忘记密码 | 否 |

## 环境变量

### 前端 (.env)
```
VITE_API_BASE_URL=http://localhost:8002
VITE_GAODE_JSAPI_KEY=your_gaode_key
VITE_GAODE_SECURITY_CONFIG=your_security_config
```

### 后端 (.env)
```
GAODE_KEY=your_gaode_key
LLM_API_KEY=your_llm_key
LLM_BASE_URL=your_llm_url
LLM_MODEL=your_model
SECRET_KEY=your_secret_key
```

## 下一步

1. 接入真实数据库（PostgreSQL/MongoDB）
2. 实现邮箱验证
3. 添加第三方登录
4. 完善用户个人资料页面
5. 添加密码重置功能

## 帮助和支持

如有问题，请查看：
- `IMPLEMENTATION_SUMMARY.md` - 完整实现文档
- `frontend/AUTH_README.md` - 前端认证功能文档
