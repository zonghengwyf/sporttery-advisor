import logging
import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from db.models import BetRecord, Match, Prediction, User
from db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ── 请求 / 响应模型 ────────────────────────────────────────────────────────────

class LegIn(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    pick: str        # "主胜" / "平局" / "客胜"
    pick_code: str   # "3" / "1" / "0"
    odds: float
    market: str = "胜平负"        # "胜平负" | "让球胜平负"
    handicap: float | None = None  # 让球数，正=主让，负=受让；仅 HHAD 市场有效

    @field_validator("handicap")
    @classmethod
    def handicap_must_be_integer(cls, v: float | None) -> float | None:
        if v is not None:
            if not math.isfinite(v):
                raise ValueError("让球数必须为有限数值")
            if v != int(v):
                raise ValueError("竞彩让球数必须为整数（如 1.0、-1.0），不支持半球让球")
        return v


class CreateBetRequest(BaseModel):
    prediction_id: int | None = None
    plan_id: str                    # conservative / balanced / high_odds / manual
    legs: list[LegIn]
    stake: float
    expected_payout: float | None = None
    note: str | None = None


class UpdateBetRequest(BaseModel):
    status: str | None = None       # won / lost / void
    payout: float | None = None
    note: str | None = None


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _hhad_result_from_score(actual_score: str | None, handicap: float) -> str | None:
    """从比分和让球数计算 HHAD 结果（H/D/A）。无比分时返回 None。"""
    if not actual_score:
        return None
    try:
        home_g, away_g = (int(x) for x in actual_score.split("-"))
    except Exception:
        return None
    # handicap < 0: home gives |h| balls; handicap > 0: home receives h balls
    # effective home score = home_g + h; compare vs away_g
    h = int(round(handicap))
    adjusted = (home_g - away_g) + h
    if adjusted > 0:
        return "H"
    if adjusted == 0:
        return "D"
    return "A"


async def _enrich_record(record: BetRecord, db: AsyncSession) -> dict:
    """将 BetRecord ORM 对象序列化为前端所需格式，补充赛事状态。"""
    legs_out = []
    all_results: list[str | None] = []
    for leg in record.legs:
        mid = leg.get("match_id")
        match: Match | None = await db.get(Match, mid) if mid else None
        # HHAD 让球盘：必须从实际比分推算让球结算结果，不能用原始 H/D/A
        # 若比分暂未记录，保持 None 使注单留在 pending 状态，等待比分录入后再结算
        if match and leg.get("market") == "让球胜平负" and leg.get("handicap") is not None:
            actual = _hhad_result_from_score(match.actual_score, leg["handicap"])
        else:
            actual = match.actual_result if match else None
        all_results.append(actual)
        legs_out.append({
            **leg,
            "actual_result": actual,
            "actual_score": match.actual_score if match else None,
            "kickoff_at": match.kickoff_at.isoformat() if match and match.kickoff_at else None,
            "league": match.league if match else None,
        })

    # 自动计算状态（仅 pending 时推算）
    computed_status = record.status
    if record.status == "pending" and all(r is not None for r in all_results):
        wins = _evaluate_legs(record.legs, all_results)
        computed_status = "won" if wins else "lost"

    return {
        "id":               record.id,
        "plan_id":          record.plan_id,
        "legs":             legs_out,
        "stake":            record.stake,
        "expected_payout":  record.expected_payout,
        "effective_odds":   record.effective_odds,
        "bet_at":           record.bet_at.isoformat(),
        "status":           computed_status,
        "payout":           record.payout,
        "note":             record.note,
        "prediction_id":    record.prediction_id,
        "profit":           _calc_profit(record.stake, record.payout, computed_status),
    }


def _evaluate_legs(legs: list[dict], results: list[str | None]) -> bool:
    """串关全中才算赢：每腿 pick 对应 H/D/A 与 actual_result 比较。"""
    mapping = {"主胜": "H", "平局": "D", "平": "D", "客胜": "A"}
    for leg, actual in zip(legs, results):
        if leg.get("void"):
            continue
        expected = mapping.get(leg.get("pick", ""), "")
        if actual != expected:
            return False
    return True


def _calc_profit(stake: float, payout: float | None, status: str) -> float | None:
    if status == "pending":
        return None
    if status == "won" and payout is not None:
        return round(payout - stake, 2)
    if status == "lost":
        return -stake
    return 0.0


# ── 端点 ──────────────────────────────────────────────────────────────────────

@router.post("/", status_code=201)
async def create_bet(
    req: CreateBetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not req.legs:
        raise HTTPException(status_code=400, detail="至少需要一关投注")
    if req.stake <= 0:
        raise HTTPException(status_code=400, detail="投注金额必须大于 0")

    total_odds = 1.0
    for leg in req.legs:
        total_odds *= leg.odds

    record = BetRecord(
        user_id=current_user.id,
        prediction_id=req.prediction_id,
        plan_id=req.plan_id,
        legs=[leg.model_dump() for leg in req.legs],
        stake=req.stake,
        expected_payout=req.expected_payout or round(req.stake * total_odds, 2),
        effective_odds=round(total_odds, 4),
        note=req.note,
        bet_at=datetime.utcnow(),
        status="pending",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return await _enrich_record(record, db)


@router.get("/")
async def list_bets(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(BetRecord).where(BetRecord.user_id == current_user.id)
    if status:
        stmt = stmt.where(BetRecord.status == status)
    stmt = stmt.order_by(BetRecord.bet_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    records = result.scalars().all()
    return [await _enrich_record(r, db) for r in records]


@router.get("/summary")
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """战绩概览：总投入、总回报、ROI、命中率、待结算金额。"""
    result = await db.execute(
        select(BetRecord).where(BetRecord.user_id == current_user.id)
    )
    records = result.scalars().all()

    total_stake = sum(r.stake for r in records)
    pending_stake = sum(r.stake for r in records if r.status == "pending")

    settled = [r for r in records if r.status in ("won", "lost")]
    total_payout = sum((r.payout or 0) for r in records if r.status == "won")
    won_count = sum(1 for r in settled if r.status == "won")

    settled_stake = sum(r.stake for r in settled)
    roi = round((total_payout - settled_stake) / settled_stake * 100, 1) if settled_stake > 0 else 0.0
    hit_rate = round(won_count / len(settled) * 100, 1) if settled else 0.0
    profit = round(total_payout - settled_stake, 2)

    return {
        "total_stake":   round(total_stake, 2),
        "total_payout":  round(total_payout, 2),
        "profit":        profit,
        "roi":           roi,
        "hit_rate":      hit_rate,
        "pending_stake": round(pending_stake, 2),
        "total_bets":    len(records),
        "settled_bets":  len(settled),
        "won_bets":      won_count,
    }


@router.patch("/{bet_id}")
async def update_bet(
    bet_id: int,
    req: UpdateBetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await db.get(BetRecord, bet_id)
    if not record or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="投注记录不存在")

    if req.status is not None:
        if req.status not in ("won", "lost", "void"):
            raise HTTPException(status_code=400, detail="状态值无效")
        record.status = req.status
    if req.payout is not None:
        record.payout = req.payout
    if req.note is not None:
        record.note = req.note

    await db.commit()
    return await _enrich_record(record, db)


@router.delete("/{bet_id}", status_code=204)
async def delete_bet(
    bet_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await db.get(BetRecord, bet_id)
    if not record or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="投注记录不存在")
    if record.status != "pending":
        raise HTTPException(status_code=400, detail="已结算的记录不能删除")
    await db.delete(record)
    await db.commit()
