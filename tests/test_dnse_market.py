import pytest

from data.dnse_market import (
    DNSEInstrument, DNSEMarketDataProvider, DNSESynchronizer,
    parse_foreign_trading, parse_ohlc,
)
from data.db.market_store import MarketStore


def test_parse_ohlc_validates_parallel_arrays() -> None:
    payload = {
        "t": [100, 200], "o": [10, 11], "h": [12, 13],
        "l": [9, 10], "c": [11, 12], "v": [1000, 2000], "nextTime": 0,
    }

    bars, next_time = parse_ohlc(payload, symbol="HPG", timeframe="1D")

    assert bars[1] == {
        "symbol": "HPG", "timeframe": "1D", "timestamp": 200,
        "open": 11.0, "high": 13.0, "low": 10.0, "close": 12.0,
        "volume": 2000, "is_closed": True,
    }
    assert next_time == 0


def test_parse_ohlc_preserves_source_ohlc_even_when_range_is_inconsistent() -> None:
    payload = {
        "t": [100, 200], "o": [13, 11], "h": [12, 13],
        "l": [9, 10], "c": [11, 12], "v": [1000, 2000], "nextTime": 0,
    }

    bars, _next_time = parse_ohlc(payload, symbol="HPG", timeframe="1D")

    assert [bar["timestamp"] for bar in bars] == [100, 200]
    assert bars[0]["open"] == 13.0
    assert bars[0]["high"] == 12.0


def test_backfill_resumes_after_latest_bar_and_limits_first_minute_day(tmp_path) -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int, int]] = []

        def list_stock_instruments(self) -> list[DNSEInstrument]:
            return [DNSEInstrument("HPG", "HOSE", "Hoa Phat", 1_000)]

        def get_ohlc(self, symbol: str, resolution: str,
                     start: int, end: int, *, asset_type: str = "STOCK") -> dict[str, object]:
            self.calls.append((symbol, resolution, start, end))
            return {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [],
                    "nextTime": 0}

    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    store.upsert_ohlcv_bars([{
        "symbol": "HPG", "timeframe": "1D", "timestamp": 2_000,
        "open": 10, "high": 10, "low": 10, "close": 10, "volume": 1,
        "is_closed": True,
    }], source="dnse")
    gateway = Gateway()

    DNSESynchronizer(gateway=gateway, store=store).backfill(now_ts=100_000,
                                                            day_start_ts=90_000)

    assert gateway.calls == [
        ("VNINDEX", "1", 90_000, 100_000),
        ("HPG", "1D", 2_001, 100_000),
        ("HPG", "1", 90_000, 100_000),
    ]


def test_index_backfill_uses_index_asset_type_without_adding_to_universe(tmp_path) -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def get_ohlc(self, symbol: str, resolution: str, start: int, end: int,
                     *, asset_type: str = "STOCK") -> dict[str, object]:
            self.calls.append((symbol, resolution, asset_type))
            return {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [],
                    "nextTime": 0}

    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    gateway = Gateway()

    DNSESynchronizer(gateway=gateway, store=store)._sync_index(
        now_ts=1_800_000_000, day_start_ts=1_799_900_000,
    )

    assert gateway.calls == [
        ("VNINDEX", "1D", "INDEX"), ("VNINDEX", "1", "INDEX"),
    ]
    assert store.list_instruments() == []


@pytest.mark.asyncio
async def test_market_provider_reads_latest_cached_bar(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    store.upsert_ohlcv_bars([{
        "symbol": "HPG", "timeframe": "1m", "timestamp": 1_700_000_000,
        "open": 27, "high": 28, "low": 26, "close": 27.5, "volume": 10,
        "is_closed": False,
    }], source="dnse")

    result = await DNSEMarketDataProvider(store).get_latest_price("hpg")

    assert result.symbol == "HPG"
    assert result.price == 27.5


def test_foreign_parser_preserves_board_snapshots() -> None:
    payload = {"foreigners": [{
        "symbol": "HPG", "boardId": "G1", "time": "2026-09-21 13:05:09.537",
        "totalBuyVolume": 413262, "totalBuyTradedAmount": 8802804150,
        "totalSellVolume": 1487403, "totalSellTradedAmount": 31660601200,
        "foreignerOrderLimitQuantity": 3827241,
        "foreignerBuyPossibleQuantity": 57013233,
    }]}

    rows = parse_foreign_trading(payload)

    assert rows[0]["symbol"] == "HPG"
    assert rows[0]["board_id"] == "G1"
    assert rows[0]["buy_volume"] == 413262
    assert rows[0]["sell_value"] == 31660601200
