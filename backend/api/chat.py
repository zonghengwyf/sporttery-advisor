import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from core.llm.client import LLMClient, LLMConfig
from core.llm.skills_injector import MatchContext, SkillsInjector
from db.models import ChatSession, LLMConfig as LLMConfigModel, Match, Prediction, User
from db.session import get_db

router = APIRouter()
injector = SkillsInjector()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    session_id: int | None = None
    match_id: int | None = None         # 关联某场比赛（注入预测上下文）
    message: str
    llm_config_id: int | None = None    # 指定 LLM，否则用默认


class SessionOut(BaseModel):
    id: int
    title: str
    match_id: int | None
    updated_at: str

    model_config = {"from_attributes": True}


async def _get_llm_client(
    config_id: int | None, user_id: int, db: AsyncSession
) -> LLMClient:
    if config_id:
        result = await db.execute(
            select(LLMConfigModel).where(
                LLMConfigModel.id == config_id,
                LLMConfigModel.user_id == user_id,
            )
        )
    else:
        result = await db.execute(
            select(LLMConfigModel).where(
                LLMConfigModel.user_id == user_id,
                LLMConfigModel.is_default.is_(True),
            )
        )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=400, detail="请先在设置页配置 LLM")
    return LLMClient(LLMConfig(
        provider=cfg.provider.value,
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
    ))


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    return [
        SessionOut(
            id=s.id,
            title=s.title,
            match_id=s.match_id,
            updated_at=str(s.updated_at),
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"id": session.id, "title": session.title, "messages": session.messages}


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式对话"""
    client = await _get_llm_client(req.llm_config_id, current_user.id, db)

    # 获取或创建会话
    if req.session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == req.session_id,
                ChatSession.user_id == current_user.id,
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        session = ChatSession(
            user_id=current_user.id,
            match_id=req.match_id,
            title=req.message[:30] + ("..." if len(req.message) > 30 else ""),
            messages=[],
        )
        db.add(session)
        await db.flush()

    # 构建 system prompt（注入 skills）
    match_context = None
    if req.match_id:
        match_result = await db.execute(select(Match).where(Match.id == req.match_id))
        match = match_result.scalar_one_or_none()
        pred_result = await db.execute(
            select(Prediction)
            .where(Prediction.match_id == req.match_id)
            .order_by(Prediction.created_at.desc())
            .limit(1)
        )
        pred = pred_result.scalar_one_or_none()
        if match:
            match_context = MatchContext(
                home_team=match.home_team,
                away_team=match.away_team,
                league=match.league,
                is_tournament=match.is_tournament,
                stat_probs=pred.stat_probs if pred else None,
                odds_data={
                    "sporttery": match.sporttery_odds,
                    "overseas": match.overseas_odds,
                } if match.sporttery_odds else None,
            )

    system_prompt = injector.build_system_prompt(match_context or MatchContext(
        home_team="", away_team="", league=""
    ))

    # 追加用户消息
    messages = list(session.messages)
    messages.append({"role": "user", "content": req.message, "ts": datetime.utcnow().isoformat()})

    api_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

    async def event_generator():
        full_response = ""
        try:
            async for chunk in client.chat_stream(api_messages, system=system_prompt):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        # 保存消息到会话
        messages.append({
            "role": "assistant",
            "content": full_response,
            "ts": datetime.utcnow().isoformat(),
        })
        session.messages = messages
        session.updated_at = datetime.utcnow()
        await db.commit()
        yield f"data: {json.dumps({'done': True, 'session_id': session.id})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
