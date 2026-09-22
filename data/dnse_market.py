"""DNSE REST backfill and realtime market-data orchestration."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, time as clock_time, UTC
import logging
import time
from typing import Protocol
from zoneinfo import ZoneInfo

from dnse import DnseClient, DnseMarketStream

from data.db.market_store import MarketStore
from data.providers import ProviderUnavailableError
from common.types import MarketPrice


logger = logging.getLogger(__name__)
MARKETS = {"STO": "HOSE", "STX": "HNX", "UPX": "UPCOM"}
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
BENCHMARK_SYMBOL = "VNINDEX"
FOREIGN_LOOKBACK_SECONDS = 730 * 24 * 60 * 60


@dataclass(frozen=True)
class DNSEInstrument:
    symbol: str
    exchange: str
    company_name: str
    listed_at: int


class DNSEGatewayProtocol(Protocol):
    def list_stock_instruments(self) -> list[DNSEInstrument]: ...
    def get_ohlc(self, symbol: str, resolution: str,
                 start: int, end: int, *, asset_type: str = "STOCK") -> dict[str, object]: ...


def parse_ohlc(payload: dict[str, object], *, symbol: str,
               timeframe: str) -> tuple[list[dict[str, object]], int]:
    columns = [payload.get(key) for key in ("t", "o", "h", "l", "c", "v")]
    if not all(isinstance(column, list) for column in columns):
        raise ValueError("DNSE OHLC response schema changed")
    if len({len(column) for column in columns}) != 1:
        raise ValueError("DNSE OHLC columns have different lengths")
    bars = []
    for timestamp, opened, high, low, close, volume in zip(*columns):
        values = (opened, high, low, close)
        if not all(isinstance(value, (int, float)) for value in values):
            raise ValueError("DNSE OHLC contains a non-numeric price")
        bars.append({
            "symbol": symbol, "timeframe": timeframe, "timestamp": int(timestamp),
            "open": float(opened), "high": float(high), "low": float(low),
            "close": float(close), "volume": int(volume), "is_closed": True,
        })
    return bars, int(payload.get("nextTime") or 0)


def parse_foreign_trading(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload.get("foreigners")
    if not isinstance(rows, list):
        raise ValueError("DNSE foreign-trading response schema changed")
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = datetime.fromisoformat(str(row["time"])).replace(tzinfo=VIETNAM)
        parsed.append({
            "symbol": str(row["symbol"]).upper(),
            "board_id": str(row.get("boardId") or ""),
            "timestamp": int(timestamp.timestamp() * 1000),
            "buy_volume": int(row.get("totalBuyVolume") or 0),
            "buy_value": float(row.get("totalBuyTradedAmount") or 0),
            "sell_volume": int(row.get("totalSellVolume") or 0),
            "sell_value": float(row.get("totalSellTradedAmount") or 0),
            "order_limit_quantity": row.get("foreignerOrderLimitQuantity"),
            "buy_possible_quantity": row.get("foreignerBuyPossibleQuantity"),
        })
    return parsed


def foreign_history_window(now_ts: int, earliest_ms: int | None, *,
                           listed_at: int) -> tuple[int, int] | None:
    """Return the next backward request, bounded to the latest two years."""
    floor = now_ts - FOREIGN_LOOKBACK_SECONDS
    if earliest_ms is not None:
        end = earliest_ms // 1000 - 1
        if end < floor:
            return None
    else:
        end = now_ts
    start = max(floor, listed_at or floor, end - 1_800)
    return (start, end) if start <= end else None


class DNSEGateway:
    """Small adapter over DNSE's signed SDK with conservative pacing."""

    def __init__(self, api_key: str, api_secret: str, *, requests_per_second: float = 2) -> None:
        self.client = DnseClient(api_key=api_key, api_secret=api_secret)
        self.interval = 1 / requests_per_second
        self.last_request = 0.0

    def _get(self, path: str, params: dict[str, object]) -> dict[str, object]:
        delay = self.interval - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        response = self.client.get(path, params=params)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("DNSE returned a non-object response")
        return payload

    def list_stock_instruments(self) -> list[DNSEInstrument]:
        instruments = []
        page = 1
        while True:
            payload = self._get("/market/instruments", {
                "securityGroupId": "ST", "limit": 1000, "page": page,
            })
            rows = payload.get("data")
            if not isinstance(rows, list):
                raise ValueError("DNSE instrument response schema changed")
            for row in rows:
                if not isinstance(row, dict) or row.get("marketId") not in MARKETS:
                    continue
                listed = str(row.get("listedDate") or "").replace("-", "")
                listed_at = int(time.mktime(time.strptime(listed, "%Y%m%d"))) if listed else 0
                instruments.append(DNSEInstrument(
                    str(row["symbol"]).upper(), MARKETS[str(row["marketId"])],
                    str(row.get("name") or row.get("shortName") or ""), listed_at,
                ))
            if page * 1000 >= int(payload.get("total") or len(rows)):
                return instruments
            page += 1

    def get_ohlc(self, symbol: str, resolution: str,
                 start: int, end: int, *, asset_type: str = "STOCK") -> dict[str, object]:
        return self._get("/price/ohlc", {
            "type": asset_type, "symbol": symbol, "resolution": resolution,
            "from": start, "to": end,
        })

    def get_foreign_trading(self, symbol: str, start: int, end: int) -> dict[str, object]:
        return self._get(f"/price/{symbol}/foreign-trading", {
            "from": start, "to": end,
        })

    def close(self) -> None:
        self.client.close()


class DNSESynchronizer:
    def __init__(self, *, gateway: DNSEGatewayProtocol, store: MarketStore) -> None:
        self.gateway = gateway
        self.store = store

    def backfill(self, *, now_ts: int, day_start_ts: int) -> int:
        instruments = self.gateway.list_stock_instruments()
        self.store.replace_instruments(instruments, source="dnse")
        saved = self._sync_index(now_ts=now_ts, day_start_ts=day_start_ts)
        for instrument in instruments:
            daily_start = self.store.latest_bar_timestamp(instrument.symbol, "1D")
            minute_start = self.store.latest_bar_timestamp(instrument.symbol, "1m")
            saved += self._sync_range(instrument.symbol, "1D", "1D",
                                      (daily_start + 1) if daily_start else instrument.listed_at,
                                      now_ts)
            saved += self._sync_range(instrument.symbol, "1", "1m",
                                      (minute_start + 60) if minute_start else day_start_ts,
                                      now_ts)
        return saved

    def _sync_index(self, *, now_ts: int, day_start_ts: int) -> int:
        daily = self.store.latest_bar_timestamp(BENCHMARK_SYMBOL, "1D")
        minute = self.store.latest_bar_timestamp(BENCHMARK_SYMBOL, "1m")
        return self._sync_range(
            BENCHMARK_SYMBOL, "1D", "1D", (daily + 1) if daily else 946_684_800,
            now_ts, asset_type="INDEX",
        ) + self._sync_range(
            BENCHMARK_SYMBOL, "1", "1m", (minute + 60) if minute else day_start_ts,
            now_ts, asset_type="INDEX",
        )

    def _sync_range(self, symbol: str, resolution: str, timeframe: str,
                    start: int, end: int, *, asset_type: str = "STOCK") -> int:
        saved = 0
        while 0 < start <= end:
            bars, next_time = parse_ohlc(
                self.gateway.get_ohlc(
                    symbol, resolution, start, end, asset_type=asset_type
                ),
                symbol=symbol, timeframe=timeframe,
            )
            if timeframe == "1m":
                for bar in bars:
                    bar["is_closed"] = int(bar["timestamp"]) + 60 <= end
            saved += self.store.upsert_ohlcv_bars(bars, source="dnse")
            if not next_time or next_time <= start:
                break
            start = next_time
        return saved


class DNSEMarketDataProvider:
    name = "dnse"

    def __init__(self, store: MarketStore) -> None:
        self.store = store

    async def get_latest_price(self, symbol: str) -> MarketPrice:
        normalized = symbol.strip().upper()
        result = self.store.latest_market_price(normalized)
        if result is None:
            raise ProviderUnavailableError(f"no DNSE data for {normalized}")
        price, timestamp = result
        local = datetime.fromtimestamp(timestamp, VIETNAM)
        day_start = int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        reference = self.store.latest_reference_price(normalized, day_start)
        return MarketPrice(normalized, price, datetime.fromtimestamp(timestamp, UTC), reference)


class DNSEMarketService:
    """Catch up via REST, then persist one-minute DNSE WebSocket bars."""

    def __init__(self, api_key: str, api_secret: str, store: MarketStore) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.store = store
        self.queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=10_000)
        self.streams: list[DnseMarketStream] = []
        self.tasks: list[asyncio.Task[object]] = []

    async def run(self) -> None:
        logger.info("DNSE backfill started", extra={
            "event": "dnse_backfill_started", "provider": "dnse",
            "operation": "backfill",
        })
        foreign_task = asyncio.create_task(
            self._foreign_loop(), name="dnse-foreign-poller"
        )
        gateway = DNSEGateway(self.api_key, self.api_secret)
        try:
            now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
            day_start = datetime.combine(now.date(), clock_time(), tzinfo=now.tzinfo)
            await asyncio.to_thread(
                DNSESynchronizer(gateway=gateway, store=self.store).backfill,
                now_ts=int(now.timestamp()), day_start_ts=int(day_start.timestamp()),
            )
            logger.info("DNSE backfill completed", extra={
                "event": "dnse_backfill_completed", "provider": "dnse",
                "operation": "backfill",
            })
        finally:
            gateway.close()

        symbols = [symbol for symbol, _exchange in self.store.list_instruments()]
        stream_symbols = [*symbols, BENCHMARK_SYMBOL]
        self.tasks.extend((foreign_task, asyncio.create_task(
            self._writer(), name="dnse-db-writer"
        )))
        for offset in range(0, len(stream_symbols), 200):
            stream = DnseMarketStream(self.api_key, self.api_secret)
            stream.subscribe_ohlc(stream_symbols[offset:offset + 200], self._on_ohlc,
                                  timeframe="1m")
            self.streams.append(stream)
            self.tasks.append(asyncio.create_task(
                stream.run_async(), name=f"dnse-stream-{offset // 200 + 1}",
            ))
        logger.info("DNSE realtime started", extra={
            "event": "dnse_realtime_started", "provider": "dnse",
            "operation": "subscribe_ohlc", "symbols": len(stream_symbols),
            "connections": len(self.streams),
        })
        await asyncio.gather(*self.tasks)

    async def _foreign_loop(self) -> None:
        gateway = DNSEGateway(self.api_key, self.api_secret, requests_per_second=1)
        try:
            while True:
                instruments = [
                    DNSEInstrument(symbol, exchange, "", 0)
                    for symbol, exchange in self.store.list_instruments()
                ]
                if not instruments:
                    await asyncio.sleep(5)
                    continue
                for instrument in instruments:
                    now = datetime.now(VIETNAM)
                    earliest, latest = self.store.foreign_snapshot_bounds(instrument.symbol)
                    trading = (
                        now.weekday() < 5
                        and clock_time(8, 45) <= now.time() <= clock_time(15, 5)
                    )
                    if trading:
                        end = int(now.timestamp())
                        start = end - 300
                        history = False
                    else:
                        if self.store.get_checkpoint(
                            f"dnse:foreign:complete:{instrument.symbol}"
                        ) == "1":
                            continue
                        window = foreign_history_window(
                            int(now.timestamp()), earliest,
                            listed_at=instrument.listed_at,
                        )
                        if window is None:
                            self.store.set_checkpoint(
                                f"dnse:foreign:complete:{instrument.symbol}", "1"
                            )
                            continue
                        start, end = window
                        history = True
                    if start > end:
                        continue
                    try:
                        payload = await asyncio.to_thread(
                            gateway.get_foreign_trading, instrument.symbol, start, end
                        )
                        rows = parse_foreign_trading(payload)
                        await asyncio.to_thread(
                            self.store.upsert_foreign_snapshots, rows, source="dnse"
                        )
                        if history and not rows:
                            self.store.set_checkpoint(
                                f"dnse:foreign:complete:{instrument.symbol}", "1"
                            )
                    except Exception as error:
                        logger.warning(
                            "DNSE foreign-trading request failed: %s", error,
                            extra={"event": "dnse_foreign_failed", "provider": "dnse",
                                   "operation": "foreign_trading",
                                   "error_type": type(error).__name__},
                        )
                await asyncio.sleep(1)
        finally:
            gateway.close()

    async def _on_ohlc(self, message: object) -> None:
        values = {name: getattr(message, name, None) for name in
                  ("symbol", "timestamp", "open", "high", "low", "close", "volume")}
        if any(values[name] is None for name in values):
            logger.warning("DNSE discarded incomplete OHLC", extra={
                "event": "dnse_invalid_ohlc", "provider": "dnse",
                "operation": "parse_ohlc",
            })
            return
        await self.queue.put({**values, "timeframe": "1m", "is_closed": False})

    async def _writer(self) -> None:
        while True:
            first = await self.queue.get()
            batch = [first]
            while len(batch) < 500:
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            await asyncio.to_thread(self.store.upsert_ohlcv_bars, batch, source="dnse")
            for _item in batch:
                self.queue.task_done()

    async def stop(self) -> None:
        for stream in self.streams:
            stream.stop()
        stream_tasks = [task for task in self.tasks if task.get_name().startswith("dnse-stream-")]
        if stream_tasks:
            await asyncio.gather(*stream_tasks, return_exceptions=True)
        if not self.queue.empty():
            await self.queue.join()
        for task in self.tasks:
            if not task.done():
                task.cancel()
