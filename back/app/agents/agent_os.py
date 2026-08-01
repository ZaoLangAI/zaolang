"""Agno AgentOS mounted on top of the product API.

The FastAPI app built by `create_app` is handed to `AgentOS` as its `base_app`
rather than the other way round. That ordering is what keeps `/v1` the stable
public contract: the agent console is mounted alongside it, and a route
conflict resolves in favour of the product API instead of silently shadowing an
endpoint clients depend on.

Mounting is opt-in (`AGENT_OS_ENABLED`) because the console is an operator
tool: it exposes model bindings and lets a human drive agents interactively,
which is useful in development and during incidents but is not something to
expose by default.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def mount_agent_os(app: FastAPI) -> FastAPI:
    """Wraps the product app with AgentOS, or returns it untouched.

    A failure here must never take the product API down: the console is
    auxiliary, so a broken agent definition degrades to "no console" rather
    than "no service".
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.agent_os_enabled:
        return app

    try:
        from agno.os import AgentOS

        from app.db import get_session_factory
        from app.teams import build_generation_gateway_team

        session = get_session_factory()()
        try:
            team = build_generation_gateway_team(session)
        finally:
            session.close()

        agent_os: Any = AgentOS(
            name="zaolang-agent-os",
            description="造浪智能网关运维控制台",
            version=settings.app_version,
            teams=[team],
            base_app=app,
            # The product contract wins: an agent route must never shadow /v1.
            on_route_conflict="preserve_base_app",
            telemetry=False,
        )
        return agent_os.get_app()
    except Exception:
        logger.exception("could not mount AgentOS; continuing with the product API only")
        return app
