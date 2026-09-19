"""Loading and validation for the shared watchlist configuration."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,10}$")


@dataclass(frozen=True)
class WatchlistConfig:
    confirmed: bool
    watchlist: tuple[str, ...]
    realtime_universe: tuple[str, ...]


def normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError(f"Invalid market symbol: {raw_symbol!r}")
    return symbol


def _read_symbols(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Watchlist symbols must be a YAML list of strings")
    return tuple(dict.fromkeys(normalize_symbol(item) for item in value))


def load_watchlist(path: Path) -> WatchlistConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Watchlist configuration must be a YAML mapping")
    return WatchlistConfig(
        confirmed=raw.get("confirmed") is True,
        watchlist=_read_symbols(raw.get("watchlist")),
        realtime_universe=_read_symbols(raw.get("realtime_universe")),
    )

