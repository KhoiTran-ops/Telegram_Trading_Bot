"""Pure technical signal and single-symbol backtest calculations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Bar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class TechnicalResult:
    action: str
    t0_pass: bool | None
    t2a_score: int | None
    t2b_score: int | None
    metrics: dict[str, float | bool | None]
    warnings: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class Trade:
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    reason: str
    return_pct: float


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    mode: str
    sessions: int
    trades: tuple[Trade, ...]
    total_return: float | None
    annualized_return: float | None
    buy_hold_return: float | None
    win_rate: float | None
    max_drawdown: float | None
    excluded_adjustment_days: int
    notes: tuple[str, ...]


def clean_adjusted_segments(bars: list[Bar], *, gap_threshold: float = 0.18
                            ) -> tuple[list[Bar], tuple[int, ...]]:
    """Keep only the segment after the last probable corporate-action gap."""
    valid = [bar for bar in bars if bar.low >= 0 and bar.high >= bar.low
             and bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high]
    excluded: list[int] = []
    segment_start = 0
    for index in range(1, len(valid)):
        previous = valid[index - 1].close
        if previous > 0 and abs(valid[index].close / previous - 1) > gap_threshold:
            excluded.append(valid[index].ts)
            segment_start = index + 1
    return valid[segment_start:], tuple(excluded)


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for current in values[period:]:
        value = current * alpha + value * (1 - alpha)
    return value


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0:
        return 100.0
    return 100 - 100 / (1 + average_gain / average_loss)


def _atr(bars: list[Bar], period: int = 14) -> float | None:
    if len(bars) <= period:
        return None
    ranges = [max(current.high - current.low,
                  abs(current.high - previous.close),
                  abs(current.low - previous.close))
              for previous, current in zip(bars, bars[1:])]
    value = sum(ranges[:period]) / period
    for current in ranges[period:]:
        value = (value * (period - 1) + current) / period
    return value


def _weekly_ema20(bars: list[Bar]) -> float | None:
    weekly: dict[int, float] = {}
    for bar in bars:
        weekly[bar.ts // 604_800] = bar.close
    return _ema(list(weekly.values()), 20)


def _obv(values: list[Bar]) -> list[int]:
    result = [0]
    for previous, current in zip(values, values[1:]):
        direction = 1 if current.close > previous.close else -1 if current.close < previous.close else 0
        result.append(result[-1] + direction * current.volume)
    return result


def evaluate_technical(bars: list[Bar], index_bars: list[Bar]) -> TechnicalResult:
    bars, adjustment_days = clean_adjusted_segments(bars)
    missing: list[str] = []
    warnings = ["possible_adjustment_history_reset"] if adjustment_days else []
    if len(bars) < 60:
        missing.append("minimum_60_sessions")
        return TechnicalResult("NOT_AVAILABLE", None, None, None, {},
                               tuple(warnings), tuple(missing))
    window = bars[-160:]
    closes = [bar.close for bar in window]
    volumes = [bar.volume for bar in window]
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    rsi = _rsi(closes)
    volume20 = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / volume20 if volume20 else None
    average_volume = sum(volumes[-20:]) / 20
    average_value = sum(bar.close * 1_000 * bar.volume for bar in window[-20:]) / 20
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    macd_values = []
    for end in range(26, len(closes) + 1):
        fast, slow = _ema(closes[:end], 12), _ema(closes[:end], 26)
        if fast is not None and slow is not None:
            macd_values.append(fast - slow)
    macd = macd_values[-1] if macd_values else None
    signal = _ema(macd_values, 9)
    obv = _obv(window)
    weekly_ema = _weekly_ema20(window)
    index_by_ts = {bar.ts: bar.close for bar in index_bars}
    rs3m = None
    if len(window) >= 64:
        start, current = window[-64], window[-1]
        index_start, index_current = index_by_ts.get(start.ts), index_by_ts.get(current.ts)
        if index_start and index_current:
            rs3m = current.close / start.close - index_current / index_start
    index_closes = [bar.close for bar in index_bars if bar.ts <= window[-1].ts][-160:]
    index_ema50 = _ema(index_closes, 50)
    index_current = index_closes[-1] if index_closes else None
    market_weak = (
        index_current < index_ema50 if index_current is not None and index_ema50 is not None
        else None
    )
    t0_pass = average_volume >= 100_000 and average_value >= 5_000_000_000
    t2a_checks = [
        ema20 is not None and ema50 is not None and closes[-1] > ema20 > ema50,
        volume_ratio is not None and volume_ratio >= 1.5,
        rsi is not None and 50 <= rsi <= 70,
    ]
    t2b_checks = [
        macd is not None and signal is not None and macd > signal,
        rs3m is not None and rs3m >= 0.05,
        len(obv) > 20 and obv[-1] > obv[-21],
        weekly_ema is not None and closes[-1] > weekly_ema,
    ]
    t2a_score, t2b_score = sum(t2a_checks), sum(t2b_checks)
    overextended = ema20 is not None and closes[-1] / ema20 - 1 > 0.08
    if overextended:
        warnings.append("overextended_above_ema20")
    if market_weak:
        warnings.append("vnindex_below_ema50")
    action = "BUY" if t0_pass and t2a_score == 3 and t2b_score >= 3 and not overextended else (
        "SELL_OR_SKIP" if t2a_score <= 1 else "WATCH"
    )
    atr = _atr(window)
    risk = min(1.5 * atr, 0.05 * closes[-1]) if atr is not None else None
    return TechnicalResult(action, t0_pass, t2a_score, t2b_score, {
        "close": closes[-1], "ema20": ema20, "ema50": ema50, "rsi14": rsi,
        "volume_ratio": volume_ratio, "average_volume20": average_volume,
        "approx_value20_vnd": average_value, "macd": macd, "macd_signal": signal,
        "rs3m": rs3m, "weekly_ema20": weekly_ema, "atr14": atr,
        "stop": closes[-1] - risk if risk is not None else None,
        "target": closes[-1] + 2 * risk if risk is not None else None,
        "market_weak": market_weak, "overextended": overextended,
    }, tuple(warnings), tuple(missing))


def run_backtest(symbol: str, bars: list[Bar], index_bars: list[Bar]) -> BacktestResult:
    cleaned, excluded = clean_adjusted_segments(bars)
    if len(cleaned) < 60:
        return BacktestResult(symbol, "TECHNICAL_ONLY", len(cleaned), (), None, None,
                              None, None, None, len(excluded),
                              ("insufficient_price_history",))
    trades: list[Trade] = []
    position: tuple[int, float, float, float] | None = None
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    index_by_ts = {bar.ts: bar for bar in index_bars}
    for index in range(59, len(cleaned)):
        current = cleaned[index]
        start = max(0, index - 159)
        stock_window = cleaned[start:index + 1]
        index_window = [index_by_ts[bar.ts] for bar in stock_window if bar.ts in index_by_ts]
        signal = evaluate_technical(stock_window, index_window)
        if position is None and signal.action == "BUY":
            stop, target = signal.metrics.get("stop"), signal.metrics.get("target")
            if isinstance(stop, float) and isinstance(target, float):
                position = (current.ts, current.close, stop, target)
            continue
        if position is None:
            continue
        entry_ts, entry, stop, target = position
        reason = None
        exit_price = current.close
        if current.low <= stop:
            reason, exit_price = "STOP", stop
        elif current.high >= target:
            reason, exit_price = "TARGET", target
        elif signal.t2a_score is not None and signal.t2a_score <= 1:
            reason = "T2A_EXIT"
        if reason:
            change = exit_price / entry - 1
            equity *= 1 + change
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, equity / peak - 1)
            trades.append(Trade(entry_ts, current.ts, entry, exit_price, reason, change))
            position = None
    if position is not None:
        entry_ts, entry, _stop, _target = position
        exit_price = cleaned[-1].close
        change = exit_price / entry - 1
        equity *= 1 + change
        trades.append(Trade(entry_ts, cleaned[-1].ts, entry, exit_price,
                            "END_OF_DATA", change))
    win_rate = sum(trade.return_pct > 0 for trade in trades) / len(trades) if trades else None
    total_return = equity - 1
    annualized = (
        (1 + total_return) ** (252 / len(cleaned)) - 1
        if len(cleaned) and total_return > -1 else None
    )
    buy_hold = cleaned[-1].close / cleaned[0].close - 1
    return BacktestResult(
        symbol, "TECHNICAL_ONLY", len(cleaned), tuple(trades), total_return,
        annualized, buy_hold, win_rate, max_drawdown, len(excluded),
        ("fundamentals_excluded_no_publication_timestamp",
         "fees_slippage_portfolio_rules_excluded"),
    )
