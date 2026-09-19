from pathlib import Path

import pytest
from pydantic import ValidationError

from common.config import Settings


def test_settings_require_telegram_and_dnse_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("TELEGRAM_BOT_TOKEN", "DNSE_API_KEY", "DNSE_API_SECRET"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_load_required_values_and_safe_defaults(tmp_path: Path) -> None:
    settings = Settings(
        telegram_bot_token="telegram-token",
        dnse_api_key="dnse-key",
        dnse_api_secret="dnse-secret",
        database_path=tmp_path / "market.db",
        _env_file=None,
    )

    assert settings.timezone == "Asia/Ho_Chi_Minh"
    assert settings.database_path == tmp_path / "market.db"
    assert settings.summary_chat_ids == ()


def test_summary_chat_ids_are_parsed_from_comma_separated_value() -> None:
    settings = Settings(
        telegram_bot_token="telegram-token",
        dnse_api_key="dnse-key",
        dnse_api_secret="dnse-secret",
        summary_chat_ids="123, -456,123",
        _env_file=None,
    )

    assert settings.summary_chat_ids == (123, -456)
