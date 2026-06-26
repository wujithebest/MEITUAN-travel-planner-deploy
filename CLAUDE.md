# BesTour — 上海本地生活路线规划

## 一键重建

```bash
docker compose up -d --build
```

后端健康检查：
```bash
curl http://localhost:8000/api/health
```

前端构建（非 Docker 模式下开发用）：
```bash
npm --prefix frontend run build
```

## 工作职责

### 每次修改后
- **仅改前端** → `npm --prefix frontend run build` + `docker compose up -d --build frontend`
- **仅改后端** → `docker compose up -d --build backend`
- **前后端都改** → `docker compose up -d --build backend frontend`
- 构建失败时自行排查语法/类型错误，修复后重新构建，不要跳过

### 推送
- **仅在用户明确要求时**才 push（用户说 push / 推送 / 推到 branch 等）
- push 前先 `git branch --show-current` 确认在 `codex/theme-recall-rerank`
- 只 `git add` 本次修改的文件，禁止 `git add .`
- 只用简洁英文 commit message

### push 失败时
- 自动提醒用户执行 `gh auth login` 完成 GitHub 认证
- 或建议设置代理：`git config --global https.proxy http://127.0.0.1:7890`
- 不要反复重试超过 2 次

## 必备前提

- Docker Desktop 已安装并运行
- 项目根目录 `.env` 文件存在（含 `GAODE_API_KEY`, `DEEPSEEK_API_KEY`, `BOCHA_API_KEY`, `SECRET_KEY`, `WEATHER_KEY`, `DIANPING_COOKIE`）
- `frontend/.env` 文件存在（含 `VITE_GAODE_JSAPI_KEY`）
- `backend/.env` 文件存在

> 迁移到新电脑时，`.env` 文件不会被 Git 跟踪，需要手动从旧电脑复制过来。

## 服务端口

| 服务 | 端口 |
|------|------|
| backend (FastAPI) | 8000 |
| frontend (React + Vite + Nginx) | 80 |
| mongodb | 27017 |
| redis | 6379 |

## 分支与推送

- 当前分支: `codex/theme-recall-rerank`
- **禁止** push 到 `master` / `main`
- **禁止** `git add .` — 精确添加修改文件
- **禁止** 覆盖 `backend/services/day_slots.py` 和 `backend/services/step3_planned.py` 中的预存改动
- **禁止** 输出 `.env` 中的真实 API Key

## 项目结构

```
backend/          — FastAPI 后端
  routers/        — API 路由
  services/       — 业务逻辑 (step1~step4 pipeline)
frontend/         — React + Vite 前端
  src/
    components/   — ChatPanel, MapContainer, ItinerarySidebar
    hooks/        — useChat, useItinerary
    pages/        — PlannerPage
    services/     — API 调用层
    store/        — Zustand 状态管理
```

## 常用验证

```bash
# Python 语法检查
python -m py_compile backend/routers/route.py backend/services/step3_micro.py backend/services/step1_intent.py backend/services/conversation_replan.py backend/services/pipeline_replan_service.py

# 前端构建检查
cd frontend && npm run build

# 推送（需代理或 VPN）
git push origin codex/theme-recall-rerank
```
