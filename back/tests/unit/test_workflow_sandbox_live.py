"""Isolated `provider_generate` walks with `WorkflowContext.dry_run=True`.

Product sandbox try-its no longer use this path — they submit a real
`GenerationJob`. These tests keep `dry_run` so the node can be exercised
without a job row, a ledger, or Celery.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.router import Candidate, RoutingDecision
from app.models import GenerationJob, ProviderAttempt, User
from app.models.base import new_id
from app.models.enums import Operation, ProviderKind, QualityTier
from app.providers.base import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderCapability,
    ProviderReference,
)
from app.workflows.configs import ProviderGenerateConfig
from app.workflows.nodes import execute_provider_generate
from app.workflows.types import WorkflowContext


class _ScriptedProvider(GenerationProvider):
    name = "live_mock"
    kind = "commercial_api"

    def __init__(self, results: list[GenerationResult]) -> None:
        self._results = list(results)
        self.submit_calls = 0
        self.poll_calls = 0
        self.submitted_requests: list[GenerationRequest] = []

    def submit(self, request: GenerationRequest) -> GenerationResult:
        self.submit_calls += 1
        self.submitted_requests.append(request)
        return self._results.pop(0)

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        self.poll_calls += 1
        return self._results.pop(0)


def _sandbox_ctx(
    db: Session,
    author: User,
    *,
    operation: Operation,
    params: dict[str, object] | None = None,
) -> WorkflowContext:
    payload = {"prompt": "雨后的东京街头", **(params or {})}
    job = GenerationJob(
        id=new_id("dry"),
        user_id=author.id,
        operation=operation.value,
        request_json=payload,
        quality_tier=QualityTier.STANDARD.value,
        status="created",
        quoted_credits=0,
        reserved_credits=0,
        idempotency_key=new_id("idk"),
        estimated_seconds=0,
    )
    return WorkflowContext(
        session=db,
        job=job,
        prompt=str(payload["prompt"]),
        params=payload,
        dry_run=True,
        live_provider=True,
    )


def _decision_for(
    provider: GenerationProvider,
    *,
    operation: Operation,
    typical_latency_ms: int = 1_000,
    resolutions: frozenset[str] | None = None,
) -> RoutingDecision:
    capability = ProviderCapability(
        name="live_mock",
        kind=ProviderKind.COMMERCIAL_API,
        operations=frozenset({operation.value}),
        tiers=frozenset({QualityTier.STANDARD.value}),
        quality_prior=0.9,
        typical_latency_ms=typical_latency_ms,
        unit_cost_micro_usd=10000,
        model_or_workflow="mock",
        provider_factory=lambda: provider,
        resolutions=resolutions,
    )
    return RoutingDecision(
        selected=Candidate(provider="live_mock"),
        catalog={"live_mock": capability},
    )


@pytest.fixture
def _presign(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.workflows.nodes.s3.presign_get",
        lambda key, **_kwargs: f"https://cdn.test/{key}",
    )


def _attempt_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(ProviderAttempt)) or 0


def _stub_references(monkeypatch: pytest.MonkeyPatch, media_type: str) -> None:
    monkeypatch.setattr(
        "app.workflows.nodes.media_service.provider_references_for",
        lambda *_args, **_kwargs: [
            ProviderReference(object_key="sandbox/ref.bin", media_type=media_type)
        ],
    )


@pytest.mark.usefixtures("_presign")
def test_live_sandbox_image_returns_preview_url(db: Session, author: User) -> None:
    provider = _ScriptedProvider(
        [GenerationResult(succeeded=True, object_key="sandbox/out.png", mime_type="image/png")]
    )
    ctx = _sandbox_ctx(db, author, operation=Operation.TEXT_TO_IMAGE)
    ctx.state["decision"] = _decision_for(provider, operation=Operation.TEXT_TO_IMAGE)
    before = _attempt_count(db)
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "succeeded"
    assert ctx.state["_preview_url"] == "https://cdn.test/sandbox/out.png"
    assert ctx.state["_preview_mime_type"] == "image/png"
    assert provider.submit_calls == 1
    assert provider.poll_calls == 0
    assert _attempt_count(db) == before


@pytest.mark.usefixtures("_presign")
def test_live_sandbox_image_to_image_with_reference_returns_preview_url(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_references(monkeypatch, "image")
    provider = _ScriptedProvider(
        [GenerationResult(succeeded=True, object_key="sandbox/edit.png", mime_type="image/png")]
    )
    ctx = _sandbox_ctx(
        db,
        author,
        operation=Operation.IMAGE_TO_IMAGE,
        params={"reference_asset_ids": ["ast_ref"]},
    )
    ctx.state["decision"] = _decision_for(provider, operation=Operation.IMAGE_TO_IMAGE)
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "succeeded"
    assert ctx.state["_preview_mime_type"] == "image/png"
    assert provider.submit_calls == 1


@pytest.mark.usefixtures("_presign")
def test_live_sandbox_image_to_image_without_reference_still_succeeds(
    db: Session, author: User
) -> None:
    """`image_to_image` shares one workflow graph with `text_to_image` — the
    prompt is mandatory, a reference image is only optional extra context
    (see `workflow_templates_service.canonical_operation`). Unlike the video
    reference ops, it must not hit `_REFERENCE_REQUIRED`."""
    provider = _ScriptedProvider(
        [GenerationResult(succeeded=True, object_key="sandbox/edit.png", mime_type="image/png")]
    )
    ctx = _sandbox_ctx(db, author, operation=Operation.IMAGE_TO_IMAGE)
    ctx.state["decision"] = _decision_for(provider, operation=Operation.IMAGE_TO_IMAGE)
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "succeeded"
    assert provider.submit_calls == 1


@pytest.mark.usefixtures("_presign")
def test_live_sandbox_audio_returns_preview_url(db: Session, author: User) -> None:
    provider = _ScriptedProvider(
        [GenerationResult(succeeded=True, object_key="sandbox/out.mp3", mime_type="audio/mpeg")]
    )
    ctx = _sandbox_ctx(db, author, operation=Operation.AUDIO_GENERATION)
    ctx.state["decision"] = _decision_for(provider, operation=Operation.AUDIO_GENERATION)
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "succeeded"
    assert ctx.state["_preview_url"] == "https://cdn.test/sandbox/out.mp3"
    assert ctx.state["_preview_mime_type"] == "audio/mpeg"


@pytest.mark.usefixtures("_presign")
@pytest.mark.parametrize(
    ("operation", "media_type"),
    [
        (Operation.TEXT_TO_VIDEO, None),
        (Operation.IMAGE_TO_VIDEO, "image"),
        (Operation.VIDEO_TO_VIDEO, "video"),
    ],
)
def test_live_sandbox_video_polls_pending_then_succeeds(
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
    operation: Operation,
    media_type: str | None,
) -> None:
    monkeypatch.setattr("app.workflows.nodes.time.sleep", lambda _seconds: None)
    if media_type:
        _stub_references(monkeypatch, media_type)
    provider = _ScriptedProvider(
        [
            GenerationResult(succeeded=False, pending=True, external_task_id="ext_1"),
            GenerationResult(succeeded=False, pending=True, external_task_id="ext_1"),
            GenerationResult(succeeded=True, object_key="sandbox/out.mp4", mime_type="video/mp4"),
        ]
    )
    params: dict[str, object] = {"duration_seconds": 4}
    if media_type:
        params["reference_asset_ids"] = ["ast_ref"]
    ctx = _sandbox_ctx(db, author, operation=operation, params=params)
    ctx.state["decision"] = _decision_for(provider, operation=operation, typical_latency_ms=8_000)
    before = _attempt_count(db)
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "succeeded"
    assert provider.poll_calls == 2
    assert ctx.state["_preview_url"] == "https://cdn.test/sandbox/out.mp4"
    assert ctx.state["_preview_mime_type"] == "video/mp4"
    assert result.suspend is not True
    assert _attempt_count(db) == before


def test_live_sandbox_video_timeout_returns_error_detail(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        now = clock["t"]
        clock["t"] += 1.0
        return now

    monkeypatch.setattr("app.workflows.nodes.time.monotonic", fake_monotonic)
    monkeypatch.setattr("app.workflows.nodes.time.sleep", lambda _seconds: None)
    provider = _ScriptedProvider(
        [
            GenerationResult(succeeded=False, pending=True, external_task_id="ext_1"),
            GenerationResult(succeeded=False, pending=True, external_task_id="ext_1"),
        ]
    )
    ctx = _sandbox_ctx(db, author, operation=Operation.TEXT_TO_VIDEO)
    ctx.state["decision"] = _decision_for(
        provider, operation=Operation.TEXT_TO_VIDEO, typical_latency_ms=1
    )
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "failed"
    assert ctx.state["failure_code"] == "PROVIDER_TIMEOUT"
    assert ctx.state["error_detail"]
    assert "timed out" in ctx.state["error_detail"]
    assert ctx.state["failure_message"] == "生成失败，积分已退回。"


def test_live_sandbox_poll_budget_uses_endpoint_timeout_not_typical_latency(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        now = clock["t"]
        clock["t"] += 1.0
        return now

    monkeypatch.setattr("app.workflows.nodes.time.monotonic", fake_monotonic)
    monkeypatch.setattr("app.workflows.nodes.time.sleep", lambda _seconds: None)
    provider = _ScriptedProvider(
        [
            GenerationResult(succeeded=False, pending=True, external_task_id="ext_1"),
            GenerationResult(succeeded=False, pending=True, external_task_id="ext_1"),
        ]
    )
    provider._creds = SimpleNamespace(timeout_s=0.001)  # type: ignore[attr-defined]
    ctx = _sandbox_ctx(db, author, operation=Operation.TEXT_TO_VIDEO)
    ctx.state["decision"] = _decision_for(
        provider, operation=Operation.TEXT_TO_VIDEO, typical_latency_ms=90_000
    )
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "failed"
    assert ctx.state["failure_code"] == "PROVIDER_TIMEOUT"


@pytest.mark.parametrize(
    "operation",
    [Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO],
)
def test_live_sandbox_reference_ops_fail_without_a_reference(
    db: Session, author: User, operation: Operation
) -> None:
    provider = _ScriptedProvider([])
    ctx = _sandbox_ctx(db, author, operation=operation)
    ctx.state["decision"] = _decision_for(provider, operation=operation)
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "failed"
    assert ctx.state["failure_code"] == "MISSING_REFERENCE"
    assert "reference_asset_ids" in ctx.state["error_detail"]
    assert provider.submit_calls == 0


def test_live_sandbox_video_resolves_a_client_tier_to_the_models_own_spelling(
    db: Session, author: User
) -> None:
    """`video_options.resolution` is a client-facing tier token (`"720p"`),
    never a vendor's own literal. This mock's `resolutions` mimics MiniMax
    H3's real profile (`768P`/`2K`, no true `720p`) — the provider must
    receive `"768P"`, or a real adapter's own `resolution not in profile
    .resolutions` check would reject it outright."""
    provider = _ScriptedProvider(
        [GenerationResult(succeeded=True, object_key="sandbox/out.mp4", mime_type="video/mp4")]
    )
    ctx = _sandbox_ctx(
        db,
        author,
        operation=Operation.TEXT_TO_VIDEO,
        params={
            "duration_seconds": 4,
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )
    ctx.state["decision"] = _decision_for(
        provider,
        operation=Operation.TEXT_TO_VIDEO,
        resolutions=frozenset({"768P", "2K"}),
    )
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "succeeded"
    assert provider.submit_calls == 1
    assert provider.submitted_requests[0].resolution == "768P"


def test_live_sandbox_video_adapts_1080p_ceiling_down_to_h3_768p(db: Session, author: User) -> None:
    """H3 has no 1080p. The user's ceiling must become 720p/`768P`, never 2K."""
    provider = _ScriptedProvider(
        [GenerationResult(succeeded=True, object_key="sandbox/out.mp4", mime_type="video/mp4")]
    )
    ctx = _sandbox_ctx(
        db,
        author,
        operation=Operation.TEXT_TO_VIDEO,
        params={
            "duration_seconds": 4,
            "video_options": {"resolution": "1080p", "reference_mode": "input_references"},
        },
    )
    ctx.state["decision"] = _decision_for(
        provider,
        operation=Operation.TEXT_TO_VIDEO,
        resolutions=frozenset({"768P", "2K"}),
    )
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "succeeded"
    assert provider.submitted_requests[0].resolution == "768P"


def test_live_sandbox_video_remix_omits_resolution_end_to_end(db: Session, author: User) -> None:
    """A video remix never sends `video_options.resolution` at all (see
    `VideoGenerationOptions`'s own docstring) — adaptation must pass that
    straight through as `None`, letting the provider adapter apply its own
    default rather than inventing a tier."""
    provider = _ScriptedProvider(
        [GenerationResult(succeeded=True, object_key="sandbox/out.mp4", mime_type="video/mp4")]
    )
    ctx = _sandbox_ctx(
        db,
        author,
        operation=Operation.TEXT_TO_VIDEO,
        params={
            "duration_seconds": 4,
            "video_options": {"reference_mode": "input_references"},
        },
    )
    ctx.state["decision"] = _decision_for(
        provider,
        operation=Operation.TEXT_TO_VIDEO,
        resolutions=frozenset({"768P", "2K"}),
    )
    result = execute_provider_generate(ctx, ProviderGenerateConfig())
    assert result.port == "succeeded"
    assert provider.submitted_requests[0].resolution is None
