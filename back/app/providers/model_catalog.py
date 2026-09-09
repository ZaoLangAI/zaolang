"""Curated per-service-provider model catalogue.

Purely additive sugar on top of the fully flexible `LlmProviderEndpoint`
config (`app/platform_config/schemas.py`): an operator can still type any
model name / `base_url` / protocol by hand — nothing here gates what can be
saved. This module is consulted only by `GET /admin/llm-providers/catalog`,
to drive a cascading "service provider -> known model" picker in
`/admin/models` that pre-fills the form with a model's real supported
protocol/modalities and shows its physical limits as a hint. The actual
enforcement of those limits lives on each provider module's own profile
table (`aihubmix_media.NativeVideoModelProfile`, `dmxapi_media
.VideoModelProfile`/`ImageModelProfile`) and on `LlmProviderEndpoint`'s own
validators — this catalogue is not itself validated against at save time.

`price_items` is the same kind of suggestion, one level deeper: each entry
names one billable line item this specific vendor record's own pricing page
quotes, and `default_micro_usd` is that quote converted to micro-USD — what
the admin form pre-fills the *first* time an operator picks this model, not
a value re-applied over a price the operator has since edited and saved.

The one rule this file exists to enforce: **two catalogue vendors are never
assumed to charge the same amount for what is nominally the same upstream
model.** AiHubMix (USD, international), DMXAPI (CNY, domestic resale), and
Metaso (CNY, its own MiniMax H3 channel) each carry their own `price_items`
sourced from that vendor's actual page — never copied from another's — and
`test_model_catalog.py` asserts the numbers differ so a future edit cannot
quietly collapse them back into one shared price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.models.enums import MediaGenerationKind

VendorId = Literal["aihubmix", "dmxapi", "metaso", "fal"]
VENDOR_IDS: tuple[VendorId, ...] = ("aihubmix", "dmxapi", "metaso", "fal")

# Presets for the admin picker's "base URL" field — still a plain text input
# an operator can override, same as every other pre-filled value here.
VENDOR_BASE_URLS: dict[VendorId, str] = {
    "aihubmix": "https://aihubmix.com",
    "dmxapi": "https://www.dmxapi.cn",
    "metaso": "https://metaso.cn/api/minimax",
    "fal": "https://queue.fal.run",
}

VENDOR_LABELS: dict[VendorId, str] = {
    "aihubmix": "AiHubMix",
    "dmxapi": "DMXAPI",
    "metaso": "秘塔",
    "fal": "fal.ai",
}

# CNY -> micro-USD, matching the admin form's own default display rate
# (`front/.../micro-usd.ts` `DEFAULT_CNY_PER_USD`). Only used to pre-compute
# `PriceItem.default_micro_usd` for a CNY-quoted vendor page at catalogue-
# authoring time — never applied again at request time, and never the rate
# an operator's own CNY input uses (that one is typed fresh on the form).
_CNY_PER_USD = 7.2


def _cny_micro_usd(yuan: float) -> int:
    """Rounds a CNY quote up to the nearest micro-USD, mirroring
    `app.domain.costs.service._ceil_div`'s "round up, never down" rule."""
    micro = yuan / _CNY_PER_USD * 1_000_000
    return -int(-micro // 1)


def _usd_micro_usd(dollars: float) -> int:
    return round(dollars * 1_000_000)


# OpenAI's own documented preset-voice roster — shared verbatim by every
# `/v1/audio/speech`-shaped model (`gpt-4o-mini-tts`/`tts-1`/`tts-1-hd`),
# whether served by OpenAI itself or resold through an OpenAI-compatible
# proxy (DMXAPI). https://platform.openai.com/docs/guides/text-to-speech
_OPENAI_TTS_VOICES: tuple[str, ...] = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "verse",
)


@dataclass(frozen=True, slots=True)
class PriceItem:
    """One billable line item exactly as this vendor's own pricing page
    quotes it, pre-computed into the same integer micro-USD unit
    `LlmProviderEndpoint`'s pricing fields store.

    `key` names which structured pricing field the admin form pre-fills —
    see `PriceItemKey` below — `dimension` scopes it further for a field
    keyed by resolution/tier (e.g. `key="video_generation"`,
    `dimension="2K"`). Every field here is a *suggestion*: saving an
    endpoint always persists whatever the operator's form actually shows,
    never this dataclass directly.
    """

    key: str
    unit: Literal[
        "per_second", "per_million_tokens", "per_image", "per_request", "per_10k_characters"
    ]
    label: str
    default_micro_usd: int
    source_currency: Literal["USD", "CNY"]
    # The vendor page's own figure, verbatim, for the admin hint text — e.g.
    # "$0.13/秒" or "0.30 元/张". Never parsed, only displayed.
    source_amount: str
    # Month the figure was checked against the vendor's page, e.g. "2026-08".
    quoted_on: str
    dimension: str = ""
    free_count: int | None = None
    # A price confirmed to have already changed once shortly after launch,
    # or one that carries a temporary promotional discount on top of it —
    # the admin form surfaces this so "apply preset" is not mistaken for
    # "verified today".
    volatile: bool = False
    # Set only on a DMXAPI entry: DMXAPI resells at the upstream vendor's
    # price plus its own markup and 6% tax (see `rmb.dmxapi.cn`'s own
    # "厂商原价 / DMXAPI价格（含税6%）" columns) — `default_micro_usd` here is
    # the upstream vendor's own domestic price, a lower-bound reference, not
    # DMXAPI's real invoiced rate.
    markup_note: str = ""


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    """One vendor's known model, for the admin picker only.

    Every field here is a *suggestion* the form pre-fills when an operator
    picks this entry — not a constraint enforced at save time.
    """

    model: str
    display_name: str
    kind: Literal["general", "media"]
    # `kind="media"` only — the HTTP contract name from `MediaProtocol`.
    protocol: str | None = None
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    # `kind="general"` only, informational (not written to the endpoint
    # unless the operator also fills in `context_length` themselves).
    context_length: int = 0
    # Human-readable limits/caveats (duration, resolution, aspect ratio,
    # known gaps) — shown as a read-only hint, never parsed.
    notes: str = ""
    doc_url: str = ""
    # The pricing page this entry's `price_items` were read from — usually
    # the *upstream* vendor's own page (MiniMax/Volcano Ark/Alibaba Cloud/
    # Zhipu/...), not this catalogue vendor's resale page, since AiHubMix and
    # DMXAPI rarely publish their own itemised rate cards; DMXAPI's markup
    # over that page is called out per-item in `PriceItem.markup_note`
    # instead of pretended away.
    pricing_doc_url: str = ""
    # Which `app.domain.costs.service` billing shape this model's prices
    # follow — `None` when the default per-second/per-image/per-token
    # dispatch already applies. `"seedance_tokens"` is the one value the
    # cost-calculation code actually branches on today (see
    # `app.domain.costs.service.SEEDANCE_TOKENS_BILLING_PROFILE`); the rest
    # are descriptive only, for the admin UI and for a future profile to
    # hook into without renaming an already-saved endpoint's metadata.
    billing_profile: str | None = None
    price_items: tuple[PriceItem, ...] = field(default_factory=tuple)
    # `output_modalities` includes `"audio"` and this model takes a
    # discrete preset-voice id (not a clone reference) only — the C-end
    # studio's per-model voice picker (`GET /v1/generation-jobs/models`,
    # `GenerationModelOption.voices`) reads this instead of a hardcoded
    # roster. `None` means either "not a voice model" or "clone-only, no
    # fixed roster" (e.g. fal's single-call voice-clone models) — the
    # studio falls back to its clone-upload tab in either case. Not
    # necessarily exhaustive for providers with dozens of voices (see
    # `tts-pro` below) — a curated, representative subset is still more
    # useful to a caller than none at all.
    voices: tuple[str, ...] | None = None
    # Pre-fills the admin timeout field when an operator picks this model.
    # Zero means "leave the form's existing / kind-default timeout alone".
    suggested_timeout_ms: int = 0
    # `kind="media"` only. Pre-fills `LlmProviderEndpoint.generation_kind`.
    # Edit-class video models are hard-filtered out of text-to-video /
    # image-to-video when the request has no video source.
    generation_kind: MediaGenerationKind = MediaGenerationKind.CREATE


VENDOR_MODEL_CATALOG: dict[VendorId, list[ModelCatalogEntry]] = {
    "aihubmix": [
        ModelCatalogEntry(
            model="minimax-h3",
            display_name="MiniMax H3",
            kind="media",
            protocol="minimax",
            input_modalities=("text", "image", "video", "audio"),
            output_modalities=("video",),
            notes=(
                "4-15秒，768P/2K，十种宽高比（16:9/9:16/1:1/4:3/3:4/21:9/3:2/2:3/9:21/"
                "adaptive）；frame_images（首尾帧）与 input_references（全能参考）二选一。"
                "官方还单列 H3-Context-IR 输入处理步骤（$0.90/M 输入、$3.60/M 输出 token），"
                "本目录未把它当作独立计费项——本项目当前接入未单独调用该预处理步骤。"
            ),
            doc_url="https://platform.minimaxi.com/docs/guides/video-generation",
            pricing_doc_url="https://platform.minimax.io/docs/guides/pricing-paygo",
            billing_profile="minimax_h3_payg",
            price_items=(
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（768P）",
                    default_micro_usd=_usd_micro_usd(0.08),
                    source_currency="USD",
                    source_amount="$0.08/秒",
                    quoted_on="2026-08",
                    dimension="768P",
                ),
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（2K）",
                    default_micro_usd=_usd_micro_usd(0.13),
                    source_currency="USD",
                    source_amount="$0.13/秒",
                    quoted_on="2026-08",
                    dimension="2K",
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="输入参考视频（按输出档 768P 计）",
                    default_micro_usd=_usd_micro_usd(0.08),
                    source_currency="USD",
                    source_amount="$0.08/秒（与 768P 输出同价）",
                    quoted_on="2026-08",
                    dimension="768P",
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="输入参考视频（按输出档 2K 计）",
                    default_micro_usd=_usd_micro_usd(0.13),
                    source_currency="USD",
                    source_amount="$0.13/秒（与 2K 输出同价）",
                    quoted_on="2026-08",
                    dimension="2K",
                ),
                PriceItem(
                    key="video_extra_reference_image",
                    unit="per_image",
                    label="超出免费张数的参考图",
                    default_micro_usd=_usd_micro_usd(0.04),
                    source_currency="USD",
                    source_amount="$0.04/张（前 5 张免费）",
                    quoted_on="2026-08",
                    free_count=5,
                ),
            ),
        ),
        ModelCatalogEntry(
            model="wan2.7-videoedit",
            display_name="通义万相 2.7 视频编辑",
            kind="media",
            protocol="minimax",
            input_modalities=("text", "video"),
            output_modalities=("video",),
            notes="2-10秒，720p/1080p，五种宽高比；带引用时内部经 OpenAI Videos API 通道转发。",
            doc_url="https://aihubmix.com/model/wan2.7-videoedit",
            pricing_doc_url="https://aihubmix.com/model/wan2.7-videoedit",
            billing_profile="wan27_videoedit_per_second",
            generation_kind=MediaGenerationKind.EDIT,
            price_items=(
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（720p）",
                    default_micro_usd=_usd_micro_usd(0.0846),
                    source_currency="USD",
                    source_amount="$0.0846/秒",
                    quoted_on="2026-08",
                    dimension="720p",
                ),
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（1080p）",
                    default_micro_usd=_usd_micro_usd(0.141),
                    source_currency="USD",
                    source_amount="$0.141/秒",
                    quoted_on="2026-08",
                    dimension="1080p",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="doubao-seedance-2-5-260628",
            display_name="豆包 Seedance 2.5",
            kind="media",
            protocol="minimax",
            input_modalities=("text", "image"),
            output_modalities=("video",),
            notes=(
                "4-30秒或 -1 智能时长，480p/720p，六种宽高比+adaptive，"
                "支持 generate_audio 原生配音；轮询走 /ai/v1/videos/{id}（与 H3 的 "
                "/ai/v1/tasks/{id} 不同，未经真实凭证验证）。按 Token 计费，非固定每秒价——"
                "两档单价对应是否附带参考视频，见价格项。"
            ),
            doc_url="https://aihubmix.com/model/doubao-seedance-2-5-260628",
            # AiHubMix is a USD gateway; the matching upstream channel is
            # BytePlus ModelArk's *international* price list, not Volcano
            # Ark's CNY-quoted domestic one (see the DMXAPI entry below for
            # that one) — the two are genuinely different rate cards, not
            # the same number in two currencies.
            pricing_doc_url="https://docs.byteplus.com/en/docs/ModelArk/1330310",
            billing_profile="seedance_tokens",
            price_items=(
                PriceItem(
                    key="token_video_no_ref",
                    unit="per_million_tokens",
                    label="视频 Token（不含视频参考）",
                    default_micro_usd=_usd_micro_usd(10.70),
                    source_currency="USD",
                    source_amount="$10.70/M token",
                    quoted_on="2026-08",
                ),
                PriceItem(
                    key="token_video_with_ref",
                    unit="per_million_tokens",
                    label="视频 Token（含视频参考）",
                    default_micro_usd=_usd_micro_usd(6.40),
                    source_currency="USD",
                    source_amount="$6.40/M token",
                    quoted_on="2026-08",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="gpt-image-2",
            display_name="GPT Image 2",
            kind="media",
            protocol="openai",
            input_modalities=("text", "image"),
            output_modalities=("image",),
            notes=(
                "OpenAI 最新生图模型。文生图走 /v1/images/generations，图生图走 "
                "/v1/images/edits（multipart），不要往 generations 塞 image 字段。"
                "quality 随 studio 档位：preview→low / standard→medium / cinematic→high；"
                "尺寸映射到 1024x1024 / 1536x1024 / 1024x1536，本轮不发明 2K/4K 像素。"
                "生成可能超过 5 分钟，端点超时须设为 600000ms（10 分钟）。"
                "真实扣费按 token（文本输入 $5/M、文本输出 $10/M、图像输入 $8/M、"
                "图像输出 $30/M）；下列按张价是官方计算器估算，仅供表单预填。"
                "不适合长时间多视角角色环（单次已接近 10 分钟）。"
            ),
            doc_url="https://aihubmix.com/model/gpt-image-2",
            pricing_doc_url="https://aihubmix.com/model/gpt-image-2",
            billing_profile="gpt_image_2_tokens",
            suggested_timeout_ms=600_000,
            price_items=(
                PriceItem(
                    key="image_generation",
                    unit="per_image",
                    label="生成输出（约 1024² medium）",
                    default_micro_usd=_usd_micro_usd(0.053),
                    source_currency="USD",
                    source_amount="$0.053/张（OpenAI 官方计算器 medium 1024x1024 估算）",
                    quoted_on="2026-09",
                ),
                PriceItem(
                    key="image_generation",
                    unit="per_image",
                    label="生成输出（1K / medium）",
                    default_micro_usd=_usd_micro_usd(0.053),
                    source_currency="USD",
                    source_amount="$0.053/张（OpenAI 官方计算器 medium 1024x1024 估算）",
                    quoted_on="2026-09",
                    dimension="1K",
                ),
                PriceItem(
                    key="image_generation",
                    unit="per_image",
                    label="生成输出（2K / high 保守估算）",
                    default_micro_usd=_usd_micro_usd(0.211),
                    source_currency="USD",
                    source_amount="$0.211/张（OpenAI 官方计算器 high 1024x1024 估算）",
                    quoted_on="2026-09",
                    dimension="2K",
                ),
            ),
        ),
    ],
    "dmxapi": [
        ModelCatalogEntry(
            model="MiniMax-H3",
            display_name="MiniMax H3",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text", "image", "video", "audio"),
            output_modalities=("video",),
            notes=(
                "4-15秒，768P/2K，六种宽高比（21:9/16:9/4:3/1:1/3:4/9:16）；"
                "文生视频场景 ratio 必填且不可为 adaptive。价格对齐 MiniMax 官网"
                "国内按量计费页，与 AiHubMix 版本（对齐国际 PAYG 页）数字不同——"
                "两者是不同结算体系，不是同一价换算币种。"
            ),
            doc_url="https://doc.dmxapi.cn/MiniMax-H3-text-to-video.html",
            pricing_doc_url="https://platform.minimaxi.com/docs/guides/pricing-paygo",
            billing_profile="minimax_h3_payg",
            price_items=(
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（768P）",
                    default_micro_usd=_cny_micro_usd(0.50),
                    source_currency="CNY",
                    source_amount="0.50 元/秒",
                    quoted_on="2026-08",
                    dimension="768P",
                    markup_note=(
                        "MiniMax 国内厂商原价，DMXAPI 实际扣费另加价 + 含税 6%，"
                        "请登录 rmb.dmxapi.cn 或控制台核对后修正。"
                    ),
                ),
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（2K）",
                    default_micro_usd=_cny_micro_usd(0.80),
                    source_currency="CNY",
                    source_amount="0.80 元/秒",
                    quoted_on="2026-08",
                    dimension="2K",
                    markup_note=(
                        "MiniMax 国内厂商原价，DMXAPI 实际扣费另加价 + 含税 6%，"
                        "请登录 rmb.dmxapi.cn 或控制台核对后修正。"
                    ),
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="输入参考视频（按输出档 768P 计）",
                    default_micro_usd=_cny_micro_usd(0.50),
                    source_currency="CNY",
                    source_amount="0.50 元/秒（与 768P 输出同价）",
                    quoted_on="2026-08",
                    dimension="768P",
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="输入参考视频（按输出档 2K 计）",
                    default_micro_usd=_cny_micro_usd(0.80),
                    source_currency="CNY",
                    source_amount="0.80 元/秒（与 2K 输出同价）",
                    quoted_on="2026-08",
                    dimension="2K",
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="video_extra_reference_image",
                    unit="per_image",
                    label="超出免费张数的参考图",
                    default_micro_usd=_cny_micro_usd(0.20),
                    source_currency="CNY",
                    source_amount="0.20 元/张（前 5 张免费）",
                    quoted_on="2026-08",
                    free_count=5,
                    markup_note="同上，为厂商原价。",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="MiniMax-H3-video_regeneration",
            display_name="MiniMax H3 视频再生成",
            kind="media",
            protocol="dmxapi",
            # Deliberately no "text" here: unlike every other video model in
            # this catalogue, regeneration can never run text-only — it
            # always requires the one `base_video` reference. Declaring
            # "text" alongside "video" would derive a spurious
            # `text_to_video` capability regeneration can never actually succeed
            # (see `_CAPABILITY_MODALITY_MAP`: `text_to_video` means
            # "text-only input", not "also reads a prompt").
            input_modalities=("video",),
            output_modalities=("video",),
            notes=(
                "仅支持把已符合 MiniMax-H3 768P 输出规格的源视频再生成为 2K，不是通用"
                "用户视频剪辑能力；源视频须含音轨、24fps、宽高均被32整除、"
                "面积≤768x1344（1,032,192像素）、总帧数107-362（约4-15秒）。"
                "不支持任意用户上传视频；无连通性探测（无安全的最小请求体）。"
            ),
            doc_url="https://doc.dmxapi.cn/MiniMax-H3-video-regeneration-text-to-video.html",
            pricing_doc_url="https://platform.minimaxi.com/docs/guides/pricing-paygo",
            billing_profile="minimax_h3_regen_payg",
            generation_kind=MediaGenerationKind.EDIT,
            price_items=(
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="再生成输出（768P→2K）",
                    default_micro_usd=_cny_micro_usd(0.30),
                    source_currency="CNY",
                    source_amount="0.30 元/秒",
                    quoted_on="2026-08",
                    dimension="2K",
                    markup_note=(
                        "MiniMax 国内厂商原价，DMXAPI 实际扣费另加价 + 含税 6%，需运营核对。"
                    ),
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="原任务输入视频（原样计费一次）",
                    default_micro_usd=_cny_micro_usd(0.30),
                    source_currency="CNY",
                    source_amount="0.30 元/秒",
                    quoted_on="2026-08",
                    dimension="2K",
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="video_extra_reference_image",
                    unit="per_image",
                    label="超出免费张数的参考图",
                    default_micro_usd=_cny_micro_usd(0.15),
                    source_currency="CNY",
                    source_amount="0.15 元/张（前 5 张免费）",
                    quoted_on="2026-08",
                    free_count=5,
                    markup_note="同上，为厂商原价。",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="doubao-seedance-2-5-260628",
            display_name="豆包 Seedance 2.5",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text", "image"),
            output_modalities=("video",),
            notes=(
                "4-30秒或 -1 智能时长，480p/720p/1080p，六种宽高比+adaptive，"
                "原生配音默认开启；参考素材写入 input 数组（image_url/video_url + "
                "role=first_frame/last_frame/reference_*），没有顶层 input_references。"
                "按 Token 计费——两档单价对应是否附带参考视频，见价格项；价格对齐火山"
                "方舟国内价目，与 AiHubMix 版本（对齐 BytePlus 国际价目）数字不同。"
            ),
            doc_url="https://doc.dmxapi.cn/doubao-seedance-2-5-260628-text-to-video.html",
            pricing_doc_url="https://docs.volcengine.com/docs/82379/1544106",
            billing_profile="seedance_tokens",
            price_items=(
                PriceItem(
                    key="token_video_no_ref",
                    unit="per_million_tokens",
                    label="视频 Token（不含视频参考）",
                    default_micro_usd=_cny_micro_usd(70),
                    source_currency="CNY",
                    source_amount="70 元/M token",
                    quoted_on="2026-08",
                    markup_note=(
                        "火山方舟国内厂商原价，DMXAPI 实际扣费另加价 + 含税 6%，需运营核对。"
                    ),
                ),
                PriceItem(
                    key="token_video_with_ref",
                    unit="per_million_tokens",
                    label="视频 Token（含视频参考）",
                    default_micro_usd=_cny_micro_usd(42),
                    source_currency="CNY",
                    source_amount="42 元/M token",
                    quoted_on="2026-08",
                    markup_note="同上，为厂商原价。",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="wan3.0-video",
            display_name="通义万相 3.0",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text", "image", "video", "audio"),
            output_modalities=("video",),
            notes=(
                "2-30秒或 -1 智能时长，480P/720P/1080P（大写P，与 doubao 的小写不同）；"
                "文生/图生（首尾帧）/参考生/视频编辑（reference_video+编辑意图 prompt）一体，"
                "无需切换模型名。计费秒数=输出秒数+参考视频秒数；参考图/音频/文档不计费，"
                "开关音轨同价。"
            ),
            doc_url="https://doc.dmxapi.cn/wan3.0-video-text-to-video.html",
            pricing_doc_url="https://help.aliyun.com/zh/model-studio/wan3-0-video",
            billing_profile="wan3_per_second",
            price_items=(
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（480P）",
                    default_micro_usd=_cny_micro_usd(0.3),
                    source_currency="CNY",
                    source_amount="0.3 元/秒",
                    quoted_on="2026-08",
                    dimension="480P",
                    markup_note=(
                        "阿里云百炼国内厂商原价，DMXAPI 实际扣费另加价 + 含税 6%，需运营核对。"
                    ),
                ),
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（720P）",
                    default_micro_usd=_cny_micro_usd(0.6),
                    source_currency="CNY",
                    source_amount="0.6 元/秒",
                    quoted_on="2026-08",
                    dimension="720P",
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（1080P）",
                    default_micro_usd=_cny_micro_usd(1.2),
                    source_currency="CNY",
                    source_amount="1.2 元/秒",
                    quoted_on="2026-08",
                    dimension="1080P",
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="参考视频秒数并入计费秒数（480P）",
                    default_micro_usd=_cny_micro_usd(0.3),
                    source_currency="CNY",
                    source_amount="0.3 元/秒（与 480P 输出同价）",
                    quoted_on="2026-08",
                    dimension="480P",
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="参考视频秒数并入计费秒数（720P）",
                    default_micro_usd=_cny_micro_usd(0.6),
                    source_currency="CNY",
                    source_amount="0.6 元/秒（与 720P 输出同价）",
                    quoted_on="2026-08",
                    dimension="720P",
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="参考视频秒数并入计费秒数（1080P）",
                    default_micro_usd=_cny_micro_usd(1.2),
                    source_currency="CNY",
                    source_amount="1.2 元/秒（与 1080P 输出同价）",
                    quoted_on="2026-08",
                    dimension="1080P",
                    markup_note="同上，为厂商原价。",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="doubao-seedream-5-0-pro-260628",
            display_name="豆包 Seedream 5.0 Pro",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text", "image"),
            output_modalities=("image",),
            notes=(
                "同步调用（非任务轮询）；size 支持 1K/2K 档位或精确 WxH 二选一"
                "（总像素 921600-4194304，宽高比 1/16-16）；最多 10 张参考图（多图融合）；"
                "响应体真实形状未经真实凭证验证。计费按输出像素档位（≤236万像素记为"
                '"1K"档、>236万记为"2K"档），非固定单价。'
            ),
            doc_url="https://doc.dmxapi.cn/doubao-seedream-5-0-pro-260628-text-to-image.html",
            pricing_doc_url="https://docs.volcengine.com/docs/82379/1544106",
            billing_profile="seedream_tiered_image",
            price_items=(
                PriceItem(
                    key="image_generation",
                    unit="per_image",
                    label="生成输出（1K / ≤236万像素）",
                    default_micro_usd=_cny_micro_usd(0.30),
                    source_currency="CNY",
                    source_amount="0.30 元/张",
                    quoted_on="2026-08",
                    dimension="1K",
                    markup_note=(
                        "火山方舟国内厂商原价，DMXAPI 实际扣费另加价 + 含税 6%，需运营核对。"
                    ),
                ),
                PriceItem(
                    key="image_generation",
                    unit="per_image",
                    label="生成输出（2K / >236万像素）",
                    default_micro_usd=_cny_micro_usd(0.60),
                    source_currency="CNY",
                    source_amount="0.60 元/张",
                    quoted_on="2026-08",
                    dimension="2K",
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="image_input_reference",
                    unit="per_image",
                    label="超出免费张数的参考图",
                    default_micro_usd=_cny_micro_usd(0.02),
                    source_currency="CNY",
                    source_amount="0.02 元/张（首张免费）",
                    quoted_on="2026-08",
                    free_count=1,
                    markup_note="同上，为厂商原价。",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="glm-5.3-flash",
            display_name="智谱 GLM-5.3-Flash",
            kind="general",
            input_modalities=("text",),
            context_length=1_310_720,
            notes=(
                "标准 /v1/chat/completions，零代码改动即可接入；"
                "DMXAPI 公开列表页尚未列出该确切版本号，接入前请与运营确认可用性。"
                "上线首两周（至约 2026-09-09）另有 5 折促销价（输入 0.4 元、输出 1.4 元、"
                "缓存命中 0.115 元，每百万 token），到期后恢复本目录的标准价。"
            ),
            pricing_doc_url="https://open.bigmodel.cn/pricing",
            billing_profile="llm_tokens",
            price_items=(
                PriceItem(
                    key="llm_input_tokens",
                    unit="per_million_tokens",
                    label="输入 token",
                    default_micro_usd=_cny_micro_usd(0.8),
                    source_currency="CNY",
                    source_amount="0.8 元/M token",
                    quoted_on="2026-08",
                    volatile=True,
                    markup_note="智谱国内厂商原价，DMXAPI 实际扣费另加价 + 含税 6%，需运营核对。",
                ),
                PriceItem(
                    key="llm_output_tokens",
                    unit="per_million_tokens",
                    label="输出 token",
                    default_micro_usd=_cny_micro_usd(2.8),
                    source_currency="CNY",
                    source_amount="2.8 元/M token",
                    quoted_on="2026-08",
                    volatile=True,
                    markup_note="同上，为厂商原价。",
                ),
                PriceItem(
                    key="llm_cached_input_tokens",
                    unit="per_million_tokens",
                    label="缓存命中 token",
                    default_micro_usd=_cny_micro_usd(0.23),
                    source_currency="CNY",
                    source_amount="0.23 元/M token",
                    quoted_on="2026-08",
                    volatile=True,
                    markup_note="同上，为厂商原价。",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="qwen3.8-flash",
            display_name="通义千问 Qwen3.8-Flash",
            kind="general",
            input_modalities=("text",),
            context_length=1_000_000,
            notes=(
                "标准 /v1/chat/completions，零代码改动即可接入；"
                "DMXAPI 公开列表页尚未列出该确切版本号，接入前请与运营确认可用性。"
                "上线一天内已从 1/3 元下调至 0.8/2.7 元（每百万 token），价格仍在变动，"
                "上线前请重新核对。"
            ),
            pricing_doc_url="https://www.aliyun.com/price/product#/bailian/detail",
            billing_profile="llm_tokens",
            price_items=(
                PriceItem(
                    key="llm_input_tokens",
                    unit="per_million_tokens",
                    label="输入 token",
                    default_micro_usd=_cny_micro_usd(0.8),
                    source_currency="CNY",
                    source_amount="0.8 元/M token",
                    quoted_on="2026-08-27",
                    volatile=True,
                    markup_note=(
                        "阿里云百炼国内厂商原价，DMXAPI 实际扣费另加价 + 含税 6%，需运营核对。"
                    ),
                ),
                PriceItem(
                    key="llm_output_tokens",
                    unit="per_million_tokens",
                    label="输出 token",
                    default_micro_usd=_cny_micro_usd(2.7),
                    source_currency="CNY",
                    source_amount="2.7 元/M token",
                    quoted_on="2026-08-27",
                    volatile=True,
                    markup_note="同上，为厂商原价。",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="gpt-4o-mini-tts",
            display_name="GPT-4o mini TTS",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text",),
            output_modalities=("audio",),
            notes=(
                "OpenAI 官方语音合成模型，走与 tts-1/tts-1-hd 相同的 /v1/audio/speech "
                "端点，11 种预置音色（alloy/ash/ballad/coral/echo/fable/onyx/nova/"
                "sage/shimmer/verse）。官方按 token 计费（输入 $0.60/M token + 输出 "
                "$12/M 音频 token，约 $0.015/分钟），与本目录固定的 per_10k_characters "
                "计价形状不匹配——本条目不给出可能误导的折算单价，运营需在保存端点后"
                "手动填写音频价格。"
            ),
            doc_url="https://doc.dmxapi.cn/openai-tts.html",
            voices=_OPENAI_TTS_VOICES,
        ),
        ModelCatalogEntry(
            model="tts-1",
            display_name="OpenAI TTS-1",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text",),
            output_modalities=("audio",),
            notes="标准音质，11 种预置音色，与 gpt-4o-mini-tts 同一 /v1/audio/speech 端点。",
            voices=_OPENAI_TTS_VOICES,
            doc_url="https://doc.dmxapi.cn/openai-tts.html",
            pricing_doc_url="https://platform.openai.com/docs/pricing",
            price_items=(
                PriceItem(
                    key="audio_generation",
                    unit="per_10k_characters",
                    label="语音合成（标准音质）",
                    default_micro_usd=_usd_micro_usd(0.15),
                    source_currency="USD",
                    source_amount="$15.00/M 字符",
                    quoted_on="2026-08",
                    markup_note=(
                        "OpenAI 官方美元定价（非国内厂商原价），DMXAPI 实际扣费按其平台"
                        "汇率与折扣结算，请登录 rmb.dmxapi.cn 或控制台核对后修正。"
                    ),
                ),
            ),
        ),
        ModelCatalogEntry(
            model="tts-1-hd",
            display_name="OpenAI TTS-1 HD",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text",),
            output_modalities=("audio",),
            notes="高清音质，11 种预置音色，同一 /v1/audio/speech 端点，价格是 tts-1 的两倍。",
            voices=_OPENAI_TTS_VOICES,
            doc_url="https://doc.dmxapi.cn/openai-tts.html",
            pricing_doc_url="https://platform.openai.com/docs/pricing",
            price_items=(
                PriceItem(
                    key="audio_generation",
                    unit="per_10k_characters",
                    label="语音合成（高清音质）",
                    default_micro_usd=_usd_micro_usd(0.30),
                    source_currency="USD",
                    source_amount="$30.00/M 字符",
                    quoted_on="2026-08",
                    markup_note=(
                        "OpenAI 官方美元定价（非国内厂商原价），DMXAPI 实际扣费按其平台"
                        "汇率与折扣结算，请登录 rmb.dmxapi.cn 或控制台核对后修正。"
                    ),
                ),
            ),
        ),
        ModelCatalogEntry(
            model="tts-pro",
            display_name="火山语音合成（情感音色）",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text",),
            output_modalities=("audio",),
            notes=(
                "字节跳动火山引擎语音合成大模型转售，同一 /v1/audio/speech 端点，"
                "额外 emotion 字段（happy/angry/fear/surprise）。实际音色有几十个，"
                "下列 `voices` 只是一个有代表性的子集（未逐一核对真实凭证返回的完整"
                "列表），studio 按此展示候选音色供选择，而非穷举全部。"
            ),
            doc_url="https://doc.dmxapi.cn/tts-pro.html",
            voices=(
                "柔美女友",
                "妩媚女生",
                "京腔小爷",
                "猴哥",
                "爽快思思(多情感)",
                "温柔小雅",
                "甜美小源",
                "知性女声",
                "阳光男声",
                "儒雅青年",
            ),
            pricing_doc_url="https://docs.volcengine.com/docs/6561/1359370?lang=zh",
            price_items=(
                PriceItem(
                    key="audio_generation",
                    unit="per_10k_characters",
                    label="语音合成（系统音色）",
                    default_micro_usd=_cny_micro_usd(3.0),
                    source_currency="CNY",
                    source_amount="0.0003 元/字符（豆包语音合成2.0系统音色）",
                    quoted_on="2026-08",
                    volatile=True,
                    markup_note=(
                        "火山引擎“豆包语音合成2.0-系统音色”厂商原价，DMXAPI 的 tts-pro "
                        "音色范围/计费档位是否完全对应未经真实凭证核实，请登录 "
                        "rmb.dmxapi.cn 或控制台核对后修正。"
                    ),
                ),
            ),
        ),
        ModelCatalogEntry(
            model="music-3.0",
            display_name="MiniMax 音乐生成 3.0（DMXAPI转售）",
            kind="media",
            protocol="dmxapi",
            input_modalities=("text",),
            output_modalities=("audio",),
            notes=(
                "MiniMax Music 3.0 转售，走与视频/图片同一 /v1/responses 端点，但"
                "同步返回完整成品（无需轮询）。`input` 为风格/主题描述，可选 "
                "`lyrics`（[Verse]/[Chorus] 结构标签），`is_instrumental=true` 则"
                "省略歌词只出纯音乐。纯音乐生成，无独立音效（SFX）子模式——音效"
                "请改用本目录 fal 的 elevenlabs/sound-effects/v2。"
                "DMXAPI 定价页未公开该模型的明确费率，需登录 rmb.dmxapi.cn 或做"
                "真实凭证连通性活检后再手动填写价格，故本条目未给出 price_items。"
            ),
            doc_url="https://doc.dmxapi.cn/music-3.0-text-to-music.html",
        ),
    ],
    "metaso": [
        ModelCatalogEntry(
            model="MiniMax-H3",
            display_name="MiniMax H3",
            kind="media",
            protocol="minimax_v2",
            input_modalities=("text", "image", "video", "audio"),
            output_modalities=("video",),
            notes=(
                "官方 MiniMax Video V2（content[]）：4-15秒，768P/2K，六种宽高比"
                "（21:9/16:9/4:3/1:1/3:4/9:16）+ adaptive。"
                "文生视频 ratio 必填且不可为 adaptive（本适配器会把 adaptive 落到 16:9）；"
                "图生首尾帧强制 adaptive；多模态参考与首尾帧互斥。"
                "走 https://metaso.cn/api/minimax/v2/video_generation，不是 OpenAI /v1/videos。"
                "查询/取消路径按官方 V2 推断，尚未对秘塔 live 凭证确认。"
                "价格取自秘塔 H3 价目页，与 AiHubMix 国际 PAYG、DMXAPI 国内官价都不同。"
            ),
            doc_url="https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create",
            pricing_doc_url="https://metaso.cn/minimax-h3",
            billing_profile="minimax_h3_payg",
            price_items=(
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（768P）",
                    default_micro_usd=_cny_micro_usd(0.09),
                    source_currency="CNY",
                    source_amount="0.09 元/秒",
                    quoted_on="2026-09",
                    dimension="768P",
                ),
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（2K）",
                    default_micro_usd=_cny_micro_usd(0.15),
                    source_currency="CNY",
                    source_amount="0.15 元/秒",
                    quoted_on="2026-09",
                    dimension="2K",
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="输入参考视频（按输出档 768P 计）",
                    default_micro_usd=_cny_micro_usd(0.09),
                    source_currency="CNY",
                    source_amount="0.09 元/秒（与 768P 输出同价）",
                    quoted_on="2026-09",
                    dimension="768P",
                ),
                PriceItem(
                    key="video_input_material",
                    unit="per_second",
                    label="输入参考视频（按输出档 2K 计）",
                    default_micro_usd=_cny_micro_usd(0.15),
                    source_currency="CNY",
                    source_amount="0.15 元/秒（与 2K 输出同价）",
                    quoted_on="2026-09",
                    dimension="2K",
                ),
                PriceItem(
                    key="video_extra_reference_image",
                    unit="per_image",
                    label="超出免费张数的参考图",
                    default_micro_usd=_cny_micro_usd(0.05),
                    source_currency="CNY",
                    source_amount="0.05 元/张（前 5 张免费）",
                    quoted_on="2026-09",
                    free_count=5,
                ),
            ),
        ),
    ],
    "fal": [
        ModelCatalogEntry(
            model="minimax/h3-max",
            display_name="MiniMax H3 Max",
            kind="media",
            protocol="fal",
            input_modalities=("text", "image", "video", "audio"),
            output_modalities=("video",),
            notes=(
                "fal.ai MiniMax H3 Max（queue.fal.run）：5-15秒，仅 480P/768P，无 2K。"
                "文生六种宽高比（21:9/16:9/4:3/1:1/3:4/9:16），studio adaptive 落到 16:9；"
                "图生有首帧时跟图走、不传 aspect_ratio；参考生保留 adaptive。"
                "一个端点按引用分发三个 app：text-to-video / image-to-video（首尾帧）/"
                "reference-to-video（图/视频/音频参考，最多 12 个，音频不能单独作为参考）。"
                "扩写固定 balanced。鉴权是 Authorization: Key，不是 Bearer。"
                "参考生刊例一律 $0.08/秒（480P 参考作业会略低估平台成本）。"
                "2026-09-07 结束的 75% 上线促销已按正式价预填。"
                "query/cancel 按 fal queue 文档接入，尚未对 live 凭证确认。"
            ),
            doc_url="https://fal.ai/models/minimax/h3-max/text-to-video",
            pricing_doc_url="https://fal.ai/models/minimax/h3-max/text-to-video",
            billing_profile="fal_h3_max",
            suggested_timeout_ms=60_000,
            price_items=(
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（480P）",
                    default_micro_usd=_usd_micro_usd(0.05),
                    source_currency="USD",
                    source_amount="$0.05/秒",
                    quoted_on="2026-09",
                    dimension="480P",
                ),
                PriceItem(
                    key="video_generation",
                    unit="per_second",
                    label="生成输出（768P）",
                    default_micro_usd=_usd_micro_usd(0.08),
                    source_currency="USD",
                    source_amount="$0.08/秒",
                    quoted_on="2026-09",
                    dimension="768P",
                ),
                PriceItem(
                    key="video_extra_reference_image",
                    unit="per_image",
                    label="超出免费张数的参考图",
                    default_micro_usd=_usd_micro_usd(0.02),
                    source_currency="USD",
                    source_amount="$0.02/张（前 4 张免费，近似 fal 前 4096 token）",
                    quoted_on="2026-09",
                    free_count=4,
                ),
            ),
        ),
        ModelCatalogEntry(
            model="minimax/voice-clone",
            display_name="MiniMax Voice Clone",
            kind="media",
            protocol="fal",
            input_modalities=("text", "audio"),
            output_modalities=("audio",),
            notes=(
                "fal.ai MiniMax Voice Clone（`fal-ai/minimax/voice-clone`）：单次调用完成"
                "「克隆+试听」——一条参考音频（`audio_url`，至少10秒）加一段文本"
                "（`text`）直接换回克隆音色朗读的成品音频（`audio.url`），不需要先注册声音"
                "再合成。返回体里也带一个 `custom_voice_id`（fal 侧7天有效的声音复用凭证），"
                "本仓库当前只取 `audio.url`，未消费该 ID 做二次合成。"
                "计费按次（每次克隆调用 $1.50），与按字符计费的普通 TTS 模型不同。"
                "query/cancel 按 fal queue 文档接入，尚未对 live 凭证确认。"
            ),
            doc_url="https://fal.ai/models/fal-ai/minimax/voice-clone",
            pricing_doc_url="https://fal.ai/models/fal-ai/minimax/voice-clone",
            billing_profile="fal_voice_clone",
            suggested_timeout_ms=60_000,
            price_items=(
                PriceItem(
                    key="audio_generation",
                    unit="per_request",
                    label="声音克隆（每次调用，含试听）",
                    default_micro_usd=_usd_micro_usd(1.50),
                    source_currency="USD",
                    source_amount="$1.50/次",
                    quoted_on="2026-09",
                ),
                PriceItem(
                    key="audio_generation",
                    unit="per_10k_characters",
                    label="试听文本（超出免费额度后按字符计）",
                    default_micro_usd=_usd_micro_usd(3.00),
                    source_currency="USD",
                    source_amount="$0.30/1000字符",
                    quoted_on="2026-09",
                    dimension="preview_text",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="minimax-music/v2.6",
            display_name="MiniMax Music 2.6",
            kind="media",
            protocol="fal",
            input_modalities=("text",),
            output_modalities=("audio",),
            notes=(
                "fal.ai MiniMax Music 2.6（`fal-ai/minimax-music/v2.6`）：`prompt` "
                "描述风格/主题，可选 `lyrics`（[Verse]/[Chorus] 结构标签），省略即"
                "为纯伴奏。单次最长约60秒，无显式时长参数——模型自行决定成品"
                "长度。按次计费，与按时长/字符计费的模型不同。"
                "query/cancel 按 fal queue 文档接入，尚未对 live 凭证确认。"
            ),
            doc_url="https://fal.ai/models/fal-ai/minimax-music/v2.6",
            pricing_doc_url="https://fal.ai/models/fal-ai/minimax-music/v2.6",
            suggested_timeout_ms=90_000,
            price_items=(
                PriceItem(
                    key="music_generation",
                    unit="per_request",
                    label="音乐生成（每次调用）",
                    default_micro_usd=_usd_micro_usd(0.15),
                    source_currency="USD",
                    source_amount="$0.15/次",
                    quoted_on="2026-09",
                ),
            ),
        ),
        ModelCatalogEntry(
            model="elevenlabs/sound-effects/v2",
            display_name="ElevenLabs Sound Effects V2",
            kind="media",
            protocol="fal",
            input_modalities=("text",),
            output_modalities=("audio",),
            notes=(
                "fal.ai ElevenLabs Sound Effects V2（`fal-ai/elevenlabs/sound-"
                "effects/v2`）：`text` 描述音效，`duration_seconds` 显式时长"
                "（0.5-22秒，本平台按整秒下发）——本目录里唯一一个音乐/音效模型"
                "接受显式时长控制。官方按秒计费（$0.002/秒），与本平台 "
                "`MusicPricing` 固定按次计费的形状不匹配：下方价格是按 5 秒"
                "（一次典型短音效的代表性时长）折算的按次估算，不是官方按秒"
                "费率本身，实际时长不同时需要运营手动调整。"
                "query/cancel 按 fal queue 文档接入，尚未对 live 凭证确认。"
            ),
            doc_url="https://fal.ai/models/fal-ai/elevenlabs/sound-effects/v2",
            pricing_doc_url="https://fal.ai/models/fal-ai/elevenlabs/sound-effects/v2",
            suggested_timeout_ms=60_000,
            price_items=(
                PriceItem(
                    key="music_generation",
                    unit="per_request",
                    label="音效生成（按 5 秒代表性时长折算的每次调用价）",
                    default_micro_usd=_usd_micro_usd(0.002 * 5),
                    source_currency="USD",
                    source_amount="$0.002/秒（官方按秒计费，非本行按次金额）",
                    quoted_on="2026-09",
                    markup_note="按 5 秒代表性时长折算为按次计价；实际时长不同需手动调整。",
                ),
            ),
        ),
    ],
}


def vendor_base_url(vendor: VendorId) -> str:
    return VENDOR_BASE_URLS[vendor]


def catalog_entry(vendor: VendorId, model: str) -> ModelCatalogEntry | None:
    for entry in VENDOR_MODEL_CATALOG.get(vendor, []):
        if entry.model == model:
            return entry
    return None


def display_name_for_model(model: str) -> str | None:
    """A friendly label for a raw, admin-configured `endpoint.model` string,
    for the C-end model picker (`GET /v1/generation-jobs/models`) — never
    validated against or enforced, purely cosmetic.

    Unlike `catalog_entry`, this searches every vendor's list and matches
    case-insensitively: the same nominal model is sometimes typed with
    different casing per vendor (e.g. AiHubMix's `minimax-h3` vs. DMXAPI's
    `MiniMax-H3` — see `zaolang-platform-config` invariant #9), and the C-end
    picker has no vendor context at all, only the bare model string a
    `ProviderCapability.model_or_workflow` carries. Returns `None` when no
    catalog entry matches, so the caller can fall back to the raw string
    instead of showing a blank label.
    """
    lowered = model.strip().lower()
    if not lowered:
        return None
    for entries in VENDOR_MODEL_CATALOG.values():
        for entry in entries:
            if entry.model.strip().lower() == lowered:
                return entry.display_name
    return None


def voices_for_model(model: str) -> tuple[str, ...] | None:
    """`ModelCatalogEntry.voices` for a raw, admin-configured `endpoint.
    model` string, the same case-insensitive cross-vendor lookup
    `display_name_for_model` does — the C-end model picker (`GET /v1/
    generation-jobs/models`) has no vendor context either, only the bare
    model string a `ProviderCapability.model_or_workflow` carries.

    Returns `None` for a model with no catalogue entry, or one whose entry
    declares no discrete voice roster (fal's single-call clone models,
    music/SFX models, or a video/image model entirely) — the studio then
    falls back to its clone-upload tab instead of a voice `Select`.
    """
    lowered = model.strip().lower()
    if not lowered:
        return None
    for entries in VENDOR_MODEL_CATALOG.values():
        for entry in entries:
            if entry.model.strip().lower() == lowered and entry.voices:
                return entry.voices
    return None
