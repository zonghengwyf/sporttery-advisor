import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import auth, backtest, chat, daily, matches, predictions, public, settings, tickets
from db.session import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _ensure_initial_admin()
    yield


app = FastAPI(
    title="竞彩足球投注顾问",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,        prefix="/api/auth",        tags=["auth"])
app.include_router(matches.router,     prefix="/api/matches",     tags=["matches"])
app.include_router(predictions.router, prefix="/api/predictions", tags=["predictions"])
app.include_router(tickets.router,     prefix="/api/tickets",     tags=["tickets"])
app.include_router(chat.router,        prefix="/api/chat",        tags=["chat"])
app.include_router(backtest.router,    prefix="/api/backtest",    tags=["backtest"])
app.include_router(settings.router,    prefix="/api/settings",    tags=["settings"])
app.include_router(daily.router,       prefix="/api/daily",       tags=["daily"])
app.include_router(public.router,      prefix="/api/public",      tags=["public"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}


async def _ensure_initial_admin():
    """首次启动时，若 DB 中无任何用户且配置了初始密码，则自动创建管理员账号。"""
    from config import get_settings
    cfg = get_settings()
    if not cfg.initial_admin_password:
        return

    from sqlalchemy import select
    from db.session import AsyncSessionLocal
    from db.models import User
    from passlib.context import CryptContext

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # 已有用户，跳过

        pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin = User(
            username=cfg.initial_admin_username,
            email=cfg.initial_admin_email,
            hashed_password=pwd.hash(cfg.initial_admin_password),
            is_admin=True,
        )
        session.add(admin)
        await session.commit()
        logger.info(
            "已自动创建管理员账号：%s（请登录后在设置页配置 LLM）",
            cfg.initial_admin_username,
        )
