from pathlib import Path

import pytest
from pydantic import ValidationError

from common.config import Settings


def test_settings_require_only_telegram_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("TELEGRAM_BOT_TOKEN", "DNSE_API_KEY", "DNSE_API_SECRET"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    settings = Settings(telegram_bot_token="telegram-token", _env_file=None)
    assert settings.dnse_configured is False


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
    assert settings.dnse_configured is True


@pytest.mark.parametrize(
    ("dnse_api_key", "dnse_api_secret"),
    [("dnse-key", None), (None, "dnse-secret")],
)
def test_settings_reject_partial_dnse_credentials(
    dnse_api_key: str | None,
    dnse_api_secret: str | None,
) -> None:
    with pytest.raises(ValidationError, match="DNSE_API_KEY and DNSE_API_SECRET"):
        Settings(
            telegram_bot_token="telegram-token",
            dnse_api_key=dnse_api_key,
            dnse_api_secret=dnse_api_secret,
            _env_file=None,
        )
