"""Thin Telegram handlers for the currently supported bot commands."""

import logging
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatters import (
    DATA_SOURCE_NOT_CONFIGURED_TEXT,
    DATA_SOURCE_UNAVAILABLE_TEXT,
    HELP_TEXT,
    MARKET_OUTPUT_NOT_CONFIGURED_TEXT,
    SIGNAL_NOT_CONFIGURED_TEXT,
    START_TEXT,
    format_market_price,
    format_watchlist,
)
from common.watchlist import WatchlistConfig, normalize_symbol
from data.providers import (
    FailoverMarketDataProvider,
    MarketDataNotConfiguredError,
    MarketDataUnavailableError,
)


logger = logging.getLogger(__name__)


async def _reply(update: Update, text: str) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(text)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, START_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, HELP_TEXT)


async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: WatchlistConfig = context.bot_data["watchlist"]
    await _reply(update, format_watchlist(config))


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await _reply(update, "Cú pháp: /price <MÃ>")
        return

    try:
        symbol = normalize_symbol(context.args[0])
    except ValueError:
        await _reply(update, "Mã chứng khoán không hợp lệ. Cú pháp: /price <MÃ>")
        return

    market_data: FailoverMarketDataProvider = context.bot_data["market_data"]
    try:
        result = await market_data.get_latest_price(symbol)
    except MarketDataNotConfiguredError:
        await _reply(update, DATA_SOURCE_NOT_CONFIGURED_TEXT)
        return
    except MarketDataUnavailableError:
        await _reply(update, DATA_SOURCE_UNAVAILABLE_TEXT)
        return

    await _reply(update, format_market_price(result.value, result.source))


async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    market_data: FailoverMarketDataProvider = context.bot_data["market_data"]
    text = (
        MARKET_OUTPUT_NOT_CONFIGURED_TEXT
        if market_data.configured
        else DATA_SOURCE_NOT_CONFIGURED_TEXT
    )
    await _reply(update, text)


async def strategy_not_configured_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _reply(update, SIGNAL_NOT_CONFIGURED_TEXT)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, "Lệnh chưa được hỗ trợ. Dùng /help để xem danh sách lệnh.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error: Any = context.error
    request_id = str(update.update_id) if isinstance(update, Update) else "unknown"
    logger.error(
        "telegram update failed",
        extra={
            "event": "telegram_update_failed",
            "entry_point": "telegram_update",
            "request_id": request_id,
            "error_type": type(error).__name__,
        },
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )
    if isinstance(update, Update):
        await _reply(update, "Bot gặp lỗi tạm thời. Vui lòng thử lại sau.")
