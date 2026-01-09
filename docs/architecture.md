# minih-livekit 架构文档

> 本文档记录项目的目录结构和各文件的作用，随开发进度持续更新。

---

## 项目结构概览

```text
minih-livekit/
├── docs/                           # 项目文档
│   ├── design.md                   # 系统设计文档：架构图、技术选型、模块设计
│   ├── tech-stack.md               # 技术栈详解：依赖配置、代码示例、部署流程
│   ├── implementation_plan.md      # 详细实施计划：分阶段步骤 + 验证测试
│   ├── progress.md                 # 进度记录：已完成步骤的验证结果
│   └── architecture.md             # 本文档：目录结构和文件作用说明
├── server/                         # ✅ LiveKit 服务端配置
│   ├── docker-compose.yaml         # Docker Compose 编排：端口映射、卷挂载、健康检查
│   └── livekit.yaml                # LiveKit 配置：API 密钥、WebRTC 端口范围
├── agent/                          # ✅ Python AI Agent
│   ├── pyproject.toml              # uv 项目配置：依赖 + hatch 构建
│    └── src/                       # 主模块包
        ├── __init__.py             # 包入口：导出核心类
        ├── agent_impl.py           # ✅ 核心入口：组装 VoicePipelineAgent
        ├── core/                   # 核心逻辑 (即将移除)
        ├── services/               # 基础服务 (即将移除)
        ├── models/                 # ASR 模型文件
        ├── plugins/                # ✅ 自定义插件 (适配 LiveKit 接口)
        │   ├── local_vad.py        # VAD 适配器
        │   ├── local_stt.py        # STT 适配器 (Sherpa-onnx)
        │   ├── deepseek_llm.py     # LLM 适配器
        │   └── volcengine_tts.py   # TTS 适配器
        ├── recorder.py             # 录音模块
        └── token_server.py         # Token HTTP 服务器
└── app/                            # ✅ React 客户端 (Rsbuild + TypeScript)
    ├── package.json                # 依赖配置
    ├── rsbuild.config.ts           # Rsbuild 配置文件 (替代 vite.config.ts)
    │   ├── App.tsx                 # 主界面组件
    │   ├── App.css                 # 界面样式
    │   ├── index.tsx               # 入口文件 (原 main.tsx)
    │   ├── env.d.ts                # 类型定义
    │   ├── index.html              # HTML 模板
    │   └── index.css               # 全局样式
    └── package.json                # 依赖配置
```

---

## 文档说明

### `docs/design.md`

- **作用**：描述系统整体架构设计
- **内容**：Client-Server-Agent 架构图、技术栈选型表、模块详细设计、开发路线图
- **适用对象**：需要理解系统全局视角的开发者

### `docs/tech-stack.md`

- **作用**：技术实施指南
- **内容**：环境准备、目录结构、服务端配置、Agent 代码范式、客户端实现、接口定义
- **适用对象**：需要动手实现各模块的开发者

### `docs/implementation_plan.md`

- **作用**：逐步执行的详细计划
- **内容**：四个阶段（核心验证、桌面端、移动端、生产部署）的具体步骤和验证测试
- **适用对象**：AI 开发助手或需要按步骤执行的开发者

### `docs/progress.md`

- **作用**：记录实施进度
- **内容**：已完成步骤的验证结果、时间戳、备注
- **适用对象**：需要了解当前进度或接手项目的开发者

---

## 开发环境

基于步骤 1.1.1 验证结果：

| 工具           | 版本    | 用途                           |
| -------------- | ------- | ------------------------------ |
| Rust           | 1.92.0  | Tauri 后端编译                 |
| Node.js        | 24.11.1 | React 前端构建                 |
| Python         | 3.13.5  | AI Agent 运行时                |
| uv             | 0.9.17  | Python 包管理（替代 pip/venv） |
| Docker         | 28.5.1  | 容器化运行 LiveKit Server      |
| Docker Compose | 2.40.3  | 服务编排                       |
