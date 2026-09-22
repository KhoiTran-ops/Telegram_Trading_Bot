"""Automatic lunch and end-of-day Telegram market summaries."""

import asyncio
from datetime import datetime, time
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from reporting.charts import render_intraday_index
from reporting.market_summary import format_market_summary


logger = logging.getLogger(__name__)
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")


def due_session(now: datetime, sent: set[tuple[str, str]]) -> str | None:
    local = now.astimezone(VIETNAM)
    if local.weekday() >= 5:
        return None
    day = local.date().isoformat()
    if time(11, 35) <= local.time() < time(13, 0) and (day, "MORNING") not in sent:
        return "MORNING"
    if local.time() >= time(15, 5) and (day, "FULL_DAY") not in sent:
        return "FULL_DAY"
    return None


async def market_summary_loop(application) -> None:
    """Send at most one summary per configured chat for each session/day."""
    sent: set[tuple[str, str]] = set()
    service = application.bot_data["strategy_service"]
    store = application.bot_data["market_store"]
    while True:
        now = datetime.now(VIETNAM)
        session = due_session(now, sent)
        if session:
            chat_ids = await asyncio.to_thread(store.notification_chat_ids)
            if not chat_ids:
                await asyncio.sleep(30)
                continue
            day = now.date().isoformat()
            try:
                summary, bars = await asyncio.to_thread(
                    service.market_summary, now=now, session=session
                )
                chart = await asyncio.to_thread(
                    render_intraday_index, bars, session, Path("var/charts")
                )
                try:
                    for chat_id in chat_ids:
                        with chart.open("rb") as image:
                            await application.bot.send_photo(
                                chat_id=chat_id, photo=image,
                                caption=format_market_summary(summary),
                            )
                finally:
                    chart.unlink(missing_ok=True)
                sent.add((day, session))
                logger.info("automatic market summary sent", extra={
                    "event": "market_summary_sent", "entry_point": "scheduler",
                    "operation": session.lower(), "saved": len(chat_ids),
                })
            except Exception as error:
                logger.warning("automatic market summary failed: %s", error, extra={
                    "event": "market_summary_failed", "entry_point": "scheduler",
                    "operation": session.lower(), "error_type": type(error).__name__,
                })
        await asyncio.sleep(30)
