from datetime import UTC, datetime

import pytest

from common.types import MarketPrice
from data.providers import (
    FailoverMarketDataProvider,
    MarketDataNotConfiguredError,
    MarketDataUnavailableError,
    MarketPriceResult,
    ProviderUnavailableError,
)


class FakeProvider:
    def __init__(
        self,
        name: str,
        *,
        result: MarketPrice | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.result = result
        self.error = error
        self.requested_symbols: list[str] = []

    async def get_latest_price(self, symbol: str) -> MarketPrice:
        self.requested_symbols.append(symbol)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.mark.asyncio
async def test_failover_uses_next_provider_when_primary_is_unavailable() -> None:
    price = MarketPrice("HPG", 28_500.0, datetime(2026, 9, 19, tzinfo=UTC))
    primary = FakeProvider("dnse", error=ProviderUnavailableError("timeout"))
    backup = FakeProvider("backup", result=price)
    provider = FailoverMarketDataProvider([primary, backup])

    result = await provider.get_latest_price("HPG")

    assert result == MarketPriceResult(value=price, source="backup")
    assert primary.requested_symbols == ["HPG"]
    assert backup.requested_symbols == ["HPG"]


@pytest.mark.asyncio
async def test_failover_reports_not_configured_when_no_provider_exists() -> None:
    provider = FailoverMarketDataProvider([])

    with pytest.raises(MarketDataNotConfiguredError):
        await provider.get_latest_price("HPG")


@pytest.mark.asyncio
async def test_failover_reports_unavailable_after_every_provider_fails() -> None:
    provider = FailoverMarketDataProvider(
        [
            FakeProvider("dnse", error=ProviderUnavailableError("timeout")),
            FakeProvider("backup", error=ProviderUnavailableError("maintenance")),
        ]
    )

    with pytest.raises(MarketDataUnavailableError) as error:
        await provider.get_latest_price("HPG")

    assert error.value.providers == ("dnse", "backup")


@pytest.mark.asyncio
async def test_failover_does_not_hide_unexpected_programming_errors() -> None:
    provider = FailoverMarketDataProvider(
        [FakeProvider("dnse", error=ValueError("bad parser"))]
    )

    with pytest.raises(ValueError, match="bad parser"):
        await provider.get_latest_price("HPG")
