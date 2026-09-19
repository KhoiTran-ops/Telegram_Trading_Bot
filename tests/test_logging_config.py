import json
import logging

from common.logging_config import JsonFormatter, configure_logging


def test_json_formatter_redacts_telegram_bot_token_from_urls() -> None:
    token = "123456789:abcdefghijklmnopqrstuvwxyz_ABCD-1234"
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            "HTTP Request: POST "
            f"https://api.telegram.org/bot{token}/sendMessage HTTP/1.1 200 OK"
        ),
        args=(),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert token not in payload["message"]
    assert "bot<redacted>/sendMessage" in payload["message"]


def test_configure_logging_suppresses_http_client_request_logs() -> None:
    configure_logging()

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
