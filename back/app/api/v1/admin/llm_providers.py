"""Model provider directory: readable CRUD over the versioned `llm_providers`
config section, with runtime status merged in and secrets never echoed back.

Deliberately not the generic `/admin/config/{key}` editor: that endpoint
would round-trip every `api_key` in plaintext and shows nothing about which
endpoint is currently overloaded or breaker-tripped. This router adds that
readability on top while still writing through `config_service.set_value`,
so versioning, rollback and audit logging stay exactly as they are for every
other config section.

The console renders a flat primary/backup list from `endpoints`. Reliability
knobs (circuit breaker, retries) live in the `llm_reliability` config-centre
section instead of here — see
`app/platform_config/schemas.py:LlmReliabilityConfig`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.api.schemas.admin import (
    DangerousAction,
    LlmProviderEndpointUpsertRequest,
    LlmProviderEndpointView,
    LlmProviderPoolView,
    MediaCapabilityView,
)
from app.api.v1.admin.deps import (
    Admin,
    AdminDangerous,
    AdminRead,
    AdminWrite,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.errors import NotFound
from app.llm import failover
from app.platform_config import service as config_service
from app.platform_config.schemas import (
    LlmProviderConfig,
    LlmProviderEndpoint,
    MediaCapability,
)

router = APIRouter(tags=["admin:llm-providers"])

CONFIG_KEY = "llm_providers"


@router.get("/llm-providers", response_model=LlmProviderPoolView)
def list_llm_providers(session: DbSession, user: Viewer, _: AdminRead) -> LlmProviderPoolView:
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    return _pool_view(config)


@router.put("/llm-providers/{endpoint_id}", response_model=LlmProviderPoolView)
def upsert_llm_provider(
    endpoint_id: str,
    payload: LlmProviderEndpointUpsertRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> LlmProviderPoolView:
    """Creates or replaces one endpoint. `api_key=None` keeps the stored secret.

    Demotion happens automatically rather than being rejected, because each
    `kind` has exactly one primary node by definition: saving with
    `role="primary"` demotes whichever other endpoint of the same `kind`
    currently holds it. The demotion is recorded on the same audit entry so
    it stays traceable.
    """
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    existing = config.endpoints.get(endpoint_id)
    api_key = existing.api_key if payload.api_key is None and existing else (payload.api_key or "")

    demoted_ids: list[str] = []
    if payload.role == "primary":
        for other_id, other in config.endpoints.items():
            if other_id != endpoint_id and other.kind == payload.kind and other.role == "primary":
                other.role = "backup"
                demoted_ids.append(other_id)

    config.endpoints[endpoint_id] = LlmProviderEndpoint(
        name=payload.name,
        base_url=payload.base_url,
        api_key=api_key,
        kind=payload.kind,
        models=payload.models if payload.kind == "general" else [],
        role=payload.role,
        backup_order=payload.backup_order,
        capabilities={
            tag: MediaCapability(model=cap.model, enabled=cap.enabled)
            for tag, cap in payload.capabilities.items()
        }
        if payload.kind == "media"
        else {},
        max_concurrency=payload.max_concurrency,
        timeout_ms=payload.timeout_ms,
        enabled=payload.enabled,
    )
    row = _save(session, config, user_id=user.id, note=f"更新端点 {endpoint_id}")
    audit.record(
        session,
        actor=user,
        action="llm_provider.upsert",
        target_type="llm_provider_endpoint",
        target_id=endpoint_id,
        after={
            "name": payload.name,
            "base_url": payload.base_url,
            "enabled": payload.enabled,
            "kind": payload.kind,
            "role": payload.role,
            "capabilities": sorted(payload.capabilities) if payload.kind == "media" else [],
            "demoted_endpoint_ids": demoted_ids,
        },
        request=request,
    )
    session.commit()
    updated = LlmProviderConfig.model_validate(row.value_json)
    return _pool_view(updated, demoted_endpoint_ids=demoted_ids)


@router.post("/llm-providers/{endpoint_id}/remove", response_model=LlmProviderPoolView)
def remove_llm_provider(
    endpoint_id: str,
    payload: DangerousAction,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> LlmProviderPoolView:
    """Removing the endpoint another agent's traffic depends on is the kind of
    mistake that stops generations from completing, hence the confirmation."""
    require_confirmation(payload.confirm)
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    if endpoint_id not in config.endpoints:
        raise NotFound(f"端点 {endpoint_id} 不存在。")
    removed = config.endpoints.pop(endpoint_id)
    row = _save(session, config, user_id=user.id, note=f"移除端点 {endpoint_id}: {payload.reason}")
    audit.record(
        session,
        actor=user,
        action="llm_provider.remove",
        target_type="llm_provider_endpoint",
        target_id=endpoint_id,
        before={"name": removed.name, "base_url": removed.base_url, "kind": removed.kind},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _pool_view(LlmProviderConfig.model_validate(row.value_json))


def _save(session, config: LlmProviderConfig, *, user_id: str, note: str):  # type: ignore[no-untyped-def]
    return config_service.set_value(
        session, CONFIG_KEY, config.model_dump(mode="json"), actor_user_id=user_id, note=note
    )


def _pool_view(
    config: LlmProviderConfig, *, demoted_endpoint_ids: list[str] | None = None
) -> LlmProviderPoolView:
    endpoints = [
        _endpoint_view(endpoint_id, endpoint) for endpoint_id, endpoint in config.endpoints.items()
    ]
    endpoints.sort(key=lambda item: (item.role != "primary", item.backup_order, item.id))
    return LlmProviderPoolView(
        endpoints=endpoints,
        categories=[],
        demoted_endpoint_ids=demoted_endpoint_ids or [],
    )


def _endpoint_view(endpoint_id: str, endpoint: LlmProviderEndpoint) -> LlmProviderEndpointView:
    status = failover.runtime_status(endpoint_id)
    return LlmProviderEndpointView(
        id=endpoint_id,
        name=endpoint.name,
        base_url=endpoint.base_url,
        api_key_configured=bool(endpoint.api_key),
        api_key_preview=_mask(endpoint.api_key),
        kind=endpoint.kind,
        models=endpoint.models,
        capabilities={
            tag: MediaCapabilityView(model=cap.model, enabled=cap.enabled)
            for tag, cap in endpoint.capabilities.items()
        },
        max_concurrency=endpoint.max_concurrency,
        role=endpoint.role,
        backup_order=endpoint.backup_order,
        timeout_ms=endpoint.timeout_ms,
        enabled=endpoint.enabled,
        concurrency_in_use=status.concurrency_in_use,
        circuit_breaker_open=status.circuit_breaker_open,
        recent_attempts=status.recent_attempts,
        recent_success_rate=status.recent_success_rate,
    )


def _mask(api_key: str) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "••••"
    return f"{api_key[:3]}···{api_key[-4:]}"
