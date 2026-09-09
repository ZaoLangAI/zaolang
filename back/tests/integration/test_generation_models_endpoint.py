"""`GET /v1/generation-jobs/models` — the C-end model picker behind
`GenerationParams.forced_model`, sourced live from `router.build_catalog`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_header
from tests.fake_provider_catalog import build_fake_catalog

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


def test_list_generation_models_returns_every_distinct_model_for_the_operation(
    client: TestClient, author
) -> None:
    """Both fake candidates serve `text_to_image` — the response must list
    each distinct `model_or_workflow` once, not once per provider."""
    response = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "text_to_image"},
        headers=auth_header(author),
    )

    assert response.status_code == 200, response.text
    models = {entry["model"] for entry in response.json()["models"]}
    assert models == {
        capability.model_or_workflow
        for capability in build_fake_catalog().values()
        if "text_to_image" in capability.operations
    }
    for entry in response.json()["models"]:
        assert entry["resolutions"] is None
        assert entry["default_resolution"] is None


def test_list_generation_models_excludes_a_model_that_does_not_serve_the_operation(
    client: TestClient, author
) -> None:
    """`fake_video_analysis` never serves `text_to_image` — it must not leak
    into this operation's list."""
    response = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "text_to_image"},
        headers=auth_header(author),
    )

    assert response.status_code == 200, response.text
    models = {entry["model"] for entry in response.json()["models"]}
    assert "fake-video-understanding-v1" not in models


def test_list_generation_models_rejects_an_operation_outside_the_forced_model_scope(
    client: TestClient, author
) -> None:
    """Mirrors `GenerationParams.forced_model`'s own restriction — the
    picker must not offer a model for an operation that would reject it.
    `video_analysis` (unlike `audio_generation`, see below) never accepts a
    `forced_model`."""
    response = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "video_analysis"},
        headers=auth_header(author),
    )

    assert response.status_code == 422


def test_list_generation_models_supports_audio_generation_and_reports_its_voices(
    client: TestClient, author
) -> None:
    """`audio_generation` is in the `forced_model` scope (unlike `video_
    analysis` above) — its own studio picker also needs each candidate's
    `voices` roster, sourced from `model_catalog.voices_for_model`."""
    response = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "audio_generation"},
        headers=auth_header(author),
    )

    assert response.status_code == 200, response.text
    models = {entry["model"]: entry for entry in response.json()["models"]}
    assert "paid-video-v3" in models
    # `fake_paid_api`'s model id is a video-catalogue name, not a real TTS
    # catalogue entry — no known voice roster for it.
    assert models["paid-video-v3"]["voices"] is None
    for entry in models.values():
        assert entry["resolutions"] is None
        assert entry["default_resolution"] is None


def test_list_generation_models_reports_the_real_voice_roster_for_a_catalogued_tts_model(
    client: TestClient, author, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate whose model id matches a real `model_catalog` TTS entry
    (case-insensitively) gets that entry's actual `voices` back — not
    `None` — so the studio can build a real `Select` from it."""
    from app.agents import router
    from app.models.enums import MediaGenerationKind, Operation, ProviderKind, QualityTier
    from app.providers.base import ProviderCapability
    from tests import fake_providers

    catalog = build_fake_catalog()
    catalog["fake_tts"] = ProviderCapability(
        name="fake_tts",
        kind=ProviderKind.COMMERCIAL_API,
        operations=frozenset({Operation.AUDIO_GENERATION}),
        tiers=frozenset({QualityTier.STANDARD}),
        quality_prior=0.8,
        typical_latency_ms=3_000,
        unit_cost_micro_usd=10_000,
        model_or_workflow="tts-1",
        provider_factory=lambda: fake_providers.get_provider("fake_paid_api"),
        generation_kind=MediaGenerationKind.CREATE,
    )
    monkeypatch.setattr(router, "build_catalog", lambda session: catalog)

    response = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "audio_generation"},
        headers=auth_header(author),
    )

    assert response.status_code == 200, response.text
    models = {entry["model"]: entry for entry in response.json()["models"]}
    assert models["tts-1"]["voices"] == [
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "onyx",
        "nova",
        "sage",
        "shimmer",
        "verse",
    ]


def test_list_generation_models_requires_authentication(client: TestClient) -> None:
    response = client.get("/v1/generation-jobs/models", params={"operation": "text_to_image"})
    assert response.status_code == 401


def test_list_generation_models_hides_edit_class_on_text_to_video(
    client: TestClient, author, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents import router
    from app.models.enums import MediaGenerationKind, Operation, ProviderKind, QualityTier
    from app.providers.base import ProviderCapability
    from tests import fake_providers

    catalog = build_fake_catalog()
    catalog["fake_edit"] = ProviderCapability(
        name="fake_edit",
        kind=ProviderKind.COMMERCIAL_API,
        operations=frozenset({Operation.TEXT_TO_VIDEO, Operation.VIDEO_TO_VIDEO}),
        tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD, QualityTier.CINEMATIC}),
        quality_prior=0.8,
        typical_latency_ms=10_000,
        unit_cost_micro_usd=100_000,
        model_or_workflow="fake-edit-v1",
        provider_factory=lambda: fake_providers.get_provider("fake_paid_api"),
        generation_kind=MediaGenerationKind.EDIT,
    )
    monkeypatch.setattr(router, "build_catalog", lambda session: catalog)

    hidden = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "text_to_video"},
        headers=auth_header(author),
    )
    assert hidden.status_code == 200, hidden.text
    hidden_models = {entry["model"] for entry in hidden.json()["models"]}
    assert "fake-edit-v1" not in hidden_models
    assert "paid-video-v3" in hidden_models

    shown = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "video_to_video"},
        headers=auth_header(author),
    )
    assert shown.status_code == 200, shown.text
    shown_models = {entry["model"] for entry in shown.json()["models"]}
    assert "fake-edit-v1" in shown_models
