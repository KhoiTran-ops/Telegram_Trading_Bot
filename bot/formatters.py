"""Vietnamese Telegram output backed only by implemented data."""

from common.types import MarketPrice
from common.watchlist import WatchlistConfig
from signal_engine.engine import BacktestResult
from signal_engine.service import SignalEvaluation

COMMAND_GROUPS_TEXT = """Lệnh chung
/start - Mở menu lệnh
/help - Hướng dẫn

Chiến lược và tín hiệu
/tinhieu - Quét tín hiệu nổi bật hiện tại
/buy hoặc /mua - Các mã có tín hiệu mua
/sell hoặc /ban - Các mã suy yếu hoặc nên tránh
/signal <MÃ> - Phân tích chi tiết một mã
/scan - Quét nhanh universe DNSE

Dữ liệu thị trường và biểu đồ
/chart <MÃ> [3m|6m|1y] [ema,rsi,macd,obv]
/thitruong - Tổng quan VN-Index và các mã nổi bật
/price <MÃ> - Giá gần nhất

Kiểm định
/hieuqua <MÃ> - Backtest kỹ thuật của một mã

Khác
/watchlist - Danh sách mã mẫu chưa xác nhận
/chatid - Xem ID chat để bật báo cáo tự động
/help - Hướng dẫn cú pháp"""

START_TEXT = f"""🤖 FINQUANT BOT

Bot quét tín hiệu định lượng, phân tích cổ phiếu, vẽ biểu đồ nến và tổng hợp thị trường từ dữ liệu đã tích hợp.

{COMMAND_GROUPS_TEXT}

Dữ liệu chỉ mang tính tham khảo, không phải khuyến nghị đầu tư."""

HELP_TEXT = f"""CÁC LỆNH ĐANG HOẠT ĐỘNG

{COMMAND_GROUPS_TEXT}

Ví dụ:
/signal HPG
/chart HPG 6m ema,rsi,macd
/hieuqua HPG

Khoảng biểu đồ: 3m, 6m, 1y. Chỉ báo: EMA20/50, RSI14, MACD và OBV."""

DATA_SOURCE_NOT_CONFIGURED_TEXT = "DATA_SOURCE_NOT_CONFIGURED\nNguồn dữ liệu chưa được cấu hình."
DATA_SOURCE_UNAVAILABLE_TEXT = "DATA_SOURCE_UNAVAILABLE\nNguồn dữ liệu đang không phản hồi."
MARKET_OUTPUT_NOT_CONFIGURED_TEXT = "Chưa đủ dữ liệu trong phiên để tổng hợp thị trường."
SIGNAL_NOT_CONFIGURED_TEXT = "NOT_CONFIGURED\nBộ máy chiến lược chưa sẵn sàng."


def format_watchlist(config: WatchlistConfig) -> str:
    label = "Danh sách đã xác nhận" if config.confirmed else "Danh sách mẫu (chưa xác nhận)"
    return f"{label}:\n{', '.join(config.watchlist) if config.watchlist else 'Chưa có mã'}"


def format_market_price(price: MarketPrice, source: str) -> str:
    lines = [f"{price.symbol}: {price.price:,.0f}", f"Cập nhật: {price.timestamp.isoformat()}", f"Nguồn: {source}"]
    if price.reference_price:
        lines.append(f"Thay đổi: {(price.price / price.reference_price - 1) * 100:+.2f}%")
    return "\n".join(lines)


def _number(value: object, digits: int = 2) -> str:
    return "N/A" if not isinstance(value, (int, float)) else f"{value:,.{digits}f}"


def format_signal(result: SignalEvaluation) -> str:
    phase = "TẠM THỜI TRONG PHIÊN" if result.phase == "PROVISIONAL_INTRADAY" else "EOD ĐÃ XÁC NHẬN"
    lines = [f"📈 {result.symbol} — {phase}"]
    if result.company_name:
        lines.append(f"{result.company_name} ({result.exchange or 'N/A'})")
    lines.append(f"Tín hiệu: {result.action}")
    if result.technical is None:
        return "\n".join(lines + ["Chưa có lịch sử giá để phân tích."])
    technical, metrics = result.technical, result.technical.metrics
    quant = round(((technical.t2a_score or 0) + (technical.t2b_score or 0)) / 7 * 100)
    lines += [
        f"Điểm Quant kỹ thuật: {quant}/100",
        f"Thanh khoản: {'ĐẠT' if technical.t0_pass else 'KHÔNG ĐẠT'}",
        f"T2A: {technical.t2a_score}/3 · T2B: {technical.t2b_score}/4",
        f"Giá {_number(metrics.get('close'))} · RSI14 {_number(metrics.get('rsi14'), 1)}",
        f"EMA20 {_number(metrics.get('ema20'))} · EMA50 {_number(metrics.get('ema50'))}",
        f"Vol Ratio {_number(metrics.get('volume_ratio'), 1)}x",
        f"Stop tham khảo {_number(metrics.get('stop'))} · Target {_number(metrics.get('target'))}",
    ]
    if result.fundamentals is not None:
        status = "ĐẠT" if result.fundamentals.mandatory_pass is True else "KHÔNG ĐẠT" if result.fundamentals.mandatory_pass is False else "CHƯA ĐỦ DỮ LIỆU"
        lines.append(f"Cơ bản: {status} · Hạng {result.fundamentals.grade or 'N/A'}")
    rows = int(result.foreign.get("rows") or 0)
    lines.append(f"Khối ngoại: {rows} bản ghi" if rows else "Khối ngoại: chưa có dữ liệu")
    if technical.warnings:
        lines.append("Cảnh báo: " + ", ".join(technical.warnings))
    if result.missing:
        lines.append("Chưa đánh giá: " + ", ".join(result.missing))
    lines.append(f"Xem chart: /chart {result.symbol} 6m ema,rsi,macd")
    lines.append("Dữ liệu tham khảo, không phải khuyến nghị đầu tư.")
    return "\n".join(lines)


def format_scan(results: list[SignalEvaluation], *, title: str = "QUÉT TÍN HIỆU HIỆN TẠI") -> str:
    if not results:
        return "Chưa có mã đủ dữ liệu để quét."
    lines = [title]
    for result in results:
        technical = result.technical
        score = f"T2A {technical.t2a_score}/3 · T2B {technical.t2b_score}/4" if technical else "thiếu dữ liệu"
        lines.append(f"/{result.symbol}: {result.action} · {score}")
    lines.append("Dùng /signal <MÃ> để xem chi tiết.")
    return "\n".join(lines)


def format_backtest(result: BacktestResult) -> str:
    if result.total_return is None:
        return f"Chưa đủ dữ liệu để backtest {result.symbol}."
    return "\n".join([
        f"📊 BACKTEST KỸ THUẬT — {result.symbol}",
        f"Số phiên: {result.sessions} · Số lệnh: {len(result.trades)}",
        f"Lợi nhuận: {result.total_return * 100:+.2f}%",
        f"Lợi nhuận năm hóa: {(result.annualized_return or 0) * 100:+.2f}%",
        f"Buy & Hold: {(result.buy_hold_return or 0) * 100:+.2f}%",
        f"Win rate: {(result.win_rate or 0) * 100:.1f}%",
        f"Max drawdown: {(result.max_drawdown or 0) * 100:.2f}%",
        "Phạm vi: technical-only; không gồm phí, trượt giá, BCTC lịch sử hay phân bổ danh mục.",
    ])
