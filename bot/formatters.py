"""Provisional Telegram copy kept separate from command behavior."""

from common.types import MarketPrice
from common.watchlist import WatchlistConfig


COMMAND_GROUPS_TEXT = """Lệnh chung
/start - Giới thiệu bot và danh sách lệnh
/help - Xem hướng dẫn

Dữ liệu thị trường
/watchlist - Xem danh sách mã mẫu
/price <MÃ> - Xem giá gần nhất
/market - Xem trạng thái tổng quan thị trường

Chiến lược (chưa cấu hình)
/signal - Xem trạng thái tín hiệu
/check - Kiểm tra trạng thái chiến lược
/alert - Xem trạng thái cảnh báo
/scan - Xem trạng thái quét thị trường"""

START_TEXT = f"""Chào bạn! Bot cung cấp thông tin thị trường chứng khoán Việt Nam.

Dữ liệu chỉ mang tính tham khảo, không phải khuyến nghị đầu tư. Một số nguồn dữ liệu và chiến lược hiện chưa được cấu hình.

{COMMAND_GROUPS_TEXT}"""

HELP_TEXT = f"""Các lệnh hiện có:

{COMMAND_GROUPS_TEXT}

Nội dung hiển thị hiện là bản tạm thời và có thể thay đổi."""

DATA_SOURCE_NOT_CONFIGURED_TEXT = (
    "DATA_SOURCE_NOT_CONFIGURED\n"
    "Nguồn dữ liệu thị trường chưa được cấu hình. Vui lòng thử lại sau."
)

DATA_SOURCE_UNAVAILABLE_TEXT = (
    "DATA_SOURCE_UNAVAILABLE\n"
    "Tất cả nguồn dữ liệu đã cấu hình hiện không phản hồi. Vui lòng thử lại sau."
)

MARKET_OUTPUT_NOT_CONFIGURED_TEXT = (
    "MARKET_OUTPUT_NOT_CONFIGURED\n"
    "Cấu trúc tổng quan thị trường chưa được chốt."
)

SIGNAL_NOT_CONFIGURED_TEXT = (
    "NOT_CONFIGURED\n"
    "Chiến lược chưa được cấu hình; bot không tạo tín hiệu giao dịch."
)


def format_watchlist(config: WatchlistConfig) -> str:
    label = "Danh sách đã xác nhận" if config.confirmed else "Danh sách mẫu (chưa xác nhận)"
    symbols = ", ".join(config.watchlist) if config.watchlist else "Chưa có mã"
    return f"{label}:\n{symbols}"


def format_market_price(price: MarketPrice, source: str) -> str:
    lines = [
        f"{price.symbol}: {price.price:,.0f}",
        f"Cập nhật: {price.timestamp.isoformat()}",
        f"Nguồn: {source}",
    ]
    if price.reference_price:
        change_percent = (price.price - price.reference_price) / price.reference_price * 100
        lines.append(f"Thay đổi: {change_percent:+.2f}%")
    return "\n".join(lines)
