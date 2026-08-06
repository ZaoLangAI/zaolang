"""Back-office API.

Everything under `/v1/admin` is a separate security domain: its own session
audience, its own rate-limit buckets and its own RBAC ladder. A consumer token
is rejected here even when it belongs to a user who happens to hold an admin
role.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin import (
    agent_skills,
    auth,
    config,
    content,
    data,
    jobs,
    learning,
    ledger,
    llm_providers,
    logs,
    observability,
    redemption,
    skill_library,
    users,
    workflow_templates,
)

router = APIRouter(prefix="/admin")
router.include_router(auth.router)
router.include_router(observability.router)
router.include_router(jobs.router)
router.include_router(content.router)
router.include_router(learning.router)
router.include_router(users.router)
router.include_router(ledger.router)
router.include_router(redemption.router)
router.include_router(config.router)
router.include_router(logs.router)
router.include_router(llm_providers.router)
router.include_router(agent_skills.router)
router.include_router(skill_library.router)
router.include_router(workflow_templates.router)
router.include_router(data.router)

__all__ = ["router"]
