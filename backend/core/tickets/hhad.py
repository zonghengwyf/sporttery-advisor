"""让球赔率（HHAD）概率转换工具。

从胜平负（HAD）概率 + 让球数，估算让球盘各结果概率。
使用基于欧洲顶级联赛的经验性进球差分布。

让球数符号约定（与竞彩官方一致）：
  正数 → 主队让球，如 1.0 = 主让1球（主队须赢2+球才算 HHAD 主胜）
  负数 → 客队让球（受让），如 -1.0 = 受让1球（主队不输即算 HHAD 主胜/平）
  0    → 平手，与 HAD 等价
"""
from __future__ import annotations

# 主队胜利时，恰好胜 k 球的经验概率（条件概率）
_HOME_WIN_BY: dict[int, float] = {1: 0.42, 2: 0.30, 3: 0.16, 4: 0.07}
_HOME_WIN_BY_5PLUS: float = 0.05

# 客队胜利时，恰好胜 k 球的经验概率
_AWAY_WIN_BY: dict[int, float] = {1: 0.44, 2: 0.30, 3: 0.15, 4: 0.06}
_AWAY_WIN_BY_5PLUS: float = 0.05


def _home_pmf(k: int) -> float:
    """P(主队恰好赢 k 球 | 主队胜)"""
    return _HOME_WIN_BY_5PLUS if k >= 5 else _HOME_WIN_BY.get(k, 0.0)


def _home_cdf_above(n: int) -> float:
    """P(主队赢球数 >= n | 主队胜)"""
    if n <= 1:
        return 1.0
    total = sum(v for k, v in _HOME_WIN_BY.items() if k >= n)
    if n <= 5:
        total += _HOME_WIN_BY_5PLUS
    return min(1.0, max(0.0, total))


def _away_pmf(k: int) -> float:
    """P(客队恰好赢 k 球 | 客队胜)"""
    return _AWAY_WIN_BY_5PLUS if k >= 5 else _AWAY_WIN_BY.get(k, 0.0)


def _away_cdf_above(n: int) -> float:
    """P(客队赢球数 >= n | 客队胜)"""
    if n <= 1:
        return 1.0
    total = sum(v for k, v in _AWAY_WIN_BY.items() if k >= n)
    if n <= 5:
        total += _AWAY_WIN_BY_5PLUS
    return min(1.0, max(0.0, total))


def had_to_hhad(
    p_home: float,
    p_draw: float,
    p_away: float,
    handicap: float,
) -> tuple[float, float, float]:
    """
    将胜平负概率转换为让球盘概率。

    参数:
      p_home/p_draw/p_away: HAD 三结果概率，之和应为 1
      handicap: 让球数（正=主让，负=受让，0=平手）

    返回: (p_hhad_home, p_hhad_draw, p_hhad_away)
    """
    h = int(round(handicap))

    if h == 0:
        raw = (p_home, p_draw, p_away)

    elif h > 0:
        # 主让 h 球：主须赢 h+1 球以上才算 HHAD 主胜
        # 原始平局 + 主赢不足 h 球 → HHAD 客胜
        p_hh = p_home * _home_cdf_above(h + 1)   # HHAD 主胜
        p_hd = p_home * _home_pmf(h)              # HHAD 平（主恰好赢 h 球）
        p_ha = max(0.0, 1.0 - p_hh - p_hd)       # HHAD 客胜（含原始平/客胜/主赢不足 h 球）
        raw = (p_hh, p_hd, p_ha)

    else:
        # 受让 |h| 球（客队让球）：客须赢 |h|+1 球以上才算 HHAD 客胜
        abs_h = -h
        p_ha = p_away * _away_cdf_above(abs_h + 1)  # HHAD 客胜
        p_hd = p_away * _away_pmf(abs_h)            # HHAD 平（客恰好赢 |h| 球）
        p_hh = max(0.0, 1.0 - p_ha - p_hd)         # HHAD 主胜（含原始主胜/平/客赢不足 |h| 球）
        raw = (p_hh, p_hd, p_ha)

    total = sum(raw)
    if total <= 0:
        return (1 / 3, 1 / 3, 1 / 3)

    norm = tuple(max(0.0, min(1.0, v / total)) for v in raw)
    return norm  # type: ignore[return-value]


def format_handicap(handicap: float) -> str:
    """将让球数格式化为中文描述，如 1.0 → '主让1球'，-1.0 → '受让1球'。"""
    h = int(round(handicap))
    if h == 0:
        return "平手"
    if h > 0:
        return f"主让{h}球"
    return f"受让{-h}球"


def hhad_ev(
    p_home: float,
    p_draw: float,
    p_away: float,
    hhad_odds: dict,
) -> tuple[float, float, float]:
    """
    计算 HHAD 三个投注方向的期望值（EV = 模型概率 × 赔率 - 1）。

    hhad_odds: {"home": x, "draw": y, "away": z, "handicap": h}

    返回 (ev_home, ev_draw, ev_away)
    """
    handicap = hhad_odds.get("handicap", 0)
    oh = float(hhad_odds.get("home", 0) or 0)
    od = float(hhad_odds.get("draw", 0) or 0)
    oa = float(hhad_odds.get("away", 0) or 0)

    ph, pd, pa = had_to_hhad(p_home, p_draw, p_away, handicap)

    ev_h = ph * oh - 1 if oh > 1.0 else -1.0
    ev_d = pd * od - 1 if od > 1.0 else -1.0
    ev_a = pa * oa - 1 if oa > 1.0 else -1.0
    return ev_h, ev_d, ev_a
