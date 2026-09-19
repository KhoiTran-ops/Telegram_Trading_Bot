from pathlib import Path

import pytest

from common.watchlist import WatchlistConfig, load_watchlist


def test_load_watchlist_normalizes_and_deduplicates_symbols(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "confirmed: false\nwatchlist: [hpg, FPT, HPG]\nrealtime_universe: [vcb]\n",
        encoding="utf-8",
    )

    result = load_watchlist(path)

    assert result == WatchlistConfig(
        confirmed=False,
        watchlist=("HPG", "FPT"),
        realtime_universe=("VCB",),
    )


def test_load_watchlist_rejects_invalid_symbols(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text("watchlist: ['HPG; DROP']\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid market symbol"):
        load_watchlist(path)

