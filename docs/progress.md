# 项目进度记录

> 本文档记录 `minih-livekit` 项目的实施进度，供后续开发者参考。

---

## 阶段一：核心链路验证 (Desktop)

### Phase 4: 功能增强 & UI 重构 ✅

- **2026-01-06**: 完成"通话保留"与"实时字幕"功能，并进行大规模 UI/UX 优化。
  - **核心功能**:
    - 新增 `recorder.py` 双声道 WAV 录音模块（修复了采样率不匹配导致的录制失效问题）。
    - 集成 `database.py` (SQLite) 模块，支持对话历史持久化。
    - Token Server 新增历史查询 API (`/api/history`)。
  - **UI/UX 重构**:
    - **双栏布局**: 为 PC 端实现左右分栏（左侧通话控制，右侧实时字幕）。
    - **视觉升级**: 全面引入 Cyber-Teal 赛博青主题，增加玻璃拟态效果、动态背景和弹性动画。
    - **字幕优化**: 重新设计对话气泡，添加头像指示灯、打字光标效果及平滑滚动。
    - **历史记录界面**: 实现全屏覆盖的历史记录查看器，支持列表检索与消息详情。
  - **Bug 修复**:
    - 修复了 AudioRecorder 的属性引用错误 (`_file_path`)。
    - 修复了 SQLite 无法直接存储 `PosixPath` 对象的类型兼容问题。
    - 修复了移动端界面被容器黑框限制的布局问题。

### ✅ 步骤 1.1.1：验证基础开发工具

**完成时间**：2026-01-05

**验证结果**：

| 工具               | 要求版本 | 实际版本 | 状态 |
| ------------------ | -------- | -------- | ---- |
| Rust               | >= 1.77  | 1.92.0   | ✅   |
| Node.js            | >= 20.0  | 24.11.1  | ✅   |
| Python             | 3.10+    | 3.13.5   | ✅   |
| Docker             | 最新版   | 28.5.1   | ✅   |
| Docker Compose     | 最新版   | 2.40.3   | ✅   |
| uv (Python 包管理) | 最新版   | 0.9.17   | ✅   |

**备注**：

- Python 使用 3.13.5 版本，经验证 `sherpa-onnx` 已提供 cp313 wheel 支持
- Python 包管理采用 `uv` 替代传统 `pip/venv`，提升依赖解析速度

---

### ✅ 步骤 1.2.1 - 1.2.4：LiveKit Server 部署

**完成时间**：2026-01-05

**创建文件**：

- `server/livekit.yaml` - LiveKit 服务器配置
- `server/docker-compose.yaml` - Docker Compose 编排文件

**配置参数**：

| 配置项          | 值                                                  |
| --------------- | --------------------------------------------------- |
| API Key         | `devkey`                                            |
| API Secret      | `devsecret_minih_livekit_2026_secure_key` (42 字符) |
| HTTP/WS 端口    | 7880                                                |
| WebRTC 端口范围 | 51000-51200 (UDP/TCP)                               |
| LiveKit 版本    | 1.9.10                                              |

**验证结果**：

- [x] `docker compose ps` - 容器状态 `Up (healthy)` ✅
- [x] `docker compose logs` - 日志显示 `starting LiveKit server` ✅
- [x] `curl http://localhost:7880` - 返回 `OK` ✅

**备注**：

- 端口范围从 50000-50200 调整为 51000-51200，避免与系统服务冲突
- API Secret 需至少 32 字符，已调整为 42 字符

---

### ✅ 步骤 1.3.1 - 1.3.9：Python AI Agent 开发

**完成时间**：2026-01-05

**创建文件**：

- `agent/pyproject.toml` - uv 项目配置，定义 Python 依赖
- `agent/asr.py` - 本地 ASR 模块，封装 Sherpa-onnx 流式识别
- `agent/llm.py` - LLM 调用模块，封装 DeepSeek API
- `agent/tts.py` - TTS 调用模块，封装火山引擎 WebSocket
- `agent/agent_impl.py` - Agent 管道逻辑，整合 VAD/ASR/LLM/TTS
- `agent/main.py` - 主入口，配置日志和环境变量检查
- `agent/models/` - ASR 模型文件目录

**依赖版本**：

| 包名           | 版本    |
| -------------- | ------- |
| livekit-agents | 1.3.10  |
| sherpa-onnx    | 1.12.20 |
| openai         | 2.14.0  |
| websockets     | 15.0.1  |
| numpy          | 2.4.0   |

**ASR 模型**：

- `encoder.int8.onnx` (158MB) - Paraformer 编码器
- `decoder.int8.onnx` (68MB) - Paraformer 解码器
- `tokens.txt` (74KB) - 词表文件

**验证结果**：

- [x] `uv sync` 安装所有依赖 ✅
- [x] `import livekit.agents` 验证通过 ✅
- [x] `import sherpa_onnx` 验证通过 ✅
- [x] ASR 模型加载成功 ✅

### ✅ 步骤 1.4.1 - 1.4.4：Web 客户端原型 (基础)

**完成时间**：2026-01-05

**创建文件**：

- `app/` - Vite + React + TypeScript 项目
- `app/src/api/token.ts` - Token API 客户端模块
- `app/src/App.tsx` - 主界面组件（连接/断开、状态显示）
- `app/src/App.css` - 现代化 UI 样式
- `agent/src/minih_livekit_agent/token_server.py` - Token HTTP 服务器

**安装依赖**：

| 包名                       | 版本    |
| -------------------------- | ------- |
| livekit-client             | 2.16.1  |
| @livekit/components-react  | 2.9.17  |
| @livekit/components-styles | 1.2.0   |
| lucide-react               | 0.562.0 |
| livekit-api (Agent)        | 0.7.0+  |
| aiohttp (Agent)            | 3.9.0+  |

**验证结果**：

- [x] `npm run build` - 前端构建成功 ✅
- [x] `npm run dev` - 开发服务器正常 (localhost:5173) ✅
- [x] `uv sync` - Agent 依赖安装成功 ✅
- [x] `import TokenServer` - 模块导入验证通过 ✅

### ✅ 迁移至 Rsbuild & UI 优化

**完成时间**：2026-01-05

**变更内容**：

- **构建系统**: Vite -> Rsbuild v1.7.1
- **UI 主题**: 蓝/紫 -> Cyber-Teal (赛博青) / 深色系
- **配置变更**:
  - 环境变量前缀: `PUBLIC_`
  - 配置文件: `rsbuild.config.ts`

**验证结果**：

- [x] `npm run build` - 构建耗时 **0.54s** (显著提升) ✅
- [x] 产物检查 - `dist/static/js/index.*.js` 生成正常 ✅

### ✅ 步骤 1.4.5：添加音频可视化组件

**完成时间**：2026-01-05

**变更内容**：

- **组件集成**: 使用 `@livekit/components-react` 的 `BarVisualizer`
- **功能实现**:
  - 用户侧 (麦克风): 底部显示音频波形
  - Agent 侧 (语音): 头像中心显示音频波形 (替代静态图标)
- **UI 优化**: 适配 Cyber-Teal 主题，调整可视化条颜色和高度

**验证结果**：

- [x] `npm run build` - 构建成功，类型检查通过 ✅
- [x] 视觉效果 - 确认 `visualizer-agent` 和 `visualizer-user`容器已正确添加 ✅

---

### ✅ 文档更新：泛化 LLM 支持

**完成时间**：2026-01-05

**变更内容**：

- **通用化文档**: 更新 `design.md`, `tech-stack.md`, `architecture.md` 已移除特定模型 (DeepSeek) 的绑定
- **可配置化**: 明确了通过环境变量 (`LLM_BASE_URL`, `LLM_MODEL`) 配置任意 OpenAI 兼容模型的方法
- **代码增强**: 更新 `agent/src/.../llm.py` 支持动态配置

**验证结果**：

- [x] 文档一致性检查通过 ✅
- [x] Agent 启动日志包含 `LLM_BASE_URL` 和 `LLM_MODEL` 提示 ✅

---

## 待完成步骤

- [x] 集成测试：LiveKit Server + Agent + Web 客户端端到端验证 ✅ (2026-01-05)

### ✅ 阶段二：Tauri 桌面端集成

**进行中**：2026-01-05

**步骤**：

- [x] 初始化 Tauri v2 项目 (Rsbuild + React) ✅
- [x] 配置 keepawake 插件 (防止息屏) ✅
- [x] 构建生产版本 (Build) ✅ (macOS .app/.dmg)

### ✅ 步骤 2.2.1：实现系统托盘 (System Tray)

**完成时间**：2026-01-05

**变更内容**：

- **代码实现**: 在 `app/src-tauri/src/lib.rs` 中添加 `TrayIconBuilder`
- **功能**:
  - 左键点击托盘图标：显示/聚焦主窗口
  - 右键菜单：包含 "显示窗口" 和 "退出" 选项
- **依赖配置**: 更新 `Cargo.toml` 启用 `tray-icon`, `image-png`, `wry` 特性

**验证结果**：

- [x] `cargo check` 编译通过 ✅
- [x] 代码静态检查无警告 ✅
- [x] `cargo check` 编译通过 ✅
- [x] 代码静态检查无警告 ✅

### ✅ 阶段三：移动端构建 (iOS/Android)

**进行中**：2026-01-05

#### 步骤 3.1：Android 构建

- 状态：**跳过** (Skipped)
- 原因：系统未检测到 `adb` 或 Android SDK 环境

#### 步骤 3.2：iOS 构建

- [x] **初始化项目**: `npm run tauri ios init` 成功，生成 `.xcodeproj`
- [x] **权限配置**: 更新 `Info.plist` 添加 `NSMicrophoneUsageDescription`
- [x] **构建验证**: 运行 `npm run tauri ios build`，确认 Xcode 项目结构有效 (因无签名导致最终通过失败，符合预期)

#### 步骤 3.3：移动端生命周期管理

- [x] **功能实现**:
  - 在 `app/src/App.tsx` 中添加 `visibilitychange` 监听
  - ~~切入后台：自动释放 Token 并断开连接~~ (已移除，桌面端保持连接)
  - 切回前台：记录日志用于调试

---

### ✅ Agent 代码重构与日志修复

**完成时间**：2026-01-06

**变更内容**：

- **目录结构重构**: 将 `agent/src/minih_livekit_agent` 下的模块拆分至 `agent/src/core` (核心逻辑) 和 `agent/src/services` (功能服务)。
  - `VoiceAgent` -> `core/agent.py`
  - `ASR`, `TTS`, `LLM`, `Recorder`, `Database`, `TokenServer` -> `services/`
  - `agent_impl.py` -> `agent/src/agent_impl.py`
  - `main.py` -> `agent/main.py`
- **日志修复**:
  - 修复了 `services.asr` 日志未正确配置导致向 Root Logger 冒泡，从而产生重复日志的问题。
  - 在 `main.py` 中明确配置 `services` 和 `core` 的 Logger，并设置 `propagate=False`。
  - 移除了 `minih_livekit_agent` 相关的废弃配置。

**验证结果**：

- [x] Agent 启动正常，模块加载无误 ✅
- [x] 日志不再重复输出，格式统一 ✅

---

### ✅ ASR 识别优化

**完成时间**：2026-01-06

**问题诊断**：

1. 识别结果碎片化（如 "是"、"你" 单字输出）
2. 环境噪音被误识别为语音
3. 重复识别（同一音频轨道被多次订阅）
4. 内存占用过高

**优化措施**：

| 优化项             | 之前         | 之后                      |
| ------------------ | ------------ | ------------------------- |
| VAD 说话后静音阈值 | 0.8s         | **1.5s**                  |
| VAD 未说话静音阈值 | 1.2s         | **2.0s**                  |
| 最大单句时长       | 20s          | **30s**                   |
| 重采样算法         | scipy.signal | **soxr (高质量)**         |
| 音频缓冲           | 无           | **100ms 最小缓冲**        |
| 采样率检测         | 硬编码 48kHz | **自动检测**              |
| 噪音过滤           | 无           | **RMS 阈值 0.01 (-40dB)** |

**代码变更**：

- `asr.py`: 添加 `soxr` 重采样、RMS 噪音过滤、音频缓冲机制
- `agent_impl.py`: 添加音频轨道去重、采样率自动检测
- `App.tsx`: 移除后台自动断开逻辑
- `cli.py`: 优化日志配置，防止重复打印

**新增依赖**：

| 包名 | 版本  | 用途             |
| ---- | ----- | ---------------- |
| soxr | 1.0.0 | 高质量音频重采样 |

**验证结果**：

- [x] 完整句子识别 "能听到我说话吗"、"我又重新开始说话" ✅
- [x] 环境噪音不再被误识别 ✅
- [x] 帧计数连续递增（无重复订阅）✅
- [x] 切换窗口后连接保持活跃 ✅
      282:
      283: ---
      284:
      285: ### ✅ TTS 模块修复与 ASR 体验优化
      286:
      287: **完成时间**：2026-01-06
      288:
      289: **变更内容**：
      290:
      291: - **TTS 接口修复**:
      292: - 弃用不稳定的 V3 接口，重写使用 **V1 WebSocket 二进制协议**
      293: - 修正了 `Authorization` Header (Bearer; {token}) 和 `gzip` 压缩 Payload
      294: - 完善了音频分帧 (30ms/帧) 和速率控制发送逻辑
      295: - **ASR 体验增强 (Anti-Echo & Noise Filter)**:
      296: - **防回声**: 添加 `_is_playing_audio` 标志，在 TTS 播放期间暂停 ASR 建议处理
      297: - **静音缓冲**: TTS 播放结束后增加 **500ms** 静音缓冲，避免尾音干扰
      298: - **碎片过滤**: 识别文本长度 < **3** 字符时自动忽略，有效屏蔽 "你"、"嗯" 等无效识别
      299: - **阈值调优**: 将 RMS 阈值从 0.06 上调至 **0.15**，过滤近距离低分贝背景噪音
      300:
      301: **验证结果**：
      302: - [x] TTS 语音回复流畅清晰 ✅
      303: - [x] 播放时不再触发 ASR 重复识别 ✅
      304: - [x] 成功过滤由于麦克风拾音导致的碎片化单字 ✅

### ✅ Phase 5: Agent 架构重构 (LiveKit Agents Pipeline)

**完成时间**：2026-01-06

**目标**：
将自定义的 Agent 循环逻辑重构为 LiveKit Agents 框架的标准 `AgentSession` 模式（注：`VoicePipelineAgent` 已被 `AgentSession` 取代），以获更好的扩展性和维护性。

**变更内容**：

- **核心逻辑重组**:
  - 弃用手动管理的 `core.VoiceAgent`
  - 迁移至 `livekit.agents.AgentSession` 标准架构
  - 新增 `VoiceAssistant(Agent)` 类管理会话生命周期
- **适配器封装 (Plugins)**:
  - `plugins/local_vad.py`: 封装 RMS/静音检测逻辑实现 `vad.VAD` 接口
  - `plugins/local_stt.py`: 封装 Sherpa-onnx 实现 `stt.STT` 接口
  - ~`plugins/deepseek_llm.py`: 封装 DeepSeek API 实现 `llm.LLM` 接口~ (已替换为 `livekit.plugins.openai.LLM`)
  - `plugins/volcengine_tts.py`: 封装火山引擎 TTS 实现 `tts.TTS` 接口
- **依赖管理**:
  - 升级 `livekit-agents` 至 1.3.10
  - 修复了 `stt.APIConnectOptions` 和 `llm.FunctionContext` 的版本兼容性问题

**验证结果**：

- [x] 插件化架构重构完成，代码结构更清晰 ✅
- [x] 自定义插件正确实现 LiveKit 接口规范 ✅
- [x] AgentSession 启动成功，Token 服务和数据库服务正常加载 ✅

---

### ✅ Phase 6: Agent Session 集成修复与增强

**完成时间**：2026-01-06

**问题诊断**：

1. `AttributeError: 'AgentSession' object has no attribute 'room'` - 无法访问房间信息
2. `TypeError: Can't instantiate abstract class InterceptedSpeechStream` - 抽象方法未实现
3. `AttributeError: 'ChatChunk' object has no attribute 'choices'` - LLM Chunk 结构不兼容
4. 前端持续显示 "AI 正在准备中..." - `agent_ready` 信号未发送
5. 对话内容未推送到前端 - Data Channel 消息缺失
6. Agent 波形图未居中 - CSS 定位问题
7. 用户断开连接后 Agent 未立即退出

**优化措施**：

| 问题                  | 修复方案                                                               |
| --------------------- | ---------------------------------------------------------------------- |
| 无法访问 room         | 在 `VoiceAssistant.__init__` 中接收并存储 `ctx.room` 引用              |
| 抽象方法缺失          | 实现 `InterceptedSpeechStream._run()` 和 `InterceptedLLMStream._run()` |
| ChatChunk 结构不兼容  | 使用 `hasattr()` 兼容 `choices` 和 `delta` 两种结构                    |
| agent_ready 信号缺失  | 在 `_send_ready_message` 中先发送 `type: "agent_ready"` 消息           |
| Data Channel 消息缺失 | 在 Intercepted STT/LLM 流中添加 `_send_transcript()` 方法              |
| 波形图定位问题        | 将 visualizer 移入 `avatar-circle` 并使用绝对定位居中                  |
| Agent 无法正常退出    | 使用 `ConnectionState` 循环监听房间状态，添加 `cleanup()` 方法         |

**代码变更**：

- `agent_impl.py`:
  - `SessionState` 添加 `room` 属性用于 Data Channel 通信
  - `InterceptedSpeechStream` 添加 `_send_transcript()` 推送用户字幕
  - `InterceptedLLMStream` 添加 `_send_transcript()` 推送 Agent 回复（支持流式更新）
  - `VoiceAssistant` 添加 `cleanup()` 方法正确取消后台任务
  - `entrypoint` 使用 `ConnectionState` 监听替代 `Event().wait()`
- `App.tsx`:
  - 将 `visualizer-agent` 移入 `avatar-circle` 内部
- `App.css`:
  - 添加 `.ai-avatar` 样式实现水平居中
  - 更新 `.visualizer-agent` 使用绝对定位

**验证结果**：

- [x] Agent 正确访问房间信息，录音和数据库功能正常 ✅
- [x] 用户语音和 Agent 回复实时推送到前端字幕面板 ✅
- [x] "可以开始对话了" 状态正确显示 ✅
- [x] Agent 波形图在圆形头像内居中显示 ✅
- [x] 用户断开连接后 Agent 正确清理并退出 ✅
