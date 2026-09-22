"""SQLite adapter for strategy inputs and data-coverage ranking."""

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from signal_engine.engine import Bar
from signal_engine.fundamentals import FinancialQuarter


@dataclass(frozen=True)
class Coverage:
    symbol: str
    exchange: str
    company_name: str
    is_likely_financial: bool
    daily_bars: int
    financial_periods: int
    complete_financial_fields: int
    foreign_rows: int


def _normalized(value: str) -> str:
    if any(marker in value for marker in ("Ã", "Ä", "Â")):
        try:
            value = value.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def is_likely_financial_company(company_name: str) -> bool:
    normalized = _normalized(company_name)
    return any(term in normalized for term in (
        "ngan hang", "chung khoan", "bao hiem", "cong ty tai chinh",
    ))


class StrategyRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def bars(self, symbol: str, timeframe: str = "1D") -> list[Bar]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT ts,open,high,low,close,volume FROM ohlcv_bars
                WHERE symbol=? AND timeframe=? ORDER BY ts
            """, (symbol.upper(), timeframe)).fetchall()
        return [Bar(int(ts), float(opened), float(high), float(low), float(close),
                    int(volume)) for ts, opened, high, low, close, volume in rows]

    def intraday_bars(self, symbol: str, day_start: int, day_end: int) -> list[Bar]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT ts,open,high,low,close,volume FROM ohlcv_bars
                WHERE symbol=? AND timeframe='1m' AND ts>=? AND ts<? ORDER BY ts
            """, (symbol.upper(), day_start, day_end)).fetchall()
        return [Bar(int(ts), float(o), float(h), float(l), float(c), int(v))
                for ts, o, h, l, c, v in rows]

    def intraday_movers(self, day_start: int, day_end: int) -> list[tuple[str, float, float]]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT b.symbol,b.open,b.close,b.volume
                FROM ohlcv_bars b JOIN instruments i ON i.symbol=b.symbol
                WHERE b.timeframe='1m' AND b.ts>=? AND b.ts<?
                  AND i.exchange='HOSE'
                ORDER BY b.symbol,b.ts
            """, (day_start, day_end)).fetchall()
            reference_ts = db.execute(
                "SELECT MAX(ts) FROM ohlcv_bars WHERE timeframe='1D' AND ts<?",
                (day_start,),
            ).fetchone()[0]
            references = dict(db.execute("""
                SELECT symbol,close FROM ohlcv_bars
                WHERE timeframe='1D' AND ts=?
            """, (reference_ts,)).fetchall()) if reference_ts is not None else {}
        grouped: dict[str, list[float]] = {}
        for symbol, opened, close, volume in rows:
            item = grouped.setdefault(str(symbol), [float(opened), float(close), 0.0])
            item[1] = float(close)
            item[2] += float(close) * 1_000 * int(volume)
        return [
            (symbol, (close / float(references.get(symbol, opened)) - 1) * 100
             if references.get(symbol, opened) else 0, value)
            for symbol, (opened, close, value) in grouped.items()
        ]

    def bars_with_intraday(self, symbol: str, now: datetime) -> tuple[list[Bar], bool]:
        daily = self.bars(symbol)
        local_now = now.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
        day_start = int(local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        day_end = day_start + 86_400
        with self._connect() as db:
            row = db.execute("""
                SELECT MIN(ts),MAX(high),MIN(low),SUM(volume) FROM ohlcv_bars
                WHERE symbol=? AND timeframe='1m' AND ts>=? AND ts<?
            """, (symbol.upper(), day_start, day_end)).fetchone()
            opened = db.execute("""
                SELECT open FROM ohlcv_bars WHERE symbol=? AND timeframe='1m'
                AND ts>=? AND ts<? ORDER BY ts LIMIT 1
            """, (symbol.upper(), day_start, day_end)).fetchone()
            closed = db.execute("""
                SELECT close FROM ohlcv_bars WHERE symbol=? AND timeframe='1m'
                AND ts>=? AND ts<? ORDER BY ts DESC LIMIT 1
            """, (symbol.upper(), day_start, day_end)).fetchone()
        if not row or row[0] is None or not opened or not closed:
            return daily, False
        intraday = Bar(day_start, float(opened[0]), float(row[1]), float(row[2]),
                       float(closed[0]), int(row[3]))
        if daily and datetime.fromtimestamp(daily[-1].ts, ZoneInfo("Asia/Ho_Chi_Minh")).date() == local_now.date():
            daily[-1] = intraday
        else:
            daily.append(intraday)
        return daily, True

    def instrument(self, symbol: str) -> tuple[str, str, bool] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT exchange,COALESCE(company_name,'') FROM instruments WHERE symbol=?",
                (symbol.upper(),),
            ).fetchone()
        if not row:
            return None
        name = str(row[1])
        display_name = name
        if any(marker in display_name for marker in ("Ã", "Ä", "Â")):
            try:
                display_name = display_name.encode("latin1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return str(row[0]), display_name, is_likely_financial_company(name)

    def financial_quarters(self, symbol: str) -> list[FinancialQuarter]:
        with self._connect() as db:
            periods = db.execute("""
                SELECT fiscal_year,fiscal_quarter FROM financial_periods
                WHERE symbol=? ORDER BY fiscal_year DESC,fiscal_quarter DESC LIMIT 8
            """, (symbol.upper(),)).fetchall()
            facts = db.execute("""
                SELECT statement_type,fiscal_year,fiscal_quarter,item_name,value_numeric
                FROM financial_facts WHERE symbol=?
            """, (symbol.upper(),)).fetchall()
        by_period: dict[tuple[int, int], list[tuple[str, str, float | None]]] = {}
        for statement, year, quarter, name, value in facts:
            by_period.setdefault((int(year), int(quarter)), []).append(
                (str(statement), _normalized(str(name)), float(value) if value is not None else None)
            )

        def pick(items: list[tuple[str, str, float | None]], statement: str,
                 candidates: tuple[str, ...]) -> float | None:
            matching = [(name, value) for kind, name, value in items if kind == statement]
            for candidate in candidates:
                exact = [value for name, value in matching if name == candidate]
                if exact:
                    return exact[0]
                contains = [(name, value) for name, value in matching if candidate in name]
                if contains:
                    return min(contains, key=lambda item: len(item[0]))[1]
            return None

        result = []
        for year, quarter in reversed(periods):
            items = by_period.get((int(year), int(quarter)), [])
            cfo = pick(items, "CashFlow", (
                "luu chuyen tien thuan tu hoat dong kinh doanh",
            ))
            if cfo is None:
                cfo = pick(items, "CashFlowDirect", (
                    "luu chuyen tien thuan tu hoat dong kinh doanh",
                ))
            result.append(FinancialQuarter(
                int(year), int(quarter),
                revenue=pick(items, "IncSta", (
                    "3 doanh thu thuan ve ban hang va cung cap dich vu 10 01 02",
                    "doanh thu thuan ve ban hang va cung cap dich vu",
                )),
                profit=pick(items, "IncSta", (
                    "19 loi nhuan sau thue cong ty me",
                    "loi nhuan sau thue cua co dong cong ty me",
                    "18 loi nhuan sau thue thu nhap doanh nghiep 60 50 51 52",
                    "loi nhuan sau thue thu nhap doanh nghiep",
                )),
                equity=pick(items, "BSheet", (
                    "d von chu so huu", "i von chu so huu", "von chu so huu",
                )),
                debt=pick(items, "BSheet", ("c no phai tra", "no phai tra")),
                current_assets=pick(items, "BSheet", (
                    "a tai san ngan han", "tai san ngan han",
                )),
                current_liabilities=pick(items, "BSheet", (
                    "i no ngan han", "no ngan han",
                )),
                cfo=cfo,
            ))
        return result

    def foreign_summary(self, symbol: str) -> dict[str, float | int | None]:
        with self._connect() as db:
            row = db.execute("""
                SELECT COUNT(*),SUM(buy_value-sell_value),MAX(order_limit_quantity),
                       MAX(buy_possible_quantity)
                FROM foreign_snapshots WHERE symbol=?
            """, (symbol.upper(),)).fetchone()
        return {
            "rows": int(row[0]), "net_value_vnd": float(row[1]) if row[1] is not None else None,
            "order_limit_quantity": row[2], "buy_possible_quantity": row[3],
        }

    def best_covered_symbols(self, limit: int = 10,
                             exchange: str | None = None) -> list[Coverage]:
        with self._connect() as db:
            instruments = db.execute("""
                SELECT i.symbol,i.exchange,COALESCE(i.company_name,'')
                FROM instruments i
                WHERE (? IS NULL OR i.exchange=? COLLATE NOCASE)
                  AND (? IS NOT NULL OR (SELECT COUNT(*) FROM financial_periods p
                       WHERE p.symbol=i.symbol)>=8)
                  AND EXISTS(SELECT 1 FROM ohlcv_bars b
                             WHERE b.symbol=i.symbol AND b.timeframe='1D')
                ORDER BY (SELECT COUNT(*) FROM financial_periods p
                          WHERE p.symbol=i.symbol) DESC,
                         (SELECT COUNT(*) FROM ohlcv_bars b
                          WHERE b.symbol=i.symbol AND b.timeframe='1D') DESC
                LIMIT ?
            """, (exchange, exchange, exchange, max(50, limit * 10))).fetchall()
        coverage = []
        for symbol, listed_exchange, company_name in instruments:
            quarters = self.financial_quarters(symbol)
            complete = sum(
                value is not None for quarter in quarters for value in (
                    quarter.revenue, quarter.profit, quarter.equity, quarter.debt,
                    quarter.current_assets, quarter.current_liabilities, quarter.cfo,
                )
            )
            foreign = self.foreign_summary(symbol)
            with self._connect() as db:
                daily = db.execute(
                    "SELECT COUNT(*) FROM ohlcv_bars WHERE symbol=? AND timeframe='1D'",
                    (symbol,),
                ).fetchone()[0]
            display_name = company_name
            if any(marker in display_name for marker in ("Ã", "Ä", "Â")):
                try:
                    display_name = display_name.encode("latin1").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            coverage.append(Coverage(
                symbol, listed_exchange, display_name,
                is_likely_financial_company(company_name), int(daily),
                len(quarters), complete, int(foreign["rows"]),
            ))
        coverage.sort(key=lambda item: (
            item.complete_financial_fields, item.foreign_rows > 0,
            item.daily_bars, item.foreign_rows,
        ), reverse=True)
        return coverage[:limit]

    def scan_symbols(self, limit: int | None = 200) -> list[str]:
        """Rank the scan universe by exchange and recent traded value.

        HOSE is intentionally considered before HNX and UPCOM. Within an
        exchange, liquid names rank first, which naturally puts the VN100
        large/mid-cap universe near the front without treating price movement
        alone as importance.
        """
        with self._connect() as db:
            rows = db.execute("""
                SELECT i.symbol
                FROM instruments i
                WHERE EXISTS (
                    SELECT 1 FROM ohlcv_bars enough
                    WHERE enough.symbol=i.symbol AND enough.timeframe='1D'
                    ORDER BY enough.ts DESC LIMIT 1 OFFSET 59
                )
                ORDER BY CASE UPPER(i.exchange)
                    WHEN 'HOSE' THEN 0 WHEN 'HNX' THEN 1 ELSE 2 END,
                    COALESCE((
                        SELECT AVG(recent.close * 1000.0 * recent.volume)
                        FROM ohlcv_bars recent
                        WHERE recent.symbol=i.symbol AND recent.timeframe='1D'
                          AND recent.ts >= COALESCE((
                              SELECT boundary.ts FROM ohlcv_bars boundary
                              WHERE boundary.symbol=i.symbol
                                AND boundary.timeframe='1D'
                              ORDER BY boundary.ts DESC LIMIT 1 OFFSET 19
                          ), 0)
                    ), 0) DESC,
                    i.symbol
                LIMIT ?
            """, (-1 if limit is None else max(1, limit),)).fetchall()
        return [str(row[0]) for row in rows]
