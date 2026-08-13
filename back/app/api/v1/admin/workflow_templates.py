"""The configurable generation workflow editor's back-office API.

Mirrors `agent_skills.py`'s shape (append-only versions, `DangerousAction`
confirmation + audit on every write) since publishing a graph and publishing
a prompt are the same kind of decision: both take effect on the very next
job, and both need a reason on record. `sandbox-run` is the one non-dangerous
write here — it creates a real `GenerationJob` (visible in ops and
moderation) but skips the credit ledger.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import DbSession, IdempotencyKey
from app.api.schemas.admin import (
    AgentBindingView,
    DangerousAction,
    DynamicAgentBindingView,
    NodeTypeView,
    WorkflowSandboxRunRequest,
    WorkflowSandboxRunResult,
    WorkflowTemplatePublishRequest,
    WorkflowTemplateValidateRequest,
    WorkflowTemplateValidateResponse,
    WorkflowTemplateView,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import (
    Admin,
    AdminDangerous,
    AdminRead,
    AdminWrite,
    Operator,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.errors import NotFound, ValidationFailed
from app.domain.jobs import service as jobs_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models.base import new_id
from app.models.enums import JobOrigin, Operation
from app.workflows import registry

router = APIRouter(tags=["admin:workflow-templates"])


@router.get("/workflow-templates/node-types", response_model=Page[NodeTypeView])
def list_node_types(user: Viewer, _: AdminRead) -> Page[NodeTypeView]:
    """The whitelist an operator drags nodes from — there is no way to add a
    type from the console; every entry here shipped in a code review."""
    return Page(
        items=[
            NodeTypeView(
                type=node_type,
                category=spec.category,
                label=spec.label,
                description=spec.description,
                label_key=f"nodeType_{node_type}_label",
                description_key=f"nodeType_{node_type}_desc",
                output_ports=list(spec.output_ports),
                is_agent=spec.is_agent,
                agent_role=spec.agent_role,
                agent_bindings=[
                    AgentBindingView(
                        config_field=binding.config_field, role=binding.role, slot=binding.slot
                    )
                    for binding in spec.agent_bindings
                ],
                dynamic_agent_binding=(
                    DynamicAgentBindingView(
                        config_field=spec.dynamic_agent_binding.config_field,
                        role_field=spec.dynamic_agent_binding.role_field,
                        slot_field=spec.dynamic_agent_binding.slot_field,
                    )
                    if spec.dynamic_agent_binding is not None
                    else None
                ),
                config_schema=spec.config_schema.model_json_schema(),
            )
            for node_type, spec in sorted(registry.NODE_TYPES.items())
        ]
    )


@router.post("/workflow-templates/validate", response_model=WorkflowTemplateValidateResponse)
def validate_workflow_graph(
    payload: WorkflowTemplateValidateRequest, session: DbSession, user: Admin, _: AdminRead
) -> WorkflowTemplateValidateResponse:
    """Pre-check so the editor can flag problems before an operator spends a
    confirmation dialog on them.

    `warnings` are advisory and never block `publish`; they exist so a
    capability mismatch between a bound agent agent and this operation is
    seen rather than discovered in production.
    """
    warnings = (
        workflow_templates_service.collect_warnings(
            session, operation=payload.operation.value, graph_json=payload.graph
        )
        if payload.operation is not None
        else []
    )
    return WorkflowTemplateValidateResponse(
        errors=workflow_templates_service.validate_graph_json(payload.graph, session=session),
        warnings=warnings,
    )


@router.get("/workflow-templates/{operation}", response_model=WorkflowTemplateView)
def get_active_template(
    operation: Operation, session: DbSession, user: Viewer, _: AdminRead
) -> WorkflowTemplateView:
    template = workflow_templates_service.get_active(session, operation.value)
    if template is None:
        raise NotFound(f"{operation.value} 还没有已发布的工作流模板。")
    return _template_view(template)


@router.get("/workflow-templates/{operation}/versions", response_model=Page[WorkflowTemplateView])
def list_template_versions(
    operation: Operation, session: DbSession, user: Viewer, _: AdminRead
) -> Page[WorkflowTemplateView]:
    versions = workflow_templates_service.list_versions(session, operation.value)
    return Page(items=[_template_view(v) for v in versions])


@router.put("/workflow-templates/{operation}", response_model=WorkflowTemplateView, status_code=201)
def publish_workflow_template(
    operation: Operation,
    payload: WorkflowTemplatePublishRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> WorkflowTemplateView:
    """Publishes a new version of one operation's graph and makes it active.

    A published graph decides the real execution path of every job submitted
    from now on, so it carries the same confirmation ceremony as any other
    dangerous admin action.
    """
    require_confirmation(payload.confirm)
    row = workflow_templates_service.publish(
        session,
        operation=operation.value,
        name=payload.name,
        graph_json=payload.graph,
        actor_user_id=user.id,
        reason=payload.reason,
    )
    audit.record(
        session,
        actor=user,
        action="workflow_template.publish",
        target_type="generation_workflow_template",
        target_id=row.id,
        after={"operation": row.operation, "version": row.version},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _template_view(row)


@router.post(
    "/workflow-templates/{operation}/activate/{template_id}", response_model=WorkflowTemplateView
)
def activate_workflow_template(
    operation: Operation,
    template_id: str,
    payload: DangerousAction,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> WorkflowTemplateView:
    """Rolls back by re-publishing an earlier version's graph as a new one."""
    require_confirmation(payload.confirm)
    target = workflow_templates_service.get_by_id(session, template_id)
    if target.operation != operation.value:
        raise ValidationFailed(f"模板 {template_id} 不属于 {operation.value}。")
    row = workflow_templates_service.activate_version(
        session, template_id, actor_user_id=user.id, reason=payload.reason
    )
    audit.record(
        session,
        actor=user,
        action="workflow_template.activate",
        target_type="generation_workflow_template",
        target_id=row.id,
        after={"operation": row.operation, "version": row.version, "rolled_back_from": template_id},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _template_view(row)


@router.post(
    "/workflow-templates/{operation}/sandbox-run",
    response_model=WorkflowSandboxRunResult,
    status_code=202,
)
def sandbox_run_workflow_template(
    operation: Operation,
    payload: WorkflowSandboxRunRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminWrite,
    idempotency_key: IdempotencyKey,
) -> WorkflowSandboxRunResult:
    """Submits a real generation job that walks this operation's graph.

    The editor's unpublished draft when `payload.graph` is given, otherwise
    the operation's active published template (pinned like a C-end submit).
    Credits are quoted but never reserved. Everything else — JobEvent, SSE,
    ProviderAttempt, asset registration, PRE_GENERATION moderation on
    NEEDS_REVIEW, POST_GENERATION on success — matches a consumer request.

    A draft is held to exactly the same validation as a publish, because a
    graph that fails it cannot be walked safely; it is stored on the job as
    `graph_override_json` and never becomes a `GenerationWorkflowTemplate`.
    """
    graph_override: dict[str, Any] | None = None
    if payload.graph is not None:
        errors = workflow_templates_service.validate_graph_json(payload.graph, session=session)
        if errors:
            raise ValidationFailed("草稿工作流图校验未通过，无法试跑。", errors=errors)
        graph_override = payload.graph

    params: dict[str, Any] = {"prompt": payload.prompt, **payload.params}
    result = jobs_service.submit(
        session,
        user_id=user.id,
        operation=operation.value,
        quality_tier=payload.quality_tier,
        params=params,
        idempotency_key=idempotency_key or new_id("idk"),
        origin=JobOrigin.SANDBOX,
        graph_override_json=graph_override,
    )
    audit.record(
        session,
        actor=user,
        action="workflow_template.sandbox_run",
        target_type="generation_job",
        target_id=result.job.id,
        after={"operation": operation.value, "origin": JobOrigin.SANDBOX.value},
        request=request,
    )
    session.commit()
    if not result.replayed:
        from app.workers import tasks

        tasks.dispatch_generation(result.job)
    return WorkflowSandboxRunResult(job_id=result.job.id)


def _template_view(row) -> WorkflowTemplateView:  # type: ignore[no-untyped-def]
    return WorkflowTemplateView(
        id=row.id,
        operation=row.operation,
        version=row.version,
        name=row.name,
        graph=row.graph_json,
        is_active=row.is_active,
        created_by_user_id=row.created_by_user_id,
        reason=row.reason,
        created_at=row.created_at,
    )
