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
    """同步竞彩赛单 + 海外赔率 → PostgreSQL + DuckDB 快照."""
    target_date = sync_date or date.today()
    logger.info("开始同步赛单：%s", target_date)

    session        = await _get_db_session()
    source_manager = await _get_source_manager()
    snapshot_mgr   = await _get_snapshot_manager()

    try:
        from core.data.sync import sync_daily_matches
        n = await sync_daily_matches(session, source_manager, snapshot_mgr, target_date)
        logger.info("赛单同步完成：%s，共 %d 场", target_date, n)
        return n
    except Exception as exc:
        logger.error("赛单同步失败：%s", exc, exc_info=True)
        raise
    finally:
        await session.close()
        snapshot_mgr.close()


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
