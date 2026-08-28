"""Declarative base and column helpers."""

from datetime import UTC, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def str_enum(enum_cls: type[StrEnum]) -> sa.Enum:
    """Store an enum as its plain string value.

    Non-native (VARCHAR) on purpose: adding a member is then a code change,
    not an `ALTER TYPE` migration.
    """
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
    )


def utcnow() -> datetime:
    return datetime.now(UTC)
