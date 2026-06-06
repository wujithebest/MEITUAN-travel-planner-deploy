# 用户认证功能说明

## 新增文件

### 页面组件
- `src/pages/LoginPage/index.tsx` - 登录页面
- `src/pages/LoginPage/LoginPage.module.css` - 登录页面样式
- `src/pages/RegisterPage/index.tsx` - 注册页面
- `src/pages/RegisterPage/RegisterPage.module.css` - 注册页面样式

### 通用组件
- `src/components/AuthGuard/index.tsx` - 路由守卫组件
- `src/components/UserMenu/index.tsx` - 用户菜单组件
- `src/components/UserMenu/UserMenu.module.css` - 用户菜单样式

### 状态管理
- `src/store/userStore.ts` - 用户状态管理（Zustand）

### API 接口
- `src/api/auth.ts` - 认证相关 API

## 功能特性

### 登录页面 (`/login`)
- 邮箱输入框（带实时验证）
- 密码输入框（可切换显示/隐藏）
- "记住我"复选框
- 登录按钮（带加载状态）
- 第三方登录占位（微信/QQ，灰色不可点击）
- 左侧品牌区域（上海地标插画）

### 注册页面 (`/register`)
- 三步注册流程：
  1. 基本信息（用户名/邮箱/密码）
  2. 选择旅行偏好（9个偏好标签，可多选）
  3. 注册成功页面
- 密码强度指示器（弱/中/强）
- 邮箱格式实时验证
- 用户名长度验证

### 用户菜单
- 未登录状态：显示"登录/注册"按钮
- 已登录状态：显示用户头像 + 用户名，下拉菜单包含：
  - 个人中心
  - 我的偏好
  - 我的行程
  - 退出登录

### 路由守卫 (`AuthGuard`)
- 检查 localStorage 中是否有 token
- 无 token 访问需登录页面时，重定向到 `/login`
- token 过期（401）时，清除 token 并重定向

## 旅行偏好选项

1. 历史文化 🏛️
2. 美食探店 🍜
3. 自然风光 🌳
4. 购物娱乐 🛍️
5. 艺术展览 🎨
6. 夜生活 🌙
7. 摄影打卡 📸
8. 亲子游玩 👨‍👩‍👧‍👦
9. 户外探险 🏔️

## API 接口

### POST /api/auth/register
用户注册
```json
{
  "username": "string",
  "email": "string",
  "password": "string",
  "preferences": ["history", "food"]
}
```

### POST /api/auth/login
用户登录
```json
{
  "email": "string",
  "password": "string"
}
```

### GET /api/auth/me
获取当前用户信息（需要认证）

### PUT /api/auth/preferences
更新用户偏好（需要认证）
```json
{
  "preferences": ["history", "food", "art"]
}
```

## 状态管理

使用 Zustand 进行状态管理，支持持久化存储：

```typescript
import { useUserStore } from '@/store/userStore';

// 在组件中使用
const { user, isLoggedIn, login, logout } = useUserStore();
```

## Docker 部署

### 环境变量
生产环境配置在 `.env.production`：
```
VITE_API_BASE_URL=/api
```

### Nginx 配置
API 请求通过 nginx 代理到后端：
```nginx
location /api/ {
    proxy_pass http://backend:8000;
}
```

## 样式特性

- 登录页背景：浅蓝色渐变
- 表单输入框聚焦时边框变主色 #1677ff
- 按钮：主色背景，hover 加深
- 移动端适配：左右布局变为上下布局
- 白色卡片，圆角 16px，阴影

## 后端依赖

确保后端安装了以下 Python 包：
```bash
pip install python-jose[cryptography] passlib[bcrypt] python-multipart
```

## 测试账号

由于使用内存数据库，每次重启服务后数据会丢失。
可以通过注册接口创建新账号进行测试。
