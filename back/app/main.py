"""FastAPI application factory.

The product API is built first and then handed to Agno's `AgentOS` as its base
app. Doing it in that order keeps `/v1` the stable public contract: agents are
mounted alongside it rather than the API being generated from them.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationMiddleware, SecurityHeadersMiddleware
from app.api.v1 import (
    admin,
    asset_derive,
    asset_graph,
    asset_variants,
    auth,
    blocking,
    canvas,
    character_voices,
    characters,
    community,
    credits,
    devices,
    distribution,
    drafts,
    editor,
    gateway,
    jobs,
    learning,
    look_fill,
    privacy,
    profiles,
    prompts,
    props,
    scene_matrix,
    scenes,
    scripts,
    shortform,
    skills,
    style_gallery,
    uploads,
    works,
)
from app.config import get_settings
from app.observability.logging import configure_logging
from app.observability.tracing import configure_tracing

API_PREFIX = "/v1"
logger = logging.getLogger(__name__)


def build_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(auth.router)
    router.include_router(profiles.router)
    router.include_router(works.router)
    router.include_router(learning.router)
    router.include_router(skills.router)
    router.include_router(drafts.router)
    router.include_router(jobs.router)
    router.include_router(prompts.router)
    router.include_router(shortform.router)
    router.include_router(characters.router)
    router.include_router(character_voices.router)
    router.include_router(scenes.router)
    router.include_router(props.router)
    router.include_router(asset_variants.router)
    router.include_router(asset_graph.router)
    router.include_router(asset_derive.router)
    router.include_router(look_fill.router)
    router.include_router(scene_matrix.router)
    router.include_router(gateway.router)
    router.include_router(uploads.router)
    router.include_router(credits.router)
    router.include_router(community.router)
    router.include_router(style_gallery.router)
    router.include_router(privacy.router)
    router.include_router(devices.router)
    router.include_router(editor.router)
    router.include_router(canvas.router)
    router.include_router(scripts.router)
    router.include_router(blocking.router)
    router.include_router(distribution.router)
    router.include_router(admin.router)
    return router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(app)
    # Production never runs seed, and a local seed against a shared COS bucket
    # used to replace the whole CORS list. Merge this process's origins in on
    # every boot; a storage blip must not take the API down with it.
    try:
        from app.storage import s3

        s3.ensure_bucket()
    except Exception:
        logger.warning(
            "could not ensure object-store bucket/CORS on startup",
            exc_info=True,
        )
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

    from app.mcp.server import router as mcp_router

    app.include_router(mcp_router)

    from app.api import health

    app.include_router(health.router)

    from app.agents.agent_os import mount_agent_os

    return mount_agent_os(app)


app = create_app()
