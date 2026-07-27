"""每日端到端分析流水线 — Phase 3

三层流水线：
  Layer 1 — Dixon-Coles 统计 + Elo 降级 + 赔率融合
  Layer 2 — Skills 注入 LLM + 情报分析
  Layer 3 — 票型生成（由 TicketGenerator 完成）

写入：PostgreSQL predictions 表 + DuckDB prediction_snapshots
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.llm.client import LLMClient
from core.llm.client import LLMConfig as ClientLLMConfig
from core.llm.skills_injector import MatchContext, SkillsInjector
from core.modeling.factor_scorer import (
    AbnormalResultType,
    FactorScores,
    TournamentRisk,
    score_match,
)
from core.modeling.fusion import FusedProbs, PredictionFusion
from core.modeling.odds import remove_vig, select_devig_method
from core.tickets.generator import TicketGenerator

logger = logging.getLogger(__name__)

TOURNAMENT_KEYWORDS = {
    "世界杯", "欧洲杯", "亚洲杯", "美洲杯", "非洲杯",
    "world cup", "euro", "copa america", "afcon",
    "champions league", "europa league", "conference league",
    "欧冠", "欧联", "欧联大会杯",
}

# 追加到 SkillsInjector system prompt 末尾，要求结构化输出
_STRUCTURED_JSON_INSTRUCTION = """

---

## 结构化输出要求

完成分析文本后，**必须**在回复最后输出以下 JSON 代码块（勿省略任何字段）：

```json
{
  "risk_label": "mainline",
  "confidence": 72,
  "intel_summary": "30字以内核心情报摘要",
  "conservative_pick": {"market": "胜平负", "pick": "主胜", "note": "主场强队"},
  "balanced_pick": {"market": "胜平负", "pick": "主胜/平", "note": "防平串关"},
  "high_odds_pick": {"market": "胜平负", "picks": ["平"], "note": "冷门覆盖"},
  "scoreline_picks": ["2-0", "3-0", "2-1"],
  "intel_adjustment": {"home": 0.0, "draw": 0.0, "away": 0.0},
  "skip_conditions": "临场主力缺阵则跳过",
  "factor_scores": {
    "team_strength": 65,
    "recent_form": 60,
    "availability": 70,
    "tactical_matchup": 55,
    "schedule_venue": 50,
    "motivation": 60,
    "odds_market": 58,
    "psychological": 50
  },
  "abnormal_result": "none",
  "tournament_risk": "low",
  "upset_flags": []
}
```

字段说明：
- risk_label: mainline（稳健主推）/ guarded（谨慎）/ upset_cover（冷门覆盖）/ avoid（建议跳过）
- confidence: 0–100 整数，你对主推结果的把握程度
- intel_adjustment: 概率调整量，正数增加该结果概率，三项之和应接近 0
- factor_scores: 8 个因素的 0–100 评分（50 = 中性，>50 = 有利于投注方向）
- abnormal_result: none / control_scoring / favorite_poor_form / underdog_strength / tactical_mismatch / variance / tournament_pattern
- tournament_risk: low / medium / high（大赛控分/轮换风险等级）
- upset_flags: 触发的爆冷风险标志列表，可选值见下方
  可用标志：missing_creator, missing_striker, missing_gk, failed_weak_opp,
            underdog_structure, qualified_rotate, mutual_draw_benefit,
            low_block_weakness, adverse_conditions, odds_drift_against, poor_sporttery_value
"""


@dataclass
class MatchAnalysisResult:
    match_id: int
    run_id: str
    stat_probs: dict
    fused_probs: dict
    intel_summary: str
    risk_label: str
    confidence: float
    tickets: dict
    llm_provider: str
    llm_model: str
    raw_analysis: str = ""
    factor_analysis: dict | None = None  # FactorScorerResult serialized


class DailyPipeline:
    def __init__(self):
        self.settings = get_settings()
        self.skills_injector = SkillsInjector()
        self.fusion = PredictionFusion()
        self.ticket_gen = TicketGenerator()
        self._dc_params = None      # lazy-load from disk
        self._devig_method = None   # cached, re-evaluated each daily run
        self._snap = None           # SnapshotManager, lazy-init in async context

    # ── 公开接口 ─────────────────────────────────────────────────────────────

    async def run(self, target_date: date) -> dict:
        """运行目标日期的完整每日分析流水线。"""
        from db.models import Match
        from db.session import AsyncSessionLocal

        session = AsyncSessionLocal()
        try:
            llm_client = await self._get_llm_client(session)
            if not llm_client:
                logger.warning("无可用 LLM 配置，跳过 LLM 分析层")

            result = await session.execute(
                select(Match).where(Match.sale_date == str(target_date))
            )
            matches = result.scalars().all()
            if not matches:
                logger.info("今日无赛事：%s", target_date)
                return {"analyzed": 0, "errors": 0}

            # 每次每日运行时从 DuckDB 重新选最优去水差方法
            try:
                snap = await self._get_snap()
                hist = await snap.get_devig_historical(limit=60)
                self._devig_method = select_devig_method(hist)
                logger.info("去水差方法自动选择：%s（基于 %d 条历史）", self._devig_method, len(hist))
            except Exception as e:
                self._devig_method = "power"
                logger.debug("去水差方法选择失败，降级 power：%s", e)

            run_id = str(uuid.uuid4())[:8]
            analyzed = errors = 0

            for match in matches:
                try:
                    ar = await self.analyze_single_match(session, match, llm_client, run_id)
                    await self._save_prediction(session, ar)
                    analyzed += 1
                except Exception as exc:
                    logger.error("分析失败 match_id=%d: %s", match.id, exc, exc_info=True)
                    errors += 1

            await session.commit()

            # 保存 DuckDB 快照
            try:
                await self._save_snapshots(target_date, run_id)
            except Exception as exc:
                logger.warning("DuckDB 快照保存失败（不影响主流程）：%s", exc)

            logger.info(
                "每日分析完成 run_id=%s date=%s analyzed=%d errors=%d",
                run_id, target_date, analyzed, errors,
            )
            return {"analyzed": analyzed, "errors": errors, "run_id": run_id}
        finally:
            await session.close()

    async def analyze_single_match(
        self,
        session: AsyncSession,
        match,
        llm_client: Optional[LLMClient],
        run_id: Optional[str] = None,
    ) -> MatchAnalysisResult:
        """完整三层分析，可被 API 端点直接调用。"""
        if not run_id:
            run_id = str(uuid.uuid4())[:8]

        # Layer 1: 统计模型
        stat_probs, fused_probs = await self._layer1_stats(match)

        # Layer 2: LLM 情报
        if llm_client:
            llm_result = await self._layer2_llm(match, fused_probs, llm_client)
        else:
            llm_result = _default_llm_result()

        # 应用情报概率微调
        adj = llm_result.get("intel_adjustment")
        if adj and any(v != 0 for v in adj.values()):
            base = FusedProbs(**fused_probs)
            fused_probs = self.fusion.apply_intelligence(base, adj).to_dict()

        # 计算期望赔值 EV = 模型概率 × 竞彩赔率 - 1
        fused_probs = _compute_ev(fused_probs, match.sporttery_odds)

        # FactorScorer：将 LLM 因素评分转化为结构化置信度
        factor_result = _run_factor_scorer(llm_result)
        if factor_result:
            effective_risk_label = factor_result.risk_label.value
            effective_confidence = factor_result.final_confidence / 100.0
        else:
            effective_risk_label = llm_result.get("risk_label", "guarded")
            effective_confidence = float(llm_result.get("confidence", 50)) / 100.0

        # 将 FactorScorer 结论反写入 llm_result 供 ticket generator 使用
        llm_result["risk_label"] = effective_risk_label

        # Layer 3: 票型生成
        tickets = self.ticket_gen.generate_for_match(match, fused_probs, llm_result)
        if factor_result:
            tickets["factor_analysis"] = _factor_result_to_dict(factor_result)

        return MatchAnalysisResult(
            match_id=match.id,
            run_id=run_id,
            stat_probs=stat_probs,
            fused_probs=fused_probs,
            intel_summary=llm_result.get("intel_summary", ""),
            risk_label=effective_risk_label,
            confidence=effective_confidence,
            tickets=tickets,
            llm_provider=llm_client.config.provider if llm_client else "",
            llm_model=llm_client.config.model if llm_client else "",
            raw_analysis=llm_result.get("raw_text", ""),
            factor_analysis=_factor_result_to_dict(factor_result) if factor_result else None,
        )

    # ── Layer 1 ─────────────────────────────────────────────────────────────

    async def _layer1_stats(self, match) -> tuple[dict, dict]:
        """Dixon-Coles + Elo + 海外赔率去水差 → 融合概率。"""
        sources: dict[str, dict] = {}

        # Elo 评分
        try:
            from core.data.providers.clubelo import ClubEloProvider
            elo_prv = ClubEloProvider()
            elos = await elo_prv.get_match_elos(match.home_team, match.away_team)
            if elos and elos.get("home_elo") and elos.get("away_elo"):
                from core.modeling.dixon_coles import predict_from_features
                sources["elo"] = predict_from_features(
                    home_elo=elos["home_elo"],
                    away_elo=elos["away_elo"],
                )
        except Exception as e:
            logger.debug("Elo 获取失败：%s", e)

        # Dixon-Coles（需要预先训练好的参数文件）
        dc_params = self._load_dc_params()
        if dc_params:
            try:
                from core.modeling.dixon_coles import predict_probs
                dc = predict_probs(dc_params, match.home_team, match.away_team)
                # 中性 1/3 降级结果不放入融合源
                if not (abs(dc["home"] - 1 / 3) < 0.001):
                    sources["dc"] = dc
            except Exception as e:
                logger.debug("Dixon-Coles 预测失败：%s", e)

        # 海外赔率去水差
        if match.overseas_odds:
            try:
                raw = match.overseas_odds
                h = raw.get("home") or raw.get("h")
                d = raw.get("draw") or raw.get("d")
                a = raw.get("away") or raw.get("a")
                if h and d and a:
                    method = self._devig_method or "power"
                    dev = remove_vig(
                        {"home": float(h), "draw": float(d), "away": float(a)},
                        method=method,
                    )
                    sources["market"] = dev.fair_probs
            except Exception as e:
                logger.debug("去水差失败：%s", e)

        # 无任何来源时用均等概率
        if not sources:
            sources["elo"] = {"home": 0.38, "draw": 0.28, "away": 0.34}

        primary = sources.get("dc") or sources.get("market") or list(sources.values())[0]
        fused = self.fusion.fuse(sources)
        return primary, fused.to_dict()

    # ── Layer 2 ─────────────────────────────────────────────────────────────

    async def _layer2_llm(
        self, match, fused_probs: dict, llm_client: LLMClient
    ) -> dict:
        """Skills 注入 + LLM 分析 + 结构化 JSON 解析。"""
        league_lower = (match.league or "").lower()
        is_tournament = (match.is_tournament or False) or any(
            kw.lower() in league_lower for kw in TOURNAMENT_KEYWORDS
        )

        injuries_text = await self._fetch_injuries(match)
        odds_movement = _compute_odds_movement(
            match.sporttery_odds_open, match.sporttery_odds
        )

        context = MatchContext(
            home_team=match.home_team,
            away_team=match.away_team,
            league=match.league,
            is_tournament=is_tournament,
            has_abnormal_form=False,
            stat_probs=fused_probs,
            odds_data={
                "sporttery": match.sporttery_odds or {},
                "overseas": match.overseas_odds or {},
            },
            intel_data={"injuries": injuries_text} if injuries_text else None,
            odds_movement=odds_movement,
        )

        system_prompt = self.skills_injector.build_system_prompt(context)
        system_prompt += _STRUCTURED_JSON_INSTRUCTION

        user_msg = self._build_prompt(match, fused_probs, injuries_text)

        try:
            raw_text = await llm_client.chat(
                messages=[{"role": "user", "content": user_msg}],
                system=system_prompt,
                max_tokens=2048,
            )
            parsed = _parse_llm_response(raw_text)
            parsed["raw_text"] = raw_text
            return parsed
        except Exception as e:
            logger.error("LLM 调用失败 match_id=%d: %s", match.id, e)
            result = _default_llm_result()
            result["intel_summary"] = f"LLM 分析失败：{e}"
            return result

    async def _fetch_injuries(self, match) -> str:
        try:
            settings = get_settings()
            api_key = getattr(settings, "api_football_key", None)
            if not api_key:
                return ""
            from core.data.providers.api_football import APIFootballProvider
            afp = APIFootballProvider(api_key=api_key)
            injuries = await afp.get_injuries(match.sporttery_id)
            if not injuries:
                return ""
            home_inj = [i for i in injuries if i.get("team") == match.home_team]
            away_inj = [i for i in injuries if i.get("team") == match.away_team]
            parts = []
            if home_inj:
                parts.append(f"主队伤停：{', '.join(i.get('player','?') for i in home_inj[:3])}")
            if away_inj:
                parts.append(f"客队伤停：{', '.join(i.get('player','?') for i in away_inj[:3])}")
            return "\n".join(parts)
        except Exception as e:
            logger.debug("伤停数据获取失败：%s", e)
            return ""

    @staticmethod
    def _build_prompt(match, fused_probs: dict, injuries_text: str) -> str:
        h = fused_probs.get("home", 0.35)
        d = fused_probs.get("draw", 0.28)
        a = fused_probs.get("away", 0.37)
        lines = [
            "请分析以下竞彩足球比赛：",
            f"- 主队：{match.home_team}",
            f"- 客队：{match.away_team}",
            f"- 联赛：{match.league}",
        ]
        if match.sporttery_odds:
            o = match.sporttery_odds
            lines.append(
                f"- 竞彩赔率：主胜 {o.get('home','-')} / 平 {o.get('draw','-')} / 客胜 {o.get('away','-')}"
            )
        lines.append(f"- 统计融合概率：主胜 {h:.1%} / 平 {d:.1%} / 客胜 {a:.1%}")
        if injuries_text:
            lines.append(f"\n伤停情报：{injuries_text}")
        lines.append("\n请完成分析并在末尾输出要求的 JSON 代码块。")
        return "\n".join(lines)

    # ── 存储 ─────────────────────────────────────────────────────────────────

    async def _save_prediction(self, session: AsyncSession, ar: MatchAnalysisResult):
        from db.models import Prediction
        pred = Prediction(
            match_id=ar.match_id,
            run_id=ar.run_id,
            stat_probs=ar.stat_probs,
            fused_probs=ar.fused_probs,
            intel_summary=ar.intel_summary,
            risk_label=ar.risk_label,
            confidence=ar.confidence,
            tickets=ar.tickets,
            llm_provider=ar.llm_provider,
            llm_model=ar.llm_model,
        )
        session.add(pred)

    async def _get_snap(self):
        """Return cached SnapshotManager, initializing it in a thread on first call."""
        if self._snap is None:
            import asyncio
            from core.data.snapshot import SnapshotManager
            db_path = self.settings.duckdb_path
            self._snap = await asyncio.to_thread(SnapshotManager, db_path)
        return self._snap

    async def _save_snapshots(self, target_date: date, run_id: str):
        from db.models import Match, Prediction
        from db.session import AsyncSessionLocal

        snap = await self._get_snap()
        session = AsyncSessionLocal()
        try:
            preds = await session.execute(
                select(Prediction).where(Prediction.run_id == run_id)
            )
            for pred in preds.scalars():
                match = await session.get(Match, pred.match_id)
                if match:
                    await snap.save_prediction(
                        match_id=pred.match_id,
                        run_id=run_id,
                        kickoff_at=str(match.kickoff_at),
                        stat_probs=pred.stat_probs or {},
                        fused_probs=pred.fused_probs or pred.stat_probs or {},
                        intel_summary=pred.intel_summary or "",
                        risk_label=pred.risk_label or "",
                        confidence=pred.confidence or 0.5,
                    )
        finally:
            await session.close()
            snap.close()

    # ── 辅助 ─────────────────────────────────────────────────────────────────

    def _load_dc_params(self):
        if self._dc_params is not None:
            return self._dc_params
        params_path = Path(self.settings.duckdb_path).parent / "dc_params.json"
        if not params_path.exists():
            return None
        try:
            from core.modeling.dixon_coles import DCParams
            data = json.loads(params_path.read_text(encoding="utf-8"))
            self._dc_params = DCParams(
                attack=data["attack"],
                defence=data["defence"],
                home_advantage=data["home_advantage"],
                rho=data["rho"],
            )
            return self._dc_params
        except Exception as e:
            logger.debug("DC 参数加载失败：%s", e)
            return None

    async def _get_llm_client(self, session: AsyncSession) -> Optional[LLMClient]:
        from db.models import LLMConfig as DBLLMConfig

        result = await session.execute(
            select(DBLLMConfig).where(DBLLMConfig.is_default.is_(True)).limit(1)
        )
        cfg = result.scalar_one_or_none()
        if not cfg:
            result = await session.execute(select(DBLLMConfig).limit(1))
            cfg = result.scalar_one_or_none()

        if cfg:
            return LLMClient(ClientLLMConfig(
                provider=cfg.provider.value,
                model=cfg.model,
                api_key=cfg.api_key,
                base_url=cfg.base_url,
            ))

        settings = get_settings()
        api_key = getattr(settings, "system_llm_api_key", None)
        if api_key:
            return LLMClient(ClientLLMConfig(
                provider=getattr(settings, "system_llm_provider", "claude"),
                model=getattr(settings, "system_llm_model", "claude-sonnet-4-6"),
                api_key=api_key,
                base_url=getattr(settings, "system_llm_base_url", None),
            ))
        return None


# ── 模块级辅助函数 ─────────────────────────────────────────────────────────

def _parse_llm_response(text: str) -> dict:
    """从 LLM 输出中提取 ```json 代码块，失败时返回最小默认值。"""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 降级：寻找含 risk_label 的 JSON 对象
    match2 = re.search(r'\{[^{}]*"risk_label"[^{}]*\}', text, re.DOTALL)
    if match2:
        try:
            return json.loads(match2.group(0))
        except json.JSONDecodeError:
            pass

    return _default_llm_result()


def _compute_odds_movement(odds_open: dict | None, odds_current: dict | None) -> dict | None:
    """计算赔率变动百分比。开盘赔率缺失则返回 None。"""
    if not odds_open or not odds_current:
        return None
    result: dict = {}
    for key in ("home", "draw", "away"):
        o = odds_open.get(key)
        c = odds_current.get(key)
        if o and c:
            try:
                o_f, c_f = float(o), float(c)
                pct = (c_f - o_f) / o_f * 100
                result[f"{key}_pct"] = round(pct, 2)
                result[f"{key}_open"] = o_f
                result[f"{key}_current"] = c_f
            except (TypeError, ValueError):
                pass
    return result or None


def _compute_ev(fused_probs: dict, sporttery_odds: dict | None) -> dict:
    """将 EV（期望赔值）写入 fused_probs，key 为 ev_home/ev_draw/ev_away。
    EV > 0 表示正期望，是值得考虑的投注信号。
    """
    result = dict(fused_probs)
    if not sporttery_odds:
        return result
    mapping = [("home", "home"), ("draw", "draw"), ("away", "away")]
    for prob_key, odds_key in mapping:
        prob = fused_probs.get(prob_key)
        odds_val = sporttery_odds.get(odds_key)
        if prob is not None and odds_val is not None:
            try:
                ev = round(float(prob) * float(odds_val) - 1, 4)
                result[f"ev_{prob_key}"] = ev
            except (TypeError, ValueError):
                pass
    return result


def _default_llm_result() -> dict:
    return {
        "risk_label": "guarded",
        "confidence": 50,
        "intel_summary": "",
        "intel_adjustment": {"home": 0.0, "draw": 0.0, "away": 0.0},
    }


def _run_factor_scorer(llm_result: dict):
    """
    Build a FactorScorerResult from LLM-supplied factor_scores / flags.
    Returns None if the LLM didn't output factor_scores (graceful degradation).
    """
    raw_scores = llm_result.get("factor_scores")
    if not raw_scores or not isinstance(raw_scores, dict):
        return None

    try:
        fs = FactorScores(
            team_strength=float(raw_scores.get("team_strength", 50)),
            recent_form=float(raw_scores.get("recent_form", 50)),
            availability=float(raw_scores.get("availability", 50)),
            tactical_matchup=float(raw_scores.get("tactical_matchup", 50)),
            schedule_venue=float(raw_scores.get("schedule_venue", 50)),
            motivation=float(raw_scores.get("motivation", 50)),
            odds_market=float(raw_scores.get("odds_market", 50)),
            psychological=float(raw_scores.get("psychological", 50)),
        )

        abnormal_raw = llm_result.get("abnormal_result", "none")
        try:
            abnormal = AbnormalResultType(abnormal_raw)
        except ValueError:
            abnormal = AbnormalResultType.NONE

        tournament_raw = llm_result.get("tournament_risk", "low")
        try:
            tournament = TournamentRisk(tournament_raw)
        except ValueError:
            tournament = TournamentRisk.LOW

        flags = llm_result.get("upset_flags") or []
        return score_match(fs, abnormal, tournament, active_upset_flags=flags)
    except Exception:
        return None


def _factor_result_to_dict(result) -> dict:
    return {
        "weighted_confidence": result.weighted_confidence,
        "final_confidence":    result.final_confidence,
        "risk_label":          result.risk_label.value,
        "abnormal_result":     result.abnormal_result.value,
        "tournament_risk":     result.tournament_risk.value,
        "active_upset_flags":  result.active_upset_flags,
        "upset_flag_penalty":  result.upset_flag_penalty,
        "notes":               result.notes,
        "factor_scores":       result.factor_scores.as_dict(),
    }


def save_dc_params_to_disk(params) -> Path:
    """训练完成后将 DC 参数持久化到磁盘，供 Pipeline 加载。"""
    settings = get_settings()
    params_path = Path(settings.duckdb_path).parent / "dc_params.json"
    params_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "attack": params.attack,
        "defence": params.defence,
        "home_advantage": params.home_advantage,
        "rho": params.rho,
    }
    params_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return params_path
