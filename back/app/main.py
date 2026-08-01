"""FastAPI application factory.

The product API is built first and then handed to Agno's `AgentOS` as its base
app. Doing it in that order keeps `/v1` the stable public contract: agents are
mounted alongside it rather than the API being generated from them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationMiddleware, SecurityHeadersMiddleware
from app.api.v1 import (
    admin,
    auth,
    community,
    credits,
    drafts,
    gateway,
    jobs,
    privacy,
    profiles,
    uploads,
    works,
)
from app.config import get_settings
from app.observability.logging import configure_logging
from app.observability.tracing import configure_tracing

API_PREFIX = "/v1"


def build_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(auth.router)
    router.include_router(profiles.router)
    router.include_router(works.router)
    router.include_router(drafts.router)
    router.include_router(jobs.router)
    router.include_router(gateway.router)
    router.include_router(uploads.router)
    router.include_router(credits.router)
    router.include_router(community.router)
    router.include_router(privacy.router)
    router.include_router(admin.router)
    return router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(app)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="造浪 zaolang API",
        version=settings.app_version,
        description="全球 AI 二创共享平台的公开接口。",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "retry-after"],
    )

    register_exception_handlers(app)
    app.include_router(build_router())

    from app.api import health

    app.include_router(health.router)

    from app.agents.agent_os import mount_agent_os

    return mount_agent_os(app)


app = create_app()
