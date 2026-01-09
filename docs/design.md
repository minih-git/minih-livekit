# AI Real-time Voice Interaction System Design Document

## 1. 项目概述

本项目旨在构建一个**低成本、跨平台、低延迟**的 AI 实时语音交互系统。

- **核心架构**: Client-Server-Agent 模式，基于 **LiveKit** 进行实时 WebRTC 通信。
- **平台支持**: Windows / macOS / Linux / iOS / Android (基于 **Tauri v2**)。
- **AI 策略**: **混合云架构 (Hybrid Architecture)** —— 本地 CPU 运行极致优化的 ASR，云端 API 处理 LLM 和 TTS，在零 GPU 成本下实现低延迟体验。

## 2. 系统架构图

```mermaid
graph TD
    User((用户))

    subgraph Client [Tauri v2 Client (React)]
        UI[React UI + LiveKit Components]
        SDK[LiveKit JS SDK]
        Mic[麦克风输入]
        Speaker[扬声器输出]
    end

    subgraph Infrastructure [LiveKit Server]
        SFU[LiveKit SFU (Docker)]
    end

    subgraph Agent_Service [Python AI Agent]
        Worker[LiveKit Worker]

        subgraph Local_Compute [本地 CPU 计算]
            ASR[Sherpa-onnx ASR]
            Model_ASR[Paraformer-Streaming]
        end

        subgraph Cloud_API [云端 API 服务]
            LLM_API[OpenAI Compatible LLM]
            TTS_API[Volcengine / Doubao TTS]
        end
    end

    User <-->|语音交互| Client
    Client <-->|WebRTC (Audio)| SFU
    SFU <-->|Audio Stream| Worker

    Worker -->|Audio Frame| ASR
    ASR -->|Text| LLM_API
    LLM_API -->|Text Stream| TTS_API
    TTS_API -->|Audio Stream| Worker

```

## 3. 技术栈选型

| 模块               | 技术组件                | 关键配置/说明                                                   |
| ------------------ | ----------------------- | --------------------------------------------------------------- |
| **App 框架**       | **Tauri v2**            | 跨平台构建核心。移动端利用 WebView 渲染。                       |
| **构建工具**       | **Rsbuild**             | 替代 Vite，基于 Rspack，提供极速构建体验 (0.5s+)。              |
| **前端 UI**        | **React** + **Rsbuild** | 使用 `@livekit/components-react`。风格：**Cyber-Teal** (赛博青) |
| **实时传输**       | **LiveKit Server**      | 使用 Docker 部署。负责信令与媒体转发。                          |
| **Agent 语言**     | **Python**              | 3.10+ 版本，生态最丰富，处理音频流最方便。                      |
| **ASR (语音转文)** | **Sherpa-onnx**         | **本地 CPU 运行**。模型：`paraformer-zh-streaming` (ONNX)。     |
| **LLM (大脑)**     | **OpenAI 兼容模型**     | 支持 **DeepSeek**, **Qwen**, **OpenAI** 等 (可配置 Base URL)。  |
| **TTS (文转语音)** | **Volcengine (豆包)**   | 通过 WebSocket 调用。低延迟，声音自然。                         |

## 4. 模块详细设计

### 4.1 客户端 (Tauri + React)

- **功能**:
- **房间连接**: 管理 Token，自动重连。
- **音频可视化**: 展示用户麦克风和 AI 回复的音频波形 (Visualizer)。
- **权限管理**: 启动时检查麦克风权限。
- **移动端适配 (Simple Mode)**:

  - **前台保活**: 使用 `tauri-plugin-keepawake` 防止屏幕熄灭导致网络断开。
  - **生命周期**: App 切入后台时保持连接状态，支持后台语音通话。

- **依赖库**:
- `livekit-client`, `@livekit/components-react`, `@livekit/components-styles`
- `@tauri-apps/plugin-os`, `@tauri-apps/plugin-http`

### 4.2 服务端 (LiveKit Server)

- **部署**: 标准 Docker Compose 部署。
- **配置**: 需开放 TCP/UDP 端口范围，确保 WebRTC 穿透。建议配置 Turn Server 以保证 4G/5G 环境下的连通性。

### 4.3 AI Agent (Python Backend)

- **运行环境**: 普通 CPU 服务器 (4 核/8G 内存即可)，**无需 GPU**。
- **管道逻辑**:

1. **VAD**: 使用 `silero-vad` 判断用户说话结束。
2. **ASR**: 接收音频帧 -> `Sherpa-onnx` -> 实时产出文本。
3. **Interrupt (打断)**: 当 VAD 检测到用户说话时，立即向 TTS 队列发送 Flush 指令，停止 AI 当前播放。
4. **LLM**: 接收 ASR 文本 -> 调用 DeepSeek API (Stream) -> 产出文本块。
5. **TTS**: 接收文本块 -> 发送至火山引擎 WebSocket -> 接收音频数据 -> 推送回 LiveKit Room。

### 4.4 录音与实时字幕设计 (New)

- **通话录音 (Local Recording)**:
  - **逻辑**: Agent 订阅 Room 内所有音轨。
  - **存储**: 创建双声道 WAV 文件。左声道录制用户原始音频，右声道录制 Agent 生成的音频。
  - **同步**: 采用统一的帧时钟（16kHz/30ms 帧）进行填充，确保回放时语序和间隔与实际通话一致。
- **实时字幕 (Real-time Subtitles)**:
  - **传输**: 通过 Data Channel 发送 JSON 消息。
  - **内容**: 包含 `participant` (user/agent)、`text`、`is_final` (ASR 状态) 和 `timestamp`。
  - **交互**: 前端实时渲染滚动对话框，支持 ASR 中间结果（Partial）的实时刷新。

## 5. 最低硬件需求 (MVP)

由于采用了**混合云架构**，硬件门槛极低：

- **CPU**: 4 vCPU (Intel i5/AMD Ryzen 5 或同级云服务器)
- **RAM**: 8 GB (16 GB 推荐)
- **GPU**: **不需要**
- **网络**: 上行带宽 10Mbps+ (保证 TTS 音频流下载流畅)
- **硬盘**: 40GB+ SSD

## 6. 开发路线图

- **Phase 1: 核心链路验证 (Desktop)**
- 在本地 Docker 启动 LiveKit Server。
- 编写 Python Agent：集成 Sherpa-onnx (CPU) + LLM (OpenAI 协议) + Volcengine。
- 使用 React 编写简单的 Web 页面进行通话测试。

- **Phase 2: Tauri 桌面端集成**
- 初始化 Tauri v2 项目。
- 将 React 代码迁移至 Tauri。
- 配置系统托盘和窗口样式。

- **Phase 3: 移动端构建 (iOS/Android)**
- 运行 `tauri android init` / `tauri ios init`。
- 配置 `AndroidManifest.xml` 和 `Info.plist` (麦克风权限)。
  - 实现 `Simple Mode` 的应用生命周期管理。
- 真机调试。

## 7. 风险与规避

- **API 网络延迟**: 云端 TTS 依赖外网稳定性。
- _规避_: Agent 服务器尽量部署在网络质量好的数据中心（如阿里云/腾讯云），与火山引擎节点物理距离近。

- **CPU ASR 瓶颈**: 如果并发用户多，CPU 负载会高。
- _规避_: 限制 MVP 房间人数；Sherpa-onnx 开启多线程优化。
