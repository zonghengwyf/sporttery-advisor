"""
Factor-based confidence scorer for China Sporttery football analysis.

Implements the 8-factor evidence model from the china-sporttery-football-advisor
decision framework, translated into executable Python logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── 枚举 ─────────────────────────────────────────────────────────────────────

class AbnormalResultType(Enum):
    """Root-cause classification for surprising match results."""
    CONTROL_SCORING    = "control_scoring"    # 刻意控分 / 留力 / 选择出线路
    FAVORITE_POOR_FORM = "favorite_poor_form" # 大热门真实状态差
    UNDERDOG_STRENGTH  = "underdog_strength"  # 冷门队有可复制的结构性优势
    TACTICAL_MISMATCH  = "tactical_mismatch"  # 战术克制（低防线 / 过渡 / 高压失效）
    VARIANCE           = "variance"           # 随机事件（红牌 / 点球 / xG 不支持）
    TOURNAMENT_PATTERN = "tournament_pattern" # 多场冷门暗示市场系统性低估
    NONE               = "none"               # 无异常赛果


class TournamentRisk(Enum):
    """Control-scoring / rotation risk level in group-stage or bracket context."""
    HIGH   = "high"    # 已出线，控分路线明确，高让球/大比分风险
    MEDIUM = "medium"  # 只需保积分 / 净胜球，可能轮换
    LOW    = "low"     # 必须赢，全力出击


class RiskLabel(Enum):
    MAINLINE    = "mainline"     # 信心 ≥ 70，可作主串关腿
    GUARDED     = "guarded"      # 信心 60–69，可入串但需防守腿
    UPSET_COVER = "upset_cover"  # 信心 52–59，小注或比分单关
    AVOID       = "avoid"        # 信心 < 52，跳过


# ── 因素权重（来自 factor-model.md） ─────────────────────────────────────────

FACTOR_WEIGHTS: dict[str, float] = {
    "team_strength":    0.18,
    "recent_form":      0.14,
    "availability":     0.16,
    "tactical_matchup": 0.12,
    "schedule_venue":   0.10,
    "motivation":       0.10,
    "odds_market":      0.14,
    "psychological":    0.06,
}


# ── 数据类 ────────────────────────────────────────────────────────────────────

@dataclass
class FactorScores:
    """
    Each factor scored 0–100 for the *favored* side.
    50 = neutral / unknown, >50 = favors, <50 = against.
    """
    team_strength:    float = 50.0
    recent_form:      float = 50.0
    availability:     float = 50.0
    tactical_matchup: float = 50.0
    schedule_venue:   float = 50.0
    motivation:       float = 50.0
    odds_market:      float = 50.0
    psychological:    float = 50.0

    def as_dict(self) -> dict[str, float]:
        return {
            "team_strength":    self.team_strength,
            "recent_form":      self.recent_form,
            "availability":     self.availability,
            "tactical_matchup": self.tactical_matchup,
            "schedule_venue":   self.schedule_venue,
            "motivation":       self.motivation,
            "odds_market":      self.odds_market,
            "psychological":    self.psychological,
        }


@dataclass
class UpsetFlag:
    """A single upset-risk condition that reduces confidence."""
    code: str
    description: str


# Canonical upset flags (≥2 active → reduce confidence, move to guarded/upset_cover)
UPSET_FLAGS: list[UpsetFlag] = [
    UpsetFlag("missing_creator",    "主力创造者 / 中场发动机缺席"),
    UpsetFlag("missing_striker",    "首发前锋缺席"),
    UpsetFlag("missing_gk",         "首发门将缺席"),
    UpsetFlag("failed_weak_opp",    "大热门近期未能击败实力明显弱于自身的对手（非控分原因）"),
    UpsetFlag("underdog_structure",  "冷门队通过可复制的结构性战术拿到积分"),
    UpsetFlag("qualified_rotate",   "热门队已出线 / 已保组首，可能轮换或保留体力"),
    UpsetFlag("mutual_draw_benefit", "双方同时受益于平局或低比分结果"),
    UpsetFlag("low_block_weakness",  "热门队对阵低防线时创造能力差"),
    UpsetFlag("adverse_conditions",  "极端天气 / 恶劣场地 / 高海拔对热门队不利"),
    UpsetFlag("odds_drift_against",  "海外赔率持续向空热门方向漂移，而公众情绪未跟上"),
    UpsetFlag("poor_sporttery_value", "竞彩赔率明显低于海外去水差隐含公平概率"),
]


@dataclass
class FactorScorerResult:
    weighted_confidence: float          # 0–100
    risk_label: RiskLabel
    factor_scores: FactorScores
    abnormal_result: AbnormalResultType
    tournament_risk: TournamentRisk
    active_upset_flags: list[str]       # flag codes
    upset_flag_penalty: float           # 0–20 points deducted
    final_confidence: float             # 0–100，after penalties
    notes: list[str] = field(default_factory=list)


# ── 核心评分函数 ──────────────────────────────────────────────────────────────

def compute_weighted_confidence(scores: FactorScores) -> float:
    """Weighted average of all factor scores → 0–100."""
    total = sum(
        getattr(scores, factor) * weight
        for factor, weight in FACTOR_WEIGHTS.items()
    )
    return round(total, 2)


def apply_abnormal_result_adjustment(
    confidence: float,
    abnormal_type: AbnormalResultType,
) -> tuple[float, str]:
    """
    Adjust confidence based on root cause of any recent surprising result.
    Returns (adjusted_confidence, note).
    """
    adjustments: dict[AbnormalResultType, tuple[float, str]] = {
        AbnormalResultType.CONTROL_SCORING: (
            -3.0,
            "近期异常赛果为控分行为，本场不下调基础信心，但去掉大让球/大比分投注",
        ),
        AbnormalResultType.FAVORITE_POOR_FORM: (
            -8.0,
            "热门队真实状态差，从稳健串关中移除，加入平局保护",
        ),
        AbnormalResultType.UNDERDOG_STRENGTH: (
            -6.0,
            "冷门队拥有可复制的结构性优势，升级平局/让球防守保护",
        ),
        AbnormalResultType.TACTICAL_MISMATCH: (
            -5.0,
            "战术克制风险，热门队对阵低防线时创造力受限",
        ),
        AbnormalResultType.VARIANCE: (
            0.0,
            "近期异常赛果由随机事件导致，不过度反应；需 xG 数据支撑前保持谨慎",
        ),
        AbnormalResultType.TOURNAMENT_PATTERN: (
            -4.0,
            "本届赛事多场黑马暗示市场系统性低估弱队，适当降低热门信心",
        ),
        AbnormalResultType.NONE: (0.0, ""),
    }
    delta, note = adjustments.get(abnormal_type, (0.0, ""))
    return max(0.0, confidence + delta), note


def apply_tournament_risk_adjustment(
    confidence: float,
    tournament_risk: TournamentRisk,
) -> tuple[float, str]:
    """Adjust confidence based on group-stage / bracket incentive risk."""
    if tournament_risk == TournamentRisk.HIGH:
        return max(0.0, confidence - 7.0), "高控分风险：去掉大让球、大比分投注，降低串关权重"
    if tournament_risk == TournamentRisk.MEDIUM:
        return max(0.0, confidence - 3.0), "中等轮换风险：降级让胜，升级平局/小比分覆盖"
    return confidence, ""


def count_upset_flags(active_flag_codes: list[str]) -> int:
    """Count how many upset flags are active."""
    valid_codes = {f.code for f in UPSET_FLAGS}
    return sum(1 for code in active_flag_codes if code in valid_codes)


def classify_confidence(final_confidence: float) -> RiskLabel:
    if final_confidence >= 70:
        return RiskLabel.MAINLINE
    if final_confidence >= 60:
        return RiskLabel.GUARDED
    if final_confidence >= 52:
        return RiskLabel.UPSET_COVER
    return RiskLabel.AVOID


# ── 主入口 ────────────────────────────────────────────────────────────────────

def score_match(
    factor_scores: FactorScores,
    abnormal_result: AbnormalResultType = AbnormalResultType.NONE,
    tournament_risk: TournamentRisk = TournamentRisk.LOW,
    active_upset_flags: Optional[list[str]] = None,
) -> FactorScorerResult:
    """
    Full scoring pipeline:
    1. Weighted factor average
    2. Abnormal-result adjustment
    3. Tournament-risk adjustment
    4. Upset-flag penalty (−3 per flag beyond threshold of 1)
    5. Classify into RiskLabel
    """
    if active_upset_flags is None:
        active_upset_flags = []

    # Step 1
    base_confidence = compute_weighted_confidence(factor_scores)
    notes: list[str] = []

    # Step 2
    conf, note = apply_abnormal_result_adjustment(base_confidence, abnormal_result)
    if note:
        notes.append(note)

    # Step 3
    conf, note = apply_tournament_risk_adjustment(conf, tournament_risk)
    if note:
        notes.append(note)

    # Step 4: each flag beyond the first costs 3 points
    flag_count = count_upset_flags(active_upset_flags)
    # ≥2 flags → trigger upset-cover mode; each extra flag beyond 1 penalises
    upset_penalty = max(0.0, (flag_count - 1) * 3.0)
    if flag_count >= 2:
        notes.append(
            f"{flag_count} 个爆冷风险因子触发，降低信心 {upset_penalty:.0f} 分"
        )
    conf = max(0.0, conf - upset_penalty)

    risk_label = classify_confidence(conf)

    return FactorScorerResult(
        weighted_confidence=base_confidence,
        risk_label=risk_label,
        factor_scores=factor_scores,
        abnormal_result=abnormal_result,
        tournament_risk=tournament_risk,
        active_upset_flags=active_upset_flags,
        upset_flag_penalty=upset_penalty,
        final_confidence=round(conf, 1),
        notes=notes,
    )
