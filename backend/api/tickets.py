import asyncio
import json
import logging
import uuid
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Any

from api.auth import get_current_user
from api.predictions import _get_user_llm_client
from config import get_settings
from db.models import BetRecord, Match, Prediction, User
from db.session import AsyncSessionLocal, get_db

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_AUTO_ANALYZE = 4


async def _make_global_decision_safe(enriched_preds: list[dict], llm_client) -> object | None:
    """全局决策调用，失败时降级返回 None（Python 规则接管）。"""
    if llm_client is None:
        return None
    try:
        from core.tickets.global_decision import make_global_decision
        return await make_global_decision(enriched_preds, llm_client)
    except Exception as e:
        logger.warning("全局决策失败，降级 Python 规则: %s", e)
        return None


def _make_client_from_db_config(cfg):
    """从 DBLLMConfig 创建 LLMClient。"""
    from core.llm.client import LLMClient
    from core.llm.client import LLMConfig as ClientLLMConfig
    client = LLMClient(ClientLLMConfig(
        provider=cfg.provider.value,
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
    ))
    client.db_config_id = cfg.id
    return client


async def _resolve_directive(
    enriched_preds: list[dict],
    force: bool,
    llm_configs: list,
    db: AsyncSession,
    user_id: int,
) -> object | None:
    client = (
        _make_client_from_db_config(llm_configs[0])
        if force and llm_configs
        else await _get_user_llm_client(db, user_id)
    )
    return await _make_global_decision_safe(enriched_preds, client)


def _merge_usage(base: dict | None, client_usage: dict | None) -> dict | None:
    if not client_usage:
        return base
    if base is None:
        base = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    base["prompt_tokens"] += client_usage.get("prompt_tokens", 0)
    base["completion_tokens"] += client_usage.get("completion_tokens", 0)
    base["calls"] += 1
    return base


async def _get_recent_roi(db: AsyncSession, user_id: int, n: int = 10) -> float | None:
    result = await db.execute(
        select(BetRecord)
        .where(BetRecord.user_id == user_id)
        .where(BetRecord.status.in_(["won", "lost"]))
        .order_by(BetRecord.bet_at.desc())
        .limit(n)
    )
    records = result.scalars().all()
    if not records:
        return None
    total_stake = sum(r.stake for r in records)
    total_payout = sum((r.payout or 0.0) for r in records)
    if total_stake <= 0:
        return None
    return (total_payout - total_stake) / total_stake

# ── Redis client（懒初始化，复用连接池） ──────────────────────────────────────

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def _task_prefix(task_id: str) -> str:
    return f"ticket_task:{task_id}"


class TicketsRequest(BaseModel):
    match_ids: list[int]
    budget: float | None = None
    force: bool = False         # True = 忽略缓存，强制重跑多角色 Ensemble 分析
    analyze_all: bool = False   # True = 自动分析全部未分析场次（不受 MAX_AUTO_ANALYZE 限制）
    multiplier: int = 1         # 用户倍数（竞彩每注倍数，≥1）

    @property
    def effective_budget(self) -> float:
        if self.budget is None or self.budget <= 0:
            return 100.0
        return self.budget

    @property
    def effective_multiplier(self) -> int:
        return max(1, int(self.multiplier))


def _sse(event_type: str, **kwargs) -> str:
    return f"data: {json.dumps({'event': event_type, **kwargs})}\n\n"


# ── 内部：Ensemble 分析单场 ───────────────────────────────────────────────────

async def _ensemble_analyze_match(db, match, pipeline, analyzer, llm_configs, ensemble_cfg) -> tuple[dict, dict, dict, list[dict]]:
    """
    运行多角色 Ensemble 分析，返回 (stat_probs, fused_probs, llm_result, votes_list)。
    """
    from core.ensemble import votes_to_dict
    from core.modeling.fusion import FusedProbs, PredictionFusion
    from core.pipeline import _compute_ev

    stat_probs, fused_probs = await pipeline._layer1_stats(match)

    ensemble_result = await analyzer.analyze_match_ensemble(
        session=db,
        match=match,
        llm_configs=llm_configs,
        config=ensemble_cfg,
        stat_probs=stat_probs,
        fused_probs=fused_probs,
    )

    llm_result = ensemble_result.aggregated_llm_result
    adj = llm_result.get("intel_adjustment")
    if adj and any(v != 0 for v in adj.values()):
        fusion = PredictionFusion()
        base = FusedProbs(**fused_probs)
        fused_probs = fusion.apply_intelligence(base, adj).to_dict()

    fused_probs = _compute_ev(fused_probs, match.sporttery_odds)

    votes_list = votes_to_dict(ensemble_result.votes)
    llm_result["_consensus_ratio"] = ensemble_result.consensus_ratio
    llm_result["_final_outcome"] = ensemble_result.final_outcome

    return stat_probs, fused_probs, llm_result, votes_list


# ── 非流式生成 ────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_tickets(
    req: TicketsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为选中场次生成 AI 投注方案（非流式）。force=True 时重跑多角色 Ensemble。"""
    if not req.match_ids:
        raise HTTPException(status_code=400, detail="请至少选择一场赛事")

    from core.pipeline import DailyPipeline
    from core.tickets.generator import TicketGenerator

    pipeline = DailyPipeline()
    budget = req.effective_budget
    enriched_preds: list[dict] = []
    llm_usage: dict | None = None
    llm_configs: list = []

    if req.force:
        # ── 强制多角色 Ensemble ────────────────────────────────────────────────
        from core.ensemble import (
            EnsembleAnalyzer, get_active_llm_configs, get_ensemble_config,
        )
        ensemble_cfg = await get_ensemble_config(db, current_user.id)
        llm_configs = await get_active_llm_configs(db, current_user.id, ensemble_cfg)
        if not llm_configs:
            raise HTTPException(status_code=400, detail="请先在设置页配置 AI 模型")

        analyzer = EnsembleAnalyzer(pipeline)
        run_id = str(uuid.uuid4())[:8]

        for mid in req.match_ids:
            match = await db.get(Match, mid)
            if not match:
                continue
            try:
                stat_probs, fused_probs, llm_result, votes_list = await _ensemble_analyze_match(
                    db, match, pipeline, analyzer, llm_configs, ensemble_cfg
                )
                tickets = pipeline.ticket_gen.generate_for_match(match, fused_probs, llm_result)
                tickets["ensemble_votes"] = votes_list
                tickets["consensus_ratio"] = llm_result.pop("_consensus_ratio", 0)
                tickets["final_outcome"] = llm_result.pop("_final_outcome", "")

                pred = Prediction(
                    match_id=match.id,
                    run_id=run_id,
                    user_id=current_user.id,
                    stat_probs=stat_probs,
                    fused_probs=fused_probs,
                    intel_summary=llm_result.get("intel_summary", ""),
                    risk_label=llm_result.get("risk_label", "guarded"),
                    confidence=float(llm_result.get("confidence", 50)) / 100.0,
                    tickets=tickets,
                    llm_provider="ensemble",
                    llm_model="+".join(f"{c.provider.value}/{c.model}" for c in llm_configs)[:100],
                )
                db.add(pred)
                await db.commit()
                await db.refresh(pred)
                enriched_preds.append({"match": match, "prediction": pred, "ensemble_votes": votes_list})
            except Exception as exc:
                logger.warning("Ensemble 分析失败 match_id=%d: %s", mid, exc)
                try:
                    await db.rollback()
                except Exception:
                    pass

    else:
        # ── 复用已有预测（补充历史 votes） ───────────────────────────────────
        for mid in req.match_ids:
            result = await db.execute(
                select(Prediction)
                .where(Prediction.match_id == mid)
                .order_by(Prediction.created_at.desc())
                .limit(1)
            )
            pred = result.scalar_one_or_none()
            if not pred or not pred.tickets:
                continue
            match = await db.get(Match, mid)
            if match:
                votes = (pred.tickets or {}).get("ensemble_votes", [])
                enriched_preds.append({"match": match, "prediction": pred, "ensemble_votes": votes})

        # 缺失场次触发单模型分析（最多 MAX_AUTO_ANALYZE 场）
        found_ids = {ep["match"].id for ep in enriched_preds}
        missing_ids = [mid for mid in req.match_ids if mid not in found_ids]
        if missing_ids:
            if len(missing_ids) > MAX_AUTO_ANALYZE and not req.analyze_all:
                raise HTTPException(
                    status_code=422,
                    detail=f"所选 {len(missing_ids)} 场赛事尚未分析。请先在赛事页触发分析，或每次最多选 {MAX_AUTO_ANALYZE} 场自动分析",
                )
            llm_client = await _get_user_llm_client(db, current_user.id)
            if not llm_client:
                raise HTTPException(status_code=400, detail="请先在设置页配置 LLM，再生成投注方案")
            for mid in missing_ids:
                match = await db.get(Match, mid)
                if not match:
                    continue
                try:
                    ar = await pipeline.analyze_single_match(db, match, llm_client)
                    llm_usage = _merge_usage(llm_usage, llm_client.last_usage)
                    pred = Prediction(
                        match_id=ar.match_id, run_id=ar.run_id,
                        user_id=current_user.id,
                        stat_probs=ar.stat_probs, fused_probs=ar.fused_probs,
                        intel_summary=ar.intel_summary, risk_label=ar.risk_label,
                        confidence=ar.confidence, tickets=ar.tickets,
                        llm_provider=ar.llm_provider, llm_model=ar.llm_model,
                    )
                    db.add(pred)
                    await db.commit()
                    await db.refresh(pred)
                    enriched_preds.append({"match": match, "prediction": pred, "ensemble_votes": []})
                except Exception as exc:
                    logger.warning("自动分析失败 match_id=%d: %s", mid, exc)
                    try:
                        await db.rollback()
                    except Exception:
                        pass

    if not enriched_preds:
        raise HTTPException(status_code=422, detail="所选赛事均无法完成分析，请检查 LLM 配置或稍后重试")

    directive = await _resolve_directive(enriched_preds, req.force, llm_configs, db, current_user.id)

    recent_roi = await _get_recent_roi(db, current_user.id)
    generator = TicketGenerator()
    plans = generator.generate_parlay_plans(
        enriched_preds, budget=budget, multiplier=req.effective_multiplier,
        recent_roi=recent_roi, directive=directive,
    )
    if not plans:
        raise HTTPException(status_code=422, detail=_empty_plans_reason(enriched_preds))
    return _build_schemes(plans, enriched_preds, llm_usage=llm_usage)


# ── SSE 流式生成 ──────────────────────────────────────────────────────────────

@router.post("/stream")
async def stream_tickets(
    req: TicketsRequest,
    current_user: User = Depends(get_current_user),
):
    """SSE 流式票型生成。force=True 时重跑多角色 Ensemble 分析，推送实时进度。"""
    if not req.match_ids:
        raise HTTPException(status_code=400, detail="请至少选择一场赛事")

    user_id = current_user.id
    match_ids = req.match_ids
    budget = req.effective_budget
    force = req.force
    analyze_all = req.analyze_all
    multiplier = req.effective_multiplier

    async def _generate():
        async with AsyncSessionLocal() as db:
            try:
                from core.pipeline import DailyPipeline
                from core.tickets.generator import TicketGenerator

                pipeline = DailyPipeline()
                enriched_preds: list[dict] = []
                llm_usage: dict | None = None
                llm_configs: list = []

                if force:
                    # ── 强制多角色 Ensemble ────────────────────────────────────
                    yield _sse("step", step="check", msg="启动多角色评估，读取模型配置…", index=0, total=4)

                    from core.ensemble import (
                        EnsembleAnalyzer, get_active_llm_configs,
                        get_ensemble_config,
                    )
                    ensemble_cfg = await get_ensemble_config(db, user_id)
                    llm_configs = await get_active_llm_configs(db, user_id, ensemble_cfg)

                    if not llm_configs:
                        yield _sse("error", msg="请先在设置页配置 AI 模型，再使用多角色评估")
                        return

                    n_models = len(llm_configs)
                    n_matches = len(match_ids)
                    analyzer = EnsembleAnalyzer(pipeline)
                    run_id = str(uuid.uuid4())[:8]

                    for i, mid in enumerate(match_ids):
                        match = await db.get(Match, mid)
                        if not match:
                            continue
                        yield _sse(
                            "step", step="ai",
                            msg=f"多角色分析 {match.home_team} vs {match.away_team}（{i+1}/{n_matches}，{n_models} 个模型并发）…",
                            match_name=f"{match.home_team} vs {match.away_team}",
                            match_index=i + 1, match_total=n_matches,
                            index=1, total=4,
                        )
                        try:
                            stat_probs, fused_probs, llm_result, votes_list = await _ensemble_analyze_match(
                                db, match, pipeline, analyzer, llm_configs, ensemble_cfg
                            )
                            consensus_ratio = llm_result.pop("_consensus_ratio", 0)
                            final_outcome = llm_result.pop("_final_outcome", "")

                            tickets = pipeline.ticket_gen.generate_for_match(match, fused_probs, llm_result)
                            tickets["ensemble_votes"] = votes_list
                            tickets["consensus_ratio"] = consensus_ratio
                            tickets["final_outcome"] = final_outcome

                            pred = Prediction(
                                match_id=match.id,
                                run_id=run_id,
                                user_id=user_id,
                                stat_probs=stat_probs,
                                fused_probs=fused_probs,
                                intel_summary=llm_result.get("intel_summary", ""),
                                risk_label=llm_result.get("risk_label", "guarded"),
                                confidence=float(llm_result.get("confidence", 50)) / 100.0,
                                tickets=tickets,
                                llm_provider="ensemble",
                                llm_model="+".join(f"{c.provider.value}/{c.model}" for c in llm_configs)[:100],
                            )
                            db.add(pred)
                            await db.commit()
                            await db.refresh(pred)
                            enriched_preds.append({"match": match, "prediction": pred, "ensemble_votes": votes_list})
                            logger.info(
                                "SSE Ensemble 完成 match_id=%d 共识=%.0f%% 方向=%s",
                                match.id, consensus_ratio * 100, final_outcome,
                            )
                        except Exception as exc:
                            logger.warning("SSE Ensemble 失败 match_id=%d: %s", mid, exc)
                            try:
                                await db.rollback()
                            except Exception:
                                pass

                else:
                    # ── 复用已有预测（补充历史 votes） ────────────────────────
                    yield _sse("step", step="check", msg="检查已有分析数据…", index=0, total=4)

                    existing: dict[int, Prediction] = {}
                    for mid in match_ids:
                        result = await db.execute(
                            select(Prediction)
                            .where(Prediction.match_id == mid)
                            .order_by(Prediction.created_at.desc())
                            .limit(1)
                        )
                        pred = result.scalar_one_or_none()
                        if pred and pred.tickets:
                            existing[mid] = pred

                    missing_ids = [mid for mid in match_ids if mid not in existing]
                    n_existing = len(existing)
                    n_missing = len(missing_ids)

                    if missing_ids:
                        if len(missing_ids) > MAX_AUTO_ANALYZE and not analyze_all:
                            yield _sse(
                                "error",
                                msg=f"所选 {len(missing_ids)} 场赛事尚未分析。请先在赛事页触发分析，或每次最多选 {MAX_AUTO_ANALYZE} 场自动分析",
                            )
                            return

                        llm_client = await _get_user_llm_client(db, user_id)
                        if not llm_client:
                            yield _sse("error", msg="请先在设置页配置 LLM，再生成投注方案")
                            return

                        yield _sse(
                            "step", step="ai",
                            msg=f"AI 情报分析：已有 {n_existing} 场，新分析 {n_missing} 场…",
                            index=1, total=4,
                        )

                        for i, mid in enumerate(missing_ids):
                            match = await db.get(Match, mid)
                            if not match:
                                continue
                            yield _sse(
                                "step", step="ai",
                                msg=f"AI 分析 {match.home_team} vs {match.away_team} ({i+1}/{n_missing})…",
                                match_name=f"{match.home_team} vs {match.away_team}",
                                match_index=i + 1, match_total=n_missing,
                                index=1, total=4,
                            )
                            try:
                                ar = await pipeline.analyze_single_match(db, match, llm_client)
                                llm_usage = _merge_usage(llm_usage, llm_client.last_usage)
                                pred = Prediction(
                                    match_id=ar.match_id, run_id=ar.run_id,
                                    user_id=user_id,
                                    stat_probs=ar.stat_probs, fused_probs=ar.fused_probs,
                                    intel_summary=ar.intel_summary, risk_label=ar.risk_label,
                                    confidence=ar.confidence, tickets=ar.tickets,
                                    llm_provider=ar.llm_provider, llm_model=ar.llm_model,
                                )
                                db.add(pred)
                                await db.commit()
                                await db.refresh(pred)
                                existing[mid] = pred
                            except Exception as exc:
                                logger.warning("SSE 自动分析失败 match_id=%d: %s", mid, exc)
                                try:
                                    await db.rollback()
                                except Exception:
                                    pass
                    else:
                        yield _sse(
                            "step", step="ai",
                            msg=f"全部 {n_existing} 场已有分析数据，跳过 AI…",
                            index=1, total=4,
                        )

                    for mid, pred in existing.items():
                        m = await db.get(Match, mid)
                        if m:
                            votes = (pred.tickets or {}).get("ensemble_votes", [])
                            enriched_preds.append({"match": m, "prediction": pred, "ensemble_votes": votes})

                # ── 汇总阶段（force/非 force 共用） ─────────────────────────
                if not enriched_preds:
                    yield _sse("error", msg="所选赛事均无法完成分析，请检查 LLM 配置或稍后重试")
                    return

                # 平均置信度 & 共识信息
                avg_conf = 0.0
                n_with_conf = 0
                total_votes = 0
                for ep in enriched_preds:
                    pred = ep["prediction"]
                    if pred and pred.confidence:
                        avg_conf += pred.confidence
                        n_with_conf += 1
                    total_votes += len(ep.get("ensemble_votes") or [])

                avg_conf_pct = round(avg_conf / max(n_with_conf, 1) * 100)
                votes_info = f"，多角色投票 {total_votes} 条" if total_votes > 0 else ""
                yield _sse("step", step="global_decision", msg="AI 全局方案结构决策…", index=2, total=5)
                directive = await _resolve_directive(enriched_preds, force, llm_configs, db, user_id)

                yield _sse(
                    "step", step="model",
                    msg=f"融合 {len(enriched_preds)} 场概率，平均置信度 {avg_conf_pct}%{votes_info}…",
                    index=3, total=5,
                )

                yield _sse("step", step="ticket", msg="筛选票型 & 分配资金…", index=4, total=5)

                recent_roi = await _get_recent_roi(db, user_id)
                gen = TicketGenerator()
                plans = gen.generate_parlay_plans(
                    enriched_preds, budget=budget, multiplier=multiplier,
                    recent_roi=recent_roi, directive=directive,
                )

                if not plans:
                    yield _sse("error", msg=_empty_plans_reason(enriched_preds))
                    return

                _PLAN_LABELS = {
                    "conservative": "稳健", "balanced": "均衡",
                    "high_odds": "博高赔", "scoreline": "比分",
                }
                plan_summary = "·".join(_PLAN_LABELS.get(p.plan_id, p.plan_id) for p in plans)
                schemes = _build_schemes(plans, enriched_preds, llm_usage=llm_usage)
                yield _sse("done", schemes=schemes, summary=f"生成 {len(plans)} 套方案：{plan_summary}")

            except Exception as exc:
                logger.error("stream_tickets 未处理异常: %s", exc, exc_info=True)
                yield _sse("error", msg="服务器内部错误，请稍后重试")

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 任务化生成（POST /task + GET /task/{task_id}）────────────────────────────

@router.post("/task")
async def create_ticket_task(
    req: TicketsRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """创建后台票型生成任务，立即返回 task_id；前端轮询 GET /task/{task_id} 获取进度和结果。"""
    if not req.match_ids:
        raise HTTPException(status_code=400, detail="请至少选择一场赛事")

    task_id = str(uuid.uuid4())
    r = _get_redis()
    prefix = _task_prefix(task_id)
    pipe = r.pipeline()
    pipe.set(f"{prefix}:status", "queued", ex=86400)
    pipe.set(f"{prefix}:meta", json.dumps({
        "match_ids": req.match_ids,
        "force": req.force,
        "analyze_all": req.analyze_all,
        "user_id": current_user.id,
        "created_at": datetime.utcnow().isoformat(),
    }), ex=86400)
    await pipe.execute()

    background_tasks.add_task(_run_ticket_task, task_id, req, current_user.id)
    return {"task_id": task_id, "status": "queued"}


@router.get("/task/{task_id}")
async def get_ticket_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """轮询票型生成任务状态。返回 { task_id, status, events, result }。"""
    r = _get_redis()
    prefix = _task_prefix(task_id)
    status, events_raw, result_raw, meta_raw = await asyncio.gather(
        r.get(f"{prefix}:status"),
        r.lrange(f"{prefix}:events", 0, -1),
        r.get(f"{prefix}:result"),
        r.get(f"{prefix}:meta"),
    )
    if not status:
        raise HTTPException(status_code=404, detail="任务不存在或已过期（24h 后自动清理）")

    if meta_raw:
        meta = json.loads(meta_raw)
        if meta.get("user_id") != current_user.id:
            raise HTTPException(status_code=403, detail="无权访问该任务")

    return {
        "task_id": task_id,
        "status": status,
        "events": [json.loads(e) for e in (events_raw or [])],
        "result": json.loads(result_raw) if result_raw else None,
    }


async def _run_ticket_task(task_id: str, req: TicketsRequest, user_id: int) -> None:
    """后台任务：运行票型生成流水线，将进度事件写入 Redis List，结果写入 Redis String。"""
    r = _get_redis()
    prefix = _task_prefix(task_id)
    TTL = 86400

    async def push(event_type: str, **kwargs) -> None:
        payload = json.dumps({"event": event_type, **kwargs})
        await r.rpush(f"{prefix}:events", payload)
        await r.expire(f"{prefix}:events", TTL)

    await r.set(f"{prefix}:status", "running", ex=TTL)

    match_ids = req.match_ids
    budget = req.effective_budget
    force = req.force
    analyze_all = req.analyze_all
    multiplier = req.effective_multiplier

    async with AsyncSessionLocal() as db:
        try:
            from core.pipeline import DailyPipeline
            from core.tickets.generator import TicketGenerator

            pipeline = DailyPipeline()
            enriched_preds: list[dict] = []
            llm_usage: dict | None = None
            llm_configs: list = []

            if force:
                await push("step", step="check", msg="启动多角色评估，读取模型配置…", index=0, total=4)

                from core.ensemble import (
                    EnsembleAnalyzer, get_active_llm_configs,
                    get_ensemble_config,
                )
                ensemble_cfg = await get_ensemble_config(db, user_id)
                llm_configs = await get_active_llm_configs(db, user_id, ensemble_cfg)

                if not llm_configs:
                    await push("error", msg="请先在设置页配置 AI 模型，再使用多角色评估")
                    await r.set(f"{prefix}:status", "error", ex=TTL)
                    return

                n_models = len(llm_configs)
                n_matches = len(match_ids)
                analyzer = EnsembleAnalyzer(pipeline)
                run_id = str(uuid.uuid4())[:8]

                for i, mid in enumerate(match_ids):
                    match = await db.get(Match, mid)
                    if not match:
                        continue
                    await push(
                        "step", step="ai",
                        msg=f"多角色分析 {match.home_team} vs {match.away_team}（{i+1}/{n_matches}，{n_models} 个模型并发）…",
                        match_name=f"{match.home_team} vs {match.away_team}",
                        match_index=i + 1, match_total=n_matches,
                        index=1, total=4,
                    )
                    try:
                        stat_probs, fused_probs, llm_result, votes_list = await _ensemble_analyze_match(
                            db, match, pipeline, analyzer, llm_configs, ensemble_cfg
                        )
                        consensus_ratio = llm_result.pop("_consensus_ratio", 0)
                        final_outcome = llm_result.pop("_final_outcome", "")

                        tickets = pipeline.ticket_gen.generate_for_match(match, fused_probs, llm_result)
                        tickets["ensemble_votes"] = votes_list
                        tickets["consensus_ratio"] = consensus_ratio
                        tickets["final_outcome"] = final_outcome

                        pred = Prediction(
                            match_id=match.id,
                            run_id=run_id,
                            user_id=user_id,
                            stat_probs=stat_probs,
                            fused_probs=fused_probs,
                            intel_summary=llm_result.get("intel_summary", ""),
                            risk_label=llm_result.get("risk_label", "guarded"),
                            confidence=float(llm_result.get("confidence", 50)) / 100.0,
                            tickets=tickets,
                            llm_provider="ensemble",
                            llm_model="+".join(f"{c.provider.value}/{c.model}" for c in llm_configs)[:100],
                        )
                        db.add(pred)
                        await db.commit()
                        await db.refresh(pred)
                        enriched_preds.append({"match": match, "prediction": pred, "ensemble_votes": votes_list})
                        logger.info(
                            "task Ensemble 完成 match_id=%d 共识=%.0f%% 方向=%s",
                            match.id, consensus_ratio * 100, final_outcome,
                        )
                    except Exception as exc:
                        logger.warning("task Ensemble 失败 match_id=%d: %s", mid, exc)
                        try:
                            await db.rollback()
                        except Exception:
                            pass

            else:
                await push("step", step="check", msg="检查已有分析数据…", index=0, total=4)

                existing: dict[int, Prediction] = {}
                for mid in match_ids:
                    result = await db.execute(
                        select(Prediction)
                        .where(Prediction.match_id == mid)
                        .order_by(Prediction.created_at.desc())
                        .limit(1)
                    )
                    pred = result.scalar_one_or_none()
                    if pred and pred.tickets:
                        existing[mid] = pred

                missing_ids = [mid for mid in match_ids if mid not in existing]
                n_existing = len(existing)
                n_missing = len(missing_ids)

                if missing_ids:
                    if len(missing_ids) > MAX_AUTO_ANALYZE and not analyze_all:
                        await push(
                            "error",
                            msg=f"所选 {len(missing_ids)} 场赛事尚未分析。请先在赛事页触发分析，或每次最多选 {MAX_AUTO_ANALYZE} 场自动分析",
                        )
                        await r.set(f"{prefix}:status", "error", ex=TTL)
                        return

                    llm_client = await _get_user_llm_client(db, user_id)
                    if not llm_client:
                        await push("error", msg="请先在设置页配置 LLM，再生成投注方案")
                        await r.set(f"{prefix}:status", "error", ex=TTL)
                        return

                    await push(
                        "step", step="ai",
                        msg=f"AI 情报分析：已有 {n_existing} 场，新分析 {n_missing} 场…",
                        index=1, total=4,
                    )

                    for i, mid in enumerate(missing_ids):
                        match = await db.get(Match, mid)
                        if not match:
                            continue
                        await push(
                            "step", step="ai",
                            msg=f"AI 分析 {match.home_team} vs {match.away_team} ({i+1}/{n_missing})…",
                            match_name=f"{match.home_team} vs {match.away_team}",
                            match_index=i + 1, match_total=n_missing,
                            index=1, total=4,
                        )
                        try:
                            ar = await pipeline.analyze_single_match(db, match, llm_client)
                            llm_usage = _merge_usage(llm_usage, llm_client.last_usage)
                            pred = Prediction(
                                match_id=ar.match_id, run_id=ar.run_id,
                                user_id=user_id,
                                stat_probs=ar.stat_probs, fused_probs=ar.fused_probs,
                                intel_summary=ar.intel_summary, risk_label=ar.risk_label,
                                confidence=ar.confidence, tickets=ar.tickets,
                                llm_provider=ar.llm_provider, llm_model=ar.llm_model,
                            )
                            db.add(pred)
                            await db.commit()
                            await db.refresh(pred)
                            existing[mid] = pred
                        except Exception as exc:
                            logger.warning("task 自动分析失败 match_id=%d: %s", mid, exc)
                            try:
                                await db.rollback()
                            except Exception:
                                pass
                else:
                    await push(
                        "step", step="ai",
                        msg=f"全部 {n_existing} 场已有分析数据，跳过 AI…",
                        index=1, total=4,
                    )

                for mid, pred in existing.items():
                    m = await db.get(Match, mid)
                    if m:
                        votes = (pred.tickets or {}).get("ensemble_votes", [])
                        enriched_preds.append({"match": m, "prediction": pred, "ensemble_votes": votes})

            # ── 汇总阶段（force/非 force 共用） ──────────────────────────────
            if not enriched_preds:
                await push("error", msg="所选赛事均无法完成分析，请检查 LLM 配置或稍后重试")
                await r.set(f"{prefix}:status", "error", ex=TTL)
                return

            avg_conf = 0.0
            n_with_conf = 0
            total_votes = 0
            for ep in enriched_preds:
                pred = ep["prediction"]
                if pred and pred.confidence:
                    avg_conf += pred.confidence
                    n_with_conf += 1
                total_votes += len(ep.get("ensemble_votes") or [])

            avg_conf_pct = round(avg_conf / max(n_with_conf, 1) * 100)
            votes_info = f"，多角色投票 {total_votes} 条" if total_votes > 0 else ""
            await push("step", step="global_decision", msg="AI 全局方案结构决策…", index=2, total=5)
            directive = await _resolve_directive(enriched_preds, force, llm_configs, db, user_id)

            await push(
                "step", step="model",
                msg=f"融合 {len(enriched_preds)} 场概率，平均置信度 {avg_conf_pct}%{votes_info}…",
                index=3, total=5,
            )

            await push("step", step="ticket", msg="筛选票型 & 分配资金…", index=4, total=5)

            recent_roi = await _get_recent_roi(db, user_id)
            gen = TicketGenerator()
            plans = gen.generate_parlay_plans(
                enriched_preds, budget=budget, multiplier=multiplier,
                recent_roi=recent_roi, directive=directive,
            )

            if not plans:
                await push("error", msg=_empty_plans_reason(enriched_preds))
                await r.set(f"{prefix}:status", "error", ex=TTL)
                return

            _PLAN_LABELS = {
                "conservative": "稳健", "balanced": "均衡",
                "high_odds": "博高赔", "scoreline": "比分",
            }
            plan_summary = "·".join(_PLAN_LABELS.get(p.plan_id, p.plan_id) for p in plans)
            schemes = _build_schemes(plans, enriched_preds, llm_usage=llm_usage)
            await push("done", summary=f"生成 {len(plans)} 套方案：{plan_summary}")
            pipe = r.pipeline()
            pipe.set(f"{prefix}:result", json.dumps(schemes), ex=TTL)
            pipe.set(f"{prefix}:status", "done", ex=TTL)
            await pipe.execute()
            logger.info("ticket task 完成 task_id=%s schemes=%s", task_id, plan_summary)

        except Exception as exc:
            logger.error("ticket task 未处理异常 task_id=%s: %s", task_id, exc, exc_info=True)
            await push("error", msg="服务器内部错误，请稍后重试")
            await r.set(f"{prefix}:status", "error", ex=TTL)


# ── 构建方案响应 ──────────────────────────────────────────────────────────────

def _build_schemes(plans: list[Any], enriched_preds: list[dict], llm_usage: dict | None = None) -> dict:
    mid_to_league: dict[int, str] = {
        ep["match"].id: (ep["match"].league or "")
        for ep in enriched_preds
    }

    schemes: dict = {}
    for plan in plans:
        legs_out = []
        for leg in plan.legs:
            leg_d = leg.to_dict()
            leg_d["league"] = mid_to_league.get(leg.match_id, "")
            leg_d["confidence"] = round(leg.win_prob * 100, 1)
            leg_d["rationale"] = ""
            legs_out.append(leg_d)

        is_cover = plan.combo_sizes is not None
        schemes[plan.plan_id] = {
            "name":              plan.name,
            "tag":               plan.tag,
            "score":             plan.score,
            "stars":             plan.stars,
            "legs":              legs_out,
            "total_odds":        plan.total_odds,
            "parlay_type":       plan.parlay_type,
            "combo_sizes":       plan.combo_sizes,
            "num_combos":        plan.num_combos,
            "stake":             plan.total_stake,
            "win_probability":   plan.win_probability,
            "theoretical_prize": plan.theoretical_prize,
            # 容错方案：理论最高奖金（全腿命中）按单倍归一，前端乘以用户倍数动态重算
            "max_unit_prize":    round(plan.theoretical_prize / max(plan.multiplier, 1), 1) if is_cover else None,
            "risk_label":        _risk_label_for(plan.plan_id),
            "ai_rationale":      plan.ai_rationale or None,
            "ai_excluded":       plan.ai_excluded or [],
        }

    if "scoreline" not in schemes:
        schemes["scoreline"] = {"legs": [], "stake": 0, "note": "比分票型请在单场详情页查看"}

    schemes["stake_allocation"] = {p.plan_id: p.total_stake for p in plans}
    schemes["llm_usage"] = llm_usage
    return schemes


def _risk_label_for(key: str) -> str:
    base = key[:-6] if key.endswith("_cover") else key
    return {
        "conservative": "低风险",
        "balanced":     "中风险",
        "high_odds":    "高风险",
        "scoreline":    "极高风险",
    }.get(base, "中风险")


def _empty_plans_reason(enriched_preds: list[dict]) -> str:
    avoid_matches = [
        f"{ep['match'].home_team} vs {ep['match'].away_team}"
        for ep in enriched_preds
        if ep["prediction"] and ep["prediction"].risk_label == "avoid"
    ]
    if avoid_matches:
        return (
            f"AI 分析建议回避所有所选场次（{'、'.join(avoid_matches)}），"
            "无法组成有效串关。建议重新选择赛事或在单场详情页重新触发分析。"
        )

    no_probs = [
        f"{ep['match'].home_team} vs {ep['match'].away_team}"
        for ep in enriched_preds
        if not (ep.get("prediction") and (ep["prediction"].fused_probs or ep["prediction"].stat_probs))
    ]
    if no_probs:
        return (
            "无法生成投注方案：所选赛事尚无分析数据，请先在今日分析页触发 AI 分析"
            f"（未分析：{'、'.join(no_probs)}）"
        )

    return "无法生成投注方案：所选赛事数据不完整，请重新同步赛单后再试"


@router.get("/match/{match_id}")
async def get_match_tickets(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单场比赛的原始票型数据。"""
    result = await db.execute(
        select(Prediction)
        .where(Prediction.match_id == match_id)
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    pred = result.scalar_one_or_none()
    if not pred or not pred.tickets:
        raise HTTPException(status_code=404, detail="该场次暂无票型数据")
    return pred.tickets
