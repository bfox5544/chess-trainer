import httpx
import pytest
import respx

from chess_trainer.ingestion.errors import (
    RateLimited,
    ResourceNotFound,
    SourceError,
    SourceUnavailable,
)
from chess_trainer.ingestion.http import RetryingClient

URL = "https://example.test/data"


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def client(sleeps: list[float]) -> RetryingClient:
    return RetryingClient(httpx.Client(), max_retries=2, backoff_base=1.0, sleep=sleeps.append)


@respx.mock
def test_success_needs_no_retry(client: RetryingClient, sleeps: list[float]) -> None:
    respx.get(URL).respond(json={"ok": True})
    assert client.get(URL).json() == {"ok": True}
    assert sleeps == []


@respx.mock
def test_429_honours_retry_after_then_succeeds(client: RetryingClient, sleeps: list[float]) -> None:
    respx.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)]
    )
    assert client.get(URL).status_code == 200
    assert sleeps == [7.0]


@respx.mock
def test_429_without_header_waits_a_full_minute(
    client: RetryingClient, sleeps: list[float]
) -> None:
    respx.get(URL).mock(side_effect=[httpx.Response(429), httpx.Response(200)])
    client.get(URL)
    assert sleeps == [60.0]


@respx.mock
def test_persistent_429_raises_rate_limited(client: RetryingClient, sleeps: list[float]) -> None:
    route = respx.get(URL).respond(429)
    with pytest.raises(RateLimited):
        client.get(URL)
    assert route.call_count == 3  # first try + 2 retries
    assert len(sleeps) == 2  # no pointless sleep after the final attempt


@respx.mock
def test_server_errors_back_off_exponentially(client: RetryingClient, sleeps: list[float]) -> None:
    respx.get(URL).respond(503)
    with pytest.raises(SourceUnavailable):
        client.get(URL)
    assert sleeps == [1.0, 2.0]


@respx.mock
def test_network_error_is_retried(client: RetryingClient, sleeps: list[float]) -> None:
    respx.get(URL).mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200)])
    assert client.get(URL).status_code == 200
    assert sleeps == [1.0]


@respx.mock
def test_404_is_not_retried(client: RetryingClient, sleeps: list[float]) -> None:
    route = respx.get(URL).respond(404)
    with pytest.raises(ResourceNotFound):
        client.get(URL)
    assert route.call_count == 1


@respx.mock
def test_other_client_errors_fail_fast(client: RetryingClient) -> None:
    respx.get(URL).respond(403)
    with pytest.raises(SourceError):
        client.get(URL)
