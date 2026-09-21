"""CafeF audited financial statements and one-day EOD fallback."""

from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
import logging
import math
from typing import Iterable, Protocol

from data.cafef.client import CafeFClient, CafeFError, DataPage, EXCHANGES
from data.cafef.parsers import parse_financial_periods, parse_financial_statement
from data.db.market_store import MarketStore


logger = logging.getLogger(__name__)
STATEMENT_TYPES = ("BSheet", "IncSta", "CashFlow", "CashFlowDirect")


class SyncClient(Protocol):
    def get_price_page(self, **kwargs: object) -> DataPage: ...


@dataclass(frozen=True)
class Instrument:
    symbol: str
    exchange: str
    company_name: str


@dataclass(frozen=True)
class SyncResult:
    dataset: str
    saved: int
    rejected: int
    requests: int


def catalog_instruments(rows: Iterable[dict[str, object]]) -> list[Instrument]:
    exchange_aliases = {"hose": "HOSE", "hastc": "HNX", "upcom": "UPCOM"}
    instruments: list[Instrument] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        redirect = str(row.get("RedirectUrl", "")).lower()
        parts = [part for part in redirect.split("/") if part]
        exchange = exchange_aliases.get(parts[1], "") if len(parts) > 1 and parts[0] == "du-lieu" else ""
        symbol = str(row.get("Symbol", "")).strip().upper()
        if exchange not in EXCHANGES or not symbol or (symbol, exchange) in seen:
            continue
        seen.add((symbol, exchange))
        instruments.append(Instrument(symbol, exchange, str(row.get("Title", "")).strip()))
    return instruments


def next_daily_run(now: datetime, *, hour: int = 15, minute: int = 0) -> datetime:
    target = datetime.combine(now.date(), clock_time(hour, minute), tzinfo=now.tzinfo)
    return target if target > now else target + timedelta(days=1)


class CafeFSynchronizer:
    def __init__(self, *, client: SyncClient, store: MarketStore,
                 page_size: int = 20) -> None:
        self.client = client
        self.store = store
        self.page_size = page_size

    def sync_market_dataset(self, *, dataset: str, exchange: str,
                            start: date, end: date, resume: bool = True) -> SyncResult:
        if dataset != "prices":
            raise ValueError("CafeF market fallback only supports EOD prices")
        key = f"cafef:{dataset}:{exchange}:{start.isoformat()}:{end.isoformat()}"
        page = int(self.store.get_checkpoint(key) or 0) + 1 if resume else 1
        saved = rejected = requests = 0
        while True:
            response = self.client.get_price_page(
                exchange=exchange, start=start, end=end,
                page=page, page_size=self.page_size,
            )
            requests += 1
            added, bad = self.store.upsert_eod_rows(
                exchange, response.rows, source="cafef"
            )
            saved += added
            rejected += bad
            self.store.set_checkpoint(key, str(page))
            logger.info("CafeF page synchronized", extra={
                "event": "cafef_page_synchronized", "provider": "cafef",
                "operation": dataset,
            })
            total_pages = math.ceil(response.total_count / self.page_size)
            if page >= total_pages or not response.rows:
                break
            page += 1
        return SyncResult(dataset, saved, rejected, requests)

    def sync_daily(self, day: date) -> list[SyncResult]:
        results: list[SyncResult] = []
        for exchange in sorted(EXCHANGES):
            results.append(self.sync_market_dataset(
                dataset="prices", exchange=exchange, start=day, end=day,
                resume=False,
            ))
        self.store.reconcile_exchange_scopes()
        return results


def sync_catalog(client: CafeFClient, store: MarketStore) -> int:
    instruments = catalog_instruments(client.get_company_catalog())
    count = store.upsert_instruments(instruments, source="cafef")
    store.reconcile_exchange_scopes()
    return count


def sync_financial_history(client: CafeFClient, store: MarketStore, *,
                           max_quarters: int = 8) -> SyncResult:
    if max_quarters < 1:
        raise ValueError("max_quarters must be positive")
    saved = rejected = requests = 0
    for symbol, _exchange in store.list_instruments():
        periods: list[dict[str, object]] = []
        page = 1
        while True:
            try:
                block, total = parse_financial_periods(
                    client.get_financial_summary(symbol, page=page)
                )
            except (CafeFError, ValueError):
                rejected += 1
                break
            requests += 1
            periods.extend(block)
            if page * 4 >= min(total, max_quarters) or not block:
                break
            page += 1
        periods = sorted(
            periods,
            key=lambda period: (
                int(period["fiscal_year"]), int(period["fiscal_quarter"])
            ),
            reverse=True,
        )[:max_quarters]
        store.upsert_financial_periods(
            periods, source="https://apiweb.cafef.vn/api/v1/BCTC/GetReportSummary"
        )
        available_periods = {
            (int(period["fiscal_year"]), int(period["fiscal_quarter"]))
            for period in periods
        }
        for statement_type in STATEMENT_TYPES:
            ordered = sorted(available_periods, reverse=True)
            for offset in range(0, len(ordered), 4):
                anchor_year, anchor_quarter = ordered[offset]
                block_periods = set(ordered[offset:offset + 4])
                try:
                    html = client.get_financial_html(
                        symbol, statement_type, anchor_year, anchor_quarter
                    )
                except CafeFError:
                    rejected += 1
                    continue
                requests += 1
                facts = parse_financial_statement(html)
                source = (
                    "https://cafef.vn/du-lieu/BaoCaoTaiChinh_V2.aspx"
                    f"?quarter={anchor_quarter}&symbol={symbol}"
                    f"&type={statement_type}&year={anchor_year}"
                )
                filtered = []
                for fact in facts:
                    values = {
                        period: value for period, value in fact["values"].items()
                        if period in block_periods
                    }
                    if values:
                        filtered.append({**fact, "values": values})
                if filtered:
                    saved += store.replace_financial_facts(
                        symbol, statement_type, filtered, source=source
                    )
                else:
                    rejected += 1
                logger.info("CafeF financial block synchronized", extra={
                    "event": "cafef_financial_synchronized", "provider": "cafef",
                    "operation": statement_type,
                })
    return SyncResult("financials", saved, rejected, requests)


def build_default_sync(database_path: str, *, requests_per_second: float = 0.5
                       ) -> tuple[CafeFClient, MarketStore, CafeFSynchronizer]:
    from pathlib import Path
    from data.cafef.client import RateLimitedTransport
    client = CafeFClient(transport=RateLimitedTransport(
        requests_per_second=requests_per_second
    ))
    store = MarketStore(Path(database_path))
    store.initialize()
    return client, store, CafeFSynchronizer(client=client, store=store)


def ho_chi_minh_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh"))
