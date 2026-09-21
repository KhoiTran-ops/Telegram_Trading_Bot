"""Quarterly fundamental rules with explicit missing-data semantics."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FinancialQuarter:
    year: int
    quarter: int
    revenue: float | None
    profit: float | None
    equity: float | None
    debt: float | None
    current_assets: float | None
    current_liabilities: float | None
    cfo: float | None


@dataclass(frozen=True)
class FundamentalResult:
    mandatory_pass: bool | None
    grade: str | None
    metrics: dict[str, float | None]
    warnings: tuple[str, ...]
    failures: tuple[str, ...]
    missing: tuple[str, ...]


def _sum(values: list[float | None]) -> float | None:
    return sum(value for value in values if value is not None) if all(
        value is not None for value in values
    ) else None


def evaluate_fundamentals(quarters: list[FinancialQuarter], *,
                          financial_sector: bool = False) -> FundamentalResult:
    ordered = sorted(quarters, key=lambda item: (item.year, item.quarter))[-8:]
    missing: set[str] = set()
    warnings: list[str] = []
    failures: list[str] = []
    if len(ordered) < 8:
        missing.add("eight_quarters")
    latest_four = ordered[-4:]
    previous_four = ordered[-8:-4]

    profit_ttm = _sum([item.profit for item in latest_four]) if len(latest_four) == 4 else None
    previous_profit = _sum([item.profit for item in previous_four]) if len(previous_four) == 4 else None
    revenue_ttm = _sum([item.revenue for item in latest_four]) if len(latest_four) == 4 else None
    previous_revenue = _sum([item.revenue for item in previous_four]) if len(previous_four) == 4 else None
    cfo_ttm = _sum([item.cfo for item in latest_four]) if len(latest_four) == 4 else None
    equity_values = [item.equity for item in latest_four]
    average_equity = (
        sum(value for value in equity_values if value is not None) / 4
        if len(equity_values) == 4 and all(value is not None for value in equity_values)
        else None
    )
    roe = profit_ttm / average_equity if profit_ttm is not None and average_equity else None
    profit_growth = (
        (profit_ttm - previous_profit) / previous_profit
        if profit_ttm is not None and previous_profit is not None and previous_profit > 0
        else None
    )
    revenue_growth = (
        (revenue_ttm - previous_revenue) / previous_revenue
        if revenue_ttm is not None and previous_revenue not in (None, 0)
        else None
    )
    latest_yoy = None
    if len(ordered) == 8 and ordered[-1].profit is not None and ordered[-5].profit is not None:
        previous_quarter_profit = ordered[-5].profit
        latest_yoy = (
            (ordered[-1].profit - previous_quarter_profit) / abs(previous_quarter_profit)
            if previous_quarter_profit != 0
            else math.copysign(math.inf, ordered[-1].profit)
        )
    latest = ordered[-1] if ordered else None
    debt_to_equity = (
        latest.debt / latest.equity if latest and latest.debt is not None
        and latest.equity not in (None, 0) else None
    )
    current_ratio = (
        latest.current_assets / latest.current_liabilities
        if latest and latest.current_assets is not None
        and latest.current_liabilities not in (None, 0) else None
    )
    cfo_to_profit = cfo_ttm / profit_ttm if cfo_ttm is not None and profit_ttm else None

    required = {
        "profit": profit_ttm, "revenue": revenue_ttm, "equity": average_equity,
        "previous_profit": previous_profit, "latest_profit_yoy": latest_yoy,
        "previous_revenue": previous_revenue,
    }
    if not financial_sector:
        required["debt"] = debt_to_equity
    for name, value in required.items():
        if value is None:
            missing.add(name)
    if previous_profit is not None and previous_profit <= 0:
        failures.append("previous_profit_not_positive")
    if previous_revenue == 0:
        failures.append("previous_revenue_zero")

    checks = (
        ("roe_below_15pct", roe, lambda value: value >= 0.15),
        ("profit_ttm_not_positive", profit_ttm, lambda value: value > 0),
        ("profit_growth_below_15pct", profit_growth, lambda value: value >= 0.15),
        ("latest_profit_yoy_not_positive", latest_yoy, lambda value: value > 0),
        ("revenue_growth_negative", revenue_growth, lambda value: value >= 0),
    )
    for reason, value, predicate in checks:
        if value is not None and not predicate(value):
            failures.append(reason)
    if not financial_sector and debt_to_equity is not None and debt_to_equity > 2:
        failures.append("debt_to_equity_above_200pct")
    if not financial_sector and current_ratio is None:
        missing.add("current_ratio")
    elif not financial_sector and current_ratio < 1:
        warnings.append("current_ratio_below_1")
    if cfo_ttm is None:
        missing.add("cfo")
    elif cfo_ttm <= 0:
        warnings.append("cfo_ttm_not_positive")
    if cfo_to_profit is None:
        missing.add("cfo_to_profit")
    elif cfo_to_profit < 0.8:
        warnings.append("cfo_to_profit_below_0_8")
    mandatory_pass = None if any(
        key in missing for key in required
    ) else not failures
    grade = None if mandatory_pass is None or not mandatory_pass else (
        "A" if not warnings else "B"
    )
    return FundamentalResult(
        mandatory_pass, grade,
        {
            "roe": roe, "profit_ttm": profit_ttm,
            "profit_growth_yoy": profit_growth,
            "latest_profit_yoy": latest_yoy,
            "revenue_ttm": revenue_ttm, "revenue_growth_yoy": revenue_growth,
            "debt_to_equity": debt_to_equity, "current_ratio": current_ratio,
            "cfo_ttm": cfo_ttm, "cfo_to_profit": cfo_to_profit,
        },
        tuple(warnings), tuple(failures), tuple(sorted(missing)),
    )
