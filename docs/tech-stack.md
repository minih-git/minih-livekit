# Technical Implementation Guide: AI Real-time Voice System

## 1. 开发环境准备 (Prerequisites)

为了支持 Tauri v2 跨平台开发和 Python AI Agent 运行，开发机需安装以下环境：

### 1.1 基础工具

- **Rust**: `1.77+` (用于 Tauri 构建)
- **Node.js**: `20.0+` (用于 React 前端)
- **Python**: `3.10` - `3.13` (用于 AI Agent，**经验证 3.13.5 已支持 sherpa-onnx，推荐使用最新版以获得更好性能**)
- **Docker & Compose**: 最新版 (用于运行 LiveKit Server)

### 1.2 移动端构建依赖

- **iOS**: macOS, Xcode 15+
- **Android**: Android Studio, NDK, JDK 17, 设置 `JAVA_HOME` 和 `ANDROID_HOME` 环境变量。

---

## 2. 项目目录结构 (Project Structure)

建议采用 **Monorepo** 风格管理代码，保持前后端隔离。

```text
ai-voice-assistant/
├── server/                     # LiveKit 服务端配置
│   ├── docker-compose.yaml     # LiveKit Server 编排
│   └── livekit.yaml            # LiveKit 配置文件
├── agent/                      # Python AI 核心业务
│   ├── models/                 # 存放 Sherpa-onnx 模型 (.onnx)
│   ├── plugins/                # 自定义插件 (如 Volcengine TTS)
│   ├── main.py                 # 入口文件
│   ├── agent_impl.py           # 核心管道逻辑
│   └── requirements.txt        # Python 依赖
└── app/                        # Tauri + React 客户端
    ├── src-tauri/              # Rust 主进程配置
    │   ├── capabilities/       # 权限配置
    │   ├── gen/                # 移动端生成的原生项目 (android/ios)
    │   └── src/lib.rs          # 移动端生命周期钩子
    ├── src/                    # React 源码
    └── package.json
```

---

## 3. 服务端实施细节 (Server)

### 3.1 LiveKit Server (`docker-compose.yaml`)

使用标准镜像，映射 UDP/TCP 端口。

```yaml
services:
  livekit:
    image: livekit/livekit-server:latest
    command: --config /livekit.yaml
    ports:
      - "7880:7880" # WebSocket / API
      - "50000-50200:50000-50200/udp" # WebRTC 媒体流
      - "50000-50200:50000-50200/tcp"
    volumes:
      - ./livekit.yaml:/livekit.yaml
    environment:
      - LIVEKIT_KEYS="API_KEY:SECRET_KEY" # 开发环境硬编码，生产环境请用 env_file
```

---

## 4. AI Agent 实施细节 (Python)

### 4.1 核心依赖 (`requirements.txt`)

```text
livekit-agents>=0.8.0
sherpa-onnx>=1.10.0
openai>=1.0.0          # 用于兼容所有 OpenAI 协议的大模型
websockets>=12.0       # 用于连接火山引擎 TTS
numpy
soxr>=0.3.0            # 用于高质量音频重采样

```

### 4.2 本地 ASR 模块 (Sherpa-onnx)

需预先下载模型文件至 `agent/models/`：

- `tokens.txt`, `encoder.onnx`, `decoder.onnx`, `joiner.onnx`
- **模型来源**: huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en

**代码集成范式**:
该模块需封装为一个 Async Generator，将 LiveKit 的 `AudioFrame` 转换为文本流。

```python
# 伪代码：ASR 封装
class LocalASR:
    def __init__(self):
        self.recognizer = sherpa_onnx.OnlineRecognizer(...) # 配置 CPU 线程数

    async def process_audio_stream(self, audio_stream):
        async for frame in audio_stream:
            # 转换 frame.data (int16) -> float32
            # 喂给 recognizer
            if is_endpoint:
                yield text

```

### 4.3 外部 API 配置

- **LLM (通用配置)**:
- **Base URL**: 可配置，默认 `https://api.deepseek.com` (支持 DeepSeek, OpenAI, Qwen 等)。
- **Model**: 可配置，默认 `deepseek-chat`。
- **配置方式**: 通过环境变量 `LLM_BASE_URL` 和 `LLM_MODEL` 设置。
- **Client**: 使用 `openai.AsyncOpenAI` 客户端初始化。

- **TTS (Volcengine)**:
- 协议: WebSocket (V1 Binary Protocol)。
- 逻辑: 接收 LLM 的文本 -> 构建二进制 Header -> Gzip 压缩 Payload -> 发送 WS 请求 -> 接收并解析二进制音频数据包 -> 封装为 LiveKit `AudioFrame`。

---

## 5. 客户端实施细节 (Tauri + React)

### 5.1 依赖安装

```bash
npm install livekit-client @livekit/components-react @livekit/components-styles
npm install lucide-react # 图标库
npm run tauri plugin add keepawake # 添加保活插件

```

### 5.2 React 核心逻辑 (`App.tsx`)

使用 `LiveKitRoom` 组件包裹应用。

```tsx
import {
  LiveKitRoom,
  RoomAudioRenderer,
  VoiceVisualizer,
} from "@livekit/components-react";

export default function App() {
  // 使用 Keepawake 保持通话连接
  // App 切入后台时保持连接状态，支持后台语音通话

  return (
    <LiveKitRoom
      serverUrl={ws_url}
      token={token}
      connect={true}
      data-lk-theme="default"
    >
      <div className="visualizer-container">
        {/* 自定义波形展示区域 */}
        <VoiceVisualizer />
      </div>
      <RoomAudioRenderer /> {/* 负责播放声音 */}
      <Controls /> {/* 麦克风开关/断开按钮 */}
    </LiveKitRoom>
  );
}
```

### 5.3 Tauri 权限配置

#### Android (`src-tauri/gen/android/app/src/main/AndroidManifest.xml`)

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />

```

#### iOS (`src-tauri/gen/apple/App/Info.plist`)

```xml
<key>NSMicrophoneUsageDescription</key>
<string>我们需要麦克风权限来进行语音对话</string>

```

#### Rust 主进程 (`src-tauri/src/lib.rs`)

初始化 `keepawake` 插件，防止通话中屏幕自动休眠。

```rust
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_keepawake::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

```

---

## 6. 数据交互与接口定义

### 6.1 Token 生成接口

为了安全，Tauri 客户端**不能**在本地生成 Token。你需要一个轻量级的 HTTP 接口（可以用 Python Agent 顺便提供，或使用 Next.js/Go）。

- **Endpoint**: `POST /api/token`
- **Request**: `{ "roomName": "room-01", "participantName": "user-01" }`
- **Response**: `{ "token": "eyJhbGciOiJIUz..." }`

### 6.2 Agent 状态同步 (Data Channel)

Agent 通过 LiveKit 的 Data Channel 向前端发送状态，用于 UI 动效。

- **Topic**: `agent_status`
- **Payload (JSON)**:
- `{"state": "listening"}`: 正在听 (波形静止等待)
- `{"state": "thinking"}`: 正在推理 (显示加载动画)
- `{"state": "speaking"}`: 正在说话 (波形跳动)

---

## 7. 构建与部署流程

### 7.1 本地联调

1. 启动 Docker: `docker-compose up -d`
2. 启动 Agent: `python agent/main.py dev`
3. 启动 React: `npm run tauri dev`

### 7.2 生产构建

- **App 构建**:
- Desktop: `npm run tauri build`
- Android: `npm run tauri android build --apk`
- iOS: `npm run tauri ios build` (需在 Xcode 中 Archive)

- **Server 部署**:
- 将 `server/` 和 `agent/` 上传至云服务器。
- 确保服务器防火墙开放了 50000-50200 端口。
