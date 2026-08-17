"""`jobs_service.submit` pins the `(operation, asset_kind)`-specific workflow
template when one is published — mirrors
`test_workflow_templates_service.py`'s resolution-order coverage, but through
the actual submission path rather than calling `get_active` directly.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.credits.pricing import quote as compute_quote
from app.domain.jobs import service as jobs_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import User
from app.models.base import new_id
from app.models.enums import ImageAssetKind, Operation, QualityTier
from app.workflows.defaults import default_graph, image_asset_graph


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    db.flush()
    return author


def _submit(db: Session, user: User, **params: object) -> str | None:
    result = jobs_service.submit(
        db,
        user_id=user.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "神秘女侦探", "aspect_ratio": "16:9", **params},
        idempotency_key=new_id("idk"),
    )
    return result.job.workflow_template_id


def test_submit_pins_the_generic_template_when_no_asset_kind_is_given(
    db: Session, funded: User
) -> None:
    generic = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="通用",
        graph_json=default_graph(db),
        actor_user_id=funded.id,
        reason="通用图片工作流",
    )
    db.commit()

    template_id = _submit(db, funded)
    assert template_id == generic.id


def test_submit_prefers_the_asset_kind_specific_template_over_the_generic_one(
    db: Session, funded: User
) -> None:
    generic = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="通用",
        graph_json=default_graph(db),
        actor_user_id=funded.id,
        reason="通用图片工作流",
    )
    character_kind = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="角色图",
        graph_json=image_asset_graph(db, ImageAssetKind.CHARACTER.value),
        actor_user_id=funded.id,
        reason="角色图工作流",
        asset_kind=ImageAssetKind.CHARACTER.value,
    )
    db.commit()

    template_id = _submit(db, funded, asset_kind=ImageAssetKind.CHARACTER.value)
    assert template_id == character_kind.id
    assert template_id != generic.id


def test_submit_falls_back_to_the_generic_template_for_an_unseeded_asset_kind(
    db: Session, funded: User
) -> None:
    generic = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="通用",
        graph_json=default_graph(db),
        actor_user_id=funded.id,
        reason="通用图片工作流",
    )
    db.commit()

    # No `cover`-specific template was ever published — the job must still
    # resolve to *some* template instead of running unpinned.
    template_id = _submit(db, funded, asset_kind=ImageAssetKind.COVER.value)
    assert template_id == generic.id


def test_submit_treats_the_general_asset_kind_the_same_as_none(db: Session, funded: User) -> None:
    generic = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="通用",
        graph_json=default_graph(db),
        actor_user_id=funded.id,
        reason="通用图片工作流",
    )
    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="角色图",
        graph_json=image_asset_graph(db, ImageAssetKind.CHARACTER.value),
        actor_user_id=funded.id,
        reason="角色图工作流",
        asset_kind=ImageAssetKind.CHARACTER.value,
    )
    db.commit()

    template_id = _submit(db, funded, asset_kind=ImageAssetKind.GENERAL.value)
    assert template_id == generic.id


def test_submit_leaves_the_job_unpinned_when_nothing_has_been_published(
    db: Session, funded: User
) -> None:
    assert _submit(db, funded) is None


# --------------------------------------------------------------------------
# `character_output_count` / multi-view quoting
# --------------------------------------------------------------------------


def test_character_output_count_is_one_without_character_views() -> None:
    assert jobs_service.character_output_count(asset_kind=None, character_views=None) == 1
    assert (
        jobs_service.character_output_count(
            asset_kind=ImageAssetKind.SCENE.value, character_views=None
        )
        == 1
    )


def test_character_output_count_is_one_for_a_single_view_character_job() -> None:
    assert (
        jobs_service.character_output_count(
            asset_kind=ImageAssetKind.CHARACTER.value, character_views=["front"]
        )
        == 1
    )


def test_character_output_count_matches_the_number_of_requested_views() -> None:
    assert (
        jobs_service.character_output_count(
            asset_kind=ImageAssetKind.CHARACTER.value, character_views=["side", "back"]
        )
        == 2
    )


def test_character_views_ignored_for_a_non_character_asset_kind() -> None:
    """`character_views` only ever has entries when `asset_kind == character`
    (`GenerationParams`'s own validator enforces this), but the helper stays
    defensive about it regardless."""
    assert (
        jobs_service.character_output_count(
            asset_kind=ImageAssetKind.SCENE.value, character_views=["front", "side"]
        )
        == 1
    )


def test_submit_reserves_credits_for_every_requested_character_view(
    db: Session, funded: User
) -> None:
    result = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={
            "prompt": "神秘女侦探",
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": ["side", "back"],
        },
        idempotency_key=new_id("idk"),
    )
    baseline = compute_quote(operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    assert result.quote.credits == baseline.credits * 2
