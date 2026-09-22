"""Thin Telegram handlers for the currently supported bot commands."""

import logging
import asyncio
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
    format_signal_detail,
    format_watchlist,
)
from common.watchlist import WatchlistConfig, normalize_symbol
from data.providers import (
    FailoverMarketDataProvider,
    MarketDataNotConfiguredError,
    MarketDataUnavailableError,
)
from data.db.market_store import MarketStore
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


async def notifications_on_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat = update.effective_chat
    store: MarketStore | None = context.bot_data.get("market_store")
    if chat is None or store is None:
        await _reply(update, "⚠️ Chưa thể bật thông báo lúc này.")
        return
    created = await asyncio.to_thread(store.subscribe_notifications, chat.id)
    status = "Đã bật" if created else "Thông báo đã được bật trước đó"
    await _reply(update, f"✅ {status}\n\n🌤 Phiên sáng: 11:35\n🌙 Cuối ngày: 15:05")


async def notifications_off_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat = update.effective_chat
    store: MarketStore | None = context.bot_data.get("market_store")
    if chat is None or store is None:
        await _reply(update, "⚠️ Chưa thể tắt thông báo lúc này.")
        return
    removed = await asyncio.to_thread(store.unsubscribe_notifications, chat.id)
    await _reply(update, "🔕 Đã tắt thông báo tự động." if removed
                 else "ℹ️ Chat này chưa đăng ký thông báo.")


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
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            format_signal(result), reply_markup=_signal_keyboard(symbol),
        )


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
    results = await asyncio.to_thread(service.scan, limit=None)
    buys = [item for item in results if item.action.endswith("BUY")]
    watches = [item for item in results if "WATCH" in item.action]
    sells = [item for item in results if (
        "SELL" in item.action
        or (item.technical is not None and "SELL" in item.technical.action)
    )]
    if command in ("/buy", "/mua"):
        selected = buys or watches
        title = ("TÍN HIỆU MUA" if buys
                 else "CHƯA CÓ TÍN HIỆU MUA RÕ · ĐANG THEO DÕI")
    elif command in ("/sell", "/ban"):
        selected = sells
        title = "TÍN HIỆU BÁN / THẬN TRỌNG"
    else:
        selected = buys[:4] + watches[:3] + sells[:3]
        title = "TÍN HIỆU ĐÁNG CHÚ Ý"
    await _reply(update, format_scan(selected[:10], title=title))


def _signal_keyboard(symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 Xem chi tiết", callback_data=f"signal_detail|{symbol}"),
        InlineKeyboardButton("📈 Biểu đồ", callback_data=f"chart|{symbol}|3m|all"),
    ]])


def _detail_keyboard(symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📈 Biểu đồ", callback_data=f"chart|{symbol}|3m|all"),
    ]])


async def signal_detail_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    await query.answer()
    _kind, symbol = query.data.split("|", 1)
    service: StrategyService | None = context.bot_data.get("strategy_service")
    if service is None:
        if query.message is not None:
            await query.message.reply_text(SIGNAL_NOT_CONFIGURED_TEXT)
        return
    result = await asyncio.to_thread(service.evaluate, symbol)
    if query.message is not None:
        await query.message.reply_text(
            format_signal_detail(result), reply_markup=_detail_keyboard(symbol),
        )


async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        options = parse_chart_args(list(context.args))
    except ValueError as error:
        await _reply(update, str(error))
        return
    await _send_chart(update, context, options)


def _chart_keyboard(symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("3 tháng", callback_data=f"chart|{symbol}|3m|all"),
         InlineKeyboardButton("6 tháng", callback_data=f"chart|{symbol}|6m|all"),
         InlineKeyboardButton("1 năm", callback_data=f"chart|{symbol}|1y|all")],
        [InlineKeyboardButton("EMA + RSI", callback_data=f"chart|{symbol}|3m|ema,rsi"),
         InlineKeyboardButton("Đầy đủ chỉ báo", callback_data=f"chart|{symbol}|3m|all")],
    ])


async def _send_chart(update: Update, context: ContextTypes.DEFAULT_TYPE, options) -> None:
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
        message = update.effective_message
        if message is not None:
            period = (f"{options.start_date} → {options.end_date}"
                      if options.start_date else {"3m": "3 tháng", "6m": "6 tháng", "1y": "1 năm"}[options.period])
            labels = {"ema": "EMA20/50", "rsi": "RSI14", "macd": "MACD", "obv": "OBV"}
            caption = (f"📊 {options.symbol} · {period}\n"
                       f"Nến ngày · Khối lượng · {' · '.join(labels[x] for x in options.indicators)}\n"
                       "Chọn nhanh khoảng thời gian hoặc bộ chỉ báo bên dưới.")
            with chart.open("rb") as image:
                await message.reply_photo(image, caption=caption,
                                          reply_markup=_chart_keyboard(options.symbol))
    finally:
        chart.unlink(missing_ok=True)


async def chart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    await query.answer()
    _kind, symbol, period, indicators = query.data.split("|", 3)
    selected = "ema,rsi,macd,obv" if indicators == "all" else indicators
    options = parse_chart_args([symbol, period, selected])
    await _send_chart(update, context, options)


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
        context.args = [raw[:-6]]
        await chart_command(update, context)
        return
    try:
        symbol = normalize_symbol(raw)
    except ValueError:
        symbol = ""
    if service is not None and symbol:
        result = await asyncio.to_thread(service.evaluate, symbol)
        if result.technical is not None:
            if update.effective_message is not None:
                await update.effective_message.reply_text(
                    format_signal(result), reply_markup=_signal_keyboard(symbol),
                )
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
