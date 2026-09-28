"""Remote MCP Streamable HTTP endpoint. No publish tool, no consumer tokens."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.domain.editor import analysis as media_analysis
from app.domain.editor import document as docs
from app.domain.editor import exports as export_service
from app.domain.editor import flags as editor_flags
from app.domain.editor import service as editor_service
from app.domain.errors import DomainError, ProjectForbidden, ValidationFailed
from app.mcp.auth import (
    McpPrincipal,
    decode_mcp_token,
    require_project,
    require_scope,
)
from app.models import Asset, EditorExport, EditPlan, MediaAnalysis
from app.observability.context import get_request_id
from app.workers.celery_app import celery_app

router = APIRouter(tags=["mcp"])

PROTOCOL_LATEST = "2026-07-28"
PROTOCOL_COMPAT = "2025-11-25"

TOOLS = (
    ("drama.list_series", "drama:read"),
    ("drama.get_episode", "drama:read"),
    ("editor.create_cut", "editor:write"),
    ("editor.get_timeline_summary", "editor:read"),
    ("editor.generate_edit_plan", "editor:write"),
    ("editor.apply_edit_plan", "editor:write"),
    ("editor.reject_edit_plan", "editor:write"),
    ("editor.create_variants", "editor:write"),
    ("editor.queue_exports", "editor:export"),
    ("editor.get_operation", "editor:read"),
    ("editor.cancel_operation", "editor:export"),
    ("editor.request_transcription", "editor:write"),
)


def _jsonrpc_result(request_id: object, result: object) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(
    request_id: object, code: int, message: str, data: object | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    session: DbSession,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    body = await request.json()
    request_id = body.get("id")
    method = str(body.get("method") or "")
    params = body.get("params") or {}
    token = _bearer(authorization)
    if method == "initialize":
        client_protocol = str(params.get("protocolVersion") or PROTOCOL_LATEST)
        protocol = (
            client_protocol
            if client_protocol in {PROTOCOL_LATEST, PROTOCOL_COMPAT}
            else PROTOCOL_LATEST
        )
        return JSONResponse(
            _jsonrpc_result(
                request_id,
                {
                    "protocolVersion": protocol,
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "zaolang-drama-editor", "version": "1.0.0"},
                },
            )
        )
    if method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "result": {}})
    if token is None:
        return JSONResponse(
            _jsonrpc_error(request_id, -32001, "UNAUTHENTICATED"),
            status_code=401,
        )
    try:
        principal = decode_mcp_token(session, token)
        editor_flags.require_flag(session, editor_flags.FLAG_MCP, user_id=principal.user_id)
        result = _dispatch(
            session,
            principal,
            method,
            params if isinstance(params, dict) else {},
        )
        session.commit()
    except DomainError as exc:
        code = "UNAUTHENTICATED" if exc.code == "AUTH_REQUIRED" else exc.code
        return JSONResponse(
            _jsonrpc_error(
                request_id,
                -32000,
                code,
                {"message": exc.message, "request_id": get_request_id()},
            ),
            status_code=exc.http_status,
        )
    return JSONResponse(_jsonrpc_result(request_id, result))


def _dispatch(
    session: Session, principal: McpPrincipal, method: str, params: dict[str, Any]
) -> Any:
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": name,
                    "description": name,
                    "inputSchema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["project_id"],
                        "properties": {"project_id": {"type": "string"}},
                    },
                }
                for name, _scope in TOOLS
            ]
        }
    if method == "resources/list":
        project = principal.series_id
        return {
            "resources": [
                {
                    "uri": f"zaolang://projects/{project}/drama",
                    "name": "drama",
                    "mimeType": "application/json",
                },
                {
                    "uri": f"zaolang://projects/{project}/episodes",
                    "name": "episodes",
                    "mimeType": "application/json",
                },
            ]
        }
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        project = principal.series_id
        prefix = f"zaolang://projects/{project}/"
        if not uri.startswith(prefix):
            raise ProjectForbidden()
        series = editor_service.require_drama_series(
            session, user_id=principal.user_id, series_id=project
        )
        if uri.endswith("/drama"):
            body = {
                "id": series.id,
                "title": series.title,
                "kind": series.kind,
                "allow_external_models": series.allow_external_models,
            }
        elif uri.endswith("/episodes"):
            episodes = editor_service.list_episodes(
                session, user_id=principal.user_id, series_id=project
            )
            body = {
                "items": [
                    {
                        "id": item.id,
                        "episode_number": item.episode_number,
                        "title": item.title,
                        "status": item.status,
                    }
                    for item in episodes
                ]
            }
        elif "/cuts/" in uri and uri.endswith("/timeline"):
            cut_id = uri.rsplit("/cuts/", 1)[-1].removesuffix("/timeline")
            cut = editor_service._owned_cut(session, user_id=principal.user_id, cut_id=cut_id)
            head = editor_service.head_revision(session, cut)
            if head is None:
                raise ValidationFailed("剪辑还没有修订。")
            body = docs.timeline_summary(head.document_json)
        else:
            raise ValidationFailed("未知资源。")
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(body, ensure_ascii=False),
                }
            ]
        }
    if method == "prompts/list":
        return {
            "prompts": [
                {"name": "short_drama_edit_plan"},
                {"name": "short_drama_trailer_plan"},
                {"name": "delivery_variant_review"},
            ]
        }
    if method == "prompts/get":
        name = str(params.get("name") or "")
        return {
            "description": name,
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": json.dumps(params, ensure_ascii=False)},
                }
            ],
        }
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValidationFailed("工具参数必须是对象。")
        payload = _call_tool(session, principal, name, arguments)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False),
                }
            ]
        }
    raise ValidationFailed(f"不支持的 MCP 方法: {method}。")


def _call_tool(
    session: Session, principal: McpPrincipal, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    if name == "publish" or name.endswith(".publish"):
        raise ValidationFailed("MCP 不提供发布工具。")
    scope = dict(TOOLS).get(name)
    if scope is None:
        raise ValidationFailed(f"未知工具: {name}。")
    require_scope(principal, scope)
    project_id = str(arguments.get("project_id") or "")
    require_project(principal, project_id)
    extra = {key: value for key, value in arguments.items() if key != "project_id"}
    extra["input_hash"] = hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if name == "drama.list_series":
        rows = editor_service.list_drama_series(session, user_id=principal.user_id)
        return {"items": [{"id": row.id, "title": row.title} for row in rows]}
    if name == "drama.get_episode":
        episode = editor_service._owned_episode(
            session, user_id=principal.user_id, episode_id=str(arguments["episode_id"])
        )
        return {
            "id": episode.id,
            "series_id": episode.series_id,
            "episode_number": episode.episode_number,
            "title": episode.title,
        }
    if name == "editor.create_cut":
        cut, revision = editor_service.create_cut_from_asset(
            session,
            user_id=principal.user_id,
            episode_id=str(arguments["episode_id"]),
            asset_id=str(arguments["asset_id"]),
            job_id=arguments.get("job_id"),
        )
        return {"cut_id": cut.id, "revision_id": revision.id}
    if name == "editor.get_timeline_summary":
        cut = editor_service._owned_cut(
            session, user_id=principal.user_id, cut_id=str(arguments["cut_id"])
        )
        head = editor_service.head_revision(session, cut)
        if head is None:
            raise ValidationFailed("剪辑还没有修订。")
        return docs.timeline_summary(head.document_json)
    if name == "editor.generate_edit_plan":
        from app.agents import editor_planner

        editor_flags.require_flag(session, editor_flags.FLAG_AI, user_id=principal.user_id)
        cut = editor_service._owned_cut(
            session, user_id=principal.user_id, cut_id=str(arguments["cut_id"])
        )
        head = editor_service.head_revision(session, cut)
        if head is None:
            raise ValidationFailed("剪辑还没有修订。")
        outcome = editor_planner.plan_timeline(
            session,
            user_id=principal.user_id,
            cut=cut,
            revision=head,
            goal=str(arguments.get("goal") or ""),
            max_commands=int(arguments.get("max_commands") or 40),
        )
        plan = editor_service.create_edit_plan(
            session,
            user_id=principal.user_id,
            cut_id=cut.id,
            goal=str(arguments.get("goal") or ""),
            commands=list(outcome.data.get("commands") or []),
            summary=str(outcome.data.get("summary") or ""),
            agent_run_id=outcome.agent_run_id,
            model=outcome.model,
        )
        return {"plan_id": plan.id, "operation_id": plan.id, "status": plan.status}
    if name == "editor.apply_edit_plan":
        revision = editor_service.apply_edit_plan(
            session,
            user_id=principal.user_id,
            plan_id=str(arguments["plan_id"]),
            lease_id=str(arguments["lease_id"]),
            lease_token=str(arguments["lease_token"]),
            selected_indexes=arguments.get("selected_indexes"),
        )
        return {"revision_id": revision.id, "revision_no": revision.revision_no}
    if name == "editor.reject_edit_plan":
        plan = editor_service.reject_edit_plan(
            session, user_id=principal.user_id, plan_id=str(arguments["plan_id"])
        )
        return {"plan_id": plan.id, "status": plan.status}
    if name == "editor.create_variants":
        variants = editor_service.create_variants(
            session,
            user_id=principal.user_id,
            revision_id=str(arguments["revision_id"]),
            profile_keys=list(arguments.get("profile_keys") or []),
        )
        return {"variant_ids": [item.id for item in variants]}
    if name == "editor.queue_exports":
        exports = export_service.queue_exports(
            session,
            user_id=principal.user_id,
            variant_ids=list(arguments.get("variant_ids") or []),
            operation_key=arguments.get("operation_key"),
        )
        return {
            "export_ids": [item.id for item in exports],
            "operation_id": exports[0].id if exports else None,
        }
    if name == "editor.get_operation":
        operation_id = str(arguments["operation_id"])
        if operation_id.startswith("exp_"):
            export = session.get(EditorExport, operation_id)
            if export is None:
                raise ValidationFailed("操作不存在。")
            return {
                "id": export.id,
                "kind": "export",
                "status": export.status,
                "progress": export.progress,
            }
        if operation_id.startswith("epl_"):
            edit_plan = session.get(EditPlan, operation_id)
            if edit_plan is None:
                raise ValidationFailed("操作不存在。")
            return {"id": edit_plan.id, "kind": "edit_plan", "status": edit_plan.status}
        if operation_id.startswith("man_"):
            analysis = session.get(MediaAnalysis, operation_id)
            if analysis is None:
                raise ValidationFailed("操作不存在。")
            result: dict[str, Any] = {}
            if analysis.status in {"succeeded", "degraded"}:
                asset = session.get(Asset, analysis.asset_id)
                if asset is not None and asset.owner_user_id == principal.user_id:
                    result = {"transcript": analysis.transcript_json}
            return {
                "id": analysis.id,
                "kind": "media_analysis",
                "status": analysis.status,
                **result,
            }
        raise ValidationFailed("操作不存在。")
    if name == "editor.cancel_operation":
        export = export_service.request_cancel(
            session, user_id=principal.user_id, export_id=str(arguments["operation_id"])
        )
        return {"id": export.id, "status": export.status}
    if name == "editor.request_transcription":
        # AI-triggerable, but this only ever produces a draft transcript to
        # review — there is no tool here (or anywhere else in this MCP
        # surface) that turns it into real caption elements on its own. A
        # human must review and confirm it in the editor's own review UI
        # before it becomes `insert_caption` commands; see
        # `zaolang-editor-drama`'s invariant on this.
        asset_id = str(arguments["asset_id"])
        asset = session.get(Asset, asset_id)
        if asset is None or asset.owner_user_id != principal.user_id:
            raise ValidationFailed("素材不存在。")
        row = media_analysis.enqueue_transcription(session, asset_id=asset_id)
        session.commit()
        celery_app.send_task("app.workers.tasks.run_editor_transcription", args=[row.id])
        return {"id": row.id, "kind": "media_analysis", "status": row.status}
    raise ValidationFailed(f"未知工具: {name}。")
