"""Build the right GameSource for a platform from application settings."""

import httpx

from chess_trainer.config import Settings
from chess_trainer.db.enums import Platform
from chess_trainer.ingestion.chesscom import ChessComSource
from chess_trainer.ingestion.http import RetryingClient
from chess_trainer.ingestion.lichess import LichessSource
from chess_trainer.ingestion.sources import GameSource


def build_http_client(settings: Settings) -> RetryingClient:
    client = httpx.Client(
        headers={"User-Agent": settings.http_user_agent},
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
    )
    return RetryingClient(client, max_retries=settings.http_max_retries)


def build_source(platform: Platform, settings: Settings) -> GameSource:
    http = build_http_client(settings)
    if platform is Platform.LICHESS:
        return LichessSource(http, settings.lichess_base_url)
    return ChessComSource(http, settings.chesscom_base_url)
