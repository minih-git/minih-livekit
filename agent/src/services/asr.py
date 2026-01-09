"""
本地 ASR 模块 - 使用 Sherpa-onnx 进行实时语音识别 (修复版)
改进点：
    1. VAD 预读缓冲 (Lookback Buffer) - 修复开头丢字问题
    2. 声道提取优化 - 修复双声道混合导致的音量衰减
    3. 逻辑顺序调整 - 先重采样再处理，保证 Buffer 数据一致性
"""

import logging
import numpy as np
import sherpa_onnx
import soxr
import time
import wave
import datetime
import collections
import os
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ASRResult:
    """ASR 识别结果"""

    text: str
    is_final: bool


class LocalASR:
    """本地 ASR 封装，使用 Sherpa-onnx Paraformer 流式模型"""

    TARGET_SAMPLE_RATE = 16000  # sherpa-onnx 模型要求 16kHz

    # --- VAD 配置调优 ---
    VAD_START_THRESHOLD = 0.025  # 门限：稍微降低以捕捉弱音 (原 0.05)
    VAD_END_THRESHOLD = 0.015
    SILENCE_FRAMES_FOR_ENDPOINT = 25  # 约 1-1.5秒静音断句

    # 预读缓冲大小 (Lookback Buffer)
    # 假设每次处理 chunk 约为 20-40ms，25 个 chunk 大约能回溯 0.5~1.0 秒
    # 这决定了"说话前"能找回多少音频
    WINDOW_BUFFER_SIZE = 25

    def __init__(self, models_dir: Path | None = None, num_threads: int = 4):
        """
        初始化 ASR 识别器
        """
        if models_dir is None:
            # 假设当前文件在 services/asr.py，模型在项目根目录 models
            models_dir = Path(__file__).parent.parent / "models"

        # 检查模型文件是否存在 (兼容 int8 和 fp32)
        encoder_path = models_dir / "encoder.int8.onnx"
        if not encoder_path.exists():
            encoder_path = models_dir / "encoder.onnx"
            decoder_path = models_dir / "decoder.onnx"
        else:
            decoder_path = models_dir / "decoder.int8.onnx"

        if not encoder_path.exists():
            raise FileNotFoundError(f"ASR 模型未找到: {models_dir}")

        logger.info(f"加载 ASR 模型: {models_dir}")

        # sherpa-onnx 识别器
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=str(models_dir / "tokens.txt"),
            encoder=str(encoder_path),
            decoder=str(decoder_path),
            num_threads=num_threads,
            sample_rate=self.TARGET_SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            enable_endpoint_detection=False,  # 禁用内置 VAD，使用自定义逻辑
            debug=False,
        )

        self._stream = self.recognizer.create_stream()
        self._last_partial_text = ""

        # soxr 重采样器缓存
        self._resamplers: dict[int, soxr.ResampleStream] = {}

        # VAD 状态
        self._is_speaking = False  # 是否正在说话
        self._silence_frame_count = 0  # 连续静音帧计数
        self._max_rms = 0.0  # 当前语音段的最大 RMS

        # --- 新增：环形缓冲 (Lookback Buffer) ---
        # 用于存储"触发说话前"的一小段音频，防止开头被切掉
        self._window_buffer = collections.deque(maxlen=self.WINDOW_BUFFER_SIZE)

        # 调试录音配置
        self._audio_buffer = []  # 仅用于保存文件调试
        # 使用相对路径，避免硬编码
        self.debug_dir = Path("debug_records")
        self.debug_dir.mkdir(parents=True, exist_ok=True)

        logger.info("ASR 引擎初始化完成 (带 VAD 预读缓冲)")

    def reset(self):
        """重置识别流和缓冲区"""
        self._stream = self.recognizer.create_stream()
        self._last_partial_text = ""
        self._is_speaking = False
        self._silence_frame_count = 0
        self._max_rms = 0.0
        self._audio_buffer = []
        # 注意：reset时不清除 _window_buffer，保持环境音的连续性

    def _save_debug_audio(self):
        """保存当前缓冲区的音频到文件 (用于排查断音问题)"""
        if not self._audio_buffer:
            return

        try:
            # 拼接音频数据
            audio_data = np.concatenate(self._audio_buffer)
            # float32 [-1, 1] -> int16
            audio_int16 = (audio_data * 32767).clip(-32768, 32767).astype(np.int16)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = self.debug_dir / f"asr_{timestamp}.wav"

            with wave.open(str(filename), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.TARGET_SAMPLE_RATE)
                wf.writeframes(audio_int16.tobytes())

            logger.info(f"已保存调试录音: {filename}")
        except Exception as e:
            logger.error(f"保存调试录音失败: {e}")

    @staticmethod
    def _calculate_rms(audio_data: np.ndarray) -> float:
        """计算音频的 RMS 能量"""
        if len(audio_data) == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio_data**2)))

    def _get_resampler(self, source_rate: int) -> soxr.ResampleStream | None:
        """获取重采样器"""
        if source_rate == self.TARGET_SAMPLE_RATE:
            return None

        if source_rate not in self._resamplers:
            self._resamplers[source_rate] = soxr.ResampleStream(
                source_rate,
                self.TARGET_SAMPLE_RATE,
                num_channels=1,
                dtype=np.float32,
            )
            logger.info(f"创建重采样器: {source_rate}Hz -> {self.TARGET_SAMPLE_RATE}Hz")

        return self._resamplers[source_rate]

    def process_audio(
        self, audio_data: np.ndarray, sample_rate: int = 48000
    ) -> ASRResult | None:
        """
        核心处理逻辑 - 双阈值 VAD + 预读缓冲
        """
        start_t = time.perf_counter()

        # 1. 重采样
        resampler = self._get_resampler(sample_rate)
        if resampler is not None:
            audio_data = resampler.resample_chunk(audio_data)

        # 2. 计算 RMS
        rms = self._calculate_rms(audio_data)

        # --- 关键逻辑：双阈值判定 ---
        if not self._is_speaking:
            # 静音状态：必须冲过较高的 START 阈值才能激活
            is_voice_active = rms >= self.VAD_START_THRESHOLD
        else:
            # 说话状态：只要维持在较低的 END 阈值以上就算延续
            is_voice_active = rms >= self.VAD_END_THRESHOLD

        # 3. 维护滑动窗口 (静音时存数据，方便回头补救)
        if not self._is_speaking:
            self._window_buffer.append(audio_data)

            # (可选) 调试打印：帮你通过日志通过 RMS 到底该设多少
            # 如果觉得日志太吵，可以注释掉
            if rms > 0.01:
                logger.info(f"环境噪音 RMS: {rms:.4f}")

        # 4. VAD 状态切换
        if is_voice_active:
            # 刚开始检测到声音 (0 -> 1)
            if not self._is_speaking:
                logger.info(
                    f"🎙️ 触发语音 (RMS: {rms:.4f}) > 阈值 {self.VAD_START_THRESHOLD} "
                    f"- 回溯补全 {len(self._window_buffer)} 帧"
                )

                # 把缓冲区里的“开头”补进去 (救回弱音的关键！)
                for past_chunk in self._window_buffer:
                    self._audio_buffer.append(past_chunk)
                    self._stream.accept_waveform(self.TARGET_SAMPLE_RATE, past_chunk)

                self._window_buffer.clear()

            self._is_speaking = True
            self._silence_frame_count = 0
            if rms > self._max_rms:
                self._max_rms = rms

        # 5. 送入识别器
        if self._is_speaking:
            self._audio_buffer.append(audio_data)
            self._stream.accept_waveform(self.TARGET_SAMPLE_RATE, audio_data)

            while self.recognizer.is_ready(self._stream):
                self.recognizer.decode_stream(self._stream)

        # 6. 静音断句检测 (1 -> 0)
        if not is_voice_active and self._is_speaking:
            self._silence_frame_count += 1

            # 只有连续 N 帧低于 END_THRESHOLD 才切断
            if self._silence_frame_count >= self.SILENCE_FRAMES_FOR_ENDPOINT:
                text = self.recognizer.get_result(self._stream).strip()

                logger.info(
                    f"🛑 说话结束 (静音计数: {self._silence_frame_count}) | "
                    f"峰值 RMS: {self._max_rms:.4f}"
                )

                self._save_debug_audio()
                self.reset()

                if text:
                    logger.info(f"ASR 最终识别: {text}")
                    return ASRResult(text=text, is_final=True)
                return None

        # 7. 中间结果
        if is_voice_active and self._is_speaking:
            text = self.recognizer.get_result(self._stream).strip()
            if text and text != self._last_partial_text:
                self._last_partial_text = text
                return ASRResult(text=text, is_final=False)

        return None

    @staticmethod
    def audio_frame_to_float32(frame_data: bytes, num_channels: int = 1) -> np.ndarray:
        """
        [修复版] 安全转换音频格式 int16 -> float32
        修复了双声道平均导致音量减半的问题
        """
        # 确保字节流对齐
        if len(frame_data) % 2 != 0:
            frame_data = frame_data[:-1]

        audio_int16 = np.frombuffer(frame_data, dtype=np.int16)

        # 处理双声道
        if num_channels == 2:
            try:
                audio_reshaped = audio_int16.reshape(-1, 2)

                # --- 关键修复 ---
                # 之前使用 np.mean 会导致 (人声+静音)/2 = 音量减半
                # 现在只取左声道 (通常 Channel 0 是 User)
                audio_mono = audio_reshaped[:, 0]

                return audio_mono.astype(np.float32) / 32768.0
            except Exception as e:
                logger.warning(f"双声道提取失败: {e}，回退到原始混合")
                pass

        # 单声道或回退情况：归一化到 [-1, 1]
        return audio_int16.astype(np.float32) / 32768.0
