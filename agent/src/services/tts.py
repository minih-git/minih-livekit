"""
TTS 服务模块 - 火山引擎 TTS 客户端
负责与火山引擎 WebSocket API 进行交互，不含 LiveKit 逻辑
"""

import logging
import os
import json
import gzip
import uuid
import struct
import aiohttp
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class VolcEngineTTSClient:
    """
    火山引擎 TTS 客户端
    使用 WebSocket 二进制协议 (V1)
    """

    # V1 单向流式 WebSocket 端点
    WS_URL = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"

    # 协议常量
    PROTOCOL_VERSION = 0b0001
    HEADER_SIZE = 0b0001
    MESSAGE_TYPE_FULL_CLIENT = 0b0001
    MESSAGE_TYPE_AUDIO_ONLY = 0b1011
    MESSAGE_TYPE_ERROR = 0b1111
    MESSAGE_SERIALIZATION_JSON = 0b0001
    MESSAGE_COMPRESSION_GZIP = 0b0001

    def __init__(
        self,
        app_id: str | None = None,
        access_token: str | None = None,
        cluster: str = "volcano_tts",
    ):
        self.app_id = app_id or os.environ.get("VOLCENGINE_APP_ID")
        self.access_token = access_token or os.environ.get("VOLCENGINE_ACCESS_TOKEN")
        self.cluster = cluster

        if not self.app_id or not self.access_token:
            logger.warning(
                "VolcEngineTTSClient: Credentials not found (APP_ID or ACCESS_TOKEN)."
            )

    async def synthesize_stream(
        self,
        text: str,
        voice_type: str = "zh_female_tianmeixiaoyuan_moon_bigtts",
        sample_rate: int = 24000,
        speed_ratio: float = 1.0,
    ) -> AsyncGenerator[bytes, None]:
        """
        合成语音流

        Args:
            text: 待合成文本
            voice_type: 音色 ID
            sample_rate: 采样率 (默认 24000)
            speed_ratio: 语速 (默认 1.0)

        Yields:
            PCM 音频数据块 (bytes)
        """
        headers = {"Authorization": f"Bearer;{self.access_token}"}
        req_id = str(uuid.uuid4())

        logger.info(f"VolcTTS Client: Synth Text='{text[:20]}...' id={req_id}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(self.WS_URL, headers=headers) as ws:
                    # 发送合成请求
                    request_data = self._build_request(
                        req_id=req_id,
                        text=text,
                        voice_type=voice_type,
                        sample_rate=sample_rate,
                        speed_ratio=speed_ratio,
                    )
                    await ws.send_bytes(request_data)

                    # 接收响应流
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            msg_type, sequence, data = self._parse_response(msg.data)

                            if msg_type == self.MESSAGE_TYPE_AUDIO_ONLY:
                                if data:
                                    # 确保偶数长度
                                    if len(data) % 2 != 0:
                                        data = data[:-1]

                                    # 返回拷贝的 bytes
                                    yield bytes(data)

                                if sequence < 0:
                                    # 最后一包
                                    break

                            elif msg_type == self.MESSAGE_TYPE_ERROR:
                                err_msg = f"VolcEngine Error: {data}"
                                logger.error(err_msg)
                                raise RuntimeError(err_msg)

                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise RuntimeError("WebSocket connection closed with error")

        except Exception as e:
            logger.error(f"VolcTTS Client Failed: {e}")
            # 这里抛出异常，让上层决定如何处理（是重试还是静默失败）
            raise

    def _build_request(
        self,
        req_id: str,
        text: str,
        voice_type: str,
        sample_rate: int,
        speed_ratio: float,
    ) -> bytes:
        request_json = {
            "app": {
                "appid": self.app_id,
                "token": "access_token",  # 实际鉴权在 header
                "cluster": self.cluster,
            },
            "user": {"uid": "agent_user"},
            "audio": {
                "voice_type": voice_type,
                "encoding": "pcm",
                "speed_ratio": speed_ratio,
                "rate": sample_rate,
            },
            "request": {"reqid": req_id, "text": text, "operation": "submit"},
        }

        # 压缩 Payload
        payload_gzip = gzip.compress(json.dumps(request_json).encode("utf-8"))
        payload_size = len(payload_gzip)

        # 构建 Header (0x11101100 = Version(1)|HeaderSize(1) | FullClient(1)|Specific(0) | Json(1)|Gzip(1) | Reserved(0))
        # 0x11 = 0001 0001
        # 0x10 = 0001 0000
        # 0x11 = 0001 0001
        # 0x00
        header = bytearray([0x11, 0x10, 0x11, 0x00])

        # 这里的协议头构造逻辑：
        # Byte 0: Version (4) | Header Size (4) -> 0x0001 | 0x0001 -> 0x11
        # Byte 1: Message Type (4) | Flags (4) -> 0x0001 (Full Client) | 0x0000 -> 0x10
        # Byte 2: Serialization (4) | Compression (4) -> 0x0001 (JSON) | 0x0001 (Gzip) -> 0x11
        # Byte 3: Reserved (0x00)

        size_bytes = struct.pack(">I", payload_size)
        return header + size_bytes + payload_gzip

    def _parse_response(self, data: bytes) -> tuple[int, int, bytes]:
        """
        解析响应
        Returns: (message_type, sequence, payload_or_audio)
        """
        if len(data) < 4:
            return 0, 0, b""

        byte1 = data[1]
        msg_type = (byte1 >> 4) & 0x0F
        type_flags = byte1 & 0x0F

        if msg_type == self.MESSAGE_TYPE_AUDIO_ONLY:
            offset = 4
            sequence = 0

            # 检查是否有 sequence number (flags 0x01, 0x02, 0x03)
            # 0b0000 = no seq
            # 0b0001 = seq > 0
            # 0b0010 = last msg (seq < 0)
            # 0b0011 = last msg (seq < 0)

            if type_flags != 0:
                if len(data) >= offset + 4:
                    sequence = struct.unpack(">i", data[offset : offset + 4])[0]
                    offset += 4

            if len(data) >= offset + 4:
                payload_size = struct.unpack(">I", data[offset : offset + 4])[0]
                offset += 4
                if len(data) >= offset + payload_size:
                    return msg_type, sequence, data[offset : offset + payload_size]

        elif msg_type == self.MESSAGE_TYPE_ERROR:
            # 错误消息解析... 略作简化，假设错误消息结构类似
            pass

        return msg_type, 0, b""
