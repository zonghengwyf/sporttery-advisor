import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from db.models import Match, Prediction, User
from db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_AUTO_ANALYZE = 4


class TicketsRequest(BaseModel):
    match_ids: list[int]
    budget: float | None = None

    @property
    def effective_budget(self) -> float:
        if self.budget is None or self.budget <= 0:
            return 100.0
        return self.budget


def _sse(event_type: str, **kwargs) -> str:
    return f"data: {json.dumps({'event': event_type, **kwargs})}\n\n"


@router.post("/generate")
async def generate_tickets(
    req: TicketsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为选中场次生成 AI 投注方案（非流式，适合较少场次）。"""
    if not req.match_ids:
        raise HTTPException(status_code=400, detail="请至少选择一场赛事")

    # ── 1. 查询已有预测 ───────────────────────────────────────────────────────
    existing: dict[int, Prediction] = {}
    for mid in req.match_ids:
        result = await db.execute(
            select(Prediction)
            .where(Prediction.match_id == mid)
            .order_by(Prediction.created_at.desc())
            .limit(1)
        )
        pred = result.scalar_one_or_none()
        if pred and pred.tickets:
            existing[mid] = pred

    missing_ids = [mid for mid in req.match_ids if mid not in existing]

    # ── 2. 自动分析缺失场次 ──────────────────────────────────────────────────
    if missing_ids:
        if len(missing_ids) > MAX_AUTO_ANALYZE:
            raise HTTPException(
                status_code=422,
                detail=f"所选 {len(missing_ids)} 场赛事尚未分析。请先在赛事页触发分析，或每次最多选 {MAX_AUTO_ANALYZE} 场自动分析",
            )

        from api.predictions import _get_user_llm_client
        llm_client = await _get_user_llm_client(db, current_user.id)
        if not llm_client:
            raise HTTPException(
                status_code=400,
                detail="请先在设置页配置 LLM，再生成投注方案",
            )

        from core.pipeline import DailyPipeline
        pipeline = DailyPipeline()

        for mid in missing_ids:
            match = await db.get(Match, mid)
            if not match:
                continue
            try:
                ar = await pipeline.analyze_single_match(db, match, llm_client)
                pred = Prediction(
                    match_id=ar.match_id,
                    run_id=ar.run_id,
                    user_id=current_user.id,
                    stat_probs=ar.stat_probs,
                    fused_probs=ar.fused_probs,
                    intel_summary=ar.intel_summary,
                    risk_label=ar.risk_label,
                    confidence=ar.confidence,
                    tickets=ar.tickets,
                    llm_provider=ar.llm_provider,
                    llm_model=ar.llm_model,
                )
                db.add(pred)
                await db.flush()
                existing[mid] = pred
                logger.info("自动分析完成 match_id=%d", mid)
            except Exception as exc:
                logger.warning("自动分析失败 match_id=%d: %s", mid, exc)
                try:
                    await db.rollback()
                except Exception:
                    pass

        await db.commit()

    predictions = list(existing.values())
    if not predictions:
        raise HTTPException(
            status_code=422,
            detail="所选赛事均无法完成分析，请检查 LLM 配置或稍后重试",
        )

    # ── 3. 构建 enriched_predictions ──────────────────────────────────────────
    enriched_preds: list[dict] = []
    for pred in predictions:
        m = await db.get(Match, pred.match_id)
        if m:
            enriched_preds.append({"match": m, "prediction": pred, "ensemble_votes": []})

    if not enriched_preds:
        raise HTTPException(status_code=422, detail="无法获取赛事数据")

    # ── 4. 生成串关方案 ───────────────────────────────────────────────────────
    budget = req.effective_budget
    from core.tickets.generator import TicketGenerator
    generator = TicketGenerator()
    plans = generator.generate_parlay_plans(enriched_preds, budget=budget)

    if not plans:
        raise HTTPException(status_code=422, detail=_empty_plans_reason(enriched_preds))

    return _build_schemes(plans, enriched_preds)


@router.post("/stream")
async def stream_tickets(
    req: TicketsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式票型生成：实时推送 step / done / error 事件。"""
    if not req.match_ids:
        raise HTTPException(status_code=400, detail="请至少选择一场赛事")

    async def _generate():
        try:
            # 0 — 检查已有预测
            yield _sse("step", step="check", msg="检查已有分析数据…", index=0, total=4)

            existing: dict[int, Prediction] = {}
            for mid in req.match_ids:
                result = await db.execute(
                    select(Prediction)
                    .where(Prediction.match_id == mid)
                    .order_by(Prediction.created_at.desc())
                    .limit(1)
                )
                pred = result.scalar_one_or_none()
                if pred and pred.tickets:
                    existing[mid] = pred

            missing_ids = [mid for mid in req.match_ids if mid not in existing]

            # 1 — 自动分析缺失场次
            if missing_ids:
                if len(missing_ids) > MAX_AUTO_ANALYZE:
                    yield _sse(
                        "error",
                        msg=f"所选 {len(missing_ids)} 场赛事尚未分析。请先在赛事页触发分析，或每次最多选 {MAX_AUTO_ANALYZE} 场自动分析",
                    )
                    return

                from api.predictions import _get_user_llm_client
                llm_client = await _get_user_llm_client(db, current_user.id)
                if not llm_client:
                    yield _sse("error", msg="请先在设置页配置 LLM，再生成投注方案")
                    return

                from core.pipeline import DailyPipeline
                pipeline = DailyPipeline()

                for i, mid in enumerate(missing_ids):
                    yield _sse(
                        "step",
                        step="ai",
                        msg=f"AI 情报分析 ({i + 1}/{len(missing_ids)})…",
                        index=1,
                        total=4,
                    )
                    match = await db.get(Match, mid)
                    if not match:
                        continue
                    try:
                        ar = await pipeline.analyze_single_match(db, match, llm_client)
                        pred = Prediction(
                            match_id=ar.match_id,
                            run_id=ar.run_id,
                            user_id=current_user.id,
                            stat_probs=ar.stat_probs,
                            fused_probs=ar.fused_probs,
                            intel_summary=ar.intel_summary,
                            risk_label=ar.risk_label,
                            confidence=ar.confidence,
                            tickets=ar.tickets,
                            llm_provider=ar.llm_provider,
                            llm_model=ar.llm_model,
                        )
                        db.add(pred)
                        await db.flush()
                        existing[mid] = pred
                        logger.info("SSE 自动分析完成 match_id=%d", mid)
                    except Exception as exc:
                        logger.warning("SSE 自动分析失败 match_id=%d: %s", mid, exc)
                        try:
                            await db.rollback()
                        except Exception:
                            pass

                await db.commit()

            # 2 — 构建 enriched_predictions
            yield _sse("step", step="model", msg="构建概率模型输入…", index=2, total=4)

            predictions = list(existing.values())
            if not predictions:
                yield _sse("error", msg="所选赛事均无法完成分析，请检查 LLM 配置或稍后重试")
                return

            enriched_preds: list[dict] = []
            for pred in predictions:
                m = await db.get(Match, pred.match_id)
                if m:
                    enriched_preds.append({"match": m, "prediction": pred, "ensemble_votes": []})

            if not enriched_preds:
                yield _sse("error", msg="无法获取赛事数据")
                return

            # 3 — 生成串关方案
            yield _sse("step", step="ticket", msg="筛选票型 & 分配资金…", index=3, total=4)

            budget = req.effective_budget
            from core.tickets.generator import TicketGenerator
            gen = TicketGenerator()
            plans = gen.generate_parlay_plans(enriched_preds, budget=budget)

            if not plans:
                yield _sse("error", msg=_empty_plans_reason(enriched_preds))
                return

            schemes = _build_schemes(plans, enriched_preds)
            yield _sse("done", schemes=schemes)

        except Exception as exc:
            logger.error("stream_tickets 未处理异常: %s", exc, exc_info=True)
            yield _sse("error", msg="服务器内部错误，请稍后重试")

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_schemes(plans, enriched_preds) -> dict:
    mid_to_league: dict[int, str] = {
        ep["match"].id: (ep["match"].league or "")
        for ep in enriched_preds
    }

    schemes: dict = {}
    for plan in plans:
        legs_out = []
        for leg in plan.legs:
            legs_out.append({
                "match_id":   leg.match_id,
                "match_no":   leg.match_code,
                "home_team":  leg.home_team,
                "away_team":  leg.away_team,
                "kickoff":    leg.kickoff,
                "league":     mid_to_league.get(leg.match_id, ""),
                "pick":       leg.pick,
                "pick_code":  leg.pick_code,
                "odds":       leg.odds,
                "confidence": round(leg.win_prob * 100, 1),
                "rationale":  "",
                "model_votes": {
                    "agree":  leg.model_votes_agree,
                    "total":  leg.model_votes_total,
                    "models": leg.model_names,
                },
            })
        schemes[plan.plan_id] = {
            "name":              plan.name,
            "tag":               plan.tag,
            "score":             plan.score,
            "stars":             plan.stars,
            "legs":              legs_out,
            "total_odds":        plan.total_odds,
            "parlay_type":       plan.parlay_type,
            "stake":             plan.total_stake,
            "win_probability":   plan.win_probability,
            "theoretical_prize": plan.theoretical_prize,
            "risk_label":        _risk_label_for(plan.plan_id),
        }

    if "scoreline" not in schemes:
        schemes["scoreline"] = {"legs": [], "stake": 0, "note": "比分票型请在单场详情页查看"}

    schemes["stake_allocation"] = {p.plan_id: p.total_stake for p in plans}
    return schemes


def _risk_label_for(key: str) -> str:
    return {
        "conservative": "低风险",
        "balanced":     "中风险",
        "high_odds":    "高风险",
        "scoreline":    "极高风险",
    }.get(key, "中风险")


def _empty_plans_reason(enriched_preds: list[dict]) -> str:
    """根据实际数据生成准确的失败原因描述。"""
    no_odds = [
        f"{ep['match'].home_team} vs {ep['match'].away_team}"
        for ep in enriched_preds
        if not ep["match"].sporttery_odds
    ]
    if no_odds:
        return (
            "无法生成投注方案：所选赛事缺少胜平负赔率，请先在今日分析页同步赛单"
            f"（缺少赔率：{'、'.join(no_odds)}）"
        )

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
