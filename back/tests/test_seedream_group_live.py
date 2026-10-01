"""Seedream group ("组图") generation against the real DMXAPI endpoint.

Excluded from CI: needs `DMXAPI_API_KEY`, costs money (one 2-image call) and
depends on a third party. Run with `make test-llm` before trusting
`ImageModelProfile.max_group_outputs` for a model: it pins the request shape
(`sequential_image_generation`) and that `extract_seedream_results` reads
every image the live response actually carries.
"""

from __future__ import annotations

import os

import pytest

from app.models.enums import Operation
from app.providers.base import GenerationRequest
from app.providers.dmxapi_media import SEEDREAM_5_PRO_MODEL, DmxApiMediaProvider

pytestmark = pytest.mark.live


def test_seedream_returns_one_image_per_requested_variant() -> None:
    key = os.getenv("DMXAPI_API_KEY", "")
    if not key:
        pytest.skip("DMXAPI_API_KEY 未配置，跳过 Seedream 组图真实调用")
    provider = DmxApiMediaProvider(
        endpoint_id="live-seedream",
        capability_tag=Operation.TEXT_TO_IMAGE.value,
        model=SEEDREAM_5_PRO_MODEL,
        base_url=os.getenv("DMXAPI_BASE_URL", "https://www.dmxapi.cn"),
        api_key=key,
        timeout_ms=300_000,
    )
    result = provider.submit(
        GenerationRequest(
            job_id="live-seedream-group",
            operation=Operation.TEXT_TO_IMAGE.value,
            quality_tier="standard",
            prompt=(
                "生成一组共 2 张独立的场景图，同一机位的老式客厅，仅光照不同——"
                "图1：白天日光；图2：夜晚台灯暖光。"
            ),
            aspect_ratio="16:9",
            output_count=2,
        )
    )

    assert result.succeeded, result.metadata
    assert result.delivered_outputs == 2, result.metadata
