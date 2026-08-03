"""
后台任务定义 — Phase 2 实现版本
每日调度：08:00 同步赛单，09:00 运行分析流水线
"""
import logging
import math
from datetime import date, datetime, timedelta
from typing import Optional


def _bj_today() -> date:
    """返回北京时间当日日期。Docker 容器默认 UTC，直接用 date.today() 会差 8 小时。"""
    return (datetime.utcnow() + timedelta(hours=8)).date()

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
    target_date = sync_date or _bj_today()
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
    target_date = analysis_date or _bj_today()
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

        today = _bj_today()
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
    降级链：竞彩赛果接口（批量）→ 竞彩在售接口 → The Odds API /scores → 跳过（等人工录入）。
    同步成功后更新关联 BetRecord 的结算状态。
    """
    from datetime import datetime, timedelta
    from sqlalchemy import select as sa_select, and_
    from db.models import BetRecord, Match
    from db.session import AsyncSessionLocal

    # kickoff_at 存北京时间（naive），比较必须用同一时间基准（utcnow+8h）
    now = datetime.utcnow() + timedelta(hours=8)
    cutoff = now - timedelta(hours=2, minutes=30)

    logger.info("开始同步赛果，截止时间：%s（北京）", cutoff.isoformat())

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

        # 批量赛果：按待同步比赛的日期范围一次拉取（避免逐场全量查询）
        dates = [m.kickoff_at.date() for m in pending_matches if m.kickoff_at]
        results_map = await source_manager.get_results_map(min(dates), max(dates)) if dates else {}
        if results_map:
            logger.info("竞彩批量赛果：%d 条（%s ~ %s）", len(results_map), min(dates), max(dates))

        for match in pending_matches:
            actual, score = results_map.get(str(match.sporttery_id), (None, None))
            if actual is None:
                # 降级：在售接口（当天完赛）→ The Odds API
                actual, score = await _fetch_result(source_manager, match)
            if actual is None:
                continue

            match.actual_result = actual
            match.result_locked = True
            if score:
                match.actual_score = score
            updated += 1
            logger.info("赛果同步 match_id=%d %s vs %s → %s (%s)",
                        match.id, match.home_team, match.away_team, actual, score or "—")

            # 自动写入回测记录（解锁温度校准 + 真实指标）
            await _auto_save_backtest(session, match)

            await _settle_bet_records(session, match, actual)

        await session.commit()
        logger.info("赛果同步完成：%d / %d 场", updated, len(pending_matches))


async def _auto_save_backtest(session, match) -> None:
    """赛果同步后自动将最新预测写入 DuckDB 回测表，驱动校准与指标闭环。"""
    from sqlalchemy import select as sa_select
    from db.models import Prediction

    result = await session.execute(
        sa_select(Prediction)
        .where(Prediction.match_id == match.id)
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    pred = result.scalar_one_or_none()
    if not pred or not (pred.fused_probs or pred.stat_probs):
        return

    try:
        from config import get_settings
        from core.data.snapshot import SnapshotManager, compute_clv_fields
        snap = SnapshotManager(db_path=get_settings().duckdb_path)
        try:
            # CLV（ADR-006）：pick 优先取实际推荐方向 final_outcome，fallback argmax
            probs_dict = pred.fused_probs or pred.stat_probs
            recommended = (pred.tickets or {}).get("final_outcome")
            pick, entry_odds, close_odds, clv = await compute_clv_fields(
                snap, match.id, probs_dict, match.sporttery_odds, recommended
            )
            await snap.save_backtest_result(
                match_id=match.id,
                predicted=probs_dict,
                actual=match.actual_result,
                user_id=pred.user_id or 0,
                market_odds=match.sporttery_odds,
                pick=pick,
                entry_odds=entry_odds,
                close_odds=close_odds,
                clv=clv,
            )
        finally:
            snap.close()
        logger.debug("回测自动写入 match_id=%d actual=%s clv=%s", match.id, match.actual_result, clv)
    except Exception as exc:
        logger.debug("回测自动写入失败 match_id=%d: %s", match.id, exc)


async def _fetch_result(source_manager, match) -> tuple[str | None, str | None]:
    """尝试从多个数据源获取赛果，返回 (H/D/A | None, score | None)。"""
    # 1. 竞彩 API（在售接口降级，仅对当天完赛有效）
    try:
        result, score = await source_manager.get_match_result(match)
        if result:
            return result, score
    except Exception as exc:
        logger.debug("竞彩 API 赛果失败 %s: %s", match.sporttery_id, exc)

    # 2. The Odds API /scores（若配置了 odds_api_key）
    try:
        result = await source_manager.get_odds_api_result(match)
        if result:
            return result, None
    except Exception as exc:
        logger.debug("The Odds API 赛果失败: %s", exc)

    return None, None


async def _settle_bet_records(session, match, actual_result: str):
    """根据已知赛果，结算关联该场次的待结算 BetRecord。"""
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm.attributes import flag_modified
    from api.bets import _hhad_result_from_score
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
                # HHAD 让球盘：必须用比分推算让球结果，不能直接用原始 H/D/A
                if leg.get("market") == "让球胜平负" and leg.get("handicap") is not None:
                    hhad_result = _hhad_result_from_score(match.actual_score, leg["handicap"])
                    if hhad_result is None:
                        # 比分未录入，无法结算
                        all_settled = False
                        continue
                    pick_for_leg = outcome_map.get(hhad_result)
                else:
                    pick_for_leg = actual_pick
                won = leg.get("pick") == pick_for_leg
                leg["actual_result"] = actual_result
                leg["won"] = won
                if not won:
                    all_won = False
            else:
                if "won" not in leg:
                    all_settled = False
            total_odds *= leg.get("odds", 1.0)

        # JSON 列需显式标记脏位，SQLAlchemy 才会追踪原地修改
        flag_modified(record, "legs")

        if all_settled:
            record.status = "won" if all_won else "lost"
            if all_won:
                record.payout = round(record.stake * total_odds, 2)
            logger.info("BetRecord id=%d 结算完成 → %s", record.id, record.status)


async def run_auto_ticket(
    user_id: int | None = None,
    trigger: str = "scheduled",
    db=None,
    stake: float | None = None,
) -> int:
    """
    自动出票：复用当日已有 Prediction，调用票型生成，写入 AutoTicketRun。
    返回新记录的 id。stake 为单用户预算，None 时回退 env 默认值。
    """
    from sqlalchemy import select as sa_select
    from db.models import AutoTicketRun, DataSourceConfig, LLMConfig, Match, Prediction
    from db.session import AsyncSessionLocal
    from config import get_settings

    settings = get_settings()
    today = _bj_today()

    _own_db = db is None
    if _own_db:
        _db_ctx = AsyncSessionLocal()
        session = await _db_ctx.__aenter__()
    else:
        session = db

    try:
        # 定时触发且未指定用户：读取所有启用自动出票的用户，逐用户出票（当日幂等）
        if user_id is None and trigger == "scheduled":
            cfg_result = await session.execute(
                sa_select(DataSourceConfig).where(
                    DataSourceConfig.source_name == "auto_ticket",
                    DataSourceConfig.enabled == True,  # noqa: E712
                )
            )
            cfgs = cfg_result.scalars().all()
            if not cfgs:
                logger.info("auto_ticket: 无启用自动出票的用户，跳过")
                return 0
            last_id = 0
            for cfg in cfgs:
                dup = await session.execute(
                    sa_select(AutoTicketRun.id).where(
                        AutoTicketRun.user_id == cfg.user_id,
                        AutoTicketRun.run_date == today,
                        AutoTicketRun.trigger == "scheduled",
                    )
                )
                if dup.scalars().first() is not None:
                    logger.info("auto_ticket: 用户 %s 今日已有定时出票，跳过", cfg.user_id)
                    continue
                user_stake = float((cfg.extra_config or {}).get("stake") or 0) or None
                last_id = await run_auto_ticket(
                    user_id=cfg.user_id, trigger="scheduled",
                    db=session, stake=user_stake,
                )
            return last_id

        effective_stake = stake if stake and stake > 0 else settings.auto_ticket_stake
        # 查当日已分析的赛事
        matches_result = await session.execute(
            sa_select(Match).where(Match.sale_date == str(today))
        )
        matches = matches_result.scalars().all()
        match_ids = [m.id for m in matches]

        if not match_ids:
            logger.warning("auto_ticket: 今日无赛事，跳过出票")
            skip_run = AutoTicketRun(
                user_id=user_id, run_date=today, trigger=trigger,
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
                user_id=user_id, run_date=today, trigger=trigger,
                model_info={}, match_ids=match_ids, tickets_json={}, stake=0,
                sync_status="skipped", sync_error="今日无可用预测",
            )
            session.add(skip_run)
            await session.commit()
            await session.refresh(skip_run)
            return skip_run.id

        # 收集 model_info（查用户 LLM 配置，user_id=None 时跳过个人配置查询）
        _uid = user_id
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

        # Kelly 回撤保护：查询近 5 次出票 ROI
        recent_roi = await _compute_recent_roi(session, _uid)
        if recent_roi is not None and recent_roi < -0.30:
            logger.warning("近 5 次出票 ROI=%.1f%%，触发回撤保护（stake 减半）", recent_roi * 100)

        tickets_json = _build_auto_tickets(
            generator, all_match_data, budget=effective_stake, recent_roi=recent_roi
        )

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
            stake=effective_stake,
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


def _compute_run_roi(run) -> float | None:
    """根据已同步的赛果计算单次出票 ROI = (总派奖 - 总投入) / 总投入。
    未能完全结算的方案跳过；无任何可结算方案时返回 None。"""
    if not run.tickets_json or not run.results_json:
        return None
    from api.bets import _hhad_result_from_score

    outcome_map = {"H": "主胜", "D": "平局", "A": "客胜"}
    total_stake = 0.0
    total_payout = 0.0

    for scheme in run.tickets_json.get("schemes", []):
        legs = scheme.get("legs", [])
        if not legs:
            continue
        # 只能正确结算 HAD/HHAD 市场：比分等方案（total_odds 为估算 0）跳过，
        # 否则 "2-1" 永不等于 "主胜" 必输 → ROI 系统性低估 → 误触发回撤保护
        if any(leg.get("market") not in ("胜平负", "让球胜平负", None) for leg in legs):
            continue
        settled = True
        leg_won: list[bool] = []
        for leg in legs:
            res = run.results_json.get(str(leg.get("match_id")))
            if not res or not res.get("actual"):
                settled = False
                break
            if leg.get("market") == "让球胜平负" and leg.get("handicap") is not None:
                hhad = _hhad_result_from_score(res.get("score"), leg["handicap"])
                if hhad is None:
                    settled = False
                    break
                actual_pick = outcome_map.get(hhad)
            else:
                actual_pick = outcome_map.get(res["actual"])
            picks = leg.get("picks") or [leg.get("pick")]
            leg_won.append(actual_pick in picks)
        if not settled:
            continue
        stake = float(scheme.get("total_stake") or 0)
        scheme_odds = float(scheme.get("total_odds") or 0)
        if stake <= 0:
            continue

        combo_sizes = scheme.get("combo_sizes")
        if combo_sizes:
            # M串N 容错方案：按子组合枚举结算，中奖子组合独立派奖
            from itertools import combinations
            num_combos = max(int(scheme.get("num_combos") or 1), 1)
            per_bet = stake / num_combos
            for k in combo_sizes:
                for idxs in combinations(range(len(legs)), k):
                    if not all(leg_won[i] for i in idxs):
                        continue
                    bets = 1
                    odds_prod = 1.0
                    for i in idxs:
                        bets *= int(legs[i].get("num_picks") or 1)
                        odds_prod *= float(legs[i].get("odds") or 0)
                    if odds_prod > 0:
                        total_payout += per_bet * bets * odds_prod
            total_stake += stake
            continue

        if scheme_odds <= 0:
            continue
        total_stake += stake
        if all(leg_won):
            total_payout += stake * scheme_odds

    if total_stake <= 0:
        return None
    return (total_payout - total_stake) / total_stake


async def _compute_recent_roi(session, user_id, limit: int = 5) -> float | None:
    """近 N 次已同步自动出票的平均 ROI，用于 Kelly 回撤保护。
    按 user_id 过滤（None 表示系统级出票），避免跨用户混淆。"""
    from sqlalchemy import select as sa_select
    from db.models import AutoTicketRun

    user_filter = (
        AutoTicketRun.user_id.is_(None) if user_id is None
        else AutoTicketRun.user_id == user_id
    )
    result = await session.execute(
        sa_select(AutoTicketRun)
        .where(
            user_filter,
            AutoTicketRun.sync_status.in_(["synced", "partial"]),
            AutoTicketRun.results_json.isnot(None),
        )
        .order_by(AutoTicketRun.id.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    rois = [r for r in (_compute_run_roi(run) for run in runs) if r is not None]
    if not rois:
        return None
    return sum(rois) / len(rois)


def _build_auto_tickets(generator, all_match_data: list, budget: float, recent_roi: float | None = None) -> dict:
    """把多场 Prediction 数据合并为票型 JSON（复用 TicketGenerator）。"""
    plans = generator.generate_parlay_plans(all_match_data, budget=budget, recent_roi=recent_roi)
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
            from datetime import datetime as _dt2, timedelta as _td
            now_bj = _dt2.utcnow() + _td(hours=8)  # kickoff_at 存北京时间（naive）
            if match.kickoff_at and match.kickoff_at < now_bj:
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

        today = _bj_today()
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

        if not records:
            logger.warning("历史数据解析后为空，放弃训练")
            return None

        # 显式按日期升序（_date_diff 降序），保证 [-100:] 是最近的比赛；
        # 注意 apply_time_decay 返回的新 MatchRecord 不带 _date_diff，必须在 decay 前排序
        records.sort(key=lambda r: -getattr(r, "_date_diff", 0))
        records_with_weights = apply_time_decay(records, today)
        params = fit(records_with_weights)
        logger.info(
            "模型训练完成：%d 场，%d 队伍，log-likelihood=%.2f",
            len(records),
            len(params.attack),
            params.log_likelihood,
        )
        # 持久化参数，供 DailyPipeline 加载
        from core.pipeline import save_dc_params_to_disk
        saved_path = save_dc_params_to_disk(params)
        logger.info("DC 参数已保存至：%s", saved_path)

        # 注册到模型注册表，用留出验证集计算真实指标后再决定是否晋升
        try:
            from core.modeling.model_registry import ModelRegistry, ModelMetrics
            from core.modeling.dixon_coles import predict_probs
            from config import get_settings

            # 留出验证（样本外）：数据充足时用 records[:-100] 单独拟合评估参数，
            # 在最近 100 场上计算 Brier / log-loss / RPS；不足则跳过晋升。
            # 注意：生产 params 仍用全量数据训练（上面），此处仅为诚实的晋升指标。
            from core.modeling.metrics import rps as _rps
            brier_sum = log_loss_sum = rps_sum = 0.0
            n_val = 0
            if len(records_with_weights) > 150:
                train_records = records_with_weights[:-100]
                validation = records_with_weights[-100:]
                eval_params = fit(train_records)
                for m in validation:
                    probs = predict_probs(eval_params, m.home_team, m.away_team)
                    actual = "H" if m.home_goals > m.away_goals else ("D" if m.home_goals == m.away_goals else "A")
                    outcome_map = {"H": 0, "D": 1, "A": 2}
                    oi = outcome_map.get(actual, 0)
                    p = [probs["home"], probs["draw"], probs["away"]]
                    # Brier: sum((p_i - o_i)^2)
                    brier_sum += sum((p[j] - (1.0 if j == oi else 0.0)) ** 2 for j in range(3))
                    # log-loss: -log(p_actual)
                    log_loss_sum += -math.log(max(p[oi], 1e-9))
                    # RPS: 累积分布平方差（ADR-006）
                    rps_sum += _rps(p, oi)
                    n_val += 1
            else:
                logger.info("数据量 %d ≤ 150，无法做样本外验证，跳过晋升", len(records_with_weights))

            if n_val > 0:
                metrics = ModelMetrics(
                    brier=round(brier_sum / n_val, 4),
                    log_loss=round(log_loss_sum / n_val, 4),
                    rps=round(rps_sum / n_val, 4),
                    ece=0.0,
                    n=n_val,
                )
            else:
                metrics = ModelMetrics(n=0)

            registry = ModelRegistry(get_settings().duckdb_path)
            model_id = f"dc_{today.isoformat()}"
            metadata = {
                "params": {
                    "attack": params.attack,
                    "defence": params.defence,
                    "home_advantage": params.home_advantage,
                    "rho": params.rho,
                },
                "log_likelihood": params.log_likelihood,
                "validation_n": n_val,
            }
            # 无验证数据时跳过晋升，避免零指标错误替换 champion
            if n_val > 0:
                promoted = await registry.try_auto_promote(
                    model_id=model_id,
                    competition="global",
                    trained_until=today.isoformat(),
                    metrics=metrics,
                    metadata=metadata,
                )
                if promoted:
                    logger.info("新模型已晋升为 champion: %s (Brier=%.4f)", model_id, metrics.brier)
            else:
                logger.warning("验证数据不足，跳过模型晋升")
        except Exception as exc:
            logger.warning("模型注册表写入失败（不影响训练结果）：%s", exc)
        return params

    except Exception as exc:
        logger.error("模型训练失败：%s", exc, exc_info=True)
        raise
