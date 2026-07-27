"""
后台任务定义 — Phase 2 实现版本
每日调度：08:00 同步赛单，09:00 运行分析流水线
"""
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


async def _get_db_session():
    from db.session import AsyncSessionLocal
    return AsyncSessionLocal()


async def _get_source_manager():
    from config import get_settings
    from core.data.source_manager import SourceManager

    settings = get_settings()
    redis_client = None
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        pass

    return SourceManager(
        redis_client=redis_client,
        sporttery_api_key=getattr(settings, "sporttery_api_key", None),
        odds_api_key=getattr(settings, "odds_api_key", None),
        api_football_key=getattr(settings, "api_football_key", None),
    )


async def _get_snapshot_manager():
    from config import get_settings
    from core.data.snapshot import SnapshotManager

    settings = get_settings()
    return SnapshotManager(db_path=settings.duckdb_path)


async def run_daily_sync(sync_date: Optional[date] = None):
    """同步竞彩赛单 → PostgreSQL."""
    target_date = sync_date or date.today()
    logger.info("开始同步赛单：%s", target_date)

    from db.session import AsyncSessionLocal
    from core.data.sync import sync_daily_matches

    async with AsyncSessionLocal() as session:
        try:
            n = await sync_daily_matches(session, target_date)
            logger.info("赛单同步完成：%s，共 %d 场", target_date, n)
            return n
        except Exception as exc:
            logger.error("赛单同步失败：%s", exc, exc_info=True)
            raise


async def run_daily_analysis(analysis_date: Optional[date] = None):
    """运行今日完整分析流水线（三层：统计 → LLM → 票型）。"""
    target_date = analysis_date or date.today()
    logger.info("开始每日分析：%s", target_date)

    try:
        from core.pipeline import DailyPipeline
        pipeline = DailyPipeline()
        result = await pipeline.run(target_date)
        logger.info("每日分析完成：%s，分析 %d 场", target_date, result.get("analyzed", 0))
        return result
    except Exception as exc:
        logger.error("每日分析失败：%s", exc, exc_info=True)
        raise


async def run_daily_briefing():
    """08:30 发送当日赛事早报到已配置的 Webhook。"""
    logger.info("开始发送每日早报")
    session = await _get_db_session()
    try:
        from sqlalchemy import select as sa_select
        from datetime import date
        from db.models import Match, Prediction, DataSourceConfig

        today = date.today()
        matches_result = await session.execute(
            sa_select(Match).where(Match.sale_date == today).order_by(Match.kickoff_at)
        )
        matches = [
            {
                "id": m.id,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "league": m.league,
                "sporttery_odds": m.sporttery_odds,
            }
            for m in matches_result.scalars().all()
        ]

        match_ids = [m["id"] for m in matches]
        preds_result = await session.execute(
            sa_select(Prediction).where(Prediction.match_id.in_(match_ids))
        )
        predictions = [
            {
                "match_id": p.match_id,
                "risk_label": p.risk_label,
                "fused_probs": p.fused_probs,
                "stat_probs": p.stat_probs,
            }
            for p in preds_result.scalars().all()
        ]

        # 找所有已启用的 webhook 配置
        wh_result = await session.execute(
            sa_select(DataSourceConfig).where(
                DataSourceConfig.source_name == "webhook",
                DataSourceConfig.enabled == True,
            )
        )
        webhooks = wh_result.scalars().all()
        if not webhooks:
            logger.info("未配置启用的 Webhook，跳过早报")
            return

        from core.notifications import build_daily_briefing, send_webhook
        payload = await build_daily_briefing(matches, predictions)

        sent = 0
        for wh in webhooks:
            ec = wh.extra_config or {}
            if ec.get("url"):
                ok = await send_webhook(ec["url"], ec.get("webhook_type", "generic"), payload)
                if ok:
                    sent += 1
        logger.info("早报已发送：%d / %d 个 Webhook 成功", sent, len(webhooks))
    except Exception as exc:
        logger.error("早报发送失败：%s", exc, exc_info=True)
    finally:
        await session.close()


async def sync_match_results():
    """
    扫描已结束但 actual_result 为空的比赛，尝试同步赛果。
    降级链：竞彩 API → The Odds API /scores → 跳过（等人工录入）。
    同步成功后更新关联 BetRecord 的结算状态。
    """
    from datetime import datetime, timedelta
    from sqlalchemy import select as sa_select, and_
    from db.models import BetRecord, Match
    from db.session import AsyncSessionLocal

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=2, minutes=30)

    logger.info("开始同步赛果，截止时间：%s", cutoff.isoformat())

    async with AsyncSessionLocal() as session:
        stmt = sa_select(Match).where(
            and_(
                Match.kickoff_at <= cutoff,
                Match.actual_result.is_(None),
                Match.result_locked == False,  # noqa: E712
            )
        )
        result = await session.execute(stmt)
        pending_matches = result.scalars().all()

        if not pending_matches:
            logger.info("无待结算赛事")
            return

        logger.info("待同步赛果场次：%d", len(pending_matches))
        source_manager = await _get_source_manager()
        updated = 0

        for match in pending_matches:
            actual = await _fetch_result(source_manager, match)
            if actual is None:
                continue

            match.actual_result = actual
            match.result_locked = True
            updated += 1
            logger.info("赛果同步 match_id=%d %s vs %s → %s",
                        match.id, match.home_team, match.away_team, actual)

            await _settle_bet_records(session, match, actual)

        await session.commit()
        logger.info("赛果同步完成：%d / %d 场", updated, len(pending_matches))


async def _fetch_result(source_manager, match) -> str | None:
    """尝试从多个数据源获取赛果，返回 H/D/A 或 None。"""
    # 1. 竞彩 API
    try:
        result = await source_manager.get_match_result(match.sporttery_id)
        if result:
            return result
    except Exception as exc:
        logger.debug("竞彩 API 赛果失败 %s: %s", match.sporttery_id, exc)

    # 2. The Odds API /scores（若配置了 odds_api_key）
    try:
        result = await source_manager.get_odds_api_result(match)
        if result:
            return result
    except Exception as exc:
        logger.debug("The Odds API 赛果失败: %s", exc)

    return None


async def _settle_bet_records(session, match, actual_result: str):
    """根据已知赛果，结算关联该场次的待结算 BetRecord。"""
    from sqlalchemy import select as sa_select
    from db.models import BetRecord

    outcome_map = {"H": "主胜", "D": "平局", "A": "客胜"}
    actual_pick = outcome_map.get(actual_result)

    result = await session.execute(
        sa_select(BetRecord).where(BetRecord.status == "pending")
    )
    records = result.scalars().all()

    for record in records:
        # 检查该记录的 legs 里是否包含这场比赛
        if not any(leg.get("match_id") == match.id for leg in record.legs):
            continue

        # 更新该腿结果，检查整注是否全中
        all_settled = True
        all_won = True
        total_odds = 1.0
        for leg in record.legs:
            if leg.get("void"):
                continue
            if leg.get("match_id") == match.id:
                won = leg.get("pick") == actual_pick
                leg["actual_result"] = actual_result
                leg["won"] = won
                if not won:
                    all_won = False
            else:
                if "won" not in leg:
                    all_settled = False
            total_odds *= leg.get("odds", 1.0)

        if all_settled:
            record.status = "won" if all_won else "lost"
            if all_won:
                record.payout = round(record.stake * total_odds, 2)
            logger.info("BetRecord id=%d 结算完成 → %s", record.id, record.status)


async def retrain_model(seasons: int = 3):
    """从 football-data.co.uk 下载历史数据并重新拟合 Dixon-Coles 模型。"""
    logger.info("开始重新训练模型，使用过去 %d 个赛季数据", seasons)

    source_manager = await _get_source_manager()
    try:
        historical = await source_manager.get_historical_data(seasons=seasons)
        if not historical:
            logger.warning("未获取到历史数据，放弃训练")
            return None

        from core.modeling.dixon_coles import MatchRecord, fit, apply_time_decay
        from datetime import date as _date

        today = _date.today()
        records = []
        for m in historical:
            try:
                match_date = _date.fromisoformat(m["date"])
                rec = MatchRecord(
                    home_team=m["home_team"],
                    away_team=m["away_team"],
                    home_goals=int(m["home_goals"]),
                    away_goals=int(m["away_goals"]),
                )
                rec._date_diff = (today - match_date).days
                records.append(rec)
            except (KeyError, ValueError):
                continue

        records_with_weights = apply_time_decay(records, today)
        params = fit(records_with_weights)
        logger.info(
            "模型训练完成：%d 队伍，log-likelihood=%.2f",
            len(params.attack),
            params.log_likelihood,
        )
        # 持久化参数，供 DailyPipeline 加载
        from core.pipeline import save_dc_params_to_disk
        saved_path = save_dc_params_to_disk(params)
        logger.info("DC 参数已保存至：%s", saved_path)
        return params

    except Exception as exc:
        logger.error("模型训练失败：%s", exc, exc_info=True)
        raise
