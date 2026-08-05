"""LLM gateway failover pool: readable CRUD over the versioned `llm_providers`
config section, with runtime status merged in and secrets never echoed back.

Deliberately not the generic `/admin/config/{key}` editor: that endpoint
would round-trip every `api_key` in plaintext and shows nothing about which
endpoint is currently overloaded or breaker-tripped. This router adds that
readability on top while still writing through `config_service.set_value`,
so versioning, rollback and audit logging stay exactly as they are for every
other config section.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.api.schemas.admin import (
    DangerousAction,
    LlmProviderBreakerSettingsRequest,
    LlmProviderEndpointUpsertRequest,
    LlmProviderEndpointView,
    LlmProviderPoolView,
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
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint

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
    """Creates or replaces one endpoint. `api_key=None` keeps the stored secret."""
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    existing = config.endpoints.get(endpoint_id)
    api_key = existing.api_key if payload.api_key is None and existing else (payload.api_key or "")

    config.endpoints[endpoint_id] = LlmProviderEndpoint(
        name=payload.name,
        base_url=payload.base_url,
        api_key=api_key,
        models=payload.models,
        scenario_tags=payload.scenario_tags or ["general"],
        max_concurrency=payload.max_concurrency,
        priority=payload.priority,
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
        after={"name": payload.name, "base_url": payload.base_url, "enabled": payload.enabled},
        request=request,
    )
    session.commit()
    return _pool_view(LlmProviderConfig.model_validate(row.value_json))


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
        before={"name": removed.name, "base_url": removed.base_url},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _pool_view(LlmProviderConfig.model_validate(row.value_json))


@router.put("/llm-providers/settings/circuit-breaker", response_model=LlmProviderPoolView)
def update_breaker_settings(
    payload: LlmProviderBreakerSettingsRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> LlmProviderPoolView:
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    config.circuit_breaker_failure_threshold = payload.circuit_breaker_failure_threshold
    config.circuit_breaker_cooldown_s = payload.circuit_breaker_cooldown_s
    row = _save(session, config, user_id=user.id, note="更新熔断阈值")
    audit.record(
        session,
        actor=user,
        action="llm_provider.breaker_settings",
        target_type="platform_config",
        target_id=CONFIG_KEY,
        after=payload.model_dump(),
        request=request,
    )
    session.commit()
    return _pool_view(LlmProviderConfig.model_validate(row.value_json))


def _save(session, config: LlmProviderConfig, *, user_id: str, note: str):  # type: ignore[no-untyped-def]
    return config_service.set_value(
        session, CONFIG_KEY, config.model_dump(mode="json"), actor_user_id=user_id, note=note
    )


def _pool_view(config: LlmProviderConfig) -> LlmProviderPoolView:
    endpoints = [
        _endpoint_view(endpoint_id, endpoint) for endpoint_id, endpoint in config.endpoints.items()
    ]
    endpoints.sort(key=lambda item: (item.priority, item.id))
    return LlmProviderPoolView(
        endpoints=endpoints,
        circuit_breaker_failure_threshold=config.circuit_breaker_failure_threshold,
        circuit_breaker_cooldown_s=config.circuit_breaker_cooldown_s,
    )


def _endpoint_view(endpoint_id: str, endpoint: LlmProviderEndpoint) -> LlmProviderEndpointView:
    status = failover.runtime_status(endpoint_id)
    return LlmProviderEndpointView(
        id=endpoint_id,
        name=endpoint.name,
        base_url=endpoint.base_url,
        api_key_configured=bool(endpoint.api_key),
        api_key_preview=_mask(endpoint.api_key),
        models=endpoint.models,
        scenario_tags=endpoint.scenario_tags,
        max_concurrency=endpoint.max_concurrency,
        priority=endpoint.priority,
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
