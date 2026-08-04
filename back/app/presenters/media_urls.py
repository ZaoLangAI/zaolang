"""Asset URL projection.

Signed URLs are minted lazily and never cached in a response body beyond their
lifetime. Callers pass optional asset ids straight through, so a missing cover
degrades to `null` instead of an exception.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Asset
from app.models.enums import MediaType
from app.storage import s3


def asset_url(session: Session, asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    asset = session.get(Asset, asset_id)
    if asset is None:
        return None
    settings = get_settings()
    return s3.presign_get(asset.object_key, expires_in=settings.download_url_ttl_seconds)


def asset_size(session: Session, asset_id: str | None) -> tuple[int, int] | None:
    """Intrinsic pixel size, when the asset carries one.

    Clients that reserve a box before the image arrives need this; without it a
    wall of mixed-ratio covers can only be laid out after every image has
    loaded, which is a page that reflows under the reader.
    """
    if not asset_id:
        return None
    asset = session.get(Asset, asset_id)
    if asset is None or asset.width is None or asset.height is None:
        return None
    return asset.width, asset.height


def media_type_of(session: Session, asset_id: str | None) -> MediaType | None:
    if not asset_id:
        return None
    asset = session.get(Asset, asset_id)
    return MediaType(asset.media_type) if asset else None
