"""多模型集成分析引擎

并发调用所有已配置 LLM，对每场比赛各给出 H/D/A 投票+置信度，
然后按多数票（或准确率加权）汇总为最终预测方向。

设计原则：
- Layer 1（统计）只跑一次，共享给所有模型
- Layer 2（LLM）并发跑，每个模型独立分析
- 记录每个模型的投票，供后续准确率分析
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EnsembleConfig:
    """集成分析配置，存于 DataSourceConfig source_name='ensemble'"""
    models: str = "all"          # "all" | "default" | 逗号分隔的 config_id 列表 "1,2,3"
    strategy: str = "majority"   # "majority" | "weighted"
    min_consensus: float = 0.5   # 最低共识比例（低于此则标记为不确定）
    min_confidence: int = 40     # 单模型置信度低于此直接跳过该模型投票
    default_multiplier: int = 2  # 默认投注倍数
    budget: float = 100.0        # 默认本金

    @classmethod
    def from_dict(cls, d: dict) -> "EnsembleConfig":
        return cls(
            models=d.get("models", "all"),
            strategy=d.get("strategy", "majority"),
            min_consensus=float(d.get("min_consensus", 0.5)),
            min_confidence=int(d.get("min_confidence", 40)),
            default_multiplier=int(d.get("default_multiplier", 2)),
            budget=float(d.get("budget", 100.0)),
        )

    def to_dict(self) -> dict:
        return {
            "models": self.models,
            "strategy": self.strategy,
            "min_consensus": self.min_consensus,
            "min_confidence": self.min_confidence,
            "default_multiplier": self.default_multiplier,
            "budget": self.budget,
        }


@dataclass
class ModelVote:
    """单个模型对一场比赛的投票结果"""
    model_name: str           # e.g. "deepseek-chat"
    provider: str             # e.g. "deepseek"
    llm_config_id: int        # 数据库 LLMConfig.id
    outcome: str              # "H" | "D" | "A"
    confidence: int           # 0-100
    risk_label: str           # mainline/guarded/upset_cover/avoid
    intel_summary: str = ""
    raw_result: dict = field(default_factory=dict)
    error: str = ""           # 非空表示该模型调用失败


@dataclass
class EnsembleResult:
    """集成汇总结果"""
    final_outcome: str        # 多数票最终方向 H/D/A
    consensus_ratio: float    # 同意最终方向的模型比例
    total_models: int
    votes: list[ModelVote]
    # 汇总 LLM 结果，供 Layer 3 使用
    aggregated_llm_result: dict
    is_confident: bool        # consensus_ratio >= min_consensus


class EnsembleAnalyzer:
    """多模型并发分析，汇总投票结果"""

    def __init__(self, pipeline):
        from core.pipeline import DailyPipeline
        self.pipeline: DailyPipeline = pipeline

    async def analyze_match_ensemble(
        self,
        session,
        match,
        llm_configs: list,  # list[db.models.LLMConfig]
        config: EnsembleConfig,
        stat_probs: dict,
        fused_probs: dict,
    ) -> EnsembleResult:
        """
        对一场比赛并发运行所有 LLM，返回投票汇总结果。
        stat_probs / fused_probs 由外部 Layer1 提供，复用不重复计算。
        """
        from core.llm.client import LLMClient
        from core.llm.client import LLMConfig as ClientCfg

        tasks = []
        for cfg in llm_configs:
            client = LLMClient(ClientCfg(
                provider=cfg.provider.value,
                model=cfg.model,
                api_key=cfg.api_key,
                base_url=cfg.base_url,
            ))
            tasks.append(self._run_single_model(match, fused_probs, client, cfg, config))

        raw_votes: list[ModelVote] = await asyncio.gather(*tasks)

        # 过滤掉调用失败的投票
        valid_votes = [v for v in raw_votes if not v.error and v.outcome]
        if not valid_votes:
            # 全部失败，返回统计模型的默认方向
            outcome = _outcome_from_probs(fused_probs)
            return EnsembleResult(
                final_outcome=outcome,
                consensus_ratio=0.0,
                total_models=len(raw_votes),
                votes=raw_votes,
                aggregated_llm_result=_default_llm_result(),
                is_confident=False,
            )

        final_outcome, consensus_ratio = _majority_vote(
            valid_votes, strategy=config.strategy
        )
        is_confident = consensus_ratio >= config.min_consensus

        aggregated = _aggregate_llm_results(valid_votes, final_outcome)

        return EnsembleResult(
            final_outcome=final_outcome,
            consensus_ratio=consensus_ratio,
            total_models=len(raw_votes),
            votes=raw_votes,
            aggregated_llm_result=aggregated,
            is_confident=is_confident,
        )

    async def _run_single_model(
        self,
        match,
        fused_probs: dict,
        client,
        cfg,
        config: EnsembleConfig,
    ) -> ModelVote:
        try:
            llm_result = await self.pipeline._layer2_llm(match, fused_probs, client)
            confidence = int(llm_result.get("confidence", 50))

            # 置信度不足时跳过此票
            if confidence < config.min_confidence:
                return ModelVote(
                    model_name=cfg.model, provider=cfg.provider.value,
                    llm_config_id=cfg.id,
                    outcome="", confidence=confidence,
                    risk_label=llm_result.get("risk_label", "guarded"),
                    error=f"置信度 {confidence} 低于阈值 {config.min_confidence}",
                    raw_result=llm_result,
                )

            outcome = _outcome_from_llm(llm_result, fused_probs)
            return ModelVote(
                model_name=cfg.model,
                provider=cfg.provider.value,
                llm_config_id=cfg.id,
                outcome=outcome,
                confidence=confidence,
                risk_label=llm_result.get("risk_label", "guarded"),
                intel_summary=llm_result.get("intel_summary", ""),
                raw_result=llm_result,
            )
        except Exception as exc:
            logger.warning("模型 %s/%s 分析失败：%s", cfg.provider, cfg.model, exc)
            return ModelVote(
                model_name=cfg.model, provider=cfg.provider.value,
                llm_config_id=cfg.id,
                outcome="", confidence=0,
                risk_label="guarded",
                error=str(exc),
            )


async def get_ensemble_config(session, user_id: int) -> EnsembleConfig:
    """从 DataSourceConfig 表读取集成配置，不存在则返回默认值。"""
    from sqlalchemy import select
    from db.models import DataSourceConfig

    result = await session.execute(
        select(DataSourceConfig).where(
            DataSourceConfig.user_id == user_id,
            DataSourceConfig.source_name == "ensemble",
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg and cfg.extra_config:
        return EnsembleConfig.from_dict(cfg.extra_config)
    return EnsembleConfig()


async def get_active_llm_configs(session, user_id: int, config: EnsembleConfig) -> list:
    """按集成配置选出参与本轮分析的 LLM 配置列表。"""
    from sqlalchemy import select
    from db.models import LLMConfig

    result = await session.execute(
        select(LLMConfig).where(LLMConfig.user_id == user_id)
    )
    all_configs = result.scalars().all()
    if not all_configs:
        return []

    if config.models == "all":
        return all_configs
    if config.models == "default":
        default = [c for c in all_configs if c.is_default]
        return default or [all_configs[0]]

    # 按 ID 列表过滤
    try:
        ids = {int(x) for x in str(config.models).split(",") if x.strip().isdigit()}
        return [c for c in all_configs if c.id in ids]
    except Exception:
        return all_configs


def votes_to_dict(votes: list[ModelVote]) -> list[dict]:
    return [
        {
            "model": v.model_name,
            "provider": v.provider,
            "config_id": v.llm_config_id,
            "outcome": v.outcome,
            "confidence": v.confidence,
            "risk_label": v.risk_label,
            "intel_summary": v.intel_summary,
            "error": v.error,
        }
        for v in votes
    ]


# ── 内部辅助 ─────────────────────────────────────────────────────────────────

def _outcome_from_probs(probs: dict) -> str:
    home = probs.get("home", 0.35)
    draw = probs.get("draw", 0.28)
    away = probs.get("away", 0.37)
    return ["H", "D", "A"][[home, draw, away].index(max(home, draw, away))]


def _outcome_from_llm(llm_result: dict, fused_probs: dict) -> str:
    """从 LLM 结果推断方向：优先看 conservative_pick，再看概率最大值。"""
    pick = (llm_result.get("conservative_pick") or {}).get("pick", "")
    if "主胜" in pick or pick == "3":
        return "H"
    if "客胜" in pick or pick == "0":
        return "A"
    if "平" in pick and "主胜" not in pick and "客胜" not in pick:
        return "D"
    return _outcome_from_probs(fused_probs)


def _majority_vote(
    votes: list[ModelVote], strategy: str = "majority"
) -> tuple[str, float]:
    """返回 (最终方向, 共识比例)。"""
    counts: dict[str, float] = {"H": 0.0, "D": 0.0, "A": 0.0}

    if strategy == "weighted":
        # 按置信度加权
        total_weight = sum(v.confidence for v in votes) or 1.0
        for v in votes:
            counts[v.outcome] = counts.get(v.outcome, 0) + v.confidence / total_weight
        winner = max(counts, key=counts.__getitem__)
        ratio = counts[winner]
    else:
        # 简单多数
        for v in votes:
            counts[v.outcome] = counts.get(v.outcome, 0) + 1
        total = len(votes)
        winner = max(counts, key=counts.__getitem__)
        ratio = counts[winner] / total

    return winner, round(ratio, 3)


def _aggregate_llm_results(votes: list[ModelVote], final_outcome: str) -> dict:
    """汇总多个模型的 LLM 分析，取共识方向的智能摘要。"""
    # 优先取与最终方向一致的、置信度最高的模型的详细结果
    aligned = [v for v in votes if v.outcome == final_outcome]
    best = max(aligned or votes, key=lambda v: v.confidence)
    result = dict(best.raw_result)

    # 汇总情报摘要（各模型摘要合并）
    summaries = [v.intel_summary for v in votes if v.intel_summary]
    if summaries:
        result["intel_summary"] = " | ".join(dict.fromkeys(summaries))  # 去重保序

    # 平均置信度
    avg_conf = sum(v.confidence for v in votes) / len(votes)
    result["confidence"] = round(avg_conf)

    # 共识模型的风险标签（取多数）
    from collections import Counter
    label_counts = Counter(v.risk_label for v in votes if v.risk_label)
    if label_counts:
        result["risk_label"] = label_counts.most_common(1)[0][0]

    return result


def _default_llm_result() -> dict:
    return {
        "risk_label": "guarded",
        "confidence": 50,
        "intel_summary": "",
        "intel_adjustment": {"home": 0.0, "draw": 0.0, "away": 0.0},
    }
