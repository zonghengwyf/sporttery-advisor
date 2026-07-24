"""
Odds utilities: devigging (vig removal) and value assessment.
Supports multiplicative, Power, and Shin methods.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


OddsMethod = Literal["multiplicative", "power", "shin"]


@dataclass
class DeviggResult:
    method: str
    raw_implied: dict[str, float]   # implied probs WITH vig
    fair_probs: dict[str, float]    # fair probs WITHOUT vig
    overround: float                # total implied - 1


def decimal_to_implied(odds: dict[str, float]) -> dict[str, float]:
    """Convert decimal odds → raw implied probabilities."""
    return {k: 1.0 / v for k, v in odds.items() if v > 0}


def remove_vig(
    decimal_odds: dict[str, float],
    method: OddsMethod = "power",
) -> DeviggResult:
    """
    Remove bookmaker vig from decimal odds.

    multiplicative: divide each implied prob by total (simple normalization).
    power:          find exponent k such that sum(p^k) = 1 (Cheung 2015).
    shin:           Shin (1993) model assuming insider trading.
    """
    if not decimal_odds:
        return DeviggResult(
            method=method,
            raw_implied={},
            fair_probs={},
            overround=0.0,
        )

    implied = decimal_to_implied(decimal_odds)
    total = sum(implied.values())
    overround = total - 1.0

    if method == "multiplicative":
        fair = {k: v / total for k, v in implied.items()}

    elif method == "power":
        from scipy.optimize import brentq

        def _sum_powered(k: float) -> float:
            return sum(p ** k for p in implied.values()) - 1.0

        try:
            k = brentq(_sum_powered, 0.5, 3.0, xtol=1e-9)
        except ValueError:
            k = 1.0
        powered = {key: p ** k for key, p in implied.items()}
        s = sum(powered.values())
        fair = {key: v / s for key, v in powered.items()}

    elif method == "shin":
        # Shin model: p_i_fair = (sqrt(z^2 + 4(1-z)*q_i^2/sigma) - z) / (2(1-z))
        # where sigma = sum(q_i^2), z is the fraction of informed bettors
        # Approximate z via iterative solver
        q = list(implied.values())
        sigma = sum(qi ** 2 for qi in q)

        def _shin_sum(z: float) -> float:
            return sum(
                (math.sqrt(z ** 2 + 4 * (1 - z) * qi ** 2 / sigma) - z)
                / (2 * (1 - z))
                for qi in q
            ) - 1.0

        try:
            from scipy.optimize import brentq
            z = brentq(_shin_sum, 1e-6, 0.5, xtol=1e-9)
        except (ValueError, ImportError):
            z = 0.0
        keys = list(implied.keys())
        raw_vals = list(implied.values())
        fair_vals = [
            (math.sqrt(z ** 2 + 4 * (1 - z) * qi ** 2 / sigma) - z) / (2 * (1 - z))
            for qi in raw_vals
        ]
        s = sum(fair_vals)
        fair = {k: v / s for k, v in zip(keys, fair_vals)}

    else:
        raise ValueError(f"Unknown devig method: {method}")

    return DeviggResult(
        method=method,
        raw_implied=implied,
        fair_probs=fair,
        overround=overround,
    )


@dataclass
class ValueAssessment:
    outcome: str
    model_prob: float
    market_prob: float      # fair (devigged)
    raw_odd: float          # original decimal odd
    edge: float             # model_prob - market_prob
    ev: float               # (model_prob * raw_odd) - 1
    has_value: bool         # edge > threshold


def assess_value(
    model_probs: dict[str, float],
    market_odds: dict[str, float],
    edge_threshold: float = 0.03,
    devig_method: OddsMethod = "power",
) -> list[ValueAssessment]:
    """
    Compare model probabilities against market odds to find value bets.
    Returns one ValueAssessment per outcome.
    """
    devigged = remove_vig(market_odds, method=devig_method)
    results = []
    for outcome, model_p in model_probs.items():
        market_fair = devigged.fair_probs.get(outcome, 0)
        raw_odd = market_odds.get(outcome, 0)
        edge = model_p - market_fair
        ev = (model_p * raw_odd) - 1 if raw_odd > 0 else -1
        results.append(
            ValueAssessment(
                outcome=outcome,
                model_prob=model_p,
                market_prob=market_fair,
                raw_odd=raw_odd,
                edge=edge,
                ev=ev,
                has_value=edge > edge_threshold and ev > 0,
            )
        )
    return results
