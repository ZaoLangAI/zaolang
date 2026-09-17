"""Agents, their roles, and their versioned prompts (engineering-side Agent Skill).

Distinct from the technical `AgentRunView`/`AgentUsageSummary` observation
endpoints in `observability.py`: those read what already happened, this
writes what happens next. Also distinct from the user-facing skill library
(`skill_library.py`) — this is the built-in pipeline stages' prompts, not
user-authored generation parameter templates.

Three levels, matching `app.models.agent_skills`: a *node* is a role, an
*agent* (`AgentProfile`) has one of those roles and is what a workflow node
binds by id, and a *skill* is one append-only prompt version for an
`(agent, slot)` pair.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.agents import base as agent_base
from app.agents import slots as agent_slots
from app.agents import tools as agent_tools
from app.api.deps import DbSession
from app.api.schemas.admin import (
    AgentDebugChatRequest,
    AgentDebugChatResponse,
    AgentNodeView,
    AgentProfileCreateRequest,
    AgentProfileUpdateRequest,
    AgentProfileView,
    AgentSkillPublishRequest,
    AgentSkillToolView,
    AgentSkillView,
    DangerousAction,
    PromptSlotView,
    RolePresetView,
    SkillTemplateView,
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
from app.domain.agent_skills import presets as role_presets
from app.domain.agent_skills import service as agent_skills_service
from app.domain.agent_skills import templates as skill_templates
from app.domain.audit import service as audit
from app.domain.workflow_templates import service as workflow_templates_service
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig

router = APIRouter(tags=["admin:agent-skills"])


@router.get("/agent-node-presets", response_model=Page[RolePresetView])
def list_agent_node_presets(session: DbSession, user: Viewer, _: AdminRead) -> Page[RolePresetView]:
    """The roles an operator may create an agent for.

    The console's role dropdown reads this instead of accepting free text —
    see `app.domain.agent_skills.presets` for why the catalogue lives in code.
    """
    existing_roles = {node.role for node in agent_skills_service.list_nodes(session)}
    return Page(
        items=[
            RolePresetView(
                role=preset.role,
                display_name=preset.display_name,
                category=preset.category,
                description=preset.description,
                operations=list(preset.operations),
                default_template_key=preset.default_template_key,
                sort_order=preset.sort_order,
                is_new=preset.role not in existing_roles,
            )
            for preset in role_presets.all_presets()
        ]
    )


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
    usage = workflow_templates_service.agent_usage(session)
    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    return Page(items=[_profile_view(p, usage, provider_config) for p in profiles])


@router.get("/agent-skill-tools", response_model=Page[AgentSkillToolView])
def list_agent_skill_tools(
    role: str, session: DbSession, user: Viewer, _: AdminRead
) -> Page[AgentSkillToolView]:
    """The tools a role's skill may be granted, from `AGENT_TOOL_GRANTS`.

    A role missing from the grant table has no tools of its own yet, not an
    error — the console shows an empty picker.
    """
    granted = agent_tools.AGENT_TOOL_GRANTS.get(role, frozenset())
    return Page(items=[AgentSkillToolView(name=name) for name in sorted(granted)])


@router.post("/agent-profiles", response_model=AgentProfileView, status_code=201)
def create_agent_profile(
    payload: AgentProfileCreateRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> AgentProfileView:
    """Creates an agent under one of the preset roles.

    Not a dangerous action on its own — an agent changes nothing until a
    workflow node binds it, and binding is what carries the confirmation
    ceremony. The role's `AgentNode` row is created here on first use, so
    this is also how a role that has never been used before enters the
    topology.
    """
    row = agent_skills_service.create_profile(
        session,
        role=payload.role,
        key=payload.key,
        display_name=payload.display_name,
        description=payload.description,
        operations=payload.operations,
        default_endpoint_id=payload.default_endpoint_id,
        backup_endpoint_id=payload.backup_endpoint_id,
        reasoning_model=payload.reasoning_model,
        default_for_asset_kind=payload.default_for_asset_kind,
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
    return _profile_view(
        row,
        workflow_templates_service.agent_usage(session),
        config_service.get_typed(session, "llm_providers", LlmProviderConfig),
    )


@router.patch("/agent-profiles/{profile_id}", response_model=AgentProfileView)
def update_agent_profile(
    profile_id: str,
    payload: AgentProfileUpdateRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> AgentProfileView:
    """Edits an agent's metadata. `role` and `key` are absent on purpose:
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
        default_endpoint_id=payload.default_endpoint_id,
        backup_endpoint_id=payload.backup_endpoint_id,
        reasoning_model=(
            payload.reasoning_model
            if "reasoning_model" in payload.model_fields_set
            else agent_skills_service.UNSET_BINDING
        ),
        default_for_asset_kind=(
            payload.default_for_asset_kind
            if "default_for_asset_kind" in payload.model_fields_set
            else agent_skills_service.UNSET_BINDING
        ),
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
    return _profile_view(
        row,
        workflow_templates_service.agent_usage(session),
        config_service.get_typed(session, "llm_providers", LlmProviderConfig),
    )


@router.post("/agent-profiles/{profile_id}/disable", response_model=AgentProfileView)
def disable_agent_profile(
    profile_id: str,
    payload: DangerousAction,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> AgentProfileView:
    """Takes an agent out of service.

    Dangerous because a graph that still binds it keeps running: the prompt
    silently falls back to the role's default. The console shows which
    operations reference an agent so this is not a blind decision.
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
    return _profile_view(
        row,
        workflow_templates_service.agent_usage(session),
        config_service.get_typed(session, "llm_providers", LlmProviderConfig),
    )


@router.post("/agent-profiles/{profile_id}/delete", status_code=204)
def delete_agent_profile(
    profile_id: str,
    payload: DangerousAction,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> None:
    """Hard-deletes an agent.

    Dangerous for the same reason `disable` is — a graph that still binds it
    falls back to the role's default agent — but irreversible where disable
    is not, so the console shows the same "used by" list before asking for
    the confirmation reason.
    """
    require_confirmation(payload.confirm)
    before = agent_skills_service.get_profile(session, profile_id)
    before_state = {"role": before.role, "key": before.key, "display_name": before.display_name}
    agent_skills_service.delete_profile(session, profile_id)
    audit.record(
        session,
        actor=user,
        action="agent_profile.delete",
        target_type="agent_profile",
        target_id=profile_id,
        before=before_state,
        reason=payload.reason,
        request=request,
    )
    session.commit()


@router.post("/agent-profiles/{profile_id}/debug-chat")
def debug_chat_agent_profile(
    profile_id: str,
    payload: AgentDebugChatRequest,
    session: DbSession,
    user: Operator,
    _: AdminWrite,
) -> StreamingResponse:
    """Evaluates a skill prompt — draft or published — with a real model call.

    `AdminWrite`'s rate limit is what keeps this bounded, the same way it is
    for the workflow sandbox-run endpoint this mirrors: no `DangerousAction`
    confirmation, because nothing here is written to any workflow or made
    live, but real enough to cost real tokens.
    """
    from app.api.agent_sse import SSE_HEADERS, iter_agent_sse
    from app.db import session_scope

    profile = agent_skills_service.get_profile(session, profile_id)
    chunks, finalize = agent_base.run_agent_debug_stream(
        session,
        profile=profile,
        slot=payload.slot,
        prompt_override=payload.prompt_template,
        history=[message.model_dump() for message in payload.messages],
    )

    def generate() -> Iterator[str]:
        def _finish() -> AgentDebugChatResponse:
            with session_scope() as persist:
                outcome = finalize(persist)
                persist.commit()
                return AgentDebugChatResponse(
                    reply_text=outcome.reply_text,
                    parsed_json=outcome.parsed_json,
                    degraded=outcome.degraded,
                    model=outcome.model,
                    latency_ms=outcome.latency_ms,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    agent_run_id=outcome.agent_run_id,
                )

        yield from iter_agent_sse(
            chunks,
            _finish,
            lambda body: body.model_dump(mode="json"),
        )

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/agent-skill-templates", response_model=Page[SkillTemplateView])
def list_agent_skill_templates(
    user: Viewer,
    _: AdminRead,
    category: str | None = None,
    role: str | None = None,
) -> Page[SkillTemplateView]:
    """Starting prompts for the skill editor's "fill from template" control."""
    return Page(
        items=[
            SkillTemplateView(
                key=template.key,
                label=template.label,
                description=template.description,
                category=template.category,
                prompt_template=template.prompt_template,
                tool_grants=list(template.tool_grants),
                role=template.role,
                slot=template.slot,
                asset_kind=template.asset_kind,
            )
            for template in skill_templates.templates_for(category=category, role=role)
        ]
    )


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
    """Publishes a new prompt version for one agent's slot and activates it.

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
        category=node.category or role_presets.category_for(node.role),
        enabled=node.enabled,
        sort_order=node.sort_order,
        candidate_endpoint_ids=candidates,
        prompt_slots=[
            PromptSlotView(key=slot.key, label=slot.label, description=slot.description)
            for slot in agent_slots.slots_for(node.role)
        ],
    )


def _profile_view(  # type: ignore[no-untyped-def]
    profile,
    usage: dict[str, list[str]],
    provider_config: LlmProviderConfig,
) -> AgentProfileView:
    # Read-only: the agent binds a provider, and the provider names the model.
    bound = provider_config.endpoints.get(profile.default_endpoint_id or "")
    return AgentProfileView(
        id=profile.id,
        role=profile.role,
        key=profile.key,
        display_name=profile.display_name,
        description=profile.description,
        category=role_presets.category_for(profile.role),
        operations=list(profile.operations_json),
        is_default=profile.is_default,
        default_for_asset_kind=profile.default_for_asset_kind,
        enabled=profile.enabled,
        default_endpoint_id=profile.default_endpoint_id,
        backup_endpoint_id=profile.backup_endpoint_id,
        model=bound.model if bound is not None else None,
        max_tokens=profile.max_tokens,
        temperature=(
            None if profile.temperature_milli is None else profile.temperature_milli / 1000
        ),
        reasoning_model=profile.reasoning_model,
        used_by_operations=usage.get(profile.id, []),
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
