from signal_engine.engine import (
    Bar, clean_adjusted_segments, evaluate_technical, run_backtest,
)
from signal_engine.repository import is_likely_financial_company


def rising_bars(count: int = 100) -> list[Bar]:
    bars = []
    for index in range(count):
        close = 20 + index * 0.1
        bars.append(Bar(index * 86_400, close - 0.1, close + 0.2,
                        close - 0.2, close, 200_000))
    return bars


def test_adjustment_day_is_excluded_and_indicator_history_restarts() -> None:
    bars = rising_bars(70)
    adjusted = Bar(70 * 86_400, 15, 15.2, 14.8, 15, 200_000)
    after = Bar(71 * 86_400, 15.1, 15.3, 15, 15.2, 200_000)

    cleaned, excluded = clean_adjusted_segments([*bars, adjusted, after])

    assert excluded == (adjusted.ts,)
    assert cleaned == [after]


def test_missing_history_is_reported_instead_of_fabricated() -> None:
    result = evaluate_technical(rising_bars(30), rising_bars(30))

    assert result.action == "NOT_AVAILABLE"
    assert "minimum_60_sessions" in result.missing


def test_strategy_can_produce_a_backtest_without_portfolio_inputs() -> None:
    bars = rising_bars(180)
    index = [Bar(bar.ts, bar.open, bar.high, bar.low, bar.close * 0.98,
                 bar.volume) for bar in bars]

    result = run_backtest("TEST", bars, index)

    assert result.symbol == "TEST"
    assert result.sessions == 180
    assert result.mode == "TECHNICAL_ONLY"
    assert result.total_return is not None


def test_backtest_uses_only_two_years_ending_at_as_of_date() -> None:
    day = 86_400
    bars = [Bar(day * index, index + 1, index + 1.2, index + .8,
                index + 1, 1_000_000) for index in range(1, 1_001)]

    result = run_backtest("HPG", bars, bars, as_of_ts=day * 1_000)

    assert result.sessions == 731
    assert result.buy_hold_return is not None
    assert result.buy_hold_return < 3
    assert "two_year_window" in result.notes


def test_financial_company_detection_is_conservative_and_keeps_technical_signal() -> None:
    assert is_likely_financial_company("Ngân hàng TMCP Á Châu") is True
    assert is_likely_financial_company("NgÃ¢n hÃ ng TMCP Ã ChÃ¢u") is True
    assert is_likely_financial_company("Công ty Cổ phần Chứng khoán SSI") is True
    assert is_likely_financial_company("Tập đoàn Hòa Phát") is False
