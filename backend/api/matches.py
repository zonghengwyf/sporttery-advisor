import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user, require_admin
from db.models import Match, Prediction, User
from db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


class MatchOut(BaseModel):
    id: int
    sporttery_id: str
    match_no: str | None = None
    home_team: str
    away_team: str
    league: str
    kickoff_at: str
    sale_date: str
    available_markets: list
    sporttery_odds: dict | None
    overseas_odds: dict | None
    is_tournament: bool

    model_config = {"from_attributes": True}

    @field_validator("kickoff_at", mode="before")
    @classmethod
    def coerce_kickoff(cls, v):
        return str(v)


@router.get("/", response_model=list[MatchOut])
async def list_matches(
    sale_date: str = Query(default=str(date.today())),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Match).where(Match.sale_date == sale_date).order_by(Match.kickoff_at)
    )
    matches = result.scalars().all()

    # 仅今日无数据时才自动同步，其他日期不触发（防止被非认证请求滥用）
    if not matches and sale_date == str(date.today()):
        try:
            from core.data.sync import sync_daily_matches
            n = await sync_daily_matches(db, date.today())
            if n > 0:
                result = await db.execute(
                    select(Match).where(Match.sale_date == sale_date).order_by(Match.kickoff_at)
                )
                matches = result.scalars().all()
        except Exception as exc:
            logger.warning("自动同步竞彩赛单失败：%s", exc)

    return matches


@router.get("/{match_id}", response_model=MatchOut)
async def get_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="比赛不存在")
    return match


class ResultIn(BaseModel):
    actual_result: str   # H / D / A
    actual_score: str | None = None  # "2-1"


@router.patch("/{match_id}/result")
async def set_match_result(
    match_id: int,
    body: ResultIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """录入比赛实际结果（H/D/A），同步写入 Match 和 DuckDB 回测记录。仅管理员可操作。"""
    if body.actual_result not in ("H", "D", "A"):
        raise HTTPException(status_code=400, detail="actual_result 须为 H / D / A")

    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if match.result_locked:
        raise HTTPException(status_code=409, detail="比赛结果已锁定，无法修改")

    match.actual_result = body.actual_result
    if body.actual_score:
        match.actual_score = body.actual_score

    # 同步写 DuckDB 回测记录
    result = await db.execute(
        select(Prediction)
        .where(Prediction.match_id == match_id)
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    pred = result.scalar_one_or_none()
    if pred and pred.stat_probs:
        try:
            from config import get_settings
            from core.data.snapshot import SnapshotManager
            snap = SnapshotManager(db_path=get_settings().duckdb_path)
            await snap.save_backtest_result(
                match_id=match_id,
                predicted=pred.fused_probs or pred.stat_probs,
                actual=body.actual_result,
                user_id=pred.user_id,
            )
            snap.close()
        except Exception as exc:
            logger.warning("DuckDB 回测写入失败: %s", exc)

    await db.commit()
    return {"match_id": match_id, "actual_result": body.actual_result, "actual_score": body.actual_score}


@router.post("/sync")
async def trigger_sync(
    sale_date: str = Query(default=str(date.today())),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动触发赛单同步（等同步完成后再返回）。"""
    from core.data.sync import sync_daily_matches

    target = date.fromisoformat(sale_date)
    n = await sync_daily_matches(db, target)
    return {"message": f"同步完成：{sale_date}，共 {n} 场", "count": n}
