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


def test_list_generation_models_rejects_an_operation_outside_image_or_video_creation(
    client: TestClient, author
) -> None:
    """Mirrors `GenerationParams.forced_model`'s own restriction — the
    picker must not offer a model for an operation that would reject it."""
    response = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "audio_generation"},
        headers=auth_header(author),
    )

    assert response.status_code == 422


def test_list_generation_models_requires_authentication(client: TestClient) -> None:
    response = client.get("/v1/generation-jobs/models", params={"operation": "text_to_image"})
    assert response.status_code == 401
