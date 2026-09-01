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

import logging

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.api.request_utils import client_ip
from app.api.schemas.admin import (
    DangerousAction,
    LlmProviderEndpointUpsertRequest,
    LlmProviderEndpointView,
    LlmProviderPoolView,
    LlmProviderValidationJob,
    LlmProviderValidationResult,
    MediaPricingPayload,
    ModelCatalogEntryView,
    ModelCatalogResponse,
    PriceItemView,
    TokenPricingPayload,
    VendorCatalogView,
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
from app.models import AgentProfile, User
from app.observability.context import get_request_id, set_request_id
from app.platform_config import service as config_service
from app.platform_config.schemas import (
    LlmProviderConfig,
    LlmProviderEndpoint,
)
from app.providers import connectivity, model_catalog, validation_jobs

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin:llm-providers"])

CONFIG_KEY = "llm_providers"


@router.get("/llm-providers", response_model=LlmProviderPoolView)
def list_llm_providers(session: DbSession, user: Viewer, _: AdminRead) -> LlmProviderPoolView:
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    return _pool_view(config)


@router.get("/llm-providers/catalog", response_model=ModelCatalogResponse)
def get_llm_provider_catalog(user: Viewer, _: AdminRead) -> ModelCatalogResponse:
    """Read-only curated model catalogue for the admin "service provider ->
    known model" picker — see `app.providers.model_catalog`. Never mutates
    config; the operator still upserts through `PUT /llm-providers/{id}`
    exactly as before, whether or not they picked a catalogue entry.
    """
    return ModelCatalogResponse(
        vendors=[
            VendorCatalogView(
                vendor=vendor,
                label=model_catalog.VENDOR_LABELS[vendor],
                base_url=model_catalog.vendor_base_url(vendor),
                models=[
                    ModelCatalogEntryView(
                        model=entry.model,
                        display_name=entry.display_name,
                        kind=entry.kind,
                        protocol=entry.protocol,
                        input_modalities=list(entry.input_modalities),
                        output_modalities=list(entry.output_modalities),
                        context_length=entry.context_length,
                        notes=entry.notes,
                        doc_url=entry.doc_url,
                        pricing_doc_url=entry.pricing_doc_url,
                        billing_profile=entry.billing_profile,
                        price_items=[
                            PriceItemView(
                                key=item.key,
                                unit=item.unit,
                                label=item.label,
                                default_micro_usd=item.default_micro_usd,
                                source_currency=item.source_currency,
                                source_amount=item.source_amount,
                                quoted_on=item.quoted_on,
                                dimension=item.dimension,
                                free_count=item.free_count,
                                volatile=item.volatile,
                                markup_note=item.markup_note,
                            )
                            for item in entry.price_items
                        ],
                    )
                    for entry in model_catalog.VENDOR_MODEL_CATALOG.get(vendor, [])
                ],
            )
            for vendor in model_catalog.VENDOR_IDS
        ]
    )


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
            role=payload.role if payload.kind == "general" else "backup",
            backup_order=payload.backup_order if payload.kind == "general" else 100,
            model=payload.model,
            # General endpoints now declare their own subset too (text is
            # auto-injected, image/video are optional) — the domain
            # validator enforces the allowed set per kind.
            input_modalities=list(payload.input_modalities),
            output_modalities=list(payload.output_modalities) if payload.kind == "media" else [],
            protocol=payload.protocol if payload.kind == "media" else None,
            max_concurrency=payload.max_concurrency if payload.kind == "general" else 1,
            timeout_ms=payload.timeout_ms,
            enabled=payload.enabled,
            context_length=payload.context_length,
            max_output_tokens=payload.max_output_tokens,
            token_pricing=payload.token_pricing.model_dump(),
            media_pricing=payload.media_pricing.model_dump(exclude_none=True),
            billing_profile=payload.billing_profile,
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
            "model": payload.model,
            "protocol": endpoint.protocol if payload.kind == "media" else None,
            "billing_profile": endpoint.billing_profile,
            "input_modalities": sorted(endpoint.input_modalities),
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


@router.post("/llm-providers/{endpoint_id}/validate", response_model=LlmProviderValidationJob)
def validate_llm_provider(
    endpoint_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> LlmProviderValidationJob:
    """Start one real request directly to a saved endpoint.

    Image and audio probes can take tens of seconds. This returns a running
    job immediately; poll `GET .../validate/{validation_id}` for the result.
    The probe still bypasses enabled state, failover, breaker state, and
    provider statistics: the result must describe this endpoint alone.
    """
    config = config_service.get_typed(session, CONFIG_KEY, LlmProviderConfig)
    endpoint = config.endpoints.get(endpoint_id)
    if endpoint is None:
        raise NotFound(f"端点 {endpoint_id} 不存在。")

    job = validation_jobs.create_running(endpoint_id=endpoint_id, timeout_ms=endpoint.timeout_ms)
    background_tasks.add_task(
        _run_validation,
        validation_id=job.validation_id,
        endpoint_id=endpoint_id,
        endpoint=endpoint,
        actor_user_id=user.id,
        request_id=get_request_id(),
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:255] or None),
        session=session,
    )
    return job


@router.get(
    "/llm-providers/{endpoint_id}/validate/{validation_id}",
    response_model=LlmProviderValidationJob,
)
def get_llm_provider_validation(
    endpoint_id: str,
    validation_id: str,
    user: Viewer,
    _: AdminRead,
) -> LlmProviderValidationJob:
    job = validation_jobs.get(endpoint_id, validation_id)
    if job is None:
        raise NotFound(f"验证任务 {validation_id} 不存在。")
    return job


def _run_validation(
    *,
    validation_id: str,
    endpoint_id: str,
    endpoint: LlmProviderEndpoint,
    actor_user_id: str,
    request_id: str,
    ip_address: str | None,
    user_agent: str | None,
    session: Session,
) -> None:
    try:
        outcome = connectivity.validate_endpoint(endpoint)
        result = _validation_result(endpoint_id, endpoint, outcome)
    except Exception:
        logger.exception("endpoint %s validation probe failed", endpoint_id)
        result = LlmProviderValidationResult(
            endpoint_id=endpoint_id,
            kind=endpoint.kind,
            target_model=endpoint.model or None,
            probe_type="media_generation" if endpoint.kind == "media" else "chat_completion",
            reachable=False,
            usable=False,
            latency_ms=0,
            error_code="provider_error",
        )
    validation_jobs.complete(validation_id, result)
    set_request_id(request_id)
    actor = session.get(User, actor_user_id)
    entry = audit.record(
        session,
        actor=actor,
        action="llm_provider.validate",
        target_type="llm_provider_endpoint",
        target_id=endpoint_id,
        after=result.model_dump(mode="json"),
    )
    if ip_address:
        entry.ip_address = ip_address
    if user_agent:
        entry.user_agent = user_agent
    session.commit()


def _validation_result(
    endpoint_id: str,
    endpoint: LlmProviderEndpoint,
    outcome: connectivity.ConnectivityResult,
) -> LlmProviderValidationResult:
    return LlmProviderValidationResult(
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
        model=endpoint.model,
        input_modalities=list(endpoint.input_modalities),
        output_modalities=list(endpoint.output_modalities),
        protocol=endpoint.protocol,
        capabilities=sorted(endpoint.capabilities),
        max_concurrency=endpoint.max_concurrency,
        role=endpoint.role,
        backup_order=endpoint.backup_order,
        timeout_ms=endpoint.timeout_ms,
        enabled=endpoint.enabled,
        context_length=endpoint.context_length,
        max_output_tokens=endpoint.max_output_tokens,
        token_pricing=TokenPricingPayload.model_validate(
            endpoint.token_pricing.model_dump(mode="json")
        ),
        media_pricing=MediaPricingPayload.model_validate(
            endpoint.media_pricing.model_dump(mode="json")
        ),
        billing_profile=endpoint.billing_profile,
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
    if endpoint.kind == "general":
        return
    for profile in _referencing_profiles(session, endpoint_id):
        raise ValidationFailed(f"{profile.display_name} 将该端点作为通用模型供应商使用。")
