from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# 增量迁移：每次启动时幂等地补齐新列，不依赖 Alembic
_MIGRATIONS = [
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS sporttery_odds_open JSONB",
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS actual_result VARCHAR(1)",
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS actual_score VARCHAR(10)",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS match_no VARCHAR(20)",
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS result_locked BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS last_error TEXT",
    "ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP",
    "ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS total_calls INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS total_prompt_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS total_completion_tokens INTEGER NOT NULL DEFAULT 0",
]


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _MIGRATIONS:
            await conn.execute(text(stmt))


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
