from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from db.models import Prediction, Match, User
from db.session import get_db

router = APIRouter()


@router.get("/metrics")
async def get_backtest_metrics(
    days: int = Query(default=30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回过去 N 天的回测精度指标（Brier、Log-loss、RPS、ECE）"""
    try:
        from config import get_settings
        from core.data.snapshot import SnapshotManager

        settings = get_settings()
        snapshot = SnapshotManager(db_path=settings.duckdb_path)
        metrics = await snapshot.get_backtest_metrics(days=days)
        snapshot.close()

        if metrics:
            return {"days": days, "metrics": metrics}
    except Exception:
        pass

    return {
        "days": days,
        "metrics": {
            "brier": None,
            "log_loss": None,
            "rps": None,
            "ece": None,
        },
        "message": "暂无回测数据，完成首轮分析并录入结果后自动更新",
    }


@router.get("/history")
async def get_prediction_history(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回历史预测记录（用于前端回测报告页）"""
    from datetime import date, timedelta
    from sqlalchemy import and_

    cutoff = date.today() - timedelta(days=days)
    result = await db.execute(
        select(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .where(Match.sale_date >= cutoff)
        .order_by(Match.kickoff_at.desc())
        .limit(100)
    )
    rows = result.all()

    history = []
    for pred, match in rows:
        # 推断预测方向（与 risk_label 结合）
        fp = pred.fused_probs or pred.stat_probs or {}
        probs = [fp.get("home", 0), fp.get("draw", 0), fp.get("away", 0)]
        predicted_outcome = ["H", "D", "A"][probs.index(max(probs))] if any(probs) else None
        correct = (
            predicted_outcome == match.actual_result
            if predicted_outcome and match.actual_result
            else None
        )
        history.append({
            "match_id":         match.id,
            "home_team":        match.home_team,
            "away_team":        match.away_team,
            "league":           match.league,
            "kickoff_at":       str(match.kickoff_at),
            "stat_probs":       pred.stat_probs,
            "fused_probs":      pred.fused_probs,
            "risk_label":       pred.risk_label,
            "confidence":       pred.confidence,
            "actual_result":    match.actual_result,
            "actual_score":     match.actual_score,
            "predicted_outcome": predicted_outcome,
            "correct":          correct,
        })

    return {"history": history, "days": days}


@router.post("/record")
async def record_result(
    match_id: int,
    actual: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """录入比赛实际结果并更新回测指标（actual: H/D/A）。"""
    if actual not in ("H", "D", "A"):
        from fastapi import HTTPException
        raise HTTPException(400, detail="actual 须为 H / D / A")

    pred_result = await db.execute(
        select(Prediction)
        .where(Prediction.match_id == match_id)
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    pred = pred_result.scalar_one_or_none()
    if not pred or not pred.stat_probs:
        from fastapi import HTTPException
        raise HTTPException(404, detail="未找到该场比赛的预测记录")

    try:
        from config import get_settings
        from core.data.snapshot import SnapshotManager

        settings = get_settings()
        snapshot = SnapshotManager(db_path=settings.duckdb_path)
        await snapshot.save_backtest_result(
            match_id=match_id,
            predicted=pred.stat_probs,
            actual=actual,
        )
        snapshot.close()
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(500, detail=f"回测记录保存失败: {exc}")

    return {"message": "回测结果已录入"}
