"""User-published learning content payloads."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.works import AuthorSummary
from app.models.enums import LearnPostLevel, LearnPostStatus


class LearnPostSummary(ApiModel):
    """列表卡片投影，风格对齐 `works.WorkSummary`。"""

    id: str
    title: str
    summary: str
    level: LearnPostLevel
    cover_url: str | None = None
    author: AuthorSummary
    status: LearnPostStatus
    published_at: dt.datetime | None = None


class LearnPostDetail(LearnPostSummary):
    """详情比列表卡片多带 `cover_asset_id`：编辑表单回填封面时如果只拿得到
    `cover_url`，用户不重新选图提交就会把封面字段整份覆盖成空。

    `body_markdown` 里的图片用 `learn-asset:{id}` 这种不过期的引用而不是直出
    URL（对象存储的签名 URL 会过期，不能写进持久化的正文）；`asset_urls` 是
    服务端在这次响应里临时解析出的 `{资产 id: 当下有效的签名 URL}` 映射，只给
    渲染/编辑时替换显示用，不代表存储格式变了。
    """

    cover_asset_id: str | None = None
    body_markdown: str = ""
    asset_urls: dict[str, str] = Field(default_factory=dict)
    reject_reason: str | None = None
    created_at: dt.datetime


class LearnPostCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=160)
    level: LearnPostLevel = LearnPostLevel.BEGINNER
    cover_asset_id: str | None = None
    body_markdown: str = ""


class LearnPostUpdateRequest(LearnPostCreateRequest):
    pass
