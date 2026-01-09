import logging
import numpy as np
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VADEventType(Enum):
    START_OF_SPEECH = 1
    END_OF_SPEECH = 2


@dataclass
class VADEvent:
    type: VADEventType
    timestamp: float
    speech_duration: float
    silence_duration: float


class VADEngine:
    """
    通用 VAD (Voice Activity Detection) 引擎
    基于 RMS 能量检测，不依赖 LiveKit
    """

    def __init__(
        self,
        min_volume_db: float = -40.0,
        start_talking_threshold: float = 0.5,
        stop_talking_threshold: float = 0.8,
        sample_rate: int = 16000,
    ):
        self.rms_threshold = 10 ** (min_volume_db / 20)
        self.start_talking_threshold = start_talking_threshold
        self.stop_talking_threshold = stop_talking_threshold
        self.sample_rate = sample_rate

        self._is_speaking = False
        self._speech_duration = 0.0
        self._silence_duration = 0.0

    def process_frame(self, audio_data: np.ndarray) -> VADEvent | None:
        """
        处理一帧音频数据

        Args:
            audio_data: float32 numpy array, range [-1, 1]

        Returns:
            VADEvent if state changes, otherwise None
        """
        # 计算 RMS
        rms = np.sqrt(np.mean(audio_data**2))

        # 计算当前帧时长 (秒)
        frame_duration = len(audio_data) / self.sample_rate

        is_active = rms >= self.rms_threshold
        event = None

        if is_active:
            self._silence_duration = 0.0
            self._speech_duration += frame_duration

            if (
                not self._is_speaking
                and self._speech_duration >= self.start_talking_threshold
            ):
                self._is_speaking = True
                event = VADEvent(
                    type=VADEventType.START_OF_SPEECH,
                    timestamp=time.time(),
                    speech_duration=self._speech_duration,
                    silence_duration=0.0,
                )
                logger.debug(f"VADEngine: Start of speech (RMS: {rms:.4f})")
        else:
            self._speech_duration = 0.0
            self._silence_duration += frame_duration

            if (
                self._is_speaking
                and self._silence_duration >= self.stop_talking_threshold
            ):
                self._is_speaking = False
                event = VADEvent(
                    type=VADEventType.END_OF_SPEECH,
                    timestamp=time.time(),
                    speech_duration=self._speech_duration,
                    silence_duration=self._silence_duration,
                )
                logger.debug(
                    f"VADEngine: End of speech (Silence: {self._silence_duration:.2f}s)"
                )

        return event

    def reset(self):
        self._is_speaking = False
        self._speech_duration = 0.0
        self._silence_duration = 0.0
