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


async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

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

    if settings.auto_ticket_enabled:
        scheduler.add_job(
            run_auto_ticket,
            CronTrigger.from_crontab(settings.auto_ticket_cron),
            id="auto_ticket",
            name="自动出票",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            sync_auto_ticket_results,
            CronTrigger.from_crontab(settings.auto_ticket_sync_cron),
            id="auto_ticket_sync",
            name="自动出票赛果同步",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "自动出票已启用 | 出票：%s | 同步：%s",
            settings.auto_ticket_cron, settings.auto_ticket_sync_cron,
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
