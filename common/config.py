"""Environment-backed application configuration."""

from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


SummaryChatIds = Annotated[tuple[int, ...], NoDecode]


class Settings(BaseSettings):
    """Validated settings loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str = Field(min_length=1)
    dnse_api_key: str = Field(min_length=1)
    dnse_api_secret: str = Field(min_length=1)
    database_path: Path = Path("var/market_data.db")
    watchlist_path: Path = Path("watchlist.yaml")
    timezone: str = "Asia/Ho_Chi_Minh"
    summary_chat_ids: SummaryChatIds = ()

    @field_validator("telegram_bot_token", "dnse_api_key", "dnse_api_secret")
    @classmethod
    def reject_blank_secrets(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("summary_chat_ids", mode="before")
    @classmethod
    def parse_summary_chat_ids(cls, value: Any) -> tuple[int, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            values = (int(item.strip()) for item in value.split(",") if item.strip())
        else:
            values = (int(item) for item in value)
        return tuple(dict.fromkeys(values))

