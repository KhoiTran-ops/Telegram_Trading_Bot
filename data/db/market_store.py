"""SQLite storage for immutable-source EOD and financial history."""

from datetime import date, datetime, UTC
import json
from pathlib import Path
import sqlite3
from typing import Iterable


class MarketStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS instruments (
                symbol TEXT NOT NULL, exchange TEXT NOT NULL, company_name TEXT,
                source TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, exchange)
            );
            CREATE TABLE IF NOT EXISTS eod_prices (
                exchange TEXT NOT NULL, symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
                adjusted_close_thousand_vnd REAL, close_thousand_vnd REAL,
                change_text TEXT, matched_volume INTEGER,
                matched_value_billion_vnd REAL, negotiated_volume INTEGER,
                negotiated_value_billion_vnd REAL, open_thousand_vnd REAL,
                high_thousand_vnd REAL, low_thousand_vnd REAL, source TEXT NOT NULL,
                retrieved_at TEXT NOT NULL, raw_json TEXT NOT NULL,
                PRIMARY KEY (exchange, symbol, trade_date)
            );
            CREATE TABLE IF NOT EXISTS foreign_trading (
                exchange TEXT NOT NULL, symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
                net_volume INTEGER, net_value_vnd REAL, change_text TEXT,
                buy_volume INTEGER, buy_value_vnd REAL, sell_volume INTEGER,
                sell_value_vnd REAL, remaining_room REAL, ownership_percent REAL,
                source TEXT NOT NULL, retrieved_at TEXT NOT NULL, raw_json TEXT NOT NULL,
                PRIMARY KEY (exchange, symbol, trade_date)
            );
            CREATE TABLE IF NOT EXISTS financial_facts (
                symbol TEXT NOT NULL, statement_type TEXT NOT NULL,
                fiscal_year INTEGER NOT NULL, fiscal_quarter INTEGER NOT NULL,
                row_order INTEGER NOT NULL,
                item_name TEXT NOT NULL, value_raw TEXT NOT NULL,
                value_numeric REAL, source TEXT NOT NULL, retrieved_at TEXT NOT NULL,
                PRIMARY KEY (symbol, statement_type, fiscal_year, fiscal_quarter, row_order)
            );
            CREATE TABLE IF NOT EXISTS financial_periods (
                symbol TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
                fiscal_quarter INTEGER NOT NULL,
                audit_status TEXT NOT NULL, is_audited INTEGER NOT NULL,
                report_code TEXT NOT NULL, source TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (symbol, fiscal_year, fiscal_quarter)
            );
            CREATE TABLE IF NOT EXISTS foreign_snapshots (
                symbol TEXT NOT NULL, board_id TEXT NOT NULL, ts INTEGER NOT NULL,
                buy_volume INTEGER NOT NULL, buy_value REAL NOT NULL,
                sell_volume INTEGER NOT NULL, sell_value REAL NOT NULL,
                order_limit_quantity INTEGER, buy_possible_quantity INTEGER,
                source TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, board_id, ts)
            );
            CREATE TABLE IF NOT EXISTS ohlcv_bars (
                symbol TEXT NOT NULL, timeframe TEXT NOT NULL, ts INTEGER NOT NULL,
                open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
                close REAL NOT NULL, volume INTEGER NOT NULL, is_closed INTEGER NOT NULL,
                source TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, timeframe, ts)
            );
            CREATE TABLE IF NOT EXISTS sync_checkpoints (
                job_key TEXT PRIMARY KEY, cursor TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS data_anomalies (
                id INTEGER PRIMARY KEY, dataset TEXT NOT NULL, record_key TEXT,
                reason TEXT NOT NULL, raw_json TEXT NOT NULL, detected_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_eod_symbol_date
                ON eod_prices(symbol, trade_date);
            CREATE INDEX IF NOT EXISTS idx_foreign_symbol_date
                ON foreign_trading(symbol, trade_date);
            CREATE INDEX IF NOT EXISTS idx_financial_symbol_year
                ON financial_facts(symbol, fiscal_year);
            CREATE INDEX IF NOT EXISTS idx_ohlcv_timeframe_ts
                ON ohlcv_bars(timeframe, ts);
            CREATE INDEX IF NOT EXISTS idx_foreign_snapshots_symbol_ts
                ON foreign_snapshots(symbol, ts);
            """)
            self._migrate_eod_column_units(db)
            self._migrate_annual_financial_tables(db)
            db.execute("""
                CREATE VIEW IF NOT EXISTS backtest_eod_prices AS
                SELECT * FROM eod_prices
                WHERE close_thousand_vnd IS NOT NULL
                  AND open_thousand_vnd IS NOT NULL
                  AND high_thousand_vnd IS NOT NULL
                  AND low_thousand_vnd IS NOT NULL
                  AND close_thousand_vnd >= 0 AND open_thousand_vnd >= 0
                  AND low_thousand_vnd >= 0 AND high_thousand_vnd >= 0
                  AND low_thousand_vnd <= high_thousand_vnd
                  AND open_thousand_vnd BETWEEN low_thousand_vnd AND high_thousand_vnd
                  AND close_thousand_vnd BETWEEN low_thousand_vnd AND high_thousand_vnd
            """)

    @staticmethod
    def _migrate_eod_column_units(db: sqlite3.Connection) -> None:
        columns = {row[1] for row in db.execute("PRAGMA table_info(eod_prices)")}
        renames = {
            "adjusted_close": "adjusted_close_thousand_vnd",
            "close": "close_thousand_vnd",
            "matched_value_billion": "matched_value_billion_vnd",
            "negotiated_value_billion": "negotiated_value_billion_vnd",
            "open": "open_thousand_vnd",
            "high": "high_thousand_vnd",
            "low": "low_thousand_vnd",
        }
        for old, new in renames.items():
            if old in columns and new not in columns:
                db.execute(f'ALTER TABLE eod_prices RENAME COLUMN "{old}" TO "{new}"')

    @staticmethod
    def _migrate_annual_financial_tables(db: sqlite3.Connection) -> None:
        columns = {row[1] for row in db.execute("PRAGMA table_info(financial_facts)")}
        if columns and "fiscal_quarter" not in columns:
            db.executescript("""
                DROP TABLE financial_facts;
                DROP TABLE financial_periods;
                CREATE TABLE financial_facts (
                    symbol TEXT NOT NULL, statement_type TEXT NOT NULL,
                    fiscal_year INTEGER NOT NULL, fiscal_quarter INTEGER NOT NULL,
                    row_order INTEGER NOT NULL, item_name TEXT NOT NULL,
                    value_raw TEXT NOT NULL, value_numeric REAL, source TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, statement_type, fiscal_year,
                                 fiscal_quarter, row_order)
                );
                CREATE TABLE financial_periods (
                    symbol TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
                    fiscal_quarter INTEGER NOT NULL, audit_status TEXT NOT NULL,
                    is_audited INTEGER NOT NULL, report_code TEXT NOT NULL,
                    source TEXT NOT NULL, retrieved_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, fiscal_year, fiscal_quarter)
                );
                CREATE INDEX idx_financial_symbol_year
                    ON financial_facts(symbol, fiscal_year, fiscal_quarter);
            """)

    def upsert_instruments(self, instruments: Iterable[object], *, source: str) -> int:
        now = datetime.now(UTC).isoformat()
        count = 0
        with self._connect() as db:
            for item in instruments:
                db.execute(
                    "DELETE FROM instruments WHERE symbol=? AND exchange<>?",
                    (item.symbol, item.exchange),
                )
                db.execute("""
                INSERT INTO instruments(symbol,exchange,company_name,source,updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(symbol,exchange) DO UPDATE SET
                  company_name=excluded.company_name, source=excluded.source,
                  updated_at=excluded.updated_at
                """, (item.symbol, item.exchange, item.company_name, source, now))
                count += 1
        return count

    def replace_instruments(self, instruments: Iterable[object], *, source: str) -> int:
        """Atomically replace the authoritative trading universe."""
        rows = list(instruments)
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("DELETE FROM instruments")
            db.executemany("""
                INSERT INTO instruments(symbol,exchange,company_name,source,updated_at)
                VALUES (?,?,?,?,?)
            """, ((item.symbol, item.exchange, item.company_name, source, now)
                  for item in rows))
        return len(rows)

    def reconcile_exchange_scopes(self) -> int:
        """Remove rows assigned to a non-current exchange for catalogued symbols."""
        with self._connect() as db:
            before = db.total_changes
            for table in ("eod_prices", "foreign_trading"):
                db.execute(f"""
                    UPDATE OR IGNORE {table}
                    SET exchange=(
                        SELECT instruments.exchange FROM instruments
                        WHERE instruments.symbol={table}.symbol
                    )
                    WHERE EXISTS (
                        SELECT 1 FROM instruments
                        WHERE instruments.symbol={table}.symbol
                          AND instruments.exchange<>{table}.exchange
                    )
                """)
                db.execute(f"""
                    DELETE FROM {table}
                    WHERE EXISTS (
                        SELECT 1 FROM instruments
                        WHERE instruments.symbol={table}.symbol
                          AND instruments.exchange<>{table}.exchange
                    )
                """)
            return db.total_changes - before

    def list_instruments(self) -> list[tuple[str, str]]:
        with self._connect() as db:
            return db.execute(
                "SELECT symbol, exchange FROM instruments ORDER BY exchange, symbol"
            ).fetchall()

    def upsert_ohlcv_bars(self, bars: Iterable[dict[str, object]], *, source: str) -> int:
        now = datetime.now(UTC).isoformat()
        rows = [(
            str(bar["symbol"]).upper(), str(bar["timeframe"]), int(bar["timestamp"]),
            float(bar["open"]), float(bar["high"]), float(bar["low"]),
            float(bar["close"]), int(bar["volume"]), int(bool(bar["is_closed"])),
            source, now,
        ) for bar in bars]
        with self._connect() as db:
            db.executemany(
                "UPDATE ohlcv_bars SET is_closed=1 "
                "WHERE symbol=? AND timeframe=? AND ts<?",
                ((row[0], row[1], row[2]) for row in rows),
            )
            db.executemany("""
                INSERT INTO ohlcv_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,timeframe,ts) DO UPDATE SET
                  open=excluded.open, high=excluded.high, low=excluded.low,
                  close=excluded.close, volume=excluded.volume,
                  is_closed=MAX(ohlcv_bars.is_closed, excluded.is_closed),
                  source=excluded.source, updated_at=excluded.updated_at
            """, rows)
        return len(rows)

    def latest_bar_timestamp(self, symbol: str, timeframe: str) -> int | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT MAX(ts) FROM ohlcv_bars WHERE symbol=? AND timeframe=?",
                (symbol.upper(), timeframe),
            ).fetchone()
        return row[0]

    def mark_bars_closed_before(self, symbol: str, timeframe: str, timestamp: int) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE ohlcv_bars SET is_closed=1 WHERE symbol=? AND timeframe=? AND ts<?",
                (symbol.upper(), timeframe, timestamp),
            )

    def latest_market_price(self, symbol: str) -> tuple[float, int] | None:
        with self._connect() as db:
            row = db.execute("""
                SELECT close,ts FROM ohlcv_bars
                WHERE symbol=? AND timeframe='1m' ORDER BY ts DESC LIMIT 1
            """, (symbol.upper(),)).fetchone()
        return (float(row[0]), int(row[1])) if row else None

    def upsert_foreign_snapshots(self, rows: Iterable[dict[str, object]],
                                 *, source: str) -> int:
        now = datetime.now(UTC).isoformat()
        values = [(
            str(row["symbol"]).upper(), str(row["board_id"]), int(row["timestamp"]),
            int(row["buy_volume"]), float(row["buy_value"]),
            int(row["sell_volume"]), float(row["sell_value"]),
            int(row["order_limit_quantity"]) if row["order_limit_quantity"] is not None else None,
            int(row["buy_possible_quantity"]) if row["buy_possible_quantity"] is not None else None,
            source, now,
        ) for row in rows]
        with self._connect() as db:
            db.executemany("""
                INSERT INTO foreign_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,board_id,ts) DO UPDATE SET
                  buy_volume=excluded.buy_volume,buy_value=excluded.buy_value,
                  sell_volume=excluded.sell_volume,sell_value=excluded.sell_value,
                  order_limit_quantity=excluded.order_limit_quantity,
                  buy_possible_quantity=excluded.buy_possible_quantity,
                  source=excluded.source,updated_at=excluded.updated_at
            """, values)
        return len(values)

    def foreign_snapshot_bounds(self, symbol: str) -> tuple[int | None, int | None]:
        with self._connect() as db:
            row = db.execute(
                "SELECT MIN(ts),MAX(ts) FROM foreign_snapshots WHERE symbol=?",
                (symbol.upper(),),
            ).fetchone()
        return row[0], row[1]

    @staticmethod
    def normalize_date(value: date) -> str:
        return value.isoformat()

    @staticmethod
    def _parse_cafef_date(value: object) -> str:
        return datetime.strptime(str(value), "%d/%m/%Y").date().isoformat()

    def upsert_eod_rows(self, exchange: str, rows: Iterable[dict[str, object]],
                        *, source: str) -> tuple[int, int]:
        now = datetime.now(UTC).isoformat()
        inserted = rejected = 0
        with self._connect() as db:
            for row in rows:
                try:
                    symbol = str(row["Symbol"]).strip().upper()
                    trade_date = self._parse_cafef_date(row["Ngay"])
                    if not symbol:
                        raise ValueError("blank symbol")
                    db.execute("""
                    INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(exchange,symbol,trade_date) DO UPDATE SET
                      adjusted_close_thousand_vnd=excluded.adjusted_close_thousand_vnd,
                      close_thousand_vnd=excluded.close_thousand_vnd,
                      change_text=excluded.change_text,
                      matched_volume=excluded.matched_volume,
                      matched_value_billion_vnd=excluded.matched_value_billion_vnd,
                      negotiated_volume=excluded.negotiated_volume,
                      negotiated_value_billion_vnd=excluded.negotiated_value_billion_vnd,
                      open_thousand_vnd=excluded.open_thousand_vnd,
                      high_thousand_vnd=excluded.high_thousand_vnd,
                      low_thousand_vnd=excluded.low_thousand_vnd,
                      source=excluded.source, retrieved_at=excluded.retrieved_at,
                      raw_json=excluded.raw_json
                    """, (exchange, symbol, trade_date, row.get("GiaDieuChinh"),
                          row.get("GiaDongCua"), row.get("ThayDoi"),
                          row.get("KhoiLuongKhopLenh"), row.get("GiaTriKhopLenh"),
                          row.get("KLThoaThuan"), row.get("GtThoaThuan"),
                          row.get("GiaMoCua"), row.get("GiaCaoNhat"),
                          row.get("GiaThapNhat"), source, now,
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
                    quality_issue = self._eod_quality_issue(row)
                    if quality_issue:
                        self._record_anomaly(
                            db, "eod_prices", f"{exchange}:{symbol}:{trade_date}",
                            quality_issue, row, now,
                        )
                    inserted += 1
                except (KeyError, TypeError, ValueError) as error:
                    self._record_anomaly(db, "eod_prices", str(row.get("Symbol", "")),
                                         str(error), row, now)
                    rejected += 1
        return inserted, rejected

    @staticmethod
    def _eod_quality_issue(row: dict[str, object]) -> str | None:
        numeric_names = (
            "GiaDieuChinh", "GiaDongCua", "KhoiLuongKhopLenh",
            "GiaTriKhopLenh", "KLThoaThuan", "GtThoaThuan",
            "GiaMoCua", "GiaCaoNhat", "GiaThapNhat",
        )
        for name in numeric_names:
            value = row.get(name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                return f"{name} is not numeric"
        for name in ("KhoiLuongKhopLenh", "GiaTriKhopLenh", "KLThoaThuan", "GtThoaThuan"):
            value = row.get(name)
            if isinstance(value, (int, float)) and value < 0:
                return f"{name} is negative"
        low, high = row.get("GiaThapNhat"), row.get("GiaCaoNhat")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            if low > high:
                return "low price exceeds high price"
            for name in ("GiaMoCua", "GiaDongCua"):
                value = row.get(name)
                if isinstance(value, (int, float)) and not low <= value <= high:
                    return f"{name} is outside the low/high range"
        return None

    def upsert_foreign_rows(self, exchange: str, rows: Iterable[dict[str, object]],
                            *, source: str) -> tuple[int, int]:
        now = datetime.now(UTC).isoformat()
        inserted = rejected = 0
        with self._connect() as db:
            for row in rows:
                try:
                    symbol = str(row["Symbol"]).strip().upper()
                    trade_date = self._parse_cafef_date(row["Ngay"])
                    if not symbol:
                        raise ValueError("blank symbol")
                    db.execute("""
                    INSERT INTO foreign_trading VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(exchange,symbol,trade_date) DO UPDATE SET
                      net_volume=excluded.net_volume, net_value_vnd=excluded.net_value_vnd,
                      change_text=excluded.change_text, buy_volume=excluded.buy_volume,
                      buy_value_vnd=excluded.buy_value_vnd, sell_volume=excluded.sell_volume,
                      sell_value_vnd=excluded.sell_value_vnd,
                      remaining_room=excluded.remaining_room,
                      ownership_percent=excluded.ownership_percent,
                      source=excluded.source, retrieved_at=excluded.retrieved_at,
                      raw_json=excluded.raw_json
                    """, (exchange, symbol, trade_date, row.get("KLGDRong"),
                          row.get("GTDGRong"), row.get("ThayDoi"), row.get("KLMua"),
                          row.get("GtMua"), row.get("KLBan"), row.get("GtBan"),
                          row.get("RoomConLai"), row.get("DangSoHuu"), source, now,
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
                    inserted += 1
                except (KeyError, TypeError, ValueError) as error:
                    self._record_anomaly(db, "foreign_trading",
                                         str(row.get("Symbol", "")), str(error), row, now)
                    rejected += 1
        return inserted, rejected

    def replace_financial_facts(self, symbol: str, statement_type: str,
                                facts: list[dict[str, object]], *, source: str) -> int:
        now = datetime.now(UTC).isoformat()
        count = 0
        with self._connect() as db:
            periods = sorted({period for fact in facts
                              for period in fact.get("values", {}).keys()})
            for year, quarter in periods:
                db.execute(
                    "DELETE FROM financial_facts WHERE symbol=? AND statement_type=? "
                    "AND fiscal_year=? AND fiscal_quarter=?",
                    (symbol, statement_type, year, quarter),
                )
            for fact in facts:
                values = fact["values"]
                if not isinstance(values, dict):
                    continue
                for (year, quarter), pair in values.items():
                    raw, numeric = pair
                    db.execute("""
                    INSERT INTO financial_facts VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol,statement_type,fiscal_year,fiscal_quarter,row_order) DO UPDATE SET
                      item_name=excluded.item_name, value_raw=excluded.value_raw,
                      value_numeric=excluded.value_numeric, source=excluded.source,
                      retrieved_at=excluded.retrieved_at
                    """, (symbol, statement_type, year, quarter, fact["row_order"],
                          fact["item_name"], raw, numeric, source, now))
                    count += 1
        return count

    def upsert_financial_periods(self, periods: Iterable[dict[str, object]],
                                 *, source: str) -> int:
        now = datetime.now(UTC).isoformat()
        rows = [(
            str(period["symbol"]).upper(), int(period["fiscal_year"]),
            int(period["fiscal_quarter"]),
            str(period["audit_status"]), int(bool(period["is_audited"])),
            str(period["report_code"]), source, now,
        ) for period in periods]
        with self._connect() as db:
            db.executemany("""
                INSERT INTO financial_periods VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,fiscal_year,fiscal_quarter) DO UPDATE SET
                  audit_status=excluded.audit_status,
                  is_audited=excluded.is_audited,
                  report_code=excluded.report_code,
                  source=excluded.source,retrieved_at=excluded.retrieved_at
            """, rows)
        return len(rows)

    def set_checkpoint(self, job_key: str, cursor: str) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO sync_checkpoints VALUES (?,?,?)
            ON CONFLICT(job_key) DO UPDATE SET cursor=excluded.cursor,
              updated_at=excluded.updated_at""",
                       (job_key, cursor, datetime.now(UTC).isoformat()))

    def get_checkpoint(self, job_key: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT cursor FROM sync_checkpoints WHERE job_key=?",
                             (job_key,)).fetchone()
        return row[0] if row else None

    def anomaly_count(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM data_anomalies").fetchone()[0]

    def statistics(self) -> dict[str, object]:
        with self._connect() as db:
            return {
                "eod_prices": db.execute("SELECT COUNT(*) FROM eod_prices").fetchone()[0],
                "eod_min_date": db.execute("SELECT MIN(trade_date) FROM eod_prices").fetchone()[0],
                "eod_max_date": db.execute("SELECT MAX(trade_date) FROM eod_prices").fetchone()[0],
                "foreign_trading": db.execute("SELECT COUNT(*) FROM foreign_trading").fetchone()[0],
                "financial_facts": db.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0],
                "instruments": db.execute("SELECT COUNT(*) FROM instruments").fetchone()[0],
                "anomalies": db.execute("SELECT COUNT(*) FROM data_anomalies").fetchone()[0],
                "completed_exports": db.execute(
                    "SELECT COUNT(*) FROM sync_checkpoints "
                    "WHERE job_key LIKE 'cafef:export:%' AND cursor='complete'"
                ).fetchone()[0],
            }

    @staticmethod
    def _record_anomaly(db: sqlite3.Connection, dataset: str, key: str,
                        reason: str, row: object, now: str) -> None:
        db.execute("INSERT INTO data_anomalies(dataset,record_key,reason,raw_json,detected_at) VALUES (?,?,?,?,?)",
                   (dataset, key, reason,
                    json.dumps(row, ensure_ascii=False, default=str), now))
