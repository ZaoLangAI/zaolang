"""The back-office security boundary.

Everything here is about what must *not* be possible: reaching `/v1/admin` with
a consumer session, acting above your rank, or taking an irreversible action
without confirming it and saying why.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ADMIN_COOKIE_NAME
from app.models import AuditLog, User
from app.models.enums import UserRole, UserStatus
from app.security.tokens import issue_admin_token, issue_consumer_tokens
from tests.conftest import admin_header, auth_header, make_user

PASSWORD = "Password123!"


@pytest.fixture
def viewer(db: Session) -> User:
    return make_user(
        db,
        email="viewer@example.com",
        handle="viewer",
        display_name="观察者",
        roles=[UserRole.USER.value, UserRole.VIEWER.value],
    )


# --- session separation ---------------------------------------------------


def test_an_anonymous_caller_cannot_reach_the_back_office(client: TestClient) -> None:
    assert client.get("/v1/admin/health").status_code == 401


def test_a_consumer_token_is_rejected_even_for_an_admin_account(
    client: TestClient, admin: User
) -> None:
    """The two sessions are separate on purpose: an XSS that steals a consumer
    token must not also hand over the console."""
    response = client.get("/v1/admin/health", headers=auth_header(admin))
    assert response.status_code == 401


def test_an_admin_token_does_not_work_on_the_consumer_api(client: TestClient, admin: User) -> None:
    """The separation has to hold in both directions."""
    response = client.get("/v1/credits/balance", headers=admin_header(admin))
    assert response.status_code == 401


def test_an_admin_token_is_accepted_on_the_back_office(client: TestClient, admin: User) -> None:
    assert client.get("/v1/admin/health", headers=admin_header(admin)).status_code == 200


def test_a_plain_user_with_a_forged_admin_token_is_refused(
    client: TestClient, author: User
) -> None:
    """Holding a correctly signed admin token is not enough; the account still
    has to carry a back-office role."""
    token, _ = issue_admin_token(author.id, list(author.roles))
    response = client.get("/v1/admin/health", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_a_garbage_token_is_refused(client: TestClient) -> None:
    response = client.get("/v1/admin/health", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_a_suspended_admin_loses_access_immediately(
    client: TestClient, db: Session, admin: User
) -> None:
    """The check is on every request, not only at login, so revocation does not
    have to wait for a token to expire."""
    header = admin_header(admin)
    assert client.get("/v1/admin/health", headers=header).status_code == 200

    admin.status = UserStatus.SUSPENDED
    admin.suspended_reason = "调查中"
    db.flush()

    assert client.get("/v1/admin/health", headers=header).status_code == 403


# --- login ----------------------------------------------------------------


def test_login_issues_an_admin_cookie(client: TestClient, admin: User) -> None:
    response = client.post(
        "/v1/admin/auth/login", json={"email": admin.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    assert ADMIN_COOKIE_NAME in response.cookies


def test_the_admin_cookie_is_http_only(client: TestClient, admin: User) -> None:
    """A cookie readable from JavaScript would undo the point of separating the
    sessions."""
    response = client.post(
        "/v1/admin/auth/login", json={"email": admin.email, "password": PASSWORD}
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower()


def test_a_plain_user_cannot_log_into_the_back_office(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/admin/auth/login", json={"email": author.email, "password": PASSWORD}
    )
    assert response.status_code in (401, 403)


def test_a_wrong_password_is_refused(client: TestClient, admin: User) -> None:
    response = client.post(
        "/v1/admin/auth/login", json={"email": admin.email, "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_an_unknown_email_is_indistinguishable_from_a_wrong_password(
    client: TestClient, admin: User
) -> None:
    """Otherwise the login form becomes a way to enumerate admin accounts."""
    unknown = client.post(
        "/v1/admin/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    wrong = client.post("/v1/admin/auth/login", json={"email": admin.email, "password": "nope"})
    assert unknown.status_code == wrong.status_code
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]


def test_a_successful_login_is_audited(client: TestClient, db: Session, admin: User) -> None:
    client.post("/v1/admin/auth/login", json={"email": admin.email, "password": PASSWORD})
    entry = db.scalar(
        select(AuditLog).where(AuditLog.actor_user_id == admin.id, AuditLog.action == "admin.login")
    )
    assert entry is not None


def test_logout_clears_the_cookie(client: TestClient, admin: User) -> None:
    client.post("/v1/admin/auth/login", json={"email": admin.email, "password": PASSWORD})
    response = client.post("/v1/admin/auth/logout")
    assert response.status_code == 200
    assert not client.cookies.get(ADMIN_COOKIE_NAME)


def test_the_session_endpoint_reports_the_current_roles(client: TestClient, admin: User) -> None:
    response = client.get("/v1/admin/auth/me", headers=admin_header(admin))
    assert response.status_code == 200
    assert "admin" in response.json()["roles"]


# --- RBAC -----------------------------------------------------------------


def test_a_viewer_can_read(client: TestClient, viewer: User) -> None:
    assert client.get("/v1/admin/health", headers=admin_header(viewer)).status_code == 200


def test_a_viewer_cannot_decide_moderation(client: TestClient, viewer: User) -> None:
    response = client.post("/v1/admin/moderation/queue/mdr_1/claim", headers=admin_header(viewer))
    assert response.status_code == 403


def test_a_reviewer_cannot_adjust_credits(client: TestClient, reviewer: User, author: User) -> None:
    """Deciding content and moving money are different jobs."""
    response = client.post(
        f"/v1/admin/users/{author.id}/credits/adjust",
        json={"amount": 100, "reason": "补偿", "confirm": True},
        headers=admin_header(reviewer),
    )
    assert response.status_code == 403


def test_an_operator_cannot_change_platform_configuration(
    client: TestClient, operator: User
) -> None:
    response = client.put(
        "/v1/admin/config/routing_weights",
        json={
            "value": {"quality": 0.4, "latency": 0.2, "cost": 0.25, "reliability": 0.15},
            "reason": "调整",
        },
        headers=admin_header(operator),
    )
    assert response.status_code == 403


def test_an_operator_cannot_grant_roles(client: TestClient, operator: User, author: User) -> None:
    """Otherwise any operator could promote themselves to admin."""
    response = client.post(
        f"/v1/admin/users/{author.id}/roles",
        json={"roles": ["user", "admin"], "reason": "提权", "confirm": True},
        headers=admin_header(operator),
    )
    assert response.status_code == 403


def test_an_admin_can_change_platform_configuration(client: TestClient, admin: User) -> None:
    response = client.put(
        "/v1/admin/config/routing_weights",
        json={
            "value": {"quality": 0.5, "latency": 0.2, "cost": 0.2, "reliability": 0.1},
            "reason": "提高质量权重",
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 200


def test_a_higher_rank_satisfies_a_lower_requirement(client: TestClient, admin: User) -> None:
    """Ranks are ordered, so an admin does not need every role listed."""
    assert client.get("/v1/admin/users", headers=admin_header(admin)).status_code == 200


def test_an_admin_cannot_strip_their_own_admin_role(client: TestClient, admin: User) -> None:
    """Locking the last admin out of the console is not recoverable in-product."""
    response = client.post(
        f"/v1/admin/users/{admin.id}/roles",
        json={"roles": ["user"], "reason": "自降权限", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code in (403, 409, 422)


# --- dangerous actions ----------------------------------------------------


def test_adjusting_credits_without_confirmation_is_refused(
    client: TestClient, admin: User, author: User
) -> None:
    response = client.post(
        f"/v1/admin/users/{author.id}/credits/adjust",
        json={"amount": 100, "reason": "补偿一次故障", "confirm": False},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_adjusting_credits_without_a_reason_is_refused(
    client: TestClient, admin: User, author: User
) -> None:
    response = client.post(
        f"/v1/admin/users/{author.id}/credits/adjust",
        json={"amount": 100, "reason": "", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_a_confirmed_adjustment_with_a_reason_succeeds_and_is_audited(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    response = client.post(
        f"/v1/admin/users/{author.id}/credits/adjust",
        json={"amount": 100, "reason": "补偿一次供应商故障", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == "credit.adjust", AuditLog.target_id == author.id)
    )
    assert entry is not None
    assert entry.reason == "补偿一次供应商故障"
    assert entry.actor_user_id == admin.id


def test_suspending_a_user_requires_a_reason(client: TestClient, admin: User, author: User) -> None:
    response = client.post(
        f"/v1/admin/users/{author.id}/suspend",
        json={"reason": "", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_suspending_a_user_is_audited_with_the_reason(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    response = client.post(
        f"/v1/admin/users/{author.id}/suspend",
        json={"reason": "反复上传侵权内容", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.refresh(author)
    assert author.status == UserStatus.SUSPENDED

    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == "user.suspend", AuditLog.target_id == author.id)
    )
    assert entry is not None
    assert entry.reason == "反复上传侵权内容"


def test_tombstoning_a_work_requires_confirmation(client: TestClient, admin: User) -> None:
    response = client.post(
        "/v1/admin/works/wrk_anything/tombstone",
        json={"reason": "版权申诉成立", "confirm": False},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_seeding_is_refused_in_production(
    client: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reseeding wipes the business tables; it must not be reachable in prod
    even for an admin who confirms."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "production", raising=False)
    response = client.post(
        "/v1/admin/seed",
        json={"reset": True, "reason": "演示", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code in (403, 409, 422)


# --- workflow templates ----------------------------------------------------


def _sample_graph() -> dict:
    from app.workflows.defaults import default_graph

    return default_graph()


def test_a_viewer_can_list_node_types(client: TestClient, viewer: User) -> None:
    response = client.get("/v1/admin/workflow-templates/node-types", headers=admin_header(viewer))
    assert response.status_code == 200
    types = {item["type"] for item in response.json()["items"]}
    assert "safety_check" in types and "settle_success" in types


def test_an_operator_cannot_publish_a_workflow_template(client: TestClient, operator: User) -> None:
    """Wiring the real execution path of every future job is an admin
    decision, not an operator one."""
    response = client.put(
        "/v1/admin/workflow-templates/text_to_image",
        json={"name": "测试模板", "graph": _sample_graph(), "reason": "测试", "confirm": True},
        headers=admin_header(operator),
    )
    assert response.status_code == 403


def test_publishing_a_workflow_template_without_confirmation_is_refused(
    client: TestClient, admin: User
) -> None:
    response = client.put(
        "/v1/admin/workflow-templates/text_to_image",
        json={"name": "测试模板", "graph": _sample_graph(), "reason": "测试", "confirm": False},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_publishing_a_broken_graph_is_refused(client: TestClient, admin: User) -> None:
    """The structural validator (`app.workflows.graph.validate`) is enforced
    server-side, not just by the editor's own client-side check."""
    broken_graph = {
        "nodes": [{"id": "a", "type": "safety_check", "config": {}}],
        "edges": [],
    }
    response = client.put(
        "/v1/admin/workflow-templates/text_to_image",
        json={"name": "坏图", "graph": broken_graph, "reason": "测试", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_a_confirmed_publish_becomes_active_and_is_audited(
    client: TestClient, db: Session, admin: User
) -> None:
    response = client.put(
        "/v1/admin/workflow-templates/text_to_image",
        json={
            "name": "v2 测试模板",
            "graph": _sample_graph(),
            "reason": "回归测试",
            "confirm": True,
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_active"] is True

    active = client.get(
        "/v1/admin/workflow-templates/text_to_image", headers=admin_header(admin)
    ).json()
    assert active["id"] == body["id"]

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "workflow_template.publish", AuditLog.target_id == body["id"]
        )
    )
    assert entry is not None
    assert entry.reason == "回归测试"


def test_rolling_back_to_an_earlier_version_republishes_its_graph(
    client: TestClient, admin: User
) -> None:
    first = client.put(
        "/v1/admin/workflow-templates/text_to_video",
        json={"name": "v1", "graph": _sample_graph(), "reason": "首次发布", "confirm": True},
        headers=admin_header(admin),
    ).json()
    client.put(
        "/v1/admin/workflow-templates/text_to_video",
        json={"name": "v2", "graph": _sample_graph(), "reason": "第二次发布", "confirm": True},
        headers=admin_header(admin),
    )

    rollback = client.post(
        f"/v1/admin/workflow-templates/text_to_video/activate/{first['id']}",
        json={"reason": "回滚一次误发布", "confirm": True},
        headers=admin_header(admin),
    )
    assert rollback.status_code == 200, rollback.text
    body = rollback.json()
    assert body["name"] == "v1"
    assert body["version"] == 3
    assert body["is_active"] is True


def test_an_operator_can_dry_run_a_workflow_template(client: TestClient, operator: User) -> None:
    """A sandbox execution is not dangerous, so the operator rank suffices."""
    response = client.post(
        "/v1/admin/workflow-templates/text_to_image/dry-run",
        json={"prompt": "雨后的东京街头"},
        headers=admin_header(operator),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in ("succeeded", "failed")
    assert body["trace"]
    assert body["trace"][0]["node_type"] == "safety_check"


def test_a_viewer_cannot_dry_run_a_workflow_template(client: TestClient, viewer: User) -> None:
    response = client.post(
        "/v1/admin/workflow-templates/text_to_image/dry-run",
        json={"prompt": "雨后的东京街头"},
        headers=admin_header(viewer),
    )
    assert response.status_code == 403


# --- audit coverage -------------------------------------------------------


def test_a_read_only_request_does_not_create_an_audit_row(
    client: TestClient, db: Session, admin: User
) -> None:
    """A trail full of page views is a trail nobody reads."""
    before = len(list(db.scalars(select(AuditLog))))
    client.get("/v1/admin/users", headers=admin_header(admin))
    assert len(list(db.scalars(select(AuditLog)))) == before


def test_the_audit_row_records_who_and_what(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    client.post(
        f"/v1/admin/users/{author.id}/suspend",
        json={"reason": "测试留痕", "confirm": True},
        headers=admin_header(admin),
    )
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "user.suspend"))
    assert entry is not None
    assert entry.actor_user_id == admin.id
    assert entry.target_id == author.id
    assert entry.actor_roles and "admin" in entry.actor_roles


def test_audit_logs_are_readable_only_from_the_back_office(
    client: TestClient, author: User
) -> None:
    assert client.get("/v1/admin/audit-logs", headers=auth_header(author)).status_code == 401


def test_a_viewer_can_read_the_audit_trail(client: TestClient, viewer: User) -> None:
    """Oversight is a read: it must not require the power to change anything."""
    assert client.get("/v1/admin/audit-logs", headers=admin_header(viewer)).status_code == 200


# --- token misuse ---------------------------------------------------------


def test_a_consumer_refresh_token_cannot_be_used_as_an_admin_token(
    client: TestClient, admin: User
) -> None:
    _, refresh, _ = issue_consumer_tokens(admin.id, list(admin.roles))
    response = client.get("/v1/admin/health", headers={"Authorization": f"Bearer {refresh}"})
    assert response.status_code == 401


def test_an_admin_token_in_the_cookie_is_accepted(client: TestClient, admin: User) -> None:
    token, _ = issue_admin_token(admin.id, list(admin.roles))
    client.cookies.set(ADMIN_COOKIE_NAME, token)
    try:
        assert client.get("/v1/admin/health").status_code == 200
    finally:
        client.cookies.clear()


def test_a_consumer_token_in_the_admin_cookie_is_refused(client: TestClient, admin: User) -> None:
    access, _, _ = issue_consumer_tokens(admin.id, list(admin.roles))
    client.cookies.set(ADMIN_COOKIE_NAME, access)
    try:
        assert client.get("/v1/admin/health").status_code == 401
    finally:
        client.cookies.clear()
