from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import (
    help_command,
    market_command,
    notifications_off_command,
    notifications_on_command,
    price_command,
    start_command,
    strategy_not_configured_command,
    signal_command,
    signal_detail_callback,
    scan_command,
    filtered_scan_command,
    watchlist_command,
)
from bot.formatters import format_backtest
from signal_engine.engine import BacktestResult
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
    message_text: str = "",
    market_store: object | None = None,
) -> tuple[SimpleNamespace, SimpleNamespace, AsyncMock]:
    reply_text = AsyncMock()
    update = SimpleNamespace(
        effective_message=SimpleNamespace(reply_text=reply_text, text=message_text),
        effective_chat=SimpleNamespace(id=12345),
    )
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
            "market_store": market_store,
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
    assert "TÍN HIỆU" in start_text
    assert "THỊ TRƯỜNG & BIỂU ĐỒ" in start_text
    assert "/price <MÃ>" in start_text
    assert "/signal" in start_text
    assert "/price" in help_text
    assert "/signal" in help_text
    assert "━" not in start_text
    assert "\n\n\n" not in start_text


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

    assert "chưa được cấu hình" in reply_text.await_args.args[0]


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
    assert "+500.00" in text
    assert "Cập nhật" not in text


@pytest.mark.asyncio
async def test_market_reports_unconfigured_data_source() -> None:
    update, context, reply_text = make_update_and_context()

    await market_command(update, context)

    assert "chưa được cấu hình" in reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_strategy_commands_never_generate_fake_signals() -> None:
    update, context, reply_text = make_update_and_context()

    await strategy_not_configured_command(update, context)

    text = reply_text.await_args.args[0]
    assert "chưa sẵn sàng" in text
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
    assert "THEO DÕI" in text
    assert "T2A" not in text
    assert "eight_quarters" not in text
    assert reply_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_scan_command_returns_compact_signal_list() -> None:
    item = SimpleNamespace(symbol="HPG", action="BUY", phase="CONFIRMED_EOD",
                           technical=SimpleNamespace(t2a_score=3, t2b_score=4))
    service = SimpleNamespace(scan=lambda limit=10: [item])
    update, context, reply_text = make_update_and_context(strategy_service=service)

    await scan_command(update, context)

    assert "HPG" in reply_text.await_args.args[0]
    assert "🟢" in reply_text.await_args.args[0]


def _scan_item(symbol: str, action: str, technical_action: str | None = None):
    return SimpleNamespace(
        symbol=symbol,
        action=action,
        phase="CONFIRMED_EOD",
        technical=SimpleNamespace(
            action=technical_action or action,
            t2a_score=2,
            t2b_score=3,
            metrics={"close": 25.0},
        ),
    )


@pytest.mark.asyncio
async def test_tinhieu_balances_buy_watch_and_sell_signals() -> None:
    items = [
        _scan_item("AAA", "REJECT_FUNDAMENTALS", "SELL_OR_SKIP"),
        _scan_item("BBB", "BUY"),
        _scan_item("CCC", "WATCH"),
        _scan_item("DDD", "SELL_OR_SKIP"),
    ]
    service = SimpleNamespace(scan=lambda limit=50: items)
    update, context, reply_text = make_update_and_context(
        strategy_service=service, message_text="/tinhieu",
    )

    await filtered_scan_command(update, context)

    text = reply_text.await_args.args[0]
    assert all(symbol in text for symbol in ("BBB", "CCC", "AAA", "DDD"))
    assert text.index("BBB") < text.index("AAA")


@pytest.mark.asyncio
async def test_buy_uses_watch_candidates_when_no_clear_buy_exists() -> None:
    items = [
        _scan_item("AAA", "SELL_OR_SKIP"),
        _scan_item("CCC", "WATCH"),
    ]
    service = SimpleNamespace(scan=lambda limit=50: items)
    update, context, reply_text = make_update_and_context(
        strategy_service=service, message_text="/buy",
    )

    await filtered_scan_command(update, context)

    text = reply_text.await_args.args[0]
    assert "CCC" in text
    assert "AAA" not in text
    assert "Chờ tín hiệu rõ hơn" in text


@pytest.mark.asyncio
async def test_signal_detail_callback_returns_readable_sections() -> None:
    result = SimpleNamespace(
        symbol="HPG", company_name="Hòa Phát", exchange="HOSE",
        phase="CONFIRMED_EOD", action="WATCH",
        technical=SimpleNamespace(
            action="WATCH", t0_pass=True, t2a_score=2, t2b_score=3,
            metrics={"close": 28.5, "ema20": 28.0, "ema50": 27.0,
                     "rsi14": 58.0, "volume_ratio": 1.3, "macd": .7,
                     "macd_signal": .8, "rs3m": .035},
            warnings=(), missing=(),
        ),
        fundamentals=SimpleNamespace(
            mandatory_pass=False, grade=None,
            metrics={"roe": .267, "revenue_growth_yoy": -.171,
                     "profit_growth_yoy": -.062, "debt_to_equity": .8,
                     "current_ratio": 1.56},
            warnings=(), failures=("profit_growth_below_15pct",), missing=(),
        ),
        foreign={"rows": 0}, sector_policy="ASSUMED_NON_FINANCIAL", missing=(),
    )
    service = SimpleNamespace(evaluate=lambda symbol: result)
    reply_text = AsyncMock()
    query = SimpleNamespace(data="signal_detail|HPG", answer=AsyncMock(),
                            message=SimpleNamespace(reply_text=reply_text))
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data={"strategy_service": service})

    await signal_detail_callback(update, context)

    text = reply_text.await_args.args[0]
    assert "KỸ THUẬT" in text
    assert "CƠ BẢN" in text
    assert "THAM KHẢO" in text
    assert "\n\n" in text
    keyboard = reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    assert [button.text for row in keyboard for button in row] == ["📈 Biểu đồ"]


def test_backtest_output_omits_trade_count() -> None:
    result = BacktestResult(
        "HPG", "TECHNICAL_ONLY", 496, (), .10, .05, .12, None, -.08, 0, (),
    )

    text = format_backtest(result)

    assert "496 phiên" in text
    assert "lệnh" not in text


@pytest.mark.asyncio
async def test_clicked_scan_symbol_returns_signal_actions() -> None:
    result = _scan_item("MSN", "WATCH")
    result.company_name = "Masan"
    result.exchange = "HOSE"
    service = SimpleNamespace(evaluate=lambda symbol: result)
    update, context, reply_text = make_update_and_context(
        strategy_service=service, message_text="/MSN",
    )

    from bot.handlers import unknown_command
    await unknown_command(update, context)

    keyboard = reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    assert [button.text for row in keyboard for button in row] == [
        "📋 Xem chi tiết", "📈 Biểu đồ",
    ]


@pytest.mark.asyncio
async def test_filtered_scan_requests_the_full_market() -> None:
    calls = []
    service = SimpleNamespace(scan=lambda limit=None: calls.append(limit) or [])
    update, context, _reply_text = make_update_and_context(
        strategy_service=service, message_text="/tinhieu",
    )

    await filtered_scan_command(update, context)

    assert calls == [None]


@pytest.mark.asyncio
async def test_filtered_scan_replies_immediately_while_snapshot_is_loading() -> None:
    service = SimpleNamespace(scan_snapshot_ready=False)
    update, context, reply_text = make_update_and_context(
        strategy_service=service, message_text="/tinhieu",
    )

    await filtered_scan_command(update, context)

    assert "snapshot" in reply_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_notification_commands_persist_current_chat() -> None:
    class Store:
        def __init__(self):
            self.ids = set()
        def subscribe_notifications(self, chat_id):
            before = len(self.ids); self.ids.add(chat_id); return len(self.ids) > before
        def unsubscribe_notifications(self, chat_id):
            if chat_id not in self.ids: return False
            self.ids.remove(chat_id); return True

    store = Store()
    update, context, reply_text = make_update_and_context(market_store=store)
    await notifications_on_command(update, context)
    assert store.ids == {12345}
    assert "Đã bật" in reply_text.await_args.args[0]

    await notifications_off_command(update, context)
    assert store.ids == set()
    assert "Đã tắt" in reply_text.await_args.args[0]
