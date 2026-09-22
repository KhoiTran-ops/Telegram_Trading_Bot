import sqlite3

from data.db.market_store import MarketStore
from signal_engine.repository import StrategyRepository


def test_scan_universe_prioritizes_liquid_hose_over_hnx_and_upcom(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    with sqlite3.connect(store.path) as db:
        db.executemany(
            "INSERT INTO instruments(symbol,exchange,company_name,source,updated_at) VALUES (?,?,?,?,?)",
            [
                ("HLI", "HOSE", "Liquid HOSE", "test", "now"),
                ("HLO", "HOSE", "Quiet HOSE", "test", "now"),
                ("HNX", "HNX", "Volatile HNX", "test", "now"),
                ("UPC", "UPCOM", "Volatile UPCOM", "test", "now"),
            ],
        )
        for symbol, value in (("HLI", 20_000_000_000), ("HLO", 5_000_000_000),
                              ("HNX", 100_000_000_000), ("UPC", 200_000_000_000)):
            price = 10.0
            volume = int(value / price / 1_000)
            db.executemany(
                "INSERT INTO ohlcv_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(symbol, "1D", day, price, price, price, price, volume, 1, "test", "now")
                 for day in range(60)],
            )

    symbols = StrategyRepository(store.path).scan_symbols(limit=4)

    assert symbols[:2] == ["HLI", "HLO"]
    assert symbols[2:] == ["HNX", "UPC"]
