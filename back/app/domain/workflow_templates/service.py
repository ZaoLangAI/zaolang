"""Versioned, admin-configurable generation workflow graphs.

Append-only like `app.domain.agent_skills.service` and
`app.platform_config.service`: publishing never edits a row in place, it
appends a new version for the `Operation` and flips `is_active`.
`GenerationJob.workflow_template_id` pins the active template at submission
time, so a later publish cannot change the behaviour of a job already in
flight — the same reasoning the pre-existing sampler-level `Workflow` /
`WorkflowVersion` hash-locking uses, just for this business-orchestration
layer instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import NotFound, ValidationFailed
from app.models import GenerationWorkflowTemplate
from app.models.base import utcnow
from app.models.enums import Operation
from app.workflows import registry
from app.workflows.defaults import default_graph
from app.workflows.graph import WorkflowGraph, WorkflowNode
from app.workflows.graph import validate as validate_graph

_REGISTRY_TYPES = set(registry.NODE_TYPES.keys())

DEFAULT_TEMPLATE_NAME = "默认生成流程"


def get_active(session: Session, operation: str) -> GenerationWorkflowTemplate | None:
    return session.scalar(
        select(GenerationWorkflowTemplate).where(
            GenerationWorkflowTemplate.operation == operation,
            GenerationWorkflowTemplate.is_active.is_(True),
        )
    )


def get_by_id(session: Session, template_id: str) -> GenerationWorkflowTemplate:
    row = session.get(GenerationWorkflowTemplate, template_id)
    if row is None:
        raise NotFound(f"工作流模板 {template_id} 不存在。")
    return row


def list_versions(
    session: Session, operation: str, limit: int = 50
) -> list[GenerationWorkflowTemplate]:
    return list(
        session.scalars(
            select(GenerationWorkflowTemplate)
            .where(GenerationWorkflowTemplate.operation == operation)
            .order_by(GenerationWorkflowTemplate.version.desc())
            .limit(limit)
        )
    )


def validate_graph_json(graph_json: dict[str, Any], *, session: Session | None = None) -> list[str]:
    """Never raises: returns human-readable problems, empty when safe.

    With a `session`, also checks that every agent variant a node binds
    actually exists and is enabled. That is an error rather than a warning:
    an unresolvable binding silently falls back to the role's default at
    runtime, so an operator would see their edit "succeed" and the prompt
    never change.
    """
    try:
        graph = WorkflowGraph.from_dict(graph_json)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"图结构格式不合法: {exc}"]
    errors = validate_graph(graph, registry_types=_REGISTRY_TYPES)
    if session is not None:
        errors.extend(_binding_errors(session, graph))
    return errors


def collect_warnings(session: Session, *, operation: str, graph_json: dict[str, Any]) -> list[str]:
    """Advisory problems that do not block publishing.

    Today that is capability mismatch: a variant declaring which operations
    it was written for, bound into a workflow for a different one. Running it
    is legitimate (an operator may be deliberately reusing a prompt), so this
    only asks them to look twice.
    """
    try:
        graph = WorkflowGraph.from_dict(graph_json)
    except (KeyError, TypeError, ValueError):
        return []

    warnings: list[str] = []
    for node, binding, key in _iter_profile_bindings(graph):
        profile = agent_skills_service.find_profile(session, binding.role, key)
        if profile is None or not profile.enabled:
            continue  # already reported as an error
        declared = list(profile.operations_json or [])
        if declared and operation not in declared:
            warnings.append(
                f"节点 {node.id} 绑定的变体「{profile.display_name}」"
                f"（{binding.role}/{key}）声明的适用操作为 {declared}，不包含 {operation}。"
            )
    return warnings


def profile_usage(session: Session) -> dict[tuple[str, str], list[str]]:
    """Which operations' live graphs reference each `(role, profile key)`.

    Powers the agents console's "used by" badges. Only ever six active
    templates, so a straight scan beats denormalising the reference into a
    column that could drift from the graph it describes.
    """
    usage: dict[tuple[str, str], list[str]] = {}
    templates = session.scalars(
        select(GenerationWorkflowTemplate).where(GenerationWorkflowTemplate.is_active.is_(True))
    )
    for template in templates:
        try:
            graph = WorkflowGraph.from_dict(template.graph_json)
        except (KeyError, TypeError, ValueError):
            continue
        for _node, binding, key in _iter_profile_bindings(graph):
            operations = usage.setdefault((binding.role, key), [])
            if template.operation not in operations:
                operations.append(template.operation)
    return usage


def _iter_profile_bindings(
    graph: WorkflowGraph,
) -> Iterator[tuple[WorkflowNode, registry.ProfileBinding, str]]:
    """Yields every explicit variant binding in a graph.

    A node that leaves the field empty is not yielded: it resolves to the
    role's default variant, which is always valid.
    """
    for node in graph.nodes:
        spec = registry.NODE_TYPES.get(node.type)
        if spec is None:
            continue
        for binding in spec.profile_bindings:
            raw = node.config.get(binding.config_field)
            if isinstance(raw, str) and raw.strip():
                yield node, binding, raw.strip()


def _binding_errors(session: Session, graph: WorkflowGraph) -> list[str]:
    errors: list[str] = []
    for node, binding, key in _iter_profile_bindings(graph):
        profile = agent_skills_service.find_profile(session, binding.role, key)
        if profile is None:
            errors.append(f"节点 {node.id} 绑定了不存在的智能体变体: {binding.role}/{key}")
        elif not profile.enabled:
            errors.append(f"节点 {node.id} 绑定的智能体变体已停用: {binding.role}/{key}")
    return errors


def publish(
    session: Session,
    *,
    operation: str,
    name: str,
    graph_json: dict[str, Any],
    actor_user_id: str | None,
    reason: str | None,
) -> GenerationWorkflowTemplate:
    if operation not in {op.value for op in Operation}:
        raise ValidationFailed(f"未知的 operation: {operation}")

    errors = validate_graph_json(graph_json, session=session)
    if errors:
        raise ValidationFailed("工作流图校验未通过，无法发布。", errors=errors)

    latest_version = session.scalar(
        select(GenerationWorkflowTemplate.version)
        .where(GenerationWorkflowTemplate.operation == operation)
        .order_by(GenerationWorkflowTemplate.version.desc())
        .limit(1)
    )
    next_version = (latest_version or 0) + 1

    session.execute(
        update(GenerationWorkflowTemplate)
        .where(
            GenerationWorkflowTemplate.operation == operation,
            GenerationWorkflowTemplate.is_active.is_(True),
        )
        .values(is_active=False)
    )
    row = GenerationWorkflowTemplate(
        operation=operation,
        version=next_version,
        name=name,
        graph_json=graph_json,
        is_active=True,
        created_by_user_id=actor_user_id,
        reason=reason,
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def activate_version(
    session: Session, template_id: str, *, actor_user_id: str | None, reason: str | None
) -> GenerationWorkflowTemplate:
    """Rolls back by re-publishing an earlier version's graph as a new one.

    Same trade-off as `agent_skills.activate_version`: moving forward with a
    copy keeps the mistake and the correction both in history.
    """
    target = get_by_id(session, template_id)
    return publish(
        session,
        operation=target.operation,
        name=target.name,
        graph_json=target.graph_json,
        actor_user_id=actor_user_id,
        reason=reason or f"回滚到版本 {target.version}",
    )


def ensure_default_templates(session: Session) -> None:
    """Idempotently seeds one active v1 template per `Operation`.

    Safe to call on every startup/seed run: an operation that already has an
    active template (including one an operator hand-edited) is left alone.
    """
    for operation in Operation:
        if get_active(session, operation.value) is not None:
            continue
        publish(
            session,
            operation=operation.value,
            name=DEFAULT_TEMPLATE_NAME,
            graph_json=default_graph(),
            actor_user_id=None,
            reason="seed: 初始默认模板",
        )
