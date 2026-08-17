"""Test-only LLM catalog: write an endpoint, then bind default agents to it.

Product code no longer invents model names. Tests that need a working
(non-degraded) agent must put a name in `llm_providers` first.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig

TEST_LLM_MODEL = "test-llm"
TEST_LLM_ENDPOINT_ID = "test-general"


def seed_test_llm_catalog(
    session: Session,
    *,
    model: str = TEST_LLM_MODEL,
    endpoint_id: str = TEST_LLM_ENDPOINT_ID,
) -> None:
    current = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    endpoints = {
        existing_id: endpoint.model_dump(mode="json")
        for existing_id, endpoint in current.endpoints.items()
    }
    endpoints[endpoint_id] = {
        "name": "测试通用端点",
        "base_url": "https://example.invalid/v1",
        "api_key": "test-key",
        "kind": "general",
        "model": model,
        "role": "primary",
    }
    config_service.set_value(
        session,
        "llm_providers",
        {"endpoints": endpoints},
        actor_user_id=None,
        note="test catalog",
    )


def bind_default_agents_to_catalog(
    session: Session,
    *,
    model: str = TEST_LLM_MODEL,
    endpoint_id: str = TEST_LLM_ENDPOINT_ID,
) -> None:
    """Seeds nodes/profiles and pins every default agent to the endpoint
    serving `model` — the endpoint is the binding, the model comes with it."""
    agent_skills_service.ensure_default_nodes(session)
    agent_skills_service.ensure_default_profiles(session)
    seed_test_llm_catalog(session, model=model, endpoint_id=endpoint_id)
    for profile in agent_skills_service.list_profiles(session):
        if profile.is_default:
            agent_skills_service.update_profile(
                session,
                profile.id,
                default_endpoint_id=endpoint_id,
            )
