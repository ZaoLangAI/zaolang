"""Shared model conventions.

Three rules the whole schema depends on:

* IDs are prefixed, non-enumerable strings (`work_01hq...`) so a leaked ID never
  reveals volume or ordering across tenants.
* Money and credits are integers in the smallest unit. Floats are never used.
* Every domain table carries `created_at` / `updated_at` in UTC.
"""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford-ish: no i/l/o/u


def new_id(prefix: str) -> str:
    """Time-ordered, non-enumerable identifier.

    The leading 48-bit millisecond timestamp keeps index locality (like UUIDv7)
    while the 80 random bits make IDs unguessable.
    """
    now_ms = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    time_part = _encode(now_ms, 10)
    random_part = _encode(secrets.randbits(80), 16)
    return f"{prefix}_{time_part}{random_part}"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ID_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}  # noqa: RUF012


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def id_column(prefix: str) -> Mapped[str]:
    return mapped_column(
        String(40), primary_key=True, default=lambda: new_id(prefix), nullable=False
    )
