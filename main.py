"""Local long-polling entry point for the Telegram bot."""

import asyncio
import logging

from telegram import Update

from bot.application import create_application
from common.config import Settings
from common.logging_config import configure_logging
from reporting.notifier import market_summary_loop


logger = logging.getLogger(__name__)


def _log_task_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "DNSE market-data task stopped unexpectedly: %s",
            error,
            exc_info=(type(error), error, error.__traceback__),
            extra={"event": "dnse_task_failed", "error_type": type(error).__name__},
        )


async def run(application) -> None:
    """Run Telegram and DNSE together on one asyncio event loop."""
    service = application.bot_data.get("market_data_service")
    market_task = None
    summary_task = None
    snapshot_task = None
    initialized = False
    polling = False
    started = False

    if service is not None:
        market_task = asyncio.create_task(service.run(), name="dnse-market-data")
        market_task.add_done_callback(_log_task_result)
        application.bot_data["market_data_task"] = market_task
    summary_task = asyncio.create_task(
        market_summary_loop(application), name="market-summary-scheduler"
    )
    strategy_service = application.bot_data["strategy_service"]

    async def refresh_signal_snapshots() -> None:
        while True:
            try:
                count = await asyncio.to_thread(strategy_service.refresh_scan_snapshot)
                logger.info("signal snapshot refreshed", extra={
                    "event": "signal_snapshot_refreshed", "saved": count,
                })
            except Exception as error:
                logger.warning("signal snapshot refresh failed: %s", error, extra={
                    "event": "signal_snapshot_failed", "error_type": type(error).__name__,
                })
            await asyncio.sleep(60)

    snapshot_task = asyncio.create_task(
        refresh_signal_snapshots(), name="signal-snapshot-scheduler"
    )

    try:
        await application.initialize()
        initialized = True
        if application.updater is None:
            raise RuntimeError("Telegram updater is not configured")
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        polling = True
        await application.start()
        started = True
        await asyncio.Future()
    finally:
        if polling and application.updater is not None and application.updater.running:
            await application.updater.stop()
        if started and application.running:
            await application.stop()
        if initialized:
            await application.shutdown()
        if service is not None:
            await service.stop()
        if market_task is not None and not market_task.done():
            market_task.cancel()
        if market_task is not None:
            await asyncio.gather(market_task, return_exceptions=True)
        if summary_task is not None and not summary_task.done():
            summary_task.cancel()
        if summary_task is not None:
            await asyncio.gather(summary_task, return_exceptions=True)
        if snapshot_task is not None and not snapshot_task.done():
            snapshot_task.cancel()
        if snapshot_task is not None:
            await asyncio.gather(snapshot_task, return_exceptions=True)


def main() -> None:
    configure_logging()
    settings = Settings()
    application = create_application(settings)
    logger.info(
        "telegram bot starting",
        extra={"event": "bot_starting", "entry_point": "long_polling"},
    )
    try:
        asyncio.run(run(application))
    except KeyboardInterrupt:
        logger.info("bot stopped", extra={"event": "bot_stopped"})


if __name__ == "__main__":
    main()
