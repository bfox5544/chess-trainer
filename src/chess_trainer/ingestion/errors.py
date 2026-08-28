"""Typed errors so callers (jobs, API) can react without parsing messages."""


class SourceError(Exception):
    """Base class for anything that goes wrong talking to a game source."""


class ResourceNotFound(SourceError):
    """The requested URL returned 404."""


class PlayerNotFound(SourceError):
    """The username does not exist on the platform."""


class RateLimited(SourceError):
    """Still rate limited after exhausting retries."""


class SourceUnavailable(SourceError):
    """Server errors or network failures persisted through all retries."""
