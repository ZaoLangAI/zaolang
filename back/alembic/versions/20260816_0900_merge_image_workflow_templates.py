"""merge text_to_image/image_to_image workflow templates

`text_to_image` and `image_to_image` now share exactly one workflow-template
family, keyed under `text_to_image` — see
`app.domain.workflow_templates.service.canonical_operation`. Whichever of the
two a job ends up as is a runtime detail (whether a reference image was
attached), not a different generation pipeline, so an operator should never
have had to configure/publish the same graph twice.

This is a one-time cleanup of whatever `image_to_image` rows a database
already accumulated under the old per-operation seeding (`ensure_default_
templates` used to seed the image family twice, once per operation): for
every `asset_kind` bucket, an active `image_to_image` row is folded into
`text_to_image` — adopted as-is (rewritten in place) when `text_to_image` has
no active row of its own for that bucket (preserving any hand customization
that only ever happened on the `image_to_image` tab), otherwise simply
deactivated since `text_to_image` already covers it and the two were seeded
identically. Historical (non-active) versions are left alone; they are just
history and nothing ever queries across operations by version.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4c8e1f6a3d9"
down_revision: str | None = "a6b3d0f9c2e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEXT_TO_IMAGE = "text_to_image"
_IMAGE_TO_IMAGE = "image_to_image"


def upgrade() -> None:
    bind = op.get_bind()
    image_to_image_rows = (
        bind.execute(
            sa.text(
                "SELECT id, asset_kind FROM generation_workflow_templates "
                "WHERE operation = :op AND is_active = true"
            ).bindparams(op=_IMAGE_TO_IMAGE)
        )
        .mappings()
        .all()
    )

    for row in image_to_image_rows:
        asset_kind = row["asset_kind"]
        text_to_image_active = bind.execute(
            sa.text(
                "SELECT id FROM generation_workflow_templates "
                "WHERE operation = :op AND is_active = true "
                "AND asset_kind IS NOT DISTINCT FROM :asset_kind"
            ).bindparams(op=_TEXT_TO_IMAGE, asset_kind=asset_kind)
        ).first()

        if text_to_image_active is None:
            # Only `image_to_image` ever had this bucket configured — adopt
            # it as the canonical row instead of losing the customization.
            bind.execute(
                sa.text(
                    "UPDATE generation_workflow_templates SET operation = :op WHERE id = :id"
                ).bindparams(op=_TEXT_TO_IMAGE, id=row["id"])
            )
        else:
            # Both exist (the normal case: both were auto-seeded with the
            # same default graph) — `text_to_image` is now the only one ever
            # resolved, so retire the duplicate rather than leave it
            # confusingly "active" with no code path reading it.
            bind.execute(
                sa.text(
                    "UPDATE generation_workflow_templates SET is_active = false WHERE id = :id"
                ).bindparams(id=row["id"])
            )


def downgrade() -> None:
    # Which `image_to_image` rows were folded vs. merely deactivated is not
    # recorded anywhere, so there is nothing sound to restore — the merge
    # itself (`canonical_operation`) is the real revert target.
    pass
