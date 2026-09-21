from datetime import date
import sqlite3

from data.cafef.parsers import parse_financial_periods, parse_financial_statement
from data.db.market_store import MarketStore


class Instrument:
    def __init__(self, symbol: str, exchange: str) -> None:
        self.symbol = symbol
        self.exchange = exchange
        self.company_name = symbol


def test_market_store_upserts_eod_without_duplicates(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    row = {
        "Symbol": "HPG",
        "Ngay": "18/09/2026",
        "GiaDieuChinh": 21.55,
        "GiaDongCua": 21.55,
        "ThayDoi": "+0,35 (+1,65%)",
        "KhoiLuongKhopLenh": 10,
        "GiaTriKhopLenh": 0.2,
        "KLThoaThuan": 0,
        "GtThoaThuan": 0,
        "GiaMoCua": 21.2,
        "GiaCaoNhat": 21.7,
        "GiaThapNhat": 21.1,
    }

    store.upsert_eod_rows("HOSE", [row], source="cafef")
    store.upsert_eod_rows("HOSE", [row], source="cafef")

    with sqlite3.connect(store.path) as connection:
        saved = connection.execute(
            "SELECT symbol, trade_date, close_thousand_vnd, source FROM eod_prices"
        ).fetchall()
    assert saved == [("HPG", "2026-09-18", 21.55, "cafef")]


def test_store_records_invalid_market_rows_as_anomalies(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()

    inserted, rejected = store.upsert_eod_rows(
        "HOSE", [{"Symbol": "HPG", "Ngay": "bad-date"}], source="cafef"
    )

    assert (inserted, rejected) == (0, 1)
    assert store.anomaly_count() == 1


def test_store_keeps_but_flags_inconsistent_ohlc(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    row = {
        "Symbol": "HPG", "Ngay": "18/09/2026", "GiaDongCua": 22,
        "GiaMoCua": 21, "GiaCaoNhat": 20, "GiaThapNhat": 19,
    }

    inserted, rejected = store.upsert_eod_rows("HOSE", [row], source="cafef")

    assert (inserted, rejected) == (1, 0)
    assert store.anomaly_count() == 1

    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM backtest_eod_prices").fetchone()[0] == 0


def test_catalog_reconciliation_removes_only_known_wrong_exchange_rows(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    row = {"Symbol": "ILC", "Ngay": "02/01/2006", "GiaDongCua": 10}
    moved = {"Symbol": "MOVED", "Ngay": "03/01/2006", "GiaDongCua": 11}
    unknown = {"Symbol": "OLD", "Ngay": "02/01/2006", "GiaDongCua": 5}
    store.upsert_eod_rows("HNX", [row, moved, unknown], source="cafef")
    store.upsert_eod_rows("UPCOM", [row, unknown], source="cafef")

    store.upsert_instruments([
        Instrument("ILC", "UPCOM"), Instrument("MOVED", "UPCOM")
    ], source="cafef")
    removed = store.reconcile_exchange_scopes()

    with sqlite3.connect(store.path) as connection:
        ilc = connection.execute(
            "SELECT exchange FROM eod_prices WHERE symbol='ILC'"
        ).fetchall()
        old = connection.execute(
            "SELECT exchange FROM eod_prices WHERE symbol='OLD' ORDER BY exchange"
        ).fetchall()
        moved_exchange = connection.execute(
            "SELECT exchange FROM eod_prices WHERE symbol='MOVED'"
        ).fetchall()
    assert removed == 2
    assert ilc == [("UPCOM",)]
    assert moved_exchange == [("UPCOM",)]
    assert old == [("HNX",), ("UPCOM",)]


def test_dnse_catalog_replacement_removes_non_dnse_instruments(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    store.upsert_instruments([
        Instrument("HPG", "HOSE"), Instrument("OLD", "UPCOM")
    ], source="cafef")

    store.replace_instruments([Instrument("HPG", "HOSE")], source="dnse")

    assert store.list_instruments() == [("HPG", "HOSE")]


def test_financial_parser_preserves_raw_values_and_missing_cells() -> None:
    html = """
    <table id="tblGridData"><tr><td>Chỉ tiêu</td><td>Quý 4-2024</td><td>Quý 1-2025</td></tr></table>
    <table id="tableContent">
      <tr><td>Lợi nhuận sau thuế</td><td>1.234.000</td><td>-</td>
      <td><table><tr><td>chart</td></tr></table></td></tr>
    </table>
    """

    facts = parse_financial_statement(html)

    assert facts == [
        {
            "row_order": 0,
            "item_name": "Lợi nhuận sau thuế",
            "values": {
                (2024, 4): ("1.234.000", 1234000),
                (2025, 1): ("-", None),
            },
        }
    ]


def test_daily_window_is_one_calendar_day() -> None:
    assert MarketStore.normalize_date(date(2026, 9, 20)) == "2026-09-20"


def test_initialize_migrates_early_eod_column_names(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE eod_prices (
            exchange TEXT, symbol TEXT, trade_date TEXT, adjusted_close REAL,
            close REAL, change_text TEXT, matched_volume INTEGER,
            matched_value_billion REAL, negotiated_volume INTEGER,
            negotiated_value_billion REAL, open REAL, high REAL, low REAL,
            source TEXT, retrieved_at TEXT, raw_json TEXT,
            PRIMARY KEY(exchange,symbol,trade_date))""")

    MarketStore(path).initialize()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(eod_prices)")}
    assert "close_thousand_vnd" in columns
    assert "close" not in columns


def test_initialize_replaces_annual_financial_tables_with_quarterly_schema(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE financial_facts (
            symbol TEXT, statement_type TEXT, fiscal_year INTEGER,
            row_order INTEGER, item_name TEXT, value_raw TEXT,
            value_numeric REAL, source TEXT, retrieved_at TEXT)""")
        connection.execute("""CREATE TABLE financial_periods (
            symbol TEXT, fiscal_year INTEGER, audit_status TEXT,
            is_audited INTEGER, report_code TEXT, source TEXT, retrieved_at TEXT)""")
        connection.execute(
            "INSERT INTO financial_facts VALUES ('BBC','IncSta',2025,0,'x','1',1,'cafef','now')"
        )

    MarketStore(path).initialize()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(financial_facts)"
        )}
        count = connection.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0]
    assert "fiscal_quarter" in columns
    assert count == 0


def test_store_upserts_dnse_bars_and_tracks_latest_timestamp(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    bar = {
        "symbol": "HPG", "timeframe": "1m", "timestamp": 1_700_000_000,
        "open": 27.1, "high": 27.2, "low": 27.0, "close": 27.15,
        "volume": 100, "is_closed": False,
    }
    store.upsert_ohlcv_bars([bar], source="dnse")
    store.upsert_ohlcv_bars([{**bar, "close": 27.2, "is_closed": True}], source="dnse")

    with sqlite3.connect(store.path) as connection:
        saved = connection.execute(
            "SELECT symbol,timeframe,ts,close,volume,is_closed,source FROM ohlcv_bars"
        ).fetchall()

    assert saved == [("HPG", "1m", 1_700_000_000, 27.2, 100, 1, "dnse")]
    assert store.latest_bar_timestamp("HPG", "1m") == 1_700_000_000

    store.mark_bars_closed_before("HPG", "1m", 1_700_000_060)
    assert store.latest_market_price("HPG") == (27.2, 1_700_000_000)


def test_financial_period_parser_keeps_quarter_and_audit_status() -> None:
    payload = {"isSuccess": True, "value": {"count": 2, "data": [{
        "code": "KQKD", "data": [
            {"symbol": "BBC", "year": 2025, "quater": 2,
             "type": "HK", "content": "Đã kiểm toán"},
            {"symbol": "BBC", "year": 2025, "quater": 1,
             "type": "HN", "content": "Chưa kiểm toán"},
        ],
    }]}}

    periods, total = parse_financial_periods(payload)

    assert total == 2
    assert periods == [
        {"symbol": "BBC", "fiscal_year": 2025, "fiscal_quarter": 2,
         "audit_status": "Đã kiểm toán",
         "is_audited": True, "report_code": "HK"},
        {"symbol": "BBC", "fiscal_year": 2025, "fiscal_quarter": 1,
         "audit_status": "Chưa kiểm toán",
         "is_audited": False, "report_code": "HN"},
    ]
