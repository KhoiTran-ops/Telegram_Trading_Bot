from datetime import date
import json

from data.cafef.client import CafeFClient, RateLimitedTransport


class StubTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        return json.dumps(self.payload).encode()


def test_price_page_uses_allowlisted_endpoint_and_pagination() -> None:
    transport = StubTransport(
        {"Success": True, "Data": {"TotalCount": 0, "Data": []}}
    )
    client = CafeFClient(transport=transport)

    page = client.get_price_page(
        exchange="HOSE",
        start=date(2026, 9, 18),
        end=date(2026, 9, 18),
        page=2,
        page_size=20,
    )

    assert page.total_count == 0
    assert "PriceHistory.ashx" in transport.urls[0]
    assert "ExchangeType=HOSE" in transport.urls[0]
    assert "PageIndex=2" in transport.urls[0]


def test_client_rejects_unknown_exchange_before_network_call() -> None:
    transport = StubTransport({})
    client = CafeFClient(transport=transport)

    try:
        client.get_price_page(
            exchange="OTC",
            start=date(2026, 9, 18),
            end=date(2026, 9, 18),
            page=1,
            page_size=100,
        )
    except ValueError as error:
        assert "exchange" in str(error)
    else:
        raise AssertionError("unknown exchange must be rejected")
    assert transport.urls == []


def test_financial_client_requests_quarterly_data() -> None:
    transport = StubTransport({"isSuccess": True, "value": {"data": []}})
    client = CafeFClient(transport=transport)

    client.get_financial_summary("BBC", page=2)
    client.get_financial_html("BBC", "CashFlow", 2025, 3)

    assert "TypeTime=QUY" in transport.urls[0]
    assert "pageIndex=2" in transport.urls[0]
    assert "quarter=3" in transport.urls[1]


def test_transport_retries_read_timeout(monkeypatch) -> None:
    calls = 0

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"ok"

    def urlopen_once_timed_out(*_args: object, **_kwargs: object) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("read timed out")
        return Response()

    monkeypatch.setattr("data.cafef.client.urlopen", urlopen_once_timed_out)
    monkeypatch.setattr("data.cafef.client.time.sleep", lambda _delay: None)
    monkeypatch.setattr("data.cafef.client.random.uniform", lambda *_args: 0)

    content = RateLimitedTransport(requests_per_second=1, retries=1).get(
        "https://cafef.vn/du-lieu/test"
    )

    assert content == b"ok"
    assert calls == 2
