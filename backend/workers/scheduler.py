"""每日自动分析调度器（APScheduler + PostgreSQL LISTEN/NOTIFY）

08:30  发送早报 Webhook（配置了才生效）
08:45  同步今日竞彩赛单 → PostgreSQL
09:00  运行完整三层分析流水线
自定时  自动出票（用户在设置页修改后 NOTIFY 实时更新，无需重启）
整点   赛果同步 & 注单结算
自定时  自动出票赛果批量同步
"""
import asyncio
import logging

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_settings

settings = get_settings()
from workers.tasks import (
    run_daily_sync, run_daily_analysis, run_daily_briefing,
    sync_match_results, run_auto_ticket, sync_auto_ticket_results,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _load_auto_ticket_crons() -> tuple[str, str]:
    """从 DB 读取出票 cron，失败回退 env 默认值。"""
    try:
        from sqlalchemy import select as _sel
        from db.models import DataSourceConfig
        from db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            result = await s.execute(
                _sel(DataSourceConfig).where(
                    DataSourceConfig.source_name == "auto_ticket",
                ).limit(1)
            )
            cfg = result.scalars().first()
            if cfg and cfg.extra_config:
                return (
                    cfg.extra_config.get("cron") or settings.auto_ticket_cron,
                    cfg.extra_config.get("sync_cron") or settings.auto_ticket_sync_cron,
                )
    except Exception as exc:
        logger.warning("读取出票 cron 失败，使用 env 默认：%s", exc)
    return settings.auto_ticket_cron, settings.auto_ticket_sync_cron


async def _apply_auto_ticket_crons() -> None:
    """从 DB 读取最新 cron 并热更新 APScheduler job。"""
    if _scheduler is None:
        return
    cron, sync_cron = await _load_auto_ticket_crons()
    try:
        _scheduler.reschedule_job(
            "auto_ticket",
            trigger=CronTrigger.from_crontab(cron, timezone="Asia/Shanghai"),
        )
        _scheduler.reschedule_job(
            "auto_ticket_sync",
            trigger=CronTrigger.from_crontab(sync_cron, timezone="Asia/Shanghai"),
        )
        logger.info("出票 cron 已热更新 | 出票：%s | 同步：%s", cron, sync_cron)
    except Exception as exc:
        logger.warning("reschedule_job 失败：%s", exc)


def _on_pg_notify(conn, pid, channel, payload) -> None:
    """asyncpg NOTIFY 回调（同步入口），调起热更新协程。"""
    logger.info("PG NOTIFY [%s]：重新加载出票配置", channel)
    asyncio.create_task(_apply_auto_ticket_crons())


async def _pg_listener_loop() -> None:
    """持久 LISTEN 连接，异常后自动重连。"""
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    while True:
        conn = None
        try:
            conn = await asyncpg.connect(dsn=dsn)
            await conn.add_listener("auto_ticket_changed", _on_pg_notify)
            logger.info("PG LISTEN auto_ticket_changed 已就绪")
            # 每 30 秒 keepalive，连接断开时 execute 会抛出，触发重连
            while True:
                await asyncio.sleep(30)
                await conn.execute("SELECT 1")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("PG LISTEN 连接异常，5s 后重连：%s", exc)
        finally:
            if conn and not conn.is_closed():
                try:
                    await conn.close()
                except Exception:
                    pass
        await asyncio.sleep(5)


async def main() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    auto_cron, auto_sync_cron = await _load_auto_ticket_crons()

    _scheduler.add_job(
        run_daily_sync,
        CronTrigger.from_crontab("45 8 * * *"),
        id="daily_sync",
        name="每日赛单同步",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    _scheduler.add_job(
        run_daily_analysis,
        CronTrigger.from_crontab(settings.daily_analyze_cron),
        id="daily_analysis",
        name="每日分析流水线",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        run_daily_briefing,
        CronTrigger.from_crontab("30 8 * * *"),
        id="daily_briefing",
        name="每日早报 Webhook",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    _scheduler.add_job(
        sync_match_results,
        CronTrigger.from_crontab("0 * * * *"),
        id="sync_results",
        name="赛果同步 & 注单结算",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    _scheduler.add_job(
        run_auto_ticket,
        CronTrigger.from_crontab(auto_cron, timezone="Asia/Shanghai"),
        id="auto_ticket",
        name="自动出票",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        sync_auto_ticket_results,
        CronTrigger.from_crontab(auto_sync_cron, timezone="Asia/Shanghai"),
        id="auto_ticket_sync",
        name="自动出票赛果同步",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    logger.info("调度器启动 | 出票：%s | 同步：%s", auto_cron, auto_sync_cron)

    listener_task = asyncio.create_task(_pg_listener_loop())

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        listener_task.cancel()
        _scheduler.shutdown()
        logger.info("调度器已停止")


if __name__ == "__main__":
    asyncio.run(main())
