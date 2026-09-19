from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from common.types import MarketPrice, OHLCVBar, SignalResult, SignalStatus


def test_market_contracts_are_immutable() -> None:
    timestamp = datetime(2026, 9, 19, tzinfo=UTC)
    price = MarketPrice(
        symbol="HPG",
        price=28_500.0,
        timestamp=timestamp,
        reference_price=28_000.0,
    )
    bar = OHLCVBar(
        symbol="HPG",
        timeframe="1D",
        timestamp=timestamp,
        open=28_000.0,
        high=29_000.0,
        low=27_900.0,
        close=28_500.0,
        volume=1_000_000,
    )

    with pytest.raises(FrozenInstanceError):
        price.price = 0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        bar.close = 0  # type: ignore[misc]


def test_signal_result_can_report_not_configured_without_fake_action() -> None:
    result = SignalResult(
        symbol="HPG",
        status=SignalStatus.NOT_CONFIGURED,
        action=None,
        reasons=("Chiến lược chưa được cấu hình.",),
        generated_at=datetime(2026, 9, 19, tzinfo=UTC),
    )

    assert result.status == SignalStatus.NOT_CONFIGURED
    assert result.action is None

