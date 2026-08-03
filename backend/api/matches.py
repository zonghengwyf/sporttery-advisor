import logging
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user, require_admin
from db.models import Match, Prediction, User
from db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

_last_sync_ts: float = 0.0
_SYNC_COOLDOWN = 300  # 5 分钟内不重复同步


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


def _bj_today() -> date:
    return (datetime.utcnow() + timedelta(hours=8)).date()


@router.get("/", response_model=list[MatchOut])
async def list_matches(
    sale_date: str = Query(default="today"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    global _last_sync_ts
    bj_today = _bj_today()
    today_str = str(bj_today)
    tomorrow_str = str(bj_today + timedelta(days=1))
    if sale_date == "today":
        sale_date = today_str
    needs_sync = sale_date in ("all", today_str, tomorrow_str)
    if needs_sync and time.monotonic() - _last_sync_ts > _SYNC_COOLDOWN:
        try:
            from core.data.sync import sync_daily_matches
            await sync_daily_matches(db, bj_today)
            if sale_date in ("all", tomorrow_str):
                await sync_daily_matches(db, bj_today + timedelta(days=1))
            _last_sync_ts = time.monotonic()
        except Exception as exc:
            logger.warning("实时同步竞彩赛单失败，返回缓存数据：%s", exc)

    if sale_date == "all":
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8 - 3)  # kickoff_at 存北京时间
        result = await db.execute(
            select(Match).where(Match.kickoff_at >= cutoff).order_by(Match.kickoff_at)
        )
    else:
        result = await db.execute(
            select(Match).where(Match.sale_date == sale_date).order_by(Match.kickoff_at)
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
    if match.result_locked:
        raise HTTPException(status_code=409, detail="比赛结果已锁定，无法修改")

    match.actual_result = body.actual_result
    match.result_locked = True
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
    sale_date: str = Query(default="today"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动触发赛单同步（等同步完成后再返回）。"""
    from core.data.sync import sync_daily_matches

    target = _bj_today() if sale_date == "today" else date.fromisoformat(sale_date)
    n = await sync_daily_matches(db, target)
    return {"message": f"同步完成：{sale_date}，共 {n} 场", "count": n}
