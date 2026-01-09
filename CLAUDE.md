# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MiniH LiveKit is a low-cost, cross-platform, low-latency AI real-time voice interaction system. It uses a **hybrid architecture**: local CPU-based ASR (Sherpa-onnx) for speech recognition and cloud-based LLM/TTS for intelligence, achieving GPT-4o-like real-time voice conversations at minimal cost.

**Architecture**: Client (Tauri v2 + React) ↔ LiveKit Server (WebRTC SFU) ↔ AI Agent (Python)

## Common Development Commands

### Server (LiveKit)
```bash
cd server
docker compose up -d        # Start LiveKit server
docker compose down         # Stop server
docker compose logs -f      # View logs
```

### Agent (Python AI Backend)
```bash
cd agent
uv sync                     # Install dependencies
uv run main.py dev          # Start in development mode (includes token server)
uv run main.py token-server # Run only token server
uv run pytest               # Run tests (if added)
```

**Important**: First-time setup requires downloading ASR model files to `agent/src/models/`. See `docs/tech-stack.md` for model download instructions (Sherpa-onnx Paraformer streaming model from HuggingFace).

### Client (Tauri + React)
```bash
cd app
npm install                 # Install dependencies
npm run dev                 # Start web development server (port 3000)
npm run build               # Build web assets
npm run lint                # Run ESLint

# Tauri Desktop
npm run tauri dev           # Start desktop app in dev mode
npm run tauri build         # Build desktop app for production

# Mobile (requires platform-specific tooling)
npm run tauri android dev   # Android development
npm run tauri ios dev       # iOS development (macOS only)
```

## Architecture and Code Structure

### High-Level Architecture

The system follows a **Client-Server-Agent** pattern with LiveKit as the WebRTC infrastructure:

1. **Client Layer** (`app/`): Tauri v2 wrapper around React frontend
   - Uses `livekit-client` and `@livekit/components-react` for WebRTC
   - Obtains room token from Agent's HTTP token server
   - Sends audio via WebRTC, receives AI audio responses and data channel messages (transcripts)

2. **Infrastructure Layer** (`server/`): LiveKit Server (Docker)
   - WebRTC SFU (Selective Forwarding Unit) for media routing
   - Runs on port 7880 (WebSocket), UDP ports 51000-51200 (RTC media)
   - API Key: `devkey` (dev environment, configured in `livekit.yaml`)

3. **Agent Layer** (`agent/`): Python AI processing pipeline
   - Connects to LiveKit as a worker using `livekit-agents` SDK
   - Implements **AgentSession** architecture with standard plugin interfaces
   - Runs HTTP token server on port 8080 (in `dev` mode)

### Agent Pipeline (Critical Flow)

The AI agent uses a streaming pipeline implemented via **livekit-agents AgentSession**:

```
Audio Input → VAD (Silero) → STT (Sherpa-onnx) → LLM (Qwen/DeepSeek) → TTS (Volcengine) → Audio Output
```

**Key Components** (`agent/src/`):

- **`core/agent_impl.py`**: Main entrypoint and session management
  - `entrypoint()`: JobContext handler that creates AgentSession
  - Wraps plugins with interceptors for database and data channel integration
  - Manages session lifecycle (recording, chat history, data channel messaging)

- **`plugins/`**: Custom implementations of livekit-agents interfaces
  - `vad.py`: LocalVAD wrapper around Silero (used during initial implementation)
  - `stt.py`: LocalSTT - Sherpa-onnx streaming ASR (CPU-based, no GPU needed)
  - `llm.py`: DashscopeLLM - OpenAI-compatible LLM client (supports Qwen, DeepSeek, etc.)
  - `tts.py`: VolcengineTTS - Volcengine (Doubao) WebSocket V1 binary protocol TTS

- **`services/`**: Supporting services
  - `token_server.py`: HTTP server for generating LiveKit room tokens
  - `recorder.py`: Dual-channel WAV recording (user left, AI right)
  - `database.py`: SQLite chat history persistence
  - `asr.py`, `llm.py`, `tts.py`, `vad.py`: Legacy service implementations (kept for reference)

- **`models/`**: Sherpa-onnx ONNX model files (not in git, download separately)
  - Required files: `tokens.txt`, `encoder.onnx`, `decoder.onnx`, `joiner.onnx`
  - Model: Paraformer-bilingual-zh-en streaming

### Client Architecture (`app/`)

- **`src/`**: React source code
  - Uses `LiveKitRoom` component as root wrapper
  - Custom UI components with "Cyber-Teal" design theme
  - Data channel listener for real-time transcript display

- **`src-tauri/`**: Rust native layer
  - `src/lib.rs`: Tauri plugin initialization (keepawake for mobile)
  - `capabilities/`: Permission configurations
  - `gen/android/`, `gen/apple/`: Generated mobile projects (Android/iOS)
  - `tauri.conf.json`: App configuration (window size, bundle settings, CSP)

### Environment Configuration

All services use `.env` files for configuration:

**Agent** (`agent/.env`):
```env
# LiveKit Connection
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret_minih_livekit_2026_secure_key

# LLM (OpenAI-compatible)
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  # or DeepSeek, OpenAI
LLM_API_KEY=your_api_key
LLM_MODEL=qwen3-max  # or deepseek-chat, gpt-4, etc.

# TTS
VOLCENGINE_APP_ID=your_app_id
VOLCENGINE_ACCESS_TOKEN=your_token

# Optional
AGENT_NAME=minih-dev-worker  # Must match token server configuration
TOKEN_SERVER_PORT=8080
```

**Client** connects to token server at `http://localhost:8080/token` (hardcoded in dev mode)

## Key Technical Patterns

### 1. AgentSession Integration
The agent uses `livekit-agents` AgentSession framework (v1.3.10+). When modifying the agent:
- Plugins must implement standard interfaces: `stt.STT`, `llm.LLM`, `tts.TTS`, `vad.VAD`
- Use `AgentSession.start()` to run the pipeline (auto-managed by framework)
- Interceptor pattern (e.g., `InterceptedSTT`) wraps plugins to inject side effects (DB writes, data channel messages)

### 2. Data Channel Communication
Agent sends real-time updates to client via LiveKit data channel:
- **Transcripts**: JSON with `{type: "transcript", participant: "user"|"assistant", text: "...", is_final: true|false}`
- Published in `InterceptedSTT` and `InterceptedLLMStream`
- Client receives via `room.on("dataReceived")` event

### 3. Audio Recording
Dual-channel recording implemented in `AudioRecorder`:
- Left channel: User audio (from participant track)
- Right channel: AI audio (from TTS synthesis)
- Saves to `recordings/{session_id}.wav` on session end
- Uses `scipy.io.wavfile` for WAV writing

### 4. Chat History
SQLite database (`data/chat_history.db`):
- Schema: `sessions` (session metadata) and `messages` (chat messages)
- Each session has UUID, created via `ChatDatabase.create_session()`
- Messages added in real-time during STT final transcripts and LLM responses

## Important Development Notes

### ASR Model Setup
First-time developers must download Sherpa-onnx models manually:
- Model source: `huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en`
- Extract to `agent/src/models/` (files: `tokens.txt`, `encoder.onnx`, `decoder.onnx`, `joiner.onnx`)
- Without models, agent will fail at startup with file not found error

### Python Version
- Requires Python 3.10-3.13 (tested on 3.13.5)
- Use `uv` for dependency management (faster than pip/poetry)
- Sherpa-onnx has binary wheels for most platforms, no compilation needed

### Mobile Development
- **iOS**: Requires macOS + Xcode 15+. Build via `npm run tauri ios build`, then archive in Xcode
- **Android**: Requires Android Studio, NDK, JDK 17, and `JAVA_HOME`/`ANDROID_HOME` env vars
- Permissions configured in:
  - Android: `app/src-tauri/gen/android/app/src/main/AndroidManifest.xml`
  - iOS: `app/src-tauri/gen/apple/App/Info.plist` (or `Info.ios.plist`)
- Keepawake plugin prevents screen sleep during calls

### LiveKit Server Ports
If changing from default ports, update in three places:
1. `server/livekit.yaml`: `port` (WebSocket) and `rtc.port_range_start/end` (UDP/TCP)
2. `server/docker-compose.yaml`: Port mappings
3. `agent/.env`: `LIVEKIT_URL`

### Debugging Agent Issues
- Agent logs to console with structured logging (module prefix: `agent`, `services`, `core`)
- Third-party logs (livekit, asyncio) silenced in `main.py` (levels set to ERROR)
- To debug WebRTC issues, temporarily set `logging.getLogger("livekit").setLevel(logging.DEBUG)` in `main.py`

## Project Status

Currently in **Phase 6** (Agent Session integration complete). Recent work:
- ✅ Core pipeline (ASR → LLM → TTS) verified
- ✅ Desktop app (Tauri) with system tray
- ✅ Dual-channel recording
- ✅ Real-time transcripts via data channel
- ✅ AgentSession standardized architecture
- ✅ iOS build configuration (Android skipped)
- 🚧 Mobile UX optimization ongoing

## Reference Documentation

The `docs/` directory contains detailed design docs:
- `design.md`: System architecture and component design
- `tech-stack.md`: Technology stack details and setup instructions
- `architecture.md`: Directory structure and file descriptions
- `progress.md`: Development progress tracking
- `implementation_plan.md`: Original implementation roadmap

Always consult these docs for detailed context before making architectural changes.
