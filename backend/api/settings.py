from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from core.llm.client import LLMClient, LLMConfig, PROVIDER_DEFAULTS
from db.models import DataSourceConfig, LLMConfig as LLMConfigModel, LLMProvider, User
from db.session import get_db

router = APIRouter()

# 模型列表 registry — 在这里更新，无需重建前端
PROVIDER_MODELS: dict[str, list[str]] = {
    "claude":   ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001",
                 "claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
    "openai":   ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini", "o3-mini", "o4-mini"],
    "gemini":   ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "kimi":     ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    "glm":      ["glm-4-flash", "glm-4-air", "glm-4", "glm-z1-flash", "glm-z1-air"],
    "custom":   [],
}


class LLMConfigCreate(BaseModel):
    name: str
    provider: str
    model: str
    api_key: str
    base_url: str | None = None
    is_default: bool = False


class LLMConfigUpdate(BaseModel):
    name: str
    provider: str
    model: str
    api_key: str | None = None  # None = keep existing key
    base_url: str | None = None
    is_default: bool = False


class LLMConfigOut(BaseModel):
    id: int
    name: str
    provider: str
    model: str
    base_url: str | None
    is_default: bool

    model_config = {"from_attributes": True}


class DataSourceConfigCreate(BaseModel):
    source_name: str
    api_key: str | None = None
    use_scraper: bool = True
    enabled: bool = True
    extra_config: dict | None = None


class DataSourceConfigOut(BaseModel):
    id: int
    source_name: str
    use_scraper: bool
    enabled: bool
    has_api_key: bool

    model_config = {"from_attributes": True}


# ── LLM 配置 ─────────────────────────────────────────────────────────────────

@router.get("/llm/models")
async def list_provider_models(provider: str):
    """返回指定 provider 的内置模型列表（无需认证，供前端 datalist 使用）"""
    return PROVIDER_MODELS.get(provider, [])


@router.get("/llm", response_model=list[LLMConfigOut])
async def list_llm_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LLMConfigModel).where(LLMConfigModel.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("/llm", response_model=LLMConfigOut)
async def create_llm_config(
    data: LLMConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.provider not in PROVIDER_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"不支持的 provider: {data.provider}")
    if data.is_default:
        # 取消其他默认
        existing = await db.execute(
            select(LLMConfigModel).where(
                LLMConfigModel.user_id == current_user.id,
                LLMConfigModel.is_default == True,
            )
        )
        for cfg in existing.scalars().all():
            cfg.is_default = False
    config = LLMConfigModel(
        user_id=current_user.id,
        name=data.name,
        provider=LLMProvider(data.provider),
        model=data.model,
        api_key=data.api_key,
        base_url=data.base_url,
        is_default=data.is_default,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.put("/llm/{config_id}", response_model=LLMConfigOut)
async def update_llm_config(
    config_id: int,
    data: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LLMConfigModel).where(
            LLMConfigModel.id == config_id,
            LLMConfigModel.user_id == current_user.id,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    if data.provider not in PROVIDER_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"不支持的 provider: {data.provider}")
    if data.is_default:
        existing = await db.execute(
            select(LLMConfigModel).where(
                LLMConfigModel.user_id == current_user.id,
                LLMConfigModel.is_default == True,
                LLMConfigModel.id != config_id,
            )
        )
        for c in existing.scalars().all():
            c.is_default = False
    cfg.name = data.name
    cfg.provider = LLMProvider(data.provider)
    cfg.model = data.model
    if data.api_key:  # only overwrite when user explicitly provides a new key
        cfg.api_key = data.api_key
    cfg.base_url = data.base_url
    cfg.is_default = data.is_default
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.post("/llm/{config_id}/test")
async def test_llm_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LLMConfigModel).where(
            LLMConfigModel.id == config_id,
            LLMConfigModel.user_id == current_user.id,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    client = LLMClient(LLMConfig(
        provider=cfg.provider.value,
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
    ))
    return await client.test_connection()


@router.delete("/llm/{config_id}")
async def delete_llm_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        delete(LLMConfigModel).where(
            LLMConfigModel.id == config_id,
            LLMConfigModel.user_id == current_user.id,
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("/llm/{config_id}/models")
async def fetch_live_models(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """用已保存配置的 API Key 向 provider 实时拉取可用模型列表"""
    result = await db.execute(
        select(LLMConfigModel).where(
            LLMConfigModel.id == config_id,
            LLMConfigModel.user_id == current_user.id,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")

    provider = cfg.provider.value
    # Claude 不暴露 /models 端点，直接返回内置列表
    if provider == "claude":
        return PROVIDER_MODELS.get("claude", [])

    # OpenAI 兼容 provider 均支持 GET /models
    try:
        from openai import AsyncOpenAI
        defaults = PROVIDER_DEFAULTS.get(provider, {})
        base_url = cfg.base_url or defaults.get("base_url")
        client = AsyncOpenAI(api_key=cfg.api_key, base_url=base_url)
        resp = await client.models.list()
        ids = [m.id for m in resp.data]
        # 过滤掉 embedding / tts / image 等非对话模型
        skip = {"embed", "text-embedding", "tts", "whisper", "dall", "babbage", "davinci", "ada", "curie"}
        filtered = [m for m in ids if not any(k in m.lower() for k in skip)]
        return sorted(filtered) or ids
    except Exception:
        # API 调用失败时降级到内置列表
        return PROVIDER_MODELS.get(provider, [])


# ── 数据源配置 ────────────────────────────────────────────────────────────────

@router.get("/datasource", response_model=list[DataSourceConfigOut])
async def list_datasource_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DataSourceConfig).where(DataSourceConfig.user_id == current_user.id)
    )
    configs = result.scalars().all()
    return [
        DataSourceConfigOut(
            id=c.id,
            source_name=c.source_name,
            use_scraper=c.use_scraper,
            enabled=c.enabled,
            has_api_key=bool(c.api_key),
        )
        for c in configs
    ]


@router.put("/datasource")
async def upsert_datasource_config(
    data: DataSourceConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DataSourceConfig).where(
            DataSourceConfig.user_id == current_user.id,
            DataSourceConfig.source_name == data.source_name,
        )
    )
    config = result.scalar_one_or_none()
    if config:
        if data.api_key is not None:  # None = "don't change existing key"
            config.api_key = data.api_key
        config.use_scraper = data.use_scraper
        config.enabled = data.enabled
        if data.extra_config is not None:
            config.extra_config = data.extra_config
    else:
        config = DataSourceConfig(
            user_id=current_user.id,
            source_name=data.source_name,
            api_key=data.api_key,
            use_scraper=data.use_scraper,
            enabled=data.enabled,
            extra_config=data.extra_config,
        )
        db.add(config)
    await db.commit()
    return {"ok": True}


# ── Webhook 配置 ──────────────────────────────────────────────────────────────

class WebhookConfigIn(BaseModel):
    url: str
    webhook_type: str = "generic"  # generic / wechat / dingtalk / feishu
    enabled: bool = True


class WebhookConfigOut(BaseModel):
    url: str
    webhook_type: str
    enabled: bool


_WEBHOOK_SOURCE = "webhook"


@router.get("/webhook", response_model=WebhookConfigOut | None)
async def get_webhook_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DataSourceConfig).where(
            DataSourceConfig.user_id == current_user.id,
            DataSourceConfig.source_name == _WEBHOOK_SOURCE,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg or not cfg.extra_config:
        return None
    ec = cfg.extra_config
    return WebhookConfigOut(
        url=ec.get("url", ""),
        webhook_type=ec.get("webhook_type", "generic"),
        enabled=cfg.enabled,
    )


@router.put("/webhook", response_model=WebhookConfigOut)
async def upsert_webhook_config(
    data: WebhookConfigIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DataSourceConfig).where(
            DataSourceConfig.user_id == current_user.id,
            DataSourceConfig.source_name == _WEBHOOK_SOURCE,
        )
    )
    cfg = result.scalar_one_or_none()
    extra = {"url": data.url, "webhook_type": data.webhook_type}
    if cfg:
        cfg.extra_config = extra
        cfg.enabled = data.enabled
    else:
        cfg = DataSourceConfig(
            user_id=current_user.id,
            source_name=_WEBHOOK_SOURCE,
            enabled=data.enabled,
            extra_config=extra,
        )
        db.add(cfg)
    await db.commit()
    return WebhookConfigOut(url=data.url, webhook_type=data.webhook_type, enabled=data.enabled)


@router.post("/webhook/test")
async def test_webhook(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DataSourceConfig).where(
            DataSourceConfig.user_id == current_user.id,
            DataSourceConfig.source_name == _WEBHOOK_SOURCE,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg or not cfg.extra_config or not cfg.extra_config.get("url"):
        raise HTTPException(status_code=404, detail="未配置 Webhook")

    from core.notifications import send_webhook
    ok = await send_webhook(
        url=cfg.extra_config["url"],
        webhook_type=cfg.extra_config.get("webhook_type", "generic"),
        payload={"title": "竞彩顾问 · 测试通知", "text": "Webhook 连通性测试成功 ✓"},
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Webhook 发送失败，请检查 URL 和格式")
    return {"ok": True, "message": "测试消息已发送"}


# ── 集成分析配置 ──────────────────────────────────────────────────────────────

class EnsembleConfigIn(BaseModel):
    models: str = "all"            # "all" | "default" | "1,2,3"（config_id 列表）
    strategy: str = "majority"     # "majority" | "weighted"
    min_consensus: float = 0.5
    min_confidence: int = 40
    default_multiplier: int = 2
    budget: float = 100.0


@router.get("/ensemble")
async def get_ensemble_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DataSourceConfig).where(
            DataSourceConfig.user_id == current_user.id,
            DataSourceConfig.source_name == "ensemble",
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg and cfg.extra_config:
        return cfg.extra_config
    from core.ensemble import EnsembleConfig
    return EnsembleConfig().to_dict()


@router.put("/ensemble")
async def upsert_ensemble_config(
    data: EnsembleConfigIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    extra = data.model_dump()
    result = await db.execute(
        select(DataSourceConfig).where(
            DataSourceConfig.user_id == current_user.id,
            DataSourceConfig.source_name == "ensemble",
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.extra_config = extra
    else:
        cfg = DataSourceConfig(
            user_id=current_user.id,
            source_name="ensemble",
            enabled=True,
            extra_config=extra,
        )
        db.add(cfg)
    await db.commit()
    return extra
