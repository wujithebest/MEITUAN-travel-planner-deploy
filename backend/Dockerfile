FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV APP_PORT=8000

# 安装系统依赖（curl + CA 证书 + OpenCV 等运行时库）
# 使用阿里云镜像加速（国内网络环境）
RUN sed -i 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y \
    curl ca-certificates \
    libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 libgl1 \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt

# 创建数据目录
RUN mkdir -p /app/data

COPY . .

EXPOSE 8000

CMD ["python", "run.py"]
