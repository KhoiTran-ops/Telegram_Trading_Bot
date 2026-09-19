"""Telegram application assembly without external market-data assumptions."""

from collections.abc import Sequence

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.handlers import (
    error_handler,
    help_command,
    market_command,
    price_command,
    start_command,
    strategy_not_configured_command,
    unknown_command,
    watchlist_command,
)
from common.config import Settings
from common.watchlist import load_watchlist
from data.providers import FailoverMarketDataProvider, MarketDataProvider


def create_application(
    settings: Settings,
    providers: Sequence[MarketDataProvider] = (),
) -> Application:
    """Build the bot; providers are ordered from primary to last fallback."""
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["watchlist"] = load_watchlist(settings.watchlist_path)
    application.bot_data["market_data"] = FailoverMarketDataProvider(providers)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("watchlist", watchlist_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("market", market_command))
    application.add_handler(
        CommandHandler(
            ["signal", "check", "alert", "scan"],
            strategy_not_configured_command,
        )
    )
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    application.add_error_handler(error_handler)
    return application

