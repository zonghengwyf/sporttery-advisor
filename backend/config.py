from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── 数据库 ────────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://sporttery:sporttery@localhost:5432/sporttery"
    redis_url: str = "redis://localhost:6379/0"
    duckdb_path: str = "./data/snapshots/sporttery.duckdb"
    skills_dir: str = "./skills"

    # ── 认证 ─────────────────────────────────────────────────────────────────
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 天

    # ── 首次运行初始管理员（留空则不自动创建） ────────────────────────────────
    initial_admin_username: str = "admin"
    initial_admin_password: str = ""
    initial_admin_email: str = "admin@localhost"

    # ── 系统级 LLM（供每日流水线使用，无用户上下文时的后备配置） ─────────────
    system_llm_provider: str = "claude"
    system_llm_model: str = "claude-sonnet-4-6"
    system_llm_api_key: Optional[str] = None
    system_llm_base_url: Optional[str] = None

    # ── 每日调度（5 字段标准 Cron，本地时间） ────────────────────────────────
    daily_sync_cron: str = "0 8 * * *"
    daily_analyze_cron: str = "0 9 * * *"
    auto_ticket_enabled: bool = False
    auto_ticket_cron: str = "30 9 * * *"   # 默认 09:30，分析完成后出票
    auto_ticket_stake: float = 10.0         # 参考投注额（仅用于盈亏计算）
    auto_ticket_sync_cron: str = "0 2 * * *"  # 凌晨 02:00 批量同步前日赛果

    # ── 数据源 API Key（留空使用免费源降级） ─────────────────────────────────
    # 竞彩赛单直接使用官方 App 内部接口，无需 Key
    sporttery_api_key: Optional[str] = None
    odds_api_key: Optional[str] = None
    api_football_key: Optional[str] = None


settings = Settings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
