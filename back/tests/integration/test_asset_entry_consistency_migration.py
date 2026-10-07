"""P3-2 migration (`skill_asset_entries.consistency_json`) round trip, run
live on the test DB inside a rolled-back transaction (Postgres DDL is
transactional), plus the admin config API for `asset_consistency`."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from app.models import User
from app.platform_config.schemas import DEFAULT_CONFIGS
from tests.conftest import admin_header


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261008_1100_asset_entry_consistency.py"
    )
    spec = importlib.util.spec_from_file_location("asset_entry_consistency", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_follows_the_panorama_entry() -> None:
    assert _migration().down_revision == "3e9a7c5d1f20"


def _columns(connection) -> set[str]:  # type: ignore[no-untyped-def]
    return {column["name"] for column in inspect(connection).get_columns("skill_asset_entries")}


def test_upgrade_and_downgrade_toggle_the_column(engine: Engine) -> None:
    migration = _migration()
    connection = engine.connect()
    transaction = connection.begin()
    try:
        assert "consistency_json" in _columns(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()
        assert "consistency_json" not in _columns(connection)
        with Operations.context(context):
            migration.upgrade()
        assert "consistency_json" in _columns(connection)
    finally:
        transaction.rollback()
        connection.close()


def _put(client: TestClient, admin: User, value: dict):  # type: ignore[no-untyped-def]
    return client.put(
        "/v1/admin/config/asset_consistency",
        json={"value": value, "note": "影子期"},
        headers=admin_header(admin),
    )


def test_the_section_is_editable_through_the_generic_config_api(
    client: TestClient, db: Session, admin: User
) -> None:
    current = client.get("/v1/admin/config/asset_consistency", headers=admin_header(admin))
    assert current.status_code == 200
    assert current.json()["value"]["mode"] == "off"

    value = copy.deepcopy(DEFAULT_CONFIGS["asset_consistency"])
    value.update(mode="shadow", thresholds={"character": {"*": 70}})
    saved = _put(client, admin, value)
    assert saved.status_code == 200, saved.text
    assert saved.json()["value"]["mode"] == "shadow"


def test_an_unknown_entry_type_threshold_is_a_422(client: TestClient, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["asset_consistency"])
    value["thresholds"] = {"character": {"master": 60}}
    response = _put(client, admin, value)
    assert response.status_code == 422
    assert "master" in response.text
