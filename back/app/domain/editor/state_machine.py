"""Conditional status transitions for editor aggregates."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import rows_affected
from app.domain.errors import InvalidJobTransition, NotFound, OperationTerminal
from app.models import DeliveryVariant, EditorExport, EditPlan, EpisodeCut
from app.models.enums import (
    DELIVERY_VARIANT_TRANSITIONS,
    EDIT_PLAN_TRANSITIONS,
    EDITOR_EXPORT_TRANSITIONS,
    EPISODE_CUT_TRANSITIONS,
    TERMINAL_EDIT_PLAN_STATUSES,
    TERMINAL_EDITOR_EXPORT_STATUSES,
    DeliveryVariantStatus,
    EditorExportStatus,
    EditPlanStatus,
    EpisodeCutStatus,
)


def transition_cut(session: Session, cut_id: str, target: EpisodeCutStatus) -> EpisodeCut:
    sources = [
        status.value for status, allowed in EPISODE_CUT_TRANSITIONS.items() if target in allowed
    ]
    matched = rows_affected(
        session,
        update(EpisodeCut)
        .where(EpisodeCut.id == cut_id, EpisodeCut.status.in_(sources))
        .values(status=target.value),
    )
    if matched != 1:
        cut = session.get(EpisodeCut, cut_id)
        if cut is None:
            raise NotFound("剪辑不存在。")
        raise InvalidJobTransition(f"剪辑状态 {cut.status} 不能迁移到 {target.value}。")
    session.expire_all()
    cut = session.get(EpisodeCut, cut_id)
    assert cut is not None
    return cut


def transition_plan(session: Session, plan_id: str, target: EditPlanStatus) -> EditPlan:
    sources = [
        status.value for status, allowed in EDIT_PLAN_TRANSITIONS.items() if target in allowed
    ]
    matched = rows_affected(
        session,
        update(EditPlan)
        .where(EditPlan.id == plan_id, EditPlan.status.in_(sources))
        .values(status=target.value),
    )
    if matched != 1:
        plan = session.get(EditPlan, plan_id)
        if plan is None:
            raise NotFound("剪辑方案不存在。")
        if EditPlanStatus(plan.status) in TERMINAL_EDIT_PLAN_STATUSES:
            raise OperationTerminal()
        raise InvalidJobTransition(f"方案状态 {plan.status} 不能迁移到 {target.value}。")
    session.expire_all()
    plan = session.get(EditPlan, plan_id)
    assert plan is not None
    return plan


def transition_variant(
    session: Session, variant_id: str, target: DeliveryVariantStatus
) -> DeliveryVariant:
    sources = [
        status.value
        for status, allowed in DELIVERY_VARIANT_TRANSITIONS.items()
        if target in allowed
    ]
    matched = rows_affected(
        session,
        update(DeliveryVariant)
        .where(DeliveryVariant.id == variant_id, DeliveryVariant.status.in_(sources))
        .values(status=target.value),
    )
    if matched != 1:
        variant = session.get(DeliveryVariant, variant_id)
        if variant is None:
            raise NotFound("交付变体不存在。")
        raise InvalidJobTransition(f"变体状态 {variant.status} 不能迁移到 {target.value}。")
    session.expire_all()
    variant = session.get(DeliveryVariant, variant_id)
    assert variant is not None
    return variant


def transition_export(
    session: Session, export_id: str, target: EditorExportStatus, **values: object
) -> EditorExport:
    sources = [
        status.value for status, allowed in EDITOR_EXPORT_TRANSITIONS.items() if target in allowed
    ]
    payload = {"status": target.value, **values}
    matched = rows_affected(
        session,
        update(EditorExport)
        .where(EditorExport.id == export_id, EditorExport.status.in_(sources))
        .values(**payload),
    )
    if matched != 1:
        export = session.get(EditorExport, export_id)
        if export is None:
            raise NotFound("导出任务不存在。")
        if EditorExportStatus(export.status) in TERMINAL_EDITOR_EXPORT_STATUSES:
            raise OperationTerminal()
        raise InvalidJobTransition(f"导出状态 {export.status} 不能迁移到 {target.value}。")
    session.expire_all()
    export = session.get(EditorExport, export_id)
    assert export is not None
    return export
