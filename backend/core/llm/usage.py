"""LLM 调用用量/状态回写

更新 LLMConfig 的累计调用次数、token 消耗与最近状态。
任何失败只记日志，永不阻断分析主流程。
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def record_llm_usage(
    config_id: int | None,
    usage: dict | None = None,
    error: str | None = None,
) -> None:
    """回写一次 LLM 调用的用量与状态。config_id 为空（env 配置）时跳过。"""
    if not config_id:
        return
    try:
        from sqlalchemy import select

        from db.models import LLMConfig
        from db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(LLMConfig).where(LLMConfig.id == config_id)
            )
            cfg = result.scalar_one_or_none()
            if not cfg:
                return
            cfg.total_calls = (cfg.total_calls or 0) + 1
            if usage:
                cfg.total_prompt_tokens = (cfg.total_prompt_tokens or 0) + int(
                    usage.get("prompt_tokens") or 0
                )
                cfg.total_completion_tokens = (cfg.total_completion_tokens or 0) + int(
                    usage.get("completion_tokens") or 0
                )
            cfg.last_used_at = datetime.utcnow()
            if error:
                cfg.status = "error"
                cfg.last_error = str(error)[:500]
            else:
                cfg.status = "ok"
                cfg.last_error = None
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("记录 LLM 用量失败 config_id=%s: %s", config_id, exc)
