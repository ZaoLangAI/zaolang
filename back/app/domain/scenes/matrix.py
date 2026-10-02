"""Scene variant matrix (P2-5): lighting × weather × state × period for one
scene card, planned as one image job per cell.

`plan` turns the picked axis values into cells and says which already have
an approved master plate on the card (skipped), which only have candidates
(skipped — approve or delete them first), and which are new. `cell_params`
is the `GenerationParams` dict one cell's job is submitted with: a single
image with that cell's presets, targeting the card, so write-back files it
under the variant whose `presets_json` matches (created on first use —
`scenes.service.append_reference_asset`). Each new variant starts from the
card's anchor (`asset_variants.service.default_subset`), and
`prompt_builder.SCENE_VARIANT_PREFIX` keeps its geometry.

One job per cell rather than a variant set: a failed cell does not touch
the others and can be resubmitted alone, and nothing depends on provider
group output.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Literal

from app.domain.asset_variants import service as asset_variants_service
from app.domain.errors import ValidationFailed
from app.domain.image_assets.vocabulary import scene_preset_label
from app.domain.scenes.service import SceneView
from app.models import CreationSkill
from app.models.enums import AssetEntryType, ImageAssetKind

MAX_MATRIX_CELLS = 12
MAX_AXIS_VALUES = 4
# Cell order: the axes in the order a user reads a variant name.
MATRIX_AXES = ("lighting", "weather", "state", "period")

CellStatus = Literal["new", "exists", "candidate"]


@dataclass(frozen=True, slots=True)
class MatrixCell:
    presets: dict[str, str]
    label: str
    status: CellStatus
    variant_id: str | None

    @property
    def key(self) -> str:
        """Stable per-cell token (idempotency, de-duplication)."""
        return "|".join(
            f"{axis}={self.presets[axis]}" for axis in MATRIX_AXES if axis in self.presets
        )


def _combos(axes: dict[str, list[str]]) -> list[dict[str, str]]:
    picked: list[tuple[str, list[str]]] = []
    for axis in MATRIX_AXES:
        values = list(dict.fromkeys(axes.get(axis) or []))
        if len(values) > MAX_AXIS_VALUES:
            raise ValidationFailed(
                f"每个维度最多选 {MAX_AXIS_VALUES} 个值。", fields={f"axes.{axis}": "数量超限"}
            )
        if values:
            picked.append((axis, values))
    if not picked:
        raise ValidationFailed("至少选择一个维度。", fields={"axes": "不能为空"})
    count = 1
    for _, values in picked:
        count *= len(values)
    if count > MAX_MATRIX_CELLS:
        raise ValidationFailed(
            f"一次最多生成 {MAX_MATRIX_CELLS} 个组合（当前 {count} 个），请分批提交。",
            fields={"axes": "组合数超限"},
        )
    names = [axis for axis, _ in picked]
    return [dict(zip(names, values, strict=True)) for values in product(*(v for _, v in picked))]


def plan(skill: CreationSkill, axes: dict[str, list[str]]) -> list[MatrixCell]:
    """Every cell of the matrix with what the card already holds for it."""
    cells: list[MatrixCell] = []
    for presets in _combos(axes):
        variant = next(
            (v for v in asset_variants_service.variants(skill) if v.presets_json == presets),
            None,
        )
        masters = (
            [e for e in variant.entries if e.entry_type == AssetEntryType.MASTER] if variant else []
        )
        status: CellStatus = "new"
        if any(asset_variants_service.is_approved(e) for e in masters):
            status = "exists"
        elif masters:
            status = "candidate"
        cells.append(
            MatrixCell(
                presets=presets,
                label=scene_preset_label(presets),
                status=status,
                variant_id=variant.id if variant else None,
            )
        )
    return cells


def default_prompt(skill: CreationSkill) -> str:
    """The card's own name + description — what the scene library's
    "生成到此处" jump-out seeds (`front/src/lib/scenes.ts:sceneImagePrompt`)."""
    scene = SceneView(skill)
    name = scene.name.strip()
    description = (scene.description or "").strip().rstrip("。．.")
    return f"{name}。{description}" if description else name


def cell_params(
    skill: CreationSkill, cell: MatrixCell, *, prompt: str, aspect_ratio: str
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "asset_kind": ImageAssetKind.SCENE.value,
        "target_scene_id": skill.id,
        "subject_name_hint": (skill.title or "")[:60] or None,
    }
    for axis, value in cell.presets.items():
        params[f"scene_{axis}"] = value
    return params
