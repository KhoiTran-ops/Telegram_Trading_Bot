"""Candlestick charts for Telegram, with automatic price-axis scaling."""

from dataclasses import dataclass
from datetime import date, datetime
import os
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", str(Path("var/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from signal_engine.engine import Bar


PERIOD_SESSIONS = {"3m": 66, "6m": 132, "1y": 264}
SUPPORTED_INDICATORS = ("ema", "rsi", "macd", "obv")
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")


@dataclass(frozen=True)
class ChartOptions:
    symbol: str
    period: str = "3m"
    indicators: tuple[str, ...] = SUPPORTED_INDICATORS
    start_date: str | None = None
    end_date: str | None = None


def parse_chart_args(args: list[str]) -> ChartOptions:
    if not args:
        raise ValueError("Cú pháp: /chart <MÃ> [3m|6m|1y] [ema,rsi,macd,obv]")
    symbol = args[0].strip().upper()
    if not symbol.isalnum() or len(symbol) > 10:
        raise ValueError("Mã chứng khoán không hợp lệ")
    period, start_date, end_date, indicator_arg = "3m", None, None, None
    if len(args) > 1 and "-" in args[1]:
        if len(args) < 3:
            raise ValueError("Cần nhập đủ ngày bắt đầu và ngày kết thúc")
        try:
            start_date, end_date = date.fromisoformat(args[1]), date.fromisoformat(args[2])
        except ValueError as error:
            raise ValueError("Ngày phải có dạng YYYY-MM-DD") from error
        if start_date > end_date:
            raise ValueError("Ngày bắt đầu phải trước ngày kết thúc")
        period, indicator_arg = "custom", args[3] if len(args) > 3 else None
    else:
        period = args[1].lower() if len(args) > 1 else "3m"
        if period not in PERIOD_SESSIONS:
            raise ValueError("Khoảng thời gian hỗ trợ: 3m, 6m, 1y hoặc hai ngày YYYY-MM-DD")
        indicator_arg = args[2] if len(args) > 2 else None
    indicators = tuple(dict.fromkeys(
        item.strip().lower() for item in (indicator_arg.split(",") if indicator_arg else SUPPORTED_INDICATORS)
        if item.strip()
    ))
    unknown = set(indicators) - set(SUPPORTED_INDICATORS)
    if unknown:
        raise ValueError("Chỉ báo hỗ trợ: ema, rsi, macd, obv")
    return ChartOptions(
        symbol, period, indicators,
        start_date.isoformat() if start_date else None,
        end_date.isoformat() if end_date else None,
    )


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    value = sum(values[:period]) / period
    result[period - 1] = value
    alpha = 2 / (period + 1)
    for index in range(period, len(values)):
        value = values[index] * alpha + value * (1 - alpha)
        result[index] = value
    return result


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    changes = [b - a for a, b in zip(values, values[1:])]
    gain = sum(max(x, 0) for x in changes[:period]) / period
    loss = sum(max(-x, 0) for x in changes[:period]) / period
    result[period] = 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    for index, change in enumerate(changes[period:], start=period + 1):
        gain = (gain * (period - 1) + max(change, 0)) / period
        loss = (loss * (period - 1) + max(-change, 0)) / period
        result[index] = 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return result


def render_candlestick(bars: list[Bar], options: ChartOptions, output_dir: Path) -> Path:
    if options.start_date:
        first = next((i for i, bar in enumerate(bars)
                      if datetime.fromtimestamp(bar.ts, VIETNAM).date() >= date.fromisoformat(options.start_date)), len(bars))
        last = next((i for i, bar in enumerate(bars[first:], first)
                     if datetime.fromtimestamp(bar.ts, VIETNAM).date() > date.fromisoformat(options.end_date or options.start_date)), len(bars))
    else:
        first, last = max(0, len(bars) - PERIOD_SESSIONS[options.period]), len(bars)
    selected = bars[first:last]
    if len(selected) < 20:
        raise ValueError("Chưa đủ dữ liệu để vẽ biểu đồ")
    output_dir.mkdir(parents=True, exist_ok=True)
    all_closes = [bar.close for bar in bars[:last]]
    closes = all_closes[first:last]
    panels = [name for name in ("rsi", "macd", "obv") if name in options.indicators]
    ratios = [4] + [1.15] * len(panels)
    figure, axes = plt.subplots(
        1 + len(panels), 1, figsize=(12, 6 + len(panels) * 1.4),
        sharex=True, gridspec_kw={"height_ratios": ratios}, constrained_layout=True,
    )
    axes = [axes] if not hasattr(axes, "__len__") else axes
    price_ax = axes[0]
    colors = []
    for x, bar in enumerate(selected):
        color = "#16a085" if bar.close >= bar.open else "#e74c3c"
        colors.append(color)
        price_ax.vlines(x, bar.low, bar.high, color=color, linewidth=1)
        body_low = min(bar.open, bar.close)
        body_height = max(abs(bar.close - bar.open), max(bar.high - bar.low, 1) * 0.015)
        price_ax.add_patch(Rectangle((x - .32, body_low), .64, body_height,
                                     facecolor=color, edgecolor=color))
    if "ema" in options.indicators:
        price_ax.plot(_ema(all_closes, 20)[first:last], color="#f39c12", linewidth=1.4, label="EMA20")
        price_ax.plot(_ema(all_closes, 50)[first:last], color="#3498db", linewidth=1.4, label="EMA50")
        price_ax.legend(loc="upper left", frameon=False, ncol=2)
    low, high = min(bar.low for bar in selected), max(bar.high for bar in selected)
    padding = max((high - low) * .08, abs(high) * .01, .01)
    price_ax.set_ylim(low - padding, high + padding)
    label = (f"{options.start_date} → {options.end_date}" if options.start_date else options.period.upper())
    price_ax.set_title(f"{options.symbol} · {label} · Nến ngày", fontweight="bold")
    price_ax.set_ylabel("Giá")
    volume_ax = price_ax.twinx()
    volume_ax.bar(range(len(selected)), [bar.volume for bar in selected], color=colors,
                  width=.7, alpha=.13, zorder=0)
    volume_ax.set_ylim(0, max(bar.volume for bar in selected) * 4)
    volume_ax.set_yticks([])
    panel_index = 1
    if "rsi" in panels:
        values = _rsi(all_closes)[first:last]
        axes[panel_index].plot(values, color="#8e44ad", linewidth=1.2)
        axes[panel_index].axhspan(30, 70, color="#8e44ad", alpha=.08)
        axes[panel_index].set_ylim(0, 100)
        axes[panel_index].set_ylabel("RSI14")
        panel_index += 1
    if "macd" in panels:
        ema12, ema26 = _ema(all_closes, 12), _ema(all_closes, 26)
        macd = [a - b if a is not None and b is not None else None for a, b in zip(ema12, ema26)]
        numeric = [x for x in macd if x is not None]
        signal = _ema(numeric, 9)
        offset = len(macd) - len(numeric)
        axes[panel_index].plot(macd[first:last], color="#2980b9", label="MACD")
        axes[panel_index].plot(([None] * offset + signal)[first:last], color="#e67e22", label="Signal")
        axes[panel_index].axhline(0, color="#888", linewidth=.6)
        axes[panel_index].set_ylabel("MACD")
        axes[panel_index].legend(loc="upper left", frameon=False, ncol=2)
        panel_index += 1
    if "obv" in panels:
        obv = [0]
        for before, current in zip(bars[:last], bars[1:last]):
            direction = 1 if current.close > before.close else -1 if current.close < before.close else 0
            obv.append(obv[-1] + direction * current.volume)
        axes[panel_index].plot(obv[first:last], color="#2c3e50", linewidth=1.1)
        axes[panel_index].set_ylabel("OBV")
    tick_count = min(8, len(selected))
    ticks = sorted(set(round(i * (len(selected) - 1) / max(tick_count - 1, 1)) for i in range(tick_count)))
    axes[-1].set_xticks(ticks, [datetime.fromtimestamp(selected[i].ts, VIETNAM).strftime("%d/%m") for i in ticks])
    for axis in axes:
        axis.grid(alpha=.18, linewidth=.6)
        axis.margins(x=.01)
    path = output_dir / f"{options.symbol}_{options.period}_{uuid4().hex}.png"
    figure.savefig(path, dpi=150, facecolor="white")
    plt.close(figure)
    return path


def render_intraday_index(bars: list[Bar], session: str, output_dir: Path) -> Path:
    if len(bars) < 2:
        raise ValueError("Chưa đủ dữ liệu VN-Index trong phiên")
    output_dir.mkdir(parents=True, exist_ok=True)
    figure, (price_ax, volume_ax) = plt.subplots(
        2, 1, figsize=(12, 6.5), sharex=True,
        gridspec_kw={"height_ratios": [4, 1]}, constrained_layout=True,
    )
    colors = []
    for x, bar in enumerate(bars):
        color = "#16a085" if bar.close >= bar.open else "#e74c3c"
        colors.append(color)
        price_ax.vlines(x, bar.low, bar.high, color=color, linewidth=.8)
        bottom = min(bar.open, bar.close)
        height = max(abs(bar.close - bar.open), max(bar.high - bar.low, .01) * .02)
        price_ax.add_patch(Rectangle((x - .3, bottom), .6, height,
                                     facecolor=color, edgecolor=color))
    low, high = min(x.low for x in bars), max(x.high for x in bars)
    padding = max((high - low) * .1, abs(high) * .002)
    price_ax.set_ylim(low - padding, high + padding)
    price_ax.set_title("VN-INDEX · Phiên sáng" if session == "MORNING" else "VN-INDEX · Cả ngày",
                       fontweight="bold")
    price_ax.set_ylabel("Điểm")
    volume_ax.bar(range(len(bars)), [x.volume for x in bars], color=colors, width=.75)
    volume_ax.set_ylabel("KL")
    ticks = sorted(set(round(i * (len(bars) - 1) / 7) for i in range(8)))
    volume_ax.set_xticks(ticks, [datetime.fromtimestamp(bars[i].ts, VIETNAM).strftime("%H:%M") for i in ticks])
    for axis in (price_ax, volume_ax):
        axis.grid(alpha=.18, linewidth=.6)
        axis.margins(x=.01)
    path = output_dir / f"VNINDEX_{session.lower()}_{uuid4().hex}.png"
    figure.savefig(path, dpi=150, facecolor="white")
    plt.close(figure)
    return path
