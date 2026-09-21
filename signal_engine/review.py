"""Run the documented strategy against the best-covered stored symbols."""

from dataclasses import asdict
from pathlib import Path

from signal_engine.engine import evaluate_technical, run_backtest
from signal_engine.fundamentals import evaluate_fundamentals
from signal_engine.repository import StrategyRepository


def run_review(database: Path, *, limit: int = 10,
               exchange: str | None = None) -> dict[str, object]:
    repository = StrategyRepository(database)
    benchmark = repository.bars("VNINDEX")
    results = []
    for coverage in repository.best_covered_symbols(limit, exchange):
        bars = repository.bars(coverage.symbol)
        technical = evaluate_technical(bars, benchmark)
        fundamentals = evaluate_fundamentals(
            repository.financial_quarters(coverage.symbol),
            financial_sector=coverage.is_likely_financial,
        )
        foreign = repository.foreign_summary(coverage.symbol)
        if coverage.is_likely_financial:
            action = f"TECHNICAL_ONLY_{technical.action}"
        elif fundamentals.mandatory_pass is False:
            action = "REJECT_FUNDAMENTALS"
        elif fundamentals.mandatory_pass is None:
            action = "NOT_AVAILABLE"
        else:
            action = technical.action
        results.append({
            "symbol": coverage.symbol,
            "coverage": asdict(coverage),
            "latest_action": action,
            "technical": asdict(technical),
            "fundamentals": asdict(fundamentals),
            "foreign": foreign,
            "sector_policy": {
                "classification": (
                    "LIKELY_FINANCIAL" if coverage.is_likely_financial
                    else "ASSUMED_NON_FINANCIAL"
                ),
                "basis": "conservative company-name heuristic",
                "fundamentals_can_authorize_buy": not coverage.is_likely_financial,
            },
            "backtest": asdict(run_backtest(coverage.symbol, bars, benchmark)),
        })
    return {
        "scope": f"{limit} best-covered symbols" + (
            f" on {exchange.upper()}" if exchange else " in the current DNSE universe"
        ),
        "signal_rule": "BUY=T0 pass + mandatory T1 pass + T2A 3/3 + T2B >=3/4 + not overextended",
        "backtest_mode": "TECHNICAL_ONLY",
        "global_missing": [
            "financial publication timestamps",
            "reliable sector classification and dedicated financial-company mapping",
            "complete historical foreign ownership percentage and room",
        ],
        "results": results,
    }
