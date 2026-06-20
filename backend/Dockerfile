# 知识库后端 Dockerfile（生产多阶段构建）
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ---- 运行时镜像 ----
FROM python:3.11-slim

# 安全：非 root 用户
RUN useradd --create-home --shell /bin/bash --uid 1001 kbuser

WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制预编译的 wheel
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# 复制代码
COPY . .

# 数据目录权限
RUN mkdir -p /app/data && chown -R kbuser:kbuser /app
USER kbuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

EXPOSE 8000

# 启动（生产模式）
CMD ["python", "start_prod.py", "--workers", "3", "--host", "0.0.0.0", "--port", "8000"]