"""Thin Telegram handlers for the currently supported bot commands."""

import logging
import asyncio
from pathlib import Path
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
    format_backtest,
    format_market_price,
    format_scan,
    format_signal,
    format_watchlist,
)
from common.watchlist import WatchlistConfig, normalize_symbol
from data.providers import (
    FailoverMarketDataProvider,
    MarketDataNotConfiguredError,
    MarketDataUnavailableError,
)
from reporting.charts import parse_chart_args, render_candlestick, render_intraday_index
from reporting.market_summary import format_market_summary
from signal_engine.service import StrategyService


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


async def chat_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    await _reply(update, f"Chat ID: {chat.id}" if chat is not None else "Không xác định được Chat ID.")


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
    service: StrategyService | None = context.bot_data.get("strategy_service")
    if service is None:
        market_data: FailoverMarketDataProvider = context.bot_data["market_data"]
        await _reply(update, DATA_SOURCE_NOT_CONFIGURED_TEXT if not market_data.configured
                     else MARKET_OUTPUT_NOT_CONFIGURED_TEXT)
        return
    try:
        summary, bars = await asyncio.to_thread(service.market_summary)
        chart = await asyncio.to_thread(render_intraday_index, bars, "FULL_DAY", Path("var/charts"))
    except ValueError as error:
        await _reply(update, str(error))
        return
    try:
        if update.effective_message is not None:
            with chart.open("rb") as image:
                await update.effective_message.reply_photo(image, caption=format_market_summary(summary))
    finally:
        chart.unlink(missing_ok=True)


async def strategy_not_configured_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _reply(update, SIGNAL_NOT_CONFIGURED_TEXT)


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await _reply(update, "Cú pháp: /signal <MÃ>")
        return
    try:
        symbol = normalize_symbol(context.args[0])
    except ValueError:
        await _reply(update, "Mã chứng khoán không hợp lệ. Cú pháp: /signal <MÃ>")
        return
    service: StrategyService | None = context.bot_data.get("strategy_service")
    if service is None:
        await _reply(update, SIGNAL_NOT_CONFIGURED_TEXT)
        return
    result = await asyncio.to_thread(service.evaluate, symbol)
    await _reply(update, format_signal(result))


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service: StrategyService | None = context.bot_data.get("strategy_service")
    if service is None:
        await _reply(update, SIGNAL_NOT_CONFIGURED_TEXT)
        return
    results = await asyncio.to_thread(service.scan, limit=10)
    await _reply(update, format_scan(results))


async def filtered_scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service: StrategyService | None = context.bot_data.get("strategy_service")
    if service is None:
        await _reply(update, SIGNAL_NOT_CONFIGURED_TEXT)
        return
    command = (update.effective_message.text or "").split()[0].lower() if update.effective_message else ""
    results = await asyncio.to_thread(service.scan, limit=50)
    if command in ("/buy", "/mua", "/tinhieu"):
        selected = [item for item in results if item.action.endswith("BUY")]
        title = "TÍN HIỆU MUA HIỆN TẠI"
    else:
        selected = [item for item in results if "SELL" in item.action or "REJECT" in item.action]
        title = "TÍN HIỆU SUY YẾU / NÊN TRÁNH"
    await _reply(update, format_scan(selected[:10], title=title))


async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        options = parse_chart_args(list(context.args))
    except ValueError as error:
        await _reply(update, str(error))
        return
    service: StrategyService | None = context.bot_data.get("strategy_service")
    if service is None:
        await _reply(update, SIGNAL_NOT_CONFIGURED_TEXT)
        return
    try:
        chart = await asyncio.to_thread(
            render_candlestick, service.chart_bars(options.symbol), options, Path("var/charts")
        )
    except ValueError as error:
        await _reply(update, str(error))
        return
    try:
        if update.effective_message is not None:
            caption = (f"{options.symbol} · {options.period.upper()} · {', '.join(options.indicators).upper()}\n"
                       f"Đổi khoảng/chỉ báo: /chart {options.symbol} 3m ema,rsi,macd,obv")
            with chart.open("rb") as image:
                await update.effective_message.reply_photo(image, caption=caption)
    finally:
        chart.unlink(missing_ok=True)


async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await _reply(update, "Cú pháp: /hieuqua <MÃ>")
        return
    try:
        symbol = normalize_symbol(context.args[0])
    except ValueError:
        await _reply(update, "Mã chứng khoán không hợp lệ.")
        return
    service: StrategyService | None = context.bot_data.get("strategy_service")
    if service is None:
        await _reply(update, SIGNAL_NOT_CONFIGURED_TEXT)
        return
    result = await asyncio.to_thread(service.backtest, symbol)
    await _reply(update, format_backtest(result))


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").split()[0] if update.effective_message else ""
    raw = text.removeprefix("/").split("@", 1)[0]
    service: StrategyService | None = context.bot_data.get("strategy_service")
    if service is not None and raw.lower().endswith("_chart"):
        context.args = [raw[:-6], "6m", "ema,rsi,macd"]
        await chart_command(update, context)
        return
    try:
        symbol = normalize_symbol(raw)
    except ValueError:
        symbol = ""
    if service is not None and symbol:
        result = await asyncio.to_thread(service.evaluate, symbol)
        if result.technical is not None:
            await _reply(update, format_signal(result))
            return
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
