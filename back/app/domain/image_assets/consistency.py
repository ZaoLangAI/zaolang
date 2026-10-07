"""Vision consistency judge for character / scene / prop card images (P3-1).

`score()` sends the card's anchor (image 1) and one generated image (image 2)
to the `quality` role's `consistency` slot and turns the reply into a
`ConsistencyResult`: a 0–100 integer per rubric dimension, a Python-weighted
integer total and a short issue list. It only scores — what the score does to
the write-back (`asset_output_link`, P3-3) is decided by the caller.

Rules that hold for every call:

- Never raises. A broken judge must not cost the user their image: any
  failure comes back as `status="failed"` and the write-back goes on (the
  same stance as `app.agents.quality.FALLBACK`).
- The call is a platform cost: it is recorded on `AgentRun.cost_micro_usd`
  like every agent turn and never touches the user's credits.
- The rubric lives here, not in the prompt: the published system prompt is
  generic, and each call's user message names the dimensions to score and
  what to ignore. Bump `RUBRIC_VERSION` whenever a dimension or weight
  changes, so calibration reports (P3-5) never mix two rubrics.
"""

from __future__ import annotations

import base64
import io
import logging
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from PIL import Image
from sqlalchemy.orm import Session

from app.agents import quality as quality_agent
from app.agents.base import run_agent
from app.agents.slots import CONSISTENCY_SLOT
from app.domain.agent_skills import service as agent_skills_service
from app.domain.asset_variants import service as asset_variants_service
from app.domain.errors import NoCapableEndpoint
from app.domain.image_assets.vocabulary import SCENE_PRESET_AXES, scene_presets_from
from app.models import Asset, CreationSkill, SkillAssetEntry, SkillAssetVariant
from app.models.enums import AgentName, AssetEntryType, MediaType
from app.storage import s3

logger = logging.getLogger(__name__)

RUBRIC_VERSION = 1

DEFAULT_MAX_IMAGE_PX = 1024
JPEG_QUALITY = 85
MAX_ISSUES = 5
MAX_ISSUE_LEN = 60
# A verdict is a short JSON object; this only lifts an undeclared endpoint's
# generic budget (a reasoning model still gets its own margin on top).
JUDGE_MAX_TOKENS = 1024
# A judge should give the same image the same score; operators tune the
# model, not the creativity.
JUDGE_TEMPERATURE = 0.0

# The user message spells the requested keys out on one machine-readable
# line as well, so the offline test gateway can answer without parsing
# Chinese prose.
DIMENSION_KEYS_PREFIX = "维度键："

STATUS_SCORED = "scored"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

SKIP_NO_ANCHOR = "no_anchor"
SKIP_OUTPUT_IS_ANCHOR = "output_is_anchor"
SKIP_PANORAMA = "panorama"
SKIP_VIDEO = "video"
SKIP_NO_VISION_ENDPOINT = "no_vision_endpoint"

ERROR_IMAGE_UNREADABLE = "image_unreadable"
ERROR_LLM = "llm_error"
ERROR_PARSE = "parse_failed"
ERROR_INTERNAL = "internal_error"


@dataclass(frozen=True, slots=True)
class Dimension:
    key: str
    label: str
    # Percent. Integers so the weighted total is exact; a dropped dimension
    # renormalises over what is left (`_weighted_total`).
    weight: int


RUBRICS: dict[str, tuple[Dimension, ...]] = {
    "character": (
        Dimension("face", "五官与脸型", 35),
        Dimension("hair", "发型发色", 20),
        Dimension("body", "肤色与体型", 15),
        Dimension("medium", "画风与媒介", 15),
        Dimension("outfit", "服装", 15),
    ),
    "scene": (
        Dimension("layout", "空间结构与布局", 40),
        Dimension("furnishings", "关键陈设", 30),
        Dimension("material", "材质与年代", 20),
        Dimension("medium", "画风", 10),
    ),
    "prop": (
        Dimension("silhouette", "外形轮廓", 40),
        Dimension("material", "材质", 25),
        Dimension("palette", "配色与纹样", 20),
        Dimension("details", "标志性细节", 15),
    ),
}
OUTFIT_DIMENSION = "outfit"

_KIND_NOUNS = {"character": "角色", "scene": "场景", "prop": "道具"}
_ALWAYS_IGNORED: dict[str, tuple[str, ...]] = {
    "character": ("表情", "姿态", "机位", "背景"),
    "scene": ("机位",),
    "prop": ("机位",),
}
_SCENE_AXIS_LABELS = {"lighting": "光照", "weather": "天气", "state": "状态", "period": "年代"}
_SHEET_NOTES = {
    AssetEntryType.EXPRESSION_SHEET.value: (
        "是表情合集（多格）：按整张评，只看每格人物的身份特征，忽略表情差异和分格布局。"
    ),
    AssetEntryType.CHARACTER_SHEET.value: (
        "是多分区设定图：按整张评，只看人物的身份特征，忽略分区布局、色板与文字标注。"
    ),
}


@dataclass(slots=True)
class ConsistencyContext:
    """What the write-back knows about the image being scored.

    `variant` is the look / scene variant / prop state the image is filed
    into, and `params` the job's params (`scene_*`, `prop_state`); together
    they decide which differences from the anchor were asked for.
    """

    entry_type: str
    variant: SkillAssetVariant | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    is_video: bool = False
    job_id: str | None = None
    user_id: str | None = None
    max_image_px: int = DEFAULT_MAX_IMAGE_PX


@dataclass(slots=True)
class ConsistencyResult:
    status: str
    rubric_version: int = RUBRIC_VERSION
    score: int | None = None
    dimensions: dict[str, int] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    anchor_entry_id: str | None = None
    anchor_asset_id: str | None = None
    model: str | None = None
    endpoint_id: str | None = None
    skip_reason: str | None = None
    # Why a `failed` result failed (`ERROR_*`); never a provider message.
    error: str | None = None
    # Scored, but at least one requested dimension was missing or not a
    # number and counted as 0.
    degraded: bool = False
    agent_run_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Rubric:
    kind: str
    dimensions: tuple[Dimension, ...]
    ignored: tuple[str, ...]
    notes: tuple[str, ...]


# ---- anchors --------------------------------------------------------------


def resolve_anchor(
    card: CreationSkill, variant: SkillAssetVariant | None = None
) -> SkillAssetEntry | None:
    """The image a new output of `card` (filed into `variant`) is compared to.

    Character: the approved identity portrait (定妆照), else the card anchor.
    Scene / prop: the target variant's approved master, else the card's
    anchor (`master_or_anchor`). A panorama is never one (CL 20). P3-3 reads
    this once when the write-back starts, so outputs of the same job are
    never compared with each other.
    """
    if asset_variants_service.card_kind(card) == "character":
        entry = asset_variants_service.identity_portrait(card) or asset_variants_service.anchor(
            card
        )
    else:
        entry = asset_variants_service.master_or_anchor(card, variant)
    if entry is None or asset_variants_service.is_panorama(entry):
        return None
    return entry


# ---- images ---------------------------------------------------------------


def prepare_image(session: Session, asset_id: str, *, max_px: int = DEFAULT_MAX_IMAGE_PX) -> str:
    """A stored image as a JPEG data URL, long edge at most `max_px`.

    A data URL rather than a presigned one: a local MinIO URL is not
    reachable from the provider, script image extract sends images the same
    way, and downscaling keeps the token bill predictable. Raises when the
    asset is missing, not an image, or undecodable — `score` turns that into
    `failed`.
    """
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise LookupError(f"asset {asset_id} not found")
    if asset.media_type != MediaType.IMAGE:
        raise ValueError(f"asset {asset_id} is not an image")
    payload = s3.get_object(asset.object_key)
    with Image.open(io.BytesIO(payload)) as source:
        image = _flatten_to_rgb(source)
    image.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _flatten_to_rgb(source: Image.Image) -> Image.Image:
    """RGB, with any transparency composited onto white (a plain `convert`
    turns transparent pixels black, which reads as a different background)."""
    if source.mode in {"RGBA", "LA"} or (source.mode == "P" and "transparency" in source.info):
        rgba = source.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return source.convert("RGB")


# ---- rubric ---------------------------------------------------------------


def rubric_for(
    card: CreationSkill, anchor_entry: SkillAssetEntry, context: ConsistencyContext
) -> Rubric:
    """Dimensions, ignore list and notes for one comparison."""
    kind = asset_variants_service.card_kind(card)
    dimensions = RUBRICS[kind]
    ignored = list(_ALWAYS_IGNORED[kind])
    if kind == "character":
        if _is_outfit_change(anchor_entry, context.variant):
            dimensions = tuple(d for d in dimensions if d.key != OUTFIT_DIMENSION)
            ignored.append("服装（本次为换装）")
    elif kind == "scene":
        for axis in _differing_scene_axes(anchor_entry, context):
            ignored.append(f"{_SCENE_AXIS_LABELS[axis]}（本次有意改变）")
    elif _prop_state_differs(anchor_entry, context):
        ignored.append("道具状态（新旧、破损等，本次有意改变）")
    notes = tuple(
        f"{label}{_SHEET_NOTES[entry_type]}"
        for label, entry_type in (
            ("图 1 ", anchor_entry.entry_type),
            ("图 2 ", context.entry_type),
        )
        if entry_type in _SHEET_NOTES
    )
    return Rubric(kind=kind, dimensions=dimensions, ignored=tuple(ignored), notes=notes)


def _is_outfit_change(anchor_entry: SkillAssetEntry, variant: SkillAssetVariant | None) -> bool:
    return variant is not None and anchor_entry.variant_id != variant.id


def _variant_presets(variant: SkillAssetVariant | None) -> dict[str, Any]:
    return dict(variant.presets_json or {}) if variant is not None else {}


def _differing_scene_axes(anchor_entry: SkillAssetEntry, context: ConsistencyContext) -> list[str]:
    """Scene preset axes this image was asked to change: the job's `scene_*`
    params over the target variant's presets, compared with the anchor's
    variant. An axis set on one side only counts as changed."""
    target = {
        **scene_presets_from(_variant_presets(context.variant)),
        **scene_presets_from(dict(context.params)),
    }
    anchor = scene_presets_from(_variant_presets(anchor_entry.variant))
    return [axis for axis in SCENE_PRESET_AXES if target.get(axis) != anchor.get(axis)]


def _prop_state_differs(anchor_entry: SkillAssetEntry, context: ConsistencyContext) -> bool:
    target = context.params.get("prop_state") or _variant_presets(context.variant).get("prop_state")
    return target != _variant_presets(anchor_entry.variant).get("prop_state")


def build_user_prompt(rubric: Rubric) -> str:
    noun = _KIND_NOUNS[rubric.kind]
    keys = [dimension.key for dimension in rubric.dimensions]
    lines = [
        f"卡片类型：{noun}",
        f"图 1 是{noun}卡的锚点，图 2 是待评图。判断图 2 与图 1 是否是同一个{noun}。",
        "评分维度（每项 0–100 的整数）：",
        *(f"- {dimension.key}：{dimension.label}" for dimension in rubric.dimensions),
        f"{DIMENSION_KEYS_PREFIX}{','.join(keys)}",
        f"不比较：{'、'.join(rubric.ignored)}",
        *rubric.notes,
        '只输出 JSON：{"dimensions": {'
        + ", ".join(f'"{key}": 整数' for key in keys)
        + '}, "issues": [字符串], "notes": 字符串}',
    ]
    return "\n".join(lines)


# ---- parsing --------------------------------------------------------------


def _as_score(value: object) -> int | None:
    """0–100 integer, or `None` when `value` is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and math.isfinite(value):
        number = math.floor(value + 0.5)
    else:
        return None
    return max(0, min(100, number))


def _issues(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    cleaned = [str(item).strip() for item in raw if isinstance(item, str | int | float)]
    return [item[:MAX_ISSUE_LEN] for item in cleaned if item][:MAX_ISSUES]


def parse_verdict(
    data: Mapping[str, Any], dimensions: tuple[Dimension, ...]
) -> tuple[dict[str, int], list[str], bool] | None:
    """`(scores, issues, degraded)`, or `None` when there is no
    `dimensions` object at all. A requested key that is missing or not a
    number scores 0 and marks the result degraded; extra keys are dropped."""
    raw = data.get("dimensions")
    if not isinstance(raw, Mapping):
        return None
    scores: dict[str, int] = {}
    degraded = False
    for dimension in dimensions:
        value = _as_score(raw.get(dimension.key))
        if value is None:
            degraded = True
            value = 0
        scores[dimension.key] = value
    return scores, _issues(data.get("issues")), degraded


def weighted_total(scores: Mapping[str, int], dimensions: tuple[Dimension, ...]) -> int:
    """Weighted mean over `dimensions`, rounded half up to an integer."""
    total_weight = sum(dimension.weight for dimension in dimensions)
    numerator = sum(dimension.weight * scores[dimension.key] for dimension in dimensions)
    return (2 * numerator + total_weight) // (2 * total_weight)


# ---- scoring --------------------------------------------------------------


def score(
    session: Session,
    *,
    card: CreationSkill,
    anchor_entry: SkillAssetEntry | None,
    output_asset_id: str,
    context: ConsistencyContext,
) -> ConsistencyResult:
    """Scores one generated image against `anchor_entry`. Never raises."""
    try:
        return _score(
            session,
            card=card,
            anchor_entry=anchor_entry,
            output_asset_id=output_asset_id,
            context=context,
        )
    except Exception:
        logger.exception(
            "consistency_score_failed card=%s output=%s job=%s",
            card.id,
            output_asset_id,
            context.job_id,
        )
        return ConsistencyResult(
            status=STATUS_FAILED,
            error=ERROR_INTERNAL,
            anchor_entry_id=anchor_entry.id if anchor_entry is not None else None,
            anchor_asset_id=anchor_entry.asset_id if anchor_entry is not None else None,
        )


def _skip_reason(
    session: Session,
    anchor_entry: SkillAssetEntry | None,
    output_asset_id: str,
    context: ConsistencyContext,
) -> str | None:
    if context.is_video:
        return SKIP_VIDEO
    output = session.get(Asset, output_asset_id)
    if output is not None and output.media_type == MediaType.VIDEO:
        return SKIP_VIDEO
    if context.entry_type == AssetEntryType.PANORAMA:
        return SKIP_PANORAMA
    if anchor_entry is None or asset_variants_service.is_panorama(anchor_entry):
        return SKIP_NO_ANCHOR
    if anchor_entry.asset_id == output_asset_id:
        return SKIP_OUTPUT_IS_ANCHOR
    return None


def _score(
    session: Session,
    *,
    card: CreationSkill,
    anchor_entry: SkillAssetEntry | None,
    output_asset_id: str,
    context: ConsistencyContext,
) -> ConsistencyResult:
    skip = _skip_reason(session, anchor_entry, output_asset_id, context)
    if skip is not None or anchor_entry is None:
        return ConsistencyResult(
            status=STATUS_SKIPPED,
            skip_reason=skip or SKIP_NO_ANCHOR,
            anchor_entry_id=anchor_entry.id if anchor_entry is not None else None,
            anchor_asset_id=anchor_entry.asset_id if anchor_entry is not None else None,
        )

    def result(status: str, **fields: Any) -> ConsistencyResult:
        return ConsistencyResult(
            status=status,
            anchor_entry_id=anchor_entry.id,
            anchor_asset_id=anchor_entry.asset_id,
            **fields,
        )

    rubric = rubric_for(card, anchor_entry, context)
    try:
        images = [
            prepare_image(session, asset_id, max_px=context.max_image_px)
            for asset_id in (anchor_entry.asset_id, output_asset_id)
        ]
    except Exception:
        logger.warning(
            "consistency_image_unreadable card=%s anchor=%s output=%s",
            card.id,
            anchor_entry.asset_id,
            output_asset_id,
            exc_info=True,
        )
        return result(STATUS_FAILED, error=ERROR_IMAGE_UNREADABLE)

    try:
        # A savepoint, so a failure after `run_agent` touched the session
        # cannot leave the caller's write-back transaction unusable.
        with session.begin_nested():
            outcome = run_agent(
                session,
                agent_name=AgentName.QUALITY.value,
                system_prompt=quality_agent.CONSISTENCY_SYSTEM_PROMPT,
                user_prompt=build_user_prompt(rubric),
                user_content=[{"type": "image_url", "image_url": {"url": url}} for url in images],
                fallback={},
                job_id=context.job_id,
                user_id=context.user_id,
                agent_id=agent_skills_service.resolve_consistency_agent_id(session),
                slot=CONSISTENCY_SLOT,
                max_tokens=JUDGE_MAX_TOKENS,
                temperature=JUDGE_TEMPERATURE,
            )
    except NoCapableEndpoint:
        return result(STATUS_SKIPPED, skip_reason=SKIP_NO_VISION_ENDPOINT)
    except Exception:
        logger.warning(
            "consistency_judge_call_failed card=%s output=%s job=%s",
            card.id,
            output_asset_id,
            context.job_id,
            exc_info=True,
        )
        return result(STATUS_FAILED, error=ERROR_LLM)

    call: dict[str, Any] = {
        "model": outcome.model or None,
        "endpoint_id": outcome.endpoint_id or None,
        "agent_run_id": outcome.agent_run_id,
    }
    parsed = None if outcome.degraded else parse_verdict(outcome.data, rubric.dimensions)
    if parsed is None:
        return result(STATUS_FAILED, error=ERROR_PARSE, **call)
    scores, issues, degraded = parsed
    return result(
        STATUS_SCORED,
        score=weighted_total(scores, rubric.dimensions),
        dimensions=scores,
        issues=issues,
        degraded=degraded,
        **call,
    )
