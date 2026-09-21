"""On-demand strategy evaluation over the latest daily and intraday data."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from signal_engine.engine import BacktestResult, TechnicalResult, evaluate_technical, run_backtest
from reporting.market_summary import MarketSummary, build_market_summary
from signal_engine.fundamentals import FundamentalResult, evaluate_fundamentals
from signal_engine.repository import StrategyRepository


VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")


@dataclass(frozen=True)
class SignalEvaluation:
    symbol: str
    company_name: str | None
    exchange: str | None
    generated_at: datetime
    phase: str
    action: str
    technical: TechnicalResult | None
    fundamentals: FundamentalResult | None
    foreign: dict[str, float | int | None]
    sector_policy: str
    missing: tuple[str, ...]


class StrategyService:
    def __init__(self, database: Path) -> None:
        self.repository = StrategyRepository(database)

    def evaluate(self, symbol: str, *, now: datetime | None = None) -> SignalEvaluation:
        normalized = symbol.strip().upper()
        current = (now or datetime.now(VIETNAM)).astimezone(VIETNAM)
        bars, has_intraday = self.repository.bars_with_intraday(normalized, current)
        if not bars:
            return SignalEvaluation(
                normalized, None, None, current, "NOT_AVAILABLE", "NOT_AVAILABLE",
                None, None, {"rows": 0}, "UNKNOWN", ("price_history",),
            )
        benchmark, _benchmark_intraday = self.repository.bars_with_intraday("VNINDEX", current)
        technical = evaluate_technical(bars, benchmark)
        instrument = self.repository.instrument(normalized)
        exchange, company_name, likely_financial = instrument or (None, None, False)
        fundamentals = evaluate_fundamentals(
            self.repository.financial_quarters(normalized),
            financial_sector=likely_financial,
        )
        foreign = self.repository.foreign_summary(normalized)
        missing = list(fundamentals.missing)
        if int(foreign.get("rows") or 0) == 0:
            missing.append("foreign_trading")
        if likely_financial:
            sector_policy = "LIKELY_FINANCIAL_TECHNICAL_ONLY"
            action = f"TECHNICAL_ONLY_{technical.action}"
            missing.append("dedicated_financial_sector_fundamentals")
        elif fundamentals.mandatory_pass is False:
            sector_policy = "ASSUMED_NON_FINANCIAL"
            action = "REJECT_FUNDAMENTALS"
        elif fundamentals.mandatory_pass is None:
            sector_policy = "ASSUMED_NON_FINANCIAL"
            action = f"TECHNICAL_ONLY_{technical.action}"
        else:
            sector_policy = "ASSUMED_NON_FINANCIAL"
            action = technical.action
        intraday_session = (
            current.weekday() < 5
            and ((current.hour == 9) or (current.hour == 10)
                 or (current.hour == 11 and current.minute <= 30)
                 or (current.hour == 13) or (current.hour == 14)
                 or (current.hour == 15 and current.minute <= 5))
        )
        phase = "PROVISIONAL_INTRADAY" if has_intraday and intraday_session else "CONFIRMED_EOD"
        return SignalEvaluation(
            normalized, company_name, exchange, current, phase, action, technical,
            fundamentals, foreign, sector_policy, tuple(sorted(set(missing))),
        )

    def scan(self, *, limit: int = 10) -> list[SignalEvaluation]:
        symbols = self.repository.best_covered_symbols(limit)
        return [self.evaluate(item.symbol) for item in symbols]

    def chart_bars(self, symbol: str):
        return self.repository.bars(symbol.upper())

    def backtest(self, symbol: str) -> BacktestResult:
        return run_backtest(symbol.upper(), self.repository.bars(symbol.upper()),
                            self.repository.bars("VNINDEX"))

    def market_summary(self, *, now: datetime | None = None,
                       session: str = "FULL_DAY") -> tuple[MarketSummary, list]:
        current = (now or datetime.now(VIETNAM)).astimezone(VIETNAM)
        start = int(current.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        end = int(current.timestamp()) + 1
        index_bars = self.repository.intraday_bars("VNINDEX", start, end)
        movers = self.repository.intraday_movers(start, end)
        daily_index = self.repository.bars("VNINDEX")
        previous = next((bar.close for bar in reversed(daily_index) if bar.ts < start), None)
        return build_market_summary(
            index_bars, movers, session=session, reference_close=previous
        ), index_bars
