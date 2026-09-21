from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import (
    help_command,
    market_command,
    price_command,
    start_command,
    strategy_not_configured_command,
    signal_command,
    scan_command,
    watchlist_command,
)
from common.types import MarketPrice
from common.watchlist import WatchlistConfig
from data.providers import FailoverMarketDataProvider


class FakeProvider:
    name = "backup"

    async def get_latest_price(self, symbol: str) -> MarketPrice:
        return MarketPrice(
            symbol=symbol,
            price=28_500.0,
            reference_price=28_000.0,
            timestamp=datetime(2026, 9, 19, 9, 30, tzinfo=UTC),
        )


def make_update_and_context(
    *,
    args: list[str] | None = None,
    provider: FailoverMarketDataProvider | None = None,
    strategy_service: object | None = None,
) -> tuple[SimpleNamespace, SimpleNamespace, AsyncMock]:
    reply_text = AsyncMock()
    update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply_text))
    context = SimpleNamespace(
        args=args or [],
        bot_data={
            "market_data": provider or FailoverMarketDataProvider([]),
            "watchlist": WatchlistConfig(
                confirmed=False,
                watchlist=("HPG", "FPT"),
                realtime_universe=("HPG",),
            ),
            "strategy_service": strategy_service,
        },
    )
    return update, context, reply_text


@pytest.mark.asyncio
async def test_start_and_help_explain_current_bot_scope() -> None:
    update, context, reply_text = make_update_and_context()

    await start_command(update, context)
    await help_command(update, context)

    start_text = reply_text.await_args_list[0].args[0]
    help_text = reply_text.await_args_list[1].args[0]
    assert "tham khảo" in start_text
    assert "Lệnh chung" in start_text
    assert "/start" in start_text
    assert "Dữ liệu thị trường" in start_text
    assert "/price <MÃ>" in start_text
    assert "Chiến lược" in start_text
    assert "/signal" in start_text
    assert "/price" in help_text
    assert "/signal" in help_text


@pytest.mark.asyncio
async def test_watchlist_is_explicitly_labeled_as_unconfirmed_sample() -> None:
    update, context, reply_text = make_update_and_context()

    await watchlist_command(update, context)

    text = reply_text.await_args.args[0]
    assert "chưa xác nhận" in text
    assert "HPG" in text


@pytest.mark.asyncio
async def test_price_requires_a_valid_symbol() -> None:
    update, context, reply_text = make_update_and_context(args=[])
    await price_command(update, context)
    assert "Cú pháp" in reply_text.await_args.args[0]

    update, context, reply_text = make_update_and_context(args=["HPG;DROP"])
    await price_command(update, context)
    assert "không hợp lệ" in reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_price_reports_unconfigured_data_source() -> None:
    update, context, reply_text = make_update_and_context(args=["hpg"])

    await price_command(update, context)

    assert reply_text.await_args.args[0].startswith("DATA_SOURCE_NOT_CONFIGURED")


@pytest.mark.asyncio
async def test_price_uses_configured_provider_and_displays_source() -> None:
    provider = FailoverMarketDataProvider([FakeProvider()])
    update, context, reply_text = make_update_and_context(
        args=["hpg"], provider=provider
    )

    await price_command(update, context)

    text = reply_text.await_args.args[0]
    assert "HPG" in text
    assert "28,500" in text
    assert "backup" in text


@pytest.mark.asyncio
async def test_market_reports_unconfigured_data_source() -> None:
    update, context, reply_text = make_update_and_context()

    await market_command(update, context)

    assert reply_text.await_args.args[0].startswith("DATA_SOURCE_NOT_CONFIGURED")


@pytest.mark.asyncio
async def test_strategy_commands_never_generate_fake_signals() -> None:
    update, context, reply_text = make_update_and_context()

    await strategy_not_configured_command(update, context)

    text = reply_text.await_args.args[0]
    assert text.startswith("NOT_CONFIGURED")
    assert "BUY" not in text.upper()
    assert "SELL" not in text.upper()
    assert "HOLD" not in text.upper()


@pytest.mark.asyncio
async def test_signal_command_evaluates_requested_symbol() -> None:
    service = SimpleNamespace(evaluate=lambda symbol: SimpleNamespace(
        symbol=symbol, company_name="Hoa Phat", exchange="HOSE",
        phase="PROVISIONAL_INTRADAY", action="TECHNICAL_ONLY_WATCH",
        technical=SimpleNamespace(
            t0_pass=True, t2a_score=2, t2b_score=3,
            metrics={"close": 28.5, "rsi14": 61.2, "stop": 27.0, "target": 31.5},
            warnings=(), missing=(),
        ),
        fundamentals=SimpleNamespace(
            mandatory_pass=None, grade=None, warnings=(), failures=(),
        ),
        foreign={"rows": 0}, sector_policy="ASSUMED_NON_FINANCIAL",
        missing=("eight_quarters", "foreign_trading"),
    ))
    update, context, reply_text = make_update_and_context(
        args=["hpg"], strategy_service=service
    )

    await signal_command(update, context)

    text = reply_text.await_args.args[0]
    assert "HPG" in text
    assert "TẠM THỜI" in text
    assert "T2A: 2/3" in text
    assert "eight_quarters" in text


@pytest.mark.asyncio
async def test_scan_command_returns_compact_signal_list() -> None:
    item = SimpleNamespace(symbol="HPG", action="BUY", phase="CONFIRMED_EOD",
                           technical=SimpleNamespace(t2a_score=3, t2b_score=4))
    service = SimpleNamespace(scan=lambda limit=10: [item])
    update, context, reply_text = make_update_and_context(strategy_service=service)

    await scan_command(update, context)

    assert "HPG" in reply_text.await_args.args[0]
    assert "BUY" in reply_text.await_args.args[0]
