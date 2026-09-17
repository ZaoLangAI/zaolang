"""Resolve inline asset references in learning-post markdown to signed URLs.

Shared by the C-end and admin learning routes so both build the exact same
`{asset_id: signed_url}` map from the same stored markdown, instead of each
duplicating the "parse markdown, presign every reference" loop.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.learning.service import iter_body_asset_ids
from app.presenters import media_urls


def resolve_body_asset_urls(session: Session, body_markdown: str) -> dict[str, str]:
    """签名 URL 会过期，绝不能持久化，所以每次读取都要重新解析正文里的引用。

    缺失的素材（比如已被删除）直接跳过，交给客户端渲染时走占位态，不因为
    一张坏图挡住整条内容。
    """
    urls: dict[str, str] = {}
    for asset_id in iter_body_asset_ids(body_markdown):
        url = media_urls.asset_url(session, asset_id)
        if url:
            urls[asset_id] = url
    return urls
