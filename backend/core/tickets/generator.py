"""竞彩票型生成器

generate_for_match  → 单场票型 dict（存入 predictions.tickets）
combine             → 多场合并的 4 类竞彩票型（旧接口，保留兼容）
generate_parlay_plans → 新接口：返回 3+1 类方案（稳健/均衡/博高赔/比分）

多选腿（LLM 选项 C）：
  LLM 返回 "主胜/平" 或 picks=["客胜","平"] 时，每个选项各自买入。
  总注数 = product(len(picks)) across all legs，串关赔率用概率加权均值估算。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.tickets.global_decision import TicketStructureDirective

logger = logging.getLogger(__name__)


# 竞彩胜平负代码
_PICK_CODE = {"主胜": "3", "平": "1", "平局": "1", "客胜": "0"}
_PICK_LABEL = {"H": "主胜", "D": "平局", "A": "客胜"}
_RISK_WEIGHT = {
    "mainline":    1.0,
    "guarded":     0.7,
    "upset_cover": 0.4,
    "avoid":       0.15,  # 参与博高赔腿，不参与稳健/均衡
}

# HHAD 必须比 HAD EV 高出此幅度才切换（防止模型误差导致全量让球）
_HHAD_PREFERENCE_MARGIN = 0.05


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
    match_code: str          # 竞彩场次号
    home_team: str
    away_team: str
    kickoff: str             # "20:00"

    # 主要选项（首选/最高概率）
    pick: str                # "主胜" / "平局" / "客胜"
    pick_code: str           # "3" / "1" / "0"

    # 全部选项（多选时包含多个）
    picks: list[str] = field(default_factory=list)
    pick_codes: list[str] = field(default_factory=list)
    picks_odds: list[float] = field(default_factory=list)  # 各选项赔率

    odds: float = 1.0        # 概率加权均值赔率（用于串关估算）
    win_prob: float = 0.0    # 该腿中奖概率（多选时为各选项概率之和）
    num_picks: int = 1       # 该腿选项数（决定注数倍增）

    model_votes_agree: int = 0
    model_votes_total: int = 0
    model_names: list[str] = field(default_factory=list)
    odds_estimated: bool = False

    market: str = "胜平负"          # "胜平负" | "让球胜平负"
    handicap: float | None = None  # 让球数

    def to_dict(self) -> dict:
        d = {
            "match_id":       self.match_id,
            "match_code":     self.match_code,
            "home_team":      self.home_team,
            "away_team":      self.away_team,
            "kickoff":        self.kickoff,
            "market":         self.market,
            "pick":           self.pick,
            "pick_code":      self.pick_code,
            "picks":          self.picks,
            "pick_codes":     self.pick_codes,
            "picks_odds":     self.picks_odds,
            "num_picks":      self.num_picks,
            "odds":           self.odds,
            "odds_estimated": self.odds_estimated,
            "win_prob":       self.win_prob,
            "model_votes": {
                "agree":  self.model_votes_agree,
                "total":  self.model_votes_total,
                "models": self.model_names,
            },
        }
        if self.handicap is not None:
            from core.tickets.hhad import format_handicap
            d["handicap"] = self.handicap
            d["handicap_label"] = format_handicap(self.handicap)
        return d


@dataclass
class ParlayPlan:
    """一个完整的串关方案"""
    plan_id: str             # "conservative" | "balanced" | "high_odds" | "scoreline"
    name: str
    tag: str
    score: int               # 0-100 综合评分
    stars: int               # 1-5 星
    parlay_type: str         # "3串1" 等
    legs: list[ParlayLeg]
    # 计算字段
    total_odds: float        # 赔率积（加权均值）
    base_stake: float        # 竞彩最低 2 元
    multiplier: int          # 用户倍数
    num_combos: int          # 实际注数（多选时 > 1）
    total_stake: float       # base_stake × num_combos × multiplier
    theoretical_prize: float # 单注潜在奖金估算
    win_probability: float   # 理论中奖概率
    # M串N 容错方案时的子组合串级（如 [2,3,4] 表示全部 2串1/3串1/4串1 子组合）；
    # None 或 [n] 表示普通 n串1
    combo_sizes: list[int] | None = None
    ai_rationale: str = ""                                    # AI 全局决策给出的方案结构说明
    ai_excluded: list[dict] = field(default_factory=list)     # 被排除场次 [{match_id, home_team, away_team, reason}]

    def to_dict(self) -> dict:
        return {
            "plan_id":           self.plan_id,
            "name":              self.name,
            "tag":               self.tag,
            "score":             self.score,
            "stars":             self.stars,
            "parlay_type":       self.parlay_type,
            "combo_sizes":       self.combo_sizes,
            "legs":              [leg.to_dict() for leg in self.legs],
            "total_odds":        round(self.total_odds, 2),
            "base_stake":        self.base_stake,
            "multiplier":        self.multiplier,
            "num_combos":        self.num_combos,
            "total_stake":       self.total_stake,
            "theoretical_prize": round(self.theoretical_prize, 1),
            "win_probability":   round(self.win_probability, 4),
            "win_probability_pct": f"{self.win_probability * 100:.1f}%",
            "ai_rationale":      self.ai_rationale,
            "ai_excluded":       self.ai_excluded,
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
            "dissent_notes": llm_result.get("dissent_notes", ""),
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
            base = {"match_id": pred.match_id}

            if weight >= 0.7 and t.get("conservative_leg"):
                leg = t["conservative_leg"]
                if isinstance(leg, dict):
                    mainline_legs.append({**base, **leg})

            if weight >= 0.4 and t.get("balanced_leg"):
                leg = t["balanced_leg"]
                if isinstance(leg, dict):
                    balanced_legs.append({**base, **leg})

            if t.get("high_odds_leg"):
                leg = t["high_odds_leg"]
                if isinstance(leg, dict):
                    high_odds_legs.append({**base, **leg})

            for sl in t.get("scoreline_legs", []):
                if isinstance(sl, str):
                    scoreline_legs.append({**base, "pick": sl})
                elif isinstance(sl, dict):
                    scoreline_legs.append({**base, **sl})

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
        multiplier: int = 1,
        recent_roi: float | None = None,
        directive: "TicketStructureDirective | None" = None,
    ) -> list[ParlayPlan]:
        """生成稳健/均衡/博高赔/比分 4 类方案；directive 非 None 时由 AI 决定场次组合，否则降级 Python 规则。"""
        # 当 AI 判断今日无推荐方案时提前返回
        if directive is not None and directive.no_recommendation:
            logger.info("generate_parlay_plans：AI 全局决策判断今日无推荐方案，跳过生成")
            return []

        # directive 提供时：各 ids 为 set（空 set 代表 AI 决定该方案不含任何场次）
        # directive 为 None 时：各 ids 为 None（降级使用 _RISK_WEIGHT 阈值）
        cons_ids: set[int] | None = None
        bal_ids: set[int] | None = None
        ho_ids: set[int] | None = None
        if directive is not None:
            cons_ids = set(directive.conservative.match_ids) if directive.conservative else set()
            bal_ids  = set(directive.balanced.match_ids)    if directive.balanced    else set()
            ho_ids   = set(directive.high_odds.match_ids)   if directive.high_odds   else set()

        conservative_legs: list[ParlayLeg] = []
        balanced_legs: list[ParlayLeg] = []
        high_odds_legs: list[ParlayLeg] = []

        for item in enriched_predictions:
            match = item["match"]
            pred = item["prediction"]
            votes = item.get("ensemble_votes", [])

            mid = getattr(match, "id", "?")
            if not pred or not pred.fused_probs:
                fp_fallback = pred.stat_probs if pred else None
                if fp_fallback:
                    logger.warning("match_id=%s fused_probs 为空，降级使用 stat_probs", mid)
                else:
                    logger.warning(
                        "match_id=%s 跳过：fused_probs 和 stat_probs 均为空", mid
                    )
                    continue
                pred_fp = fp_fallback
            else:
                pred_fp = pred.fused_probs

            risk = pred.risk_label or "guarded"
            weight = _RISK_WEIGHT.get(risk, 0.5)

            fp = pred_fp
            tickets = pred.tickets or {}
            match_code = _extract_match_code(match)

            # ── _make_leg：解析 LLM pick（含多选），构建 ParlayLeg ─────────────
            def _make_leg(pick_dict, pick_override: str | None = None, max_picks: int = 99) -> ParlayLeg | None:
                if not pick_dict and not pick_override:
                    return None

                # 提取所有选项
                if pick_override:
                    raw_picks = [pick_override]
                else:
                    raw = pick_dict.get("pick", "") or ""
                    multi = pick_dict.get("picks") or []
                    if multi and isinstance(multi, list):
                        raw_picks = [str(p).strip() for p in multi if str(p).strip()]
                    elif raw:
                        raw_picks = [p.strip() for p in str(raw).split("/") if p.strip()]
                    else:
                        return None

                if not raw_picks:
                    return None

                # 归一化，去重
                normalized: list[str] = []
                seen: set[str] = set()
                for rp in raw_picks:
                    canonical = _primary_pick(rp)
                    if canonical not in seen:
                        normalized.append(canonical)
                        seen.add(canonical)

                if not normalized:
                    return None

                # 防止多选对冲导致注数膨胀和方向不明
                normalized = normalized[:max_picks]

                # 以第一个（主要）选项决定市场
                primary_pick_name = normalized[0]
                market_name, primary_odds, handicap_val, primary_prob, odds_estimated = _select_market(
                    match, primary_pick_name, fp
                )

                # 按选定市场获取各选项的赔率和概率
                from core.tickets.hhad import had_to_hhad
                ph = fp.get("home", 0.33)
                pd_ = fp.get("draw", 0.28)
                pa = fp.get("away", 0.39)

                picks_list: list[str] = []
                picks_odds_list: list[float] = []
                probs_list: list[float] = []
                pick_idx_map = {"主胜": 0, "平局": 1, "客胜": 2}

                if market_name == "让球胜平负":
                    hhad_data = (match.sporttery_odds or {}).get("hhad") or {}
                    handicap = hhad_data.get("handicap", 0)
                    hhad_probs = had_to_hhad(ph, pd_, pa, handicap)
                    for pick_name in normalized:
                        idx = pick_idx_map.get(pick_name)
                        if idx is None:
                            continue
                        o = _hhad_odds_for_pick(hhad_data, pick_name) or primary_odds
                        p = hhad_probs[idx]
                        picks_list.append(pick_name)
                        picks_odds_list.append(round(float(o), 2))
                        probs_list.append(p)
                else:
                    for pick_name in normalized:
                        o = _odds_for_pick(match.sporttery_odds, pick_name) or primary_odds
                        p = _prob_for_pick(fp, pick_name)
                        picks_list.append(pick_name)
                        picks_odds_list.append(round(float(o), 2))
                        probs_list.append(p)

                if not picks_list:
                    return None

                # 总中奖概率 = 各互斥选项概率之和
                total_win_prob = min(1.0, sum(probs_list))

                # 概率加权均值赔率（串关奖金估算用）
                prob_sum = sum(probs_list)
                weighted_odds = (
                    sum(p * o for p, o in zip(probs_list, picks_odds_list)) / prob_sum
                    if prob_sum > 0 else picks_odds_list[0]
                )

                pick_code_list = [_PICK_CODE.get(p, "-") for p in picks_list]

                # 单模型时共识设为中性（避免 0/0 导致所有腿等分）
                if votes:
                    agree_count, total_count, model_names = _compute_votes(votes, picks_list[0])
                else:
                    agree_count, total_count, model_names = 1, 1, []

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
                    market=market_name,
                    handicap=handicap_val,
                    pick=picks_list[0],
                    pick_code=pick_code_list[0],
                    picks=picks_list,
                    pick_codes=pick_code_list,
                    picks_odds=picks_odds_list,
                    odds=round(float(weighted_odds), 2),
                    odds_estimated=odds_estimated,
                    win_prob=round(total_win_prob, 4),
                    model_votes_agree=agree_count,
                    model_votes_total=total_count,
                    model_names=model_names,
                    num_picks=len(picks_list),
                )

            match_id_int = int(mid) if str(mid).isdigit() else -1
            logger.info(
                "match_id=%s risk=%s weight=%.1f conservative_leg=%s",
                mid, risk, weight, tickets.get("conservative_leg"),
            )

            use_cons = match_id_int in cons_ids if cons_ids is not None else weight >= 0.7
            use_bal  = match_id_int in bal_ids  if bal_ids  is not None else weight >= 0.4
            use_ho   = match_id_int in ho_ids   if ho_ids   is not None else True

            if use_cons:
                leg = _make_leg(tickets.get("conservative_leg"), max_picks=1)
                if leg:
                    conservative_legs.append(leg)

            if use_bal:
                leg = _make_leg(tickets.get("balanced_leg"), max_picks=1)
                if leg:
                    balanced_legs.append(leg)

            ho = tickets.get("high_odds_leg")
            if ho and use_ho:
                leg = _make_leg(ho, max_picks=1)
                if leg:
                    high_odds_legs.append(leg)

        logger.info(
            "generate_parlay_plans 汇总：输入%d场 → 稳健腿%d 均衡腿%d 高赔腿%d",
            len(enriched_predictions),
            len(conservative_legs), len(balanced_legs), len(high_odds_legs),
        )

        # 按策略排序，取最优子集（最少 2 腿）
        conservative_legs = _best_legs(conservative_legs, max_legs=5, strategy="safe")
        balanced_legs = _best_legs(balanced_legs, max_legs=5, strategy="balanced")
        high_odds_legs = _best_legs(high_odds_legs, max_legs=4, strategy="high_odds")

        base_stake = 2.0

        # 构建 directive 的排除列表（供所有方案共享）
        excluded_list: list[dict] = []
        if directive is not None:
            for ex in directive.excluded:
                # 尝试从 enriched_predictions 中找到队名
                info = next(
                    ({"match_id": ex.match_id,
                      "home_team": item["match"].home_team,
                      "away_team": item["match"].away_team,
                      "reason": ex.reason}
                     for item in enriched_predictions
                     if item["match"].id == ex.match_id),
                    {"match_id": ex.match_id, "reason": ex.reason},
                )
                excluded_list.append(info)

        plans: list[ParlayPlan] = []
        for plan_id, name, legs in [
            ("conservative", "稳健串关", conservative_legs),
            ("balanced",     "均衡串关", balanced_legs),
            ("high_odds",    "博高赔串关", high_odds_legs),
        ]:
            if len(legs) < 2:   # 竞彩串关最少 2 场
                if legs:
                    logger.info("plan=%s 仅 %d 腿，不足 2 场，跳过", plan_id, len(legs))
                continue
            plan = _build_plan(plan_id, name, legs, base_stake, multiplier, budget)

            scheme_dir = _get_scheme_dir(directive, plan_id)
            if scheme_dir and scheme_dir.rationale:
                plan.ai_rationale = scheme_dir.rationale
            plan.ai_excluded = excluded_list

            plans.append(plan)

            n = len(legs)
            if directive is not None:
                should_cover = bool(scheme_dir and scheme_dir.cover is not None)
            else:
                should_cover = 3 <= n <= 4 and all(l.num_picks == 1 for l in legs)

            if should_cover and all(l.num_picks == 1 for l in legs):
                combo_sizes = list(range(2, n + 1))
                # 官网拒单上限 5 注（SC-001），无论 AI 指令还是 Python 规则路径均强制截断
                trial_combos = sum(
                    sum(1 for _ in combinations(range(n), k)) for k in combo_sizes
                )
                if trial_combos > 5:
                    logger.warning("plan=%s 容错注数 %d > 5，截断为最高两级子组合", plan_id, trial_combos)
                    combo_sizes = [n - 1, n] if n >= 2 else [n]

                cover = _build_plan(
                    f"{plan_id}_cover", f"{name}·容错", legs,
                    base_stake, multiplier, budget,
                    combo_sizes=combo_sizes,
                )
                if scheme_dir and scheme_dir.cover:
                    cover.ai_rationale = f"[容错说明] {scheme_dir.cover.rationale}"
                cover.ai_excluded = excluded_list
                plans.append(cover)

        # Kelly 动态调整注额（含回撤保护）
        if plans:
            kelly_stakes = kelly_allocate(plans, budget, recent_roi=recent_roi)
            for plan in plans:
                original_stake = plan.base_stake * plan.num_combos * plan.multiplier
                stake = kelly_stakes.get(plan.plan_id, original_stake)
                plan.total_stake = round(stake, 1)
                if plan.combo_sizes and len(plan.combo_sizes) > 1:
                    # M串N：theoretical_prize 已在 _build_plan 中设为 max_payout，
                    # Kelly 调整注额时按比例缩放，而非错误地用 stake × conditional_odds
                    scale = stake / original_stake if original_stake > 0 else 1.0
                    plan.theoretical_prize = round(plan.theoretical_prize * scale, 1)
                else:
                    plan.theoretical_prize = round(stake * plan.total_odds, 1)

        # 比分方案：从各场次的 scoreline_legs 收集
        scoreline_plan = _build_scoreline_plan(enriched_predictions, budget)
        if scoreline_plan:
            plans.append(scoreline_plan)

        return plans

    # ── 内部辅助 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_pick(llm_pick, match, home, draw, away, ticket_type) -> dict:
        if isinstance(llm_pick, dict) and (llm_pick.get("pick") or llm_pick.get("picks")):
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


# ── 比分方案构建 ────────────────────────────────────────────────────────────

def _build_scoreline_plan(enriched_predictions: list[dict], budget: float) -> ParlayPlan | None:
    """从各场次的 scoreline_legs 构建比分方案，腿赔率为估算值。"""
    scoreline_legs: list[ParlayLeg] = []

    for item in enriched_predictions:
        match = item["match"]
        pred = item["prediction"]
        if not pred or not pred.tickets:
            continue
        sl_raw = pred.tickets.get("scoreline_legs", [])
        if not sl_raw:
            continue

        picks_strs: list[str] = []
        for sl in sl_raw:
            if isinstance(sl, dict) and sl.get("pick"):
                picks_strs.append(sl["pick"])
            elif isinstance(sl, str) and sl:
                picks_strs.append(sl)
        if not picks_strs:
            continue

        kickoff_str = ""
        if match.kickoff_at:
            try:
                kickoff_str = match.kickoff_at.strftime("%H:%M")
            except Exception:
                pass

        scoreline_legs.append(ParlayLeg(
            match_id=match.id,
            match_code=_extract_match_code(match),
            home_team=match.home_team,
            away_team=match.away_team,
            kickoff=kickoff_str,
            market="比分",
            handicap=None,
            pick=picks_strs[0],
            pick_code="-",
            picks=picks_strs,
            pick_codes=["-"] * len(picks_strs),
            picks_odds=[0.0] * len(picks_strs),
            odds=0.0,
            odds_estimated=True,
            win_prob=0.0,
            model_votes_agree=0,
            model_votes_total=0,
            num_picks=len(picks_strs),
        ))

    if not scoreline_legs:
        return None

    stake = max(2.0, round(budget * 0.05, 1))
    n = len(scoreline_legs)
    tag = f"{n} 场推荐比分，小额覆盖"

    return ParlayPlan(
        plan_id="scoreline",
        name="比分小注",
        tag=tag,
        score=30,
        stars=2,
        parlay_type=f"{n}场比分",
        legs=scoreline_legs,
        total_odds=0.0,
        base_stake=2.0,
        multiplier=1,
        num_combos=1,
        total_stake=stake,
        theoretical_prize=0.0,
        win_probability=0.0,
    )


# ── 模块级辅助函数 ─────────────────────────────────────────────────────────

def _extract_match_code(match) -> str:
    sid = getattr(match, "sporttery_id", None) or str(match.id)
    if len(sid) >= 6 and sid.isdigit():
        return sid[-6:]
    return sid[:10]


def _primary_pick(pick_str: str) -> str:
    """单个 pick 字符串归一化为标准选项名。"""
    if not pick_str:
        return "主胜"
    part = pick_str.strip()
    mapping = {
        "主胜": "主胜", "胜": "主胜", "H": "主胜", "h": "主胜", "win": "主胜",
        "平":   "平局", "平局": "平局", "D": "平局", "d": "平局", "draw": "平局",
        "客胜": "客胜", "负": "客胜", "A": "客胜", "a": "客胜", "lose": "客胜",
    }
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
        f = float(val)
        return f if f > 1.0 else None
    except (TypeError, ValueError):
        return None


def _hhad_odds_for_pick(hhad_data: dict, pick: str) -> float | None:
    mapping = {"主胜": "home", "平局": "draw", "客胜": "away"}
    val = hhad_data.get(mapping.get(pick, "home"))
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 1.0 else None
    except (TypeError, ValueError):
        return None


def _select_market(
    match,
    primary_pick: str,
    model_fp: dict,
) -> tuple[str, float, float | None, float, bool]:
    """比较 HAD / HHAD EV，选更优市场。返回 (market, odds, handicap, win_prob, is_estimated)。"""
    from core.tickets.hhad import had_to_hhad

    pick_idx = {"主胜": 0, "平局": 1, "客胜": 2}
    idx = pick_idx.get(primary_pick, 0)

    ph = model_fp.get("home", 0.33)
    pd = model_fp.get("draw", 0.28)
    pa = model_fp.get("away", 0.39)
    had_prob = (ph, pd, pa)[idx]

    had_odds = _odds_for_pick(match.sporttery_odds, primary_pick)
    had_ev = had_prob * had_odds - 1 if had_odds else -2.0

    hhad_data = (match.sporttery_odds or {}).get("hhad") or {}
    best_hhad: dict = {}

    if hhad_data and isinstance(hhad_data, dict):
        handicap = hhad_data.get("handicap", 0)
        hhad_odds_val = _hhad_odds_for_pick(hhad_data, primary_pick)
        if hhad_odds_val:
            hhad_probs = had_to_hhad(ph, pd, pa, handicap)
            hhad_p = hhad_probs[idx]
            ev = hhad_p * hhad_odds_val - 1
            best_hhad = {"ev": ev, "odds": hhad_odds_val, "handicap": handicap, "prob": hhad_p}

    if best_hhad and best_hhad["ev"] > had_ev + _HHAD_PREFERENCE_MARGIN:
        return ("让球胜平负", best_hhad["odds"], best_hhad["handicap"], best_hhad["prob"], False)

    if had_odds:
        return "胜平负", had_odds, None, had_prob, False

    raw_p = max(had_prob, 0.05)
    est_odds = round(min(1.0 / (raw_p * 1.125), 19.9), 2)
    return "胜平负", est_odds, None, had_prob, True


def _compute_votes(votes: list[dict], pick: str) -> tuple[int, int, list[str]]:
    if not votes:
        return 0, 0, []
    outcome_map = {"主胜": "H", "平局": "D", "客胜": "A"}
    target_outcome = outcome_map.get(pick, "H")
    total = len(votes)
    agreed = [v for v in votes if v.get("outcome") == target_outcome]
    model_names = [v.get("model", "") for v in agreed]
    return len(agreed), total, model_names


def _get_scheme_dir(directive, plan_id: str):
    """取 directive 中对应 plan_id 的 SchemeDirective；directive 为 None 时返回 None。"""
    return getattr(directive, plan_id, None) if directive is not None else None


def _best_legs(legs: list[ParlayLeg], max_legs: int, strategy: str) -> list[ParlayLeg]:
    """从候选腿中选出最优组合（每场最多取一腿）。"""
    if not legs:
        return []

    # 所有腿的 model_votes_total 都为 0 时（单模型），共识视为中性 0.5
    all_no_votes = all(leg.model_votes_total == 0 for leg in legs)

    def consensus(leg: ParlayLeg) -> float:
        if all_no_votes:
            return 0.5
        return leg.model_votes_agree / max(leg.model_votes_total, 1)

    if strategy == "safe":
        def score(leg: ParlayLeg) -> float:
            c = consensus(leg)
            odds_fit = 1.0 if 1.5 <= leg.odds <= 2.8 else 0.6
            if not leg.odds_estimated:
                ev = leg.win_prob * leg.odds - 1
                ev_factor = max(0.5, 1.0 + ev)
            else:
                ev_factor = 0.85
            return leg.win_prob * c * odds_fit * ev_factor

    elif strategy == "balanced":
        def score(leg: ParlayLeg) -> float:
            c = consensus(leg)
            if not leg.odds_estimated:
                ev = leg.win_prob * leg.odds - 1
                ev_factor = max(0.6, 1.0 + ev)
            else:
                ev_factor = 0.9
            return math.sqrt(leg.win_prob * max(leg.odds, 0.01)) * (0.5 + 0.5 * c) * ev_factor

    else:  # high_odds
        def score(leg: ParlayLeg) -> float:
            return leg.odds * (0.5 + 0.5 * leg.win_prob)

    seen_matches: set[int] = set()
    unique_legs: list[ParlayLeg] = []
    for leg in sorted(legs, key=score, reverse=True):
        if leg.match_id not in seen_matches:
            unique_legs.append(leg)
            seen_matches.add(leg.match_id)
        if len(unique_legs) >= max_legs:
            break

    unique_legs.sort(key=lambda l: l.kickoff)
    return unique_legs


def _build_plan(
    plan_id: str,
    name: str,
    legs: list[ParlayLeg],
    base_stake: float,
    multiplier: int,
    budget: float,
    combo_sizes: list[int] | None = None,
) -> ParlayPlan:
    """构建串关方案。combo_sizes=None 为普通 n串1；传 [2..n] 为 M串N 容错方案。"""
    n = len(legs)
    if combo_sizes is None:
        combo_sizes = [n]
    is_system = combo_sizes != [n]

    # 枚举所有子组合（n串1 时仅 1 个；M串N 时为 ΣC(n,k) 个）
    combos: list[tuple[tuple[int, ...], int, float, float]] = []  # (腿索引, 注数, 赔率积, 中奖概率)
    for k in combo_sizes:
        for idxs in combinations(range(n), k):
            num_bets = 1
            odds_prod = 1.0
            prob = 1.0
            for i in idxs:
                leg = legs[i]
                num_bets *= leg.num_picks
                odds_prod *= leg.odds
                prob *= leg.win_prob
            if k > 1:
                prob *= 0.97 ** (k - 1)
            combos.append((idxs, num_bets, odds_prod, prob))

    num_combos = sum(c[1] for c in combos)
    total_stake = base_stake * num_combos * multiplier

    if not is_system:
        parlay_type = f"{n}串1"
        total_odds = combos[0][2]
        win_prob = combos[0][3]
        # 理论奖金：总注额 × 总赔率（多选腿时每个组合单注独立计算）
        theoretical_prize = total_stake * total_odds
    else:
        parlay_type = f"{n}串{num_combos}"
        # 枚举 2^n 种腿胜负结果（n≤5，开销可忽略），求：
        #   win_probability = P(至少中 1 注) = P(胜腿数 ≥ 最小串级)
        #   total_odds      = 中时条件期望派奖 / 总注额（Kelly/展示用的等效赔率）
        k_min = min(combo_sizes)
        p_any = 0.0
        exp_payout = 0.0
        for mask in range(1 << n):
            wins = [bool(mask >> i & 1) for i in range(n)]
            if sum(wins) < k_min:
                continue
            p_outcome = 1.0
            for i, leg in enumerate(legs):
                p_outcome *= leg.win_prob if wins[i] else (1.0 - leg.win_prob)
            if p_outcome <= 0:
                continue
            payout = 0.0
            for idxs, num_bets, odds_prod, _ in combos:
                if all(wins[i] for i in idxs):
                    payout += base_stake * multiplier * num_bets * odds_prod
            p_any += p_outcome
            exp_payout += p_outcome * payout
        win_prob = p_any
        cond_payout = exp_payout / p_any if p_any > 0 else 0.0
        total_odds = cond_payout / total_stake if total_stake > 0 else 0.0
        # 全腿命中时所有子组合均派奖（与竞彩官网"理论最高奖金"口径一致）
        max_payout = sum(base_stake * multiplier * nb * op for _, nb, op, _ in combos)
        theoretical_prize = max_payout

    avg_prob = win_prob ** (1 / n) if n > 0 else 0
    all_no_votes = all(leg.model_votes_total == 0 for leg in legs)
    avg_consensus = (
        sum(
            (0.5 if all_no_votes else leg.model_votes_agree / max(leg.model_votes_total, 1))
            for leg in legs
        ) / n
        if n > 0 else 0
    )
    base_score = avg_prob * 100
    consensus_bonus = avg_consensus * 20
    odds_penalty = max(0, (5 - total_odds) * 3) if plan_id == "conservative" else 0
    score = max(5, min(99, round(base_score + consensus_bonus - odds_penalty)))
    stars = _score_to_stars(score)
    tag = _build_tag(plan_id, legs, avg_consensus, win_prob)
    if is_system:
        tolerate = n - min(combo_sizes)
        tag = f"{parlay_type} 容错，错 {tolerate} 场仍有奖 | {tag}"

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
        num_combos=num_combos,
        total_stake=total_stake,
        theoretical_prize=theoretical_prize,
        win_probability=win_prob,
        combo_sizes=combo_sizes if is_system else None,
    )


def kelly_fraction(win_prob: float, total_odds: float, kelly_factor: float = 0.25) -> float:
    b = total_odds - 1.0
    if b <= 0 or win_prob <= 0:
        return 0.0
    full_kelly = (win_prob * b - (1.0 - win_prob)) / b
    return max(0.0, full_kelly * kelly_factor)


def kelly_allocate(plans: list, budget: float, recent_roi: float | None = None) -> dict[str, float]:
    min_stake = 2.0
    fractions: dict[str, float] = {}

    # 回撤保护：近5次出票ROI < -30%时stake减半
    stake_scale = 0.5 if (recent_roi is not None and recent_roi < -0.30) else 1.0

    for plan in plans:
        f = kelly_fraction(plan.win_probability, plan.total_odds)
        fractions[plan.plan_id] = f

    total_fraction = sum(fractions.values())

    if total_fraction <= 0:
        per_plan = max(min_stake, budget / max(len(plans), 1))
        return {p.plan_id: round(per_plan * stake_scale, 1) for p in plans}

    n = len(plans)
    if budget < min_stake * n:
        per_plan = round(budget / n, 1)
        return {p.plan_id: per_plan for p in plans}

    reserved = min_stake * n
    distributable = budget - reserved

    allocation: dict[str, float] = {}
    for plan in plans:
        f = fractions[plan.plan_id]
        extra = distributable * (f / total_fraction)
        stake = round((min_stake + extra) * stake_scale, 1)

        # 回撤保护：单票理论奖金超过本金50%时自动降倍
        if plan.total_odds > 0:
            potential_prize = stake * plan.total_odds
            max_prize = budget * 0.5
            if potential_prize > max_prize:
                stake = round(max_prize / plan.total_odds, 1)
                stake = max(min_stake, stake)  # 不低于最小注额

        allocation[plan.plan_id] = stake

    return allocation


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
    multi_legs = [l for l in legs if l.num_picks > 1]
    multi_str = f"含 {len(multi_legs)} 腿双向覆盖，" if multi_legs else ""
    consensus_str = f"AI {round(avg_consensus * 100):.0f}% 共识" if avg_consensus > 0 else ""
    win_pct = f"理论中奖率 {win_prob * 100:.0f}%"

    if plan_id.startswith("conservative"):
        return f"{n} 场，{multi_str}{consensus_str}，稳健型首选，{win_pct}"
    if plan_id.startswith("balanced"):
        return f"均衡串关，{multi_str}{consensus_str}，{win_pct}"
    return f"高赔率冷门组合，{multi_str}小额博高奖，{win_pct}"
