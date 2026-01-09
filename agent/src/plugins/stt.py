import asyncio
import logging
import json
import time
from typing import AsyncIterable

from livekit import rtc
from livekit.agents import stt
from livekit.agents.utils import AudioBuffer

from services.asr import LocalASR, ASRResult
from services.database import ChatDatabase
from core.session import SessionState

logger = logging.getLogger(__name__)


class LocalSTT(stt.STT):
    """
    本地 ASR 适配器，使用 Sherpa-onnx
    """

    def __init__(
        self,
        *,
        language: str = "zh",
        db: ChatDatabase = None,
        state: SessionState = None,
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=True, interim_results=True)
        )
        self._asr = LocalASR()
        self.db = db
        self.state = state

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: str | None = None,
        conn_options: dict | None = None,
    ) -> stt.SpeechEvent:
        pass

    def stream(
        self,
        *,
        language: str | None = None,
        conn_options: dict | None = None,
    ) -> stt.SpeechStream:
        return LocalSpeechStream(
            stt=self,
            conn_options=conn_options,
            asr=self._asr,
            db=self.db,
            state=self.state,
        )


class LocalSpeechStream(stt.SpeechStream):
    def __init__(
        self,
        stt: stt.STT,
        conn_options: dict | None,
        asr: LocalASR,
        db: ChatDatabase = None,
        state: SessionState = None,
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options)
        self._asr = asr
        self._db = db
        self._state = state
        self._asr.reset()

    async def _run(self) -> None:
        """
        主处理循环：从 self._input_ch 读取音频帧，处理后将事件发送到 self._event_ch
        """
        async for frame in self._input_ch:
            if isinstance(frame, self._FlushSentinel):
                # 暂时忽略 flush，或清理当前 buffer
                continue

            if frame is None:
                break

            try:
                # 1. 将 CPU 密集型操作移入线程池
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self._process_audio_sync, frame
                )

                if result and result.text and len(result.text.strip()) > 0:
                    event = stt.SpeechEvent(
                        type=(
                            stt.SpeechEventType.FINAL_TRANSCRIPT
                            if result.is_final
                            else stt.SpeechEventType.INTERIM_TRANSCRIPT
                        ),
                        alternatives=[
                            stt.SpeechData(
                                text=result.text, confidence=1.0, language="zh"
                            )
                        ],
                    )

                    self._event_ch.send_nowait(event)

                    # 2. 字幕/数据库记录 (Merge logic from InterceptedSpeechStream)
                    if self._state and self._state.session_id:
                        await self._handle_transcript(result.text, result.is_final)

            except Exception as e:
                logger.error(f"STT Processing Error: {e}", exc_info=True)

    async def _handle_transcript(self, text: str, is_final: bool):
        if is_final:
            logger.info(f"用户说: {text}")
            if self._db:
                self._db.add_message(self._state.session_id, "user", text)

        # 发送字幕到前端 (Data Channel)
        await self._send_transcript("user", text, is_final=is_final)

    async def _send_transcript(self, participant: str, text: str, is_final: bool):
        """发送字幕消息到 Data Channel"""
        if not self._state or not self._state.room:
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

    def _process_audio_sync(self, frame) -> ASRResult | None:
        """
        同步执行音频处理 (CPU 密集型)，供线程池调用
        """
        try:
            # 1. 转换 frame 到 float32 numpy (正确处理声道)
            # LocalASR.audio_frame_to_float32 内部使用 np.frombuffer
            audio_data = self._asr.audio_frame_to_float32(
                frame.data, num_channels=frame.num_channels
            )

            # 2. ASR 识别
            return self._asr.process_audio(audio_data, sample_rate=frame.sample_rate)
        except Exception as e:
            logger.error(f"Audio Sync Processing Error: {e}", exc_info=True)
            return None
