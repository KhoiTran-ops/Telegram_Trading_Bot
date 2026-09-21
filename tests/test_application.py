from common.config import Settings
from common.watchlist import WatchlistConfig
from bot.application import create_application


def test_application_registers_commands_without_dnse_credentials(tmp_path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_path.write_text(
        "confirmed: false\nwatchlist: [HPG]\nrealtime_universe: []\n",
        encoding="utf-8",
    )
    settings = Settings(
        telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEFG",
        watchlist_path=watchlist_path,
        _env_file=None,
    )

    application = create_application(settings)

    assert application.bot_data["watchlist"] == WatchlistConfig(
        confirmed=False,
        watchlist=("HPG",),
        realtime_universe=(),
    )
    assert application.bot_data["market_data"].configured is False

    registered_commands = {
        command
        for handler in application.handlers[0]
        for command in getattr(handler, "commands", ())
    }
    assert {
        "start",
        "help",
        "watchlist",
        "price",
        "market",
        "signal",
        "check",
        "alert",
        "scan",
    } <= registered_commands


def test_application_exposes_dnse_service_for_process_lifecycle(tmp_path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_path.write_text(
        "confirmed: false\nwatchlist: []\nrealtime_universe: []\n",
        encoding="utf-8",
    )
    settings = Settings(
        telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEFG",
        dnse_api_key="key",
        dnse_api_secret="secret",
        database_path=tmp_path / "market.db",
        watchlist_path=watchlist_path,
        _env_file=None,
    )

    application = create_application(settings)

    assert "market_data_service" in application.bot_data
    assert "market_data_task" not in application.bot_data
    assert application.bot_data["market_data"].configured is True
