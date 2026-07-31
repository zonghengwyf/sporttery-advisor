# ADR-003: 多模型 OpenAI 兼容适配层

**状态：** 已采用
**日期：** 2026-07-25

## 决策

所有 LLM 调用通过 `backend/core/llm/client.py` 的统一客户端封装。Claude 使用 Anthropic SDK，其他所有模型（GPT、Gemini、DeepSeek、Kimi、GLM、自定义中转）统一用 `openai` SDK 配合 `base_url + api_key` 调用。

## 背景

中国主流模型（DeepSeek、Kimi、GLM）均提供 OpenAI 兼容 API，三方中转站同理。每个模型单独实现 SDK 调用会产生大量重复代码，且用户添加新模型时需修改后端。统一用 `openai` SDK + `base_url` 切换，新增模型只需在设置页配置，无需改代码。

Claude 因使用专有 SDK（`anthropic`）单独处理，但对外暴露相同接口。

## 后果

- `LLMConfig.provider` 枚举：`claude | openai | gemini | deepseek | kimi | glm | custom`
- `provider=claude` 走 `anthropic.AsyncAnthropic`；其余走 `openai.AsyncOpenAI(base_url=..., api_key=...)`
- 用户在设置页配置 `base_url`（中转站时必填）和 `api_key`，前端存入 `llm_configs` 表
- 新增 OpenAI 兼容模型：设置页选 `custom`，填入 `base_url` 即可，**无需改后端代码**
- SSE 流式输出：Claude 用 `stream=True` 的 `MessageStream`，其余用 `openai` 的 `stream=True`，统一 yield `str` chunk
