# 使用官方 Python 3.12 slim 镜像作为基础镜像
FROM python:3.12-slim-bookworm

# 设置工作目录
WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 设置环境变量
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV DEBIAN_FRONTEND=noninteractive

# 复制依赖定义文件
COPY pyproject.toml uv.lock ./

# 安装依赖
RUN uv sync --frozen --no-install-project --no-dev

# 复制项目代码
COPY . .

# 将 .venv 添加到 PATH
ENV PATH="/app/.venv/bin:$PATH"

# 暴露端口
EXPOSE 8080

# 启动命令
CMD ["python", "main.py", "start"]
