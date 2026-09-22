"""Market summary calculations shared by commands and scheduled messages."""

from dataclasses import dataclass
import math

from signal_engine.engine import Bar


@dataclass(frozen=True)
class MarketHighlight:
    symbol: str
    change_percent: float
    traded_value: float


@dataclass(frozen=True)
class MarketSummary:
    session: str
    index_close: float
    points_change: float
    percent_change: float
    advancers: int
    decliners: int
    unchanged: int
    highlights: tuple[MarketHighlight, ...]


def build_market_summary(index_bars: list[Bar], movers: list[tuple[str, float, float]], *,
                         session: str, reference_close: float | None = None) -> MarketSummary:
    if len(index_bars) < 2:
        raise ValueError("Chưa đủ dữ liệu VN-Index để tổng hợp thị trường")
    reference, current = reference_close or index_bars[0].open, index_bars[-1].close
    points = current - reference
    percent = points / reference * 100 if reference else 0
    liquid = [item for item in movers if item[2] >= 5_000_000_000]
    ordered = sorted(
        liquid, key=lambda item: abs(item[1]) * math.log10(max(item[2], 1)), reverse=True
    )[:6]
    return MarketSummary(
        session, current, points, percent,
        sum(change > 0 for _, change, _ in movers),
        sum(change < 0 for _, change, _ in movers),
        sum(change == 0 for _, change, _ in movers),
        tuple(MarketHighlight(*item) for item in ordered),
    )


def format_market_summary(summary: MarketSummary) -> str:
    title = "KẾT PHIÊN SÁNG" if summary.session == "MORNING" else "TỔNG KẾT PHIÊN"
    direction = "🟢" if summary.points_change > 0 else "🔴" if summary.points_change < 0 else "⚪"
    lines = [
        f"📊 {title}",
        f"{direction} VN-Index: {summary.index_close:,.2f} · {summary.points_change:+.2f} điểm ({summary.percent_change:+.2f}%)",
        f"🌐 Độ rộng HOSE: 🟢 {summary.advancers} tăng · 🔴 {summary.decliners} giảm · ⚪ {summary.unchanged} tham chiếu",
    ]
    if summary.highlights:
        lines.append("⭐ Mã HOSE nổi bật theo biến động và dòng tiền:\n" + "\n".join(
            f"{'🟢' if item.change_percent >= 0 else '🔴'} {item.symbol} {item.change_percent:+.2f}% · {item.traded_value / 1_000_000_000:,.1f} tỷ"
            for item in summary.highlights
        ))
    lines.append("Dữ liệu tham khảo, không phải khuyến nghị đầu tư.")
    return "\n".join(lines)
