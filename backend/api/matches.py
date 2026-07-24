from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from db.models import Match, Prediction, User
from db.session import get_db

router = APIRouter()


class MatchOut(BaseModel):
    id: int
    sporttery_id: str
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

    def model_post_init(self, __context):
        self.kickoff_at = str(self.kickoff_at)


@router.get("/", response_model=list[MatchOut])
async def list_matches(
    sale_date: str = Query(default=str(date.today())),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Match)
        .where(Match.sale_date == sale_date)
        .order_by(Match.kickoff_at)
    )
    return result.scalars().all()


@router.get("/{match_id}", response_model=MatchOut)
async def get_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
):
    """录入比赛实际结果（H/D/A），同步写入 Match 和 DuckDB 回测记录。"""
    if body.actual_result not in ("H", "D", "A"):
        raise HTTPException(status_code=400, detail="actual_result 须为 H / D / A")

    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="比赛不存在")

    match.actual_result = body.actual_result
    if body.actual_score:
        match.actual_score = body.actual_score

    # 同步写 DuckDB 回测记录
    result = await db.execute(
        select(Prediction)
        .where(Prediction.match_id == match_id)  # type: ignore[attr-defined]
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
            )
            snap.close()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("DuckDB 回测写入失败: %s", exc)

    await db.commit()
    return {"match_id": match_id, "actual_result": body.actual_result, "actual_score": body.actual_score}


@router.post("/sync")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    sale_date: str = Query(default=str(date.today())),
    current_user: User = Depends(get_current_user),
):
    """手动触发赛单同步（管理员或普通用户均可）。"""
    from workers.tasks import run_daily_sync
    from datetime import date as _date

    target = _date.fromisoformat(sale_date)
    background_tasks.add_task(run_daily_sync, target)
    return {"message": f"已触发 {sale_date} 赛单同步，后台执行中"}
