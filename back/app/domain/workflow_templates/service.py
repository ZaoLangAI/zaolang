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
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.slots import is_known_slot
from app.domain.agent_skills import presets
from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import NotFound, ValidationFailed
from app.models import GenerationWorkflowTemplate
from app.models.base import utcnow
from app.models.enums import ImageAssetKind, Operation, VideoAssetKind
from app.workflows import registry
from app.workflows.defaults import asset_graph, default_graph
from app.workflows.graph import WorkflowGraph, WorkflowNode
from app.workflows.graph import validate as validate_graph

_OUTPUT_PORTS_BY_TYPE = {
    node_type: spec.output_ports for node_type, spec in registry.NODE_TYPES.items()
}

DEFAULT_TEMPLATE_NAME = "默认生成流程"

# The two operations that currently seed anything beyond the generic
# `asset_kind=None` template for images — see `ImageAssetKind`.
IMAGE_ASSET_OPERATIONS: frozenset[Operation] = frozenset(
    {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
)
# All three video operations seed per-`VideoAssetKind` templates, but they
# all canonicalize onto `TEXT_TO_VIDEO` (see `canonical_operation`), so this
# only ever produces rows under that one key — same shape as the image pair
# above collapsing onto `TEXT_TO_IMAGE`.
VIDEO_ASSET_OPERATIONS: frozenset[Operation] = frozenset(
    {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
)


def canonical_operation(operation: str) -> str:
    """`text_to_image`/`image_to_image`, and all three video operations,
    each share exactly one workflow graph per family.

    Whether an image job ends up as `text_to_image` or `image_to_image` — or
    a video job as `text_to_video`/`image_to_video`/`video_to_video` — is a
    runtime detail — whether the requester attached a reference image/video
    — not a different generation pipeline: the prompt is mandatory either
    way and an attached reference is only extra input (see
    `VideoGenerationStudio`'s "derive the operation" pattern on the
    frontend, the same one `ImageGenerationStudio` uses). Storing/resolving
    every operation in a family under one canonical key is what makes
    "configure the graph once, every entry point picks it up" true, instead
    of an operator having to publish the same graph two or three times.
    Every other operation is returned unchanged.
    """
    if operation == Operation.IMAGE_TO_IMAGE.value:
        return Operation.TEXT_TO_IMAGE.value
    if operation in (Operation.IMAGE_TO_VIDEO.value, Operation.VIDEO_TO_VIDEO.value):
        return Operation.TEXT_TO_VIDEO.value
    return operation


def get_active(
    session: Session, operation: str, asset_kind: str | None = None
) -> GenerationWorkflowTemplate | None:
    """Resolves the active template for `(operation, asset_kind)`.

    Falls back to the operation's generic (`asset_kind=None`) template when
    no template was ever published for this specific asset kind — the
    normal state for every non-image operation, and for `GENERAL` images,
    which is why `asset_kind=None`/`GENERAL` are treated the same here.
    `operation` is canonicalized first, so `image_to_image` resolves the
    same row as `text_to_image` — see `canonical_operation`.
    """
    operation = canonical_operation(operation)
    normalized = asset_kind if asset_kind and asset_kind != ImageAssetKind.GENERAL else None
    if normalized is not None:
        specific = session.scalar(
            select(GenerationWorkflowTemplate).where(
                GenerationWorkflowTemplate.operation == operation,
                GenerationWorkflowTemplate.asset_kind == normalized,
                GenerationWorkflowTemplate.is_active.is_(True),
            )
        )
        if specific is not None:
            return specific
    return session.scalar(
        select(GenerationWorkflowTemplate).where(
            GenerationWorkflowTemplate.operation == operation,
            GenerationWorkflowTemplate.asset_kind.is_(None),
            GenerationWorkflowTemplate.is_active.is_(True),
        )
    )


def _has_specific_active_template(session: Session, operation: str, asset_kind: str) -> bool:
    """Unlike `get_active`, never falls back to the generic template — used
    only to decide whether a *specific* `(operation, asset_kind)` template
    was ever published. `get_active` itself cannot answer that: once the
    generic template exists, it always resolves truthy for every kind via
    its own fallback, which would make `ensure_default_templates`'s "already
    seeded?" check for each kind vacuously true and it would never seed any
    of them."""
    return (
        session.scalar(
            select(GenerationWorkflowTemplate.id).where(
                GenerationWorkflowTemplate.operation == canonical_operation(operation),
                GenerationWorkflowTemplate.asset_kind == asset_kind,
                GenerationWorkflowTemplate.is_active.is_(True),
            )
        )
        is not None
    )


def get_by_id(session: Session, template_id: str) -> GenerationWorkflowTemplate:
    row = session.get(GenerationWorkflowTemplate, template_id)
    if row is None:
        raise NotFound(f"工作流模板 {template_id} 不存在。")
    return row


def list_versions(
    session: Session,
    operation: str,
    limit: int = 50,
    *,
    asset_kind: str | None = None,
) -> list[GenerationWorkflowTemplate]:
    stmt = select(GenerationWorkflowTemplate).where(
        GenerationWorkflowTemplate.operation == canonical_operation(operation)
    )
    normalized = asset_kind if asset_kind and asset_kind != ImageAssetKind.GENERAL else None
    stmt = stmt.where(GenerationWorkflowTemplate.asset_kind == normalized)
    return list(
        session.scalars(stmt.order_by(GenerationWorkflowTemplate.version.desc()).limit(limit))
    )


def validate_graph_json(graph_json: dict[str, Any], *, session: Session | None = None) -> list[str]:
    """Never raises: returns human-readable problems, empty when safe.

    With a `session`, also checks that every agent a node binds actually
    exists, is enabled, and has the role the node type expects. Those are
    errors rather than warnings: an unresolvable binding silently falls back
    to the role's default at runtime, so an operator would see their edit
    "succeed" and the prompt never change.
    """
    try:
        graph = WorkflowGraph.from_dict(graph_json)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"图结构格式不合法: {exc}"]
    errors = validate_graph(graph, output_ports_by_type=_OUTPUT_PORTS_BY_TYPE)
    if session is not None:
        errors.extend(_binding_errors(session, graph))
    return errors


def collect_warnings(session: Session, *, operation: str, graph_json: dict[str, Any]) -> list[str]:
    """Advisory problems that do not block publishing.

    Today that is capability mismatch: an agent declaring which operations
    it was written for, bound into a workflow for a different one. Running it
    is legitimate (an operator may be deliberately reusing a prompt), so this
    only asks them to look twice.
    """
    try:
        graph = WorkflowGraph.from_dict(graph_json)
    except (KeyError, TypeError, ValueError):
        return []

    operation = canonical_operation(operation)
    warnings: list[str] = []
    for binding in _iter_agent_bindings(graph):
        if binding.agent_id is None:
            continue
        agent = agent_skills_service.find_agent(session, binding.agent_id)
        if agent is None or not agent.enabled:
            continue  # already reported as an error
        if binding.expected_role is not None and agent.role != binding.expected_role:
            continue  # ditto
        declared = list(agent.operations_json or [])
        if declared and operation not in declared:
            warnings.append(
                f"节点 {binding.node.id} 绑定的智能体「{agent.display_name}」"
                f"声明的适用操作为 {declared}，不包含 {operation}。"
            )
    return warnings


def agent_usage(session: Session) -> dict[str, list[str]]:
    """Which operations' live graphs reference each agent, keyed by agent id.

    Powers the agents console's "used by" badges. Only ever six active
    templates, so a straight scan beats denormalising the reference into a
    column that could drift from the graph it describes.
    """
    usage: dict[str, list[str]] = {}
    templates = session.scalars(
        select(GenerationWorkflowTemplate).where(GenerationWorkflowTemplate.is_active.is_(True))
    )
    for template in templates:
        try:
            graph = WorkflowGraph.from_dict(template.graph_json)
        except (KeyError, TypeError, ValueError):
            continue
        for binding in _iter_agent_bindings(graph):
            if binding.agent_id is None:
                continue
            operations = usage.setdefault(binding.agent_id, [])
            if template.operation not in operations:
                operations.append(template.operation)
    return usage


@dataclass(frozen=True, slots=True)
class ResolvedBinding:
    """One node's agent selection, flattened across the two ways a node
    type can declare one (`registry.AgentBinding` /
    `registry.DynamicAgentBinding`).

    `agent_id` is `None` when the field was left empty, which means "the
    role's default agent" — always a valid choice, since a default judgment
    agent is required to carry a model binding. It is still yielded for a
    dynamic binding, because there the *role* is a config value that has to
    be checked whether or not a specific agent was picked.
    """

    node: WorkflowNode
    agent_id: str | None
    expected_role: str | None = None
    slot: str | None = None
    # True when `expected_role`/`slot` came out of the graph rather than out
    # of `registry.py`, and so are themselves operator input to be checked.
    is_dynamic: bool = False


def _config_str(node: WorkflowNode, field: str) -> str | None:
    raw = node.config.get(field)
    return raw.strip() or None if isinstance(raw, str) else None


def _iter_agent_bindings(graph: WorkflowGraph) -> Iterator[ResolvedBinding]:
    """Yields every agent selection a graph makes.

    A role binding left empty is skipped: it resolves to the role's default
    agent, which needs no checking. A dynamic binding is always yielded —
    its role field is what decides whether the node can run at all.
    """
    for node in graph.nodes:
        spec = registry.NODE_TYPES.get(node.type)
        if spec is None:
            continue

        for binding in spec.agent_bindings:
            agent_id = _config_str(node, binding.config_field)
            if agent_id is not None:
                yield ResolvedBinding(
                    node=node,
                    agent_id=agent_id,
                    expected_role=binding.role,
                    slot=binding.slot,
                )

        dynamic = spec.dynamic_agent_binding
        if dynamic is not None:
            yield ResolvedBinding(
                node=node,
                agent_id=_config_str(node, dynamic.config_field),
                expected_role=_config_str(node, dynamic.role_field),
                slot=_config_str(node, dynamic.slot_field),
                is_dynamic=True,
            )


def _dynamic_role_errors(node: WorkflowNode, role: str | None) -> list[str]:
    """Checks a role an operator typed into a `custom_agent`-style node.

    A role outside `ROLE_PRESETS` is not merely unusual — no node type
    invokes it and no agent can be created for it, so the node would fail
    every time it ran. Both `judgment` and `assist` roles are accepted,
    since `assist` is just the semantic label for a prompt-bound role that
    generates/polishes content instead of handing down a verdict (`copy`'s
    `enhance`/`clarify` slots are reached this way from anywhere in a graph).
    """
    if role is None:
        return [f"节点 {node.id} 没有指定智能体角色。"]
    preset = presets.find(role)
    if preset is None:
        return [f"节点 {node.id} 指定的角色 {role} 不在角色预设里，不会被执行。"]
    return []


def _binding_errors(session: Session, graph: WorkflowGraph) -> list[str]:
    errors: list[str] = []
    for binding in _iter_agent_bindings(graph):
        node = binding.node

        if binding.is_dynamic:
            # A static binding's role and slot shipped in `registry.py` and
            # are code-reviewed; a dynamic one's are operator input.
            role_errors = _dynamic_role_errors(node, binding.expected_role)
            if role_errors:
                errors.extend(role_errors)
                continue
            role = binding.expected_role
            assert role is not None  # `_dynamic_role_errors` rejects `None`
            if binding.slot is not None and not is_known_slot(role, binding.slot):
                errors.append(f"节点 {node.id} 指定的提示词槽位 {binding.slot} 不属于角色 {role}。")

        if binding.agent_id is None:
            continue

        agent = agent_skills_service.find_agent(session, binding.agent_id)
        if agent is None:
            errors.append(f"节点 {node.id} 绑定了不存在的智能体: {binding.agent_id}")
        elif not agent.enabled:
            errors.append(f"节点 {node.id} 绑定的智能体「{agent.display_name}」已停用。")
        elif binding.expected_role is not None and agent.role != binding.expected_role:
            # Only reachable by hand-editing the graph JSON — the console
            # filters its picker by role — but a mismatch would run the wrong
            # kind of agent for the stage, so it must not publish.
            errors.append(
                f"节点 {node.id} 需要 {binding.expected_role} 角色的智能体，"
                f"但绑定的「{agent.display_name}」是 {agent.role}。"
            )
    return errors


def publish(
    session: Session,
    *,
    operation: str,
    name: str,
    graph_json: dict[str, Any],
    actor_user_id: str | None,
    reason: str | None,
    asset_kind: str | None = None,
) -> GenerationWorkflowTemplate:
    if operation not in {op.value for op in Operation}:
        raise ValidationFailed(f"未知的 operation: {operation}")

    normalized_kind = (
        asset_kind
        if asset_kind and asset_kind not in (ImageAssetKind.GENERAL, VideoAssetKind.GENERAL)
        else None
    )
    if normalized_kind is not None:
        op = Operation(operation)
        is_image_kind = normalized_kind in {kind.value for kind in ImageAssetKind}
        is_video_kind = normalized_kind in {kind.value for kind in VideoAssetKind}
        # Not just "does this operation support *an* asset kind" — the kind's
        # own value must belong to the matching family too, or an image
        # kind (`scene`) could be published against a video operation and
        # vice versa. `ensure_default_templates` never does this itself
        # (each loop only ever pairs `ImageAssetKind` with an image
        # operation, `VideoAssetKind` with a video one), so this only ever
        # fires on a hand-built admin/API call.
        if (is_image_kind and op not in IMAGE_ASSET_OPERATIONS) or (
            is_video_kind and op not in VIDEO_ASSET_OPERATIONS
        ):
            raise ValidationFailed(f"{operation} 不支持按资产用途区分工作流。")
        if not is_image_kind and not is_video_kind:
            raise ValidationFailed(f"未知的 asset_kind: {asset_kind}")

    # `image_to_image` publishes into the same row family as `text_to_image`
    # from here on — see `canonical_operation`.
    operation = canonical_operation(operation)

    errors = validate_graph_json(graph_json, session=session)
    if errors:
        raise ValidationFailed("工作流图校验未通过，无法发布。", errors=errors)

    latest_version = session.scalar(
        select(GenerationWorkflowTemplate.version)
        .where(
            GenerationWorkflowTemplate.operation == operation,
            GenerationWorkflowTemplate.asset_kind == normalized_kind,
        )
        .order_by(GenerationWorkflowTemplate.version.desc())
        .limit(1)
    )
    next_version = (latest_version or 0) + 1

    session.execute(
        update(GenerationWorkflowTemplate)
        .where(
            GenerationWorkflowTemplate.operation == operation,
            GenerationWorkflowTemplate.asset_kind == normalized_kind,
            GenerationWorkflowTemplate.is_active.is_(True),
        )
        .values(is_active=False)
    )
    row = GenerationWorkflowTemplate(
        operation=operation,
        asset_kind=normalized_kind,
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
        asset_kind=target.asset_kind,
    )


def ensure_default_templates(session: Session) -> None:
    """Idempotently seeds one active v1 template per `(Operation, asset_kind)`.

    Every `Operation` gets the generic (`asset_kind=None`) template it always
    had; the image family additionally gets one per non-`GENERAL`
    `ImageAssetKind` (`character`/`scene`/`cover`), and the video family one
    per non-`GENERAL` `VideoAssetKind` (`character_action`/
    `transition_video`/`cover_video`), each running the `asset_planning`/
    `asset_output_link`-augmented graph — the image `character` kind also
    loops through `asset_output_advance` when the job asks for more than one
    `character_views` entry (no video kind ever loops). `image_to_image` is
    folded into `text_to_image`, and `image_to_video`/`video_to_video` into
    `text_to_video`, by `get_active`/`canonical_operation`, so this loop only
    ever creates rows under `text_to_image`/`text_to_video` for each family —
    four image rows plus four video rows, not sixteen. Safe to call on every
    startup/seed run: any `(operation, asset_kind)` that already has an
    active template (including one an operator hand-edited) is left alone.
    """
    for operation in Operation:
        if get_active(session, operation.value) is None:
            publish(
                session,
                operation=operation.value,
                name=DEFAULT_TEMPLATE_NAME,
                graph_json=default_graph(session),
                actor_user_id=None,
                reason="seed: 初始默认模板",
            )
        if operation in IMAGE_ASSET_OPERATIONS:
            for kind in ImageAssetKind:
                if kind == ImageAssetKind.GENERAL:
                    continue
                if _has_specific_active_template(session, operation.value, kind.value):
                    continue
                publish(
                    session,
                    operation=operation.value,
                    name=f"{DEFAULT_TEMPLATE_NAME} · {kind.value}",
                    graph_json=asset_graph(session, kind.value),
                    actor_user_id=None,
                    reason="seed: 初始默认模板（按资产用途）",
                    asset_kind=kind.value,
                )
        if operation in VIDEO_ASSET_OPERATIONS:
            for video_kind in VideoAssetKind:
                if video_kind == VideoAssetKind.GENERAL:
                    continue
                if _has_specific_active_template(session, operation.value, video_kind.value):
                    continue
                publish(
                    session,
                    operation=operation.value,
                    name=f"{DEFAULT_TEMPLATE_NAME} · {video_kind.value}",
                    graph_json=asset_graph(session, video_kind.value),
                    actor_user_id=None,
                    reason="seed: 初始默认模板（按资产用途）",
                    asset_kind=video_kind.value,
                )
