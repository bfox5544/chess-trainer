"""Open the puzzle CSV as a stream of text lines, from a URL or a file,
compressed (.zst) or not.

The download is streamed and decompressed on the fly, so importing the first
100,000 puzzles reads only the first few megabytes of the ~300 MB file and
nothing is written to disk.
"""

import io
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import IO

import httpx
import zstandard

from chess_trainer.ingestion.errors import SourceUnavailable


class ChunkReader(io.RawIOBase):
    """A read-only file object over an iterator of byte chunks."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        while not self._pending:
            chunk = next(self._chunks, None)
            if chunk is None:
                return 0
            self._pending = chunk
        size = min(len(buffer), len(self._pending))
        buffer[:size] = self._pending[:size]
        self._pending = self._pending[size:]
        return size


def is_url(location: str) -> bool:
    return location.startswith(("http://", "https://"))


@contextmanager
def open_lines(
    location: str, *, user_agent: str = "chess-trainer", timeout: float = 30.0
) -> Iterator[IO[str]]:
    """Yield a text stream of the CSV at `location`."""
    with ExitStack() as stack:
        raw: IO[bytes]
        if is_url(location):
            client = stack.enter_context(
                httpx.Client(
                    timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent}
                )
            )
            try:
                response = stack.enter_context(client.stream("GET", location))
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise SourceUnavailable(f"puzzle database download failed: {exc}") from exc
            raw = io.BufferedReader(ChunkReader(response.iter_bytes()))
        else:
            raw = stack.enter_context(open(location, "rb"))
        if location.endswith(".zst"):
            raw = stack.enter_context(zstandard.ZstdDecompressor().stream_reader(raw))  # type: ignore[arg-type]
        try:
            yield io.TextIOWrapper(raw, encoding="utf-8", newline="")  # type: ignore[arg-type]
        except httpx.HTTPError as exc:  # the connection dropped mid-stream
            raise SourceUnavailable(f"puzzle database download failed: {exc}") from exc
