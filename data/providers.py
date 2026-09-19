"""Stable market-data provider contract and ordered failover."""

from dataclasses import dataclass
import logging
from typing import Protocol, Sequence

from common.types import MarketPrice


logger = logging.getLogger(__name__)


class ProviderUnavailableError(RuntimeError):
    """A configured provider cannot serve the request right now."""


class MarketDataNotConfiguredError(RuntimeError):
    """No market-data provider has been configured."""


class MarketDataUnavailableError(RuntimeError):
    """Every configured provider failed with a transient availability error."""

    def __init__(self, providers: tuple[str, ...]) -> None:
        super().__init__("all configured market-data providers are unavailable")
        self.providers = providers


class MarketDataProvider(Protocol):
    """Contract implemented by DNSE and future fallback data sources."""

    name: str

    async def get_latest_price(self, symbol: str) -> MarketPrice:
        """Return the latest known market price for a normalized symbol."""
        ...


@dataclass(frozen=True)
class MarketPriceResult:
    value: MarketPrice
    source: str


class FailoverMarketDataProvider:
    """Try providers in priority order until one serves the request."""

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        self._providers = tuple(providers)

    @property
    def configured(self) -> bool:
        return bool(self._providers)

    async def get_latest_price(self, symbol: str) -> MarketPriceResult:
        if not self._providers:
            raise MarketDataNotConfiguredError("no market-data provider configured")

        failed_providers: list[str] = []
        for provider in self._providers:
            try:
                price = await provider.get_latest_price(symbol)
            except ProviderUnavailableError as error:
                failed_providers.append(provider.name)
                logger.warning(
                    "market data provider unavailable",
                    extra={
                        "event": "market_data_provider_unavailable",
                        "provider": provider.name,
                        "operation": "get_latest_price",
                        "error_type": type(error).__name__,
                    },
                )
                continue

            if failed_providers:
                logger.info(
                    "market data failover succeeded",
                    extra={
                        "event": "market_data_failover_succeeded",
                        "provider": provider.name,
                        "operation": "get_latest_price",
                    },
                )
            return MarketPriceResult(value=price, source=provider.name)

        raise MarketDataUnavailableError(tuple(failed_providers))
