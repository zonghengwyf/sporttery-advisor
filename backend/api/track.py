"""
追踪模块 — 自动出票历史 + 赛果同步结果

GET  /api/track/runs            历史出票列表（分页）
GET  /api/track/runs/{id}       单次详情
POST /api/track/runs            手动触发出票
POST /api/track/runs/{id}/sync  手动触发该次赛果同步
GET  /api/track/summary         统计概览
"""
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.bets import _hhad_result_from_score
from db.models import AutoTicketRun, Match, User
from db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ── 序列化 ────────────────────────────────────────────────────────────────────

def _serialize_run(run: AutoTicketRun) -> dict:
    tickets = run.tickets_json or {}
    schemes = tickets.get("schemes", [])

    # 计算每个方案的盈亏（如果有 results）
    results = run.results_json or {}
    enriched_schemes = []
    for scheme in schemes:
        legs = scheme.get("legs", [])
        settled_legs = []
        all_settled = True
        all_won = True
        for leg in legs:
            mid = leg.get("match_id")
            res = results.get(str(mid)) if mid else None
            actual = res.get("actual") if res else None
            score = res.get("score") if res else None
            won = None
            if actual is not None:
                pick_map = {"主胜": "H", "平局": "D", "客胜": "A"}
                expected = pick_map.get(leg.get("pick", ""), "")
                # HHAD 让球市场：从比分推算；比分未录入时 won 为 None
                if leg.get("market") == "让球胜平负" and leg.get("handicap") is not None:
                    actual_for_leg = _hhad_result_from_score(score, leg["handicap"])
                else:
                    actual_for_leg = actual
                won = (actual_for_leg == expected) if actual_for_leg else None
                if won is None:
                    all_settled = False
            else:
                all_settled = False
            if won is False:
                all_won = False
            settled_legs.append({**leg, "actual_result": actual, "actual_score": score, "won": won})

        status = "pending"
        profit = None
        if all_settled:
            status = "won" if all_won else "lost"
            total_odds = 1.0
            for leg in legs:
                if not leg.get("void"):
                    total_odds *= leg.get("odds", 1.0)
            profit = round(run.stake * total_odds - run.stake, 2) if all_won else -run.stake

        enriched_schemes.append({**scheme, "legs": settled_legs, "status": status, "profit": profit})

    return {
        "id":           run.id,
        "run_date":     run.run_date.isoformat(),
        "trigger":      run.trigger,
        "model_info":   run.model_info,
        "match_ids":    run.match_ids,
        "stake":        run.stake,
        "schemes":      enriched_schemes,
        "sync_status":  run.sync_status,
        "sync_error":   run.sync_error,
        "created_at":   run.created_at.isoformat(),
        "synced_at":    run.synced_at.isoformat() if run.synced_at else None,
    }


# ── 端点 ──────────────────────────────────────────────────────────────────────

@router.get("/runs")
async def list_runs(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Include user_id=0 (system/scheduler runs) so scheduled jobs appear alongside manual ones
    _uid_filter = or_(AutoTicketRun.user_id == current_user.id, AutoTicketRun.user_id == 0)
    stmt = (
        select(AutoTicketRun)
        .where(_uid_filter)
        .order_by(AutoTicketRun.run_date.desc(), AutoTicketRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()
    return [_serialize_run(r) for r in runs]


@router.get("/summary")
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _uid_filter = or_(AutoTicketRun.user_id == current_user.id, AutoTicketRun.user_id == 0)
    result = await db.execute(
        select(AutoTicketRun).where(_uid_filter)
    )
    runs = result.scalars().all()

    total_runs = len(runs)
    synced_runs = [r for r in runs if r.sync_status in ("synced", "partial")]

    total_stake = 0.0
    total_payout = 0.0
    won_schemes = 0
    total_schemes = 0

    for run in synced_runs:
        serialized = _serialize_run(run)
        for scheme in serialized["schemes"]:
            if scheme["status"] == "pending":
                continue
            total_schemes += 1
            total_stake += run.stake
            if scheme["status"] == "won":
                won_schemes += 1
                legs = scheme.get("legs", [])
                odds = 1.0
                for leg in legs:
                    if not leg.get("void"):
                        odds *= leg.get("odds", 1.0)
                total_payout += run.stake * odds

    hit_rate = round(won_schemes / total_schemes * 100, 1) if total_schemes > 0 else 0.0
    roi = round((total_payout - total_stake) / total_stake * 100, 1) if total_stake > 0 else 0.0
    profit = round(total_payout - total_stake, 2)

    return {
        "total_runs":    total_runs,
        "synced_runs":   len(synced_runs),
        "total_schemes": total_schemes,
        "won_schemes":   won_schemes,
        "hit_rate":      hit_rate,
        "roi":           roi,
        "profit":        profit,
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await db.get(AutoTicketRun, run_id)
    if not run or (run.user_id != current_user.id and run.user_id != 0):
        raise HTTPException(status_code=404, detail="记录不存在")
    return _serialize_run(run)


@router.post("/runs", status_code=201)
async def trigger_run(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动触发今日自动出票。"""
    from workers.tasks import run_auto_ticket
    try:
        run_id = await run_auto_ticket(user_id=current_user.id, trigger="manual", db=db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"出票失败：{exc}")
    if run_id < 0:
        raise HTTPException(status_code=422, detail="今日无可用赛事或预测数据，请先触发赛事分析")
    run = await db.get(AutoTicketRun, run_id)
    return _serialize_run(run)


@router.post("/runs/{run_id}/sync")
async def sync_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动触发该次记录的赛果同步。"""
    run = await db.get(AutoTicketRun, run_id)
    if not run or (run.user_id != current_user.id and run.user_id != 0):
        raise HTTPException(status_code=404, detail="记录不存在")

    from workers.tasks import _sync_one_auto_ticket_run
    await _sync_one_auto_ticket_run(run, db)
    await db.commit()
    await db.refresh(run)
    return _serialize_run(run)
