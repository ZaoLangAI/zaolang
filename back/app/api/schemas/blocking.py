"""白膜 (blockout) request/response models.

The document models mirror what `app.domain.blocking.sanitize` writes —
they exist so the OpenAPI schema (and the frontend's generated types)
carries the closed vocabularies as unions. The request models live in
`app.api.schemas.script` (they reference `ScriptDocument`, which in turn
embeds `BlockingState`) and take the document as a loose dict on purpose:
the sanitizer, not Pydantic, is the one validator.
"""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.domain.blocking.vocabulary import (
    BlockingAspectRatio,
    CameraHeight,
    CameraMove,
    CameraSide,
    CastAction,
    ColorRole,
    Ground,
    MoveEase,
    Primitive,
    ShotSize,
    ShotTransition,
)


class BlockingProp(ApiModel):
    id: str
    primitive: Primitive
    label: str = ""
    color_role: ColorRole
    position: list[float]
    rotation_y_deg: float = 0.0
    scale: list[float]


class BlockingAnchor(ApiModel):
    id: str
    label: str = ""
    x: float
    z: float


class BlockingSet(ApiModel):
    id: str
    heading: str
    ground: Ground
    width_m: float
    depth_m: float
    props: list[BlockingProp] = Field(default_factory=list)
    anchors: list[BlockingAnchor] = Field(default_factory=list)


class BlockingCastMember(ApiModel):
    id: str
    name: str
    character_ref_id: str | None = None
    color_index: int
    height_m: float


class BlockingMark(ApiModel):
    anchor: str | None = None
    x: float
    z: float


class BlockingFacing(ApiModel):
    # A cast id, an anchor id, or `camera`; `None` means use `deg`.
    target: str | None = None
    deg: float = 0.0


class BlockingStartEntry(ApiModel):
    cast_id: str
    at: BlockingMark
    face: BlockingFacing
    action: CastAction


class BlockingBeat(ApiModel):
    cast_id: str
    t0: float
    t1: float
    action: CastAction
    to: BlockingMark | None = None
    face: BlockingFacing | None = None


class BlockingCameraMove(ApiModel):
    preset: CameraMove
    intensity: float
    ease: MoveEase


class BlockingShot(ApiModel):
    # Seconds into the segment where this shot starts; the first is 0.
    t0: float = 0.0
    transition: ShotTransition = "cut"
    size: ShotSize
    lens_mm: int
    height: CameraHeight
    side: CameraSide
    subject: str | None = None
    over: str | None = None
    move: BlockingCameraMove


class BlockingCameraPose(ApiModel):
    position: list[float]
    target: list[float]
    fov: float


class BlockingCameraOverride(ApiModel):
    start: BlockingCameraPose
    end: BlockingCameraPose | None = None


class BlockingSegment(ApiModel):
    key: str
    heading: str
    set_id: str
    source_hash: str
    duration_s: int
    start: list[BlockingStartEntry] = Field(default_factory=list)
    beats: list[BlockingBeat] = Field(default_factory=list)
    # In time order, first at t0=0; a manual `camera_override` replaces all.
    shots: list[BlockingShot] = Field(min_length=1)
    camera_override: BlockingCameraOverride | None = None


class BlockingDocument(ApiModel):
    version: int
    script_hash: str
    target_duration_s: int
    aspect_ratio: BlockingAspectRatio
    sets: list[BlockingSet] = Field(default_factory=list)
    cast: list[BlockingCastMember] = Field(default_factory=list)
    segments: list[BlockingSegment] = Field(default_factory=list)


class BlockingState(ApiModel):
    document: BlockingDocument | None = None
    # 0 until the first build. Echoed back as `base_version_no` on every
    # manual save, which 409s when another tab or a chat turn got there first.
    version_no: int = 0
    stale: bool = False
    stale_segment_keys: list[str] = Field(default_factory=list)
    duration_warning: str | None = None
    target_duration_seconds: int | None = None
    default_target_duration_seconds: int = 0


class BlockingVersionResponse(ApiModel):
    version_no: int
    origin: str
    summary: str
    turn_id: str | None = None
    document: BlockingDocument
