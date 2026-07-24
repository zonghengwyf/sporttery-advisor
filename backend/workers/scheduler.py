"""每日自动分析调度器（APScheduler）

08:00  同步竞彩赛单
09:00  运行完整三层分析流水线

使用标准 5 字段 Cron（本地时间），由 DAILY_SYNC_CRON / DAILY_ANALYZE_CRON 配置。
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from workers.tasks import run_daily_analysis, run_daily_briefing, run_daily_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    scheduler.add_job(
        run_daily_sync,
        CronTrigger.from_crontab(settings.daily_sync_cron),
        id="daily_sync",
        name="每日赛单同步",
        replace_existing=True,
        misfire_grace_time=3600,  # 错过 1 小时内仍允许补跑
    )
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

    scheduler.start()
    logger.info(
        "调度器启动 | 赛单同步：%s | 分析流水线：%s",
        settings.daily_sync_cron,
        settings.daily_analyze_cron,
    )

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("调度器已停止")


if __name__ == "__main__":
    asyncio.run(main())
