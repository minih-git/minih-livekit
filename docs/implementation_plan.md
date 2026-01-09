# LiveKit Agents 重构实施计划

## 目标

将当前的自定义 Agent 循环逻辑（`core.VoiceAgent`）重构为 LiveKit Agents 框架的标准 `VoicePipelineAgent` 模式。
保持现有的技术方案不变：

- **ASR**: 本地 Sherpa-onnx 方案
- **LLM**: DeepSeek (OpenAI 兼容)
- **TTS**: 火山引擎 Websocket 方案

## 核心变更

LiveKit Agents 框架通过 `VoicePipelineAgent` 类管理语音交互的完整生命周期（VAD -> STT -> LLM -> TTS）。我们需要将现有的 `services` 模块封装为框架定义的标准接口插件。

### 1. 架构对比

| 组件       | 当前实现                              | 重构后方案                                     |
| :--------- | :------------------------------------ | :--------------------------------------------- |
| **主循环** | `core/agent.py` (VoiceAgent) 手动管理 | `livekit.agents.pipeline.VoicePipelineAgent`   |
| **VAD**    | `asr.py` 内置 RMS/计数器逻辑          | 自定义 `LocalVAD` 适配器 (实现 `vad.VAD`)      |
| **STT**    | `asr.py` LocalASR                     | 自定义 `LocalSTT` 适配器 (实现 `stt.STT`)      |
| **LLM**    | `llm.py` LLMClient                    | 自定义 `DeepSeekLLM` 适配器 (实现 `llm.LLM`)   |
| **TTS**    | `tts.py` VolcengineTTS                | 自定义 `VolcengineTTS` 适配器 (实现 `tts.TTS`) |

### 2. 组件适配计划

需要创建 `agent/src/plugins` 目录（既然已经存在，则在其下创建或整理），将现有逻辑适配为 LiveKit 接口。

#### [NEW] `plugins/local_vad.py`

- 继承自 `livekit.agents.vad.VAD`。
- 移植 `services/asr.py` 中的 RMS 能量检测和静音计数逻辑。
- 作用：向 Pipeline 提供 `VADEvent.START_OF_SPEECH` 和 `VADEvent.END_OF_SPEECH` 事件，用于打断 TTS 和触发 STT 提交。

#### [MODIFY] `services/asr.py` -> `plugins/local_stt.py`

- 继承自 `livekit.agents.stt.STT`。
- 保留 `LocalASR` 核心推理逻辑，但移除 VAD 状态机（交由 `LocalVAD` 或 Pipeline 控制）。
- 实现 `stream()` 方法，接收音频流，输出 `SpeechStream`，其中产出 `SpeechEvent` (包含 `SpeechData` 文本)。
- 注意：由于 `Sherpa-onnx` 本身支持流式，这与 STT 接口非常契合。

#### [MODIFY] `services/llm.py` -> `plugins/deepseek_llm.py`

- 继承自 `livekit.agents.llm.LLM`。
- 实现 `chat()` 方法，适配 `AsyncOpenAI` 的流式输出为 `llm.ChatChunk`。
- 支持 `chat_context` 上下文管理。

#### [MODIFY] `services/tts.py` -> `plugins/volcengine_tts.py`

- 继承自 `livekit.agents.tts.TTS`。
- 实现 `synthesize()` 方法，适配 `SynthesizedAudio` 输出。
- 确保采样率和音频格式与 LiveKit 期望一致（通常 `VoicePipelineAgent` 会处理重采样，但提供正确的元数据很重要）。

### 3. 入口与配置

#### [MODIFY] `agent_impl.py`

- 移除 `core.VoiceAgent` 的使用。
- 在 `entrypoint` 中初始化各个插件：

  ```python
  vad = LocalVAD()
  stt = LocalSTT()
  llm = DeepSeekLLM()
  tts = VolcengineTTS()

  agent = VoicePipelineAgent(
      vad=vad,
      stt=stt,
      llm=llm,
      tts=tts,
      chat_ctx=initial_chat_ctx
  )
  agent.start(ctx.room, participant)
  ```

- 保留现有的录音逻辑（`AudioRecorder`），可能需要作为 Pipeline 的 hook 或独立任务运行（Pipeline 提供了 `before_llm_cb`, `after_tts_cb` 等回调，或者直接监听房间音频）。
- **注意**：原有的录音功能是分轨录制，`VoicePipelineAgent` 自动处理了音频流。如果要保持录音功能，可能需要单独订阅 Track 并写入文件，这部分逻辑可以保留在 `entrypoint` 中独立于 Agent 运行，或者通过 Agent 的 Hook 机制。

## 详细步骤

1.  **准备环境**: 确认 `livekit-agents` 库版本支持 `VoicePipelineAgent` (最新版)。
2.  **创建 VAD 适配器**: 从 `asr.py` 提取 VAD 逻辑到 `plugins/local_vad.py`。
3.  **重构 STT**: 修改 `asr.py` 或新建 `plugins/local_stt.py`，实现 `STT` 接口。
4.  **重构 LLM**: 基于 `llm.py` 修改为 `plugins/deepseek_llm.py`，实现 `LLM` 接口。
5.  **重构 TTS**: 基于 `tts.py` 修改为 `plugins/volcengine_tts.py`，实现 `TTS` 接口。
6.  **更新依赖**: 确保所有重构后的类正确导入。
7.  **集成测试**: 在 `agent_impl.py` 中组装 Pipeline 并测试基本对话流程。
8.  **功能验证**:
    - 验证 VAD 打断是否灵敏。
    - 验证 STT 识别准确度。
    - 验证 TTS 播放流畅度。
    - 验证录音功能（如果需要保留）。

## 验证计划

1.  **单元测试**: 对每个 Plugin 进行简单的 Mock 输入测试，确保符合接口规范。
2.  **端到端测试**: 启动 Agent，连接 LiveKit 房间，进行语音对话，检查日志输出确认 Pipeline 各阶段（Thinking, Speaking, Listening）状态切换正常。

## 风险评估

- **VAD 调优**: 现在的 VAD 逻辑是硬编码在 `LocalASR` 里的，拆分后可能需要重新调整参数以配合 `VoicePipelineAgent` 的状态机。
- **自定义事件**: 原有的 `agent_ready` 和 `transcript` DataChannel 消息，`VoicePipelineAgent` 默认可能会发送相关事件，也可能不发送。需要确认是否需要手动发送这些业务消息支持前端展示。
  - `VoicePipelineAgent` 通常会自动处理对话逻辑，但字幕发送可能需要通过 `before_tts_cb` 或监听 Agent 事件来通过 `rpc` 或 `data channel` 发送给前端。需要保留原有的字幕发送逻辑。
