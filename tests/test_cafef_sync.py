from datetime import date, datetime, timedelta, timezone

from data.cafef.client import DataPage
from data.cafef.client import CafeFError
from data.cafef.sync import (
    CafeFSynchronizer, Instrument, catalog_instruments, next_daily_run,
    sync_financial_history,
)
from data.db.market_store import MarketStore


class PagingClient:
    def __init__(self) -> None:
        self.pages: list[int] = []

    def get_price_page(self, **kwargs: object) -> DataPage:
        page = int(kwargs["page"])
        self.pages.append(page)
        row = {
            "Symbol": f"T{page}", "Ngay": "18/09/2026",
            "GiaDongCua": page,
        }
        return DataPage(total_count=2, rows=(row,))

def test_sync_follows_all_pages_and_persists_checkpoint(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    client = PagingClient()
    sync = CafeFSynchronizer(client=client, store=store, page_size=1)

    result = sync.sync_market_dataset(
        dataset="prices", exchange="HOSE",
        start=date(2026, 9, 18), end=date(2026, 9, 18),
    )

    assert client.pages == [1, 2]
    assert result.saved == 2
    assert store.get_checkpoint("cafef:prices:HOSE:2026-09-18:2026-09-18") == "2"


def test_catalog_filters_only_three_listed_exchanges() -> None:
    rows = [
        {"Symbol": "HPG", "Title": "Hoa Phat", "RedirectUrl": "/du-lieu/hose/hpg-x.chn"},
        {"Symbol": "SHS", "Title": "Sai Gon Ha Noi", "RedirectUrl": "/du-lieu/hastc/shs-x.chn"},
        {"Symbol": "A32", "Title": "A32", "RedirectUrl": "/du-lieu/upcom/a32-x.chn"},
        {"Symbol": "24H", "Title": "24H", "RedirectUrl": "/du-lieu/otc/24h-x.chn"},
    ]

    assert [(x.symbol, x.exchange) for x in catalog_instruments(rows)] == [
        ("HPG", "HOSE"), ("SHS", "HNX"), ("A32", "UPCOM")
    ]


def test_next_daily_run_uses_ho_chi_minh_time() -> None:
    vietnam_time = timezone(timedelta(hours=7))
    now = datetime(2026, 9, 20, 14, 59, tzinfo=vietnam_time)

    assert next_daily_run(now, hour=15, minute=0) == datetime(
        2026, 9, 20, 15, 0, tzinfo=vietnam_time
    )


def test_daily_sync_reconciles_symbols_returned_under_old_exchange(tmp_path) -> None:
    class TransferClient(PagingClient):
        def get_price_page(self, **kwargs: object) -> DataPage:
            return DataPage(total_count=1, rows=({
                "Symbol": "ILC", "Ngay": "18/09/2026", "GiaDongCua": 10,
            },))

    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    store.upsert_instruments([Instrument("ILC", "UPCOM", "ILC")], source="cafef")

    CafeFSynchronizer(client=TransferClient(), store=store).sync_daily(date(2026, 9, 18))

    assert store.statistics()["eod_prices"] == 1


def test_financial_sync_stores_quarterly_facts_and_audit_status(tmp_path) -> None:
    class FinancialClient:
        def __init__(self) -> None:
            self.summary_pages: list[int] = []

        def get_financial_summary(self, symbol: str, *, page: int) -> object:
            self.summary_pages.append(page)
            periods = [
                {"symbol": symbol, "year": 2025 - ((index - 1) // 4),
                 "quater": 5 - index if index <= 4 else 9 - index,
                 "type": "HK", "content": "Đã kiểm toán"}
                for index in range((page - 1) * 4 + 1, page * 4 + 1)
            ]
            return {"isSuccess": True, "value": {"count": 12, "data": [{
                "code": "KQKD", "data": [
                    *periods,
                ],
            }]}}

        def get_financial_html(self, symbol: str, statement_type: str,
                               anchor_year: int, anchor_quarter: int) -> str:
            return """
            <table id="tblGridData"><tr><td>Chỉ tiêu</td><td>Quý 1-2025</td><td>Quý 2-2025</td></tr></table>
            <table id="tableContent"><tr><td>Lợi nhuận</td><td>10</td><td>20</td></tr></table>
            """

    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    store.upsert_instruments([Instrument("BBC", "HOSE", "Bibica")], source="dnse")
    store.replace_financial_facts("BBC", "IncSta", [{
        "row_order": 0, "item_name": "Dữ liệu cũ",
        "values": {(2020, 1): ("1", 1)},
    }], source="existing")

    client = FinancialClient()
    sync_financial_history(client, store, max_quarters=8)

    import sqlite3
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT fiscal_year,fiscal_quarter,is_audited FROM financial_periods "
            "ORDER BY fiscal_year,fiscal_quarter"
        ).fetchall() == [
            (2024, 1, 1), (2024, 2, 1), (2024, 3, 1), (2024, 4, 1),
            (2025, 1, 1), (2025, 2, 1), (2025, 3, 1), (2025, 4, 1),
        ]
        assert connection.execute(
            "SELECT DISTINCT fiscal_year,fiscal_quarter FROM financial_facts "
            "ORDER BY fiscal_year,fiscal_quarter"
        ).fetchall() == [(2020, 1), (2025, 1), (2025, 2)]
    assert client.summary_pages == [1, 2]


def test_financial_sync_continues_when_one_statement_is_missing(tmp_path) -> None:
    class Client:
        def get_financial_summary(self, symbol: str, *, page: int) -> object:
            return {"isSuccess": True, "value": {"count": 1, "data": [{
                "data": [{"symbol": symbol, "year": 2025, "quater": 1,
                          "type": "HK", "content": "Đã kiểm toán"}],
            }]}}

        def get_financial_html(self, symbol: str, statement_type: str,
                               anchor_year: int, anchor_quarter: int) -> str:
            if statement_type == "BSheet":
                raise CafeFError("CafeF HTTP 404")
            return '<table id="tblGridData"><tr><td>x</td><td>Quý 1-2025</td></tr></table><table id="tableContent"><tr><td>Lợi nhuận</td><td>20</td></tr></table>'

    store = MarketStore(tmp_path / "market.db")
    store.initialize()
    store.upsert_instruments([Instrument("BBC", "HOSE", "Bibica")], source="dnse")

    result = sync_financial_history(Client(), store, max_quarters=8)

    assert result.rejected == 1
    assert result.saved == 3
