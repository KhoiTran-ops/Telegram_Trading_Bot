from datetime import datetime
from zoneinfo import ZoneInfo

from data.db.market_store import MarketStore
from signal_engine.service import StrategyService


def test_signal_uses_current_minute_data_and_marks_intraday_provisional(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    bars = [{
        "symbol": symbol, "timeframe": "1D", "timestamp": 1_700_000_000 + day * 86_400,
        "open": 20 + day * .1, "high": 20.3 + day * .1,
        "low": 19.8 + day * .1, "close": 20.1 + day * .1,
        "volume": 200_000, "is_closed": True,
    } for symbol in ("HPG", "VNINDEX") for day in range(100)]
    now = datetime(2026, 9, 22, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    minute_ts = int(now.replace(hour=9, minute=30).timestamp())
    bars.extend([{
        "symbol": symbol, "timeframe": "1m", "timestamp": minute_ts,
        "open": 31, "high": 32, "low": 30.5, "close": 31.5,
        "volume": 500_000, "is_closed": False,
    } for symbol in ("HPG", "VNINDEX")])
    store.upsert_ohlcv_bars(bars, source="dnse")

    result = StrategyService(store.path).evaluate("HPG", now=now)

    assert result.phase == "PROVISIONAL_INTRADAY"
    assert result.technical.metrics["close"] == 31.5
    assert result.action.startswith("TECHNICAL_ONLY_")


def test_signal_without_price_history_reports_not_available(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()

    result = StrategyService(store.path).evaluate("NONE")

    assert result.action == "NOT_AVAILABLE"
    assert "price_history" in result.missing


def test_full_scan_uses_refreshed_snapshot_without_recalculation(tmp_path) -> None:
    service = StrategyService(tmp_path / "market.db")
    service.repository.scan_symbols = lambda limit=None: ["AAA", "BBB"]
    calls = []
    service.evaluate = lambda symbol: calls.append(symbol) or symbol

    assert service.refresh_scan_snapshot() == 2
    assert service.scan(limit=None) == ["AAA", "BBB"]
    assert calls == ["AAA", "BBB"]
