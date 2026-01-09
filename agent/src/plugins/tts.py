from __future__ import annotations
import asyncio
import uuid
import logging
import os
from dataclasses import dataclass, replace
from typing import AsyncGenerator

from livekit import rtc
from livekit.agents import (
    APIConnectOptions,
    tokenize,
    tts,
    utils,
)
from services.tts import VolcEngineTTSClient

import numpy as np
from services.recorder import AudioRecorder

logger = logging.getLogger(__name__)

TTS_SAMPLE_RATE = 24000
TTS_NUM_CHANNELS = 1


@dataclass
class _TTSOptions:
    voice: str
    sample_rate: int
    speed_ratio: float
    tokenizer: tokenize.SentenceTokenizer


class VolcengineTTS(tts.TTS):
    """
    火山引擎 TTS (LiveKit Adapter)
    使用 services.tts.VolcEngineTTSClient 进行语音合成
    支持音频采集录制
    """

    def __init__(
        self,
        recorder: AudioRecorder | None = None,
        *,
        voice: str = "zh_female_tianmeixiaoyuan_moon_bigtts",
        sample_rate: int = TTS_SAMPLE_RATE,
        speed_ratio: float = 1.0,
        app_id: str | None = None,
        access_token: str | None = None,
        cluster: str = "volcano_tts",
        tokenizer: tokenize.SentenceTokenizer | None = None,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=sample_rate,
            num_channels=TTS_NUM_CHANNELS,
        )
        self.recorder = recorder

        if tokenizer is None:
            tokenizer = tokenize.basic.SentenceTokenizer()

        self._opts = _TTSOptions(
            voice=voice,
            sample_rate=sample_rate,
            speed_ratio=speed_ratio,
            tokenizer=tokenizer,
        )

        # 初始化服务客户端
        self._client = VolcEngineTTSClient(
            app_id=app_id, access_token=access_token, cluster=cluster
        )

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions | None = None
    ) -> "ChunkedStream":
        return ChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
            client=self._client,
            recorder=self.recorder,
        )

    def stream(
        self, *, conn_options: APIConnectOptions | None = None
    ) -> "SynthesizeStream":
        return SynthesizeStream(
            tts=self,
            conn_options=conn_options,
            client=self._client,
            recorder=self.recorder,
        )


class ChunkedStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: VolcengineTTS,
        input_text: str,
        conn_options: APIConnectOptions | None = None,
        client: VolcEngineTTSClient,
        recorder: AudioRecorder | None = None,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: VolcengineTTS = tts
        self._opts = replace(tts._opts)
        self._client = client
        self._recorder = recorder

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        # 初始化为 PCM 模式
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=self._opts.sample_rate,
            num_channels=TTS_NUM_CHANNELS,
            mime_type="audio/pcm",
            stream=False,
        )

        try:
            async for audio_bytes in self._client.synthesize_stream(
                text=self._input_text,
                voice_type=self._opts.voice,
                sample_rate=self._opts.sample_rate,
                speed_ratio=self._opts.speed_ratio,
            ):
                if self._recorder:
                    self._write_audio(audio_bytes)
                output_emitter.push(audio_bytes)

        except Exception as e:
            logger.error(f"TTS ChunkedStream Failed: {e}")

    def _write_audio(self, data: bytes):
        target_sr = 16000
        if self._opts.sample_rate != target_sr:
            try:
                import soxr

                # 转换 bytes -> numpy
                audio_data = np.frombuffer(data, dtype=np.int16)
                # 重采样
                resampled = soxr.resample(audio_data, self._opts.sample_rate, target_sr)
                # 转换回 bytes
                resampled_bytes = resampled.astype(np.int16).tobytes()
                self._recorder.write_agent_frame(resampled_bytes)
            except ImportError:
                logger.warning(
                    "soxr not installed, skipping resampling (audio may be distorted)"
                )
                self._recorder.write_agent_frame(data)
            except Exception as e:
                logger.error(f"Resampling failed: {e}")
        else:
            self._recorder.write_agent_frame(data)


class SynthesizeStream(tts.SynthesizeStream):
    def __init__(
        self,
        *,
        tts: VolcengineTTS,
        conn_options: APIConnectOptions | None = None,
        client: VolcEngineTTSClient,
        recorder: AudioRecorder | None = None,
    ) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._tts: VolcengineTTS = tts
        self._opts = replace(tts._opts)
        self._client = client
        self.recorder = recorder
        self._segments_ch = utils.aio.Chan[tokenize.SentenceStream]()

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=self._opts.sample_rate,
            num_channels=TTS_NUM_CHANNELS,
            mime_type="audio/pcm",
            stream=True,
        )

        async def _tokenize_input() -> None:
            input_stream = None
            async for input_data in self._input_ch:
                if isinstance(input_data, str):
                    if input_stream is None:
                        input_stream = self._opts.tokenizer.stream()
                        self._segments_ch.send_nowait(input_stream)
                    input_stream.push_text(input_data)
                elif isinstance(input_data, self._FlushSentinel):
                    if input_stream:
                        input_stream.end_input()
                    input_stream = None
            self._segments_ch.close()

        async def _run_segments() -> None:
            async for sentence_stream in self._segments_ch:
                full_sentence = ""
                async for text_part in sentence_stream:
                    full_sentence += text_part.token

                if full_sentence.strip():
                    output_emitter.start_segment(segment_id=str(uuid.uuid4()))

                    try:
                        async for audio_bytes in self._client.synthesize_stream(
                            text=full_sentence,
                            voice_type=self._opts.voice,
                            sample_rate=self._opts.sample_rate,
                            speed_ratio=self._opts.speed_ratio,
                        ):
                            if self.recorder:
                                self._write_audio(audio_bytes)
                            output_emitter.push(audio_bytes)
                    except Exception as e:
                        logger.error(f"TTS Segment Failed: {e}")

                    output_emitter.end_segment()

        tasks = [
            asyncio.create_task(_tokenize_input()),
            asyncio.create_task(_run_segments()),
        ]

        try:
            await asyncio.gather(*tasks)
        finally:
            await utils.aio.cancel_and_wait(*tasks)

    def _write_audio(self, data: bytes):
        target_sr = 16000
        if self._opts.sample_rate != target_sr:
            try:
                import soxr

                # 转换 bytes -> numpy
                audio_data = np.frombuffer(data, dtype=np.int16)
                # 重采样
                resampled = soxr.resample(audio_data, self._opts.sample_rate, target_sr)
                # 转换回 bytes
                resampled_bytes = resampled.astype(np.int16).tobytes()
                self.recorder.write_agent_frame(resampled_bytes)
            except ImportError:
                logger.warning(
                    "soxr not installed, skipping resampling (audio may be distorted)"
                )
                self.recorder.write_agent_frame(data)
            except Exception as e:
                logger.error(f"Resampling failed: {e}")
        else:
            self.recorder.write_agent_frame(data)
