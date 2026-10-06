"""AC-7 migration: the `entry_type_valid` CHECK gains `panorama`; the
downgrade drops panorama entries and restores the old CHECK. Run live on
the test DB inside a rolled-back transaction (Postgres DDL is
transactional)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.scenes import service as scenes_service
from app.models import Asset
from app.models.base import new_id
from app.models.enums import MediaType
from tests.conftest import make_user


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261008_1000_scene_panorama_entry.py"
    )
    spec = importlib.util.spec_from_file_location("scene_panorama_entry", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_follows_prop_assets() -> None:
    assert _migration().down_revision == "8c2f6d1b7e43"


def test_upgrade_and_downgrade_toggle_the_panorama_type(engine: Engine) -> None:
    migration = _migration()
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        owner = make_user(session, email="panorama-migration@example.com")
        scene = scenes_service.create_scene(
            session, user_id=owner.id, name="客厅", description=None, reference_asset_ids=[]
        )
        variant = av.find_default(scene.skill)

        def new_entry(entry_type: str) -> None:
            asset = Asset(
                owner_user_id=owner.id,
                object_key=f"test/{new_id('obj')}.png",
                media_type=MediaType.IMAGE,
                mime_type="image/png",
                size_bytes=1,
                checksum_sha256="d" * 64,
                role="generation_output",
            )
            session.add(asset)
            session.flush()
            av.add_entry(session, scene.skill, variant, asset_id=asset.id, entry_type=entry_type)

        new_entry("panorama")
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()
        remaining = connection.execute(
            text("SELECT count(*) FROM skill_asset_entries WHERE entry_type = 'panorama'")
        ).scalar_one()
        assert remaining == 0
        session.expire_all()
        with pytest.raises(IntegrityError), session.begin_nested():
            new_entry("panorama")

        with Operations.context(context):
            migration.upgrade()
        session.expire_all()
        new_entry("panorama")
    finally:
        session.close()
        transaction.rollback()
        connection.close()
