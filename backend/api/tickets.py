from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Prediction
from db.session import get_db

router = APIRouter()


class TicketsRequest(BaseModel):
    match_ids: list[int]
    budget: float | None = None


class TicketsOut(BaseModel):
    conservative: dict   # 稳健票
    balanced: dict       # 均衡票
    high_odds: dict      # 博高赔票
    scoreline: dict      # 比分小注
    stake_allocation: dict  # 资金分配


@router.post("/generate", response_model=TicketsOut)
async def generate_tickets(
    req: TicketsRequest,
    db: AsyncSession = Depends(get_db),
):
    predictions = []
    for mid in req.match_ids:
        result = await db.execute(
            select(Prediction)
            .where(Prediction.match_id == mid)
            .order_by(Prediction.created_at.desc())
            .limit(1)
        )
        pred = result.scalar_one_or_none()
        if pred and pred.tickets:
            predictions.append(pred)

    if not predictions:
        raise HTTPException(status_code=404, detail="所选比赛暂无预测数据，请先运行分析")

    budget = req.budget or 100.0
    from core.tickets.generator import TicketGenerator
    generator = TicketGenerator()
    tickets = generator.combine(predictions, budget)
    return tickets


@router.get("/match/{match_id}")
async def get_match_tickets(
    match_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取单场比赛的原始票型数据（含 raw_analysis）。"""
    result = await db.execute(
        select(Prediction)
        .where(Prediction.match_id == match_id)
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    pred = result.scalar_one_or_none()
    if not pred or not pred.tickets:
        return None
    return pred.tickets
