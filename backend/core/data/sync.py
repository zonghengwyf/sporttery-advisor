"""赛单同步 — 从竞彩官方接口拉取并 upsert 到 PostgreSQL。"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Match

logger = logging.getLogger(__name__)


async def sync_daily_matches(session: AsyncSession, target_date: date) -> int:
    """拉取指定日期竞彩赛单并 upsert 到 PostgreSQL，返回写入场次数。"""
    from core.data.providers.sporttery import ProviderError, fetch_today

    try:
        rows = await asyncio.to_thread(fetch_today, target_date)
    except ProviderError as exc:
        logger.error("竞彩数据拉取失败：%s", exc)
        return 0

    if not rows:
        logger.info("竞彩官方无 %s 赛单数据", target_date)
        return 0

    upserted = 0
    for row in rows:
        if not row["sporttery_id"]:
            continue
        result = await session.execute(
            select(Match).where(Match.sporttery_id == row["sporttery_id"])
        )
        match = result.scalar_one_or_none()

        kickoff = datetime.fromisoformat(row["kickoff_at"])
        available = row.get("available_markets", [])

        # 合并 had + hhad 到同一字段，兼容原有 {home,draw,away} 结构
        had_odds = row.get("sporttery_odds")
        hhad_odds = row.get("hhad_odds")
        stored_odds: dict | None = None
        if had_odds:
            stored_odds = dict(had_odds)
            if hhad_odds:
                stored_odds["hhad"] = hhad_odds

        if match is None:
            match = Match(
                sporttery_id=row["sporttery_id"],
                match_no=row.get("match_no") or None,
                home_team=row["home_team"],
                away_team=row["away_team"],
                league=row["league"],
                kickoff_at=kickoff,
                sale_date=row["sale_date"],
                available_markets=available,
                sporttery_odds=stored_odds,
                sporttery_odds_open=stored_odds,  # 首次写入即为开盘赔率
                overseas_odds=None,
                is_tournament=False,
            )
            session.add(match)
        else:
            match.sporttery_odds = stored_odds
            match.available_markets = available
            match.match_no = row.get("match_no") or match.match_no
            # sporttery_odds_open 只在首次创建时设置，后续不覆盖
            if match.sporttery_odds_open is None and stored_odds:
                match.sporttery_odds_open = stored_odds
            match.updated_at = datetime.utcnow()

        # 若 API 返回赛果字段且尚未锁定，写入实际结果
        api_result = row.get("actual_result")
        if api_result and not match.result_locked:
            match.actual_result = api_result
            match.actual_score = row.get("actual_score") or match.actual_score
            match.result_locked = True

        upserted += 1

    await session.commit()
    logger.info("赛单同步完成：%s，%d 场", target_date, upserted)
    return upserted
