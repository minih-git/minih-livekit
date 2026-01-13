# ============================================
# Stage 1: Builder - 安装依赖和下载模型
# ============================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# 安装 uv 包管理器
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# uv 优化设置
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

# 复制依赖定义文件
COPY pyproject.toml uv.lock ./

# 安装依赖（不包含 dev 依赖）
RUN uv sync --no-dev --frozen

# ============================================
# Stage 2: Model Downloader - 下载 ASR 模型
# ============================================
FROM debian:bookworm-slim AS model-downloader

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /models

# 下载 Sherpa-onnx Paraformer 流式双语模型
# 模型来源: https://huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en
ARG MODEL_REPO="https://huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en/resolve/main"

RUN curl -L -o tokens.txt "${MODEL_REPO}/tokens.txt" && \
    curl -L -o encoder.onnx "${MODEL_REPO}/encoder.onnx" && \
    curl -L -o decoder.onnx "${MODEL_REPO}/decoder.onnx" && \
    curl -L -o joiner.onnx "${MODEL_REPO}/joiner.onnx"

# ============================================
# Stage 3: Runtime - 最小化运行时镜像
# ============================================
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Python 运行时优化
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    # 禁用 pip 版本检查
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # 虚拟环境路径
    PATH="/app/.venv/bin:$PATH"

# 从 builder 复制虚拟环境
COPY --from=builder /app/.venv /app/.venv

# 从 model-downloader 复制模型文件
COPY --from=model-downloader /models /app/src/models

# 复制应用代码
COPY . .

# 创建所有需要的数据目录
# - /app/data: SQLite 数据库存储 (database.py)
# - /app/recordings: 通话录音存储 (recorder.py)
# - /tmp/asr_debug: ASR 调试录音 (asr.py)
RUN mkdir -p /app/data /app/recordings /tmp/asr_debug

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# 暴露端口
EXPOSE 8080

# 启动命令
CMD ["python", "main.py", "dev"]
