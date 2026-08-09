"""Agent node topology, variants and versioned prompts (engineering-side Agent Skill).

Distinct from the technical `AgentRunView`/`AgentUsageSummary` observation
endpoints in `observability.py`: those read what already happened, this
writes what happens next. Also distinct from the user-facing skill library
(`skill_library.py`) — this is the built-in pipeline stages' prompts, not
user-authored generation parameter templates.

Three levels, matching `app.models.agent_skills`: a *node* is a role, a
*profile* is a named variant of that role bound by a workflow node, and a
*skill* is one append-only prompt version for a `(profile, slot)` pair.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.agents import slots as agent_slots
from app.api.deps import DbSession
from app.api.schemas.admin import (
    AgentNodeView,
    AgentProfileCreateRequest,
    AgentProfileUpdateRequest,
    AgentProfileView,
    AgentSkillPublishRequest,
    AgentSkillView,
    DangerousAction,
    PromptSlotView,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import (
    Admin,
    AdminDangerous,
    AdminRead,
    AdminWrite,
    Viewer,
    require_confirmation,
)
from app.domain.agent_skills import service as agent_skills_service
from app.domain.audit import service as audit
from app.domain.workflow_templates import service as workflow_templates_service
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig

router = APIRouter(tags=["admin:agent-skills"])


@router.get("/agent-nodes", response_model=Page[AgentNodeView])
def list_agent_nodes(session: DbSession, user: Viewer, _: AdminRead) -> Page[AgentNodeView]:
    nodes = agent_skills_service.list_nodes(session)
    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    return Page(items=[_node_view(node, provider_config) for node in nodes])


@router.get("/agent-profiles", response_model=Page[AgentProfileView])
def list_agent_profiles(
    session: DbSession, user: Viewer, _: AdminRead, role: str | None = None
) -> Page[AgentProfileView]:
    profiles = agent_skills_service.list_profiles(session, role=role)
    usage = workflow_templates_service.profile_usage(session)
    return Page(items=[_profile_view(p, usage) for p in profiles])


@router.post("/agent-profiles", response_model=AgentProfileView, status_code=201)
def create_agent_profile(
    payload: AgentProfileCreateRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> AgentProfileView:
    """Adds a variant. Not a dangerous action on its own — a variant changes
    nothing until a workflow node binds it, and binding is what carries the
    confirmation ceremony."""
    row = agent_skills_service.create_profile(
        session,
        role=payload.role,
        key=payload.key,
        display_name=payload.display_name,
        description=payload.description,
        operations=payload.operations,
    )
    audit.record(
        session,
        actor=user,
        action="agent_profile.create",
        target_type="agent_profile",
        target_id=row.id,
        after={"role": row.role, "key": row.key, "operations": list(row.operations_json)},
        request=request,
    )
    session.commit()
    return _profile_view(row, workflow_templates_service.profile_usage(session))


@router.patch("/agent-profiles/{profile_id}", response_model=AgentProfileView)
def update_agent_profile(
    profile_id: str,
    payload: AgentProfileUpdateRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> AgentProfileView:
    """Edits a variant's metadata. `role` and `key` are absent on purpose:
    live graphs bind by key, so renaming one would silently re-point them."""
    before = agent_skills_service.get_profile(session, profile_id)
    before_state = {
        "operations": list(before.operations_json),
        "is_default": before.is_default,
        "enabled": before.enabled,
    }
    row = agent_skills_service.update_profile(
        session,
        profile_id,
        display_name=payload.display_name,
        description=payload.description,
        operations=payload.operations,
        is_default=payload.is_default,
        enabled=payload.enabled,
    )
    audit.record(
        session,
        actor=user,
        action="agent_profile.update",
        target_type="agent_profile",
        target_id=row.id,
        before=before_state,
        after={
            "operations": list(row.operations_json),
            "is_default": row.is_default,
            "enabled": row.enabled,
        },
        request=request,
    )
    session.commit()
    return _profile_view(row, workflow_templates_service.profile_usage(session))


@router.post("/agent-profiles/{profile_id}/disable", response_model=AgentProfileView)
def disable_agent_profile(
    profile_id: str,
    payload: DangerousAction,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> AgentProfileView:
    """Takes a variant out of service.

    Dangerous because a graph that still binds it keeps running: the prompt
    silently falls back to the role's default. The console shows which
    operations reference a variant so this is not a blind decision.
    """
    require_confirmation(payload.confirm)
    row = agent_skills_service.update_profile(session, profile_id, enabled=False)
    audit.record(
        session,
        actor=user,
        action="agent_profile.disable",
        target_type="agent_profile",
        target_id=row.id,
        after={"role": row.role, "key": row.key, "enabled": False},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _profile_view(row, workflow_templates_service.profile_usage(session))


@router.get("/agent-skills", response_model=Page[AgentSkillView])
def list_agent_skills(
    profile_id: str, session: DbSession, user: Viewer, _: AdminRead, slot: str | None = None
) -> Page[AgentSkillView]:
    profile = agent_skills_service.get_profile(session, profile_id)
    versions = agent_skills_service.list_versions(
        session, profile_id=profile_id, slot=slot or agent_slots.primary_slot(profile.role)
    )
    return Page(items=[_skill_view(v) for v in versions])


@router.post("/agent-skills", response_model=AgentSkillView, status_code=201)
def publish_agent_skill(
    payload: AgentSkillPublishRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> AgentSkillView:
    """Publishes a new prompt version for one variant's slot and activates it.

    A rejected or unparseable safety verdict is the direct, immediate result
    of what this prompt says, so publishing it is treated with the same
    confirmation ceremony as any other dangerous admin action.
    """
    require_confirmation(payload.confirm)
    row = agent_skills_service.publish(
        session,
        profile_id=payload.profile_id,
        slot=payload.slot,
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
        after={
            "node_role": row.node_role,
            "profile_id": row.profile_id,
            "slot": row.slot,
            "version": row.version,
        },
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
        after={
            "node_role": row.node_role,
            "profile_id": row.profile_id,
            "slot": row.slot,
            "version": row.version,
            "rolled_back_from": skill_id,
        },
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
        prompt_slots=[
            PromptSlotView(key=slot.key, label=slot.label, description=slot.description)
            for slot in agent_slots.slots_for(node.role)
        ],
    )


def _profile_view(profile, usage: dict[tuple[str, str], list[str]]) -> AgentProfileView:  # type: ignore[no-untyped-def]
    return AgentProfileView(
        id=profile.id,
        role=profile.role,
        key=profile.key,
        display_name=profile.display_name,
        description=profile.description,
        operations=list(profile.operations_json),
        is_default=profile.is_default,
        enabled=profile.enabled,
        used_by_operations=usage.get((profile.role, profile.key), []),
        created_at=profile.created_at,
    )


def _skill_view(skill) -> AgentSkillView:  # type: ignore[no-untyped-def]
    return AgentSkillView(
        id=skill.id,
        node_role=skill.node_role,
        profile_id=skill.profile_id,
        slot=skill.slot,
        version=skill.version,
        prompt_template=skill.prompt_template,
        tool_grants=list(skill.tool_grants_json),
        is_active=skill.is_active,
        created_by_user_id=skill.created_by_user_id,
        reason=skill.reason,
        created_at=skill.created_at,
    )
