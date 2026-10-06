"""The "参考图说明" legend only ever names images the provider receives."""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.image_assets import prompt_builder as pb
from app.models.enums import Operation
from app.providers.base import ProviderReference
from app.workflows import nodes


def _image(asset_id: str, frame_type: str | None = None) -> ProviderReference:
    return ProviderReference(
        object_key=f"k/{asset_id}", media_type="image", frame_type=frame_type, asset_id=asset_id
    )


LABELS = {"a": "角色「林夏」设定图", "b": "场景「客厅」主图", "c": "角色「周野」设定图"}


def test_legend_numbers_images_in_provider_order() -> None:
    legend = pb.reference_legend([_image("a"), _image("b")], LABELS, cap=9)
    assert legend.startswith(pb.REFERENCE_LEGEND_PREFIX)
    assert "图1 是角色「林夏」设定图；图2 是场景「客厅」主图" in legend
    assert legend.endswith("\n")


def test_legend_truncates_to_what_the_model_receives() -> None:
    legend = pb.reference_legend([_image("a"), _image("b"), _image("c")], LABELS, cap=2)
    assert "图2" in legend and "图3" not in legend


def test_legend_is_silent_when_it_cannot_be_trusted() -> None:
    refs = [_image("a"), _image("b")]
    assert pb.reference_legend(refs, LABELS, cap=None) == ""
    assert pb.reference_legend(refs, LABELS, cap=1) == ""
    assert pb.reference_legend([_image("a")], LABELS, cap=9) == ""
    assert pb.reference_legend([_image("x"), _image("y")], LABELS, cap=9) == ""
    assert pb.reference_legend([*refs, _image("f", "first_frame")], LABELS, cap=9) == ""


def test_unlabelled_images_still_count_toward_numbering() -> None:
    legend = pb.reference_legend([_image("upload"), _image("a")], LABELS, cap=9)
    assert "图1 是参考图；图2 是角色「林夏」设定图" in legend


def test_strip_reference_legend_round_trips() -> None:
    legend = pb.reference_legend([_image("a"), _image("b")], LABELS, cap=9)
    assert pb.strip_reference_legend(f"{legend}老式客厅") == "老式客厅"
    assert pb.strip_reference_legend("老式客厅") == "老式客厅"


SCOPED = {
    "a": "角色「林夏」·设定图",
    "b": "场景「客厅」·主图",
    "p": "道具「旧怀表」·主图",
    "face": "角色「林夏」·定妆照（只取面部与体型，忽略服装）",
}


def test_scope_names_only_the_kinds_present_and_stays_one_line() -> None:
    legend = pb.reference_legend([_image("a"), _image("b")], SCOPED, cap=9, scope=True)
    assert legend.startswith(f"{pb.REFERENCE_LEGEND_PREFIX}图1 是角色「林夏」·设定图；图2 是场景")
    assert "角色参考图沿用其相貌、发型、体型与服装" in legend
    assert "场景参考图沿用空间结构、陈设与材质" in legend
    assert "道具参考图" not in legend
    assert legend.endswith("以下文描述为准。请按以上对应关系使用各参考图。\n")
    assert legend.count("\n") == 1
    assert pb.strip_reference_legend(f"{legend}雨夜") == "雨夜"


def test_scope_leaves_role_suffixed_and_unlabelled_images_alone() -> None:
    assert pb.reference_scope_sentence(["角色「林夏」·定妆照（只取面部与体型，忽略服装）"]) == ""
    assert pb.reference_scope_sentence([pb.GENERIC_REFERENCE_LABEL]) == ""
    legend = pb.reference_legend([_image("face"), _image("upload")], SCOPED, cap=9, scope=True)
    assert "沿用" not in legend


def test_scope_treats_a_character_cards_prop_entry_as_a_prop() -> None:
    sentence = pb.reference_scope_sentence(["角色「林夏」·道具", "道具「旧怀表」·主图"])
    assert sentence.startswith("道具参考图沿用其外形、材质与颜色")
    assert "角色参考图" not in sentence


def test_scope_off_is_byte_identical_to_the_plain_legend() -> None:
    refs = [_image("a"), _image("b")]
    plain = pb.reference_legend(refs, SCOPED, cap=9)
    assert plain == pb.reference_legend(refs, SCOPED, cap=9, scope=False)
    assert plain == (
        f"{pb.REFERENCE_LEGEND_PREFIX}图1 是角色「林夏」·设定图；图2 是场景「客厅」·主图。"
        "请按以上对应关系使用各参考图。\n"
    )


def _legend_ctx(operation: str, **params: object) -> SimpleNamespace:
    labels = [{"asset_id": key, "label": SCOPED[key]} for key in ("a", "b")]
    return SimpleNamespace(
        job=SimpleNamespace(operation=operation),
        params={"reference_labels": labels, **params},
    )


def test_only_video_jobs_get_the_scope_sentence() -> None:
    refs = [_image("a"), _image("b")]
    cap = SimpleNamespace(max_image_references=9)

    def prompt_for(ctx: SimpleNamespace) -> str:
        return nodes._with_reference_legend("雨夜", refs, cap, ctx)  # type: ignore[arg-type]

    assert "沿用" in prompt_for(_legend_ctx(Operation.TEXT_TO_VIDEO.value))
    assert "沿用" in prompt_for(
        _legend_ctx(Operation.IMAGE_TO_VIDEO.value, video_asset_kind="character_action")
    )
    still = prompt_for(_legend_ctx(Operation.IMAGE_TO_IMAGE.value))
    assert still.startswith(pb.REFERENCE_LEGEND_PREFIX) and "沿用" not in still
    sheet = prompt_for(_legend_ctx(Operation.IMAGE_TO_IMAGE.value, asset_kind="character"))
    assert "沿用" not in sheet
