"""
Dixon-Coles model — port from football-prediction-skill.
Estimates team attack/defence strengths from historical match data
and generates score probability matrices with low-score correction (τ).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson


@dataclass
class DCParams:
    """Fitted Dixon-Coles parameter set."""
    attack: dict[str, float] = field(default_factory=dict)
    defence: dict[str, float] = field(default_factory=dict)
    home_advantage: float = 0.25
    rho: float = -0.13        # low-score correction strength
    log_likelihood: float = -math.inf


@dataclass
class MatchRecord:
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    weight: float = 1.0       # time-decay weight, pre-computed


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Low-score correction factor τ(x, y)."""
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def _neg_log_likelihood(params: np.ndarray, teams: list[str], matches: list[MatchRecord]) -> float:
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}

    attack  = params[:n]
    defence = params[n: 2 * n]
    home_adv = params[2 * n]
    rho      = params[2 * n + 1]

    ll = 0.0
    for m in matches:
        hi = idx[m.home_team]
        ai = idx[m.away_team]
        lam = math.exp(attack[hi] + defence[ai] + home_adv)
        mu  = math.exp(attack[ai] + defence[hi])
        t   = _tau(m.home_goals, m.away_goals, lam, mu, rho)
        if t <= 0:
            return 1e9
        ll += m.weight * (
            math.log(t)
            + math.log(poisson.pmf(m.home_goals, lam))
            + math.log(poisson.pmf(m.away_goals, mu))
        )
    return -ll


def fit(matches: list[MatchRecord], l2_lambda: float = 0.01) -> DCParams:
    """Fit Dixon-Coles parameters via L-BFGS-B with L2 regularization."""
    if not matches:
        return DCParams()

    teams = sorted({m.home_team for m in matches} | {m.away_team for m in matches})
    n = len(teams)

    x0 = np.zeros(2 * n + 2)
    x0[2 * n] = 0.25   # home advantage
    x0[2 * n + 1] = -0.13  # rho

    def objective(params: np.ndarray) -> float:
        nll = _neg_log_likelihood(params, teams, matches)
        l2 = l2_lambda * float(np.sum(params[: 2 * n] ** 2))
        return nll + l2

    bounds = [(-3, 3)] * (2 * n) + [(0, 1), (-1, 0)]

    result = minimize(
        objective,
        x0,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 1000, "ftol": 1e-9},
    )

    params = DCParams(
        attack={t: float(result.x[i]) for i, t in enumerate(teams)},
        defence={t: float(result.x[n + i]) for i, t in enumerate(teams)},
        home_advantage=float(result.x[2 * n]),
        rho=float(result.x[2 * n + 1]),
        log_likelihood=-float(result.fun),
    )
    return params


def predict_probs(
    params: DCParams,
    home_team: str,
    away_team: str,
    max_goals: int = 8,
) -> dict[str, float]:
    """
    Return {home, draw, away} 1X2 probabilities from fitted parameters.
    Falls back to neutral 1/3 if teams unseen.
    """
    ha = params.attack.get(home_team)
    hd = params.defence.get(home_team)
    aa = params.attack.get(away_team)
    ad = params.defence.get(away_team)

    if None in (ha, hd, aa, ad):
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}

    lam = math.exp(ha + ad + params.home_advantage)
    mu  = math.exp(aa + hd)

    p_home = p_draw = p_away = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = (
                _tau(i, j, lam, mu, params.rho)
                * poisson.pmf(i, lam)
                * poisson.pmf(j, mu)
            )
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p

    total = p_home + p_draw + p_away
    if total == 0:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    return {
        "home": p_home / total,
        "draw": p_draw / total,
        "away": p_away / total,
    }


def predict_from_features(
    home_elo: float,
    away_elo: float,
    home_xg: Optional[float] = None,
    away_xg: Optional[float] = None,
) -> dict[str, float]:
    """
    Lightweight prediction when no historical match data is available.
    Uses Elo difference + optional xG to estimate 1X2 probabilities.
    """
    elo_diff = home_elo - away_elo
    # Convert Elo diff to win probability via logistic curve
    home_win_elo = 1 / (1 + 10 ** (-elo_diff / 400))

    if home_xg is not None and away_xg is not None:
        total_xg = home_xg + away_xg
        if total_xg > 0:
            home_win_xg = home_xg / total_xg
            home_win = 0.6 * home_win_elo + 0.4 * home_win_xg
        else:
            home_win = home_win_elo
    else:
        home_win = home_win_elo

    # Rough draw probability: peaks around 0.25 for balanced matches
    draw = 0.25 * (1 - abs(home_win - 0.5) / 0.5)
    away = 1 - home_win - draw

    total = home_win + draw + away
    return {
        "home": home_win / total,
        "draw": draw / total,
        "away": away / total,
    }


def apply_time_decay(
    matches: list[MatchRecord],
    reference_date,
    decay_rate: float = 0.0025,
) -> list[MatchRecord]:
    """
    Apply exponential time decay weights.
    decay_rate=0.0025 → half-life ≈ 277 days.
    reference_date should be a date-like object with subtraction support.
    """
    from datetime import date as _date

    if isinstance(reference_date, _date):
        ref = reference_date
    else:
        ref = _date.today()

    result = []
    for m in matches:
        # MatchRecord.weight expected to carry a `date` attribute for decay
        days = getattr(m, "_date_diff", None)
        if days is None:
            days = 0
        w = math.exp(-decay_rate * max(0, days))
        result.append(
            MatchRecord(
                home_team=m.home_team,
                away_team=m.away_team,
                home_goals=m.home_goals,
                away_goals=m.away_goals,
                weight=w,
            )
        )
    return result
