import asyncio
import logging
import json
import time
import numpy as np
from typing import AsyncIterable
import os

from livekit import rtc
from livekit.agents import JobContext, WorkerOptions, AgentSession, Agent, stt, llm, tts
from livekit.agents.utils import AudioBuffer
from livekit.plugins import silero

# 引入自定义插件
from plugins.stt import LocalSTT, LocalSpeechStream
from plugins.llm import FastGPTLLM, FastGPTLLMStream
from plugins.tts import VolcengineTTS, SynthesizeStream, ChunkedStream

from services.recorder import AudioRecorder
from services.database import ChatDatabase
from core.session import SessionState


logger = logging.getLogger("agent")


# --- Wrappers for History & Recording ---


class VoiceAssistant(Agent):
    """
    自定义语音助手 Agent
    """

    def __init__(
        self,
        db: ChatDatabase,
        recorder: AudioRecorder,
        state: SessionState,
        room: rtc.Room,
    ):
        super().__init__(
            instructions="你是一个友好的 AI 语音助手。请用简洁、口语化的方式回复用户。回复应该简短（通常 1-3 句话），适合语音播放。",
        )
        self.db = db
        self.recorder = recorder
        self.state = state
        self.room = room
        self._recording_task = None

    async def on_enter(self, participant: rtc.RemoteParticipant = None):
        """当 Agent 进入房间时调用"""
        # 如果框架没有传入 participant，尝试从房间获取
        if participant is None:
            # 等待参与者加入
            while not self.room.remote_participants:
                await asyncio.sleep(0.1)

            # 获取第一个参与者
            participant = next(iter(self.room.remote_participants.values()))

        logger.info(
            f"VoiceAssistant 进入会话: {self.room.name}, 参与者: {participant.identity}"
        )

        # 1. 初始化会话
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.state.session_id = f"{self.room.name}_{timestamp}"

        # 2. 启动录音
        path = self.recorder.start(session_id=self.state.session_id)

        # 3. 记录到数据库
        self.db.create_session(
            session_id=self.state.session_id,
            room_name=self.room.name,
            participant=participant.identity,
            recording_path=str(path) if path else None,
        )

        # 4. 发送就绪信号和欢迎消息 (通过 Data Channel)
        await self._send_ready_message(participant)

        # 5. 启动用户音频录制任务
        self._recording_task = asyncio.create_task(self._record_user_audio(participant))

    async def _send_ready_message(self, participant: rtc.RemoteParticipant):
        try:
            # 等待客户端完全订阅 Data Channel
            await asyncio.sleep(0.5)

            # 1. 发送 agent_ready 信号，通知前端 AI 已就绪
            ready_msg = json.dumps({"type": "agent_ready", "message": "已连接"})
            logger.info(f"发送 agent_ready 信号...")
            await self.room.local_participant.publish_data(
                payload=ready_msg.encode("utf-8"),
                reliable=True,
            )
            logger.info(f"agent_ready 信号已发送")

            # 2. 发送欢迎字幕
            message = json.dumps(
                {
                    "type": "transcript",
                    "participant": "agent",
                    "text": "你好！我是你的 AI 助手，请问有什么可以帮你的吗？",
                    "is_final": True,
                    "timestamp": int(time.time() * 1000),
                }
            )
            logger.info(f"发送欢迎字幕...")
            await self.room.local_participant.publish_data(
                payload=message.encode("utf-8"),
                reliable=True,
            )
            logger.info(f"欢迎字幕已发送")
        except Exception as e:
            logger.warning(f"发送欢迎消息失败: {e}")

    async def _record_user_audio(self, participant: rtc.RemoteParticipant):
        """监听并录制用户音频"""
        logger.info(f"开始监听用户音频: {participant.identity}")

        audio_stream = None

        # 等待用户发布音频轨道
        from livekit.rtc import ConnectionState

        while self.room.connection_state == ConnectionState.CONN_CONNECTED:
            # 查找该用户的音频轨道
            track_pub = None
            for pub in participant.track_publications.values():
                if pub.kind == rtc.TrackKind.KIND_AUDIO and pub.track:
                    track_pub = pub
                    break

            if track_pub and track_pub.track:
                logger.info(f"找到用户音频轨道: {track_pub.sid}")
                audio_stream = rtc.AudioStream(track_pub.track)
                break

            await asyncio.sleep(1)

        if not audio_stream:
            return

        try:
            async for event in audio_stream:
                if not self.recorder._is_recording:
                    break

                frame = event.frame
                # 为简单起见，这里先做简单的重采样检查
                if frame.sample_rate != 16000:
                    import soxr

                    resampled = (
                        soxr.resample(frame.data, frame.sample_rate, 16000)
                        .astype(np.int16)
                        .tobytes()
                    )
                    self.recorder.write_user_frame(resampled)
                else:
                    self.recorder.write_user_frame(frame.data)
        except Exception as e:
            logger.error(f"用户音频录制出错: {e}")

    async def cleanup(self):
        """清理后台任务"""
        if self._recording_task and not self._recording_task.done():
            self._recording_task.cancel()
            try:
                await self._recording_task
            except asyncio.CancelledError:
                pass
        logger.info("VoiceAssistant 后台任务已清理")


async def entrypoint(ctx: JobContext):
    """Agent 入口点"""
    logger.info(f"Agent 启动: {ctx.room.name}")

    # 1. 初始化基础服务
    db = ChatDatabase()
    recorder = AudioRecorder(output_dir="recordings")
    session_state = SessionState()
    session_state.room = ctx.room  # 设置房间引用，用于 Data Channel 消息

    # 2. 初始化带拦截功能的插件
    vad_plugin = silero.VAD.load()
    stt_plugin = LocalSTT(db=db, state=session_state)
    llm_plugin = FastGPTLLM(
        db=db,
        state=session_state,
        base_url=os.environ.get("LLM_BASE_URL", "https://api.fastgpt.in/api/v1"),
        api_key=os.environ.get("LLM_API_KEY"),
        model=os.environ.get("LLM_MODEL", "fastgpt-model"),
    )

    tts_plugin = VolcengineTTS(recorder=recorder)

    # 3. 创建 AgentSession
    session = AgentSession(
        vad=vad_plugin,
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
    )

    # 4. 启动 Agent
    assistant = VoiceAssistant(db, recorder, session_state, ctx.room)

    logger.info("启动 AgentSession...")
    try:
        await session.start(
            agent=assistant,
            room=ctx.room,
        )

        # 监听用户离开事件
        @ctx.room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant):
            logger.info(f"参与者已断开: {participant.identity}，准备关闭房间连接...")
            asyncio.create_task(ctx.room.disconnect())

        # 保持运行，直到房间断开连接
        from livekit.rtc import ConnectionState

        while ctx.room.connection_state == ConnectionState.CONN_CONNECTED:
            await asyncio.sleep(0.5)

        logger.info(f"房间连接状态变更: {ctx.room.connection_state}, 准备退出...")

    except asyncio.CancelledError:
        logger.info("任务被取消，准备退出...")
    finally:
        logger.info("AgentSession 结束，清理资源...")
        # 显式关闭 Session，确保 VAD/STT/TTS 等插件的内部任务被取消
        try:
            await session.aclose()
            # 给后台任务一点时间完成清理
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"关闭 session 时出错 (可能已关闭): {e}")

        # 清理 VoiceAssistant 的后台任务
        await assistant.cleanup()
        # 停止录音
        path = await recorder.stop()
        if path and session_state.session_id:
            db.end_session(session_state.session_id, str(path))

        # 收集并取消所有与 STT 相关的挂起任务
        try:
            current_task = asyncio.current_task()
            all_tasks = asyncio.all_tasks()
            stt_tasks = [
                t
                for t in all_tasks
                if t is not current_task
                and t.get_name() in ("STT._metrics_task", "Task-23")
                or (hasattr(t, "get_coro") and "stt" in str(t.get_coro()).lower())
            ]
            if stt_tasks:
                logger.info(f"取消 {len(stt_tasks)} 个 STT 相关任务...")
                for task in stt_tasks:
                    task.cancel()
                await asyncio.gather(*stt_tasks, return_exceptions=True)
        except Exception as e:
            logger.warning(f"清理 STT 任务时出错: {e}")

    return WorkerOptions(
        entrypoint_fnc=entrypoint,
    )
