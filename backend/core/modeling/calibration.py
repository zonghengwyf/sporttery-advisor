"""
Temperature calibration for predicted probabilities.
Logit scaling + softmax to correct overconfident or underconfident models.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import minimize_scalar


@dataclass
class CalibrationResult:
    temperature: float
    brier_before: float
    brier_after: float
    n_samples: int


def _softmax(logits: list[float]) -> list[float]:
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    s = sum(exps)
    return [e / s for e in exps]


def _logits(probs: list[float]) -> list[float]:
    eps = 1e-7
    clipped = [max(eps, min(1 - eps, p)) for p in probs]
    return [math.log(p / (1 - p)) for p in clipped]


def _brier_score(preds: list[list[float]], actuals: list[list[float]]) -> float:
    total = 0.0
    for pred, act in zip(preds, actuals):
        total += sum((p - a) ** 2 for p, a in zip(pred, act))
    return total / len(preds)


def calibrate_temperature(
    raw_probs: list[list[float]],     # [[home, draw, away], ...]
    outcomes: list[int],               # 0=home, 1=draw, 2=away
) -> CalibrationResult:
    """
    Find optimal temperature T such that softmax(logits / T) minimises Brier.
    """
    n = len(raw_probs)
    actuals = [[1 if j == o else 0 for j in range(3)] for o in outcomes]

    brier_before = _brier_score(raw_probs, actuals)

    def loss(T: float) -> float:
        if T <= 0:
            return 1e9
        calibrated = [_softmax([l / T for l in _logits(p)]) for p in raw_probs]
        return _brier_score(calibrated, actuals)

    result = minimize_scalar(loss, bounds=(0.1, 5.0), method="bounded")
    T_opt = float(result.x)

    calibrated = [_softmax([l / T_opt for l in _logits(p)]) for p in raw_probs]
    brier_after = _brier_score(calibrated, actuals)

    return CalibrationResult(
        temperature=T_opt,
        brier_before=brier_before,
        brier_after=brier_after,
        n_samples=n,
    )


class TemperatureCalibrator:
    """Stateful calibrator: fit once, apply many times."""

    def __init__(self, temperature: float = 1.0):
        self.temperature = temperature
        self._fitted = False

    def fit(
        self,
        raw_probs: list[list[float]],
        outcomes: list[int],
    ) -> CalibrationResult:
        result = calibrate_temperature(raw_probs, outcomes)
        self.temperature = result.temperature
        self._fitted = True
        return result

    def transform(self, probs: dict[str, float]) -> dict[str, float]:
        """Apply temperature scaling to a single {home, draw, away} dict."""
        ordered = [probs.get("home", 1/3), probs.get("draw", 1/3), probs.get("away", 1/3)]
        logits = _logits(ordered)
        scaled = [l / self.temperature for l in logits]
        calibrated = _softmax(scaled)
        return {"home": calibrated[0], "draw": calibrated[1], "away": calibrated[2]}

    def transform_list(self, probs_list: list[dict[str, float]]) -> list[dict[str, float]]:
        return [self.transform(p) for p in probs_list]
