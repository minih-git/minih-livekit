/**
 * AI 实时语音交互客户端主界面
 * 使用 LiveKit 组件实现房间连接和音频通话
 */

import { useState, useCallback, useEffect } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useTracks,
  useLocalParticipant,
  BarVisualizer,
  useDataChannel,
} from "@livekit/components-react";
import { Track } from "livekit-client";
import {
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  Loader2,
  History,
  X,
} from "lucide-react";
import { fetchToken, generateParticipantId } from "./api/token";
import { start, stop } from "tauri-plugin-keepawake-api";
import "./App.css";

// LiveKit 服务器地址
const LIVEKIT_URL = import.meta.env.PUBLIC_LIVEKIT_URL || "ws://localhost:7880";

/**
 * 字幕条目类型定义
 */
interface TranscriptItem {
  id: string;
  participant: "user" | "agent";
  text: string;
  isFinal: boolean;
  timestamp: number;
}

/**
 * 历史会话类型
 */
interface HistorySession {
  id: string;
  room_name: string;
  started_at: string;
  ended_at: string | null;
  message_count: number;
}

interface HistoryMessage {
  role: "user" | "agent";
  content: string;
  created_at: string;
}

// API 基础地址
const API_BASE =
  import.meta.env.PUBLIC_TOKEN_SERVER_URL || "http://localhost:8080";

/**
 * 历史记录模态框组件
 */
function HistoryModal({ onClose }: { onClose: () => void }) {
  const [sessions, setSessions] = useState<HistorySession[]>([]);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [loading, setLoading] = useState(true);

  // 加载会话列表
  useEffect(() => {
    fetch(`${API_BASE}/api/history`)
      .then((res) => res.json())
      .then((data) => {
        setSessions(data.sessions || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  // 加载会话消息
  const loadSession = async (sessionId: string) => {
    setSelectedSession(sessionId);
    const res = await fetch(`${API_BASE}/api/history/${sessionId}`);
    const data = await res.json();
    setMessages(data.messages || []);
  };

  return (
    <div className="history-modal-overlay" onClick={onClose}>
      <div className="history-modal" onClick={(e) => e.stopPropagation()}>
        <div className="history-modal-header">
          <h2>📝 对话历史</h2>
          <button className="history-close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="history-modal-content">
          {/* 左侧会话列表 */}
          <div className="history-sessions">
            {loading ? (
              <div className="history-loading">加载中...</div>
            ) : sessions.length === 0 ? (
              <div className="history-empty">暂无历史记录</div>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.id}
                  className={`history-session-item ${
                    selectedSession === s.id ? "active" : ""
                  }`}
                  onClick={() => loadSession(s.id)}
                >
                  <div className="session-time">
                    {new Date(s.started_at).toLocaleString("zh-CN")}
                  </div>
                  <div className="session-info">{s.message_count} 条消息</div>
                </div>
              ))
            )}
          </div>

          {/* 右侧消息列表 */}
          <div className="history-messages">
            {!selectedSession ? (
              <div className="history-empty">选择左侧会话查看详情</div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={`history-message ${m.role}`}>
                  <span className="history-role">
                    {m.role === "user" ? "你" : "AI"}
                  </span>
                  <span className="history-text">{m.content}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 连接控制面板组件
 */
function ControlBar({
  isConnected,
  isMuted,
  onToggleMute,
  onDisconnect,
}: {
  isConnected: boolean;
  isMuted: boolean;
  onToggleMute: () => void;
  onDisconnect: () => void;
}) {
  return (
    <div className="control-bar">
      <button
        className={`control-btn ${isMuted ? "muted" : ""}`}
        onClick={onToggleMute}
        disabled={!isConnected}
        title={isMuted ? "取消静音" : "静音"}
      >
        {isMuted ? <MicOff size={24} /> : <Mic size={24} />}
      </button>

      <button
        className="control-btn disconnect"
        onClick={onDisconnect}
        disabled={!isConnected}
        title="挂断"
      >
        <PhoneOff size={24} />
      </button>
    </div>
  );
}

/**
 * 简单的回铃音生成器 (使用 Web Audio API)
 */
class RingbackTone {
  private ctx: AudioContext | null = null;
  private osc: OscillatorNode | null = null;
  private gain: GainNode | null = null;
  private isPlaying: boolean = false;

  constructor() {
    try {
      // @ts-ignore - for Safari support
      const AudioContextClass =
        window.AudioContext || (window as any).webkitAudioContext;
      this.ctx = new AudioContextClass();
    } catch (e) {
      console.error("Web Audio API not supported", e);
    }
  }

  start() {
    if (!this.ctx || this.isPlaying) return;

    // 恢复 AudioContext (解决浏览器自动播放策略限制)
    if (this.ctx.state === "suspended") {
      this.ctx.resume();
    }

    this.isPlaying = true;
    this.playTone();
  }

  stop() {
    this.isPlaying = false;
    if (this.osc) {
      try {
        this.osc.stop();
        this.osc.disconnect();
      } catch (e) {
        /* ignore */
      }
      this.osc = null;
    }
    if (this.gain) {
      try {
        this.gain.disconnect();
      } catch (e) {
        /* ignore */
      }
      this.gain = null;
    }
  }

  private playTone() {
    if (!this.ctx || !this.isPlaying) return;

    // 创建振荡器和增益节点
    const t0 = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = "sine";
    osc.frequency.value = 440; // A4 - 标准音
    // 双频效果模拟电话铃声 (440Hz + 480Hz 是标准，这里简化用单频或者调制)

    // 配置增益包络: 嘟... (1秒) ... 停 (2秒)
    gain.connect(this.ctx.destination);
    osc.connect(gain);

    // 声音渐入渐出
    gain.gain.setValueAtTime(0, t0);
    gain.gain.linearRampToValueAtTime(0.1, t0 + 0.1);
    gain.gain.linearRampToValueAtTime(0.1, t0 + 1.0);
    gain.gain.linearRampToValueAtTime(0, t0 + 1.2);

    osc.start(t0);
    osc.stop(t0 + 1.2);

    this.osc = osc;
    this.gain = gain;

    // 循环: 3秒后再次播放
    setTimeout(() => {
      if (this.isPlaying) {
        this.playTone();
      }
    }, 3000);
  }
}

/**
 * 已连接房间内的界面
 */
function ConnectedRoom({ onDisconnect }: { onDisconnect: () => void }) {
  const [isMuted, setIsMuted] = useState(false);
  const [agentReady, setAgentReady] = useState(false);
  const [transcripts, setTranscripts] = useState<TranscriptItem[]>([]);
  const { localParticipant } = useLocalParticipant();
  const tracks = useTracks([Track.Source.Microphone]);

  const localTrack = tracks.find((tr) => tr.participant.isLocal);
  const agentTrack = tracks.find((tr) => !tr.participant.isLocal);
  const agentParticipant = agentTrack?.participant;

  // 监听 Agent 的 DataChannel 消息
  const { message } = useDataChannel();

  // 管理回铃音
  useEffect(() => {
    // 如果已经连接但 AI 还未就绪，播放铃声
    const ringback = new RingbackTone();

    if (!agentReady) {
      console.log("正在呼叫 AI...");
      ringback.start();
    }

    return () => {
      ringback.stop();
    };
  }, [agentReady]);

  useEffect(() => {
    if (message) {
      try {
        const data = JSON.parse(new TextDecoder().decode(message.payload));

        if (data.type === "agent_ready") {
          console.log("Agent 已就绪:", data.message);
          setAgentReady(true);
        } else if (data.type === "transcript") {
          // 处理字幕消息
          const newItem: TranscriptItem = {
            id: `${data.participant}-${data.timestamp}`,
            participant: data.participant,
            text: data.text,
            isFinal: data.is_final,
            timestamp: data.timestamp,
          };

          setTranscripts((prev) => {
            // 如果是同一来源的 Partial 更新，替换最后一条；否则添加新条目
            const lastItem = prev[prev.length - 1];
            if (
              lastItem &&
              lastItem.participant === newItem.participant &&
              !lastItem.isFinal
            ) {
              // 更新最后一条 Partial
              return [...prev.slice(0, -1), newItem];
            } else if (
              newItem.isFinal &&
              lastItem?.participant === newItem.participant &&
              !lastItem.isFinal
            ) {
              // Final 替换 Partial
              return [...prev.slice(0, -1), newItem];
            }
            return [...prev, newItem];
          });
        }
      } catch (e) {
        // 非 JSON 消息，忽略
      }
    }
  }, [message]);

  const handleToggleMute = useCallback(() => {
    setIsMuted((prev) => !prev);
    if (localParticipant) {
      localParticipant.setMicrophoneEnabled(!isMuted);
    }
  }, [isMuted, localParticipant]);

  // Enable Keepawake when in room
  useEffect(() => {
    const initKeepAwake = async () => {
      try {
        await start();
        console.log("Keepawake enabled");
      } catch (e) {
        console.warn("Failed to enable keepawake (not in Tauri?)", e);
      }
    };

    initKeepAwake();

    return () => {
      stop().catch(() => {});
    };
  }, []);

  return (
    <div className="connected-room">
      <div className="call-panel">
        <div className="ai-avatar-container">
          <div className={`ai-avatar ${agentTrack ? "active" : ""}`}>
            <div className="avatar-circle">
              <span className="avatar-icon">🤖</span>
            </div>

            <div className="visualizer-agent">
              {agentTrack && (
                <BarVisualizer
                  barCount={7}
                  trackRef={agentTrack}
                  className="agent-viz-bars"
                  style={{ height: "30px", gap: "4px" }}
                />
              )}
            </div>

            <p className="avatar-label">
              {agentParticipant?.identity || "用户"}
            </p>

            {!agentReady && (
              <div className="agent-loading">
                <Loader2 className="spinner" size={16} />
                <span>AI 正在准备中...</span>
              </div>
            )}
          </div>
        </div>

        <div className="user-section">
          <div className="visualizer-user">
            {localTrack && (
              <BarVisualizer
                barCount={20}
                trackRef={localTrack}
                className="user-viz-bars"
                style={{ height: "20px" }}
              />
            )}
          </div>

          <ControlBar
            isConnected={true}
            isMuted={isMuted}
            onToggleMute={handleToggleMute}
            onDisconnect={onDisconnect}
          />
        </div>
      </div>

      <div className="transcript-panel">
        <div className="transcript-header">💬 实时对话</div>
        <div className="transcript-list">
          {transcripts.map((item) => (
            <div
              key={item.id}
              className={`transcript-item ${item.participant} ${
                item.isFinal ? "final" : "partial"
              }`}
            >
              <span className="transcript-text">{item.text}</span>
            </div>
          ))}
        </div>
      </div>

      <RoomAudioRenderer />
    </div>
  );
}

/**
 * 主应用组件
 */
function App() {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [participantName] = useState(() => generateParticipantId("user"));
  const [roomName] = useState(() => generateParticipantId("room"));
  const [showHistory, setShowHistory] = useState(false);

  // 连接房间
  const handleConnect = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const newToken = await fetchToken(roomName, participantName);
      setToken(newToken);
    } catch (err) {
      setError(err instanceof Error ? err.message : "连接失败");
    } finally {
      setIsLoading(false);
    }
  }, [participantName]);

  // 断开连接
  const handleDisconnect = useCallback(() => {
    setToken(null);
  }, []);

  // 未连接状态
  if (!token) {
    return (
      <div className="app">
        <div className="app-container">
          <header className="app-header">
            <h1>🎙️ AI 语音助手</h1>
            <p>实时语音交互体验</p>
          </header>

          <div className="connect-section">
            {error && <div className="error-message">{error}</div>}

            <button
              className="connect-btn"
              onClick={handleConnect}
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <Loader2 className="spinner" size={20} />
                  连接中...
                </>
              ) : (
                <>
                  <Phone size={20} />
                  开始通话
                </>
              )}
            </button>

            <p className="hint-text">点击按钮连接 AI 语音助手</p>

            <button
              className="history-btn"
              onClick={() => setShowHistory(true)}
            >
              <History size={24} />
            </button>
          </div>

          <footer className="app-footer">
            <p>
              房间: {roomName} | 用户: {participantName}
            </p>
          </footer>
        </div>

        {showHistory && <HistoryModal onClose={() => setShowHistory(false)} />}
      </div>
    );
  }

  // 已连接状态
  return (
    <div className="app">
      <div className="app-container wide">
        <LiveKitRoom
          serverUrl={LIVEKIT_URL}
          token={token}
          connect={true}
          audio={{
            deviceId: "default", // 可选
            noiseSuppression: true, // 开启降噪
            echoCancellation: true, // 开启回声消除
            autoGainControl: true, // 开启自动增益
          }}
          video={false}
          onDisconnected={handleDisconnect}
        >
          <header className="app-header connected">
            <h1>🎙️ AI 语音助手</h1>
            <p>正在与 AI 对话</p>
          </header>

          <ConnectedRoom onDisconnect={handleDisconnect} />

          <footer className="app-footer">
            <p>
              房间: {roomName} | 用户: {participantName}
            </p>
          </footer>
        </LiveKitRoom>
      </div>
    </div>
  );
}

export default App;
