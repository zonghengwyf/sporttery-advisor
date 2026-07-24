"""
Multi-source probability fusion.
Blends Dixon-Coles statistical probs with market signals and LLM intelligence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FusedProbs:
    home: float
    draw: float
    away: float
    sources: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, float]:
        return {"home": self.home, "draw": self.draw, "away": self.away}


def _softmax(vals: list[float]) -> list[float]:
    m = max(vals)
    exps = [math.exp(v - m) for v in vals]
    s = sum(exps)
    return [e / s for e in exps]


def _normalize(probs: dict[str, float]) -> dict[str, float]:
    total = sum(probs.values())
    if total == 0:
        return {"home": 1/3, "draw": 1/3, "away": 1/3}
    return {k: v / total for k, v in probs.items()}


class PredictionFusion:
    """
    Weighted geometric mean fusion of multiple probability sources.

    Sources and default weights:
    - "dc":      Dixon-Coles statistical model         (weight 0.50)
    - "market":  Devigged market odds (reference only) (weight 0.30)
    - "elo":     Elo-based simple estimate             (weight 0.10)
    - "xg":      xG-based estimate                    (weight 0.10)
    """

    DEFAULT_WEIGHTS = {
        "dc":     0.50,
        "market": 0.30,
        "elo":    0.10,
        "xg":     0.10,
    }

    def __init__(self, weights: Optional[dict[str, float]] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()

    def fuse(self, sources: dict[str, dict[str, float]]) -> FusedProbs:
        """
        sources: {"dc": {"home":..., "draw":..., "away":...}, "market": {...}, ...}
        Missing sources are skipped and remaining weights are renormalised.
        """
        active = {k: v for k, v in sources.items() if k in self.weights and v}
        if not active:
            return FusedProbs(home=1/3, draw=1/3, away=1/3, sources=[])

        eff_weights = {k: self.weights[k] for k in active}
        w_total = sum(eff_weights.values())
        eff_weights = {k: v / w_total for k, v in eff_weights.items()}

        # Geometric mean (log-domain weighted average)
        log_home = log_draw = log_away = 0.0
        eps = 1e-9
        for src, probs in active.items():
            w = eff_weights[src]
            log_home += w * math.log(max(probs.get("home", 1/3), eps))
            log_draw += w * math.log(max(probs.get("draw", 1/3), eps))
            log_away += w * math.log(max(probs.get("away", 1/3), eps))

        unnorm = {"home": math.exp(log_home), "draw": math.exp(log_draw), "away": math.exp(log_away)}
        norm = _normalize(unnorm)

        return FusedProbs(
            home=norm["home"],
            draw=norm["draw"],
            away=norm["away"],
            sources=list(active.keys()),
            weights=eff_weights,
        )

    def apply_intelligence(
        self,
        base: FusedProbs,
        intel_adjustment: dict[str, float],
    ) -> FusedProbs:
        """
        Apply LLM intelligence adjustment.
        intel_adjustment: {"home": +0.05, "draw": -0.02, "away": -0.03}
        Values are additive shifts in probability space, renormalised after.
        """
        adjusted = {
            "home": base.home + intel_adjustment.get("home", 0),
            "draw": base.draw + intel_adjustment.get("draw", 0),
            "away": base.away + intel_adjustment.get("away", 0),
        }
        # Clip to [0.01, 0.98] to avoid extremes
        clipped = {k: max(0.01, min(0.98, v)) for k, v in adjusted.items()}
        norm = _normalize(clipped)
        return FusedProbs(
            home=norm["home"],
            draw=norm["draw"],
            away=norm["away"],
            sources=base.sources + ["intel"],
            weights=base.weights,
        )

    def apply_availability_facts(
        self,
        base: FusedProbs,
        home_missing_key_players: int = 0,
        away_missing_key_players: int = 0,
    ) -> FusedProbs:
        """
        Apply simple availability adjustments based on missing key players.
        Each missing key player shifts probability ~1.5% away from that team.
        """
        home_penalty = home_missing_key_players * 0.015
        away_penalty = away_missing_key_players * 0.015

        adjusted = {
            "home": base.home - home_penalty + away_penalty * 0.5,
            "draw": base.draw + (home_penalty + away_penalty) * 0.2,
            "away": base.away - away_penalty + home_penalty * 0.5,
        }
        clipped = {k: max(0.01, min(0.98, v)) for k, v in adjusted.items()}
        norm = _normalize(clipped)
        return FusedProbs(
            home=norm["home"],
            draw=norm["draw"],
            away=norm["away"],
            sources=base.sources + ["availability"],
            weights=base.weights,
        )
