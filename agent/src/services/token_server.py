"""
Token HTTP 服务器模块
提供 LiveKit Token 生成 API 接口 + 对话历史查询 API
"""

import json
import logging
import os
from aiohttp import web
from livekit import api

from services.database import ChatDatabase

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_PORT = 8080


class TokenServer:
    """Token HTTP 服务器，为客户端提供 LiveKit Token 和历史查询"""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        port: int = DEFAULT_PORT,
    ):
        """
        初始化 Token 服务器

        参数:
            api_key: LiveKit API Key，默认从环境变量 LIVEKIT_API_KEY 获取
            api_secret: LiveKit API Secret，默认从环境变量 LIVEKIT_API_SECRET 获取
            port: HTTP 服务端口，默认 8080
        """
        self.api_key = api_key or os.environ.get("LIVEKIT_API_KEY", "devkey")
        self.api_secret = api_secret or os.environ.get(
            "LIVEKIT_API_SECRET", "devsecret_minih_livekit_2026_secure_key"
        )
        self.port = port
        self.db = ChatDatabase()  # 对话历史数据库
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None

    def _cors_headers(self) -> dict:
        """返回 CORS 响应头"""
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }

    async def _handle_token(self, request: web.Request) -> web.Response:
        """
        处理 Token 生成请求

        请求体:
            {
                "roomName": "room-01",
                "participantName": "user-01"
            }

        返回:
            {
                "token": "eyJhbGciOiJIUz..."
            }
        """
        headers = self._cors_headers()

        # 处理 OPTIONS 预检请求
        if request.method == "OPTIONS":
            return web.Response(status=204, headers=headers)

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": "Invalid JSON"}, status=400, headers=headers
            )

        room_name = data.get("roomName")
        participant_name = data.get("participantName")

        if not room_name or not participant_name:
            return web.json_response(
                {"error": "Missing roomName or participantName"},
                status=400,
                headers=headers,
            )

        # 获取 Agent 名称（与 cli.py 中的 agent_name 保持一致）
        agent_name = os.environ.get("AGENT_NAME", "minih-dev-worker")

        # 生成 Token，并配置显式 Agent 调度
        token = (
            api.AccessToken(self.api_key, self.api_secret)
            .with_identity(participant_name)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                )
            )
            .with_room_config(
                api.RoomConfiguration(
                    agents=[
                        api.RoomAgentDispatch(agent_name=agent_name),
                    ],
                )
            )
            .to_jwt()
        )

        logger.info(
            f"生成 Token: room={room_name}, participant={participant_name}, agent={agent_name}"
        )

        return web.json_response({"token": token}, headers=headers)

    async def _handle_history(self, request: web.Request) -> web.Response:
        """
        获取会话历史列表

        GET /api/history?limit=50

        返回:
            {
                "sessions": [
                    {"id": "...", "room_name": "...", "started_at": "...", "message_count": 5}
                ]
            }
        """
        headers = self._cors_headers()

        if request.method == "OPTIONS":
            return web.Response(status=204, headers=headers)

        limit = int(request.query.get("limit", 50))
        sessions = self.db.get_sessions(limit=limit)

        return web.json_response({"sessions": sessions}, headers=headers)

    async def _handle_session(self, request: web.Request) -> web.Response:
        """
        获取单个会话详情（含消息）

        GET /api/history/<session_id>

        返回:
            {
                "session": {...},
                "messages": [...]
            }
        """
        headers = self._cors_headers()

        if request.method == "OPTIONS":
            return web.Response(status=204, headers=headers)

        session_id = request.match_info.get("session_id")
        if not session_id:
            return web.json_response(
                {"error": "Missing session_id"}, status=400, headers=headers
            )

        session = self.db.get_session(session_id)
        if not session:
            return web.json_response(
                {"error": "Session not found"}, status=404, headers=headers
            )

        messages = self.db.get_session_messages(session_id)

        return web.json_response(
            {"session": session, "messages": messages}, headers=headers
        )

    async def start(self):
        """启动 HTTP 服务器"""
        self._app = web.Application()
        self._app.router.add_route("*", "/api/token", self._handle_token)
        self._app.router.add_route("*", "/api/history", self._handle_history)
        self._app.router.add_route("*", "/api/history/{session_id}", self._handle_session)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()

        logger.info(f"🚀 Token Server 启动: http://localhost:{self.port}/api/token")

    async def stop(self):
        """停止 HTTP 服务器"""
        if self._runner:
            await self._runner.cleanup()
            logger.info("Token Server 已停止")


async def start_token_server(port: int = DEFAULT_PORT) -> TokenServer:
    """
    启动 Token 服务器的便捷函数

    参数:
        port: HTTP 服务端口

    返回:
        TokenServer 实例
    """
    server = TokenServer(port=port)
    await server.start()
    return server
