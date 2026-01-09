import logging
import os
import json
import time
from typing import AsyncIterable

from livekit.agents import llm
from services.llm import LLMClient
from services.database import ChatDatabase
from core.session import SessionState

logger = logging.getLogger(__name__)


class FastGPTLLM(llm.LLM):
    """
    FastGPT LLM 适配器，集成了字幕发送和数据库记录功能
    """

    def __init__(
        self,
        db: ChatDatabase,
        state: SessionState,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__()
        self._client = LLMClient(api_key=api_key, base_url=base_url, model=model)
        self.db = db
        self.state = state

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.FunctionTool] | None = None,
        conn_options: dict | None = None,
        **kwargs,
    ) -> "llm.LLMStream":
        """同步方法，返回 LLMStream"""
        return FastGPTLLMStream(
            llm=self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            client=self._client,
            db=self.db,
            state=self.state,
        )


class FastGPTLLMStream(llm.LLMStream):
    def __init__(
        self,
        llm: llm.LLM,
        chat_ctx: llm.ChatContext,
        tools: list,
        conn_options: dict | None,
        client: LLMClient,
        db: ChatDatabase,
        state: SessionState,
    ) -> None:
        super().__init__(
            llm=llm, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options
        )
        self._client = client
        self._chat_ctx = chat_ctx
        self._db = db
        self._state = state
        self._collected_text = ""
        self._start_t = time.perf_counter()  # 记录开始时间以统计耗时

    async def _run(self) -> None:
        """主处理循环：调用 LLM 并将结果发送到 _event_ch"""
        # 使用 to_provider_format 转换为 OpenAI 格式
        messages, _ = self._chat_ctx.to_provider_format("openai")

        # 获取 roomId 作为 chatId
        chat_id = self._state.room.name if self._state.room else "unknown_room"

        try:
            response = await self._client.client.chat.completions.create(
                model=self._client.model,
                messages=messages,
                stream=True,
                max_tokens=256,
                temperature=0.1,  # 降低随机性，通常能微量提升响应速度和稳定性
                extra_body={
                    "chatId": chat_id,
                },
            )

            async for chunk in response:
                content = None
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content

                if content:
                    # 性能打点：首包延迟
                    if not hasattr(self, "_first_chunk_t"):
                        self._first_chunk_t = time.perf_counter()
                        llm_pre_dur = (self._first_chunk_t - self._start_t) * 1000
                        logger.info(f"⚡ LLM 首包延迟: {llm_pre_dur:.1f}ms")

                    self._collected_text += content

                    # 发送 Partial 字幕（流式更新）
                    await self._send_transcript(
                        "agent", self._collected_text, is_final=False
                    )

                    self._event_ch.send_nowait(
                        llm.ChatChunk(
                            id=chunk.id or "",
                            delta=llm.ChoiceDelta(content=content, role="assistant"),
                        )
                    )

            # Stream finished
            if self._state.session_id and self._collected_text:
                end_t = time.perf_counter()
                total_dur = (end_t - self._start_t) * 1000
                logger.info(
                    f"✅ LLM 完成响应: {total_dur:.1f}ms | 长度: {len(self._collected_text)} 字"
                )
                self._db.add_message(
                    self._state.session_id, "agent", self._collected_text
                )
                # 发送 Final 字幕
                await self._send_transcript(
                    "agent", self._collected_text, is_final=True
                )

        except Exception as e:
            logger.error(f"LLM Chat Error: {e}")
            raise e

    async def _send_transcript(self, participant: str, text: str, is_final: bool):
        """发送字幕消息到 Data Channel"""
        if not self._state.room:
            return
        try:
            message = json.dumps(
                {
                    "type": "transcript",
                    "participant": participant,
                    "text": text,
                    "is_final": is_final,
                    "timestamp": int(time.time() * 1000),
                }
            )
            await self._state.room.local_participant.publish_data(
                payload=message.encode("utf-8"),
                reliable=True,
            )
        except Exception as e:
            logger.warning(f"发送字幕失败: {e}")
