FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（Playwright + curl 用于高德 API 降级请求 + CA 证书）
RUN apt-get update && apt-get install -y \
    curl ca-certificates \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装Playwright浏览器
RUN playwright install chromium

# 创建数据目录
RUN mkdir -p /app/data

COPY . .

EXPOSE 8000

CMD ["python", "run.py"]
