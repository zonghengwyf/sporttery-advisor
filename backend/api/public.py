"""公开分享端点（无需认证）

GET /api/public/plan  → 返回今日推荐方案（只读，供分享链接使用）
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Match, Prediction
from db.session import get_db

router = APIRouter()


@router.get("/plan")
async def get_public_plan(
    multiplier: int = Query(default=2, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
):
    """
    公开端点：返回今日推荐方案，不要求登录。
    仅返回已有预测结果，不触发新分析。
    """
    sale_date = str(date.today())

    matches_result = await db.execute(
        select(Match)
        .where(Match.sale_date == sale_date)
        .order_by(Match.kickoff_at)
    )
    matches = matches_result.scalars().all()

    if not matches:
        return {"date": sale_date, "plans": [], "message": "今日暂无赛事"}

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

    if not enriched:
        return {
            "date": sale_date,
            "plans": [],
            "match_count": len(matches),
            "analyzed_count": 0,
            "message": "今日尚未运行分析",
        }

    from core.tickets.generator import TicketGenerator
    gen = TicketGenerator()
    plans = gen.generate_parlay_plans(enriched, budget=100.0, multiplier=multiplier)

    # 精简输出（去掉 model_votes 中的敏感字段）
    def sanitize_plan(p):
        d = p.to_dict()
        for leg in d.get("legs", []):
            leg.pop("model_votes", None)
        return d

    return {
        "date": sale_date,
        "plans": [sanitize_plan(p) for p in plans],
        "match_count": len(matches),
        "analyzed_count": len(enriched),
        "multiplier": multiplier,
    }
