"""
LLM 调用模块 - 使用 DeepSeek API（OpenAI 兼容接口）
支持流式对话
"""

import logging
import os
from typing import AsyncIterator
from openai import AsyncOpenAI

logger = logging.getLogger("agent")


class LLMClient:
    """LLM 客户端，使用 DeepSeek V3 API"""

    # 系统提示词
    DEFAULT_SYSTEM_PROMPT = """你是一个友好的 AI 语音助手。
请用简洁、口语化的方式回复用户。
回复应该简短（通常 1-3 句话），适合语音播放。
避免使用 markdown 格式、代码块或复杂的格式化。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        """
        初始化 LLM 客户端

        Args:
            api_key: API Key，默认从环境变量 LLM_API_KEY 获取
            base_url: API 基础 URL，默认从环境变量 LLM_BASE_URL 获取
            model: 使用的模型名称，默认从环境变量 LLM_MODEL 获取
        """
        self.api_key = api_key or os.environ.get("LLM_API_KEY")
        if not self.api_key:
            raise ValueError("LLM_API_KEY 环境变量未设置")

        # 从环境变量读取 base_url，默认使用 DeepSeek
        self.base_url = base_url or os.environ.get(
            "LLM_BASE_URL", "https://api.deepseek.com"
        )
        # 从环境变量读取 model
        self.model = model or os.environ.get("LLM_MODEL", "deepseek-chat")

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        self.system_prompt = self.DEFAULT_SYSTEM_PROMPT
        self.conversation_history: list[dict] = []

        logger.info(f"LLM 客户端初始化: base_url={self.base_url}, model={self.model}")

    def reset_conversation(self):
        """重置对话历史"""
        self.conversation_history = []

    async def chat_stream(self, user_text: str) -> AsyncIterator[str]:
        """
        流式对话，返回文本块异步迭代器

        Args:
            user_text: 用户输入的文本

        Yields:
            LLM 生成的文本块
        """
        # 添加用户消息到历史
        self.conversation_history.append(
            {
                "role": "user",
                "content": user_text,
            }
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            *self.conversation_history,
        ]

        logger.info(f"开始调用 LLM,model:{self.model}")
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            max_tokens=256,  # 语音场景限制回复长度
            temperature=0.7,
        )

        full_response = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full_response += text
                yield text

        # 添加助手回复到历史
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": full_response,
            }
        )

        # 限制历史长度，防止 token 溢出
        if len(self.conversation_history) > 10:
            self.conversation_history = self.conversation_history[-10:]
