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


async def run_auto_ticket(
    user_id: int | None = None,
    trigger: str = "scheduled",
    db=None,
) -> int:
    """
    自动出票：复用当日已有 Prediction，调用票型生成，写入 AutoTicketRun。
    返回新记录的 id。
    """
    from datetime import date as _date
    from sqlalchemy import select as sa_select
    from db.models import AutoTicketRun, LLMConfig, Match, Prediction
    from db.session import AsyncSessionLocal
    from config import get_settings

    settings = get_settings()
    today = _date.today()

    _own_db = db is None
    if _own_db:
        _db_ctx = AsyncSessionLocal()
        session = await _db_ctx.__aenter__()
    else:
        session = db

    try:
        # 查当日已分析的赛事
        matches_result = await session.execute(
            sa_select(Match).where(Match.sale_date == str(today))
        )
        matches = matches_result.scalars().all()
        match_ids = [m.id for m in matches]

        if not match_ids:
            logger.warning("auto_ticket: 今日无赛事，跳过出票")
            skip_run = AutoTicketRun(
                user_id=user_id or 0, run_date=today, trigger=trigger,
                model_info={}, match_ids=[], tickets_json={}, stake=0,
                sync_status="skipped", sync_error="今日无赛事",
            )
            session.add(skip_run)
            await session.commit()
            await session.refresh(skip_run)
            return skip_run.id

        # 收集 Prediction（最新一条/场）
        preds_result = await session.execute(
            sa_select(Prediction)
            .where(Prediction.match_id.in_(match_ids))
            .order_by(Prediction.created_at.desc())
        )
        all_preds = preds_result.scalars().all()
        # 每场取最新
        seen: set[int] = set()
        preds: list[Prediction] = []
        for p in all_preds:
            if p.match_id not in seen:
                seen.add(p.match_id)
                preds.append(p)

        if not preds:
            logger.warning("auto_ticket: 今日无可用 Prediction，跳过")
            skip_run = AutoTicketRun(
                user_id=user_id or 0, run_date=today, trigger=trigger,
                model_info={}, match_ids=match_ids, tickets_json={}, stake=0,
                sync_status="skipped", sync_error="今日无可用预测",
            )
            session.add(skip_run)
            await session.commit()
            await session.refresh(skip_run)
            return skip_run.id

        # 收集 model_info（查用户 LLM 配置）
        _uid = user_id or 0
        llm_result = await session.execute(
            sa_select(LLMConfig).where(
                LLMConfig.user_id == _uid,
                LLMConfig.is_default == True,  # noqa: E712
            )
        )
        default_llms = llm_result.scalars().all()
        if not default_llms:
            llm_result2 = await session.execute(
                sa_select(LLMConfig).where(LLMConfig.user_id == _uid)
            )
            default_llms = llm_result2.scalars().all()

        llm_names = [f"{c.provider}/{c.model}" for c in default_llms]
        analysis_type = "ensemble" if len(llm_names) > 1 else "single"

        # 用最新 Prediction 的 fused_probs 调用票型生成器
        from core.tickets.generator import TicketGenerator
        generator = TicketGenerator()
        all_match_data = []
        for pred in preds:
            match = next((m for m in matches if m.id == pred.match_id), None)
            if not match or not pred.fused_probs:
                continue
            ensemble_votes = (pred.tickets or {}).get("ensemble_votes", [])
            all_match_data.append({
                "match": match,
                "prediction": pred,
                "ensemble_votes": ensemble_votes,
            })

        if not all_match_data:
            logger.warning("auto_ticket: 无有效 fused_probs，跳过")
            skip_run = AutoTicketRun(
                user_id=_uid, run_date=today, trigger=trigger,
                model_info={}, match_ids=match_ids, tickets_json={}, stake=0,
                sync_status="skipped", sync_error="无有效概率数据",
            )
            session.add(skip_run)
            await session.commit()
            await session.refresh(skip_run)
            return skip_run.id

        tickets_json = _build_auto_tickets(generator, all_match_data, budget=settings.auto_ticket_stake)

        # Pre-embed team names in leg dicts for historical display (avoids N+1 at read time)
        _match_map = {m.id: m for m in matches}
        for _scheme in tickets_json.get("schemes", []):
            for _leg in _scheme.get("legs", []):
                _mid = _leg.get("match_id")
                if _mid and _mid in _match_map:
                    _leg["home_team"] = _match_map[_mid].home_team
                    _leg["away_team"] = _match_map[_mid].away_team
                    _leg["league"] = _match_map[_mid].league

        # 写入 AutoTicketRun
        run = AutoTicketRun(
            user_id=_uid,
            run_date=today,
            trigger=trigger,
            model_info={
                "llms": llm_names,
                "type": analysis_type,
            },
            match_ids=[d["match"].id for d in all_match_data],
            tickets_json=tickets_json,
            stake=settings.auto_ticket_stake,
            sync_status="pending",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        logger.info("auto_ticket 完成：run_id=%d trigger=%s 场次=%d", run.id, trigger, len(all_match_data))
        return run.id

    except Exception as exc:
        logger.error("auto_ticket 失败：%s", exc, exc_info=True)
        if _own_db:
            await session.rollback()
        raise
    finally:
        if _own_db:
            await _db_ctx.__aexit__(None, None, None)


def _build_auto_tickets(generator, all_match_data: list, budget: float) -> dict:
    """把多场 Prediction 数据合并为票型 JSON（复用 TicketGenerator）。"""
    plans = generator.generate_parlay_plans(all_match_data, budget=budget)
    return {
        "schemes": [p.to_dict() for p in plans],
        "match_count": len(all_match_data),
    }


async def _sync_one_auto_ticket_run(run, session) -> None:
    """同步一条 AutoTicketRun 的赛果，更新 sync_status 和 results_json。"""
    from sqlalchemy import select as sa_select
    from db.models import Match
    from datetime import datetime as _dt

    if not run.match_ids:
        run.sync_status = "failed"
        run.sync_error = "match_ids 为空"
        return

    results: dict = {}
    errors: list[str] = []
    synced_count = 0

    for mid in run.match_ids:
        match = await session.get(Match, mid)
        if not match:
            errors.append(f"match#{mid}: not_found")
            continue
        if match.actual_result is None:
            from datetime import datetime as _dt2, timezone
            now_utc = _dt2.utcnow()
            if match.kickoff_at and match.kickoff_at < now_utc:
                errors.append(f"match#{mid}: score_missing")
            else:
                errors.append(f"match#{mid}: no_result_yet")
            continue

        results[str(mid)] = {
            "actual": match.actual_result,
            "score":  match.actual_score,
        }
        synced_count += 1

    total = len(run.match_ids)
    if synced_count == total:
        run.sync_status = "synced"
        run.sync_error = None
    elif synced_count > 0:
        run.sync_status = "partial"
        run.sync_error = "; ".join(errors)
    else:
        run.sync_status = "failed"
        run.sync_error = "; ".join(errors) or "all_missing"

    run.results_json = results
    run.synced_at = _dt.utcnow()
    logger.info("auto_ticket sync run#%d: %d/%d 场同步", run.id, synced_count, total)


async def sync_auto_ticket_results():
    """凌晨批量同步 pending/partial 的 AutoTicketRun 赛果。"""
    from sqlalchemy import select as sa_select, or_
    from db.models import AutoTicketRun
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        stmt = sa_select(AutoTicketRun).where(
            or_(
                AutoTicketRun.sync_status == "pending",
                AutoTicketRun.sync_status == "partial",
            )
        )
        result = await session.execute(stmt)
        runs = result.scalars().all()

        logger.info("sync_auto_ticket_results: 待同步 %d 条", len(runs))
        for run in runs:
            try:
                await _sync_one_auto_ticket_run(run, session)
            except Exception as exc:
                logger.error("sync auto_ticket run#%d 失败：%s", run.id, exc)

        await session.commit()
        logger.info("sync_auto_ticket_results 完成")


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
