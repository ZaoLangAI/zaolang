"""Prompt-polish for the generation studio.

`ShortformStudio` has its own gated endpoint (`/shortform/prompt/enhance`,
behind the `shortform_studio` feature flag). This one backs
`GenerationStudio`'s "AI 润色" button instead — same shared logic
(`app.domain.prompts`), no feature flag, available to any authenticated user
composing a prompt.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, rate_limited
from app.api.schemas.shortform import PromptEnhanceRequest, PromptEnhanceResponse
from app.api.v1.prompt_enhance import context_from, enhanced_response
from app.domain import prompts

router = APIRouter(tags=["prompts"])


@router.post("/generation/prompts/enhance", response_model=PromptEnhanceResponse)
def enhance_generation_prompt(
    payload: PromptEnhanceRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> PromptEnhanceResponse:
    """把画面描述交给文案 Agent 逐维度诊断并润色，保留用户核心意图。"""
    result = prompts.enhance(
        session, user_id=user.id, prompt=payload.prompt, context=context_from(payload)
    )
    return enhanced_response(session, result)
