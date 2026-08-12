"""Model provider directory: readable CRUD over the versioned `llm_providers`
config section, with runtime status merged in and secrets never echoed back.

Deliberately not the generic `/admin/config/{key}` editor: that endpoint
would round-trip every `api_key` in plaintext and shows nothing about which
endpoint is currently overloaded or breaker-tripped. This router adds that
readability on top while still writing through `config_service.set_value`,
so versioning, rollback and audit logging stay exactly as they are for every
other config section.

The console renders general and media endpoints separately. Endpoint timeout
and concurrency are maintained here; bounded gateway retry/breaker safeguards
are code defaults rather than a second global runtime-config surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.api.schemas.admin import (
    DangerousAction,
    LlmProviderEndpointUpsertRequest,
    LlmProviderEndpointView,
    LlmProviderPoolView,
    LlmProviderValidationResult,
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
from app.domain.errors import NotFound, ValidationFailed
from app.llm import failover
from app.models import AgentProfile
from app.platform_config import service as config_service
from app.platform_config.schemas import (
    LlmProviderConfig,
    LlmProviderEndpoint,
)
from app.providers import connectivity

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

    General endpoints have one primary: saving one as primary demotes the
    previous primary and records that relation change in the same audit entry.
    Media endpoints have no primary/backup semantics.
    """
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    existing = config.endpoints.get(endpoint_id)
    api_key = existing.api_key if payload.api_key is None and existing else (payload.api_key or "")

    demoted_ids: list[str] = []
    if payload.kind == "general" and payload.role == "primary":
        for other_id, other in config.endpoints.items():
            if other_id != endpoint_id and other.kind == payload.kind and other.role == "primary":
                other.role = "backup"
                demoted_ids.append(other_id)

    try:
        endpoint = LlmProviderEndpoint(
            name=payload.name,
            base_url=payload.base_url,
            api_key=api_key,
            kind=payload.kind,
            models=payload.models if payload.kind == "general" else [],
            role=payload.role if payload.kind == "general" else "backup",
            backup_order=payload.backup_order if payload.kind == "general" else 100,
            model=payload.model if payload.kind == "media" else "",
            input_modalities=list(payload.input_modalities) if payload.kind == "media" else [],
            output_modalities=list(payload.output_modalities) if payload.kind == "media" else [],
            max_concurrency=payload.max_concurrency if payload.kind == "general" else 1,
            timeout_ms=payload.timeout_ms,
            enabled=payload.enabled,
        )
        _assert_agent_bindings_compatible(session, endpoint_id, endpoint)
        config.endpoints[endpoint_id] = endpoint
    except ValidationError as exc:
        # Business-rule checks (e.g. "modalities must cover a capability")
        # live on the domain model's own validator, not the request schema,
        # so they surface here rather than as a `RequestValidationError`.
        raise ValidationFailed(f"模型配置校验失败: {exc}") from exc
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
            "model": payload.model if payload.kind == "media" else None,
            "input_modalities": sorted(payload.input_modalities) if payload.kind == "media" else [],
            "output_modalities": sorted(payload.output_modalities)
            if payload.kind == "media"
            else [],
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
    references = _referencing_profiles(session, endpoint_id)
    if references:
        names = "、".join(profile.display_name for profile in references[:3])
        raise ValidationFailed(f"端点仍被智能体使用，请先解除绑定：{names}")
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


@router.post("/llm-providers/{endpoint_id}/validate", response_model=LlmProviderValidationResult)
def validate_llm_provider(
    endpoint_id: str,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> LlmProviderValidationResult:
    """Send one real request directly to a saved endpoint.

    This intentionally bypasses enabled state, failover, breaker state, and
    provider statistics: the result must describe this endpoint alone.
    """
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    endpoint = config.endpoints.get(endpoint_id)
    if endpoint is None:
        raise NotFound(f"端点 {endpoint_id} 不存在。")

    outcome = connectivity.validate_endpoint(endpoint)
    result = LlmProviderValidationResult(
        endpoint_id=endpoint_id,
        kind=endpoint.kind,
        target_model=outcome.target_model,
        probe_type=outcome.probe_type,
        reachable=outcome.reachable,
        usable=outcome.usable,
        latency_ms=outcome.latency_ms,
        provider_status_code=outcome.provider_status_code,
        error_code=outcome.error_code,
        warning_code=outcome.warning_code,
        provider_error_code=outcome.provider_error_code,
        provider_error_message=outcome.provider_error_message,
        external_task_id=outcome.external_task_id,
    )
    audit.record(
        session,
        actor=user,
        action="llm_provider.validate",
        target_type="llm_provider_endpoint",
        target_id=endpoint_id,
        after=result.model_dump(mode="json"),
        request=request,
    )
    session.commit()
    return result


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
        model=endpoint.model,
        input_modalities=list(endpoint.input_modalities),
        output_modalities=list(endpoint.output_modalities),
        capabilities=sorted(endpoint.capabilities),
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


def _referencing_profiles(session: Session, endpoint_id: str) -> list[AgentProfile]:
    profiles = list(session.scalars(select(AgentProfile)))
    return [
        profile
        for profile in profiles
        if endpoint_id in (profile.default_endpoint_id, profile.backup_endpoint_id)
    ]


def _assert_agent_bindings_compatible(
    session: Session,
    endpoint_id: str,
    endpoint: LlmProviderEndpoint,
) -> None:
    for profile in _referencing_profiles(session, endpoint_id):
        if endpoint_id in (profile.default_endpoint_id, profile.backup_endpoint_id):
            if endpoint.kind != "general":
                raise ValidationFailed(f"{profile.display_name} 将该端点作为通用模型供应商使用。")
            if profile.model and profile.model not in endpoint.models:
                raise ValidationFailed(
                    f"{profile.display_name} 绑定的模型 {profile.model} 不在端点模型列表中。"
                )
