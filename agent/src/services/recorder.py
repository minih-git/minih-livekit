"""
音频录制模块 - 双声道 WAV 文件存储

功能说明：
- 左声道：用户音频
- 右声道：Agent (AI) 音频
- 采用 16kHz、16bit PCM 格式

同步策略：
    使用时间戳对齐，定时刷新缓冲区确保左右声道同步存储。
"""

import asyncio
import logging
import os
import struct
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("agent.recorder")

# 录音参数配置
SAMPLE_RATE = 16000
NUM_CHANNELS = 2  # 双声道
BYTES_PER_SAMPLE = 2  # 16bit
SAMPLES_PER_FRAME = 480  # 30ms @ 16kHz

# 静音帧（用于填充无数据的时段）
SILENCE_FRAME = bytes(SAMPLES_PER_FRAME * BYTES_PER_SAMPLE)


class AudioRecorder:
    """
    双声道音频录制器

    实现左右声道独立写入并自动对齐存储。
    """

    def __init__(self, output_dir: str = "recordings"):
        """
        初始化录音器

        Args:
            output_dir: 录音文件输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._wav_file: Optional[wave.Wave_write] = None
        self._file_path: Optional[Path] = None
        self._is_recording = False

        # 缓冲区：存储左右声道的帧数据
        self._user_buffer: bytearray = bytearray()
        self._agent_buffer: bytearray = bytearray()

        # 帧计数器
        self._user_frame_count = 0
        self._agent_frame_count = 0
        self._synced_frame_count = 0

        # 刷新任务
        self._flush_task: Optional[asyncio.Task] = None

    def start(self, session_id: Optional[str] = None) -> Path:
        """
        开始录音会话

        Args:
            session_id: 可选的会话 ID，用于生成文件名

        Returns:
            录音文件路径
        """
        if self._is_recording:
            logger.warning("录音已在进行中")
            return self._file_path

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{session_id or 'call'}_{timestamp}.wav"
        self._file_path = self.output_dir / filename

        # 创建 WAV 文件（先创建临时文件，最后写入正确头信息）
        self._wav_file = wave.open(str(self._file_path), "wb")
        self._wav_file.setnchannels(NUM_CHANNELS)
        self._wav_file.setsampwidth(BYTES_PER_SAMPLE)
        self._wav_file.setframerate(SAMPLE_RATE)

        self._is_recording = True
        self._user_buffer.clear()
        self._agent_buffer.clear()
        self._user_frame_count = 0
        self._agent_frame_count = 0
        self._synced_frame_count = 0

        # 启动定时刷新任务
        self._flush_task = asyncio.create_task(self._periodic_flush())

        logger.info(f"开始录音: {self._file_path}")
        return self._file_path

    async def stop(self) -> Optional[Path]:
        """
        停止录音并关闭文件

        Returns:
            生成的录音文件路径，如果没有录音则返回 None
        """
        if not self._is_recording:
            return None

        self._is_recording = False

        # 停止刷新任务
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # 最后一次刷新
        self._flush_buffers()

        # 关闭文件
        if self._wav_file:
            self._wav_file.close()
            self._wav_file = None

        file_path = self._file_path
        self._file_path = None

        logger.info(f"录音结束: {file_path}, 总帧数: {self._synced_frame_count}")
        return file_path

    def write_user_frame(self, pcm_data: bytes):
        """
        写入用户音频帧（左声道）

        Args:
            pcm_data: 16bit PCM 音频数据
        """
        if not self._is_recording:
            return

        self._user_buffer.extend(pcm_data)
        self._user_frame_count += len(pcm_data) // (
            SAMPLES_PER_FRAME * BYTES_PER_SAMPLE
        )

    def write_agent_frame(self, pcm_data: bytes):
        """
        写入 Agent 音频帧（右声道）

        Args:
            pcm_data: 16bit PCM 音频数据
        """
        if not self._is_recording:
            return

        self._agent_buffer.extend(pcm_data)
        self._agent_frame_count += len(pcm_data) // (
            SAMPLES_PER_FRAME * BYTES_PER_SAMPLE
        )

    async def _periodic_flush(self):
        """定期刷新缓冲区到文件"""
        while self._is_recording:
            await asyncio.sleep(0.1)  # 每 100ms 刷新一次
            self._flush_buffers()

    def _flush_buffers(self):
        """
        将缓冲区数据以交错格式写入 WAV 文件

        确保左右声道对齐：短的一方用静音填充。
        """
        if not self._wav_file:
            return

        frame_size = SAMPLES_PER_FRAME * BYTES_PER_SAMPLE

        # 计算可写入的完整帧数（取较长的一方）
        user_frames = len(self._user_buffer) // frame_size
        agent_frames = len(self._agent_buffer) // frame_size
        frames_to_write = max(user_frames, agent_frames)

        if frames_to_write == 0:
            return

        for _ in range(frames_to_write):
            # 提取左声道数据（用户）
            if len(self._user_buffer) >= frame_size:
                left_data = bytes(self._user_buffer[:frame_size])
                del self._user_buffer[:frame_size]
            else:
                left_data = SILENCE_FRAME

            # 提取右声道数据（Agent）
            if len(self._agent_buffer) >= frame_size:
                right_data = bytes(self._agent_buffer[:frame_size])
                del self._agent_buffer[:frame_size]
            else:
                right_data = SILENCE_FRAME

            # 交错合并左右声道
            interleaved = self._interleave_stereo(left_data, right_data)
            self._wav_file.writeframes(interleaved)
            self._synced_frame_count += 1

    @staticmethod
    def _interleave_stereo(left: bytes, right: bytes) -> bytes:
        """
        将两个单声道数据交错合并为双声道

        Args:
            left: 左声道 PCM 数据
            right: 右声道 PCM 数据

        Returns:
            交错后的双声道 PCM 数据
        """
        left_samples = np.frombuffer(left, dtype=np.int16)
        right_samples = np.frombuffer(right, dtype=np.int16)

        # 确保长度一致
        min_len = min(len(left_samples), len(right_samples))
        left_samples = left_samples[:min_len]
        right_samples = right_samples[:min_len]

        # 创建交错数组
        stereo = np.empty(min_len * 2, dtype=np.int16)
        stereo[0::2] = left_samples  # 左声道
        stereo[1::2] = right_samples  # 右声道

        return stereo.tobytes()


# 单元测试用例（可直接运行）
if __name__ == "__main__":
    import asyncio

    async def test_recorder():
        """测试录音功能"""
        recorder = AudioRecorder(output_dir="test_recordings")

        # 开始录音
        path = recorder.start(session_id="test")
        print(f"录音开始: {path}")

        # 模拟写入数据（1秒的正弦波）
        duration = 1.0
        t = np.linspace(0, duration, int(SAMPLE_RATE * duration), dtype=np.float32)

        # 左声道：440Hz（A4 音）
        left_tone = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        # 右声道：880Hz（A5 音）
        right_tone = (np.sin(2 * np.pi * 880 * t) * 32767).astype(np.int16)

        # 分帧写入
        frame_samples = SAMPLES_PER_FRAME
        for i in range(0, len(left_tone), frame_samples):
            left_frame = left_tone[i : i + frame_samples].tobytes()
            right_frame = right_tone[i : i + frame_samples].tobytes()
            recorder.write_user_frame(left_frame)
            recorder.write_agent_frame(right_frame)
            await asyncio.sleep(0.01)

        # 停止录音
        await asyncio.sleep(0.2)
        final_path = await recorder.stop()
        print(f"录音结束: {final_path}")

    asyncio.run(test_recorder())
