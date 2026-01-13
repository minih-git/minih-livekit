"""
CLI 入口模块
提供 Agent 命令行启动功能，同时启动 Token HTTP 服务器
"""

import asyncio
import logging
import os
import signal
import sys
import socket
import threading
import uuid

# 将 src 目录添加到 sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, "src")
sys.path.insert(0, src_dir)

from livekit.agents import cli, WorkerOptions, JobProcess
from dotenv import load_dotenv

from core.agent_impl import entrypoint
from services.token_server import TokenServer
from services.sip_setup import setup_sip_trunk

# 加载 .env 文件
load_dotenv()

# ========== 日志配置 ==========
# 1. 彻底清除可能已存在的配置（防止多次运行导致重复）
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# 2. 统一配置 Root Logger（设高级别，屏蔽第三方库杂音）
logging.basicConfig(
    level=logging.INFO,  # 默认改为 INFO，不要用 WARNING
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# 3. 创建统一的日志 Handler（所有业务模块共用）
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

# 4. 配置业务主 logger（cli 模块）
logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)
logger.propagate = False  # 不向 root 传播，防止重复
if not logger.handlers:
    logger.addHandler(_console_handler)

# 5. 配置业务模块的 logger (services, core)
#    防止 propagate 到 root 导致与 LiveKit 或 Root handler 重复
for logger_name in ["services", "core"]:
    _mod_logger = logging.getLogger(logger_name)
    _mod_logger.setLevel(logging.INFO)
    _mod_logger.propagate = False  # 关键：不向 root 传播
    if not _mod_logger.handlers:
        _mod_logger.addHandler(_console_handler)

# 6. 屏蔽第三方库的冗余日志
logging.getLogger("livekit").setLevel(logging.INFO)
logging.getLogger("livekit.agents").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.WARNING)

logger = logging.getLogger("agent")


def check_environment():
    """检查必要的环境变量"""
    required_vars = [
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
    ]

    missing = [var for var in required_vars if not os.environ.get(var)]
    if missing:
        logger.warning(f"⚠️  缺少环境变量: {', '.join(missing)}")
        logger.info("请设置以下环境变量:")
        logger.info("  export LIVEKIT_URL=ws://localhost:7880")
        logger.info("  export LIVEKIT_API_KEY=devkey")
        logger.info(
            "  export LIVEKIT_API_SECRET=devsecret_minih_livekit_2026_secure_key"
        )
        logger.info("  export DEEPSEEK_API_KEY=your_api_key")
        logger.info("  export LLM_BASE_URL=https://api.deepseek.com")
        logger.info("  export LLM_MODEL=deepseek-chat")
        logger.info("  export VOLCENGINE_APP_ID=your_app_id")
        logger.info("  export VOLCENGINE_ACCESS_TOKEN=your_token")


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用 (防止多进程启动时端口冲突)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def run_token_server_safely():
    """安全地启动 Token Server，如果端口占用则跳过"""
    token_port = int(os.environ.get("TOKEN_SERVER_PORT", "8080"))

    if is_port_in_use(token_port):
        logger.warning(
            f"⚠️  端口 {token_port} 已被占用，可能是父进程已启动 Server。跳过启动。"
        )
        return

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server = TokenServer(port=token_port)
        try:
            loop.run_until_complete(server.start())
            logger.info(f"✅ Token 服务器后台启动成功: http://localhost:{token_port}")
            loop.run_forever()
        except Exception as e:
            logger.error(f"❌ Token 服务器启动失败: {e}")
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def prewarm(proc: JobProcess):
    """预热回调"""
    proc.userdata["started"] = True
    logging.info(f"🔥 Worker Process Prewarmed: {proc.pid}")


def main():
    check_environment()

    # 1. 生成唯一的 Agent Name (每次启动重置)
    # 这样可以避免多次重启导致的 Worker ID 冲突，或者让 Token Server 总是指向最新的 Worker
    base_name = os.environ.get("AGENT_NAME", "minih-dev-worker")
    # 添加 6 位随机后缀
    suffix = uuid.uuid4().hex[:6]
    agent_name = f"{base_name}-{suffix}"

    # 关键：更新环境变量，以便 Token Server (在后台线程运行) 也能获取到这个新的 Name
    os.environ["AGENT_NAME"] = agent_name

    # Dev 模式下的后台服务
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        logger.info("🚀 正在初始化所有服务...")

        # 安全启动 Token Server (带端口检测)
        run_token_server_safely()

        # 尝试配置 SIP (不阻塞主流程，失败仅警告)
        try:
            # 这里简单调用即可，不要让它 crash 整个程序
            # 最好是把 SIP setup 变成非阻塞的，或者放在 Server 线程里做
            logger.info("正在配置 SIP Trunk (后台)...")
        except Exception as e:
            logger.warning(f"SIP Setup Error: {e}")

    # 3. 启动 LiveKit Agent
    logger.info(f"🔧 Agent Name: {agent_name} | 正在等待任务...")

    # 4. 【最后一步调试】
    # 此时，请确保你的 core/agent_impl.py 中的 entrypoint 函数
    # 第一行有一句 print("DEBUG: Entrypoint entered!")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=agent_name,
        )
    )


if __name__ == "__main__":
    main()
