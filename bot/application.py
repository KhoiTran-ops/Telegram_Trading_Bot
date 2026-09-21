"""Telegram application assembly without external market-data assumptions."""

from collections.abc import Sequence

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.handlers import (
    backtest_command,
    chat_id_command,
    chart_command,
    error_handler,
    help_command,
    filtered_scan_command,
    market_command,
    price_command,
    scan_command,
    signal_command,
    start_command,
    strategy_not_configured_command,
    unknown_command,
    watchlist_command,
)
from common.config import Settings
from common.watchlist import load_watchlist
from data.providers import FailoverMarketDataProvider, MarketDataProvider
from data.db.market_store import MarketStore
from data.dnse_market import DNSEMarketDataProvider, DNSEMarketService
from signal_engine.service import StrategyService


def create_application(
    settings: Settings,
    providers: Sequence[MarketDataProvider] = (),
) -> Application:
    """Build the bot; providers are ordered from primary to last fallback."""
    market_providers = list(providers)
    builder = Application.builder().token(settings.telegram_bot_token)
    if settings.dnse_configured:
        store = MarketStore(settings.database_path)
        store.initialize()
        service = DNSEMarketService(settings.dnse_api_key, settings.dnse_api_secret, store)
        market_providers.insert(0, DNSEMarketDataProvider(store))

    application = builder.build()
    if settings.dnse_configured:
        application.bot_data["market_data_service"] = service
    application.bot_data["watchlist"] = load_watchlist(settings.watchlist_path)
    application.bot_data["market_data"] = FailoverMarketDataProvider(market_providers)
    application.bot_data["strategy_service"] = StrategyService(settings.database_path)
    application.bot_data["summary_chat_ids"] = settings.summary_chat_ids

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("watchlist", watchlist_command))
    application.add_handler(CommandHandler("chatid", chat_id_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("market", market_command))
    application.add_handler(CommandHandler("thitruong", market_command))
    application.add_handler(CommandHandler("signal", signal_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler(["buy", "mua", "sell", "ban", "tinhieu"], filtered_scan_command))
    application.add_handler(CommandHandler("chart", chart_command))
    application.add_handler(CommandHandler("hieuqua", backtest_command))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    application.add_error_handler(error_handler)
    return application

