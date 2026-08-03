import logging
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_optional_user, require_admin
from db.models import Prediction, Match, User
from db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/metrics")
async def get_backtest_metrics(
    days: int = Query(default=30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """返回过去 N 天的回测精度指标（Brier、Log-loss、RPS、ECE）及趋势图数据。"""
    metrics = None
    chart = {"dates": [], "brier_series": [], "baseline_series": []}
    user_id = current_user.id if current_user else 0

    try:
        from config import get_settings
        from core.data.snapshot import SnapshotManager

        cfg = get_settings()
        snap = SnapshotManager(db_path=cfg.duckdb_path)
        metrics = await snap.get_backtest_metrics(days=days, user_id=user_id)
        chart = await snap.get_chart_data(days=days, user_id=user_id)
        snap.close()
    except Exception as e:
        logger.warning("DuckDB 回测初始化失败: %s", e, exc_info=True)

    return {
        "days": days,
        "metrics": metrics or {
            "brier": None,
            "log_loss": None,
            "rps": None,
            "ece": None,
            "avg_clv": None,
            "clv_positive_ratio": None,
            "n_with_clv": 0,
        },
        "chart": chart,
        "message": None if metrics else "暂无回测数据，录入比赛结果后自动更新",
    }


@router.get("/history")
async def get_prediction_history(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """返回历史预测记录（含模型准确率统计）。"""
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=days)
    if current_user:
        user_filter = or_(Prediction.user_id == current_user.id, Prediction.user_id.is_(None))
    else:
        user_filter = Prediction.user_id.is_(None)

    result = await db.execute(
        select(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .where(
            Match.sale_date >= str(cutoff),
            user_filter,
        )
        .order_by(Match.kickoff_at.desc())
        .limit(100)
    )
    rows = result.all()

    history = []
    model_stats: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0, "provider": "", "model": ""})

    for pred, match in rows:
        fp = pred.fused_probs or pred.stat_probs or {}
        probs = [fp.get("home", 0), fp.get("draw", 0), fp.get("away", 0)]
        predicted_outcome = ["H", "D", "A"][probs.index(max(probs))] if any(probs) else None
        correct = (
            predicted_outcome == match.actual_result
            if predicted_outcome and match.actual_result
            else None
        )
        history.append({
            "match_id":          match.id,
            "home_team":         match.home_team,
            "away_team":         match.away_team,
            "league":            match.league,
            "kickoff_at":        str(match.kickoff_at),
            "stat_probs":        pred.stat_probs,
            "fused_probs":       pred.fused_probs,
            "risk_label":        pred.risk_label,
            "confidence":        pred.confidence,
            "actual_result":     match.actual_result,
            "actual_score":      match.actual_score,
            "predicted_outcome": predicted_outcome,
            "correct":           correct,
        })

        # 统计各模型准确率（仅对已有实际结果的场次统计）
        if match.actual_result:
            tickets = pred.tickets or {}
            ensemble_votes = tickets.get("ensemble_votes", [])
            if ensemble_votes:
                for vote in ensemble_votes:
                    if vote.get("error"):
                        continue
                    key = f"{vote.get('provider', '')}/{vote.get('model', '')}"
                    ms = model_stats[key]
                    ms["provider"] = vote.get("provider", "")
                    ms["model"] = vote.get("model", "")
                    ms["total"] += 1
                    if vote.get("outcome") == match.actual_result:
                        ms["correct"] += 1
            elif pred.llm_provider and pred.llm_model:
                key = f"{pred.llm_provider}/{pred.llm_model}"
                ms = model_stats[key]
                ms["provider"] = pred.llm_provider
                ms["model"] = pred.llm_model
                ms["total"] += 1
                if correct:
                    ms["correct"] += 1

    model_accuracy_list = []
    for key, ms in model_stats.items():
        total = ms["total"]
        if total == 0:
            continue
        model_accuracy_list.append({
            "key":      key,
            "provider": ms["provider"],
            "model":    ms["model"],
            "total":    total,
            "correct":  ms["correct"],
            "accuracy": round(ms["correct"] / total, 3),
        })
    model_accuracy_list.sort(key=lambda x: x["accuracy"], reverse=True)

    return {
        "history":     history,
        "days":        days,
        "model_stats": model_accuracy_list,
    }


@router.post("/record")
async def record_result(
    match_id: int,
    actual: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """录入比赛实际结果并更新回测指标（actual: H/D/A）。仅管理员可操作。"""
    if actual not in ("H", "D", "A"):
        raise HTTPException(400, detail="actual 须为 H / D / A")

    pred_result = await db.execute(
        select(Prediction)
        .where(Prediction.match_id == match_id)
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    pred = pred_result.scalar_one_or_none()
    if not pred or not pred.stat_probs:
        raise HTTPException(404, detail="未找到该场比赛的预测记录")

    try:
        from config import get_settings
        from core.data.snapshot import SnapshotManager, compute_clv_fields

        cfg = get_settings()
        snap = SnapshotManager(db_path=cfg.duckdb_path)
        try:
            # CLV（ADR-006）：与自动写入同口径，避免手动录入覆盖丢 CLV
            match = await db.get(Match, match_id)
            recommended = (pred.tickets or {}).get("final_outcome")
            pick, entry_odds, close_odds, clv = await compute_clv_fields(
                snap, match_id, pred.fused_probs or pred.stat_probs,
                match.sporttery_odds if match else None, recommended,
            )
            await snap.save_backtest_result(
                match_id=match_id,
                predicted=pred.fused_probs or pred.stat_probs,
                actual=actual,
                user_id=pred.user_id or 0,
                market_odds=match.sporttery_odds if match else None,
                pick=pick,
                entry_odds=entry_odds,
                close_odds=close_odds,
                clv=clv,
            )
        finally:
            snap.close()
    except Exception as exc:
        raise HTTPException(500, detail=f"回测记录保存失败: {exc}")

    return {"message": "回测结果已录入"}
