"""HTTP client with retry, backoff, and rate-limit handling.

Both platforms ask API clients to back off on 429 (Lichess: wait a full
minute), so this is shared rather than reimplemented per source.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from chess_trainer.ingestion.errors import (
    RateLimited,
    ResourceNotFound,
    SourceError,
    SourceUnavailable,
)

DEFAULT_RATE_LIMIT_WAIT = 60.0


class RetryingClient:
    def __init__(
        self,
        client: httpx.Client,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        rate_limit_wait: float = DEFAULT_RATE_LIMIT_WAIT,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._rate_limit_wait = rate_limit_wait
        self._sleep = sleep  # injectable so tests don't actually wait

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET with retries; the body is fully read."""
        with self.stream(url, **kwargs) as response:
            response.read()
            return response

    @contextmanager
    def stream(self, url: str, **kwargs: Any) -> Iterator[httpx.Response]:
        """GET with retries; yields an open response for streaming.

        Retries cover connecting and the status line. A connection that drops
        mid-stream surfaces as SourceUnavailable rather than a silent restart,
        because the caller has already consumed part of the body.
        """
        response = self._open(url, **kwargs)
        try:
            yield response
        except httpx.TransportError as exc:
            raise SourceUnavailable(f"connection lost while reading {url}") from exc
        finally:
            response.close()

    def _open(self, url: str, **kwargs: Any) -> httpx.Response:
        last_error: SourceError = SourceUnavailable(f"no attempts made for {url}")
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.send(
                    self._client.build_request("GET", url, **kwargs), stream=True
                )
            except httpx.TransportError as exc:
                last_error = SourceUnavailable(f"network error for {url}: {exc}")
                wait = self._backoff(attempt)
            else:
                wait_or_none = self._retry_wait(response, attempt)
                if wait_or_none is None:
                    return response
                wait = wait_or_none
                last_error = self._error_for(response, url)
                response.close()
            if attempt < self._max_retries:
                self._sleep(wait)
        raise last_error

    def _retry_wait(self, response: httpx.Response, attempt: int) -> float | None:
        """Seconds to wait before retrying, or None if the response is final."""
        status = response.status_code
        if status == 429:
            return self._retry_after(response)
        if status >= 500:
            return self._backoff(attempt)
        if status == 404:
            response.close()
            raise ResourceNotFound(str(response.request.url))
        if status >= 400:
            response.close()
            raise SourceError(f"unexpected HTTP {status} for {response.request.url}")
        return None

    def _retry_after(self, response: httpx.Response) -> float:
        header = response.headers.get("Retry-After", "")
        return float(header) if header.isdigit() else self._rate_limit_wait

    def _backoff(self, attempt: int) -> float:
        return self._backoff_base * (2**attempt)

    @staticmethod
    def _error_for(response: httpx.Response, url: str) -> SourceError:
        if response.status_code == 429:
            return RateLimited(f"rate limited by {url}")
        return SourceUnavailable(f"HTTP {response.status_code} from {url}")
