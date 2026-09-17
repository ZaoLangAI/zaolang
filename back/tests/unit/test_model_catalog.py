"""Curated per-vendor model catalogue: structural integrity only — this data
feeds an admin form-filling convenience (`GET /admin/llm-providers/catalog`),
not a validated config, so these tests guard against a typo breaking the
picker rather than re-testing each provider's own request-building logic
(see `test_dmxapi_media.py`/`test_aihubmix_media.py` for that).
"""

from __future__ import annotations

from app.platform_config.schemas import IMPLEMENTED_MEDIA_PROTOCOLS, LLM_ENDPOINT_TIMEOUT_MS_MAX
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
        "gpt-4o-mini-tts",
        "tts-1",
        "tts-1-hd",
        "tts-pro",
        "music-3.0",
    }


def test_aihubmix_catalog_includes_the_new_seedance_model() -> None:
    models = {entry.model for entry in model_catalog.VENDOR_MODEL_CATALOG["aihubmix"]}
    assert "doubao-seedance-2-5-260628" in models


def test_aihubmix_catalog_includes_gpt_image_2() -> None:
    entry = model_catalog.catalog_entry("aihubmix", "gpt-image-2")
    assert entry is not None
    assert entry.display_name == "GPT Image 2"
    assert entry.kind == "media"
    assert entry.protocol == "openai"
    assert entry.input_modalities == ("text", "image")
    assert entry.output_modalities == ("image",)
    assert entry.billing_profile == "gpt_image_2_tokens"
    assert entry.suggested_timeout_ms == 600_000
    assert entry.pricing_doc_url == "https://aihubmix.com/model/gpt-image-2"
    keys = {(item.key, item.dimension) for item in entry.price_items}
    assert ("image_generation", "") in keys
    assert ("image_generation", "1K") in keys
    assert ("image_generation", "2K") in keys


def test_every_suggested_timeout_fits_the_endpoint_ceiling() -> None:
    for entries in model_catalog.VENDOR_MODEL_CATALOG.values():
        for entry in entries:
            assert 0 <= entry.suggested_timeout_ms <= LLM_ENDPOINT_TIMEOUT_MS_MAX, entry.model


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
    assert entry.generation_kind == "edit"


def test_known_video_edit_models_are_catalogued_as_edit() -> None:
    wan = model_catalog.catalog_entry("aihubmix", "wan2.7-videoedit")
    assert wan is not None
    assert wan.generation_kind == "edit"
    h3 = model_catalog.catalog_entry("aihubmix", "minimax-h3")
    assert h3 is not None
    assert h3.generation_kind == "create"


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
    pricing shape instead of the token formula. Not every catalogue vendor
    carries Seedance (Metaso is H3-only today)."""
    from app.domain.costs.service import SEEDANCE_TOKENS_BILLING_PROFILE

    found = False
    for vendor in model_catalog.VENDOR_IDS:
        entry = model_catalog.catalog_entry(vendor, "doubao-seedance-2-5-260628")
        if entry is None:
            continue
        found = True
        assert entry.billing_profile == SEEDANCE_TOKENS_BILLING_PROFILE
    assert found


def test_fal_catalog_covers_minimax_h3_max() -> None:
    entry = model_catalog.catalog_entry("fal", "minimax/h3-max")
    assert entry is not None
    assert entry.protocol == "fal"
    assert entry.display_name == "MiniMax H3 Max"
    assert entry.billing_profile == "fal_h3_max"
    assert entry.generation_kind == "create"
    assert model_catalog.vendor_base_url("fal") == "https://queue.fal.run"
    assert model_catalog.VENDOR_LABELS["fal"] == "fal.ai"
    assert model_catalog.display_name_for_model("minimax/h3-max") == "MiniMax H3 Max"
    dimensions = {item.dimension for item in entry.price_items if item.key == "video_generation"}
    assert dimensions == {"480P", "768P"}
    extra = next(item for item in entry.price_items if item.key == "video_extra_reference_image")
    assert extra.free_count == 4
    assert extra.default_micro_usd == 20_000


def test_fal_catalog_covers_minimax_voice_clone() -> None:
    entry = model_catalog.catalog_entry("fal", "minimax/voice-clone")
    assert entry is not None
    assert entry.protocol == "fal"
    assert entry.display_name == "MiniMax Voice Clone"
    assert entry.input_modalities == ("text", "audio")
    assert entry.output_modalities == ("audio",)
    assert entry.billing_profile == "fal_voice_clone"
    per_request = next(
        item
        for item in entry.price_items
        if item.key == "audio_generation" and item.unit == "per_request"
    )
    assert per_request.default_micro_usd == 1_500_000
    preview = next(
        item
        for item in entry.price_items
        if item.key == "audio_generation" and item.unit == "per_10k_characters"
    )
    assert preview.default_micro_usd == 3_000_000


def test_metaso_catalog_covers_minimax_h3_on_minimax_v2() -> None:
    entry = model_catalog.catalog_entry("metaso", "MiniMax-H3")
    assert entry is not None
    assert entry.protocol == "minimax_v2"
    assert entry.billing_profile == "minimax_h3_payg"
    assert entry.pricing_doc_url == "https://metaso.cn/minimax-h3"
    assert model_catalog.vendor_base_url("metaso") == "https://metaso.cn/api/minimax"


def test_minimax_h3_price_items_differ_across_all_three_vendors() -> None:
    """AiHubMix / DMXAPI / Metaso each have their own H3 resale rate —
    collapsing any pair back into one shared default would misprice the
    cheaper Metaso channel."""
    aihubmix_entry = model_catalog.catalog_entry("aihubmix", "minimax-h3")
    dmxapi_entry = model_catalog.catalog_entry("dmxapi", "MiniMax-H3")
    metaso_entry = model_catalog.catalog_entry("metaso", "MiniMax-H3")
    assert aihubmix_entry is not None and dmxapi_entry is not None and metaso_entry is not None

    def two_k(entry: model_catalog.ModelCatalogEntry) -> int:
        return next(
            item.default_micro_usd
            for item in entry.price_items
            if item.key == "video_generation" and item.dimension == "2K"
        )

    rates = {two_k(aihubmix_entry), two_k(dmxapi_entry), two_k(metaso_entry)}
    assert len(rates) == 3


def test_metaso_price_items_are_the_vendor_own_list_without_a_reseller_markup_note() -> None:
    """Metaso quotes its own H3 list — it is not a reseller markup on
    MiniMax's domestic page, so a leftover `markup_note` would misread as
    DMXAPI-style "厂商原价 / 含税价"."""
    for entry in model_catalog.VENDOR_MODEL_CATALOG["metaso"]:
        for item in entry.price_items:
            assert not item.markup_note, (entry.model, item.key, item.dimension)


def test_dmxapi_catalog_covers_music_3_0() -> None:
    entry = model_catalog.catalog_entry("dmxapi", "music-3.0")
    assert entry is not None
    assert entry.protocol == "dmxapi"
    assert entry.input_modalities == ("text",)
    assert entry.output_modalities == ("audio",)
    # Pricing page has no published rate for this model — same "no
    # price_items" shape as `gpt-4o-mini-tts`'s own token-billed entry.
    assert entry.price_items == ()


def test_fal_catalog_covers_minimax_music() -> None:
    entry = model_catalog.catalog_entry("fal", "minimax-music/v2.6")
    assert entry is not None
    assert entry.protocol == "fal"
    assert entry.display_name == "MiniMax Music 2.6"
    assert entry.input_modalities == ("text",)
    assert entry.output_modalities == ("audio",)
    per_request = next(item for item in entry.price_items if item.key == "music_generation")
    assert per_request.unit == "per_request"
    assert per_request.default_micro_usd == 150_000


def test_fal_catalog_covers_elevenlabs_sound_effects() -> None:
    entry = model_catalog.catalog_entry("fal", "elevenlabs/sound-effects/v2")
    assert entry is not None
    assert entry.protocol == "fal"
    assert entry.display_name == "ElevenLabs Sound Effects V2"
    assert entry.input_modalities == ("text",)
    assert entry.output_modalities == ("audio",)
    per_request = next(item for item in entry.price_items if item.key == "music_generation")
    assert per_request.unit == "per_request"
    # Vendor bills per second; the catalog note explains the per-request
    # conversion, so a `markup_note` must be present, not left implicit.
    assert per_request.markup_note


def test_voices_for_model_finds_the_dmxapi_openai_compatible_roster() -> None:
    voices = model_catalog.voices_for_model("tts-1")
    assert voices is not None
    assert "alloy" in voices
    assert len(voices) == 11


def test_voices_for_model_is_case_insensitive_like_display_name_for_model() -> None:
    assert model_catalog.voices_for_model("TTS-1") == model_catalog.voices_for_model("tts-1")


def test_voices_for_model_finds_the_tts_pro_curated_roster() -> None:
    voices = model_catalog.voices_for_model("tts-pro")
    assert voices is not None
    assert len(voices) > 0
    # Never the OpenAI roster leaking across models on the same vendor.
    assert "alloy" not in voices


def test_voices_for_model_returns_none_for_a_clone_only_model() -> None:
    """`minimax/voice-clone` takes a reference sample, not a preset voice
    id — its catalogue entry must declare no `voices` roster, or the studio
    would wrongly show a `Select` instead of the clone-upload tab."""
    entry = model_catalog.catalog_entry("fal", "minimax/voice-clone")
    assert entry is not None
    assert entry.voices is None
    assert model_catalog.voices_for_model("minimax/voice-clone") is None


def test_voices_for_model_returns_none_for_an_unknown_model() -> None:
    assert model_catalog.voices_for_model("some-model-nobody-registered") is None


def test_fal_music_and_sfx_prices_differ() -> None:
    """Both are `per_request` under the same `music_generation` key on the
    same vendor — a copy-paste that reused one figure for both would be
    caught here."""
    music = model_catalog.catalog_entry("fal", "minimax-music/v2.6")
    sfx = model_catalog.catalog_entry("fal", "elevenlabs/sound-effects/v2")
    assert music is not None and sfx is not None
    music_price = next(item.default_micro_usd for item in music.price_items)
    sfx_price = next(item.default_micro_usd for item in sfx.price_items)
    assert music_price != sfx_price
