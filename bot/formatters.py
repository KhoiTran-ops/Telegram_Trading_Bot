"""Short, user-facing Vietnamese Telegram messages."""

from common.types import MarketPrice
from common.watchlist import WatchlistConfig
from signal_engine.engine import BacktestResult
from signal_engine.service import SignalEvaluation


COMMAND_GROUPS_TEXT = """🔎 TÍN HIỆU
/signal <MÃ>  •  Phân tích một cổ phiếu
/tinhieu  •  Tín hiệu đáng chú ý
/buy  •  Cơ hội mua và mã đang theo dõi
/sell  •  Tín hiệu bán hoặc thận trọng

📊 THỊ TRƯỜNG & BIỂU ĐỒ
/thitruong  •  Toàn cảnh VN-Index
/price <MÃ>  •  Giá và biến động trong phiên
/chart <MÃ>  •  Biểu đồ nến và chỉ báo

🧪 KIỂM ĐỊNH
/hieuqua <MÃ>  •  Backtest 2 năm

⚙️ TIỆN ÍCH
/thongbao  •  Bật báo cáo tự động
/huythongbao  •  Tắt báo cáo tự động
/help  •  Hướng dẫn sử dụng"""

START_TEXT = f"""🤖 GOODJOB
Trợ lý theo dõi thị trường chứng khoán Việt Nam

{COMMAND_GROUPS_TEXT}

ℹ️ Thông tin chỉ mang tính tham khảo."""

HELP_TEXT = f"""📚 HƯỚNG DẪN

{COMMAND_GROUPS_TEXT}

Ví dụ biểu đồ:
• /chart HPG
• /chart FPT 6m ema,rsi
• /chart VNINDEX 1y ema,macd
• /chart VCB 2026-01-01 2026-06-30 ema,rsi,macd

Khoảng nhanh: 3m · 6m · 1y
Chỉ báo: ema · rsi · macd · obv"""

DATA_SOURCE_NOT_CONFIGURED_TEXT = "⚠️ Nguồn dữ liệu chưa được cấu hình."
DATA_SOURCE_UNAVAILABLE_TEXT = "⚠️ Nguồn dữ liệu đang không phản hồi."
MARKET_OUTPUT_NOT_CONFIGURED_TEXT = "⚠️ Chưa đủ dữ liệu trong phiên để tổng hợp thị trường."
SIGNAL_NOT_CONFIGURED_TEXT = "⚠️ Bộ máy phân tích chưa sẵn sàng."


def format_watchlist(config: WatchlistConfig) -> str:
    label = "Danh sách đã xác nhận" if config.confirmed else "Danh sách mẫu — chưa xác nhận"
    return f"📌 {label}\n{', '.join(config.watchlist) if config.watchlist else 'Chưa có mã'}"


def format_market_price(price: MarketPrice, source: str) -> str:
    lines = [f"💹 {price.symbol}: {price.price:,.2f} nghìn đồng"]
    if price.reference_price is not None:
        change = price.price - price.reference_price
        percent = change / price.reference_price * 100 if price.reference_price else 0
        icon = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
        lines.append(f"{icon} Trong phiên: {change:+,.2f} ({percent:+.2f}%)")
        lines.append(f"Tham chiếu: {price.reference_price:,.2f}")
    return "\n".join(lines)


def _number(value: object, digits: int = 2) -> str | None:
    return f"{value:,.{digits}f}" if isinstance(value, (int, float)) else None


def _signal_label(action: str) -> tuple[str, str]:
    if action.endswith("BUY"):
        return "🟢 MUA", "Đà tăng tốt."
    if "SELL" in action:
        return "🔴 BÁN / THẬN TRỌNG", "Áp lực giảm chiếm ưu thế."
    if "REJECT" in action:
        return "🔴 CHƯA ĐẠT", "Chưa đạt tiêu chí."
    if "WATCH" in action:
        return "🟡 THEO DÕI", "Chờ tín hiệu rõ hơn."
    return "⚪ TRUNG LẬP", "Chưa có tín hiệu."


def format_signal(result: SignalEvaluation) -> str:
    label, note = _signal_label(result.action)
    lines = [f"📌 {result.symbol} · {label}"]
    if result.company_name:
        lines.append(f"{result.company_name} · {result.exchange or ''}")
    if result.technical is None:
        return "\n".join(lines + ["Chưa đủ lịch sử giá để phân tích."])
    lines.append("")
    metrics = result.technical.metrics
    price = _number(metrics.get("close"))
    if price:
        lines.append(f"💰 Giá: {price}")
    ema20, ema50 = metrics.get("ema20"), metrics.get("ema50")
    if all(isinstance(x, (int, float)) for x in (metrics.get("close"), ema20, ema50)):
        trend = "Xu hướng tăng" if metrics["close"] > ema20 > ema50 else "Xu hướng chưa rõ" if metrics["close"] > ema50 else "Xu hướng yếu"
        lines.append(f"📈 {trend}")
    rsi = _number(metrics.get("rsi14"), 1)
    volume = _number(metrics.get("volume_ratio"), 1)
    details = [f"RSI {rsi}" if rsi else None, f"Khối lượng {volume}x trung bình" if volume else None]
    details = [item for item in details if item]
    if details:
        lines.append("📊 " + " · ".join(details))
    stop, target = _number(metrics.get("stop")), _number(metrics.get("target"))
    if stop and target:
        lines.extend(["", f"🛡 Tham khảo: dừng lỗ {stop} · mục tiêu {target}"])
    lines.append("")
    lines.append(f"💬 {note}")
    return "\n".join(lines)


def _percent(value: object) -> str:
    return f"{value * 100:+.1f}%" if isinstance(value, (int, float)) else "—"


def format_signal_detail(result: SignalEvaluation) -> str:
    if result.technical is None:
        return f"📌 {result.symbol}\n\nChưa đủ lịch sử giá để phân tích chi tiết."
    technical = result.technical
    metrics = technical.metrics
    technical_label, technical_note = _signal_label(technical.action)
    lines = [
        f"📌 CHI TIẾT {result.symbol}",
        result.company_name or "",
        "",
        f"🔧 KỸ THUẬT · {technical_label}",
        f"Giá {_number(metrics.get('close')) or '—'} · EMA20 {_number(metrics.get('ema20')) or '—'} · EMA50 {_number(metrics.get('ema50')) or '—'}",
        f"RSI {_number(metrics.get('rsi14'), 1) or '—'} · Khối lượng {_number(metrics.get('volume_ratio'), 1) or '—'}x TB20",
        f"MACD {_number(metrics.get('macd')) or '—'} · Signal {_number(metrics.get('macd_signal')) or '—'}",
        f"Sức mạnh 3 tháng so với VN-Index: {_percent(metrics.get('rs3m'))}",
        f"→ {technical_note}",
    ]
    fundamental = result.fundamentals
    if fundamental is not None:
        status = ("🟢 ĐẠT" if fundamental.mandatory_pass is True else
                  "🔴 CHƯA ĐẠT" if fundamental.mandatory_pass is False else
                  "🟡 CHƯA ĐỦ DỮ LIỆU")
        fm = fundamental.metrics
        lines.extend([
            "",
            f"📊 CƠ BẢN · {status}",
            f"ROE {_percent(fm.get('roe'))} · Doanh thu {_percent(fm.get('revenue_growth_yoy'))} · Lợi nhuận {_percent(fm.get('profit_growth_yoy'))}",
        ])
        failure_labels = {
            "roe_below_15pct": "ROE dưới 15%",
            "profit_ttm_not_positive": "Lợi nhuận 12 tháng không dương",
            "profit_growth_below_15pct": "Tăng trưởng lợi nhuận dưới 15%",
            "latest_profit_yoy_not_positive": "Lợi nhuận quý gần nhất chưa tăng",
            "revenue_growth_negative": "Doanh thu đang giảm",
            "debt_to_equity_above_200pct": "Nợ cao hơn 2 lần vốn chủ",
            "previous_profit_not_positive": "Lợi nhuận năm trước không dương",
            "previous_revenue_zero": "Thiếu doanh thu năm trước",
        }
        reasons = [failure_labels[item] for item in fundamental.failures
                   if item in failure_labels]
        if reasons:
            lines.append("→ " + " · ".join(reasons[:3]))
        elif fundamental.mandatory_pass is None:
            lines.append("→ Đang chờ đủ 8 quý và các chỉ tiêu bắt buộc.")
        else:
            lines.append("→ Các tiêu chí chính đang đạt.")
        debt = _number(fm.get("debt_to_equity"))
        current = _number(fm.get("current_ratio"))
        references = [f"Nợ/VCSH {debt}x" if debt else None,
                      f"Thanh toán hiện hành {current}x" if current else None]
        references = [item for item in references if item]
        if references:
            lines.extend(["", "📎 THAM KHẢO", " · ".join(references)])
    lines.extend(["", "ℹ️ Công cụ hỗ trợ tham khảo, không phải khuyến nghị đầu tư."])
    return "\n".join(line for line in lines if line is not None)


def format_scan(results: list[SignalEvaluation], *, title: str = "TÍN HIỆU ĐÁNG CHÚ Ý") -> str:
    if not results:
        return "ℹ️ Chưa có mã phù hợp ở lần quét này."
    lines = [f"🔎 {title}", ""]
    for result in results:
        label, note = _signal_label(result.action)
        metrics = getattr(result.technical, "metrics", {}) if result.technical else {}
        price = _number(metrics.get("close"))
        lines.append(f"{label.split()[0]} /{result.symbol}" + (f" · {price}" if price else "") + f" — {note}")
    lines.extend(["", "Chạm vào mã hoặc dùng /signal <MÃ> để xem thêm."])
    return "\n".join(lines)


def format_backtest(result: BacktestResult) -> str:
    if result.total_return is None:
        return f"⚠️ Chưa đủ dữ liệu để backtest {result.symbol}."
    return "\n".join([
        f"🧪 BACKTEST {result.symbol}",
        f"📅 2 năm gần nhất · {result.sessions} phiên",
        f"💰 Lợi nhuận: {result.total_return * 100:+.2f}%",
        f"📈 Buy & Hold: {(result.buy_hold_return or 0) * 100:+.2f}%",
        f"🎯 Tỷ lệ thắng: {(result.win_rate or 0) * 100:.1f}%",
        f"📉 Sụt giảm lớn nhất: {(result.max_drawdown or 0) * 100:.2f}%",
        "Kết quả chỉ mô phỏng phần kỹ thuật và không phải khuyến nghị đầu tư.",
    ])
