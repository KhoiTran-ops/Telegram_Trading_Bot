"""Minimal JSON logging with an allowlist of operational fields."""

from datetime import UTC, datetime
import json
import logging
import re


LOG_FIELDS = (
    "event", "entry_point", "request_id", "provider", "operation", "error_type",
    "exchange", "saved", "rejected", "window_start", "window_end",
    "session",
)
TELEGRAM_BOT_URL_PATTERN = re.compile(
    r"(https://api\.telegram\.org/bot)[^/\s]+",
    flags=re.IGNORECASE,
)


def redact_secrets(message: str) -> str:
    return TELEGRAM_BOT_URL_PATTERN.sub(r"\1<redacted>", message)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
        }
        for field in LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for noisy_logger in ("httpx", "httpcore", "telegram"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
