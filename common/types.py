"""Canonical data contracts shared across application boundaries."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True)
class OHLCVBar:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class MarketPrice:
    symbol: str
    price: float
    timestamp: datetime
    reference_price: float | None = None


class SignalStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    READY = "READY"


@dataclass(frozen=True)
class SignalResult:
    symbol: str
    status: SignalStatus
    action: str | None
    reasons: tuple[str, ...]
    generated_at: datetime

