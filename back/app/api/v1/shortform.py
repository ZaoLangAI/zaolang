"""Short-video delivery spec catalogue.

The compliance-check, prompt/enhance, prompt/clarify and standalone
publications routes that used to live here belonged to the old single-clip
`ShortformStudio` (`/create/short/studio`), which has been replaced by the
`kind=drama` series management module — see `.cursor/skills/zaolang-editor-drama`.
Publishing a work now only ever happens through the standard eight-step
`/publish/[draftId]` form plus `app.domain.distribution.service.publish_fanout`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, rate_limited
from app.api.schemas.shortform import ShortformProfileResponse, ShortformProfilesResponse
from app.domain.shortform import service as shortform
from app.platform_config.schemas import ShortformProfile

router = APIRouter(tags=["shortform"])


@router.get("/shortform/profiles", response_model=ShortformProfilesResponse)
def list_profiles(
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> ShortformProfilesResponse:
    """The delivery-variant export spec catalogue (`zaolang-editor-drama`'s
    `batchCreateVariants`) renders its selector and limits from this."""
    catalog = shortform.catalog(session)
    return ShortformProfilesResponse(
        default_profile=catalog.default_profile,
        profiles=[_profile_response(key, p) for key, p in sorted(catalog.profiles.items())],
    )


def _profile_response(key: str, profile: ShortformProfile) -> ShortformProfileResponse:
    return ShortformProfileResponse(key=key, **profile.model_dump())
