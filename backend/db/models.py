import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    llm_configs: Mapped[list["LLMConfig"]] = relationship(back_populates="user")


class LLMProvider(str, enum.Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    GLM = "glm"
    CUSTOM = "custom"


class LLMConfig(Base):
    """每个用户可配置多个 LLM，可指定默认使用哪个"""
    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # 用户自定义名称
    provider: Mapped[LLMProvider] = mapped_column(Enum(LLMProvider), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "claude-sonnet-4-6"
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))        # 三方中转站或自定义
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="llm_configs")


class DataSourceConfig(Base):
    """数据源配置（API Key + 爬虫开关）"""
    __tablename__ = "data_source_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)  # sporttery/odds_api/api_football
    api_key: Mapped[str | None] = mapped_column(String(500))
    use_scraper: Mapped[bool] = mapped_column(Boolean, default=True)  # 无 Key 时是否用爬虫
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_config: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("user_id", "source_name"),)


class Match(Base):
    """竞彩赛事"""
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sporttery_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    home_team: Mapped[str] = mapped_column(String(100), nullable=False)
    away_team: Mapped[str] = mapped_column(String(100), nullable=False)
    league: Mapped[str] = mapped_column(String(100), nullable=False)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sale_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    available_markets: Mapped[list] = mapped_column(JSON, default=list)
    sporttery_odds: Mapped[dict | None] = mapped_column(JSON)
    sporttery_odds_open: Mapped[dict | None] = mapped_column(JSON)  # 开盘赔率快照
    overseas_odds: Mapped[dict | None] = mapped_column(JSON)
    is_tournament: Mapped[bool] = mapped_column(Boolean, default=False)
    tournament_context: Mapped[dict | None] = mapped_column(JSON)  # 出线形势等
    actual_result: Mapped[str | None] = mapped_column(String(1))   # H/D/A（赛后录入）
    actual_score: Mapped[str | None] = mapped_column(String(10))   # "2-1" 格式
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    predictions: Mapped[list["Prediction"]] = relationship(back_populates="match")


class Prediction(Base):
    """每场比赛的预测结果（统计 + LLM 情报 + 票型）"""
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(50), nullable=False)  # 每次分析批次 ID
    stat_probs: Mapped[dict | None] = mapped_column(JSON)    # 主要来源原始概率（DC/Elo/市场）
    fused_probs: Mapped[dict | None] = mapped_column(JSON)   # 多源融合 + 情报调整后概率
    intel_summary: Mapped[str | None] = mapped_column(Text)  # LLM 情报摘要
    risk_label: Mapped[str | None] = mapped_column(String(20))  # mainline/guarded/upset/avoid
    confidence: Mapped[float | None] = mapped_column(Float)
    tickets: Mapped[dict | None] = mapped_column(JSON)       # 4 类票型
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    llm_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    match: Mapped["Match"] = relationship(back_populates="predictions")


class ChatSession(Base):
    """AI 对话会话"""
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))  # 可关联某场比赛
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    messages: Mapped[list] = mapped_column(JSON, default=list)  # [{role, content, ts}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
