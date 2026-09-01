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


def test_every_media_entry_with_price_items_declares_a_pricing_doc_url() -> None:
    """A price with no source page is unverifiable by an operator — every
    `price_items` entry must trace back to somewhere."""
    for entries in model_catalog.VENDOR_MODEL_CATALOG.values():
        for entry in entries:
            if entry.price_items:
                assert entry.pricing_doc_url, entry.model


def test_every_price_item_is_a_non_negative_integer_micro_usd() -> None:
    for entries in model_catalog.VENDOR_MODEL_CATALOG.values():
        for entry in entries:
            for item in entry.price_items:
                assert item.default_micro_usd >= 0, (entry.model, item.key, item.dimension)
                assert item.source_currency in ("USD", "CNY")
                assert item.source_amount


def test_a_dmxapi_price_item_with_an_upstream_vendor_page_carries_a_markup_note() -> None:
    """DMXAPI resells at the upstream vendor's price plus its own markup and
    6% tax (`rmb.dmxapi.cn`'s own "厂商原价 / DMXAPI价格（含税6%）" columns) —
    a `default_micro_usd` with no `markup_note` would read as DMXAPI's real
    invoiced rate instead of the lower-bound reference it actually is."""
    for entry in model_catalog.VENDOR_MODEL_CATALOG["dmxapi"]:
        for item in entry.price_items:
            assert item.markup_note, (entry.model, item.key, item.dimension)


def test_aihubmix_and_dmxapi_never_share_one_price_for_the_same_upstream_model() -> None:
    """AiHubMix (USD, international channel) and DMXAPI (CNY, domestic
    channel) are two different resale channels for MiniMax H3 and Doubao
    Seedance 2.5 — collapsing them back into one shared default would
    silently misprice whichever vendor's real channel does not match. This
    is a regression test for exactly that mistake."""
    aihubmix_media_models = {
        entry.model
        for entry in model_catalog.VENDOR_MODEL_CATALOG["aihubmix"]
        if entry.kind == "media"
    }
    dmxapi_media_models = {
        entry.model
        for entry in model_catalog.VENDOR_MODEL_CATALOG["dmxapi"]
        if entry.kind == "media"
    }
    shared_models = aihubmix_media_models & dmxapi_media_models
    # Casing differs between the two vendors' own model ids for MiniMax H3
    # (`minimax-h3` vs `MiniMax-H3`) but not for Seedance — at least one
    # overlap is expected today; if this list ever goes empty the assertions
    # below simply do not run, which would silently stop testing anything.
    assert "doubao-seedance-2-5-260628" in shared_models

    for model in shared_models:
        aihubmix_entry = model_catalog.catalog_entry("aihubmix", model)
        dmxapi_entry = model_catalog.catalog_entry("dmxapi", model)
        assert aihubmix_entry is not None and dmxapi_entry is not None
        aihubmix_rates = {
            (item.key, item.dimension): item.default_micro_usd
            for item in aihubmix_entry.price_items
        }
        dmxapi_rates = {
            (item.key, item.dimension): item.default_micro_usd for item in dmxapi_entry.price_items
        }
        shared_keys = set(aihubmix_rates) & set(dmxapi_rates)
        assert shared_keys, model
        assert any(aihubmix_rates[key] != dmxapi_rates[key] for key in shared_keys), model


def test_minimax_h3_price_items_differ_between_aihubmix_and_dmxapi_by_casing() -> None:
    """Same assertion as above, spelled out for MiniMax H3 specifically since
    its model id casing differs between the two vendors and would not be
    caught by the generic shared-model-id check."""
    aihubmix_entry = model_catalog.catalog_entry("aihubmix", "minimax-h3")
    dmxapi_entry = model_catalog.catalog_entry("dmxapi", "MiniMax-H3")
    assert aihubmix_entry is not None and dmxapi_entry is not None
    aihubmix_2k = next(
        item.default_micro_usd
        for item in aihubmix_entry.price_items
        if item.key == "video_generation" and item.dimension == "2K"
    )
    dmxapi_2k = next(
        item.default_micro_usd
        for item in dmxapi_entry.price_items
        if item.key == "video_generation" and item.dimension == "2K"
    )
    assert aihubmix_2k != dmxapi_2k


def test_seedance_billing_profile_matches_the_costs_service_dispatch_constant() -> None:
    """`app.domain.costs.service` only special-cases one literal string —
    a typo here would silently fall back to the default per-second video
    pricing shape instead of the token formula."""
    from app.domain.costs.service import SEEDANCE_TOKENS_BILLING_PROFILE

    for vendor in model_catalog.VENDOR_IDS:
        entry = model_catalog.catalog_entry(vendor, "doubao-seedance-2-5-260628")
        assert entry is not None
        assert entry.billing_profile == SEEDANCE_TOKENS_BILLING_PROFILE
