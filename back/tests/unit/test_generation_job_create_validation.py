"""`GenerationJobCreateRequest` validation for the two new media operations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.schemas.jobs import GenerationJobCreateRequest, GenerationParams
from app.models.enums import Operation, QualityTier


def _request(operation: str, **param_overrides: object) -> GenerationJobCreateRequest:
    params = GenerationParams(prompt="测试提示词", **param_overrides)
    return GenerationJobCreateRequest(
        operation=operation, quality_tier=QualityTier.STANDARD, params=params
    )


def test_image_to_image_requires_a_reference_image() -> None:
    with pytest.raises(ValidationError, match="图生图必须提供参考图"):
        _request(Operation.IMAGE_TO_IMAGE)

    request = _request(Operation.IMAGE_TO_IMAGE, reference_asset_ids=["asset-1"])
    assert request.operation == Operation.IMAGE_TO_IMAGE


def test_audio_generation_requires_a_recognised_voice() -> None:
    with pytest.raises(ValidationError, match="音频生成必须指定音色"):
        _request(Operation.AUDIO_GENERATION)

    with pytest.raises(ValidationError, match="音频生成必须指定音色"):
        _request(Operation.AUDIO_GENERATION, extra={"voice": "not-a-real-voice"})

    request = _request(Operation.AUDIO_GENERATION, extra={"voice": "nova"})
    assert request.operation == Operation.AUDIO_GENERATION


def test_audio_generation_does_not_require_a_duration() -> None:
    """Unlike the video operations, a zero duration is fine here."""
    request = _request(Operation.AUDIO_GENERATION, extra={"voice": "alloy"}, duration_seconds=0)
    assert request.params.duration_seconds == 0


def test_image_to_image_does_not_require_a_duration() -> None:
    request = _request(
        Operation.IMAGE_TO_IMAGE, reference_asset_ids=["asset-1"], duration_seconds=0
    )
    assert request.params.duration_seconds == 0
