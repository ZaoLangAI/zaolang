"""Curated per-vendor model catalogue: structural integrity only — this data
feeds an admin form-filling convenience (`GET /admin/llm-providers/catalog`),
not a validated config, so these tests guard against a typo breaking the
picker rather than re-testing each provider's own request-building logic
(see `test_dmxapi_media.py`/`test_aihubmix_media.py` for that).
"""

from __future__ import annotations

from app.platform_config.schemas import IMPLEMENTED_MEDIA_PROTOCOLS
from app.providers import model_catalog


def test_every_vendor_id_has_a_base_url_and_label() -> None:
    for vendor in model_catalog.VENDOR_IDS:
        assert model_catalog.vendor_base_url(vendor).startswith("https://")
        assert model_catalog.VENDOR_LABELS[vendor]


def test_every_catalog_entry_declares_a_known_kind() -> None:
    for entries in model_catalog.VENDOR_MODEL_CATALOG.values():
        for entry in entries:
            assert entry.kind in ("general", "media")
            assert entry.model


def test_every_media_entry_declares_an_implemented_protocol() -> None:
    """A catalogue entry that points at an unimplemented protocol would let
    the admin picker pre-fill a combination the backend then rejects."""
    for entries in model_catalog.VENDOR_MODEL_CATALOG.values():
        for entry in entries:
            if entry.kind != "media":
                continue
            assert entry.protocol in IMPLEMENTED_MEDIA_PROTOCOLS


def test_every_general_entry_declares_no_protocol() -> None:
    for entries in model_catalog.VENDOR_MODEL_CATALOG.values():
        for entry in entries:
            if entry.kind == "general":
                assert entry.protocol is None


def test_catalog_entry_lookup_finds_a_known_model() -> None:
    entry = model_catalog.catalog_entry("dmxapi", "MiniMax-H3")
    assert entry is not None
    assert entry.display_name


def test_catalog_entry_lookup_returns_none_for_an_unknown_model() -> None:
    assert model_catalog.catalog_entry("dmxapi", "some-model-nobody-registered") is None


def test_dmxapi_catalog_covers_every_model_the_plan_named() -> None:
    models = {entry.model for entry in model_catalog.VENDOR_MODEL_CATALOG["dmxapi"]}
    assert models == {
        "MiniMax-H3",
        "MiniMax-H3-video_regeneration",
        "doubao-seedance-2-5-260628",
        "wan3.0-video",
        "doubao-seedream-5-0-pro-260628",
        "glm-5.3-flash",
        "qwen3.8-flash",
    }


def test_aihubmix_catalog_includes_the_new_seedance_model() -> None:
    models = {entry.model for entry in model_catalog.VENDOR_MODEL_CATALOG["aihubmix"]}
    assert "doubao-seedance-2-5-260628" in models


def test_the_video_regeneration_entry_only_declares_video_to_video_shaped_modalities() -> None:
    """It always requires a source clip — never a plain text-to-video
    candidate — so its modalities must not read as a general video model.
    No "text" on the input side: declaring it would derive a spurious
    `text_to_video` capability regeneration can never actually serve (see
    `_CAPABILITY_MODALITY_MAP`)."""
    entry = model_catalog.catalog_entry("dmxapi", "MiniMax-H3-video_regeneration")
    assert entry is not None
    assert entry.input_modalities == ("video",)
    assert "video" in entry.output_modalities
