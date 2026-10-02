"""The "参考图说明" legend only ever names images the provider receives."""

from __future__ import annotations

from app.domain.image_assets import prompt_builder as pb
from app.providers.base import ProviderReference


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
