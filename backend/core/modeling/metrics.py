"""共享评估指标函数。

供回测（snapshot._calc_metrics）与模型晋升（retrain_model / model_registry）
复用，避免同一指标在两处实现漂移。口径定义见 ADR-006。
"""
from __future__ import annotations


def rps(probs: list[float], outcome_idx: int) -> float:
    """Ranked Probability Score（1X2 有序结果的标准 proper score）。

    RPS = Σ(cum_p - cum_o)² / (K - 1)，K=3。
    能区分"差点对"（预测主胜实际平局）与"错得离谱"（预测主胜实际客胜），
    越小越好。
    """
    indicators = [1.0 if i == outcome_idx else 0.0 for i in range(3)]
    cum_p = [probs[0], probs[0] + probs[1], 1.0]
    cum_o = [indicators[0], indicators[0] + indicators[1], 1.0]
    return sum((cp - co) ** 2 for cp, co in zip(cum_p, cum_o)) / 2
