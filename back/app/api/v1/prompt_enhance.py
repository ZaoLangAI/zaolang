"""Shared plumbing for the two prompt-polish endpoints.

`GenerationStudio` and `ShortformStudio` each own their own route (only the
latter is feature-flagged) but publish the same request and response, and must
handle a degraded copy agent identically.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.schemas.shortform import (
    PromptDimensionView,
    PromptEnhanceRequest,
    PromptEnhanceResponse,
)
from app.domain import prompts
from app.domain.errors import ProviderTemporaryFailure


def context_from(payload: PromptEnhanceRequest) -> prompts.PromptContext:
    return prompts.PromptContext(
        operation=payload.operation or "",
        aspect_ratio=payload.aspect_ratio or "",
        duration_seconds=payload.duration_seconds,
        quality_tier=payload.quality_tier or "",
        style_hint=payload.style_hint,
        has_reference=payload.has_reference,
        direction=payload.direction or "",
        instruction=payload.instruction,
        asset_kind=payload.asset_kind or "",
    )


def enhanced_response(session: Session, result: prompts.PromptEnhancement) -> PromptEnhanceResponse:
    """Commits the `AgentRun`, then fails loudly if the agent degraded.

    The order matters both ways. Committing first keeps the degraded call in
    the ops console — `get_db` never commits on the way out, so raising before
    this would erase the only record that the gateway was unreachable. Raising
    after it is what stops the caller from presenting the fallback (which is
    the author's own text, echoed back) as a polish: an honest 503 is more
    useful than a suggestion that suggests nothing.
    """
    session.commit()
    if result.degraded:
        raise ProviderTemporaryFailure(prompts.ENHANCE_UNAVAILABLE_MESSAGE)
    return PromptEnhanceResponse(
        prompt=result.prompt,
        detail_level=result.detail_level,
        feedback=result.feedback,
        dimensions=[
            PromptDimensionView(key=d.key, status=d.status, hint=d.hint) for d in result.dimensions
        ],
        additions=result.additions,
    )
