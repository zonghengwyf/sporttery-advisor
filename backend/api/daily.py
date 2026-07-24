"""今日推荐 API

GET  /daily/today-plan      → 返回今日串关方案（无需手动选场）
POST /daily/run-analysis    → 触发多模型集成分析（今日所有赛事）
GET  /daily/model-accuracy  → 各模型历史准确率
"""
from __future__ import annotations

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from db.models import Match, Prediction, User
from db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 今日串关方案 ──────────────────────────────────────────────────────────────

@router.get("/today-plan")
async def get_today_plan(
    multiplier: int = Query(default=2, ge=1, le=10),
    budget: float = Query(default=100.0, ge=2.0, le=10000.0),
    target_date: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    返回今日串关方案。
    如果当日预测已存在直接使用，否则提示先运行分析。
    """
    sale_date = target_date or str(date.today())

    # 取今日所有赛事
    matches_result = await db.execute(
        select(Match)
        .where(Match.sale_date == sale_date)
        .order_by(Match.kickoff_at)
    )
    matches = matches_result.scalars().all()
    if not matches:
        return {
            "date": sale_date,
            "plans": [],
            "match_count": 0,
            "analyzed_count": 0,
            "message": "今日暂无赛事，请先同步赛单",
        }

    # 取最新预测（单条 subquery，避免 N+1）
    match_ids = [m.id for m in matches]
    subq = (
        select(func.max(Prediction.id).label("max_id"))
        .where(Prediction.match_id.in_(match_ids))
        .group_by(Prediction.match_id)
        .subquery()
    )
    preds_result = await db.execute(
        select(Prediction).where(Prediction.id.in_(select(subq.c.max_id)))
    )
    preds_by_match = {p.match_id: p for p in preds_result.scalars().all()}

    enriched: list[dict] = []
    for m in matches:
        pred = preds_by_match.get(m.id)
        if pred:
            ensemble_votes = (pred.tickets or {}).get("ensemble_votes", [])
            enriched.append({
                "match": m,
                "prediction": pred,
                "ensemble_votes": ensemble_votes,
            })

    analyzed_count = len(enriched)
    if analyzed_count == 0:
        return {
            "date": sale_date,
            "plans": [],
            "match_count": len(matches),
            "analyzed_count": 0,
            "message": "今日赛事暂无预测数据，请点击「立即分析」",
        }

    # 生成串关方案
    from core.tickets.generator import TicketGenerator
    gen = TicketGenerator()
    plans = gen.generate_parlay_plans(enriched, budget=budget, multiplier=multiplier)

    return {
        "date": sale_date,
        "plans": [p.to_dict() for p in plans],
        "match_count": len(matches),
        "analyzed_count": analyzed_count,
        "multiplier": multiplier,
        "budget": budget,
        "message": None,
    }


# ── 触发多模型集成分析 ────────────────────────────────────────────────────────

class RunAnalysisRequest(BaseModel):
    target_date: str | None = None
    multiplier: int = 2
    budget: float = 100.0


@router.post("/run-analysis")
async def run_ensemble_analysis(
    req: RunAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    触发今日多模型集成分析。
    按 Settings > 分析配置 中设置的模型列表并发运行，取多数票。
    """
    sale_date = req.target_date or str(date.today())

    matches_result = await db.execute(
        select(Match)
        .where(Match.sale_date == sale_date)
        .order_by(Match.kickoff_at)
    )
    matches = matches_result.scalars().all()
    if not matches:
        raise HTTPException(status_code=404, detail="今日暂无赛事，请先同步赛单")

    # 读取集成配置 + 可用模型
    from core.ensemble import (
        EnsembleAnalyzer, get_active_llm_configs, get_ensemble_config, votes_to_dict
    )
    from core.pipeline import DailyPipeline, _compute_ev

    ensemble_cfg = await get_ensemble_config(db, current_user.id)
    llm_configs = await get_active_llm_configs(db, current_user.id, ensemble_cfg)

    if not llm_configs:
        raise HTTPException(
            status_code=400,
            detail="未找到可用的 AI 模型配置，请在设置页添加模型"
        )

    pipeline = DailyPipeline()
    analyzer = EnsembleAnalyzer(pipeline)
    run_id = str(uuid.uuid4())[:8]

    analyzed = 0
    errors = 0
    results = []

    for match in matches:
        try:
            # Layer 1: 统计模型（共享）
            stat_probs, fused_probs = await pipeline._layer1_stats(match)

            # Layer 2: 多模型并发
            ensemble_result = await analyzer.analyze_match_ensemble(
                session=db,
                match=match,
                llm_configs=llm_configs,
                config=ensemble_cfg,
                stat_probs=stat_probs,
                fused_probs=fused_probs,
            )

            # 应用情报调整
            from core.modeling.fusion import FusedProbs, PredictionFusion
            llm_result = ensemble_result.aggregated_llm_result
            adj = llm_result.get("intel_adjustment")
            fusion = PredictionFusion()
            if adj and any(v != 0 for v in adj.values()):
                base = FusedProbs(**fused_probs)
                fused_probs = fusion.apply_intelligence(base, adj).to_dict()

            fused_probs = _compute_ev(fused_probs, match.sporttery_odds)

            # Layer 3: 票型生成（在票型里记录 ensemble_votes）
            tickets = pipeline.ticket_gen.generate_for_match(match, fused_probs, llm_result)
            tickets["ensemble_votes"] = votes_to_dict(ensemble_result.votes)
            tickets["consensus_ratio"] = ensemble_result.consensus_ratio
            tickets["final_outcome"] = ensemble_result.final_outcome

            pred = Prediction(
                match_id=match.id,
                run_id=run_id,
                stat_probs=stat_probs,
                fused_probs=fused_probs,
                intel_summary=llm_result.get("intel_summary", ""),
                risk_label=llm_result.get("risk_label", "guarded"),
                confidence=float(llm_result.get("confidence", 50)) / 100.0,
                tickets=tickets,
                llm_provider="ensemble",
                llm_model=(lambda s: s if len(s) <= 100 else s[:97] + "...")(
                    "+".join(f"{c.provider.value}/{c.model}" for c in llm_configs)
                ),
            )
            db.add(pred)
            analyzed += 1
            results.append({
                "match_id": match.id,
                "home": match.home_team,
                "away": match.away_team,
                "final_outcome": ensemble_result.final_outcome,
                "consensus": f"{ensemble_result.consensus_ratio:.0%}",
                "models_voted": len(ensemble_result.votes),
            })
        except Exception as exc:
            logger.error("集成分析失败 match_id=%d: %s", match.id, exc, exc_info=True)
            errors += 1

    await db.commit()

    return {
        "run_id": run_id,
        "date": sale_date,
        "analyzed": analyzed,
        "errors": errors,
        "models_used": [f"{c.provider.value}/{c.model}" for c in llm_configs],
        "results": results,
    }


# ── 各模型历史准确率 ──────────────────────────────────────────────────────────

@router.get("/model-accuracy")
async def get_model_accuracy(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回每个模型的历史预测准确率（用于权重参考）。"""
    from datetime import timedelta
    from sqlalchemy import and_

    cutoff = date.today() - timedelta(days=days)
    result = await db.execute(
        select(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .where(
            Match.sale_date >= str(cutoff),
            Match.actual_result.isnot(None),
        )
        .order_by(Prediction.created_at.desc())
    )
    rows = result.all()

    # 从 ensemble_votes 中拆分各模型的准确率
    model_stats: dict[str, dict] = {}

    for pred, match in rows:
        actual = match.actual_result
        votes = (pred.tickets or {}).get("ensemble_votes", [])

        if not votes:
            # 单模型记录
            model_key = f"{pred.llm_provider}/{pred.llm_model}"
            if model_key not in model_stats:
                model_stats[model_key] = {"correct": 0, "total": 0}
            fp = pred.fused_probs or pred.stat_probs or {}
            probs = [fp.get("home", 0), fp.get("draw", 0), fp.get("away", 0)]
            predicted = ["H", "D", "A"][probs.index(max(probs))] if any(probs) else None
            if predicted:
                model_stats[model_key]["total"] += 1
                if predicted == actual:
                    model_stats[model_key]["correct"] += 1
        else:
            for vote in votes:
                model_key = f"{vote.get('provider', '')}/{vote.get('model', '')}"
                if not model_key or model_key == "/":
                    continue
                if model_key not in model_stats:
                    model_stats[model_key] = {"correct": 0, "total": 0}
                outcome = vote.get("outcome")
                if outcome and not vote.get("error"):
                    model_stats[model_key]["total"] += 1
                    if outcome == actual:
                        model_stats[model_key]["correct"] += 1

    accuracy_list = []
    for model_key, stats in model_stats.items():
        total = stats["total"]
        correct = stats["correct"]
        acc = correct / total if total > 0 else None
        accuracy_list.append({
            "model": model_key,
            "total": total,
            "correct": correct,
            "accuracy": round(acc, 4) if acc is not None else None,
            "accuracy_pct": f"{acc * 100:.1f}%" if acc is not None else "—",
        })

    accuracy_list.sort(key=lambda x: x["accuracy"] or 0, reverse=True)
    return {"days": days, "models": accuracy_list}
