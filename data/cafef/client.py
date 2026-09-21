"""Rate-limited client for CafeF's public data pages."""

from dataclasses import dataclass
from datetime import date
import json
import random
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://cafef.vn"
EXCHANGES = frozenset({"HOSE", "HNX", "UPCOM"})


class CafeFError(RuntimeError):
    pass


class Transport(Protocol):
    def get(self, url: str) -> bytes: ...


class RateLimitedTransport:
    def __init__(self, *, requests_per_second: float = 0.5,
                 timeout_seconds: float = 30.0, retries: int = 3) -> None:
        if not 0 < requests_per_second <= 1:
            raise ValueError("requests_per_second must be in (0, 1]")
        self._interval = 1 / requests_per_second
        self._timeout = timeout_seconds
        self._retries = retries
        self._last_request = 0.0

    def get(self, url: str) -> bytes:
        if not url.startswith((f"{BASE_URL}/", "https://cafefnew.mediacdn.vn/",
                               "https://apiweb.cafef.vn/")):
            raise ValueError("CafeF transport only allows known HTTPS hosts")
        for attempt in range(self._retries + 1):
            remaining = self._interval - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            request = Request(
                url,
                headers={
                    "Accept": "application/json,text/html;q=0.9",
                    "Referer": f"{BASE_URL}/du-lieu.chn",
                    "User-Agent": "TelegramTradingBot/1.0 (EOD backup; contact owner)",
                },
            )
            try:
                self._last_request = time.monotonic()
                with urlopen(request, timeout=self._timeout) as response:
                    return response.read()
            except HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == self._retries:
                    raise CafeFError(f"CafeF HTTP {error.code}") from error
                retry_after = error.headers.get("Retry-After")
                delay = min(float(retry_after), 300) if retry_after else 2 ** attempt
            except (URLError, TimeoutError) as error:
                if attempt == self._retries:
                    raise CafeFError("CafeF network request failed") from error
                delay = 2 ** attempt
            time.sleep(delay + random.uniform(0, 0.25))
        raise AssertionError("retry loop exhausted")


@dataclass(frozen=True)
class DataPage:
    total_count: int
    rows: tuple[dict[str, object], ...]


class CafeFClient:
    def __init__(self, *, transport: Transport | None = None) -> None:
        self._transport = transport or RateLimitedTransport()

    def get_price_page(self, *, exchange: str, start: date, end: date,
                       page: int, page_size: int) -> DataPage:
        return self._get_data_page(
            "/du-lieu/Ajax/PageNew/DataHistory/PriceHistory.ashx",
            "ExchangeType", exchange, start, end, page, page_size,
        )

    def _get_data_page(self, path: str, exchange_key: str, exchange: str,
                       start: date, end: date, page: int,
                       page_size: int) -> DataPage:
        exchange = exchange.upper()
        if exchange not in EXCHANGES:
            raise ValueError("exchange must be HOSE, HNX, or UPCOM")
        # CafeF silently caps responses at 20 rows even when a larger value is sent.
        if start > end or page < 1 or not 1 <= page_size <= 20:
            raise ValueError("invalid date range or pagination")
        query = urlencode({
            exchange_key: exchange,
            "Symbol": "ALL",
            "StartDate": start.strftime("%m/%d/%Y"),
            "EndDate": end.strftime("%m/%d/%Y"),
            "PageIndex": page,
            "PageSize": page_size,
        })
        payload = self._get_json(f"{BASE_URL}{path}?{query}")
        if payload.get("Success") is not True or not isinstance(payload.get("Data"), dict):
            raise CafeFError("CafeF returned an unsuccessful data response")
        data = payload["Data"]
        rows = data.get("Data")
        if not isinstance(rows, list) or not isinstance(data.get("TotalCount"), int):
            raise CafeFError("CafeF data response schema changed")
        if not all(isinstance(row, dict) for row in rows):
            raise CafeFError("CafeF returned a non-object data row")
        return DataPage(total_count=data["TotalCount"], rows=tuple(rows))

    def get_company_catalog(self) -> tuple[dict[str, object], ...]:
        payload = self._get_json("https://cafefnew.mediacdn.vn/Search/company.json")
        if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
            raise CafeFError("CafeF company catalog schema changed")
        return tuple(payload)

    def get_financial_html(self, symbol: str, statement_type: str,
                           anchor_year: int, anchor_quarter: int) -> str:
        query = urlencode({"quarter": anchor_quarter, "symbol": symbol,
                           "type": statement_type, "year": anchor_year})
        raw = self._transport.get(f"{BASE_URL}/du-lieu/BaoCaoTaiChinh_V2.aspx?{query}")
        return raw.decode("utf-8", errors="replace")

    def get_financial_summary(self, symbol: str, *, page: int,
                              page_size: int = 4) -> object:
        query = urlencode({
            "symbol": symbol.upper(), "pageIndex": page, "pageSize": page_size,
            "reportType": "ALL", "TypeTime": "QUY",
        })
        return self._get_json(
            f"https://apiweb.cafef.vn/api/v1/BCTC/GetReportSummary?{query}"
        )

    def _get_json(self, url: str) -> object:
        try:
            return json.loads(self._transport.get(url))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CafeFError("CafeF returned invalid JSON") from error
