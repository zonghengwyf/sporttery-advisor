"""多模型 LLM 统一客户端

支持：Claude、OpenAI、Gemini、DeepSeek、Kimi、GLM、自定义中转站
DeepSeek/Kimi/GLM 均提供 OpenAI 兼容 API，统一用 openai_compat 模式。
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import anthropic
import httpx
from openai import AsyncOpenAI


PROVIDER_DEFAULTS: dict[str, dict] = {
    "claude":   {"base_url": "https://api.anthropic.com", "sdk": "anthropic"},
    "openai":   {"base_url": "https://api.openai.com/v1", "sdk": "openai_compat"},
    "gemini":   {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "sdk": "openai_compat"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "sdk": "openai_compat"},
    "kimi":     {"base_url": "https://api.moonshot.cn/v1", "sdk": "openai_compat"},
    "glm":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "sdk": "openai_compat"},
    "custom":   {"base_url": None, "sdk": "openai_compat"},  # 用户填写 base_url
}


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None = None


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        defaults = PROVIDER_DEFAULTS.get(config.provider, PROVIDER_DEFAULTS["custom"])
        self.sdk = defaults["sdk"]
        self.base_url = config.base_url or defaults["base_url"]

    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> str:
        if self.sdk == "anthropic":
            return await self._anthropic_chat(messages, system, max_tokens, **kwargs)
        return await self._openai_chat(messages, system, max_tokens, **kwargs)

    async def chat_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        if self.sdk == "anthropic":
            async for chunk in self._anthropic_stream(messages, system, max_tokens, **kwargs):
                yield chunk
        else:
            async for chunk in self._openai_stream(messages, system, max_tokens, **kwargs):
                yield chunk

    # ── Anthropic ────────────────────────────────────────────────────────────

    async def _anthropic_chat(
        self, messages: list[dict], system: str | None, max_tokens: int, **kwargs: Any
    ) -> str:
        client = anthropic.AsyncAnthropic(api_key=self.config.api_key)
        params: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": messages,
            **kwargs,
        }
        if system:
            params["system"] = system
        response = await client.messages.create(**params)
        return response.content[0].text

    async def _anthropic_stream(
        self, messages: list[dict], system: str | None, max_tokens: int, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        client = anthropic.AsyncAnthropic(api_key=self.config.api_key)
        params: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": messages,
            **kwargs,
        }
        if system:
            params["system"] = system
        async with client.messages.stream(**params) as stream:
            async for text in stream.text_stream:
                yield text

    # ── OpenAI compatible (GPT / DeepSeek / Kimi / GLM / Gemini / custom) ───

    async def _openai_chat(
        self, messages: list[dict], system: str | None, max_tokens: int, **kwargs: Any
    ) -> str:
        client = AsyncOpenAI(api_key=self.config.api_key, base_url=self.base_url)
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        response = await client.chat.completions.create(
            model=self.config.model,
            messages=full_messages,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    async def _openai_stream(
        self, messages: list[dict], system: str | None, max_tokens: int, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        client = AsyncOpenAI(api_key=self.config.api_key, base_url=self.base_url)
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        stream = await client.chat.completions.create(
            model=self.config.model,
            messages=full_messages,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    # ── Connection test ───────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        try:
            result = await self.chat(
                messages=[{"role": "user", "content": "回复 ok"}],
                max_tokens=10,
            )
            return {"ok": True, "response": result}
        except Exception as e:
            return {"ok": False, "error": str(e)}
