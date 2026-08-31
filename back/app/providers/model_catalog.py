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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VendorId = Literal["aihubmix", "dmxapi"]
VENDOR_IDS: tuple[VendorId, ...] = ("aihubmix", "dmxapi")

# Presets for the admin picker's "base URL" field — still a plain text input
# an operator can override, same as every other pre-filled value here.
VENDOR_BASE_URLS: dict[VendorId, str] = {
    "aihubmix": "https://aihubmix.com",
    "dmxapi": "https://www.dmxapi.cn",
}

VENDOR_LABELS: dict[VendorId, str] = {
    "aihubmix": "AiHubMix",
    "dmxapi": "DMXAPI",
}


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
            ),
            doc_url="https://platform.minimaxi.com/docs/guides/video-generation",
        ),
        ModelCatalogEntry(
            model="wan2.7-videoedit",
            display_name="通义万相 2.7 视频编辑",
            kind="media",
            protocol="minimax",
            input_modalities=("text", "video"),
            output_modalities=("video",),
            notes="2-10秒，720p/1080p，五种宽高比；带引用时内部经 OpenAI Videos API 通道转发。",
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
                "/ai/v1/tasks/{id} 不同，未经真实凭证验证）。"
            ),
            doc_url="https://aihubmix.com/model/doubao-seedance-2-5-260628",
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
                "文生视频场景 ratio 必填且不可为 adaptive。"
            ),
            doc_url="https://doc.dmxapi.cn/MiniMax-H3-text-to-video.html",
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
            # `text_to_video` candidate that could never actually succeed
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
                "原生配音默认开启；首尾帧/参考图字段未经真实凭证验证（推断自"
                "AiHubMix 对同一模型已确认的 schema）。"
            ),
            doc_url="https://doc.dmxapi.cn/doubao-seedance-2-5-260628-text-to-video.html",
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
                "无需切换模型名。"
            ),
            doc_url="https://doc.dmxapi.cn/wan3.0-video-text-to-video.html",
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
                "响应体真实形状未经真实凭证验证。"
            ),
            doc_url="https://doc.dmxapi.cn/doubao-seedream-5-0-pro-260628-text-to-image.html",
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
