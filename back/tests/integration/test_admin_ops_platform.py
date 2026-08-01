"""Platform operations: config editing, diff and rollback, data ops, announcements."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Announcement, AuditLog, Notification, User
from app.platform_config import service as config_service
from app.platform_config.schemas import AgentConfig, FeatureFlags, RoutingWeights
from tests.conftest import admin_header

BALANCED = {"quality": 0.4, "latency": 0.2, "cost": 0.25, "reliability": 0.15}
QUALITY_FIRST = {"quality": 0.7, "latency": 0.1, "cost": 0.1, "reliability": 0.1}


def _put_weights(client: TestClient, admin: User, value: dict, note: str = "调整权重"):
    return client.put(
        "/v1/admin/config/routing_weights",
        json={"value": value, "note": note},
        headers=admin_header(admin),
    )


def _announcement(**overrides: object) -> dict:
    payload = {
        "kind": "notice",
        "title_zh": "计划内维护",
        "title_en": "Scheduled maintenance",
        "body_zh": "本周日 02:00-04:00 暂停生成服务。",
        "body_en": "Generation pauses Sunday 02:00-04:00.",
        "is_published": True,
        "broadcast": False,
    }
    payload.update(overrides)
    return payload


# --- reading configuration ------------------------------------------------


def test_every_known_key_is_listed(client: TestClient, admin: User) -> None:
    body = client.get("/v1/admin/config", headers=admin_header(admin)).json()
    assert {item["key"] for item in body["items"]} == set(config_service.all_keys())


def test_an_unset_key_reports_its_built_in_default(client: TestClient, admin: User) -> None:
    body = client.get("/v1/admin/config/routing_weights", headers=admin_header(admin)).json()
    assert body["version"] == 0
    assert body["value"]["quality"] == RoutingWeights().quality


def test_the_response_names_the_editable_fields(client: TestClient, admin: User) -> None:
    """The console renders its form from this list instead of hard-coding one."""
    body = client.get("/v1/admin/config/routing_weights", headers=admin_header(admin)).json()
    assert set(body["schema_fields"]) == set(RoutingWeights.model_fields)


def test_an_unknown_key_is_a_clean_404(client: TestClient, admin: User) -> None:
    response = client.get("/v1/admin/config/not_a_real_key", headers=admin_header(admin))
    assert response.status_code == 404


def test_a_reviewer_can_read_configuration(client: TestClient, reviewer: User) -> None:
    assert client.get("/v1/admin/config", headers=admin_header(reviewer)).status_code == 200


def test_a_reviewer_cannot_edit_configuration(client: TestClient, reviewer: User) -> None:
    assert _put_weights(client, reviewer, QUALITY_FIRST).status_code == 403


# --- editing --------------------------------------------------------------


def test_a_valid_change_takes_effect_immediately(
    client: TestClient, db: Session, admin: User
) -> None:
    assert _put_weights(client, admin, QUALITY_FIRST).status_code == 200
    assert config_service.get_typed(db, "routing_weights", RoutingWeights).quality == 0.7


def test_an_invalid_change_is_rejected_at_edit_time(
    client: TestClient, db: Session, admin: User
) -> None:
    """Catching it here means no worker ever has to defend against a malformed
    value."""
    response = _put_weights(
        client, admin, {"quality": 0.9, "latency": 0.9, "cost": 0.9, "reliability": 0.9}
    )
    assert response.status_code == 422
    assert config_service.get_typed(db, "routing_weights", RoutingWeights).quality == 0.4


def test_an_unknown_field_is_rejected_rather_than_silently_dropped(
    client: TestClient, admin: User
) -> None:
    """A typo that is quietly ignored looks like a change that did nothing."""
    response = _put_weights(client, admin, {**BALANCED, "qulaity": 0.4})
    assert response.status_code == 422


def test_a_rejected_change_leaves_no_version_behind(client: TestClient, admin: User) -> None:
    _put_weights(client, admin, {"quality": 2.0, "latency": 0, "cost": 0, "reliability": 0})
    body = client.get(
        "/v1/admin/config/routing_weights/history", headers=admin_header(admin)
    ).json()
    assert body["items"] == []


def test_a_change_is_audited_with_before_and_after(
    client: TestClient, db: Session, admin: User
) -> None:
    _put_weights(client, admin, QUALITY_FIRST, note="提高质量权重")

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "config.update", AuditLog.target_id == "routing_weights"
        )
    )
    assert entry is not None
    assert entry.reason == "提高质量权重"
    assert entry.after_json["quality"] == 0.7


# --- versioning, diff and rollback ---------------------------------------


def test_the_first_write_creates_version_one(client: TestClient, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    body = client.get(
        "/v1/admin/config/routing_weights/history", headers=admin_header(admin)
    ).json()
    assert [v["version"] for v in body["items"]] == [1]


def test_each_write_adds_a_version_and_only_one_stays_active(
    client: TestClient, admin: User
) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    _put_weights(client, admin, BALANCED)

    items = client.get(
        "/v1/admin/config/routing_weights/history", headers=admin_header(admin)
    ).json()["items"]
    assert [v["version"] for v in items] == [2, 1]
    assert [v["version"] for v in items if v["is_active"]] == [2]


def test_the_diff_shows_only_what_changed(client: TestClient, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    _put_weights(client, admin, {**QUALITY_FIRST, "quality": 0.6, "cost": 0.2})

    body = client.get(
        "/v1/admin/config/routing_weights/diff",
        params={"from_version": 1, "to_version": 2},
        headers=admin_header(admin),
    ).json()
    assert {entry["path"] for entry in body["entries"]} == {"quality", "cost"}


def test_the_diff_carries_both_sides(client: TestClient, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    _put_weights(client, admin, BALANCED)

    body = client.get(
        "/v1/admin/config/routing_weights/diff",
        params={"from_version": 1, "to_version": 2},
        headers=admin_header(admin),
    ).json()
    quality = next(e for e in body["entries"] if e["path"] == "quality")
    assert (quality["before"], quality["after"]) == (0.7, 0.4)


def test_version_zero_diffs_against_the_built_in_default(client: TestClient, admin: User) -> None:
    """The first edit still needs a readable "what did I change" view."""
    _put_weights(client, admin, QUALITY_FIRST)
    body = client.get(
        "/v1/admin/config/routing_weights/diff",
        params={"from_version": 0, "to_version": 1},
        headers=admin_header(admin),
    ).json()
    assert {e["path"] for e in body["entries"]} == {"quality", "latency", "cost", "reliability"}


def test_a_nested_change_reads_as_one_dotted_path(
    client: TestClient, db: Session, admin: User
) -> None:
    from app.platform_config.schemas import ProviderConfig

    first = config_service.get_typed(db, "providers", ProviderConfig).model_dump(mode="json")
    second = {**first}
    second["providers"] = {name: {**setting} for name, setting in first["providers"].items()}
    second["providers"]["fake_paid_api"]["enabled"] = False

    client.put(
        "/v1/admin/config/providers",
        json={"value": first, "note": "基线"},
        headers=admin_header(admin),
    )
    client.put(
        "/v1/admin/config/providers",
        json={"value": second, "note": "停用付费供应商"},
        headers=admin_header(admin),
    )

    body = client.get(
        "/v1/admin/config/providers/diff",
        params={"from_version": 1, "to_version": 2},
        headers=admin_header(admin),
    ).json()
    assert [e["path"] for e in body["entries"]] == ["providers.fake_paid_api.enabled"]


def test_rollback_restores_the_earlier_value(client: TestClient, db: Session, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    _put_weights(client, admin, BALANCED)

    response = client.post(
        "/v1/admin/config/routing_weights/rollback",
        json={"target_version": 1, "reason": "新权重导致成本失控", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text
    assert config_service.get_typed(db, "routing_weights", RoutingWeights).quality == 0.7


def test_rollback_moves_forward_rather_than_deleting_history(
    client: TestClient, admin: User
) -> None:
    """Rewriting history would destroy the record of what was live during an
    incident."""
    _put_weights(client, admin, QUALITY_FIRST)
    _put_weights(client, admin, BALANCED)
    client.post(
        "/v1/admin/config/routing_weights/rollback",
        json={"target_version": 1, "reason": "回滚验证", "confirm": True},
        headers=admin_header(admin),
    )

    body = client.get(
        "/v1/admin/config/routing_weights/history", headers=admin_header(admin)
    ).json()
    assert [v["version"] for v in body["items"]] == [3, 2, 1]


def test_rollback_requires_confirmation(client: TestClient, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    response = client.post(
        "/v1/admin/config/routing_weights/rollback",
        json={"target_version": 1, "reason": "回滚验证", "confirm": False},
        headers=admin_header(admin),
    )
    assert response.status_code in (409, 422)


def test_rollback_requires_a_reason(client: TestClient, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    response = client.post(
        "/v1/admin/config/routing_weights/rollback",
        json={"target_version": 1, "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_rolling_back_to_a_version_that_never_existed_is_refused(
    client: TestClient, admin: User
) -> None:
    response = client.post(
        "/v1/admin/config/routing_weights/rollback",
        json={"target_version": 99, "reason": "不存在的版本", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 404


def test_rollback_is_audited(client: TestClient, db: Session, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    _put_weights(client, admin, BALANCED)
    client.post(
        "/v1/admin/config/routing_weights/rollback",
        json={"target_version": 1, "reason": "成本失控", "confirm": True},
        headers=admin_header(admin),
    )
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "config.rollback"))
    assert entry is not None
    assert entry.reason == "成本失控"


# --- agent model binding --------------------------------------------------


def test_an_agent_model_can_be_switched_without_a_restart(
    client: TestClient, db: Session, admin: User
) -> None:
    payload = config_service.get_typed(db, "agents", AgentConfig).model_dump(mode="json")
    payload["bindings"]["planner"]["model"] = "doubao-seed-2-1-pro"

    response = client.put(
        "/v1/admin/config/agents",
        json={"value": payload, "note": "切换规划器模型"},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    updated = config_service.get_typed(db, "agents", AgentConfig)
    assert updated.bindings["planner"].model == "doubao-seed-2-1-pro"


def test_an_agent_cannot_be_left_without_a_model(client: TestClient, admin: User) -> None:
    response = client.put(
        "/v1/admin/config/agents",
        json={"value": {"bindings": {"planner": {"model": "kimi-k3"}}}, "note": "只留一个"},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


# --- feature flags --------------------------------------------------------


def test_feature_flags_are_listed_with_state_and_description(
    client: TestClient, admin: User
) -> None:
    items = client.get("/v1/admin/feature-flags", headers=admin_header(admin)).json()["items"]
    assert items
    assert all(isinstance(flag["enabled"], bool) and flag["description"] for flag in items)


def test_a_flag_can_be_turned_off(client: TestClient, db: Session, admin: User) -> None:
    value = config_service.get_typed(db, "feature_flags", FeatureFlags).model_dump(mode="json")
    value["royalties"] = False

    response = client.put(
        "/v1/admin/config/feature_flags",
        json={"value": value, "note": "临时关闭回流分成"},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text
    assert config_service.is_enabled(db, "royalties") is False


def test_a_rollout_percentage_outside_the_range_is_rejected(
    client: TestClient, db: Session, admin: User
) -> None:
    value = config_service.get_typed(db, "feature_flags", FeatureFlags).model_dump(mode="json")
    value["rollout_percentages"] = {"semantic_search": 140}

    response = client.put(
        "/v1/admin/config/feature_flags",
        json={"value": value, "note": "非法灰度"},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_a_greyscale_rollout_is_reported_per_flag(
    client: TestClient, db: Session, admin: User
) -> None:
    value = config_service.get_typed(db, "feature_flags", FeatureFlags).model_dump(mode="json")
    value["rollout_percentages"] = {"semantic_search": 25}
    client.put(
        "/v1/admin/config/feature_flags",
        json={"value": value, "note": "灰度 25%"},
        headers=admin_header(admin),
    )

    items = client.get("/v1/admin/feature-flags", headers=admin_header(admin)).json()["items"]
    flag = next(f for f in items if f["name"] == "semantic_search")
    assert flag["rollout_percent"] == 25


# --- data operations ------------------------------------------------------


def test_storage_usage_is_reported(client: TestClient, admin: User) -> None:
    response = client.get("/v1/admin/storage/usage", headers=admin_header(admin))
    assert response.status_code == 200, response.text
    assert response.json()["total_bytes"] >= 0


def test_lifecycle_rules_can_be_applied_and_read_back(client: TestClient, admin: User) -> None:
    response = client.post("/v1/admin/storage/lifecycle", headers=admin_header(admin))
    assert response.status_code == 200, response.text
    assert {r["ID"] for r in response.json()["lifecycle_rules"]} == {
        "expire-staging",
        "expire-exports",
    }


def test_applying_lifecycle_rules_is_audited(client: TestClient, db: Session, admin: User) -> None:
    client.post("/v1/admin/storage/lifecycle", headers=admin_header(admin))
    assert db.scalar(select(AuditLog).where(AuditLog.action == "storage.lifecycle")) is not None


def test_backups_can_be_listed(client: TestClient, admin: User) -> None:
    assert client.get("/v1/admin/backups", headers=admin_header(admin)).status_code == 200


def test_an_operator_cannot_trigger_a_backup(client: TestClient, operator: User) -> None:
    response = client.post(
        "/v1/admin/backups",
        json={"kind": "database", "reason": "手动备份", "confirm": True},
        headers=admin_header(operator),
    )
    assert response.status_code == 403


def test_seeding_requires_confirmation(client: TestClient, admin: User) -> None:
    response = client.post(
        "/v1/admin/seed",
        json={"reset": False, "reason": "重新灌入演示数据", "confirm": False},
        headers=admin_header(admin),
    )
    assert response.status_code in (409, 422)


# --- announcements --------------------------------------------------------


def test_an_announcement_is_stored(client: TestClient, db: Session, admin: User) -> None:
    response = client.post(
        "/v1/admin/announcements",
        json=_announcement(kind="maintenance"),
        headers=admin_header(admin),
    )
    assert response.status_code == 201, response.text
    assert db.scalar(select(Announcement).where(Announcement.kind == "maintenance")) is not None


def test_a_broadcast_reaches_active_users(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    client.post(
        "/v1/admin/announcements",
        json=_announcement(broadcast=True),
        headers=admin_header(admin),
    )
    assert db.scalar(select(Notification).where(Notification.user_id == author.id)) is not None


def test_an_unbroadcast_announcement_notifies_nobody(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    client.post("/v1/admin/announcements", json=_announcement(), headers=admin_header(admin))
    assert db.scalar(select(Notification).where(Notification.user_id == author.id)) is None


def test_an_unpublished_draft_is_never_broadcast(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    """A draft that fans out to every inbox is not a draft."""
    client.post(
        "/v1/admin/announcements",
        json=_announcement(is_published=False, broadcast=True),
        headers=admin_header(admin),
    )
    assert db.scalar(select(Notification).where(Notification.user_id == author.id)) is None


def test_announcements_can_be_listed(client: TestClient, admin: User) -> None:
    client.post("/v1/admin/announcements", json=_announcement(), headers=admin_header(admin))
    body = client.get("/v1/admin/announcements", headers=admin_header(admin)).json()
    assert body["items"]


def test_publishing_an_announcement_is_audited(
    client: TestClient, db: Session, admin: User
) -> None:
    client.post("/v1/admin/announcements", json=_announcement(), headers=admin_header(admin))
    assert db.scalar(select(AuditLog).where(AuditLog.action == "announcement.create")) is not None


def test_a_reviewer_cannot_publish_an_announcement(client: TestClient, reviewer: User) -> None:
    response = client.post(
        "/v1/admin/announcements", json=_announcement(), headers=admin_header(reviewer)
    )
    assert response.status_code == 403


# --- audit search and export ---------------------------------------------


def test_the_audit_trail_can_be_filtered_by_action(client: TestClient, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    client.post("/v1/admin/announcements", json=_announcement(), headers=admin_header(admin))

    body = client.get(
        "/v1/admin/audit-logs", params={"action": "config.update"}, headers=admin_header(admin)
    ).json()
    assert body["items"]
    assert {item["action"] for item in body["items"]} == {"config.update"}


def test_the_audit_trail_can_be_filtered_by_target(client: TestClient, admin: User) -> None:
    _put_weights(client, admin, QUALITY_FIRST)
    body = client.get(
        "/v1/admin/audit-logs",
        params={"target_type": "platform_config", "target_id": "routing_weights"},
        headers=admin_header(admin),
    ).json()
    assert body["items"]


def test_the_audit_trail_pages_with_a_cursor(client: TestClient, admin: User) -> None:
    for weights in (QUALITY_FIRST, BALANCED, QUALITY_FIRST):
        _put_weights(client, admin, weights)

    first = client.get(
        "/v1/admin/audit-logs", params={"limit": 2}, headers=admin_header(admin)
    ).json()
    assert first["has_more"] is True

    second = client.get(
        "/v1/admin/audit-logs",
        params={"limit": 2, "cursor": first["next_cursor"]},
        headers=admin_header(admin),
    ).json()
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})


def test_platform_operations_are_closed_to_anonymous_callers(client: TestClient) -> None:
    for path in ("/v1/admin/config", "/v1/admin/feature-flags", "/v1/admin/backups"):
        assert client.get(path).status_code == 401, path
