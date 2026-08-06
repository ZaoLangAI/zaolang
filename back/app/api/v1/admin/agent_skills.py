"""Agent node topology and versioned prompts (engineering-side Agent Skill).

Distinct from the technical `AgentRunView`/`AgentUsageSummary` observation
endpoints in `observability.py`: those read what already happened, this
writes what happens next. Also distinct from the user-facing skill library
(`skill_library.py`, once added) — this is the four/five built-in pipeline
stages' prompts, not user-authored generation parameter templates.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.api.schemas.admin import (
    AgentNodeView,
    AgentSkillPublishRequest,
    AgentSkillView,
    DangerousAction,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import Admin, AdminDangerous, AdminRead, Viewer, require_confirmation
from app.domain.agent_skills import service as agent_skills_service
from app.domain.audit import service as audit
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig

router = APIRouter(tags=["admin:agent-skills"])


@router.get("/agent-nodes", response_model=Page[AgentNodeView])
def list_agent_nodes(session: DbSession, user: Viewer, _: AdminRead) -> Page[AgentNodeView]:
    nodes = agent_skills_service.list_nodes(session)
    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    return Page(items=[_node_view(node, provider_config) for node in nodes])


@router.get("/agent-skills", response_model=Page[AgentSkillView])
def list_agent_skills(
    node_role: str, session: DbSession, user: Viewer, _: AdminRead
) -> Page[AgentSkillView]:
    versions = agent_skills_service.list_versions(session, node_role)
    return Page(items=[_skill_view(v) for v in versions])


@router.post("/agent-skills", response_model=AgentSkillView, status_code=201)
def publish_agent_skill(
    payload: AgentSkillPublishRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> AgentSkillView:
    """Publishes a new prompt version for one node and makes it active.

    A rejected or unparseable safety verdict is the direct, immediate result
    of what this prompt says, so publishing it is treated with the same
    confirmation ceremony as any other dangerous admin action.
    """
    require_confirmation(payload.confirm)
    row = agent_skills_service.publish(
        session,
        node_role=payload.node_role,
        prompt_template=payload.prompt_template,
        tool_grants=payload.tool_grants,
        actor_user_id=user.id,
        reason=payload.reason,
    )
    audit.record(
        session,
        actor=user,
        action="agent_skill.publish",
        target_type="agent_skill",
        target_id=row.id,
        after={"node_role": row.node_role, "version": row.version},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _skill_view(row)


@router.post("/agent-skills/{skill_id}/activate", response_model=AgentSkillView)
def activate_agent_skill(
    skill_id: str,
    payload: DangerousAction,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> AgentSkillView:
    """Rolls back to an earlier version by re-publishing its content."""
    require_confirmation(payload.confirm)
    row = agent_skills_service.activate_version(
        session, skill_id, actor_user_id=user.id, reason=payload.reason
    )
    audit.record(
        session,
        actor=user,
        action="agent_skill.activate",
        target_type="agent_skill",
        target_id=row.id,
        after={"node_role": row.node_role, "version": row.version, "rolled_back_from": skill_id},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _skill_view(row)


def _node_view(node, provider_config: LlmProviderConfig) -> AgentNodeView:  # type: ignore[no-untyped-def]
    candidates = [
        endpoint_id
        for endpoint_id, endpoint in provider_config.endpoints.items()
        if endpoint.enabled and endpoint.kind == "general"
    ]
    return AgentNodeView(
        id=node.id,
        role=node.role,
        display_name=node.display_name,
        description=node.description,
        enabled=node.enabled,
        sort_order=node.sort_order,
        candidate_endpoint_ids=candidates,
    )


def _skill_view(skill) -> AgentSkillView:  # type: ignore[no-untyped-def]
    return AgentSkillView(
        id=skill.id,
        node_role=skill.node_role,
        version=skill.version,
        prompt_template=skill.prompt_template,
        tool_grants=list(skill.tool_grants_json),
        is_active=skill.is_active,
        created_by_user_id=skill.created_by_user_id,
        reason=skill.reason,
        created_at=skill.created_at,
    )
