"""每日自动分析调度器（APScheduler）

09:00  运行完整三层分析流水线（赛单由 GET /matches/ 按需拉取，无需单独同步任务）
08:30  发送早报 Webhook（配置了才生效）
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_settings
settings = get_settings()
from workers.tasks import (
    run_daily_analysis, run_daily_briefing,
    sync_match_results, run_auto_ticket, sync_auto_ticket_results,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _auto_ticket_crons() -> tuple[str, str]:
    """启动时从 DataSourceConfig 读取启用用户的出票/同步 cron（UI 设置页可配），
    无配置或读取失败时回退 env 默认值。运行中修改 cron 仍需重启 worker 生效。"""
    try:
        from sqlalchemy import select as _sel
        from db.models import DataSourceConfig
        from db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            r = await s.execute(
                _sel(DataSourceConfig).where(
                    DataSourceConfig.source_name == "auto_ticket",
                    DataSourceConfig.enabled == True,  # noqa: E712
                ).limit(1)
            )
            cfg = r.scalars().first()
            if cfg and cfg.extra_config:
                return (
                    cfg.extra_config.get("cron") or settings.auto_ticket_cron,
                    cfg.extra_config.get("sync_cron") or settings.auto_ticket_sync_cron,
                )
    except Exception as exc:
        logger.warning("读取自动出票 cron 配置失败，使用 env 默认：%s", exc)
    return settings.auto_ticket_cron, settings.auto_ticket_sync_cron


async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    auto_cron, auto_sync_cron = await _auto_ticket_crons()

    scheduler.add_job(
        run_daily_analysis,
        CronTrigger.from_crontab(settings.daily_analyze_cron),
        id="daily_analysis",
        name="每日分析流水线",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_daily_briefing,
        CronTrigger.from_crontab("30 8 * * *"),
        id="daily_briefing",
        name="每日早报 Webhook",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        sync_match_results,
        CronTrigger.from_crontab("0 * * * *"),  # 每整点执行一次
        id="sync_results",
        name="赛果同步 & 注单结算",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # 自动出票始终注册：是否启用/预算按用户在 DataSourceConfig（UI 设置页）中的
    # 配置逐用户判定，不再依赖 env 开关；cron 优先取 DB 配置（启动时读取）
    scheduler.add_job(
        run_auto_ticket,
        CronTrigger.from_crontab(auto_cron),
        id="auto_ticket",
        name="自动出票",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        sync_auto_ticket_results,
        CronTrigger.from_crontab(auto_sync_cron),
        id="auto_ticket_sync",
        name="自动出票赛果同步",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        "自动出票任务已注册（按用户配置启用） | 出票：%s | 同步：%s",
        auto_cron, auto_sync_cron,
    )

    scheduler.start()
    logger.info("调度器启动 | 分析流水线：%s", settings.daily_analyze_cron)

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("调度器已停止")


if __name__ == "__main__":
    asyncio.run(main())
