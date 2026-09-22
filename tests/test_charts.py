from pathlib import Path

import pytest

from reporting.charts import ChartOptions, parse_chart_args, render_candlestick
from signal_engine.engine import Bar


def sample_bars(count: int = 90) -> list[Bar]:
    return [
        Bar(1_700_000_000 + day * 86_400, 100 + day, 103 + day,
            98 + day, 101 + day, 100_000 + day * 1_000)
        for day in range(count)
    ]


def test_parse_chart_args_accepts_supported_period_and_indicators() -> None:
    options = parse_chart_args(["hpg", "6m", "ema,rsi,macd"])
    assert options == ChartOptions("HPG", "6m", ("ema", "rsi", "macd"))


def test_chart_defaults_to_three_months_with_all_indicators() -> None:
    assert parse_chart_args(["VCB"]) == ChartOptions(
        "VCB", "3m", ("ema", "rsi", "macd", "obv")
    )


def test_chart_accepts_custom_start_and_end_dates() -> None:
    options = parse_chart_args(["VNINDEX", "2026-01-01", "2026-06-30", "ema,macd"])
    assert options.start_date == "2026-01-01"
    assert options.end_date == "2026-06-30"
    assert options.indicators == ("ema", "macd")


def test_parse_chart_args_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="Khoảng thời gian"):
        parse_chart_args(["HPG", "2y"])
    with pytest.raises(ValueError, match="Chỉ báo"):
        parse_chart_args(["HPG", "3m", "bollinger"])


def test_render_candlestick_creates_a_centered_auto_scaled_png(tmp_path: Path) -> None:
    output = render_candlestick(
        sample_bars(), ChartOptions("HPG", "3m", ("ema", "rsi")), tmp_path
    )
    assert output.suffix == ".png"
    assert output.stat().st_size > 10_000
