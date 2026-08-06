"""The configurable generation workflow editor's back-office API.

Mirrors `agent_skills.py`'s shape (append-only versions, `DangerousAction`
confirmation + audit on every write) since publishing a graph and publishing
a prompt are the same kind of decision: both take effect on the very next
job, and both need a reason on record. `dry-run` is the one non-dangerous
write here — a sandbox execution that never creates a real `GenerationJob`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.api.schemas.admin import (
    DangerousAction,
    NodeTypeView,
    WorkflowDryRunRequest,
    WorkflowDryRunResult,
    WorkflowDryRunStepView,
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
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import GenerationJob
from app.models.base import new_id
from app.models.enums import JobStatus, Operation
from app.workflows import registry
from app.workflows.defaults import default_graph
from app.workflows.graph import WorkflowGraph
from app.workflows.runner import WorkflowRunner
from app.workflows.types import WorkflowContext

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
                output_ports=list(spec.output_ports),
                is_agent=spec.is_agent,
                agent_role=spec.agent_role,
                config_schema=spec.config_schema.model_json_schema(),
            )
            for node_type, spec in sorted(registry.NODE_TYPES.items())
        ]
    )


@router.post("/workflow-templates/validate", response_model=WorkflowTemplateValidateResponse)
def validate_workflow_graph(
    payload: WorkflowTemplateValidateRequest, user: Admin, _: AdminRead
) -> WorkflowTemplateValidateResponse:
    """Structural pre-check so the editor can flag a broken graph before an
    operator spends a confirmation dialog on it."""
    return WorkflowTemplateValidateResponse(
        errors=workflow_templates_service.validate_graph_json(payload.graph)
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


@router.post("/workflow-templates/{operation}/dry-run", response_model=WorkflowDryRunResult)
def dry_run_workflow_template(
    operation: Operation,
    payload: WorkflowDryRunRequest,
    session: DbSession,
    user: Operator,
    _: AdminWrite,
) -> WorkflowDryRunResult:
    """Simulates a job through the operation's *active* published graph.

    Never creates a `GenerationJob` row, reserves credits, or hits a paid
    provider — see `WorkflowContext.dry_run` and every node executor's own
    `if ctx.dry_run` branch for the specifics. The four agent nodes
    (safety/planning/intent_router/quality) still call the real LLM gateway
    on purpose: that is the one thing worth spending a little real cost on to
    actually validate a prompt change before publishing it.
    """
    # Mirrors `pipeline._resolve_graph`'s fallback: dry-running should show
    # exactly what a real job would run right now, including before anything
    # has ever been published for this operation.
    template = workflow_templates_service.get_active(session, operation.value)
    graph = WorkflowGraph.from_dict(template.graph_json if template else default_graph())

    params: dict[str, Any] = {"prompt": payload.prompt, **payload.params}
    fake_job = GenerationJob(
        id=new_id("dry"),
        user_id=user.id,
        operation=operation.value,
        request_json=params,
        quality_tier=payload.quality_tier,
        status=JobStatus.CREATED.value,
        quoted_credits=0,
        reserved_credits=0,
        idempotency_key=new_id("idk"),
        estimated_seconds=0,
    )
    ctx = WorkflowContext(
        session=session, job=fake_job, prompt=payload.prompt, params=params, dry_run=True
    )

    try:
        outcome = WorkflowRunner(graph).run(ctx)
        session.commit()
    except Exception:
        # A genuine crash (e.g. a mis-set LLM endpoint) must not 500 the
        # editor's try-it panel — surface it as a failed dry run with
        # whatever trace was collected before the crash, and roll back any
        # half-written agent-run rows from this attempt.
        session.rollback()
        return WorkflowDryRunResult(
            status=JobStatus.FAILED,
            failure_code="DRY_RUN_CRASHED",
            trace=_trace_view(ctx),
        )

    return WorkflowDryRunResult(
        status=outcome.status,
        failure_code=outcome.failure_code,
        asset_id=outcome.asset_id,
        trace=_trace_view(ctx),
    )


def _trace_view(ctx: WorkflowContext) -> list[WorkflowDryRunStepView]:
    trace: list[dict[str, Any]] = ctx.state.get("_trace") or []
    return [
        WorkflowDryRunStepView(
            node_id=entry["node_id"],
            node_type=entry["node_type"],
            port=entry["port"],
            agent_run_id=entry.get("agent_run_id"),
        )
        for entry in trace
    ]


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
