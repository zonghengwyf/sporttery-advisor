from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from db.models import LLMConfig as DBLLMConfig
from db.models import Match, Prediction, User
from db.session import get_db

router = APIRouter()


class PredictionOut(BaseModel):
    id: int
    match_id: int
    run_id: str
    stat_probs: dict | None
    fused_probs: dict | None = None
    intel_summary: str | None
    risk_label: str | None
    confidence: float | None
    tickets: dict | None
    llm_provider: str | None
    llm_model: str | None
    created_at: str | None = None

    model_config = {"from_attributes": True}

    def model_post_init(self, __context):
        if self.created_at is not None and not isinstance(self.created_at, str):
            self.created_at = str(self.created_at)


@router.get("/batch")
async def get_batch_predictions(
    match_ids: str = Query(default="", description="逗号分隔的 match_id 列表"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量获取多场比赛最新预测状态，供赛事列表显示分析徽章。"""
    if not match_ids:
        return {}
    ids = [int(x) for x in match_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return {}

    subq = (
        select(func.max(Prediction.id).label("max_id"))
        .where(Prediction.match_id.in_(ids))
        .group_by(Prediction.match_id)
        .subquery()
    )
    result = await db.execute(
        select(Prediction.match_id, Prediction.risk_label, Prediction.confidence, Prediction.tickets)
        .where(Prediction.id.in_(select(subq.c.max_id)))
    )
    rows = result.all()
    out = {}
    for r in rows:
        tickets = r.tickets or {}
        votes = tickets.get("ensemble_votes", [])
        total = len(votes)
        if total > 0:
            outcome = tickets.get("final_outcome", "")
            agree = sum(1 for v in votes if v.get("outcome") == outcome and not v.get("error"))
            consensus = f"{agree}/{total}"
        else:
            consensus = None
        out[r.match_id] = {
            "risk_label": r.risk_label,
            "confidence": r.confidence,
            "consensus": consensus,
        }
    return out


@router.get("/{match_id}", response_model=PredictionOut | None)
async def get_prediction(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取最近一次对该场次的预测结果。"""
    result = await db.execute(
        select(Prediction)
        .where(Prediction.match_id == match_id)
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.post("/{match_id}/analyze", response_model=PredictionOut)
async def trigger_analysis(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    触发单场 AI 分析（统计模型 → Skills 注入 → LLM → 写 DB）。
    前端从赛事详情页的"立即分析"按钮调用。
    """
    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="赛事不存在")

    llm_client = await _get_user_llm_client(db, current_user.id)
    if not llm_client:
        raise HTTPException(status_code=400, detail="请先在设置页配置 LLM")

    from core.pipeline import DailyPipeline
    pipeline = DailyPipeline()
    ar = await pipeline.analyze_single_match(db, match, llm_client)

    pred = Prediction(
        match_id=ar.match_id,
        run_id=ar.run_id,
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
    await db.commit()
    await db.refresh(pred)

    return pred


@router.post("/{match_id}/analyze-async")
async def trigger_analysis_async(
    match_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    异步触发分析（立即返回，后台执行）。
    用于开球前批量分析场景，前端轮询 GET /{match_id} 等结果。
    """
    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="赛事不存在")

    llm_cfg = await _get_user_llm_config(db, current_user.id)
    if not llm_cfg:
        raise HTTPException(status_code=400, detail="请先在设置页配置 LLM")

    background_tasks.add_task(_run_analysis_background, match_id, llm_cfg)
    return {"status": "queued", "match_id": match_id}


# ── 内部辅助 ─────────────────────────────────────────────────────────────────

async def _get_user_llm_config(session: AsyncSession, user_id: int):
    result = await session.execute(
        select(DBLLMConfig)
        .where(DBLLMConfig.user_id == user_id, DBLLMConfig.is_default.is_(True))
        .limit(1)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        result = await session.execute(
            select(DBLLMConfig).where(DBLLMConfig.user_id == user_id).limit(1)
        )
        cfg = result.scalar_one_or_none()
    return cfg


async def _get_user_llm_client(session: AsyncSession, user_id: int):
    from core.llm.client import LLMClient
    from core.llm.client import LLMConfig as ClientLLMConfig

    cfg = await _get_user_llm_config(session, user_id)
    if not cfg:
        return None
    return LLMClient(ClientLLMConfig(
        provider=cfg.provider.value,
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
    ))


async def _run_analysis_background(match_id: int, llm_cfg):
    """后台任务：完成分析后写入 DB。"""
    import logging
    from core.llm.client import LLMClient
    from core.llm.client import LLMConfig as ClientLLMConfig
    from core.pipeline import DailyPipeline
    from db.models import Match, Prediction
    from db.session import AsyncSessionLocal

    logger = logging.getLogger(__name__)
    session = AsyncSessionLocal()
    try:
        match = await session.get(Match, match_id)
        if not match:
            return
        llm_client = LLMClient(ClientLLMConfig(
            provider=llm_cfg.provider.value,
            model=llm_cfg.model,
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url,
        ))
        pipeline = DailyPipeline()
        ar = await pipeline.analyze_single_match(session, match, llm_client)
        pred = Prediction(
            match_id=ar.match_id,
            run_id=ar.run_id,
            stat_probs=ar.stat_probs,
            fused_probs=ar.fused_probs,
            intel_summary=ar.intel_summary,
            risk_label=ar.risk_label,
            confidence=ar.confidence,
            tickets=ar.tickets,
            llm_provider=ar.llm_provider,
            llm_model=ar.llm_model,
        )
        session.add(pred)
        await session.commit()
        logger.info("后台分析完成 match_id=%d run_id=%s", match_id, ar.run_id)
    except Exception as exc:
        logger.error("后台分析失败 match_id=%d: %s", match_id, exc, exc_info=True)
    finally:
        await session.close()
