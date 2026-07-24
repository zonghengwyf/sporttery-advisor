"""竞彩票型生成器

generate_for_match  → 单场票型 dict（存入 predictions.tickets）
combine             → 多场合并的 4 类竞彩票型（旧接口，保留兼容）
generate_parlay_plans → 新接口：返回 3 类串关方案（含场次编号/赔率/奖金/评分）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime


# 竞彩胜平负代码
_PICK_CODE = {"主胜": "3", "平": "1", "平局": "1", "客胜": "0"}
_PICK_LABEL = {"H": "主胜", "D": "平局", "A": "客胜"}
_RISK_WEIGHT = {
    "mainline":    1.0,
    "guarded":     0.7,
    "upset_cover": 0.4,
    "avoid":       0.0,
}


@dataclass
class TicketLeg:
    match_id: int
    home_team: str
    away_team: str
    market: str
    pick: str
    odds: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "market": self.market,
            "pick": self.pick,
            "odds": self.odds,
            "note": self.note,
        }


@dataclass
class ParlayLeg:
    match_id: int
    match_code: str          # 竞彩场次号（如 "周六001"）
    home_team: str
    away_team: str
    kickoff: str             # "20:00"
    pick: str                # "主胜" / "平局" / "客胜"
    pick_code: str           # "3" / "1" / "0"
    odds: float              # 竞彩赔率
    win_prob: float          # 模型预测该结果的概率
    model_votes_agree: int   # 同意此投注的模型数
    model_votes_total: int   # 参与投票的模型数
    model_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "match_code": self.match_code,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "kickoff": self.kickoff,
            "pick": self.pick,
            "pick_code": self.pick_code,
            "odds": self.odds,
            "win_prob": self.win_prob,
            "model_votes": {
                "agree": self.model_votes_agree,
                "total": self.model_votes_total,
                "models": self.model_names,
            },
        }


@dataclass
class ParlayPlan:
    """一个完整的串关方案"""
    plan_id: str             # "conservative" | "balanced" | "high_odds"
    name: str                # "稳健串关" | "均衡串关" | "博高赔串关"
    tag: str                 # 特点说明
    score: int               # 0-100 综合评分
    stars: int               # 1-5 星
    parlay_type: str         # "3串1" | "4串1" 等
    legs: list[ParlayLeg]
    # 计算字段
    total_odds: float        # 所有腿赔率之积
    base_stake: float        # 每注金额（竞彩最低 2 元）
    multiplier: int          # 用户选择的倍数
    total_stake: float       # base_stake × multiplier
    theoretical_prize: float # total_stake × total_odds
    win_probability: float   # 各腿中奖概率之积

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "tag": self.tag,
            "score": self.score,
            "stars": self.stars,
            "parlay_type": self.parlay_type,
            "legs": [leg.to_dict() for leg in self.legs],
            "total_odds": round(self.total_odds, 2),
            "base_stake": self.base_stake,
            "multiplier": self.multiplier,
            "total_stake": self.total_stake,
            "theoretical_prize": round(self.theoretical_prize, 1),
            "win_probability": round(self.win_probability, 4),
            "win_probability_pct": f"{self.win_probability * 100:.1f}%",
        }


class TicketGenerator:
    """将预测结果转换为竞彩票型。"""

    # ── 单场票型生成 ─────────────────────────────────────────────────────────

    def generate_for_match(self, match, fused_probs: dict, llm_result: dict) -> dict:
        home = fused_probs.get("home", 0.35)
        draw = fused_probs.get("draw", 0.28)
        away = fused_probs.get("away", 0.37)

        conservative_leg = self._resolve_pick(
            llm_result.get("conservative_pick"),
            match, home, draw, away, "conservative",
        )
        balanced_leg = self._resolve_pick(
            llm_result.get("balanced_pick"),
            match, home, draw, away, "balanced",
        )
        high_odds_leg = self._resolve_high_odds(
            llm_result.get("high_odds_pick"),
            match, home, draw, away,
        )
        scoreline_legs = self._resolve_scorelines(
            llm_result.get("scoreline_picks"),
            home, draw, away,
        )

        ctx = {"home_team": match.home_team, "away_team": match.away_team}
        if isinstance(conservative_leg, dict):
            conservative_leg = {**ctx, **conservative_leg}
        if isinstance(balanced_leg, dict):
            balanced_leg = {**ctx, **balanced_leg}
        if isinstance(high_odds_leg, dict):
            high_odds_leg = {**ctx, **high_odds_leg}
        scoreline_legs = [
            {**ctx, **(s if isinstance(s, dict) else {"pick": str(s)})}
            for s in scoreline_legs
        ]

        return {
            "conservative_leg": conservative_leg,
            "balanced_leg": balanced_leg,
            "high_odds_leg": high_odds_leg,
            "scoreline_legs": scoreline_legs,
            "fused_probs": fused_probs,
            "risk_label": llm_result.get("risk_label", "guarded"),
            "confidence": llm_result.get("confidence", 50),
            "skip_conditions": llm_result.get("skip_conditions", ""),
            "raw_analysis": llm_result.get("raw_text", ""),
        }

    # ── 多场合并（旧接口，保留兼容） ─────────────────────────────────────────

    def combine(self, predictions: list, budget: float) -> dict:
        mainline_legs: list[dict] = []
        balanced_legs: list[dict] = []
        high_odds_legs: list[dict] = []
        scoreline_legs: list[dict] = []

        for pred in predictions:
            if not pred.tickets:
                continue
            t = pred.tickets
            label = pred.risk_label or "guarded"
            weight = _RISK_WEIGHT.get(label, 0.5)

            if weight >= 0.7 and t.get("conservative_leg"):
                leg = t["conservative_leg"]
                if isinstance(leg, dict):
                    mainline_legs.append(leg)

            if weight >= 0.4 and t.get("balanced_leg"):
                leg = t["balanced_leg"]
                if isinstance(leg, dict):
                    balanced_legs.append(leg)

            if t.get("high_odds_leg"):
                leg = t["high_odds_leg"]
                if isinstance(leg, dict):
                    high_odds_legs.append(leg)

            for sl in t.get("scoreline_legs", []):
                if isinstance(sl, str):
                    scoreline_legs.append({"pick": sl})
                elif isinstance(sl, dict):
                    scoreline_legs.append(sl)

        allocation = self._allocate(budget)
        return {
            "conservative": {
                "legs": mainline_legs,
                "stake": allocation["conservative"],
                "note": "稳健票：高置信主腿，避免让球/大比分串关",
            },
            "balanced": {
                "legs": balanced_legs,
                "stake": allocation["balanced"],
                "note": "均衡票：主观点 + 防守腿（含平局保护）",
            },
            "high_odds": {
                "legs": high_odds_legs,
                "stake": allocation["high_odds"],
                "note": "博高赔票：小注，含平局/冷门覆盖",
            },
            "scoreline": {
                "legs": scoreline_legs,
                "stake": allocation["scoreline"],
                "note": "比分小注：每场 2-4 个最可能比分，极小注",
            },
            "stake_allocation": allocation,
        }

    # ── 新串关方案生成接口 ───────────────────────────────────────────────────

    def generate_parlay_plans(
        self,
        enriched_predictions: list[dict],
        budget: float = 100.0,
        multiplier: int = 2,
    ) -> list[ParlayPlan]:
        """
        enriched_predictions: 每项包含
          {
            "match": db.Match 对象,
            "prediction": db.Prediction 对象,
            "ensemble_votes": list[dict] (可选),
          }
        返回 3 个串关方案（稳健/均衡/博高赔）。
        """
        conservative_legs: list[ParlayLeg] = []
        balanced_legs: list[ParlayLeg] = []
        high_odds_legs: list[ParlayLeg] = []

        for item in enriched_predictions:
            match = item["match"]
            pred = item["prediction"]
            votes = item.get("ensemble_votes", [])

            if not pred or not pred.fused_probs:
                continue

            risk = pred.risk_label or "guarded"
            weight = _RISK_WEIGHT.get(risk, 0.5)

            # 跳过建议回避的比赛
            if weight == 0.0:
                continue

            fp = pred.fused_probs
            tickets = pred.tickets or {}
            match_code = _extract_match_code(match)

            def _make_leg(pick_dict, pick_override: str | None = None) -> ParlayLeg | None:
                if not pick_dict and not pick_override:
                    return None
                pick_str = pick_override or (
                    pick_dict.get("pick") or
                    ("/".join(pick_dict.get("picks", [])) if pick_dict.get("picks") else None)
                )
                if not pick_str:
                    return None

                # 找到对应的概率和赔率
                primary_pick = _primary_pick(pick_str)  # "主胜" / "平局" / "客胜"
                win_prob = _prob_for_pick(fp, primary_pick)
                odds_val = _odds_for_pick(match.sporttery_odds, primary_pick)

                if odds_val is None or odds_val < 1.01:
                    return None

                # 计算 AI 共识
                agree_count, total_count, model_names = _compute_votes(votes, primary_pick)

                kickoff_str = ""
                if match.kickoff_at:
                    try:
                        kickoff_str = match.kickoff_at.strftime("%H:%M")
                    except Exception:
                        pass

                return ParlayLeg(
                    match_id=match.id,
                    match_code=match_code,
                    home_team=match.home_team,
                    away_team=match.away_team,
                    kickoff=kickoff_str,
                    pick=primary_pick,
                    pick_code=_PICK_CODE.get(primary_pick, "-"),
                    odds=round(float(odds_val), 2),
                    win_prob=win_prob,
                    model_votes_agree=agree_count,
                    model_votes_total=total_count,
                    model_names=model_names,
                )

            # 稳健腿：高置信场次
            if weight >= 0.7:
                leg = _make_leg(tickets.get("conservative_leg"))
                if leg:
                    conservative_legs.append(leg)

            # 均衡腿：中等置信场次
            if weight >= 0.4:
                leg = _make_leg(tickets.get("balanced_leg"))
                if leg:
                    balanced_legs.append(leg)

            # 博高赔腿
            ho = tickets.get("high_odds_leg")
            if ho:
                leg = _make_leg(ho)
                if leg:
                    high_odds_legs.append(leg)

        # 按赔率乘积潜力排序，取最优子集
        conservative_legs = _best_legs(conservative_legs, max_legs=5, strategy="safe")
        balanced_legs = _best_legs(balanced_legs, max_legs=5, strategy="balanced")
        high_odds_legs = _best_legs(high_odds_legs, max_legs=4, strategy="high_odds")

        base_stake = 2.0  # 竞彩最低每注 2 元

        plans: list[ParlayPlan] = []
        for plan_id, name, legs in [
            ("conservative", "稳健串关", conservative_legs),
            ("balanced",     "均衡串关", balanced_legs),
            ("high_odds",    "博高赔串关", high_odds_legs),
        ]:
            if not legs:
                continue
            plan = _build_plan(plan_id, name, legs, base_stake, multiplier, budget)
            plans.append(plan)

        return plans

    # ── 内部辅助 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_pick(llm_pick, match, home, draw, away, ticket_type) -> dict:
        if isinstance(llm_pick, dict) and llm_pick.get("pick"):
            return llm_pick
        if ticket_type == "conservative":
            if home > 0.55:
                pick = "主胜"
            elif away > 0.55:
                pick = "客胜"
            elif home > away:
                pick = "主胜/平"
            else:
                pick = "客胜/平"
            return {"market": "胜平负", "pick": pick, "note": "基于统计概率自动生成"}
        if home >= away:
            pick = "主胜/平" if draw > 0.25 else "主胜"
        else:
            pick = "客胜/平" if draw > 0.25 else "客胜"
        return {"market": "胜平负", "pick": pick, "note": "均衡含平局保护，自动生成"}

    @staticmethod
    def _resolve_high_odds(llm_pick, match, home, draw, away) -> dict:
        if isinstance(llm_pick, dict) and (llm_pick.get("pick") or llm_pick.get("picks")):
            return llm_pick
        if draw > 0.30:
            picks = ["平"]
        elif home < away:
            picks = ["主胜", "平"]
        else:
            picks = ["客胜", "平"]
        return {"market": "胜平负", "picks": picks, "note": "冷门覆盖，自动生成"}

    @staticmethod
    def _resolve_scorelines(llm_scorelines, home, draw, away) -> list:
        if llm_scorelines and isinstance(llm_scorelines, list):
            return [s if isinstance(s, dict) else {"pick": str(s)} for s in llm_scorelines]
        if home > 0.5:
            return [{"pick": s} for s in ["2-0", "2-1", "3-0"]]
        elif draw > home and draw > away:
            return [{"pick": s} for s in ["1-1", "0-0", "1-0"]]
        elif away > 0.5:
            return [{"pick": s} for s in ["0-2", "1-2", "0-1"]]
        else:
            return [{"pick": s} for s in ["1-0", "1-1", "2-1"]]

    @staticmethod
    def _allocate(budget: float) -> dict:
        return {
            "conservative": round(budget * 0.60, 1),
            "balanced":     round(budget * 0.25, 1),
            "high_odds":    round(budget * 0.10, 1),
            "scoreline":    round(budget * 0.05, 1),
            "total":        budget,
        }


# ── 模块级辅助函数 ─────────────────────────────────────────────────────────

def _extract_match_code(match) -> str:
    """从 sporttery_id 或 id 提取展示用场次编号。"""
    sid = getattr(match, "sporttery_id", None) or str(match.id)
    # sporttery_id 格式通常是 "25026001"（年份+周+序号），截取后6位
    if len(sid) >= 6 and sid.isdigit():
        return sid[-6:]  # 如 "026001"
    return sid[:10]


def _primary_pick(pick_str: str) -> str:
    """从 pick 字符串提取主要选项（取斜杠前的那个）。"""
    if not pick_str:
        return "主胜"
    part = pick_str.split("/")[0].strip()
    mapping = {"主胜": "主胜", "平": "平局", "平局": "平局", "客胜": "客胜"}
    return mapping.get(part, "主胜")


def _prob_for_pick(fp: dict, pick: str) -> float:
    mapping = {"主胜": "home", "平局": "draw", "客胜": "away"}
    key = mapping.get(pick, "home")
    return float(fp.get(key, 0.33))


def _odds_for_pick(odds: dict | None, pick: str) -> float | None:
    if not odds:
        return None
    mapping = {"主胜": "home", "平局": "draw", "客胜": "away"}
    key = mapping.get(pick, "home")
    val = odds.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _compute_votes(votes: list[dict], pick: str) -> tuple[int, int, list[str]]:
    """统计多少模型支持该投注方向。"""
    if not votes:
        return 0, 0, []
    outcome_map = {"主胜": "H", "平局": "D", "客胜": "A"}
    target_outcome = outcome_map.get(pick, "H")
    total = len(votes)
    agreed = [v for v in votes if v.get("outcome") == target_outcome]
    model_names = [v.get("model", "") for v in agreed]
    return len(agreed), total, model_names


def _best_legs(legs: list[ParlayLeg], max_legs: int, strategy: str) -> list[ParlayLeg]:
    """从候选腿中选出最优组合。"""
    if not legs:
        return []

    if strategy == "safe":
        # 优先选共识高、赔率适中（1.5-2.5）的腿
        def score(leg: ParlayLeg) -> float:
            consensus = leg.model_votes_agree / max(leg.model_votes_total, 1)
            odds_fit = 1.0 if 1.5 <= leg.odds <= 2.8 else 0.6
            return leg.win_prob * consensus * odds_fit

    elif strategy == "balanced":
        # 平衡概率和赔率乘积
        def score(leg: ParlayLeg) -> float:
            consensus = leg.model_votes_agree / max(leg.model_votes_total, 1)
            return math.sqrt(leg.win_prob * leg.odds) * (0.5 + 0.5 * consensus)

    else:  # high_odds
        # 优先选高赔率
        def score(leg: ParlayLeg) -> float:
            return leg.odds * (0.5 + 0.5 * leg.win_prob)

    # 去重（每场只取一腿）
    seen_matches: set[int] = set()
    unique_legs: list[ParlayLeg] = []
    for leg in sorted(legs, key=score, reverse=True):
        if leg.match_id not in seen_matches:
            unique_legs.append(leg)
            seen_matches.add(leg.match_id)
        if len(unique_legs) >= max_legs:
            break

    # 按开球时间排序，方便用户核对
    unique_legs.sort(key=lambda l: l.kickoff)
    return unique_legs


def _build_plan(
    plan_id: str,
    name: str,
    legs: list[ParlayLeg],
    base_stake: float,
    multiplier: int,
    budget: float,
) -> ParlayPlan:
    n = len(legs)
    parlay_type = f"{n}串1"
    total_odds = 1.0
    win_prob = 1.0
    for leg in legs:
        total_odds *= leg.odds
        win_prob *= leg.win_prob

    total_stake = base_stake * multiplier
    theoretical_prize = total_stake * total_odds

    # 评分计算
    avg_prob = win_prob ** (1 / n) if n > 0 else 0
    avg_consensus = (
        sum(l.model_votes_agree / max(l.model_votes_total, 1) for l in legs) / n
        if n > 0 else 0
    )
    # 基础分 = 平均单场胜率
    base_score = avg_prob * 100
    # 共识加成：满共识 +20，0 共识 +0
    consensus_bonus = avg_consensus * 20
    # 赔率乘积惩罚：过低奖金方案减分
    odds_penalty = max(0, (5 - total_odds) * 3) if plan_id == "conservative" else 0
    score = max(5, min(99, round(base_score + consensus_bonus - odds_penalty)))
    stars = _score_to_stars(score)

    # 特点描述
    tag = _build_tag(plan_id, legs, avg_consensus, win_prob)

    return ParlayPlan(
        plan_id=plan_id,
        name=name,
        tag=tag,
        score=score,
        stars=stars,
        parlay_type=parlay_type,
        legs=legs,
        total_odds=total_odds,
        base_stake=base_stake,
        multiplier=multiplier,
        total_stake=total_stake,
        theoretical_prize=theoretical_prize,
        win_probability=win_prob,
    )


def _score_to_stars(score: int) -> int:
    if score >= 85:
        return 5
    if score >= 75:
        return 4
    if score >= 62:
        return 3
    if score >= 50:
        return 2
    return 1


def _build_tag(plan_id: str, legs: list[ParlayLeg], avg_consensus: float, win_prob: float) -> str:
    n = len(legs)
    consensus_str = f"AI {round(avg_consensus * 100):.0f}% 共识" if avg_consensus > 0 else ""
    win_pct = f"理论中奖率 {win_prob * 100:.0f}%"

    if plan_id == "conservative":
        return f"{n} 场主场优势，{consensus_str}，稳健型首选，{win_pct}"
    if plan_id == "balanced":
        return f"均衡串关，含平局防守腿，{consensus_str}，{win_pct}"
    return f"高赔率冷门组合，小额博高奖，{win_pct}"
