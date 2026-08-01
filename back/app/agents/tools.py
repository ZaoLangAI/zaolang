"""The only functions an agent is allowed to call.

An agent's output is a suggestion, never a fact. These tools are therefore all
read-only or advisory: they let an agent look things up and price things, but
nothing here moves credits, changes visibility, publishes a work or overrides a
moderation verdict. Those transitions belong to the domain services, which the
worker calls directly after deciding what to trust.

Adding a tool that mutates state would let a prompt injection spend a user's
credits, so the whitelist is enforced structurally: `TOOL_REGISTRY` is the
complete set, and `build_toolkit` refuses anything outside it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.router import PROVIDER_CATALOG
from app.domain.jobs import service as jobs_service
from app.models import Tag, Work, WorkVersion
from app.models.enums import LifecycleStatus, Visibility

logger = logging.getLogger(__name__)


def price_operation(
    session: Session, operation: str, quality_tier: str, duration_seconds: int = 0
) -> dict[str, Any]:
    """Prices a hypothetical job. Advisory only: no credits move."""
    quote = jobs_service.quote_for(
        session,
        operation=operation,
        quality_tier=quality_tier,
        duration_seconds=duration_seconds,
    )
    return {
        "credits": quote.credits,
        "estimated_seconds": quote.estimated_seconds,
        "breakdown": quote.breakdown,
    }


def list_provider_capabilities(session: Session) -> list[dict[str, Any]]:
    """Describes what each route can do, so a planner does not propose an
    operation nothing supports."""
    return [
        {
            "provider": capability.name,
            "kind": capability.kind.value,
            "operations": sorted(capability.operations),
            "tiers": sorted(capability.tiers),
        }
        for capability in sorted(PROVIDER_CATALOG.values(), key=lambda c: c.name)
    ]


def lookup_source_parameters(session: Session, work_version_id: str) -> dict[str, Any]:
    """Returns the reusable parameters of a published version.

    Only versions whose work is public and remixable are readable here: an
    agent must not become a way to read parameters the viewer could not see
    through the API.
    """
    version = session.get(WorkVersion, work_version_id)
    if version is None:
        return {"found": False}

    work = session.get(Work, version.work_id)
    if (
        work is None
        or work.lifecycle_status != LifecycleStatus.ACTIVE
        or work.visibility != Visibility.PUBLIC_REMIXABLE
    ):
        return {"found": False}

    return {"found": True, "parameters": dict(version.reusable_params_json or {})}


def suggest_tags(session: Session, keywords: list[str], limit: int = 8) -> list[dict[str, Any]]:
    """Maps free text onto tags that already exist.

    Returning existing tags rather than inventing new ones keeps the taxonomy
    from fragmenting into near-duplicates.
    """
    if not keywords:
        return []
    clauses = [Tag.slug.ilike(f"%{k.strip().lower()}%") for k in keywords if k.strip()]
    if not clauses:
        return []

    from sqlalchemy import or_

    rows = session.scalars(
        select(Tag).where(or_(*clauses)).order_by(Tag.usage_count.desc()).limit(limit)
    )
    return [
        {"slug": tag.slug, "label": tag.label_en, "usage_count": tag.usage_count} for tag in rows
    ]


# The complete set. Anything not listed here cannot be handed to an agent.
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "price_operation": price_operation,
    "list_provider_capabilities": list_provider_capabilities,
    "lookup_source_parameters": lookup_source_parameters,
    "suggest_tags": suggest_tags,
}

# Which agent may use which tool. Safety gets nothing: a content judgement must
# not depend on anything a prompt could steer.
AGENT_TOOL_GRANTS: dict[str, frozenset[str]] = {
    "safety": frozenset(),
    "planner": frozenset(
        {"price_operation", "list_provider_capabilities", "lookup_source_parameters"}
    ),
    "quality": frozenset(),
    "copy": frozenset({"suggest_tags"}),
}


class UnknownToolError(LookupError):
    """Raised when something outside the whitelist is requested."""


def build_toolkit(session: Session, agent_name: str) -> dict[str, Callable[..., Any]]:
    """Binds the tools an agent is allowed to use to a database session.

    The session is closed over rather than passed by the model, so an agent
    cannot reach a different transaction than the one its caller opened.
    """
    granted = AGENT_TOOL_GRANTS.get(agent_name)
    if granted is None:
        raise UnknownToolError(f"未知的智能体: {agent_name}")

    unknown = granted - set(TOOL_REGISTRY)
    if unknown:  # pragma: no cover - guards against a typo in the grants table
        raise UnknownToolError(f"未注册的工具: {sorted(unknown)}")

    def bind(func: Callable[..., Any]) -> Callable[..., Any]:
        def bound(**kwargs: Any) -> Any:
            return func(session, **kwargs)

        bound.__name__ = func.__name__
        bound.__doc__ = func.__doc__
        return bound

    return {name: bind(TOOL_REGISTRY[name]) for name in sorted(granted)}


def call_tool(session: Session, agent_name: str, tool_name: str, **kwargs: Any) -> Any:
    """Invokes one whitelisted tool on behalf of an agent."""
    toolkit = build_toolkit(session, agent_name)
    tool = toolkit.get(tool_name)
    if tool is None:
        raise UnknownToolError(f"智能体 {agent_name} 无权调用 {tool_name}。")
    logger.debug("agent %s calling tool %s", agent_name, tool_name)
    return tool(**kwargs)
