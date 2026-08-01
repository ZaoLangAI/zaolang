"""Shared response envelopes."""

from __future__ import annotations

import datetime as dt
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ErrorDetail(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""


class ErrorResponse(ApiModel):
    error: ErrorDetail


class Page[T](ApiModel):
    """Cursor pagination.

    Offsets are avoided so that new content arriving mid-scroll cannot cause
    the reader to skip or repeat items.
    """

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class Timestamped(ApiModel):
    created_at: dt.datetime
    updated_at: dt.datetime


class OkResponse(ApiModel):
    ok: bool = True


class CountResponse(ApiModel):
    count: int
