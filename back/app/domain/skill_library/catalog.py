"""Seed catalogue of `CreationSkill` templates: short-drama video recipes,
a 「提示词格式 format」section carrying structural writing rules rather than
content, a 「戏码与情绪 drama」section carrying the opposite (one kind of
scene, played and cut), a "图片风格 image style" section for the image studio,
a canvas section (framing / lighting / staging / method) for composing a
still before it is animated, and a dual-shape 「图片资产」section
(`character` / `scene_asset` / `cover_asset`).

Genre/shot/scene *naming conventions* here are informed by patterns common to
several open-source "AI short-drama" Agent Skill suites (Claude/Codex
`SKILL.md` instruction sets), the image-style section's naming is informed
by publicly documented 2026 Nano Banana / GPT-Image prompt-trend write-ups,
and the image-asset section's *layout names* (turnaround sheet, expression
grid, empty establishing still, title-safe cover) are informed by public
character-sheet / environment / cover Agent Skills — see
`THIRD_PARTY_NOTICES.md` in this package for sources and licences. None of
that is a `CreationSkill.params_json` template to begin with: an Agent
Skill's `SKILL.md` drives an LLM coding agent through a multi-file
production pipeline, and a prompt-trend write-up is prose about a
technique, not a flat `prompt_suffix`/`aspect_ratio` dict a job folds in.
Every `title` / `description` / `prompt_suffix` below is original text
written for this catalogue.

The canvas section is the newest and exists because of an asymmetry the
rest of the catalogue has: every `lens` and `scene` recipe above it is
scoped to `_VIDEO_OPERATIONS`, since a camera *move* only means something
over time. The canvas works the other way round — compose a still, then
animate it — so it needs framing, lighting and staging vocabulary that a
`text_to_image` job will actually accept. Without those rows a lens card
dragged from the prompt library onto an image node is silently dropped by
`execute_skill_context`: visible on the canvas, absent from the request.

The 「提示词格式」section is the only one that is not about a look at all.
Every other section answers "what should this shot be"; that one answers
"how should the prompt be written", which is why it needed a category of its
own instead of being folded into `lens`/`style` — see its own section
comment for the boundary test and `docs/video-prompt-formats.md` for the
vendor evidence behind each rule.

The 「戏码与情绪」section is its mirror: a `format` row stays true whatever
the clip is about, a `drama` row means nothing outside the one situation or
emotion it names. That is also what makes it the only category
`app.agents.skill_matcher` searches — a plot description can point at a
scene type, it can never point at a writing rule. See
`docs/video-drama-scenes.md`.

Not every entry here has a cover in `seed_covers/`; the canvas and format
sections ship without them for now and `ensure_catalog_skills` looks a cover
up per key rather than assuming one.

`ensure_catalog_skills` (`app.domain.skill_library.service`) is what turns
this table into real `CreationSkill` rows — this module only declares *what*
to seed and never touches a session or an ORM class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.enums import CreationSkillCategory, Operation

# AI-generated cover stills shipped alongside this module (one JPEG per
# `CatalogSkill.key`), committed to the repo as system-default content —
# `ensure_catalog_skills` uploads whichever of these exist and are still
# missing from a seeded skill's `cover_asset_id`. Not every entry is
# guaranteed to have one (a catalogue addition that hasn't had a cover
# generated yet), so this is looked up per-key rather than assumed.
_COVERS_DIR = Path(__file__).parent / "seed_covers"

# The studio's skill picker / prompt `@` menu and `execute_skill_context`
# both skip a skill whose declared `applicable_operations` doesn't include
# the job's own operation (an empty tuple means "any operation"). Most of
# this catalogue targets short-drama video production and stays scoped to
# `_VIDEO_OPERATIONS` on purpose — a `lens`/`scene` shot-composition recipe
# or a script `beat` (`other`) doesn't mean anything as a single still
# image. The "图片风格 image style" section and the later 「图片资产」
# section are the deliberate exceptions: those rows use `_IMAGE_OPERATIONS`
# instead so they surface in the image studio's `@` menu
# (`text_to_image`/`image_to_image`) and stay out of the video one. Image
# styles stay on `STYLE`; image-asset rows use `CHARACTER` / `SCENE_ASSET` /
# `COVER_ASSET` so the marketplace 「图片资产」tab can list them.
_VIDEO_OPERATIONS: tuple[Operation, ...] = (
    Operation.TEXT_TO_VIDEO,
    Operation.IMAGE_TO_VIDEO,
    Operation.VIDEO_TO_VIDEO,
)
_IMAGE_OPERATIONS: tuple[Operation, ...] = (
    Operation.TEXT_TO_IMAGE,
    Operation.IMAGE_TO_IMAGE,
)


@dataclass(frozen=True, slots=True)
class CatalogSkill:
    """One seeded `CreationSkill` template.

    `key` is this catalogue's own stable identity for tests/tooling — it is
    never persisted. `CreationSkill` has no dedicated catalogue-key column
    (adding one for ~310 seed rows isn't worth a migration), so
    `ensure_catalog_skills` matches an existing row by `(owner_user_id,
    title)` instead; `title` is therefore the real identity once seeded.
    """

    key: str
    title: str
    description: str
    category: CreationSkillCategory
    prompt_suffix: str
    aspect_ratio: str = "9:16"
    applicable_operations: tuple[Operation, ...] = _VIDEO_OPERATIONS

    def params_json(self) -> dict[str, Any]:
        """Flat recipe keys plus, for image-asset categories, the nested
        character/scene bundle `ensure_catalog_skills` later fills with the
        seeded cover as a reference still."""
        flat: dict[str, Any] = {
            "prompt_suffix": self.prompt_suffix,
            "aspect_ratio": self.aspect_ratio,
        }
        if self.category == CreationSkillCategory.CHARACTER:
            return {
                **flat,
                "character": {
                    "description": self.description,
                    "voice_description": None,
                    "reference_assets": [],
                },
            }
        if self.category == CreationSkillCategory.SCENE_ASSET:
            return {
                **flat,
                "scene": {"description": self.description, "reference_assets": []},
            }
        return flat

    def cover_path(self) -> Path | None:
        """This entry's seeded cover JPEG, or `None` if none was shipped."""
        candidate = _COVERS_DIR / f"{self.key}.jpg"
        return candidate if candidate.is_file() else None


# Keys of the canvas still section — framing, lighting, staging and method
# recipes meant for composing a single frame rather than describing a camera
# move over time. The `light-` rows are `STYLE` (like the image-style section);
# the rest are `LENS` / `SCENE` / `OTHER` by meaning but declare `_IMAGE_OPERATIONS`,
# which is the exception to "shot-composition categories are video-only"; see
# the module docstring and `test_video_only_categories_never_declare_image_operations`.
CANVAS_STILL_KEY_PREFIXES = ("frame-", "light-", "stage-", "method-")

# Entries that are catalogued but have no cover still generated yet.
#
# Enumerated rather than tolerated: `test_ensure_catalog_skills_backfills_a_cover_for_every_entry`
# holds every *other* entry to shipping one, so a missing cover stays a visible
# to-do in this file instead of a marketplace tile that quietly renders blank.
# Producing these means running real image generations against a live provider,
# which is an operator action, not a code change. Delete a key from here the
# moment `seed_covers/<key>.jpg` lands.
COVERS_PENDING: frozenset[str] = frozenset(
    {
        "frame-low-angle-wide-establish",
        "frame-tight-portrait-negative-space",
        "frame-foreground-occlusion-layer",
        "frame-symmetry-center-power",
        "frame-over-shoulder-still",
        "frame-reflection-double-read",
        "frame-hands-and-object",
        "frame-crowd-isolate-one",
        "light-single-source-hard-key",
        "light-practical-motivated",
        "light-backlit-silhouette-rim",
        "light-window-soft-morning",
        "light-two-tone-split",
        "light-overcast-flat-documentary",
        "stage-two-hander-distance",
        "stage-threshold-doorway",
        "stage-empty-chair-absence",
        "stage-height-difference-power",
        "stage-vertical-safe-margins",
        "stage-weather-as-pressure",
        "method-shot-pair-reverse",
        "method-keyframe-first-last",
        "method-continuity-anchor",
        "method-no-text-in-frame",
        # The 提示词格式 section, all 120 of it. Unlike the sections above,
        # these entries have nothing photographable to put on a cover — a
        # 「一镜一运镜」tile would have to illustrate a rule, not a look — so
        # they need art direction of their own before any generation run is
        # worth doing.
        "fmt-frame-minimal-core",
        "fmt-frame-five-slot-video",
        "fmt-frame-camera-first",
        "fmt-frame-eleven-section",
        "fmt-frame-prose-plus-blocks",
        "fmt-frame-key-value-block",
        "fmt-frame-motion-block",
        "fmt-frame-constraints-tail",
        "fmt-frame-three-sentence",
        "fmt-frame-word-budget",
        "fmt-hook-open-mid-conflict",
        "fmt-hook-one-line-identity",
        "fmt-hook-object-ecu",
        "fmt-hook-charge-to-camera",
        "fmt-hook-direct-address",
        "fmt-hook-status-drop",
        "fmt-hook-sound-first",
        "fmt-hook-cold-open",
        "fmt-hook-visible-countdown",
        "fmt-hook-three-signal-open",
        "fmt-action-one-beat-reaction",
        "fmt-action-body-part",
        "fmt-action-counted-beats",
        "fmt-action-relative-pacing",
        "fmt-action-emotion-externalized",
        "fmt-action-speed-evidence",
        "fmt-action-enter-exit-frame",
        "fmt-action-physical-contact",
        "fmt-action-single-active-subject",
        "fmt-action-hold-tail",
        "fmt-vertical-shot-size-codes",
        "fmt-vertical-overlay-safe-area",
        "fmt-vertical-caption-band",
        "fmt-vertical-medium-close-first",
        "fmt-vertical-depth-layers",
        "fmt-vertical-two-shot-stagger",
        "fmt-vertical-over-shoulder",
        "fmt-vertical-eyes-upper-third",
        "fmt-vertical-angle-four",
        "fmt-vertical-focal-length",
        "fmt-camera-one-move",
        "fmt-camera-separate-sentence",
        "fmt-camera-term-direction-speed",
        "fmt-camera-bilingual-term",
        "fmt-camera-framing-vs-motion",
        "fmt-camera-relational-verb",
        "fmt-camera-stage-reveal",
        "fmt-camera-locked-off",
        "fmt-camera-handheld-micro-drift",
        "fmt-camera-move-plus-texture",
        "fmt-light-named-source",
        "fmt-light-key-direction",
        "fmt-light-ratio",
        "fmt-light-adjective-to-parameter",
        "fmt-light-high-low-key",
        "fmt-light-continuity-across-shots",
        "fmt-light-material-nouns",
        "fmt-light-time-of-day-anchor",
        "fmt-audio-explicit-declaration",
        "fmt-audio-three-layers",
        "fmt-audio-line-budget",
        "fmt-audio-dialogue-block",
        "fmt-audio-speaker-label",
        "fmt-audio-voice-six",
        "fmt-audio-sfx-after-trigger",
        "fmt-audio-explicit-silence",
        "fmt-transition-whip-direction",
        "fmt-transition-match-pair",
        "fmt-transition-late-chaos",
        "fmt-transition-match-cut",
        "fmt-transition-occluder-pass",
        "fmt-transition-light-wipe",
        "fmt-transition-first-last-frame",
        "fmt-transition-empty-plate",
        "fmt-transition-single-axis",
        "fmt-transition-verb-forward",
        "fmt-lock-identity-block",
        "fmt-lock-verbatim-reuse",
        "fmt-lock-one-ref-one-job",
        "fmt-lock-ref-numbering",
        "fmt-lock-named-label",
        "fmt-lock-name-subject-plus-motion",
        "fmt-lock-changes-only",
        "fmt-lock-palette",
        "fmt-lock-light-direction",
        "fmt-lock-wardrobe-state",
        "fmt-lock-hair-state",
        "fmt-lock-prop-position",
        "fmt-lock-eyeline-axis",
        "fmt-lock-screen-direction",
        "fmt-lock-handoff-frame",
        "fmt-lock-ground-wetness",
        "fmt-lock-makeup-damage",
        "fmt-lock-time-of-day",
        "fmt-lock-weather-grade",
        "fmt-lock-body-carryover",
        "fmt-lock-injury-progression",
        "fmt-lock-crowd-density",
        "fmt-lock-camera-height",
        "fmt-lock-focal-length",
        "fmt-lock-color-temperature",
        "fmt-lock-audio-bed",
        "fmt-lock-distance-between",
        "fmt-lock-object-count",
        "fmt-teaser-energy-dip",
        "fmt-teaser-first-act-only",
        "fmt-teaser-question-line",
        "fmt-teaser-cut-at-peak",
        "fmt-teaser-title-safe-band",
        "fmt-teaser-seamless-loop",
        "fmt-teaser-montage-ratio",
        "fmt-teaser-genre-anchor",
        "fmt-guard-positive-phrasing",
        "fmt-guard-negative-field",
        "fmt-guard-short-negative-list",
        "fmt-guard-conflict-check",
        "fmt-guard-occlusion-audit",
        "fmt-guard-no-container-params",
        "fmt-guard-adjective-to-shootable",
        "fmt-guard-caption-leak",
        # The 戏码与情绪 section, all 80 of it. These *are* photographable —
        # a 「雨夜追逐」tile is a real still — but generating eighty covers is
        # a live-provider operator run, so they land in the same queue as the
        # format rows above rather than blocking the entries themselves.
        "drama-scene-hospital-standoff",
        "drama-scene-rooftop-negotiation",
        "drama-scene-car-argument",
        "drama-scene-dinner-showdown",
        "drama-scene-office-humiliation",
        "drama-scene-doorway-refusal",
        "drama-scene-elevator-trap",
        "drama-scene-parking-lot-block",
        "drama-scene-courtroom-reversal",
        "drama-scene-family-verdict",
        "drama-scene-badge-reveal",
        "drama-scene-phone-call-reveal",
        "drama-scene-boardroom-entrance",
        "drama-scene-entourage-arrival",
        "drama-scene-signature-reveal",
        "drama-scene-mask-removal",
        "drama-scene-old-photo-found",
        "drama-scene-report-truth",
        "drama-scene-rain-farewell",
        "drama-scene-snow-farewell",
        "drama-scene-wedding-reversal",
        "drama-scene-deathbed-goodbye",
        "drama-scene-airport-chase",
        "drama-scene-midnight-kitchen",
        "drama-scene-umbrella-share",
        "drama-scene-bench-confession",
        "drama-scene-hug-from-behind",
        "drama-scene-ring-returned",
        "drama-scene-rain-chase",
        "drama-scene-stairwell-pursuit",
        "drama-scene-alley-cornered",
        "drama-scene-car-tail",
        "drama-scene-crowd-escape",
        "drama-scene-warehouse-standoff",
        "drama-scene-last-second-grab",
        "drama-scene-forced-entry",
        "drama-scene-street-stall-encounter",
        "drama-scene-classroom-callout",
        "drama-scene-shop-snub",
        "drama-scene-lost-and-found",
        "drama-scene-transit-seat-clash",
        "drama-scene-neighbor-doorstep",
        "drama-scene-market-haggle",
        "drama-scene-delivery-at-door",
        "drama-scene-empty-house-return",
        "drama-scene-mirror-behind",
        "drama-scene-surveillance-review",
        "drama-scene-locked-room-opened",
        "drama-scene-followed-at-night",
        "drama-scene-midnight-message",
        "drama-emotion-held-back",
        "drama-emotion-outburst",
        "drama-emotion-feigned-weakness",
        "drama-emotion-counterattack",
        "drama-emotion-blank-shock",
        "drama-emotion-forced-composure",
        "drama-emotion-contempt",
        "drama-emotion-panic",
        "drama-emotion-relief",
        "drama-emotion-guilt",
        "drama-emotion-jealousy",
        "drama-emotion-disgust",
        "drama-emotion-resignation",
        "drama-emotion-hope-rekindled",
        "drama-emotion-suspicion",
        "drama-emotion-embarrassment",
        "drama-emotion-gloating",
        "drama-emotion-heartbreak",
        "drama-emotion-cold-rage",
        "drama-emotion-frozen-fear",
        "drama-emotion-longing",
        "drama-emotion-pride",
        "drama-emotion-betrayal-realized",
        "drama-emotion-exhaustion",
        "drama-emotion-softening",
        "drama-emotion-resolve",
        "drama-emotion-humiliated",
        "drama-emotion-nostalgia",
        "drama-emotion-dread-waiting",
        "drama-emotion-numb-acceptance",
    }
)


CATALOG: tuple[CatalogSkill, ...] = (
    # ---------------------------------------------------------------- 镜头 lens
    CatalogSkill(
        key="lens-extreme-closeup-reveal",
        title="极限特写·揭面反转",
        description=(
            "身份反转前的关键一帧：镜头从局部细节缓缓推近至演员双眼，配合呼吸感停顿，"
            "把“发现真相”的瞬间留给观众自己读出来，而不是靠台词说破。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "extreme close-up push-in on the character's eyes, shallow depth of field, "
            "a half-second breathing pause before the reveal, natural skin texture, "
            "no over-smoothing"
        ),
    ),
    CatalogSkill(
        key="lens-over-the-shoulder-confrontation",
        title="过肩镜头·正面对峙",
        description=(
            "两人对峙戏的标准调度：前景肩膀虚化、背景人物清晰入焦，镜头保持轻微手持感，"
            "强化压迫氛围而不显浮夸。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "over-the-shoulder shot, foreground shoulder softly out of focus, "
            "background character sharp and in focus, subtle handheld sway, "
            "tense confrontation blocking"
        ),
    ),
    CatalogSkill(
        key="lens-handheld-tracking",
        title="手持跟拍·追逐节奏",
        description=(
            "贴身跟随角色行走或奔跑的第一视角式手持运镜，画面带轻微晃动与呼吸感，"
            "适合冲突升级或逃跑段落。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "handheld tracking shot following the character at shoulder height, "
            "slight camera shake, urgent walking pace, environment softly blurring "
            "at the edges of frame"
        ),
    ),
    CatalogSkill(
        key="lens-high-low-angle-power",
        title="俯拍/仰拍·权力落差",
        description=(
            "用机位高度直接讲权力关系——强者仰拍显威压、弱者俯拍显渺小，两个机位交替剪辑"
            "即可讲完一场羞辱戏的情绪落差。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "low angle shot looking up at the dominant character emphasizing power "
            "and height, intercut with a high angle looking down at the other "
            "character emphasizing vulnerability"
        ),
    ),
    CatalogSkill(
        key="lens-dolly-identity-reveal",
        title="推轨/摇臂·身份揭示",
        description=(
            "缓慢横向或纵向的机位移动，把原本被环境遮挡的关键道具或人物身份逐步带入画面，"
            "制造“原来如此”的空间悬念。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "slow dolly move gradually revealing a previously obscured object or "
            "character from behind foreground elements, smooth continuous motion, "
            "no jump cuts"
        ),
    ),
    CatalogSkill(
        key="lens-vertical-close-dialogue",
        title="竖屏近景·对白特写",
        description=(
            "为竖屏短剧优化的对白构图：单人居中偏上、脸部占画面三分之一左右，适配手机端"
            "观看的信息密度。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "vertical 9:16 close-up dialogue framing, subject centered slightly "
            "above frame middle, face occupying roughly one third of frame height, "
            "clean shallow-focus background"
        ),
    ),
    CatalogSkill(
        key="lens-orbit-hero-reveal",
        title="环绕运镜·角色亮相",
        description=(
            "镜头绕主体缓慢环绕一圈、人物始终居中清晰，适合身份亮相或把一件关键道具"
            "从多角度交给观众看清楚。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "slow orbital camera move circling the subject, subject stays centered "
            "and sharp throughout, smooth continuous arc, no jump cuts"
        ),
    ),
    CatalogSkill(
        key="lens-crash-zoom-impact",
        title="急速变焦·情绪冲击",
        description=(
            "在羞辱、惊吓或反转落地的那一拍突然急推到面部，用镜头速度本身完成情绪重音，"
            "而不是靠台词解释。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "rapid crash zoom into the character's face at the impact beat, "
            "background compressing sharply, brief hold on the reaction, no whip pan"
        ),
    ),
    CatalogSkill(
        key="lens-rack-focus-secret",
        title="焦点转移·前后景反转",
        description=(
            "先让前景人物虚化、后景道具或第二人清晰，再把焦点拉回来，用一次对焦完成"
            "“原来关键在那儿”的信息移交。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "rack focus from a soft foreground figure to a sharp background object "
            "or second character, then reverse, shallow depth of field, no cut"
        ),
    ),
    CatalogSkill(
        key="lens-oner-continuous",
        title="一镜到底·连续跟拍",
        description=(
            "一条连续运动跟住角色从室内走到室外（或反过来），中途不切镜，用空间穿越"
            "本身制造紧迫感，适合逃跑、赴约或闯入。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "single continuous tracking shot following the character from an "
            "interior into an exterior with no cuts, steadicam-smooth motion, "
            "environment changing around the subject"
        ),
    ),
    CatalogSkill(
        key="lens-macro-detail-token",
        title="微距特写·信物纹理",
        description=(
            "把合同章、戒指、泪痕或锁屏这类关键信物推到物距：极浅景深只留一层纹理清晰，"
            "用细节本身完成信息移交，而不是再给一张人脸特写。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "100mm macro lens, extreme close detail on a small token or surface "
            "texture, razor-thin depth of field, slow micro push-in, no face "
            "filling the frame"
        ),
    ),
    CatalogSkill(
        key="lens-drone-ultrawide-establish",
        title="无人机超广角·开场定场",
        description=(
            "竖屏开场用 14mm 航拍把豪宅、街区或夜城的尺度一次交代完：镜头缓慢爬升，"
            "人物只占画面一角，禁止急转或俯冲。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "14mm ultra-wide drone aerial, slow rising establish over the "
            "location, deep focus, subject small in frame, no aggressive "
            "banking or dive"
        ),
    ),
    CatalogSkill(
        key="lens-hitchcock-dolly-zoom",
        title="希区柯克变焦·眩晕反转",
        description=(
            "听到真相或身份落地的那一拍：机位后撤同时镜头推近，人脸大小几乎不变，"
            "只有背景透视被拉扁或撑开，用空间扭曲代替台词解释震惊。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "Hitchcock dolly zoom, camera dollies back while zooming in, "
            "subject size stays constant, background perspective warps, one "
            "continuous move"
        ),
    ),
    CatalogSkill(
        key="lens-fpv-dive-chase",
        title="FPV俯冲·穿越追逐",
        description=(
            "逃跑或闯入的肾上腺素段落：第一人称无人机高速俯冲、侧倾穿过楼隙或巷道，"
            "目标始终压在画面里，和开场那种平稳航拍定场不是同一种镜头。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "high-velocity FPV drone dive, banking through a tight space, "
            "slight motion blur, destination held in frame, no whip pan"
        ),
    ),
    CatalogSkill(
        key="lens-dutch-angle-unease",
        title="荷兰角·失衡不安",
        description=(
            "地平线倾斜大约三十度，走廊、审讯室或胁迫场立刻失去平衡感；机位锁定或"
            "只做缓慢平移，不靠急推脸来制造紧张。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "Dutch angle, horizon canted about thirty degrees, locked or slow "
            "track, uneasy composition, no crash zoom"
        ),
    ),
    CatalogSkill(
        key="lens-pov-subjective",
        title="主观视角·代入目击",
        description=(
            "观众只看见角色看见的：偷看、目击或告白都从一双眼睛出发，画面带呼吸感晃动，"
            "中途不切回该角色的正脸。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "first-person POV through the character's eyes, handheld breathing "
            "sway, what they see stays in frame, no cutaway to their face"
        ),
    ),
    CatalogSkill(
        key="lens-whip-pan-handoff",
        title="甩镜·视线交接",
        description=(
            "从羞辱者快速甩到被羞辱者（或反转落地的那张脸）：中段水平运动模糊，"
            "落幅硬切稳住，用视线移交代替一句解释性对白。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "rapid whip pan from one subject to another, heavy motion blur "
            "mid-swing, hard settle on the second subject, no orbit"
        ),
    ),
    CatalogSkill(
        key="lens-crane-up-reveal",
        title="摇臂升起·格局揭开",
        description=(
            "从一双交握的手或一件信物缓缓升起、前推，直到整座礼堂、街区或对峙大厅"
            "进入画面，用摇臂升幅把私密细节变成格局，而不是变焦。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "crane up and forward from an intimate detail to a wide reveal of "
            "the whole space, smooth jib arc, no zoom"
        ),
    ),
    # ---------------------------------------------------------------- 景别 scene
    CatalogSkill(
        key="scene-urban-neon-alley",
        title="都市霓虹后巷",
        description=(
            "高密度都市感的背景素材：湿漉路面反射霓虹招牌光斑，适合追逐、密谈或反转前的"
            "压抑铺垫场次。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "narrow urban alley at night, wet reflective pavement, neon sign "
            "reflections in puddles, steam rising from a street vent, moody "
            "cinematic lighting"
        ),
    ),
    CatalogSkill(
        key="scene-family-confrontation-living-room",
        title="豪门客厅·家族对峙",
        description=(
            "冷调奢华的室内对峙空间：挑高落地窗、克制的家具陈设，服务于都市打脸题材里"
            "“上位者审判”式的场次。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "opulent modern living room, floor-to-ceiling windows, cold color "
            "grading, minimal but expensive furniture, dramatic side lighting"
        ),
    ),
    CatalogSkill(
        key="scene-rainy-street-showdown",
        title="雨夜巷口·摊牌戏",
        description=(
            "潮湿冷调的户外对手戏场景，雨滴与路灯逆光制造情绪张力，适合关键秘密揭露或"
            "决裂段落。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "rain-soaked street corner at night, streetlight backlighting rain "
            "streaks, cool blue-green color grade, characters facing each other "
            "under a single light source"
        ),
    ),
    CatalogSkill(
        key="scene-hospital-corridor",
        title="医院走廊·生死时刻",
        description=(
            "高对比度荧光灯走廊，长焦压缩透视强化等待与不安，适合抢救、诊断或亲情戏的"
            "高压场次。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "long hospital corridor, harsh fluorescent overhead lighting, "
            "telephoto compression, characters small in frame at the far end, "
            "sterile cold tones"
        ),
    ),
    CatalogSkill(
        key="scene-old-town-balcony-dusk",
        title="老城阳台·黄昏独白",
        description=(
            "温暖颗粒感的黄昏外景，适合角色独白、回忆或情绪转折的安静场次，与都市对峙戏"
            "形成冷暖对比。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "old town rooftop balcony at golden hour, warm film grain, soft "
            "backlight, laundry lines and rooftops in soft-focus background"
        ),
    ),
    CatalogSkill(
        key="scene-glass-tower-office",
        title="玻璃幕墙·总裁办公室",
        description=(
            "高层办公室俯瞰全景，冷色调玻璃反射，适合“总裁”“董事”身份揭示或权力宣示"
            "类场次。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "high-rise corner office, floor-to-ceiling glass wall overlooking a "
            "city skyline, cold blue tint, sharp geometric shadows from window "
            "mullions"
        ),
    ),
    CatalogSkill(
        key="scene-wedding-hall-tension",
        title="婚礼礼堂·喜中藏危",
        description=(
            "红金喜庆的礼堂被压成略冷的色温，宾客面孔模糊、通道空得过分，适合当众揭穿、"
            "悔婚或喜事里突然死寂的一场。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "ornate wedding hall at night, red-and-gold decor under a slightly "
            "cold grade, empty aisle, guests as soft-focus silhouettes, festive "
            "space that feels too quiet"
        ),
    ),
    CatalogSkill(
        key="scene-classroom-podium",
        title="教室讲台·当众打脸",
        description=(
            "日光灯教室、讲台居中、后排座位压暗，适合公开对质、成绩单/身份被当众拆穿"
            "的校园或职场培训戏。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "fluorescent classroom, podium centered in frame, back rows in "
            "shadow, harsh overhead light on the speaker, rows of empty desks "
            "receding"
        ),
    ),
    CatalogSkill(
        key="scene-underground-parking",
        title="地下停车场·密谈",
        description=(
            "低顶混凝土、一盏钠灯、远处车灯扫过，适合交易、威胁或不能被第三人听见的"
            "短对峙。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "underground parking garage, low concrete ceiling, single sodium "
            "vapor lamp, distant headlights sweeping past, long shadows between "
            "parked cars"
        ),
    ),
    CatalogSkill(
        key="scene-airport-gate-farewell",
        title="登机口·离别挽留",
        description=(
            "落地玻璃、航班信息屏冷光、旅客人流虚化，适合分手挽留、临行摊牌或错过最后"
            "一班的停顿。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "airport departure gate, floor-to-ceiling glass, cool glow from "
            "flight boards, travelers blurred in the background, a still figure "
            "in the foreground"
        ),
    ),
    # ---------------------------------------------------------------- 风格 style
    CatalogSkill(
        key="style-urban-revenge-cold-warm",
        title="都市打脸·冷暖对切",
        description=(
            "反派场景走冷色调、爽点/逆袭场景切暖色调，用色温本身完成情绪反转的视觉叙事，"
            "是都市打脸题材最常见的调色语言。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "cold-to-warm color grading transition, teal shadows shifting to warm "
            "amber highlights at the turning point, high contrast cinematic grade"
        ),
    ),
    CatalogSkill(
        key="style-sweet-romance-golden-soft",
        title="甜宠·暖金柔光",
        description=(
            "高光溢出的柔焦暖调，皮肤质感细腻但不失真，适合甜宠、追妻题材的浪漫日常戏。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "warm golden soft lighting, gentle highlight bloom, soft focus glow, "
            "flattering natural skin tones, romantic diffused backlight"
        ),
    ),
    CatalogSkill(
        key="style-suspense-teal-film-grain",
        title="悬疑·青冷胶片颗粒",
        description="低饱和青绿色调叠加胶片颗粒，压低整体亮度，服务悬疑/复仇题材的压抑氛围。",
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "desaturated teal-green color grade, visible film grain, low-key "
            "lighting, crushed shadows, suspenseful noir atmosphere"
        ),
    ),
    CatalogSkill(
        key="style-period-opera-sidelight",
        title="古装·戏曲式侧光",
        description=(
            "借鉴传统戏曲舞台光的强侧光与阴影分割，服务古装宫斗/权谋题材的仪式感构图。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "strong side lighting reminiscent of traditional opera stage lighting, "
            "sharp shadow division across the face, rich traditional costume "
            "texture, formal symmetrical composition"
        ),
    ),
    CatalogSkill(
        key="style-cyberpunk-rain-neon",
        title="赛博朋克·雨夜霓虹",
        description="高饱和霓虹色对比叠加雨夜湿反射，适合科幻/都市异能类短剧的视觉基调。",
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "cyberpunk color palette, saturated magenta and cyan neon, "
            "rain-slicked reflective surfaces, atmospheric haze, high contrast "
            "night lighting"
        ),
    ),
    CatalogSkill(
        key="style-cel-shaded-comic",
        title="漫剧·赛璐璐渲染",
        description=(
            "平涂色块叠加清晰轮廓线的二次元渲染风格，服务漫剧（条漫/动态漫）类内容的"
            "统一视觉语言。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "cel-shaded anime rendering, flat color blocks, clean bold outlines, "
            "simplified shading, vibrant saturated palette"
        ),
    ),
    CatalogSkill(
        key="style-15s-reversal-pacing",
        title="15秒·身份反转节奏",
        description=(
            "参照短视频黄金三秒法则设计的极短叙事节奏：前3秒冲突/羞辱，中段铺垫误会，"
            "尾段身份揭示定格，适合投流素材。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "rapid-cut short-form pacing, first three seconds establish conflict "
            "tension immediately, mid-section slow-motion humiliation beat, final "
            "freeze-frame on the reveal moment"
        ),
    ),
    CatalogSkill(
        key="style-mockumentary-handheld-grain",
        title="伪纪录·手持颗粒质感",
        description=(
            "全片手持不稳定运镜叠加高颗粒感，制造“偷拍/纪实”的真实错觉，适合悬疑或黑料"
            "揭露类题材开场。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "handheld documentary-style camera, visible film grain and slight "
            "motion blur, naturalistic uncorrected lighting, voyeuristic framing "
            "as if secretly filmed"
        ),
    ),
    CatalogSkill(
        key="style-korean-window-soft",
        title="韩剧窗光·柔焦",
        description=(
            "侧窗自然光打在脸颊高光、背景轻轻虚化，适合告白、和解或“终于说出口”的"
            "室内近景。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "soft window sidelight on the face, gentle highlight bloom, shallow "
            "focus background, warm-neutral skin tones, quiet romantic interior"
        ),
    ),
    CatalogSkill(
        key="style-hongkong-wet-neon",
        title="港风湿街·霓虹",
        description=(
            "潮湿街道、招牌红绿叠色、路灯晕开，比赛博朋克更生活、更夜市，适合都市夜戏"
            "和擦肩而过。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "wet Hong Kong side street at night, layered red and green neon from "
            "shop signs, blooming streetlights, lived-in clutter, cinematic but "
            "not sci-fi"
        ),
    ),
    CatalogSkill(
        key="style-ink-wash-guofeng",
        title="水墨国风·留白",
        description=(
            "淡墨渲染、大面积留白、衣袂与山雾同色阶，适合古装独白、诀别或把情绪交给"
            "空镜的一场。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "ink-wash Chinese painting look, large areas of negative space, "
            "muted ink tones, mist and fabric sharing the same value range, "
            "no heavy saturation"
        ),
    ),
    CatalogSkill(
        key="style-anamorphic-35mm",
        title="变形宽银幕·35mm",
        description=(
            "变形镜头的椭圆光斑与轻微水平拉伸，配合可见胶片颗粒，把一条竖屏短剧段落"
            "拍得像院线画幅被裁进手机。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "35mm anamorphic look, oval bokeh, subtle horizontal stretch, "
            "visible film grain, cinematic widescreen texture inside a vertical "
            "frame"
        ),
    ),
    # ---------------------------------------------------------------- 剧本节拍 other
    # This bucket is the one meaningfully consumed through script writing's
    # `@` reference (`script_writing.service._resolve_referenced_skills`),
    # which only reads `title`/`description` as a style hint and never folds
    # `params_json` — so unlike the three categories above, the load-bearing
    # field here is `description`, not `prompt_suffix`. Each still carries a
    # short `prompt_suffix` for the (secondary) case of applying it in the
    # video studio directly.
    CatalogSkill(
        key="beat-three-second-hook",
        title="三秒钩子·开场即冲突",
        description=(
            "短剧黄金三秒法则：开场第一句台词或第一个画面必须直接抛出冲突或悬念"
            "（羞辱、反差身份、意外死讯），不做人物介绍式铺垫；把“这个人是谁”“为什么在"
            "这里”留到冲突发生之后再补。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "open directly on the conflict already in motion, no establishing "
            "dialogue, the first line is a challenge or accusation"
        ),
    ),
    CatalogSkill(
        key="beat-identity-reversal-structure",
        title="身份反转·打脸结构",
        description=(
            "单集最小完整结构：反派基于错误信息实施羞辱→主角隐忍不辩解→关键道具/来电/"
            "证件揭示真实身份→反派瞬间态度崩塌。四拍缺一不可，铺垫要够但不能拖，揭示后"
            "立刻给反派的表情反应镜头，不给对白解释空间。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "beat structure: humiliation, silent restraint, sudden reveal via a "
            "prop or phone call, antagonist's expression collapsing in real time"
        ),
    ),
    CatalogSkill(
        key="beat-causal-episode-contract",
        title="因果节拍·单集合同",
        description=(
            "每一集开场必须兑现上一集结尾抛出的钩子（“合同”），中段推进一个新的因果链"
            "（做了什么→导致什么），结尾必须留一个新钩子而不是简单的情绪收尾；避免"
            "“这集只是过渡”的空转集。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "cause-and-effect scene chain where each action has a visible "
            "consequence before the scene cuts away"
        ),
    ),
    CatalogSkill(
        key="beat-natural-dialogue",
        title="去 AI 味·口语化对白",
        description=(
            "台词要像真人吵架/示爱一样有停顿、重复、打断和未说完的半句，避免书面语排比句"
            "和“你以为……殊不知……”这类网文腔；允许语病和口头禅，情绪比语法正确更重要。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "naturalistic broken dialogue with interruptions and unfinished "
            "sentences, no literary parallelism, colloquial speech patterns"
        ),
    ),
    CatalogSkill(
        key="beat-episode-map-hook-density",
        title="分集地图·钩子密度",
        description=(
            "长篇改编拆分集时，每一集必须在结尾埋一个具体可回收的钩子（不是“敬请期待”式"
            "的空泛悬念），且钩子要能在后续一到两集内兑现，避免堆积不还的钩子欠账。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "end each episode on a specific unresolved question the audience can "
            "name, payable within the next one to two episodes"
        ),
    ),
    CatalogSkill(
        key="beat-restrained-emotional-close",
        title="情绪留白·克制收尾",
        description=(
            "高潮过后不用煽情配乐和慢镜头堆叠情绪，改用一个安静的静态镜头或未说出口的"
            "沉默收尾，把情绪判断权交还观众，避免“过度煽情”的 AI 感尾声。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "end the emotional peak on a quiet static shot or unspoken silence "
            "rather than swelling music or a slow-motion montage"
        ),
    ),
    CatalogSkill(
        key="beat-rebirth-flashback-open",
        title="重生开场·记忆闪回",
        description=(
            "开场先给死亡或最大羞辱的残片（不超过两秒），再硬切回“一切尚未发生”的日常，"
            "让观众比角色先知道结局，而角色只带着说不清的熟悉感往前走。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "open on a two-second flash of the fatal or humiliating future, hard "
            "cut back to an ordinary morning before it happens, lingering unease "
            "without explanation"
        ),
    ),
    CatalogSkill(
        key="beat-time-travel-cut",
        title="穿越变身·时空对切",
        description=(
            "同一动作或同一句台词横跨两个时空：前半在现代/原身，后半落在古代/新身份，"
            "中间只用一次光或一次转身完成切换，不解说规则。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "match-cut the same gesture or line across two time periods, first "
            "half modern wardrobe and space, second half period setting, one "
            "light or turn bridges the jump"
        ),
    ),
    CatalogSkill(
        key="beat-reaction-payoff",
        title="反应特写·打脸兑现",
        description=(
            "身份或证据抛出之后，不给反派解释的对白，只给足够长的表情特写让态度崩塌"
            "自己完成，再切走。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "after the reveal, hold a close-up on the antagonist's collapsing "
            "expression with no explanatory dialogue, then cut away"
        ),
    ),
    CatalogSkill(
        key="beat-six-slot-prompt",
        title="六段提示词·主体到风格",
        description=(
            "写画面时按固定六段：主体是谁、在什么场景、正在做什么、镜头怎么动、光从哪来、"
            "整体什么风格。一段只写一件事，避免把互相打架的形容词堆进同一句。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "structure the shot as subject, setting, action, camera move, light "
            "direction, then overall style, one fact per slot, no conflicting "
            "adjectives"
        ),
    ),
    # ------------------------------------------------- 提示词格式 format
    # `category=FORMAT`, the one category that carries *how to write it*
    # rather than *what to shoot*. The boundary against the `lens-` / `scene-`
    # / `style-` sections above is a single test: if an entry stops making
    # sense once the subject matter changes, it is a content recipe and does
    # not belong here. 「悬疑·青冷胶片颗粒」only fits suspense; 「一镜一运镜」
    # holds for a wedding, a chase and an empty street alike.
    #
    # Sourced from `docs/video-prompt-formats.md`, which records which rules
    # eleven vendors state officially, which are community practice, and the
    # handful where vendors openly contradict each other. Two conventions
    # follow from that document and matter when adding rows:
    #
    #  * `prompt_suffix` is *appended* to the author's prompt by
    #    `fold_params_prompt`, so it has to read as a declarative constraint
    #    on the footage ("a single continuous camera move"), never as an
    #    instruction about prompt writing ("write one camera move"). The
    #    writing rule itself goes in `description`, which is also the only
    #    field script writing's `@` reference reads.
    #  * Phrase constraints positively. Runway, Luma, PixVerse and Veo all
    #    state officially that a negation in the prompt body biases the model
    #    toward the very thing being excluded, so an appended suffix says
    #    "camera stays locked" rather than "no camera shake". The `fmt-guard-`
    #    rows exist to teach that rewrite, and would undercut themselves by
    #    breaking it.
    #  * Every quota row here is scoped to *one beat*, never to the whole
    #    prompt. The vendor evidence is about how much a model can hold in one
    #    continuous stretch of description, and the house style
    #    (`copywriter.ENHANCE_SYSTEM_PROMPT`) now writes a video prompt as an
    #    ordered beat sequence up to `PROMPT_ENHANCE_MAX_LENGTH`. A row that
    #    capped the whole prompt would be stapled onto that output by
    #    `apply_matching_format_skills` and contradict it on the wire.
    CatalogSkill(
        key="fmt-frame-minimal-core",
        title="三要素最小式·主体动作场景",
        description=(
            "只写主体、动作、场景三件事就提交，别的一律不加。十一家厂商里有七家在官方"
            "文档中把这三样列为唯一必填层，其余的镜头、光影、风格、音频都是可选层。"
            "这是排查用的回退式而不是默认写法：画面反复失控时先退回这一式，确认模型"
            "至少把主体和动作拍对了，再逐项加回细节。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "one named subject, one clear action, one stated place, and that is "
            "the whole of it"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-five-slot-video",
        title="五槽视频式·加镜头与光",
        description=(
            "在三要素之上补两槽：镜头语言（景别与视角）和光影，共五槽，每槽一句。"
            "这是可灵官方文生视频公式的形状，也是把“会动”变成“像拍出来的”所需的最小"
            "增量；风格词留到确实需要时再加，不要在这一式里堆。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "subject, subject movement, setting, then one framing choice and one "
            "lighting description, one fact per clause"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-camera-first",
        title="摄影优先倒装式·先锁空间",
        description=(
            "把景别和运镜提到整段最前面，再写主体和动作，形如“中近景缓慢推进，"
            "拍一个正在……的人”。适合空间关系比人物表演更重要的镜头（定场、揭示、"
            "转场）。注意 Runway 官方自己在两处文档里对“开头是否更重要”给了相反答案，"
            "所以这一式的收益不保证，但把核心信息前置对不敏感的模型也没有损失。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "framing and camera move stated first, subject and action second, "
            "environment last"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-eleven-section",
        title="分项十一段式·逐项填格",
        description=(
            "按主体、动作、场景、机位角度、运镜、镜头与光学效果、视觉风格、时间要素、"
            "音频、电影术语、排除项十一项逐一填写，不需要的整项省略而不是留空话。"
            "这是 Veo 当前官方 prompt 解剖表的形状，官方同时明说“不必每条都用”；"
            "适合一条提示词要交付完整制作信息的场合，写完记得回头删掉空洞的项。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "subject, action, scene, camera angle, camera movement, lens and "
            "optical effects, visual style, temporal element, audio, each stated "
            "once and only if it carries information"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-prose-plus-blocks",
        title="散文加标签块式·先叙后挂",
        description=(
            "先用一段平实的自然语言把场面讲清楚，再在下方挂 Cinematography、Actions、"
            "Dialogue 三个标签块分别写摄影、动作条目和台词。Sora 2 官方模板就是这个"
            "形状，好处是散文保留上下文、标签块保留可定位可迭代的字段，改一个块不用"
            "重写整段。注意这不是 JSON——没有任何厂商官方推荐 JSON 提示词。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "a plain-language scene paragraph, then a Cinematography block, an "
            "Actions block listing distinct beats, and a Dialogue block"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-key-value-block",
        title="键值块式·分段可迭代",
        description=(
            "用 # 主体 / # 要求 这样的标题块把内容和约束分开写，内容块讲画面、"
            "要求块只放运镜与硬约束。Vidu 官方给的就是这种键值块语法，是除 Sora 2 的"
            "标签块之外唯一有厂商文档背书的结构化写法；适合同一场面反复微调运镜时用，"
            "每次只动要求块。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "content stated as a subject block, followed by a requirements block "
            "holding only the camera move and hard constraints"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-motion-block",
        title="运动独立成块式·动静分离",
        description=(
            "把“画面里有什么”和“什么在动”彻底分成两块写：静态块交代主体外观与环境陈设，"
            "运动块只列主体运动、环境运动和镜头运动三条。这对应即梦官方的空间层与时间层"
            "心智模型，也是排查“画面对了但不动”或“动得乱”时最快能定位问题的写法。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "static description of subject and environment first, then a separate "
            "motion pass listing subject motion, environmental motion and camera "
            "motion"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-constraints-tail",
        title="约束收尾式·末段挂硬规则",
        description=(
            "正文写完，固定在末尾挂一段约束：每个节拍只有一个运镜、服装与发型保持不变、"
            "光向不变、画面内不新增人物。把约束集中在一处而不是散落在各句中间，"
            "既方便复用同一段约束到整场戏，也避免约束句打断画面描述的连贯性。"
            "提示词越长这一式越值得用——细节多了之后，散在中间的约束句会被淹没。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "constraints: one camera move per beat, wardrobe and hair hold, key "
            "light direction holds, the cast in frame stays as listed"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-three-sentence",
        title="三句配额式·五十到八十词",
        description=(
            "这个配额是给一个节拍的，不是给整条提示词的：每个节拍写三句——第一句写"
            "主体、一个动作和地点，第二句写一个运镜加一个质感修饰，第三句写这一拍要"
            "保持稳定的部分——单拍五十到八十词。PixVerse 实测过单段连续描述超过八十词"
            "之后控制力开始下降，因为后段细节会与前段指令互相竞争；把长提示词切成"
            "若干个各自守住配额的节拍，既拿到了细节量，又避开了这个衰减。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each beat kept to three sentences and under eighty words: subject "
            "action and place, then one camera move with one texture modifier, "
            "then what must stay stable through that beat"
        ),
    ),
    CatalogSkill(
        key="fmt-frame-word-budget",
        title="篇幅配额式·八十到一百二十词",
        description=(
            "一个节拍写成八十到一百二十词的一段，写满就切下一个节拍，而不是让这一段"
            "继续膨胀。各家官方推荐的单段长度从五十词到七千字符跨了近三十倍，这个区间"
            "是多数模型对一段连续描述的共同舒适区。同一个描述词在这一段里只出现一次；"
            "要加内容时先切新节拍，再考虑加长本段。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each beat held to one paragraph of eighty to one hundred twenty "
            "words, each descriptor stated once inside it"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-open-mid-conflict",
        title="首帧冲突式·零帧起冲突",
        description=(
            "第 0 帧就是冲突本身：耳光已经落下、协议已经甩在桌上、门已经被踹开。"
            "不给任何交代性铺垫，“这是谁”“为什么”留到冲突之后。厂商官方对开场秒数"
            "没有任何指引，这一式来自竖屏短剧的运营经验，但它同时满足了六家官方共同"
            "认可的“一个片段一个连续动作”。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "opens on the conflict already in motion in the very first frame"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-one-line-identity",
        title="一句话身份反转式·台词带信息",
        description=(
            "开场那一句台词同时交代三件事：说话人是谁、两人什么关系、关系刚刚发生了"
            "什么反转。十二个词以内。写法上不要用旁白或字幕补充，让信息全部由这一句"
            "和听者的反应镜头承担。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "a single spoken line under twelve words carrying who they are, how "
            "they are related and what just changed, answered only by the "
            "listener's reaction"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-object-ecu",
        title="悬念物件特写式·先给物再给人",
        description=(
            "开场先给一个高信息量物件的大特写——化验单、婚戒、监控回放、锁屏来电——"
            "人脸留到第二镜。物件比人脸更容易在小屏上一眼读懂，也天然回避了首镜就要"
            "锁定角色一致性的难题。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "extreme close-up on one story-critical object filling the entire "
            "frame edge to edge"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-charge-to-camera",
        title="冲向镜头急停式·纯运动量",
        description=(
            "主体从画面深处朝镜头冲过来，在贴近镜头处急停。靠纯粹的运动量和景别急变"
            "抓住划走前的那一瞬，不依赖台词也不依赖观众理解剧情。写的时候一定要写清"
            "急停这个收束动作，否则模型容易让主体一路冲穿画面。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "subject sprints from deep background straight toward the lens and stops "
            "abruptly close to it, framing tightening as they arrive"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-direct-address",
        title="直视镜头开口式·打破第四面墙",
        description=(
            "主体转头直视镜头，说一句十二词以内的话，然后停住。视线正对是小屏上最强的"
            "留人信号。搭配一个锁定机位使用，因为这一式的全部信息都在脸和眼睛上，"
            "任何运镜都是干扰。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "subject turns to look directly into the lens, delivers one short line, "
            "then holds still, locked-off camera"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-status-drop",
        title="极致反差落差式·一镜内跌落",
        description=(
            "同一个镜头里完成从高位到跌落的两态切换：敬酒的手僵在半空、笑容还没收回"
            "就听见那句话。关键是两态都要有可见的物理证据（手停住、笑僵住、身体后撤"
            "半步），而不是靠“表情变得复杂”这种拍不出来的描述。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "one shot carrying a status drop with physical evidence for both "
            "states, the raised gesture freezing and the smile going rigid"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-sound-first",
        title="声音先入式·先听见再看见",
        description=(
            "声音事件早于画面出现：先是玻璃碎响、刹车声或一句画外的质问，画面才跟上。"
            "在自动播放且用户可能先听见声音的竖屏场景里，这一式的抓人效率高于纯视觉"
            "冲击。必须显式写出音频，Veo 与万相官方都说明不写音频模型会自行发挥。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the sound event lands before its source appears, image catching up "
            "to the audio a beat later"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-cold-open",
        title="中断式冷开场·从中段进入",
        description=(
            "从一个动作的中段进入，不交代前情：人已经在跑、话已经说到一半、雨已经下"
            "很久了。这是预告片剪辑的冷开场手法，要求这一拍本身不需要任何上下文就成立。"
            "写法上避免用“开始”“正准备”这类起始词，Luma 官方明确点名这类时间性短语"
            "会拖慢动作。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "enters mid-action, the motion already at full speed in the first "
            "frame"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-visible-countdown",
        title="可见倒计时式·画面内计时",
        description=(
            "让紧迫感有实体：画面里有正在跳动的倒计时、逼近的车灯、快烧到底的引信、"
            "一格格掉的电量。观众不需要理解剧情就能读出“来不及了”。这比写“气氛紧张”"
            "有效得多，因为紧张不是可拍摄的对象，而计时器是。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "a visible timer, approaching light or draining indicator inside the "
            "frame carrying the urgency"
        ),
    ),
    CatalogSkill(
        key="fmt-hook-three-signal-open",
        title="首两秒三信号式·脸动作与缺口",
        description=(
            "前两秒同时给三个信号：一张脸或身体、一个运动或声音上的炸点、一句制造好奇"
            "缺口的短台词。三者缺一都会让停留率明显下降。这一式是纯运营经验，没有任何"
            "厂商官方背书，但它拆出来的三个成分恰好都是官方公式里的必填层。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "first two seconds carry a visible face, one kinetic or audio impact, "
            "and one short line that opens a question"
        ),
    ),
    CatalogSkill(
        key="fmt-action-one-beat-reaction",
        title="一动作一反应式·动完给反应",
        description=(
            "一个节拍只写一个可读的物理动作，加一个小的收束反应：推开门，然后停住；"
            "接过纸，然后手指收紧。Sora 2、Runway、可灵、PixVerse、Luma 五家官方明文"
            "都是这一条——同一时段里堆叠多个动作会导致变形与多肢体，因为模型要解算"
            "互相竞争的形变。需要一串连续动作时把它们排成节拍序列，一拍一个，而不是"
            "压进同一句。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "one readable physical action followed by one small settling reaction "
            "in each beat, the beats running in order"
        ),
    ),
    CatalogSkill(
        key="fmt-action-body-part",
        title="身体部位级式·写到手指与下颌",
        description=(
            "把动作写到具体部位：手指蜷起、下颌绷紧、肩膀塌下去、脊背绷直。不要写"
            "“他很紧张地站着”这类整体状态描述——整体状态没有形变方向，模型只能猜；"
            "部位级描述给的是明确的骨骼与肌肉目标。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "written at body-part level: fingers curling, jaw tightening, "
            "shoulders dropping"
        ),
    ),
    CatalogSkill(
        key="fmt-action-counted-beats",
        title="计数节拍式·用可数量词定时长",
        description=(
            "用可数的量词锁住动作时长：敲三下、走两步、眨一次眼、翻两页。Sora 2 官方"
            "的强弱对照就是这个逻辑——“走过房间”是弱写法，“走四步到窗前、停住、"
            "在最后一秒拉开窗帘”是强写法。数量词同时解决了动作时长和动作边界两个问题。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "action given as counted beats, such as three taps or two steps, so "
            "its length is defined by the count"
        ),
    ),
    CatalogSkill(
        key="fmt-action-relative-pacing",
        title="相对节奏副词式·不写硬秒数",
        description=(
            "节拍头上标的秒数区间是给人看的节奏参考，节拍内部的时序仍然用“随即”"
            "“短暂停顿”“话音未落”“片刻后”这类相对副词来组织，不要在句子里写"
            "“第 1.5 秒抬手”这种精确到某一刻的指令。即梦官方明说模型对精确时间"
            "支持不稳定、强行限时可能导致生成异常，Luma 更是禁止一切时间性词汇；"
            "区间是排布顺序用的，副词才是模型真正能执行的时序表达。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "timing inside each beat carried by relative pacing words such as a "
            "brief pause and then immediately, the second ranges left as headers "
            "for ordering"
        ),
    ),
    CatalogSkill(
        key="fmt-action-emotion-externalized",
        title="情绪外化式·禁用情绪形容词",
        description=(
            "提示词里不出现悲伤、愤怒、紧张这类情绪词，全部换成可见的生理信号：悲伤"
            "写成低头、肩膀微颤、手指攥紧衣角、泪在眼眶打转未落；紧张写成频繁看表、"
            "手指敲桌、眼神闪躲。七家官方都指出抽象词让模型自行解释，结果是随机的。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "emotion carried entirely by visible physical tells"
        ),
    ),
    CatalogSkill(
        key="fmt-action-speed-evidence",
        title="速度物理表征式·不写“快”",
        description=(
            "不写 fast、迅速、飞快，改写速度的可见证据：脚下扬起的尘、被甩开的衣摆、"
            "拖影、被带动的纸张。PixVerse 官方专门说明“快”是一个时间需求而不只是风格，"
            "模型会用降低画质的方式满足它。写证据则只影响画面内容。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "speed shown through its physical evidence, dust kicking up and fabric "
            "snapping back"
        ),
    ),
    CatalogSkill(
        key="fmt-action-enter-exit-frame",
        title="入画出画式·明写进出方向",
        description=(
            "主体的进出一律写成从画面某边入画、从某边出画，不要只写“他来了”“她走了”。"
            "不写方向时模型常让主体在画面里瞬移或凭空出现。这一式同时给转场留了接口——"
            "出画方向就是下一镜的入画方向。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "subject enters frame from a stated edge and exits toward a stated "
            "edge, travelling all the way across"
        ),
    ),
    CatalogSkill(
        key="fmt-action-physical-contact",
        title="受力接触式·写清接触点",
        description=(
            "涉及接触的动作要写受力点和接触细节：脚跟先着地再过渡到脚掌、手掌压在玻璃"
            "上留下印、肩膀撞开门的那一侧。抽象动词（使用、拿起、操作）会让主体在动作里"
            "漂浮，因为没有一个明确的力学锚点。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "contact written with its force point, heel landing first then weight "
            "transferring, palm pressing flat against the surface"
        ),
    ),
    CatalogSkill(
        key="fmt-action-single-active-subject",
        title="单主体独占式·其余人明写静止",
        description=(
            "一个节拍只给一个主体主动作，画面里其他人物明确写成静止或维持原姿态。"
            "不写“其他人静止”时，模型倾向于让所有人都动起来，画面立刻失控。同理，"
            "写“熙熙攘攘的街道”会强迫模型发明几十个运动元素，时序随之崩溃。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "exactly one subject in motion, everyone else in frame holding their "
            "pose"
        ),
    ),
    CatalogSkill(
        key="fmt-action-hold-tail",
        title="动作留白收尾式·末尾留静帧",
        description=(
            "动作做完，让主体保持静止半秒再结束。剪辑时这半秒静帧就是干净的切点，"
            "也让下一镜的匹配剪辑有可对齐的构图。反过来，卡在运动最剧烈处结束的片段"
            "几乎无法与任何镜头衔接。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the action completes and the subject holds still for a beat before "
            "the clip ends"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-shot-size-codes",
        title="标准景别缩写式·统一术语",
        description=(
            "景别一律用行业缩写写死：大特写、特写、中近景、中景、中远景、远景、大远景，"
            "英文对应 ECU、CU、MCU、MS、MWS、WS、EWS。消灭“近一点”“拉远些”这种相对"
            "表述——相对表述没有基准，同一句话在不同片段里会得到不同景别。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "framing named with a standard shot-size term rather than a relative "
            "instruction to move closer or further"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-overlay-safe-area",
        title="遮挡安全区式·关键信息避开边缘",
        description=(
            "脸、手和关键道具留在竖屏中央区域，四边让给平台自己的按钮、昵称条和进度条。"
            "这不是构图审美问题而是交付问题：贴边的信息在播放器里会被 UI 压掉，成片"
            "看不出问题、上架就废。与画布的静帧留白规则是两件事——那条管的是压字排版，"
            "这条管的是平台控件遮挡。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "faces, hands and key props kept inside the central vertical area, "
            "frame edges left free of essential information"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-caption-band",
        title="底部字幕留白式·预留烧字带",
        description=(
            "画面底部预留一条不放关键信息的横带，给后期烧录的字幕。竖屏短剧的字幕几乎"
            "总是烧在下方，这条带上如果有脸、手或道具细节，字幕一压就互相毁掉。留白"
            "的做法是构图上把主体上移，而不是指望模型自己让开。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "a clean horizontal band at the bottom of frame kept free for "
            "captions, subject composed above it"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-medium-close-first",
        title="中近景优先式·远景只当空镜",
        description=(
            "竖屏优先中近景与特写，远景只用于背影、侧背或无人的环境空镜。Vidu 与"
            "MiniMax 两家官方都把这一条直接绑到了竖屏短剧场景：竖屏画幅里远景的人脸"
            "只有几十像素，表演信息全部丢失。注意这不是行业共识，只有这两家写进了官方"
            "文档，但对竖屏产品是最直接可用的一条。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "medium and close framing throughout, any wide shot showing the "
            "subject from behind or as an empty environment only"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-depth-layers",
        title="三层纵深式·用前中后代替左右",
        description=(
            "竖屏没有横向余量，关系要靠纵深表达：前景一只手或一件道具、中景人脸、"
            "后景正在发生的事。三层各自清晰可辨，不要把两层挤在同一焦平面上。这一式"
            "是竖屏里同时容纳“谁在看”和“看到了什么”的标准解法。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "composed in three stacked depth layers, a foreground element, the "
            "face in midground and the event behind, each separable"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-two-shot-stagger",
        title="双人错位式·不左右并排",
        description=(
            "竖屏双人对话不要左右并排——并排会把两张脸各压到半个画幅宽，谁也看不清。"
            "改成上下错位的紧凑双人镜：一人偏下偏前、一人偏上偏后，脸不在同一水平线上。"
            "调度上让演员沿垂直线移动而非水平弧线。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "vertical two-shot with the faces staggered on different heights, one "
            "nearer and lower, one further and higher, blocking along the vertical "
            "axis"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-over-shoulder",
        title="竖屏过肩式·下方主体留头顶空间",
        description=(
            "竖屏的过肩镜要把近侧主体压在画面下方、只留肩和后脑，上方留出负空间给对面"
            "那张脸。横屏过肩的左右布局搬到竖屏会同时切掉两个人。这一式配合双人错位式"
            "使用，是竖屏对峙戏最省画幅的两个机位。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "vertical over-the-shoulder framing, near subject low in frame showing "
            "shoulder and back of head, negative space above holding the far face"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-eyes-upper-third",
        title="上三分之一眼位式·特写定眼线",
        description=(
            "特写把眼睛放在画面上三分之一线上，而不是几何中心。眼睛居中会让下半张脸"
            "和脖子占掉大量画幅，同时把眼神挤到视觉重心之外。这条来自传统人像构图，"
            "在竖屏窄画幅里效果被放大。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "close-up with the eyes placed on the upper third line"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-angle-four",
        title="角度四态式·明写机位高度",
        description=(
            "机位角度只在平视、仰拍、俯拍、荷兰角四态里选一个写死，不留空。不写角度时"
            "模型默认给平视，权力关系、压迫感、失衡感这些靠角度承载的信息就全丢了。"
            "Veo 官方另有提醒：一些高级机位角度并未正式支持，效果与稳定性可能有波动。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "camera height stated as one of eye level, low angle, high angle or "
            "dutch tilt"
        ),
    ),
    CatalogSkill(
        key="fmt-vertical-focal-length",
        title="焦段与景深式·用毫米代替“虚化”",
        description=(
            "用等效焦段和景深深浅代替“背景虚化”“有电影感”：八十五毫米配浅景深做紧特写"
            "并压缩背景，二十四到三十五毫米配深景深交代环境。焦段是可测量的，虚化程度"
            "不是。Veo 官方同样提醒镜头焦段的效果与可靠性可能有波动。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "lens stated as a focal length with a matching depth of field, such as "
            "eighty-five millimetre with shallow focus or twenty-four millimetre "
            "with deep focus"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-one-move",
        title="一镜一运镜式·只给一个运动",
        description=(
            "一个节拍只允许一个运镜动作，换运镜就换节拍。PixVerse 官方给出了失败机理："
            "运镜是空间指令，同一时段叠加多个时模型必须自行决定谁主导、何时切换，"
            "切换点上会出现可见的抖动。Sora 2、Runway、即梦三家官方也各自写了同一条。"
            "把运镜按节拍排成序列，每拍一个，是在不触发这条故障的前提下拿到多段运动的"
            "唯一写法。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "a single continuous camera move holding one direction for the whole "
            "of each beat"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-separate-sentence",
        title="运镜与动作分写式·各自成句",
        description=(
            "主体动作写一句，镜头运动另起一句，不要塞进同一个子句里。混写时模型经常把"
            "镜头的运动方向套到主体身上（或反过来），出现主体莫名后退、镜头莫名跟着"
            "抬手的错位。分句是最省事的消歧手段。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the subject's action in one sentence and the camera's move in its own "
            "separate sentence"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-term-direction-speed",
        title="术语加方向加速度式·三件齐全",
        description=(
            "运镜必须同时给出术语、方向和速度三件：不写“镜头移动”，写“缓慢向左平移”"
            "“快速推进”。七家官方都要求具体电影术语。三件缺一的后果分别是：缺术语"
            "得到随机运动，缺方向得到随机方向，缺速度得到过快的运动和随之而来的画质下降。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "camera move given as a named term with an explicit direction and an "
            "explicit speed"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-bilingual-term",
        title="中英双标式·术语加括注",
        description=(
            "中文描述里给关键运镜与景别加英文术语括注，形如“缓慢推进（slow push in）”"
            "“中近景（MCU）”。多数模型的训练语料以英文影视术语为主，中文运镜词的映射"
            "不稳定；双标既保留中文可读性，又给模型一个确定的锚点。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each camera and framing term followed by its standard English "
            "equivalent in brackets"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-framing-vs-motion",
        title="镜头语言与运镜分槽式·两件事分开填",
        description=(
            "景别与视角属于“镜头语言”，推拉摇移属于“运镜控制”，两者填在不同的槽里。"
            "可灵官方专门加注要区分这两组概念。混在一起写时最常见的故障是：写了"
            "“特写环绕”，模型给出一个绕着拍但景别一路乱变的镜头。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "framing and angle stated in one slot, camera motion in another, the "
            "framing holding steady while the move happens"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-relational-verb",
        title="关系动词衔接式·把镜头绑到主体",
        description=(
            "用关系动词把镜头运动和主体运动连起来：镜头跟随骑车的人、镜头以与奔跑者"
            "相同的速度向左平移。Runway 官方的写法就是这样。只分别写“主体在跑”和"
            "“镜头向左移”时，两者的速度关系没有约束，主体会跑出画面或被镜头甩掉。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "camera tied to the subject with a relational verb, following and "
            "matching the subject's speed rather than moving independently"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-stage-reveal",
        title="阶段揭示式·写揭示了什么",
        description=(
            "确实需要多阶段运动时，描述每个阶段揭示了什么，而不是堆叠运动动词。"
            "Runway 官方原话是：如果片段出现漂移或形变，就退回单一运动，把下一拍"
            "拆成独立片段。动词堆叠给的是运动量，阶段揭示给的是构图目标——后者模型"
            "更容易解算。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each stage of the move described by what it brings into frame rather "
            "than by stacking movement verbs"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-locked-off",
        title="锁定机位式·三脚架锁死",
        description=(
            "明确写机位锁定、三脚架固定、画面边框不动。这是时序一致性最高的选择，"
            "也是排查问题时的基线：镜头不动的情况下如果主体还在形变，问题就在动作"
            "描述而不是运镜。注意要写成正向的“保持锁定”，而不是“不要抖动”——"
            "Runway 官方给的机理是模型会盯住“抖动”这个词本身。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "locked-off tripod camera, the frame edges stay exactly where they are "
            "for the whole clip"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-handheld-micro-drift",
        title="手持微抖式·写微幅漂移",
        description=(
            "需要手持感时写“微幅漂移”“呼吸般的轻微起伏”，不要写“晃动”“摇晃”。"
            "写晃动会得到高频抖动，在竖屏小屏上直接读作画质故障而不是风格。"
            "幅度词是这一式的关键，写清是几厘米级的漂移还是肩扛级的起伏。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "subtle handheld micro-drift with a slow breathing rise and fall, "
            "amplitude staying within a few centimetres"
        ),
    ),
    CatalogSkill(
        key="fmt-camera-move-plus-texture",
        title="主运镜加质感式·唯一安全的组合",
        description=(
            "想要更丰富的镜头感时，正确的加法是一个主运镜配一个质感修饰词（浅景深、"
            "长焦压缩、轻微暗角），而不是第二个运镜。PixVerse 官方给的修法就是这个："
            "质感修饰是空间上的静态属性，不与运镜争夺同一时段的解算。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "one primary camera move plus a single static texture modifier such as "
            "shallow depth of field"
        ),
    ),
    CatalogSkill(
        key="fmt-light-named-source",
        title="命名光源式·点名光是从哪来的",
        description=(
            "点名真实存在的光源实体：钨丝台灯、招牌霓虹、手机屏幕、走廊应急灯、"
            "窗外路灯。禁止“美丽的光线”“有氛围的打光”这类描述——它们不指向任何"
            "可渲染的对象。命名光源同时确定了色温、硬柔和方向三件事。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "light attributed to a named physical source such as a tungsten desk "
            "lamp or a neon sign"
        ),
    ),
    CatalogSkill(
        key="fmt-light-key-direction",
        title="光位方向式·写主光来向",
        description=(
            "明确写主光从哪个方位来：机位左侧偏上、正后方逆光、正下方底光。不写方向时"
            "模型默认给均匀的正面光，脸是平的，立体感和情绪指向全部丢失。方向是这一式"
            "唯一必写的信息，强度和色温可以先留空。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "key light coming from a stated position relative to the camera, such "
            "as camera-left and slightly above"
        ),
    ),
    CatalogSkill(
        key="fmt-light-ratio",
        title="明暗比式·用比值量化对比",
        description=(
            "用主光与补光的比值量化对比强度：一比一是平光、二比一适度、四比一戏剧性、"
            "八比一是黑色电影和恐怖片。比值是一个可测量的数，比“对比强烈”“光线很有"
            "层次”这类形容词稳定得多，也方便同一场戏跨镜头复用同一个数。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "contrast given as a key-to-fill ratio, such as four to one, rather "
            "than as an adjective"
        ),
    ),
    CatalogSkill(
        key="fmt-light-adjective-to-parameter",
        title="形容词转光参数式·拆掉“电影感的光”",
        description=(
            "遇到“电影感的光”“高级的打光”就把它拆成四个参数：色温、方向、硬柔、"
            "明暗比。PixVerse 官方专门写过 cinematic 几乎无用——它可以指恐怖片的阴影、"
            "爱情片的金光或纪录片的写实，模型只能随机选一种。拆完再决定要不要保留"
            "那个基调词。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "lighting expressed as colour temperature, direction, hardness and "
            "contrast ratio instead of a mood adjective"
        ),
    ),
    CatalogSkill(
        key="fmt-light-high-low-key",
        title="高低调式·用行业术语定基调",
        description=(
            "整体亮度基调用高调、低调这组行业术语写死：高调是明亮均匀、阴影浅；"
            "低调是深阴影、高对比、大面积压暗。不要写“亮一点”“暗一些”——相对指令"
            "没有基准，同一句在不同片段里得到的结果不可复现。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "overall exposure stated as high-key or low-key lighting rather than "
            "as a relative brightness instruction"
        ),
    ),
    CatalogSkill(
        key="fmt-light-continuity-across-shots",
        title="光向跨镜一致式·整场锁同一主光",
        description=(
            "同一场戏的所有片段沿用同一个主光方向和同一个色温，逐字复用同一段光线描述。"
            "不锁的后果是剪在一起后曝光和阴影在镜头间乱跳，观众读作“不是同一时间同一"
            "地点”。这是同一场戏里最容易被忽略、又最难在后期补救的连贯性项。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the same key light direction and colour temperature as the rest of "
            "the scene, described in the same words"
        ),
    ),
    CatalogSkill(
        key="fmt-light-material-nouns",
        title="材质纹理名词式·写表面而非质感",
        description=(
            "写具体的表面材质：哑光、拉丝金属、风化木、覆着薄灰、雨后湿滑。不要写"
            "“质感很好”“高级感”——质感不是可渲染的对象，材质是。材质名词同时决定了"
            "反射特性，比单独描述打光更省字。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "surfaces named by material, such as matte, brushed metal, weathered "
            "wood or dust-covered, in place of quality adjectives"
        ),
    ),
    CatalogSkill(
        key="fmt-light-time-of-day-anchor",
        title="时段锚定式·用具体时段定光",
        description=(
            "用具体时段锚定整体光线：黄金时段的低角度暖光、正午的顶光硬阴影、"
            "蓝调时刻的冷调余光、深夜只有人工光源。时段是一个完整的光线预设，"
            "一个词同时给出方向、色温和对比，比逐项描述更不容易自相矛盾。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "overall light anchored to a named time of day such as golden hour, "
            "harsh midday overhead sun or blue hour"
        ),
    ),
    CatalogSkill(
        key="fmt-audio-explicit-declaration",
        title="显式音频声明式·不写就会被自动加",
        description=(
            "音频必须单独成句显式描述。万相官方说得最直白：提示词不描述台词时模型会"
            "自由发挥添加台词，不描述背景音乐时模型会自行发挥。Veo 官方也要求用独立"
            "句子描述音频。所以“没写音频”不等于“静音”，而等于“交给模型随机决定”。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "audio described in its own dedicated sentence rather than left "
            "unstated"
        ),
    ),
    CatalogSkill(
        key="fmt-audio-three-layers",
        title="三层音频式·对白环境音与音效",
        description=(
            "音频分三层分别写：对白、环境底噪、点状音效。六家官方都是这个分层。"
            "混在一句里写时模型难以判断哪一层该压在下面，常见故障是环境音盖掉对白，"
            "或者音效被当成背景音乐处理。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "audio split into dialogue, an ambient bed and specific sound effects, "
            "each named separately"
        ),
    ),
    CatalogSkill(
        key="fmt-audio-line-budget",
        title="台词长度配额式·按秒折字数",
        description=(
            "台词长度按时长折算：中文一秒大约三到四个字，英文八秒片段不超过十二词。"
            "超出配额的后果不是台词被截断，而是模型加快语速或压缩口型，两者都会让"
            "画面看起来像配音没对上。一个四秒片段最多容纳一到两轮短对白。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "spoken lines kept within the clip's length at roughly three or four "
            "characters per second, at most two short exchanges"
        ),
    ),
    CatalogSkill(
        key="fmt-audio-dialogue-block",
        title="独立对白块式·台词与画面分离",
        description=(
            "台词放在画面描述下方的独立块里，与画面描述明确分离。Sora 2 官方模板就是"
            "这个形状。混写时模型容易把台词内容当成画面描述的一部分去渲染——写“他说"
            "‘外面下雨了’”，结果画面里真的下起雨来。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "dialogue placed in its own block below the visual description, "
            "clearly separated from it"
        ),
    ),
    CatalogSkill(
        key="fmt-audio-speaker-label",
        title="说话人标签式·全程同一写法",
        description=(
            "每句台词前挂固定的说话人标签，同一角色从第一句到最后一句用完全相同的"
            "写法，不要在“他”“男人”“穿风衣的男人”之间换来换去。标签变了，模型可能"
            "判定这是另一个人，声音随之改变。Veo 官方的对白语法是角色描述加冒号。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each line prefixed with a consistent speaker label, the same wording "
            "for the same character throughout"
        ),
    ),
    CatalogSkill(
        key="fmt-audio-voice-six",
        title="人声六件套式·台词加五个属性",
        description=(
            "人声按六件写：台词内容、情绪、语调、语速、音色、口音。这是万相官方的"
            "人声子公式，也是最细的一家。只写台词内容时，情绪和语速由模型随机决定，"
            "同一角色在不同片段里听起来像不同的人。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each voice given its line plus emotion, intonation, pace, timbre and "
            "accent"
        ),
    ),
    CatalogSkill(
        key="fmt-audio-sfx-after-trigger",
        title="音效跟随触发式·紧跟视觉动因",
        description=(
            "音效紧跟在触发它的那句视觉描述之后，不要集中堆在段尾。位置本身就是"
            "时序信息：写“杯子落地，玻璃碎响”，模型知道声音发生在落地那一刻；"
            "把碎响挪到最后一句，声音就可能落在片段结尾。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each sound effect written immediately after the visual moment that "
            "causes it"
        ),
    ),
    CatalogSkill(
        key="fmt-audio-explicit-silence",
        title="显式静音式·主动关掉台词与配乐",
        description=(
            "需要安静的片段必须显式关闭：写明无台词、无背景音乐、只保留环境底噪。"
            "空镜、转场和情绪留白镜头尤其需要——不关的话模型会自己配一段音乐，"
            "剪进整场戏时与前后镜的声音完全接不上。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "audio limited to the room's own ambient bed, dialogue and music both "
            "silent"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-whip-direction",
        title="甩镜方向加模糊式·写方向与拖影",
        description=(
            "甩镜要显式写方向和运动模糊：向右猛甩、中段强烈的水平运动模糊、落幅硬切"
            "稳住。只写“快速甩镜”得到的是高速抖动而不是拖影，因为模型没有被告知"
            "模糊是这一式的目标而非副作用。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "camera whips in one stated direction with heavy horizontal motion "
            "blur mid-swing and settles hard at the end"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-match-pair",
        title="同向配对式·两端同方向同速",
        description=(
            "转场要成对生产：A 片段的出幅方向和 B 片段的入幅方向必须一致，速度也要"
            "一致。方向相反会被观众读成“弹回来了”，速度不一致会读成卡顿。写两条提示"
            "词时把方向和速度的措辞逐字复制，不要各自重写。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "outgoing and incoming halves sharing the same movement direction and "
            "the same speed, described in identical words"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-late-chaos",
        title="末尾崩坏容忍式·剧烈运动放最后",
        description=(
            "把剧烈运动安排在片段的最后几帧，前段保持稳定。剧烈运动处模型的画质和"
            "形体最容易崩，但那几帧最终会被下一镜盖掉或被运动模糊糊掉。反过来，"
            "开头就崩的片段完全不可用。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "stable and clean for most of the clip, the violent movement confined "
            "to the final frames"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-match-cut",
        title="匹配剪辑式·共享形状与屏幕位置",
        description=(
            "两端共享同一个形状、颜色或运动方向，并且让它出现在屏幕的同一个位置。"
            "只共享形状不共享位置的匹配剪辑读起来是跳切而不是过渡。写的时候把位置"
            "说清楚：画面中央偏上、左三分之一处。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "a shared shape or colour held at the same screen position on both "
            "sides of the cut"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-occluder-pass",
        title="穿越遮挡式·穿过前景换场",
        description=(
            "镜头推进穿过一个前景遮挡物——柱子、人的背影、门框、树干——遮挡物完全"
            "占满画面的那一瞬就是切点。这一式的好处是切点由画面自己给出，不需要"
            "两端构图匹配，是最容错的转场接口。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "camera pushes through a foreground occluder until it fills the frame "
            "completely"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-light-wipe",
        title="光效擦除式·用光扫过完成换场",
        description=(
            "让一片光扫过画面完成擦除：车灯扫过、白闪、镜头耀斑横掠、开门瞬间涌入的"
            "强光。写清光从哪边来、扫向哪边，以及是否过曝到全白。不写方向时模型倾向于"
            "给一个居中的闪光，擦除感消失。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "a band of light sweeping across frame from a stated side, briefly "
            "blowing out to white as it passes"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-first-last-frame",
        title="首尾帧过渡式·只让模型补中间",
        description=(
            "指定首帧与尾帧，提示词只负责描述中间发生的运动，不重述两端已经存在的"
            "画面内容。Luma 官方的说法是有关键帧时只描述发生变化的部分；重述静态元素"
            "会稀释运动指令，常见故障是运动量明显变小。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "only the movement between the two given frames described, each "
            "endpoint left to its own frame"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-empty-plate",
        title="纯运镜空镜式·无人环境垫片",
        description=(
            "画面里不出现任何人物，只有环境和一个缓慢运镜。这是万能垫片：接在任意"
            "两场之间都不会有连贯性问题，因为没有人物就没有一致性需要维护。Vidu 官方"
            "对环境镜头的要求也是不要包含人物。同时它是整场戏的呼吸点。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "a deserted environment empty of people, carried by one slow camera "
            "move"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-single-axis",
        title="单轴运动式·全程只沿一个轴",
        description=(
            "转场片段全程只沿一个轴运动：要么水平、要么垂直、要么纵深推进，中途不换轴。"
            "换轴的那一帧是形变和拖影最集中的地方，也正好是要与下一镜对齐的接点。"
            "需要复合方向时拆成两个片段，各自单轴。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "movement confined to a single axis for the whole clip, horizontal or "
            "vertical or straight in, holding that axis throughout"
        ),
    ),
    CatalogSkill(
        key="fmt-transition-verb-forward",
        title="转场动词前置式·写过程不写两端",
        description=(
            "把“移动的过程”本身写成句子的主干动词，而不是只描述起点和终点的画面。"
            "写“镜头快速推进，虚化溶入下一场”而不是“从房间的画面变成街道的画面”。"
            "只写两端时模型往往给一个硬切加上两段静态画面，转场感为零。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the transition written as the main verb of the sentence, the movement "
            "itself carrying the change rather than the two endpoints"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-identity-block",
        title="身份锚定段式·固定段落逐字复用",
        description=(
            "为每个主要角色写一段固定的身份描述块，包含二到三个稳定的静态特征，"
            "在这个角色出现的每一条提示词里逐字粘贴，一个字都不改。改写措辞是角色"
            "漂移最常见的人为原因——模型没有“同一个人”的概念，只有“同样的描述”。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the character's fixed identity block reused word for word, holding two "
            "or three stable static features"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-verbatim-reuse",
        title="措辞逐字复用式·同场戏共用一套词",
        description=(
            "同一场戏的场地、光线、服装、色调都复用同一段措辞，而不是每条提示词重新"
            "形容一遍。Sora 2 官方的说法是跨镜头复用同一段措辞来保持连贯。同义改写"
            "在人看来是同一件事，在模型看来是新的一组条件。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "location, lighting, wardrobe and palette carried over in exactly the "
            "same phrasing as the previous shot"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-one-ref-one-job",
        title="一图一职责式·显式绑定维度",
        description=(
            "每一张参考素材显式声明它锁的是哪个维度：这张锁服装、那张锁场景、"
            "这段视频锁运镜节奏。一图承担多个职责时模型会混用，常见故障是场景参考图"
            "里的人被当成主角。MiniMax 官方示例用的就是“某维度参考图 N”这个句式。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each reference bound to one stated dimension, one for wardrobe, one "
            "for the location, one for camera rhythm"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-ref-numbering",
        title="素材指代语法式·规范编号",
        description=(
            "用规范的编号指代素材，图与视频分别计数：图 1、图 2、视频 1。万相官方给了"
            "最细的规定，连英文写法的空格和大小写都写明了。编号混用或跳号时模型的"
            "绑定关系会错位，表现为参考图张冠李戴。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "references addressed by ordered index, images and videos counted "
            "separately, each index used consistently"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-named-label",
        title="标签定义复用式·先定义再沿用",
        description=(
            "先把参考素材定义成一个命名主体，后续全程只用这个标签指代，不再重复描述"
            "特征。多主体时分别定义，标签要唯一且稳定。要求越精准参考的素材放在越前面。"
            "这是即梦官方的主体定义句式，也是多角色同框时唯一可靠的区分手段。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each reference defined once as a named subject, then addressed only "
            "by that label for the rest of the prompt"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-name-subject-plus-motion",
        title="点名主体加动作式·参考图两件都要",
        description=(
            "有参考图时不重复外貌，但必须点名主体再写动作。可灵官方解释了只写动作的"
            "后果：模型判定输入是一幅画，于是生成画作展览式的平移镜头——这正是"
            "“照片容易生成静态视频”的原因。两件都给才既省字又有运动。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the subject named and the movement described, appearance left to the "
            "reference"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-changes-only",
        title="只写变化式·静态元素不重述",
        description=(
            "有参考图或关键帧时只描述会变化的部分，静态元素一律不提。Runway 官方的"
            "说法是高细节重述图中已有元素会导致运动量下降或结果异常。判断标准很简单："
            "这句话描述的东西在片段里会变吗，不会就删掉。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "only what changes over the clip described, everything already fixed by "
            "the reference left unmentioned"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-palette",
        title="色板锚定式·点名三到五个颜色",
        description=(
            "点名三到五个具体颜色作为整场戏的色板，跨片段复用同一组。Sora 2 官方的"
            "说法是命名三到五个颜色有助于跨镜头保持色调稳定。比“统一色调”“同一"
            "风格”这种要求有效得多，因为颜色是可枚举的，色调不是。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "palette pinned to three to five named colours, the same set as the "
            "rest of the scene"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-light-direction",
        title="光向锁定式·主光来向逐字固定",
        description=(
            "同一场戏的每一条提示词都用同一句话写主光方向（例如主光从画面左前方"
            "四十五度打来），换镜头也不改这句。光向是观众判断“还在同一个地方”的"
            "最强线索，一旦在相邻两镜之间翻面，即使人物和场景完全一致，观众也会"
            "读成两场戏。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "key light holding the same stated direction as the previous shot, "
            "described in the same words"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-wardrobe-state",
        title="服装状态锁定式·连损耗程度一起写",
        description=(
            "服装不只写款式和颜色，还要写当前的损耗状态：领口敞到第几颗扣、袖口"
            "卷起、下摆湿到膝盖、肩上那道口子。同场戏内这段描述整段复用。只锁款式"
            "不锁状态时，模型会在下一镜把衣服“修好”。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "wardrobe carried over with its current state intact, the same collar, "
            "cuffs, hem and damage as before"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-hair-state",
        title="发型状态锁定式·散乱程度也是特征",
        description=(
            "头发写清当前状态：束起还是散着、有几缕落在脸侧、湿到什么程度、被风"
            "吹向哪一侧。淋雨、打斗、奔跑之后的镜头尤其要写，否则模型倾向于回到"
            "干爽整齐的默认发型，观众会直接看出接不上。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "hair kept in the same state, the same loose strands, the same wetness, "
            "falling to the same side"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-prop-position",
        title="道具位置锁定式·东西此刻在谁手里",
        description=(
            "每个关键道具都写清此刻在哪：在谁的哪只手里、放在桌上什么位置、揣进"
            "哪个口袋。道具是短剧里承担反转的东西——一份文件、一部手机、一枚戒指"
            "——它凭空换手或消失是最容易被观众抓到的穿帮。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each story prop held in the same hand or resting in the same spot as "
            "the shot before"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-eyeline-axis",
        title="视线轴线锁定式·守住一百八十度线",
        description=(
            "两人对话的机位始终留在两人连线的同一侧：甲看画面右侧，乙就看画面左侧，"
            "整场戏保持这组朝向。越过这条线会让两个人看起来朝同一个方向说话，观众"
            "读成他俩没在对话。提示词里直接写清每个人朝向画面哪一侧。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "each speaker looking toward the stated side of frame, the camera "
            "staying on one side of the line between them"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-screen-direction",
        title="银幕方向锁定式·左出即右进",
        description=(
            "主体从上一镜的哪一侧出画，下一镜就从相反的一侧入画，追逐与赶路戏全程"
            "保持同一个行进方向。方向翻转会让观众以为人物折返了。写法上把出画边和"
            "入画边都写成明确的左右，而不是走开、进来这类没有方向的词。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the subject exiting toward one stated edge and entering the next shot "
            "from the opposite edge, travel direction held"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-handoff-frame",
        title="衔接帧锁定式·上一镜末帧即下一镜首帧",
        description=(
            "分段生成时，把上一段结束时的完整画面状态——姿势、位置、光、表情——"
            "原样写成下一段的起始状态，一个字不改。两段之间最容易断的就是这一帧："
            "模型对每一段都从一个合理的开场重新起手，除非你明确告诉它这一段是从"
            "半途接上的。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "opening on exactly the pose, position, light and expression the "
            "previous segment ended on"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-ground-wetness",
        title="地面状态锁定式·水渍与痕迹连续",
        description=(
            "雨戏、泼洒、打斗之后，地面的湿度、水洼位置、碎片与拖痕在后续镜头里"
            "保持一致并只增不减。地面占竖屏画面的下三分之一，是观众余光一直在看的"
            "区域，它自己变干是很显眼的穿帮。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "ground keeping the same wetness, the same puddles and the same debris, "
            "marks accumulating forward only"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-makeup-damage",
        title="妆面损耗锁定式·泪痕血迹只增不减",
        description=(
            "泪痕、花掉的眼妆、血迹、汗、灰尘按剧情时间只增不减，并写清位置："
            "左脸颊一道、右眉骨上方。这是情绪戏最容易穿帮的一项，因为模型的默认"
            "人脸永远是干净的。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "tear tracks, smudged makeup, blood and dust kept in the same places "
            "and only accumulating as the scene goes on"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-time-of-day",
        title="时段推进锁定式·光只朝一个方向变",
        description=(
            "一场戏内的时段只能单向推进：黄昏之后回不到正午，室内灯打开之后不会"
            "自己熄灭。每条提示词都写清当前时段与光源开关状态，而不是只写地点。"
            "忽明忽暗是长场景分段生成最常见的接不上。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "time of day stated in every shot and moving in one direction only, "
            "practicals staying on once they are lit"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-weather-grade",
        title="天气连续锁定式·雨量风力写成量级",
        description=(
            "雨、雪、风、雾写成可比较的量级——细雨还是瓢泼，树梢微动还是衣角翻飞"
            "——并在同场戏内保持，或按剧情单向变化。只写下雨时，模型每一段给的雨量"
            "都不一样，剪在一起像穿插了不同天气的素材。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "rain, wind and fog stated at the same graded intensity as the previous "
            "shot, shifting in one direction only when the story calls for it"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-body-carryover",
        title="体位承接式·接着上一拍的姿势起手",
        description=(
            "每一段的第一句先写主体此刻的身体状态：站着还是坐着、面朝哪、手撑在哪、"
            "重心在哪只脚，承接上一拍的结束姿势。不写时模型会把人物重新摆成一个"
            "中性站姿，观众看到的是一次生硬的瞬移。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "opening with the subject already in the posture the previous beat "
            "ended in, the same stance, facing and weight"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-injury-progression",
        title="伤情推进锁定式·伤只会更重",
        description=(
            "伤口、淤青、绷带、跛行在剧情时间里只会加重或被当场处理，写清在身体的"
            "哪一侧。观众对上一镜还在流血、下一镜完好如初极其敏感，这一条同时约束了"
            "后续镜头里这个人还做得出哪些动作。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "injuries kept on the same side of the body and carried forward, "
            "getting worse or getting treated on screen"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-crowd-density",
        title="背景人数锁定式·给一个可数的量",
        description=(
            "背景人物写成可数的量级：三两个路人、约十人围观、满座。同场戏内保持"
            "这个量级。只写人群时，模型会在相邻镜头里给出空旷与拥挤两种极端，"
            "切在一起像换了个场地。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "background populated at the same countable density as the previous "
            "shot, the same handful of people or the same full room"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-camera-height",
        title="机位高度锁定式·平视就一直平视",
        description=(
            "一场戏内机位高度保持一致：统一平视、统一略俯或统一仰拍。改变高度必须是"
            "剧情要传达权力关系变化时的一次刻意选择。高度在相邻镜头间随机跳动，会让"
            "人物的身高与气场跟着一起跳。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "camera staying at the same stated height across the scene, eye level "
            "held unless a power shift calls for a deliberate change"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-focal-length",
        title="焦段锁定式·同场戏不换镜头",
        description=(
            "同一场戏用同一个焦段区间，例如全程三十五毫米或全程八十五毫米。换焦段"
            "等于换一套透视和背景压缩关系，观众会读成换了场地。需要改变距离感时"
            "改机位距离，而不是改焦段。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the whole scene shot on the same stated focal length, distance changed "
            "by moving the camera"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-color-temperature",
        title="色温锁定式·冷暖写成一句固定描述",
        description=(
            "把整场戏的冷暖写成一句固定描述并逐字复用：偏暖的钨丝灯白平衡，或偏冷的"
            "阴天白平衡。色温比色板更容易在分段生成时漂移，因为它不属于任何一个"
            "可点名的物体，模型手上没有锚点。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the same stated white balance carried through every shot of the scene, "
            "warm tungsten or cool overcast as declared"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-audio-bed",
        title="环境声底锁定式·底噪也要连",
        description=(
            "环境声底——雨声、空调嗡鸣、远处车流、餐厅人声——在同场戏的每一段都"
            "显式写出同一组。视频模型不写音频就会自行发挥，相邻两段配上完全不同的"
            "环境声，剪在一起的断裂感比画面跳动更明显。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the same ambient bed stated in every shot of the scene, the same rain, "
            "hum or distant traffic underneath"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-distance-between",
        title="人物间距锁定式·把距离写成步数",
        description=(
            "两人之间的距离写成可比较的量：一臂之内、隔着一张桌子、三步开外，"
            "同场戏内保持，或按剧情单向靠近。间距是对峙戏的压力来源，它在镜头之间"
            "随机变化会让紧张感彻底失效。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the gap between them held at the same stated distance, an arm's length "
            "or three steps apart, closing only when the story closes it"
        ),
    ),
    CatalogSkill(
        key="fmt-lock-object-count",
        title="物件数量锁定式·可数的就写数",
        description=(
            "画面里可数的东西给出确切数量并跨镜头保持：桌上三个杯子、墙上两幅画、"
            "手里一沓文件。模型在没有数量约束时会在每一次生成里重新决定，数量漂移"
            "是观众说不出哪里怪、但就是觉得假的常见来源。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "countable objects in frame kept at the same stated number across "
            "shots, three cups on the table staying three"
        ),
    ),
    CatalogSkill(
        key="fmt-teaser-energy-dip",
        title="能量回落式·开场强再回落",
        description=(
            "预告的能量曲线不是一路走高：开场给强，然后主动回落，再逐步建高到高潮。"
            "预告剪辑的经验是全程高能等于全程不高能——没有低点，观众就没有参照来"
            "感知高点。回落段用空镜、慢速台词或一个安静的反应镜头承担。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "energy opening high, dropping to a quiet beat, then rebuilding toward "
            "the climax"
        ),
    ),
    CatalogSkill(
        key="fmt-teaser-first-act-only",
        title="不剧透素材式·只用前四成剧情",
        description=(
            "预告素材只取全片前四成左右的内容，不出现任何解决画面、不展示结局。"
            "这是预告剪辑的行业铁律。落到提示词上就是：反转的“果”可以给情绪，"
            "但不能给出可辨识的解答画面。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "footage drawn only from the setup, the outcome left off screen"
        ),
    ),
    CatalogSkill(
        key="fmt-teaser-question-line",
        title="疑问句留白式·只给问不给答",
        description=(
            "预告里的台词只给问句，不给答案：“你到底是谁”“那天晚上你在哪”。"
            "答句会关闭好奇缺口，而好奇缺口是点击的唯一来源。搭配一个不给答案的"
            "反应镜头使用——听者沉默比听者回答有效。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "spoken line is a question, the answer withheld, the listener's "
            "reaction staying opaque"
        ),
    ),
    CatalogSkill(
        key="fmt-teaser-cut-at-peak",
        title="峰值截断式·最高点直接切黑",
        description=(
            "在情绪最高点直接切黑，不等余波、不给收尾镜头。多给的那半秒会让张力"
            "泄掉，观众从“接下来怎样”变成“看完了”。这一式要求最后一个动作在片段"
            "结束前一刻仍在进行中，而不是已经完成。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "cuts to black at the emotional peak with the action still in progress"
        ),
    ),
    CatalogSkill(
        key="fmt-teaser-title-safe-band",
        title="标题安全区留白式·留纯色暗场",
        description=(
            "结尾留出一块干净的纯色暗场区域给后期压标题，不要让模型生成文字。"
            "所有模型渲染可读文字都不可靠，得到的是乱码字形；正确的做法是画面只提供"
            "承载区域，文字在后期合成。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "ends on a clean unbroken dark area large enough to carry a title "
            "added later in post"
        ),
    ),
    CatalogSkill(
        key="fmt-teaser-seamless-loop",
        title="无缝循环式·首尾构图对齐",
        description=(
            "首帧与尾帧的构图和运动方向保持一致，让片段可以无缝循环。用作封面视频时"
            "这一式几乎是必须的：循环处的跳变在自动重播的封面位上会被反复看到。"
            "实现上让运镜走一个闭合路径，或首尾都停在同一个静帧。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "first and last frame share the same composition and movement "
            "direction so the clip loops seamlessly"
        ),
    ),
    CatalogSkill(
        key="fmt-teaser-montage-ratio",
        title="快切配额式·限定快切镜头数",
        description=(
            "高能快切段限定镜头数量，每个镜头只承担一个可读信息，别指望在半秒里"
            "交代复杂动作。落到单条提示词上就是：这一片段只给一个动作的一个瞬间，"
            "构图极简、主体居中，保证在半秒内可读。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "one single readable instant with a minimal composition, centred "
            "subject, legible in half a second"
        ),
    ),
    CatalogSkill(
        key="fmt-teaser-genre-anchor",
        title="对标品类锚定式·写清对标什么",
        description=(
            "在提示词里写清对标的品类与气质，形如“对标竖屏都市复仇短剧预告，"
            "暗黑、宿命感、关系张力”。MiniMax 官方示例用的就是这个写法。它比"
            "“电影感”“高级”有效，因为品类名同时携带了构图、节奏和调色的一整套"
            "先验，而形容词只携带一个模糊的方向。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "tone anchored to a named genre reference for vertical short-drama "
            "trailers rather than to quality adjectives"
        ),
    ),
    CatalogSkill(
        key="fmt-guard-positive-phrasing",
        title="正向约束替代式·不写“不要”",
        description=(
            "提示词正文里的否定要求全部改写成正向陈述：把“不要抖动”写成“机位保持"
            "锁定”，把“手不要变形”写成“双手保持自然形态”。Runway、Luma、PixVerse、"
            "Veo 四家官方都明说正文里的否定会适得其反——连有独立负面字段的 Veo 都"
            "要求不要写 no 和 don't。机理是模型会盯住否定词后面那个名词本身。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "camera stays locked, hands keep their natural shape, facial features "
            "hold steady, lighting stays even throughout"
        ),
    ),
    CatalogSkill(
        key="fmt-guard-negative-field",
        title="独立负面框式·只填名词不填句子",
        description=(
            "模型提供独立负面字段时，那里只填要排除的名词本身，不填否定句：填“墙、"
            "画框”而不是“不要有墙”。Veo 是唯一把这条语法写进官方指南的厂商。"
            "没有独立字段的模型不要在正文里伪造 negative 前缀，那只是更多正文。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the prompt body carrying only what should appear, exclusions moved to "
            "the request's own negative field as bare nouns"
        ),
    ),
    CatalogSkill(
        key="fmt-guard-short-negative-list",
        title="精简负面词表式·五到八个为宜",
        description=(
            "负面词控制在五到八个，上限十二到十五。三十词的负面表会让画面明显僵硬、"
            "丢失运动和细节，因为大量排除项会压缩模型可用的解空间。优先排除具体的"
            "形变故障，不要排除风格。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "exclusions kept to a handful of specific artefact terms rather than a "
            "long list"
        ),
    ),
    CatalogSkill(
        key="fmt-guard-conflict-check",
        title="互斥指令自检式·提交前扫一遍",
        description=(
            "提交前扫一遍互斥组合：慢动作与快节奏、锁定机位与手持、极简构图与繁复"
            "陈设、浅景深与深焦全清、静默与配乐。同时出现时模型必须自行取舍，结果"
            "在同一条提示词的多次生成之间不可复现——这类问题最容易被误判成模型不稳定。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "one consistent choice on each axis, pacing, camera stability, "
            "composition density and depth of field all agreeing with each other"
        ),
    ),
    CatalogSkill(
        key="fmt-guard-occlusion-audit",
        title="遮挡自检式·看不见的就别写",
        description=(
            "逐个名词回问一遍：隔着这层遮挡真的看得见吗。隔着毛玻璃、雨幕、纱帘、"
            "浓雾还写清晰的五官和纹理，模型只能二选一——要么撤掉遮挡，要么让主体"
            "糊掉。看不见的细节应当降级成透过遮挡能读到的光与色。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "anything behind an occluder described only as the light and colour "
            "that reads through it, fine detail left to what is actually visible"
        ),
    ),
    CatalogSkill(
        key="fmt-guard-no-container-params",
        title="容器参数不入正文式·时长画幅走面板",
        description=(
            "时长、画幅、分辨率、角色引用是容器参数，走面板而不是写进提示词正文。"
            "Sora 2 官方明说这些不会因为正文里写“再长一点”而改变。写进正文的后果是"
            "白占篇幅并稀释真正的画面指令。（即梦与 MiniMax 的官方示例把时长写在首句"
            "当双保险，是这一条的公开例外。）"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "the prompt describes only what is in frame and how it moves, leaving "
            "length and framing ratio to the request parameters"
        ),
    ),
    CatalogSkill(
        key="fmt-guard-adjective-to-shootable",
        title="形容词换可拍参数式·拆掉大词",
        description=(
            "把电影感、高级、大片质感、8K、杰作这类词逐个换成镜头看得见的参数："
            "焦段、景深、光向、明暗比、材质、色板。五家官方都指出这类词无效或有害，"
            "但也不必一律删——保留一个基调词是可以的，前提是同时给出至少两个可测量的"
            "视觉锚点，让基调词不再承担信息。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "look expressed through measurable anchors such as focal length, depth "
            "of field, light direction and palette rather than quality words"
        ),
    ),
    CatalogSkill(
        key="fmt-guard-caption-leak",
        title="字幕泄漏防治式·画面留干净带",
        description=(
            "模型自行生成的字幕和水印会与后期烧录的字幕打架。可用的手段有三个："
            "画面内的招牌与文字保持在读不清的虚化状态、底部留一条干净带、参考素材"
            "里的多余文字先用工具去掉。这一块是全行业最不成熟的一项，只有一家厂商在"
            "官方文档里提过写法，其余各家的官方示例反而都在用否定句，效果不保证。"
        ),
        category=CreationSkillCategory.FORMAT,
        prompt_suffix=(
            "any signage in frame left softly out of focus and unreadable, the "
            "lower band kept clean for captions added in post"
        ),
    ),
    # ---------------------------------------------------------------- 戏码与情绪 drama
    # The mirror image of the 提示词格式 section above. Those rows say how a
    # sentence should be written and stay true whatever the clip is about;
    # these say how one *kind of scene* is played and cut, and mean nothing
    # outside it. That split is what makes this the one category
    # `app.agents.skill_matcher` searches: a plot description can point at
    # 「雨夜追逐」or「强撑」, it can never point at 「一镜一运镜」.
    #
    # `description` therefore carries a double duty here — it is both the
    # marketplace copy and the *only* text the matcher's candidate list and
    # the agents' reference block ever see, so every row names its situation
    # in the wording a synopsis would use before it explains the beats.
    # Sources and boundaries: `docs/video-drama-scenes.md`.
    CatalogSkill(
        key="drama-scene-hospital-standoff",
        title="病房床前对峙·压着嗓子的战争",
        description=(
            "一方躺在病床上、另一方站在床边，为遗产、隐瞒的病情或一句迟到的道歉"
            "摊牌。这场戏的张力全在“不能大声”上：监护仪在响、门外有人、病人经不起"
            "刺激。四拍——站定不坐下、压着嗓子说出最狠的一句、病人手指抓紧被单、"
            "监护仪数字跳一下把话打断。全程不要让两人同时进画面的正中。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a bedside confrontation held at a whisper, the standing figure "
            "refusing the chair, the patient's fingers tightening on the sheet, "
            "the monitor's beep cutting the line short"
        ),
    ),
    CatalogSkill(
        key="drama-scene-rooftop-negotiation",
        title="天台谈判·风声里的最后通牒",
        description=(
            "两人在天台上谈条件、逼问真相或拦下一个想跳下去的人。风、城市底噪和"
            "空旷的背景是这场戏的全部氛围来源。四拍——一人背对栏杆站着、另一人"
            "隔着五步开外停下、递出一样东西（合同、照片、手机）、对方看完之后"
            "松手让风把它吹走。距离只在最后一拍缩短。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a rooftop ultimatum in constant wind, one figure backed against the "
            "railing, the other stopping five steps short, a document or phone "
            "held out and then let go into the wind"
        ),
    ),
    CatalogSkill(
        key="drama-scene-car-argument",
        title="车内争吵·两个座位的密闭战场",
        description=(
            "副驾与主驾之间的争吵，车停着或在开。密闭空间让两人无法走开，这是它"
            "区别于其他争吵戏的地方。四拍——一人始终盯着前方挡风玻璃说话、另一人"
            "侧过身逼视、一句话之后车里彻底安静只剩雨刷或引擎声、一人解开安全带"
            "去开车门。窗外的流动光斑扫过脸是这场戏的标志性画面。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "an argument locked inside a car, the driver talking to the windshield, "
            "the passenger turned to face them, the cabin falling to wiper and "
            "engine noise, a seatbelt unclicking on the last beat"
        ),
    ),
    CatalogSkill(
        key="drama-scene-dinner-showdown",
        title="饭局摊牌·满桌人只有两个人在说话",
        description=(
            "一桌人的饭局上，两个人当着所有人的面把事挑明。其余人的反应镜头是这场戏"
            "的主要武器。四拍——有人放下筷子、说出那句让桌面安静的话、镜头扫过一圈"
            "停住的手和交换的眼神、被指名的人慢慢抬头。全场只有转盘还在自己转是"
            "最好的收尾画面。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a banquet table going silent, chopsticks set down, the room's hands "
            "frozen mid-motion in a slow pan, the named person raising their head "
            "last, the lazy susan still turning"
        ),
    ),
    CatalogSkill(
        key="drama-scene-office-humiliation",
        title="办公室羞辱·开放工位上的公开处刑",
        description=(
            "上司或同事在开放办公区当众羞辱一个人，周围隔间里的头一个个探出来又缩"
            "回去。四拍——文件被摔在桌上、一句带姓名的贬低、周围键盘声集体停住、"
            "被羞辱者把散落的纸一张张捡起来。捡纸这一拍必须给足时间，它比任何台词"
            "都更能让观众记住这场戏。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a public dressing-down across an open-plan floor, papers slapped onto "
            "the desk, the surrounding keyboards going quiet at once, the humiliated "
            "one gathering the scattered sheets one by one"
        ),
    ),
    CatalogSkill(
        key="drama-scene-doorway-refusal",
        title="门口拒之门外·一道门框的两个世界",
        description=(
            "一个人上门求见、求和或求助，被挡在门口。门框把画面切成两半，门内暖光"
            "门外冷光，这个对比就是全部主题。四拍——敲门、门开一条缝、门内的人"
            "身体挡住缝隙说完拒绝的话、门关上后门外的人还站在原地不动。最后一拍"
            "至少停三秒。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a caller turned away at a door, the frame splitting warm interior from "
            "cold exterior, the door opened only a hand's width, a body blocking the "
            "gap, the visitor still standing there after it shuts"
        ),
    ),
    CatalogSkill(
        key="drama-scene-elevator-trap",
        title="电梯同乘·躲不开的三十秒",
        description=(
            "两个刚闹翻或身份悬殊的人被迫同乘一部电梯。楼层数字是这场戏的计时器。"
            "四拍——两人一前一后进电梯站在两个角、都盯着楼层显示、其中一人开口说"
            "半句又咽回去、门开时一人快步先走。全程不给正面双人镜头，用电梯轿厢"
            "的镜面墙让两张脸出现在同一个画面里。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "two people trapped in one elevator, standing in opposite corners both "
            "watching the floor counter, one line started and swallowed, the doors "
            "opening on a quick exit, their two faces meeting only in the mirrored wall"
        ),
    ),
    CatalogSkill(
        key="drama-scene-parking-lot-block",
        title="停车场拦车·车灯下的堵截",
        description=(
            "地下停车场里有人站在车前不让走，或拦住正要上车的人。车头灯把人照成"
            "剪影，柱子和阴影提供遮挡层次。四拍——引擎发动车灯亮起、一个人影走进"
            "光束里站定、车内的人隔着挡风玻璃对视、车门被拍响。光束里的浮尘要写出来。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a car blocked in an underground garage, headlights snapping on, a "
            "silhouette stepping into the beam and holding, eyes meeting through the "
            "windshield, a palm striking the door, dust drifting in the light"
        ),
    ),
    CatalogSkill(
        key="drama-scene-courtroom-reversal",
        title="庭审反转·一份证据翻盘",
        description=(
            "法庭或听证会上，一方拿出一份原本不该存在的证据。四拍——起身、把材料"
            "递交出去、对方律师翻页时手停住、旁听席上的低声骚动。旁听席与被告席的"
            "反应镜头比宣读证据本身重要。竖屏里不要拍全景法庭，只拍手、纸、脸。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a courtroom reversal carried by hands, paper and faces, a folder handed "
            "across, opposing counsel's page-turn stopping mid-motion, a murmur "
            "running through the gallery"
        ),
    ),
    CatalogSkill(
        key="drama-scene-family-verdict",
        title="家族会议宣判·长辈席上的判决",
        description=(
            "一屋子长辈坐着，当事人站着听宣布结果：逐出家门、剥夺继承、指定联姻。"
            "座次即权力，站着的人始终比坐着的人低一头。四拍——茶盏放回桌面、长辈"
            "开口宣布、当事人身边的人先反应、当事人自己最后才动。反打时用略仰的"
            "机位拍长辈、略俯的机位拍当事人。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a family verdict delivered from seated elders to one person standing, a "
            "teacup set down before the ruling, the bystanders reacting first and the "
            "accused last, low angle on the seated and high angle on the standing"
        ),
    ),
    CatalogSkill(
        key="drama-scene-badge-reveal",
        title="证件亮明身份·一张卡片改变全场",
        description=(
            "被看轻的人掏出证件、名片、工牌或印章，全场态度瞬间崩塌。四拍——铺垫"
            "羞辱到最难堪处、手伸进口袋（这一拍要慢）、证件正面朝上推到对方眼前、"
            "对方的表情自己垮下来。最后一拍只给对方的脸，不给任何解释性台词。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a credential produced at the worst moment of the humiliation, the hand "
            "going to the pocket slowly, the card pushed face up under their eyes, "
            "the antagonist's expression collapsing with the line left unsaid"
        ),
    ),
    CatalogSkill(
        key="drama-scene-phone-call-reveal",
        title="一通电话揭身份·听筒那头的人",
        description=(
            "当事人当着所有人的面拨一个号码，接电话的人的身份让局面反转。四拍——"
            "拨号（拍手指和屏幕）、免提键按下、听筒那头传出一句所有人都认得的称呼"
            "或声音、在场者的脸依次变色。声音先到、人后到是这一式的关键。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a number dialled in front of everyone, speaker mode tapped, a voice "
            "everyone recognises coming out of the phone, faces changing one after "
            "another while the caller stays still"
        ),
    ),
    CatalogSkill(
        key="drama-scene-boardroom-entrance",
        title="会议室推门而入·迟到的那个人是老板",
        description=(
            "会议进行到一半，门被推开，进来的人是全场都没料到的身份。四拍——门把"
            "转动的特写、满桌人回头、来人径直走到主位、之前趾高气扬的那个人慢慢"
            "站起来。来人全程不看任何人，只看主位。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a boardroom door opening mid-meeting, the table turning as one, the "
            "newcomer walking straight to the head seat with eyes fixed on it "
            "alone, the loudest "
            "person in the room rising slowly"
        ),
    ),
    CatalogSkill(
        key="drama-scene-entourage-arrival",
        title="随行列队到场·门外那一排人",
        description=(
            "一排黑西装、助理团或医疗团队跟着主角同时出现，用阵仗完成身份宣告。"
            "四拍——远处走廊尽头出现一排人影、脚步声整齐逼近、为首者停在门口侧身"
            "让路、主角从队伍中间走出来。脚步声要先于画面到达。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a line of figures filling the far end of the corridor, synchronised "
            "footsteps arriving before they do, the lead stepping aside at the door, "
            "the principal emerging from the middle of the formation"
        ),
    ),
    CatalogSkill(
        key="drama-scene-signature-reveal",
        title="签字时暴露身份·笔尖下的名字",
        description=(
            "签合同、签病危通知、签离婚协议时，名字或职务栏暴露了真实身份。四拍——"
            "笔被递过来、落笔的特写、对方低头看清签名、抬头时眼神已经完全不同。"
            "签名的特写要清晰到能读出笔画，这是全场唯一的信息载体。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a signature revealing who they are, the pen handed over, an insert close "
            "enough to read the strokes, the other party's eyes going down to the "
            "page and coming back up completely changed"
        ),
    ),
    CatalogSkill(
        key="drama-scene-mask-removal",
        title="摘下遮挡·帽檐抬起的那一刻",
        description=(
            "口罩、帽子、头盔、墨镜或围巾被摘下，露出一张所有人都认识的脸。四拍——"
            "被遮挡的人一直低着头、一只手伸向遮挡物、抬头（这一拍用慢速）、对面的人"
            "后退半步。摘下之前必须先给足对方的轻蔑，落差才成立。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a covered face uncovered, the head staying down until the hand reaches "
            "the mask or brim, the lift played slow, the person opposite taking half "
            "a step back"
        ),
    ),
    CatalogSkill(
        key="drama-scene-old-photo-found",
        title="旧照片被翻出·抽屉底下的那一张",
        description=(
            "整理遗物、搬家或找东西时翻出一张照片，牵出被隐瞒多年的关系。四拍——"
            "手在抽屉或箱底摸索、照片被抽出（背面朝上）、翻面的特写、拿照片的人"
            "手开始抖。照片内容可以不给观众看全，只给一个角。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a photograph found at the bottom of a drawer, pulled out face down, "
            "turned over in an insert shot, the hand holding it beginning to shake, "
            "only a corner of the image ever shown"
        ),
    ),
    CatalogSkill(
        key="drama-scene-report-truth",
        title="报告单揭真相·一页纸的判决",
        description=(
            "亲子鉴定、诊断书、财务审计报告被当众打开。四拍——信封被递到手上、"
            "拆封的声音、目光在纸上停住不动、纸从手里滑落或被死死攥住。观众不需要"
            "看清报告内容，只需要看清这个人怎么拿这张纸。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a report opened in front of everyone, the envelope tearing audibly, the "
            "eyes locking onto one line and staying, the page either slipping from "
            "the fingers or being crushed in them"
        ),
    ),
    CatalogSkill(
        key="drama-scene-rain-farewell",
        title="雨中告别·伞外的那一个",
        description=(
            "两人在雨里分开，一人有伞一人没有，或两人都淋着。四拍——一人转身走"
            "进雨里、另一人追出两步又停住、雨水顺着头发流进领口、留下的人在原地"
            "站到浑身湿透。全程不要给远景，湿透的程度是随时间推进的连续线索。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a parting in the rain, one walking away into it, the other taking two "
            "steps and stopping, water running from hair into the collar, the one "
            "left behind standing there until soaked through"
        ),
    ),
    CatalogSkill(
        key="drama-scene-snow-farewell",
        title="雪中送别·呵出的白气",
        description=(
            "站台、村口或医院门口的雪中分别。白气、落在肩上的雪和逐渐冻红的鼻尖"
            "承担全部时间流逝的表达。四拍——一人替另一人拉紧围巾、说一句最普通的"
            "叮嘱、转身走出五步、留下的人肩上已经积了一层雪。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a farewell in falling snow, a scarf pulled tighter for the other, one "
            "ordinary parting line, five steps walked away, snow already gathered on "
            "the shoulders of the one who stayed, breath visible throughout"
        ),
    ),
    CatalogSkill(
        key="drama-scene-wedding-reversal",
        title="婚礼反转·礼堂门口的那句话",
        description=(
            "婚礼进行到誓词或交换戒指时，有人闯入、有人当众悔婚、或真相被公布。"
            "四拍——礼堂门被推开的逆光剪影、宾客整齐回头、新人手上的动作停在半空、"
            "戒指落地滚出画面。逆光剪影这一拍是这场戏的招牌画面。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a wedding interrupted, a backlit silhouette in the opened chapel "
            "doorway, the guests turning as one, the ring stopped halfway to the "
            "finger, the band hitting the floor and rolling out of frame"
        ),
    ),
    CatalogSkill(
        key="drama-scene-deathbed-goodbye",
        title="病榻诀别·松开的那只手",
        description=(
            "临终前的最后一段对话。手是这场戏唯一需要拍好的东西。四拍——两只手"
            "握在一起的特写、一句没说完的话、握力松开、监护仪的声音变成长音。"
            "脸部镜头留给活着的那一个，将死者只给手和呼吸的起伏。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a deathbed goodbye carried by hands, two hands clasped in close-up, a "
            "sentence left unfinished, the grip loosening, the monitor's tone going "
            "flat, the face shots saved for the one still living"
        ),
    ),
    CatalogSkill(
        key="drama-scene-airport-chase",
        title="机场追人·安检口前的最后一米",
        description=(
            "赶在登机前追到机场或车站，隔着安检线、闸机或车窗喊住对方。四拍——"
            "在人流中逆行奔跑、隔着栏杆或玻璃看见对方、喊出的话被广播盖住、对方"
            "回头。人流方向必须与追赶者相反，这是这场戏的全部压力来源。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a run against the flow of a terminal crowd, spotting them through a "
            "barrier or glass, the shout buried under the announcement, the other "
            "person turning their head at the last moment"
        ),
    ),
    CatalogSkill(
        key="drama-scene-midnight-kitchen",
        title="深夜厨房和解·一碗面的距离",
        description=(
            "深夜的厨房里，两个白天吵过架的人隔着一碗面或一杯水重新说话。冰箱灯、"
            "抽油烟机灯是唯一光源。四拍——一人在黑暗里坐着、另一人开灯愣住、"
            "沉默地把食物推过去、对方拿起筷子。全程台词少于三句，动作承担和解。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a late-night kitchen reconciliation lit only by the fridge or range "
            "hood, one sitting in the dark, the other freezing in the doorway, a bowl "
            "pushed across in silence, chopsticks picked up, under three lines spoken"
        ),
    ),
    CatalogSkill(
        key="drama-scene-umbrella-share",
        title="共伞·倾斜的那一边",
        description=(
            "两人共一把伞，伞明显偏向其中一人，另一人的肩膀在淋雨。这个不对称是"
            "全部的情感信息。四拍——伞被举高罩过来、并肩走的中景、湿掉的那半边"
            "肩膀特写、被照顾的人伸手把伞推回去一点。不需要任何台词。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "one umbrella tilted hard toward the other person, a walking two-shot, "
            "an insert on the soaked shoulder taking the rain, a hand reaching over "
            "to push the umbrella back, the whole exchange carried by the tilt alone"
        ),
    ),
    CatalogSkill(
        key="drama-scene-bench-confession",
        title="长椅告白·并排不对视",
        description=(
            "两人并排坐在长椅、台阶或车后座上说心里话，全程不看对方。并排构图"
            "本身就是这场戏的意义：说得出口正是因为不用对视。四拍——并排坐着的"
            "侧后方中景、一人开口时另一人低头看手、说完之后长时间沉默、其中一人"
            "偏过头看向对方的侧脸。最后一拍是全场唯一的对视机会，可以不给回应。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a confession spoken side by side facing forward, a rear three-quarter "
            "two-shot, the listener looking down at their hands, a long silence "
            "after, one head finally turning toward the other's profile"
        ),
    ),
    CatalogSkill(
        key="drama-scene-hug-from-behind",
        title="背后拥抱·看不见的那张脸",
        description=(
            "一人从背后抱住另一人，被抱的人始终背对镜头，抱人的人的脸对着镜头。"
            "观众能看见的表情和戏中人能看见的正好相反，这个错位是全部的力量来源。"
            "四拍——一人站在原地不动、身后的人走近停住、手臂环上来、被抱的人的手"
            "抬起又放下。抱人者的表情要与台词的意思相反。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "an embrace from behind, the held one facing away from camera, the "
            "holder's face turned to lens carrying an expression that contradicts "
            "the words, a hand rising and settling back down"
        ),
    ),
    CatalogSkill(
        key="drama-scene-ring-returned",
        title="退还戒指·摊开的手心",
        description=(
            "戒指、钥匙、房卡或一叠钱被退回去。物件在两只手之间的移动就是全部剧情。"
            "四拍——一只手摊开伸到对方面前、物件被放上去、收手的人的手指慢慢合拢、"
            "给出的人转身。合拢手指这一拍要给到最紧，指节发白。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a ring or key handed back, an open palm held out, the object placed on "
            "it, the fingers closing slowly until the knuckles go pale, the giver "
            "turning away"
        ),
    ),
    CatalogSkill(
        key="drama-scene-rain-chase",
        title="雨夜追逐·湿街反光里的两个人",
        description=(
            "雨夜街头的追与逃。湿路面的反光、溅起的水花和被雨模糊的路灯是这场戏"
            "的全部质感来源。四拍——一人回头看、开始跑、脚踩进水洼溅起水花的低机位"
            "特写、追赶者从同一个水洼跑过。低机位水花镜头是这一式的标志。全程保持"
            "同一个行进方向。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a chase through wet night streets, reflections on the road surface, a "
            "glance back before the run, a low-angle insert of a foot hitting a "
            "puddle, the pursuer crossing the same puddle a beat later, travel "
            "direction held throughout"
        ),
    ),
    CatalogSkill(
        key="drama-scene-stairwell-pursuit",
        title="楼梯间追逃·垂直方向的压迫",
        description=(
            "消防楼梯或老楼梯间里的追逐。垂直构图、旋转的扶手和声控灯的明灭是"
            "竖屏最有优势的场景之一。四拍——脚步声在楼梯井里回响、俯拍旋转扶手"
            "看见下面的人影、声控灯一层层亮起、追赶者在转角与人撞个正着。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a pursuit through a concrete stairwell, footsteps echoing up the shaft, "
            "a top-down shot along the spiralling rail onto the figure below, "
            "sensor lights waking floor by floor, a collision at a landing"
        ),
    ),
    CatalogSkill(
        key="drama-scene-alley-cornered",
        title="巷子被堵·退到墙根",
        description=(
            "在死胡同或狭窄巷子里被人堵住。两侧墙面的挤压感和唯一的出口光是全部"
            "空间语言。四拍——快步走进巷子、发现前方是死路、回头看见入口被人影"
            "填满、背抵上墙。背抵墙这一拍用略仰机位拍堵人的一方。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "someone cornered in a dead-end alley, walls pressing in on both sides, "
            "the only light at the mouth of it filled by silhouettes, a back going "
            "flat against brick, low angle on those blocking the way"
        ),
    ),
    CatalogSkill(
        key="drama-scene-car-tail",
        title="跟车尾随·后视镜里的那盏灯",
        description=(
            "开车时发现被跟。后视镜是这场戏的主镜头。四拍——后视镜里出现一对车灯、"
            "驾驶者的眼睛在镜子和前方之间来回、故意变道试探、后车跟着变道。全程"
            "不给后车驾驶者的脸，只给车灯。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a tail discovered in the rear-view mirror, a pair of headlights holding "
            "distance, the driver's eyes flicking between mirror and road, a test "
            "lane change matched by the car behind, the pursuer shown only as lights"
        ),
    ),
    CatalogSkill(
        key="drama-scene-crowd-escape",
        title="人群中脱身·反方向的那一个",
        description=(
            "在密集人流里甩开跟踪者或找一个人。所有人朝一个方向走，主角逆行，这个"
            "对比本身就说明了紧迫。四拍——人群整体流动的中景、主角在其中逆向移动、"
            "肩膀撞到人的主观镜头、回头时视线被人墙挡住。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "an escape through dense foot traffic, the crowd flowing one way and the "
            "subject cutting across it, shoulders knocking past in a subjective "
            "shot, the view back sealed off by a wall of people"
        ),
    ),
    CatalogSkill(
        key="drama-scene-warehouse-standoff",
        title="仓库对峙·空旷里的两拨人",
        description=(
            "废弃仓库或地下车库里两拨人隔着空地对峙。空旷、回声和顶窗漏下的光柱"
            "是全部氛围。四拍——两拨人分别从两端进入、在中间空地各自停住、为首"
            "两人往前多走三步、其中一人抬手身后的人跟着动。光柱里的浮尘要写。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "two groups facing off across an empty warehouse floor, entering from "
            "opposite ends and halting, the two leads advancing three steps further, "
            "one raised hand moving everyone behind them, dust in the roof-light shafts"
        ),
    ),
    CatalogSkill(
        key="drama-scene-last-second-grab",
        title="千钧一发拉住·手腕上的那一把",
        description=(
            "坠落、被车撞、跌下台阶的前一瞬被人一把拉住。这场戏的全部价值在那个"
            "抓握的特写。四拍——失衡的瞬间、一只手伸进画面、抓住手腕的特写（这一拍"
            "用慢速）、两人一起后退跌坐。抓握的手指要陷进皮肤里。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a fall stopped at the last instant, the moment of losing balance, a "
            "hand entering frame, a slow-motion insert of fingers closing hard "
            "around a wrist and pressing into skin, both staggering back together"
        ),
    ),
    CatalogSkill(
        key="drama-scene-forced-entry",
        title="破门而入·撞开的那一下",
        description=(
            "撞门、踹门或破窗进入。声音先行、画面后到是这一式的节奏。四拍——门内"
            "的人听见外面的动静、门板受力弯曲的特写、门锁崩开门撞到墙、门口逆光"
            "站着的人影。门撞墙的回弹要写出来。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a door forced open, the sound arriving before the image, an insert of "
            "the panel bowing under impact, the lock giving and the door slamming "
            "into the wall and rebounding, a backlit figure in the opening"
        ),
    ),
    CatalogSkill(
        key="drama-scene-street-stall-encounter",
        title="路边摊偶遇·塑料凳上的两个世界",
        description=(
            "西装革履的人和穿着朴素的人在路边摊同桌。塑料凳、一次性杯子和头顶的"
            "白炽灯泡构成这场戏的阶层对照。四拍——一人在小凳上局促地坐下、另一人"
            "熟练地招呼老板、两碗一样的东西端上来、其中一人先动筷子。摊主的背景"
            "动作要一直有。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "two social worlds sharing a street-stall table, one perched awkwardly "
            "on the plastic stool, the other calling to the owner like a regular, "
            "two identical bowls arriving, the vendor working continuously behind them"
        ),
    ),
    CatalogSkill(
        key="drama-scene-classroom-callout",
        title="课堂点名·全班回头的那一刻",
        description=(
            "老师当众点名批评或宣读成绩，全班回头看向一个人。回头这个集体动作是"
            "这场戏的核心画面。四拍——名字被念出来、全班的头依次转过来、被点名者"
            "慢慢站起来、椅子腿刮地的声音在安静的教室里格外响。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a name read out in a quiet classroom, heads turning row by row toward "
            "one desk, that student rising slowly, the chair leg scraping loud "
            "against the floor"
        ),
    ),
    CatalogSkill(
        key="drama-scene-shop-snub",
        title="店员势利拒客·橱窗里外的目光",
        description=(
            "衣着普通的顾客在高档店里被店员上下打量、婉拒或无视。目光的扫视是"
            "这场戏的武器。四拍——顾客推门进店、店员从上到下扫一眼、手伸向商品时"
            "被一句话拦住、顾客的手停在半空。店员的笑容全程不消失。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a customer sized up in a luxury shop, a glance travelling head to foot, "
            "a reaching hand stopped by one polite line and left hanging in the air, "
            "the clerk's smile holding the entire time"
        ),
    ),
    CatalogSkill(
        key="drama-scene-lost-and-found",
        title="失物归还·递回去的那只手",
        description=(
            "捡到钱包、手机、证件或孩子后归还，牵出后续的关系。四拍——物件被捡起"
            "的低角度特写、四处张望找失主、递还时两只手短暂接触、失主道谢时对方"
            "已经转身走了。转身走开这一拍要快，不给道谢完成的机会。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a lost item returned, a low-angle insert as it is picked up, a scan of "
            "the crowd for its owner, two hands brushing in the handover, the finder "
            "already walking off before the thanks are finished"
        ),
    ),
    CatalogSkill(
        key="drama-scene-transit-seat-clash",
        title="地铁让座冲突·车厢里的公审",
        description=(
            "公交或地铁上为座位起争执，周围乘客的沉默围观是压力来源。四拍——一人"
            "站在座位旁大声说话、坐着的人低头装作没听见、周围乘客默默抬头看、"
            "有人举起手机开始拍。举手机这一拍是当代版的围观。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a seat dispute in a moving carriage, one standing and speaking loudly, "
            "the seated one keeping their head down, the surrounding passengers "
            "looking up in silence, a phone raised to record it"
        ),
    ),
    CatalogSkill(
        key="drama-scene-neighbor-doorstep",
        title="邻里上门理论·楼道里的对峙",
        description=(
            "邻居敲门理论噪音、漏水、堆物。楼道的声控灯、防盗门和门内探出的半张脸"
            "是这场戏的全部道具。四拍——敲门声、门开到防盗链的长度、门内门外各说"
            "一句、门被关上后楼道灯熄灭。灯熄灭的收尾比任何台词都干净。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a neighbour dispute at a security door, a knock, the door opening to "
            "the length of its chain, one line from each side, the door shutting and "
            "the corridor sensor light going dark"
        ),
    ),
    CatalogSkill(
        key="drama-scene-market-haggle",
        title="菜市场讨价还价·一块钱的尊严",
        description=(
            "为几块钱与摊主来回争执，暴露处境。市场的嘈杂、水渍地面和塑料袋是"
            "环境语言。四拍——手指捏着零钱数、摊主摇头、把已经装好的菜放回去、"
            "转身走时摊主叫住。放回去这一拍要拍手，不拍脸。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a haggle over small change at a wet market, coins counted between "
            "fingers, the vendor shaking their head, the filled bag set back on the "
            "pile shown in a hands-only insert, the vendor calling out as they turn away"
        ),
    ),
    CatalogSkill(
        key="drama-scene-delivery-at-door",
        title="快递上门·门口那个箱子",
        description=(
            "一件没人承认寄出的包裹送到家门口。箱子本身承担全部悬念。四拍——门铃"
            "或敲门、门开时走廊已空只剩地上的箱子、蹲下看寄件人一栏、抬头看向"
            "走廊两端的空荡。寄件人一栏要给特写但可以让它是空白的。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a parcel left at the door, the corridor already empty when it opens, a "
            "crouch to read the sender field in close-up, a look up at both ends of "
            "an empty hallway"
        ),
    ),
    CatalogSkill(
        key="drama-scene-empty-house-return",
        title="回到空屋·哪里不对劲",
        description=(
            "回到家发现有人来过：鞋摆歪了、灯开着、水杯换了位置。观众和主角同时"
            "发现异常。四拍——开门后站在玄关不动、目光落在一处细节上、慢慢往里走"
            "并按下每一盏灯、推开最后一扇门。全程只有环境声，脚步声要清晰。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a return to a home someone has been in, standing still in the entryway, "
            "the eyes settling on one wrong detail, moving inward switching on every "
            "light, pushing the last door open, ambience and footsteps carrying it all"
        ),
    ),
    CatalogSkill(
        key="drama-scene-mirror-behind",
        title="镜中看见身后·先于回头的那一眼",
        description=(
            "洗手间、化妆镜或车窗的反射里出现身后的人影。观众先看见，角色后看见，"
            "这个时间差就是恐惧。四拍——对着镜子做日常动作、镜子深处出现模糊人影、"
            "角色的动作停住、猛地回头（这一拍身后可以是空的）。人影只在焦外。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a figure appearing deep in a mirror behind them, an ordinary action at "
            "the sink continuing a beat too long, the hands stopping, a sudden turn "
            "to what may be an empty room, the reflection kept out of focus"
        ),
    ),
    CatalogSkill(
        key="drama-scene-surveillance-review",
        title="回看监控·屏幕里的那一帧",
        description=(
            "在屏幕前逐帧回看监控录像，发现被遗漏的细节。屏幕的光打在脸上是唯一"
            "光源。四拍——手指在进度条上拖动、画面被暂停、身体不自觉前倾贴近屏幕、"
            "在某一帧上停住。屏幕内容可以只给观众看一部分。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "security footage scrubbed frame by frame, screen light as the only "
            "source on the face, a finger dragging the timeline, the body leaning in "
            "toward the monitor, everything stopping on one frame"
        ),
    ),
    CatalogSkill(
        key="drama-scene-locked-room-opened",
        title="打开上锁的房间·门缝里的光",
        description=(
            "打开一间一直锁着的房门。开门的过程本身要占掉一半时长。四拍——钥匙"
            "插进锁孔的特写、门被推开一条缝有光漏出、缝隙逐渐变宽、站在门口的人"
            "的脸被里面的光照亮。房间里有什么可以完全不给，只给脸上的反应。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a long-locked door being opened, an insert of the key entering, a "
            "sliver of light widening as it swings, the face in the doorway lit by "
            "whatever is inside, the room itself left off screen"
        ),
    ),
    CatalogSkill(
        key="drama-scene-followed-at-night",
        title="夜路被跟·身后的脚步",
        description=(
            "深夜独行时听见身后的脚步。脚步声的节奏变化承担全部张力。四拍——两组"
            "脚步声重叠、主角停下身后的脚步也停、加快后身后也加快、猛地回头时"
            "巷子空无一人。声音要比画面先变化。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "footsteps following on an empty night street, two sets of steps "
            "overlapping, stopping when they stop and quickening when they quicken, "
            "a turn onto an empty lane, the sound shifting before the image does"
        ),
    ),
    CatalogSkill(
        key="drama-scene-midnight-message",
        title="深夜收到消息·亮起来的那块屏",
        description=(
            "深夜手机亮起，一条消息改变一切。屏幕光是唯一光源，脸在黑暗里被自下而上"
            "照亮。四拍——黑暗中屏幕突然亮起、手伸过去拿、屏幕光打在脸上、手指悬在"
            "回复框上不动。最后一拍要停够久，让观众看清那只手在抖。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a phone lighting up in a dark room, the screen as the only source "
            "throwing light upward onto the face, a hand reaching for it, a finger "
            "hovering over the reply box and staying there long enough to see it shake"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-held-back",
        title="隐忍·全身都在用力不哭",
        description=(
            "被冤枉、被羞辱、被误解时把情绪压住不发作。隐忍的可拍证据是用力："
            "下颌绷紧、喉结上下滚动一次、指甲掐进掌心、呼吸变浅而快、眼眶红了但"
            "泪停在眼睑上不落。三拍——听见那句话时肩膀先僵、身体各处依次开始用力、"
            "最后深吸一口气把表情抹平。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "emotion held down by visible effort, jaw set, one swallow travelling "
            "the throat, nails pressed into the palm, breathing shallow and quick, "
            "eyes wet with the tears staying on the lid, ending on one deep breath "
            "smoothing the face over"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-outburst",
        title="爆发·压到尽头的那一下",
        description=(
            "长期压抑之后的一次彻底发作。爆发要有起跳点：前一秒必须是安静的。"
            "三拍——一个极小的触发（一句话、一个眼神、一只手搭上肩）、静止半秒、"
            "然后是一个不可收回的物理动作（掀桌、摔杯、揪住衣领），最后是发作者"
            "自己被自己吓到的两秒停顿。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a breaking point reached, a tiny trigger, half a second of complete "
            "stillness, then one irreversible physical action, closing on two "
            "seconds of the person startled by what they just did"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-feigned-weakness",
        title="示弱·眼泪是给别人看的",
        description=(
            "故意表现得可怜以换取同情或降低对方戒心。关键在于观众要能看出这是演的："
            "泪水掉下来的同时眼神有一瞬间是清醒的、抹眼泪时手指从指缝里看人、"
            "背对目标时表情立刻收干净。三拍——低头哽咽、抬眼确认对方的反应、"
            "转身后瞬间平静。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "distress performed for an audience, tears falling while the eyes stay "
            "clear for one frame, a glance through the fingers while wiping them "
            "away, the face going flat the instant they turn away"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-counterattack",
        title="反杀·从挨打的姿势里站直",
        description=(
            "一直被压着的人开始反击。身体姿态的翻转比台词重要：从低头到抬头、"
            "从后退到上前一步、从两手交握到双手插兜。三拍——最后一次被羞辱时"
            "身体不再退、慢慢抬起头直视、说出第一句反击时同时向前迈一步。"
            "语速要比之前慢，音量不必更大。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a posture reversal from cornered to advancing, the retreat stopping, "
            "the head lifting into direct eye contact, one step forward landing with "
            "the first line back, spoken slower than everything before it"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-blank-shock",
        title="失神·听见噩耗的那几秒",
        description=(
            "接到死讯、看到背叛现场时的空白。失神不是表情剧烈变化，恰恰是所有表情"
            "消失：眼神失焦、嘴微张、手里的东西滑落、听不见周围的声音。三拍——"
            "信息进入的瞬间脸上还残留着上一个表情、表情缓慢褪去变成空白、手里的"
            "东西掉在地上但人没有低头去看。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "every expression draining away rather than changing, the previous smile "
            "still on the face as the news lands, eyes losing focus, lips parting, an "
            "object slipping from the hand while the head stays up, ambience dropping out"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-forced-composure",
        title="强撑·体面是装出来的",
        description=(
            "在众人面前维持体面，但细节出卖了自己：端杯子的手在抖所以用两只手、"
            "笑容维持得过久、说话时中间断了半拍才接上、扶着桌沿借力。三拍——被"
            "问到痛处、笑容先出现、然后是一个借力或稳住自己的小动作。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "composure kept up while the details give it away, a cup taken in both "
            "hands because one shakes, a smile held a beat too long, a sentence "
            "resuming half a beat late, a hand steadying against the table edge"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-contempt",
        title="轻蔑·连正眼都懒得给",
        description=(
            "居高临下的看不起。轻蔑的证据是省略：不看对方而是看对方身后、回答时"
            "只用鼻音、把对方递来的东西放在桌上而不是接过手、说话时视线停在自己"
            "的指甲上。三拍——对方说完话之后有一秒的停顿、然后是一个省略动作、"
            "最后才给一个短促的回应。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "contempt shown by what is withheld, the gaze aimed past them rather "
            "than at them, an offered item set on the table instead of taken, eyes "
            "drifting to their own fingernails, a beat of silence before a clipped reply"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-panic",
        title="慌乱·手比脑子快",
        description=(
            "突发状况下的手忙脚乱。慌乱的证据是无效动作：反复摸口袋找同一样东西、"
            "拿起又放下、走两步又折回、一句话说到一半改口。三拍——先是一个错误的"
            "动作、意识到错了之后停顿半秒、然后动作更快但同样无效。呼吸声要压过台词。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "panic shown through useless motion, the same pocket patted three times, "
            "an object picked up and set down, two steps taken and reversed, a "
            "sentence changing direction halfway, breathing louder than the words"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-relief",
        title="松一口气·撑住的力气突然没了",
        description=(
            "危险解除、误会澄清、人平安归来时的脱力。关键是先有紧绷才有松弛："
            "肩膀突然落下三厘米、扶着墙或蹲下、长长地吐出一口气、笑出来的时候"
            "眼泪反而下来了。三拍——听到确认消息、全身的力气一起卸掉、然后是"
            "一个坐下或蹲下的动作。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "tension leaving all at once, shoulders dropping several centimetres, a "
            "hand going to the wall or a slow crouch, one long breath released, a "
            "laugh arriving together with the tears"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-guilt",
        title="愧疚·不敢对上的那双眼",
        description=(
            "面对被自己伤害过的人。愧疚的证据是回避与代偿：视线始终落在对方的"
            "肩膀或胸口而不是眼睛、抢着去做一些不必要的小事、话说得比平时多。"
            "三拍——对方看过来时视线先移开、然后主动伸手去接对方手里的东西、"
            "最后仍然没能说出那句道歉。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "guilt shown as avoidance and over-compensation, the gaze landing on "
            "their shoulder instead of their eyes, hands rushing to take something "
            "they were managing fine, the apology still unspoken at the end"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-jealousy",
        title="嫉妒·笑着但眼睛没笑",
        description=(
            "看着别人得到自己想要的东西。嫉妒的证据是不一致：嘴角在笑但眼周肌肉"
            "没动、鼓掌时手掌没有真正合拢、目光在对方的战利品上停得比在对方脸上"
            "更久。三拍——先给一个得体的祝贺、然后是一个停留过久的注视、最后"
            "转开时表情立刻塌下来。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a smile that stops at the mouth while the muscles around the eyes stay "
            "still, applause where the palms barely meet, the gaze resting longer on "
            "the prize than on the person, the face collapsing the moment they turn away"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-disgust",
        title="厌恶·身体先退开",
        description=(
            "对某人或某事的生理性排斥。厌恶是全身的：上半身微微后仰、鼻翼收紧、"
            "手在裤子上蹭一下、退开半步。三拍——先是一个瞬间的面部微表情、然后"
            "身体后撤、最后是一个清洁性的小动作（擦手、整理衣领）。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "revulsion carried by the whole body, the torso tilting back, nostrils "
            "tightening, half a step of retreat, closing on a cleaning gesture such "
            "as a hand wiped down the trouser leg or a collar straightened"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-resignation",
        title="认命·争到最后不争了",
        description=(
            "放弃抵抗、接受最坏的结果。认命的证据是松开：攥着的拳头一根根松开、"
            "挺直的背弯下来、原本要说的话咽回去改成一句“好”。三拍——最后一次"
            "试图争辩、对方的态度没有任何松动、然后是全身姿态的塌陷与一句极简短的"
            "应答。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "surrender shown by letting go, a fist opening finger by finger, a "
            "straight back curving, the prepared argument swapped for a single short "
            "word of agreement"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-hope-rekindled",
        title="重燃希望·眼睛先亮起来",
        description=(
            "在绝境里听到一点可能性。希望的证据是重新启动：原本垂着的头抬起、"
            "呼吸从浅变深、抓住对方的手腕追问、身体从坐着变成站起来。三拍——听到"
            "关键词时动作停住、缓慢地抬头确认自己没听错、然后是一个突然加速的动作。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "hope restarting the body, a lowered head coming up, breathing "
            "deepening, a hand catching their wrist to make them repeat it, the "
            "stillness breaking into one sudden accelerating movement"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-suspicion",
        title="起疑·话对上了但人不对",
        description=(
            "开始怀疑眼前的人在撒谎。起疑的证据是重新审视：目光从对方的脸移到手上"
            "再移回来、重复对方刚说过的一个词、语速放慢、身体保持原姿势但脚尖已经"
            "转向门口。三拍——听完之后停顿一秒、重复其中一个词、然后换一个角度"
            "再问一遍同一件事。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "doubt shown as re-examination, the gaze travelling from their face to "
            "their hands and back, one of their own words repeated aloud, speech "
            "slowing, the feet already angled toward the door"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-embarrassment",
        title="难堪·想找个地缝钻进去",
        description=(
            "当众出丑、被揭穿、被拒绝之后的窘迫。证据是缩小自己：肩膀内收、"
            "低头看地面、手去整理本来就整齐的衣服、快速找一件事做来掩饰。三拍——"
            "耳朵和颈侧先红、身体缩小、然后是一个转移注意力的多余动作。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "shame shown by shrinking, the ears and neck flushing first, shoulders "
            "drawing in, eyes on the floor, hands straightening clothes that were "
            "already straight, one busy gesture invented to cover it"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-gloating",
        title="得意·先享受一会儿再开口",
        description=(
            "占了上风时的洋洋自得。得意的证据是从容：靠回椅背、跷起腿、慢慢喝一口"
            "水再回答、说话前先笑一下。关键是拖延——让对方等，这个等待本身就是"
            "羞辱。三拍——对方问完之后停两秒、做一个悠闲的动作、然后才回答。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "the upper hand played as leisure, leaning back into the chair, one leg "
            "crossing over the other, a slow sip taken before answering, two seconds "
            "of deliberate delay making the other person wait"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-heartbreak",
        title="心碎·当场没事，走出去才塌",
        description=(
            "得知被抛弃、被背叛的瞬间。心碎最有效的写法是延迟：在对方面前维持"
            "正常，转身离开、关上门、走到楼梯间之后才崩溃。三拍——听完之后点头"
            "说一句得体的话、转身走出去（背影要稳）、门关上的瞬间背贴着门滑坐到地上。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "heartbreak delayed, a composed nod and one polite line in front of "
            "them, a steady walk out shown from behind, the collapse arriving only "
            "after the door shuts, back sliding down it to the floor"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-cold-rage",
        title="冷怒·越生气越安静",
        description=(
            "极度愤怒但完全不提高音量。冷怒的证据是过度控制：动作变得极慢且精确、"
            "把桌上的东西一件件摆正、语速均匀到不自然、全程直视对方不眨眼。三拍——"
            "听完之后长时间沉默、做一个缓慢而精确的整理动作、然后用平静的语调说出"
            "最重的一句话。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "fury expressed as over-control, movements slowing to something precise, "
            "objects on the table squared up one by one, speech level to the point of "
            "being unnatural, unblinking eye contact held throughout"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-frozen-fear",
        title="恐惧僵住·想跑但动不了",
        description=(
            "面对危险时的僵直反应。证据是想动而动不了：手指抽动但手臂不动、"
            "呼吸变得又浅又快、眼睛睁大但视线固定在一点、喉咙发不出声音。三拍——"
            "危险出现的瞬间全身定住、只有胸口在快速起伏、直到某个声音把人惊醒才"
            "突然后退。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "the freeze response, the whole body locking while the fingers twitch, "
            "breathing fast and shallow, eyes wide and fixed on one point, the "
            "spell broken by a sound and released as one sudden backward step"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-longing",
        title="思念·对着一样东西出神",
        description=(
            "想念一个不在场的人。思念的证据是与物件的互动：反复摩挲一件旧物、"
            "看着某个空位置发呆、手机相册里的照片被放大又缩小。三拍——正在做的"
            "事情停下来、目光落到那件东西上、手伸过去碰它但停在半空。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "longing attached to an object, an ordinary task stopping, the gaze "
            "settling on a worn keepsake or an empty seat, a hand reaching toward it "
            "and halting just short of contact"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-pride",
        title="骄傲·替别人骄傲的那种",
        description=(
            "看着自己在意的人成功、站起来、被认可。这种骄傲的证据是退到后面："
            "站在人群外围、看的是对方而不是舞台、鼓掌鼓得比谁都久、眼睛发红但"
            "笑着。三拍——先看向对方、然后环视四周确认别人也看见了、最后目光回到"
            "对方身上不再移开。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "pride felt on someone else's behalf, watching from the back of the "
            "crowd, eyes on the person rather than the stage, applause lasting "
            "longer than everyone else's, eyes reddening above a steady smile"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-betrayal-realized",
        title="察觉被背叛·拼上的那一块",
        description=(
            "所有线索在一瞬间对上，明白是身边的人做的。证据是回溯：目光失焦地"
            "看向空处（在回想）、然后猛地看向那个人、身体不自觉后撤半步。三拍——"
            "听到某个只有那个人知道的细节、停住、慢慢转过头去看向那个人。转头"
            "这一拍要慢到不自然。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "the moment the pieces fit, the gaze going unfocused into middle "
            "distance while they reassemble it, the head turning toward that one "
            "person unnaturally slowly, the body drifting back half a step"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-exhaustion",
        title="疲惫·连生气的力气都没有",
        description=(
            "长期消耗之后的钝感。证据是延迟与省力：对别人的话反应慢半拍、坐下"
            "时是整个人落下去而不是坐下去、揉眼睛和后颈、把要说的话简化成一个字。"
            "三拍——被叫到名字时过一秒才抬头、回应得极简短、然后是一个撑住自己的"
            "动作。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "exhaustion shown as delay and economy, a one-second lag before looking "
            "up when addressed, dropping into the chair rather than sitting down, "
            "eyes and the back of the neck rubbed, replies pared to a single word"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-softening",
        title="心软·本来要狠下心的",
        description=(
            "本打算拒绝或惩罚，看到某个细节之后改了主意。证据是动作的中断与逆转："
            "举起的手放下、已经转身又回来、说到一半的话改口。三拍——先把狠话说到"
            "一半、目光落到一个具体的细节上（对方冻红的手、破了的鞋）、然后是一个"
            "与前面完全相反的动作。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a hardening reversed mid-action, the raised hand lowering, a turn "
            "completed and then undone, the harsh line changing course when the eyes "
            "catch one specific detail such as reddened hands or broken shoes"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-resolve",
        title="下定决心·把东西收进口袋",
        description=(
            "从犹豫转为决定。决心的证据是一个收束性的动作：把文件折好放进内袋、"
            "扣上扣子、把头发扎起来、关掉手机。三拍——长时间的犹豫与静止、一个"
            "深呼吸、然后是一个干脆利落的收束动作和转身离开。转身之后不回头。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "hesitation resolving into one decisive act, a long stillness, a deep "
            "breath, then something folded away into an inside pocket or hair tied "
            "back, and a walk out that keeps going forward"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-humiliated",
        title="被羞辱·当众被剥掉体面",
        description=(
            "在众目睽睽下被贬低。证据是身体的收缩与周围的静止：被泼的水顺着头发"
            "往下滴而人不动、手悬在半空、周围人的窃笑声。三拍——羞辱落下的瞬间"
            "全场安静半秒、被羞辱者维持原姿势不动（这一拍要长）、然后才慢慢做出"
            "第一个动作（擦脸、捡东西、抬头）。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "public humiliation absorbed in stillness, half a second of total "
            "silence around them, water dripping from the hair while they hold their "
            "pose far longer than comfortable, the first small movement coming last"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-nostalgia",
        title="怀旧触动·一个气味把人带回去",
        description=(
            "某个感官细节唤起旧事：一首歌、一种味道、一件旧物。证据是短暂的抽离："
            "正在做的事停下、目光变柔、嘴角先扬起随后落下、眨眼时眼睛湿了。三拍——"
            "触发物出现（声音或画面细节）、动作停顿两秒、然后是一个若无其事的"
            "继续动作。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "a sensory trigger pulling them out of the present, the task stopping, "
            "the gaze softening, the mouth lifting and then falling, the eyes wet on "
            "the next blink, the task resumed as if none of it happened"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-dread-waiting",
        title="忐忑等待·门后面是什么",
        description=(
            "等结果、等人出来、等一句宣判。证据是无法安放的身体：走来走去、"
            "反复看时间、坐下又站起、手指在膝盖上敲。三拍——重复性的小动作持续"
            "一段时间、某个声音出现时所有动作同时停住、然后是全身朝向声音来源。"
            "手术室灯、会议室门、手机屏幕是这一式的三个经典对象。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "waiting shown as a body with nowhere to put itself, pacing, the time "
            "checked again, sitting and standing again, fingers drumming a knee, "
            "everything stopping at once when the door or the light changes"
        ),
    ),
    CatalogSkill(
        key="drama-emotion-numb-acceptance",
        title="麻木接受·反应不过来了",
        description=(
            "坏消息太多之后的钝化。与失神不同，麻木是有反应的，只是反应过于平淡："
            "点头、说“知道了”、继续手上的动作、把该签的字签了。三拍——听完消息、"
            "极短促地点一下头、然后继续做被打断的那件事。让观众自己意识到不对劲。"
        ),
        category=CreationSkillCategory.DRAMA,
        prompt_suffix=(
            "bad news met with a response too flat for it, one short nod, a quiet "
            "acknowledgement, the interrupted task simply picked back up, leaving the "
            "wrongness for the audience to notice"
        ),
    ),
    # ---------------------------------------------------------------- 图片风格 image style
    # `category=STYLE` (reused, not a new enum value) + `_IMAGE_OPERATIONS` —
    # see the comment above `_VIDEO_OPERATIONS`. Naming here tracks 2026's
    # most-repeated AI-image prompt formats (see `THIRD_PARTY_NOTICES.md`),
    # not any single site's exact wording; every `prompt_suffix` is written
    # fresh for this catalogue's flat template shape.
    CatalogSkill(
        key="image-figurine-blindbox",
        title="手办盲盒·收藏摄影",
        description=(
            "把人像或原创形象转成桌面收藏级手办：磨砂/亮面注塑质感、透明吸塑包装与"
            "亚克力展示座，配合棚拍产品光营造“真实收藏品照片”而非数字绘画的错觉，"
            "是当下最热的图片二创玩法之一。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "turn the subject into a palm-sized collectible action figure, matte "
            "or glossy vinyl toy material with visible mold seams, displayed in "
            "clear blister packaging on a transparent acrylic stand, soft studio "
            "softbox lighting, front-facing product photography, clean seamless "
            "backdrop, no logos or watermark, no extra limbs"
        ),
        aspect_ratio="4:5",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-miniature-diorama",
        title="微缩景观·桌面建筑",
        description=(
            "把真实或想象中的建筑/街景压缩成掌心大小的立体模型质感：移轴摄影般的"
            "浅景深与柔和顶光，让整座城市看起来像摆在桌上的沙盘，常用于城市、"
            "校园、地标类图片二创。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "tilt-shift miniature diorama effect, the whole building or street "
            "rendered as a palm-sized scale model, exaggerated shallow depth of "
            "field, soft overhead studio lighting, tiny scale figures and props "
            "for reference, clean tabletop backdrop, macro lens product "
            "photography look"
        ),
        aspect_ratio="4:3",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-polaroid-retro",
        title="复古拍立得·瞬间定格",
        description=(
            "在照片外圈加上宝丽来白框与轻微曝光过度、褪色颗粒，营造“随手一拍”的"
            "胶片质感，适合怀旧、纪念类图片二创。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "instant polaroid photo look, white border frame, slightly "
            "overexposed highlights, faded warm color cast, soft film grain, "
            "mild vignette, casual snapshot framing as if just pulled from the "
            "camera"
        ),
        aspect_ratio="1:1",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-old-photo-restore-color",
        title="老照片修复上色",
        description=(
            "把泛黄破损的黑白老照片修复为清晰自然的彩色影像：补全划痕折痕、还原"
            "合理肤色与服饰颜色，同时保留人物原本的年代感神态，不做过度美颜，是"
            "家庭老照片类图片二创的刚需玩法。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "restore an old damaged black-and-white photo, remove scratches "
            "creases and dust, add natural realistic skin tones and "
            "period-appropriate clothing colors, keep the original facial "
            "features and expression unaltered, gentle photographic sharpening, "
            "no over-smoothing or beautification"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-ghibli-watercolor",
        title="吉卜力手绘水彩风",
        description=(
            "把照片或场景转成宫崎骏动画质感的手绘水彩画面：柔和的色块与笔触感、"
            "明亮干净的天空与草木、角色眼神清澈有光，营造温暖治愈的动画感而非"
            "写实照片。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "hand-painted Studio-Ghibli-inspired watercolor animation style, soft "
            "painterly brushstrokes, warm gentle color palette, bright clean sky "
            "and lush foliage, expressive glossy eyes, whimsical storybook "
            "atmosphere, no photorealistic texture"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-fashion-magazine-cover",
        title="时尚杂志封面风",
        description=(
            "把人像包装成时尚大刊封面：高对比棚拍光、精致妆造质感与留白的刊头/"
            "标题区域，构图偏简洁大气，适合个人写真或角色立绘的“出片感”包装。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "high-fashion magazine cover photography, dramatic studio lighting "
            "with a strong key light, polished editorial makeup and styling, "
            "clean negative space reserved for a masthead and headline, minimal "
            "bold composition, glossy print magazine finish, no legible text "
            "rendered"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-sticker-sheet-ip",
        title="IP表情包·九宫格贴纸",
        description=(
            "把一个角色形象拆成一整版九宫格表情贴纸：同一角色在不同表情/动作间"
            "保持发型、配色和标志性道具一致，只切换情绪与小动作，贴纸边缘带白色"
            "描边与轻微投影，方便直接当聊天表情包使用。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "flat kawaii sticker sheet, nine-panel grid of the same character in "
            "nine different expressions and poses, consistent hairstyle, color "
            "palette and signature accessory across every panel, only "
            "expression and small props change, thin white die-cut outline with "
            "a soft drop shadow per sticker, clean solid background"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-id-photo",
        title="标准证件照生成",
        description=(
            "把生活照转成规范证件照：纯色背景、正面免冠、五官清晰无遮挡、光线均匀"
            "无阴影，保留本人真实相貌特征不做变形美化，满足考试、签证、工牌等"
            "场景的基本规格要求。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "standard passport-style ID photo, plain solid color background, "
            "front-facing neutral expression, no hat or accessories covering the "
            "face, even flat lighting with no harsh shadows, sharp focus on the "
            "face, realistic unaltered facial features, formal attire"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-lineart-to-real",
        title="线稿涂鸦转真实成片",
        description=(
            "把手绘线稿、简笔涂鸦或简单草图转成有质感的成片：保留原稿的构图与"
            "形态特征，补齐材质、光影与色彩细节，让一张随手画的草图“活”成一张"
            "可用的完整画面。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "convert the rough line-art sketch into a fully rendered image, "
            "preserve the original composition and silhouette exactly, add "
            "believable material texture, lighting, shading and color, fill in "
            "only what the sketch implies without inventing a different subject"
        ),
        aspect_ratio="1:1",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-ecommerce-product-shot",
        title="电商白底·产品摄影",
        description=(
            "把产品图转成电商详情页标准的白底图：干净的纯白/浅灰背景、均匀柔光去除"
            "杂乱阴影、产品居中占满画面并保留真实材质细节，直接可用于商品主图。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "clean e-commerce product photography, pure white or seamless light "
            "gray studio background, even soft diffused lighting with minimal "
            "harsh shadow, product centered and filling most of the frame, "
            "true-to-life material and color detail, no props or clutter, no "
            "watermark"
        ),
        aspect_ratio="1:1",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-architecture-render",
        title="建筑室内·效果图渲染",
        description=(
            "把手绘草图、平面图或粗模转成接近实拍质感的建筑/室内效果图：准确的"
            "空间透视与比例、自然的材质与光影层次，适合方案汇报或空间设计类图片"
            "二创。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "photorealistic architectural visualization render, accurate spatial "
            "perspective and proportion, natural daylight and soft interior "
            "lighting, realistic material textures for glass metal wood and "
            "fabric, clean professional presentation composition, no people "
            "unless specified"
        ),
        aspect_ratio="16:9",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="image-retro-propaganda-poster",
        title="复古宣传·通缉风海报",
        description=(
            "把人像或主题包装成老式宣传画/通缉令风格的海报：做旧纸张质感、留白的"
            "粗体标题区与做旧配色，戏谑与怀旧感兼具，适合整活类图片二创。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "vintage propaganda-poster style illustration, aged paper texture "
            "with subtle creases and stains, bold retro typography-safe header "
            "area left blank, muted halftone color palette, dramatic "
            "hand-painted poster lighting, no legible text rendered"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    # ------------------------------------------------- 画布构图 canvas framing
    #
    # Everything above this line that is a `lens` / `scene` recipe is scoped
    # to `_VIDEO_OPERATIONS`, because a camera *move* only means something
    # over time. The canvas builds the opposite way round: you compose a still
    # first and animate it afterwards, so a still needs its own framing,
    # staging and lighting vocabulary. Without these rows a lens card dragged
    # onto an image node would be silently skipped by `execute_skill_context`
    # — present on the canvas, absent from the request.
    CatalogSkill(
        key="frame-low-angle-wide-establish",
        title="低角度广角·定场一帧",
        description=(
            "把镜头压到接近地面再用广角向上带，让街道与楼体的纵深线条汇聚到画面上方，"
            "一帧就交代清楚这场戏发生在什么地方。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "low camera height, wide-angle lens looking slightly up, converging "
            "vertical lines carrying the eye into depth, foreground ground plane "
            "included, single establishing frame"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="frame-tight-portrait-negative-space",
        title="紧特写·单侧留白",
        description=(
            "人物压在画面一侧、视线朝向留白的那一半。竖屏里这一招最省力：不用加任何元素，"
            "空的半边自己会读成“还有事没发生”。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "tight portrait framing, subject pushed to one third, generous negative "
            "space on the side the eyes look toward, shallow depth of field, clean "
            "uncluttered background"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="frame-foreground-occlusion-layer",
        title="前景遮挡·三层纵深",
        description=(
            "前景放一层虚化的遮挡物（门框、人肩、树叶），中景放人，背景留环境。"
            "三层叠起来画面才有厚度，而不是贴在一张纸上。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "three distinct depth layers, soft out-of-focus foreground occluder "
            "framing one edge, subject sharp in the middle ground, readable "
            "environment behind, natural depth falloff"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="frame-symmetry-center-power",
        title="正中对称·气场压制",
        description=(
            "人物摆在几何正中、左右结构对称。这是最不自然也最有压迫感的构图，"
            "留给主导整场戏的那个人。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "perfectly centered subject, bilaterally symmetrical architecture "
            "around them, level horizon, frontal composition, deliberate and "
            "static, commanding presence"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="frame-over-shoulder-still",
        title="过肩静帧·对峙起手",
        description=(
            "过肩关系的静帧版本：前景肩背占据画面一角并虚化，对面的人清晰入焦。"
            "生成一对互为反打的图，后面接上对话戏就是现成的正反打。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "over-the-shoulder still, near shoulder and back of head blurred in the "
            "lower corner, facing character sharp and centered in the remaining "
            "frame, eyeline just off lens"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="frame-reflection-double-read",
        title="镜面倒影·一帧两读",
        description=(
            "借水面、玻璃或后视镜让人物同时出现两次，一实一虚。适合表里不一、"
            "或者需要暗示第二重身份的镜头。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "subject and their reflection both visible in one frame, reflective "
            "surface (wet ground, window glass or mirror), the reflection softer "
            "and slightly distorted, deliberate visual doubling"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="frame-hands-and-object",
        title="手部与信物·无脸特写",
        description=(
            "只拍手和手里的东西，脸不入画。合同、戒指、验孕棒、一把钥匙——"
            "信物类插入镜头用这条，比拍脸更让人想往下看。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "insert shot of hands holding a single significant object, face out of "
            "frame, macro-leaning focal length, tactile material detail, shallow "
            "focus on the object itself"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="frame-crowd-isolate-one",
        title="人群中的一个·焦点隔离",
        description=(
            "满画面的人，只有一个人清晰。用景深而不是构图把主角挑出来，"
            "适合“所有人都知道了只有他不知道”这类场面。"
        ),
        category=CreationSkillCategory.LENS,
        prompt_suffix=(
            "crowded frame, exactly one figure in sharp focus while everyone else "
            "falls into soft blur, isolation carried by depth of field rather than "
            "by empty space, busy but readable"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    # ------------------------------------------------- 画布布光 canvas lighting
    CatalogSkill(
        key="light-single-source-hard-key",
        title="单光源硬光·棱角分明",
        description=(
            "一盏硬光从侧上方打下来，另一半脸交给阴影。不用补光，"
            "让明暗交界线自己把人的轮廓画出来。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "single hard key light from high side, no fill, deep shadow across the "
            "far half of the face, crisp terminator line, controlled contrast, "
            "clean falloff into black"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="light-practical-motivated",
        title="实景光源·画面内发光",
        description=(
            "光必须来自画面里看得见的东西：台灯、手机屏、招牌、车灯。"
            "观众看得到光是从哪来的，整张图就不会有那种“打光棚”的假感。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "all illumination motivated by practical sources visible in frame "
            "(lamp, phone screen, signage, headlights), light direction consistent "
            "with those sources, no unexplained studio fill"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="light-backlit-silhouette-rim",
        title="逆光轮廓·身份未明",
        description=(
            "光全在人身后，正面几乎只剩一圈边缘光。人是谁先不告诉观众，"
            "留到下一个镜头再揭。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "strong backlight, subject reading as a near-silhouette with a bright "
            "rim along shoulders and hair, facial detail withheld, atmospheric haze "
            "catching the beam"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="light-window-soft-morning",
        title="窗光柔调·清晨室内",
        description=(
            "一整面窗当柔光箱，光线大面积、方向单一、衰减很慢。"
            "情绪戏和早晨醒来的镜头默认走这个。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "large soft window light as the only key, gentle directional falloff, "
            "airy interior, low contrast, faint warm cast, calm morning mood"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="light-two-tone-split",
        title="双色分割·冷暖各半",
        description=(
            "两侧分别用冷、暖两种色光，交界线正好落在人物中轴。"
            "角色正在两难之间的时候，用色温说比用台词说快。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "split lighting with a cool source on one side and a warm source on the "
            "other, the colour boundary falling along the subject's centre line, "
            "saturated but controlled, dark neutral background"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="light-overcast-flat-documentary",
        title="阴天平光·纪实质感",
        description=(
            "没有明显主光、没有硬阴影，全靠环境光。刻意不好看，"
            "换来的是“这真的发生过”的可信度。"
        ),
        category=CreationSkillCategory.STYLE,
        prompt_suffix=(
            "flat overcast ambient light, no visible key, minimal shadow, muted "
            "desaturated palette, documentary plainness, unglamorous and credible"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    # ------------------------------------------------- 画布场景 canvas staging
    CatalogSkill(
        key="stage-two-hander-distance",
        title="双人构图·距离即关系",
        description=(
            "两个人在画面里的间距就是他们的关系。要吵架就把他们推到画框两端，"
            "要和解就让轮廓开始重叠。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "two figures staged at a deliberate distance that reads as their "
            "relationship, both fully visible, body orientation telling who is "
            "advancing and who is withdrawing, uncluttered background"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="stage-threshold-doorway",
        title="门口临界·进与不进",
        description=(
            "人卡在门框里，一半在里一半在外。所有“要不要进这个房间”的戏，"
            "都可以先落成这一帧。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "figure standing exactly in a doorway, framed by the jamb, one side of "
            "the threshold lit differently from the other, unresolved forward "
            "motion, decisive moment held"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="stage-empty-chair-absence",
        title="空座位·缺席在场",
        description=(
            "该在的人不在。拍那把空椅子、那副没动过的碗筷，"
            "比拍一张哭脸更能说明发生了什么。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "a space arranged for someone who is not there — an empty chair, an "
            "untouched place setting — everything else in the room used, quiet "
            "stillness, absence as the subject"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="stage-height-difference-power",
        title="高低错位·谁在上位",
        description=(
            "一个站着一个坐着，或者一个在楼梯上一个在楼梯下。"
            "不用台词，画面高度差已经把话说完了。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "two figures at clearly different heights within the frame (standing "
            "over seated, upper stair over lower), eyelines crossing diagonally, "
            "the height gap carrying the power balance"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="stage-vertical-safe-margins",
        title="竖屏安全边·主体居中下",
        description=(
            "竖屏成片顶部会压标题、底部会压字幕和按钮。主体放在中下三分之一，"
            "上下各留一条干净的带，导出后不会被裁掉脸。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "vertical 9:16 composition, subject centred in the lower-middle third, "
            "clean uncluttered band across the top and bottom for overlays, nothing "
            "essential near any edge"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="stage-weather-as-pressure",
        title="天气即压力·外部逼迫",
        description=(
            "让雨、风、烈日参与演出：人被天气推着走，而不是站在天气前面。"
            "外部环境施压比角色自己说“我很难”管用。"
        ),
        category=CreationSkillCategory.SCENE,
        prompt_suffix=(
            "weather actively acting on the subject — rain soaking, wind pushing "
            "clothing and hair, harsh sun forcing a squint — visible atmospheric "
            "particles, the environment applying pressure rather than decorating"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    # ------------------------------------------------- 画布方法 canvas method
    CatalogSkill(
        key="method-shot-pair-reverse",
        title="正反打成对·一次两帧",
        description=(
            "对话戏一次生成两张：同一场景、同一布光、机位互为反打。"
            "在画布上并排放，接下来两条视频的连贯性就已经定下来了。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "shot-reverse-shot pair from one scene: identical location, lighting "
            "direction and colour, camera positions mirrored across the eyeline, "
            "matching focal length and framing height"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="method-keyframe-first-last",
        title="首尾关键帧·留给动起来",
        description=(
            "为同一个镜头画首帧和尾帧：构图相同，只改一件事（人物位置、光线、"
            "手里的东西）。图生视频拿到这两张，中间的运动是自然补出来的。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "a keyframe intended to be animated: stable composition with exactly "
            "one element positioned for change, room left in frame for the motion "
            "to travel into, no motion blur baked in"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="method-continuity-anchor",
        title="连戏锚点·跨镜不跳",
        description=(
            "同一场戏的每一张图都锁死这几项：服装、发型、配饰、伤口位置、"
            "时间与天气。列清楚再生成，比事后挑图省得多。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "continuity locked across the scene: same wardrobe, hair, accessories, "
            "visible injuries and time of day as the reference, consistent colour "
            "temperature, no wardrobe or grooming drift"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="method-no-text-in-frame",
        title="画面不写字·后期再压",
        description=(
            "让模型不要在画面里生成任何文字。招牌、手机屏、合同一律留空或糊掉，"
            "标题和字幕交给后期，避免生成一堆没人认识的字。"
        ),
        category=CreationSkillCategory.OTHER,
        prompt_suffix=(
            "no legible text anywhere in frame: signage, screens and documents left "
            "blank, abstracted or defocused, no watermarks, no captions, no logos"
        ),
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    # ---------------------------------------------------------------- 图片资产 image asset
    # Dual-shape rows: flat `prompt_suffix`/`aspect_ratio` for the image
    # studio `@` menu, plus `category` in `IMAGE_ASSET_SKILL_CATEGORIES` so
    # they land on the marketplace 「图片资产」tab. Layout *names* track
    # widely-used character-sheet / empty-set / title-safe-cover patterns
    # (see `THIRD_PARTY_NOTICES.md`); every suffix is original. Titles use
    # 「设定板 / 空镜 / 封面」so they never collide with the video
    # `scene-*` / `style-*` titles above under `(owner, title)` matching.
    CatalogSkill(
        key="asset-char-turnaround-sheet",
        title="三视图设定板",
        description=(
            "单张左右分栏的角色设定图：左侧全身正/侧/背面三视图，右侧面部特写、"
            "面料细节与色板，方便直接当后续分镜的身份锚点。"
        ),
        category=CreationSkillCategory.CHARACTER,
        prompt_suffix=(
            "single character-design sheet, left-to-right full-body front side "
            "and back standing views uncropped head to toe, right column face "
            "close-ups fabric details and a color palette, one character only, "
            "solid white studio background, no environment, no extra people"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-char-expression-grid",
        title="表情九宫格设定板",
        description=(
            "同一角色的 3×3 表情板：中性、喜、怒、哀、惊、思考、坚定、怀疑、"
            "失笑，五官与发型锁定，只切换情绪与口型。"
        ),
        category=CreationSkillCategory.CHARACTER,
        prompt_suffix=(
            "nine-panel expression sheet of the same character, three-by-three "
            "grid, head-and-shoulders, expressions clearly different: neutral, "
            "happy, angry, sad, surprised, thinking, determined, suspicious, "
            "amused, identical face hair and lighting, clean white background, "
            "no readable labels"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-char-wardrobe-grid",
        title="换装网格设定板",
        description=(
            "同一角色的多套服装网格：脸、发型、体型全程锁定，只换衣服与配饰，"
            "适合短剧日常/礼服/战损等造型对照。"
        ),
        category=CreationSkillCategory.CHARACTER,
        prompt_suffix=(
            "wardrobe variation grid of the same character, six standing "
            "panels, only clothing and accessories change, face hair and body "
            "proportions locked across every cell, even studio light, light "
            "gray seamless backdrop, no extra people"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-char-three-column-ref",
        title="特写正面背面三栏设定板",
        description=(
            "三栏参考图：左面部特写、中全身正面、右全身背面，同一套服装与"
            "同一人，适合导入视频生成当身份板。"
        ),
        category=CreationSkillCategory.CHARACTER,
        prompt_suffix=(
            "three-column character reference, left detailed face close-up, "
            "center full-body front, right full-body back, same character and "
            "outfit in every column, flat complementary backdrop, no extra "
            "people"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-char-palette-fabric",
        title="色板面料细节设定板",
        description=(
            "以服装材质与配色为主的细节板：大块面料特写、配饰微距，角落放一小张"
            "全身缩略，不写品牌名。"
        ),
        category=CreationSkillCategory.CHARACTER,
        prompt_suffix=(
            "costume material study plate, large fabric swatches and accessory "
            "macros from one outfit, a small full-body inset of the same "
            "character, printed color chips with no brand names or readable "
            "text, white background"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-char-identity-anchor",
        title="外貌锚点立绘设定板",
        description=(
            "一张腰部以上的身份锁定位：年龄、体型、发型、肤色、脸型、瞳色和一件"
            "标志配饰写死，后续分镜只改动作与场景。"
        ),
        category=CreationSkillCategory.CHARACTER,
        prompt_suffix=(
            "single canonical waist-up identity portrait, lock age build hair "
            "skin tone face shape eye color and one signature accessory, even "
            "soft studio light, plain backdrop, no second character"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-char-period-sheet",
        title="古装戏曲式设定板",
        description=(
            "古装角色设定图：强侧光分割五官，左侧全身三视图、右侧刺绣与头面"
            "细节加克制色板，一人一板。"
        ),
        category=CreationSkillCategory.CHARACTER,
        prompt_suffix=(
            "period Chinese costume character sheet, strong opera-style side "
            "light, left three-view full body in hanfu, right face and "
            "embroidery details plus a muted palette, solid dark studio, one "
            "character only"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-char-urban-contrast",
        title="都市反差人设设定板",
        description=(
            "都市短剧常用的「看起来普通、细节很贵」人设板：同一人便装站姿三视图，"
            "右侧特写一件昂贵标志物。"
        ),
        category=CreationSkillCategory.CHARACTER,
        prompt_suffix=(
            "modern urban character sheet emphasizing status contrast, the "
            "same person in ordinary street clothes with one expensive "
            "signature item, left three-view full body, right face and "
            "accessory close-ups, cool city-neutral studio, no location "
            "backdrop"
        ),
        aspect_ratio="3:4",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-scene-vertical-establish",
        title="竖屏空镜建立",
        description=(
            "给竖屏短剧用的无人建立镜头：建筑或地形占满高度，人物完全不出现，"
            "只交代空间尺度。"
        ),
        category=CreationSkillCategory.SCENE_ASSET,
        prompt_suffix=(
            "vertical empty establishing shot, architecture filling the height "
            "of the frame, no people no silhouettes no crowds, deep space, "
            "natural light, photoreal environment still"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-scene-rain-alley-empty",
        title="雨夜无人巷空镜",
        description=(
            "潮湿霓虹后巷的纯空镜：积水反光、无行人无前景车辆，给密谈或追逐戏"
            "当地点底板。"
        ),
        category=CreationSkillCategory.SCENE_ASSET,
        prompt_suffix=(
            "deserted rain-soaked urban alley at night, neon reflections in "
            "puddles, no pedestrians no foreground vehicles, wet asphalt, "
            "cinematic empty set, photoreal"
        ),
        aspect_ratio="16:9",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-scene-mansion-empty",
        title="冷调豪门客厅空镜",
        description=(
            "挑高落地窗的空客厅：冷色调、家具克制，画面里不能有任何人物或"
            "可辨认肖像。"
        ),
        category=CreationSkillCategory.SCENE_ASSET,
        prompt_suffix=(
            "empty opulent living room, floor-to-ceiling windows, cold color "
            "grade, expensive but minimal furniture, no people no readable "
            "portraits, still establishing shot"
        ),
        aspect_ratio="16:9",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-scene-hospital-empty",
        title="医院走廊高压空镜",
        description="荧光灯长走廊的无人空镜，透视压向尽头，只留空间本身的不安。",
        category=CreationSkillCategory.SCENE_ASSET,
        prompt_suffix=(
            "empty hospital corridor, harsh fluorescent overhead lighting, "
            "long telephoto compression toward the far doors, no staff no "
            "patients, sterile cold tones"
        ),
        aspect_ratio="16:9",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-scene-glass-office-empty",
        title="玻璃幕墙总裁办空镜",
        description="无人的高层转角办公室，玻璃墙外是城市天际线，只交代权力空间。",
        category=CreationSkillCategory.SCENE_ASSET,
        prompt_suffix=(
            "empty high-rise corner office, floor-to-ceiling glass wall "
            "overlooking a city skyline, cold blue tint, no people, sharp "
            "geometric shadows from window mullions"
        ),
        aspect_ratio="16:9",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-scene-parking-empty",
        title="地下停车场密谈空镜",
        description="低顶混凝土与一盏钠灯的空车库，远处可以有静止车影，前景不许有人。",
        category=CreationSkillCategory.SCENE_ASSET,
        prompt_suffix=(
            "empty underground parking garage, low concrete ceiling, single "
            "sodium vapor lamp, parked cars only as distant still shapes, no "
            "people, long shadows between columns"
        ),
        aspect_ratio="16:9",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-scene-balcony-empty",
        title="黄昏老城阳台空镜",
        description="暖金黄昏的无人阳台，衣架与屋顶在虚焦里，给独白或回忆当空镜。",
        category=CreationSkillCategory.SCENE_ASSET,
        prompt_suffix=(
            "empty old-town rooftop balcony at golden hour, warm film grain, "
            "laundry lines and rooftops in soft-focus background, no people, "
            "soft backlight"
        ),
        aspect_ratio="16:9",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-scene-wedding-empty",
        title="婚礼礼堂空场空镜",
        description="红金礼堂被压成略冷的色温，通道空着，宾客席位空置，不许出现人脸。",
        category=CreationSkillCategory.SCENE_ASSET,
        prompt_suffix=(
            "empty ornate wedding hall at night, red-and-gold decor under a "
            "slightly cold grade, vacant aisle and empty chairs, no guests no "
            "faces, festive space that feels too quiet"
        ),
        aspect_ratio="16:9",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-cover-title-safe",
        title="竖屏标题安全区封面",
        description=(
            "竖版封面的基础版式：上三分之一留白给标题，主体压在中下，画面里"
            "不写任何字。"
        ),
        category=CreationSkillCategory.COVER_ASSET,
        prompt_suffix=(
            "vertical nine-sixteen key art, top third empty negative space "
            "reserved for a title, subject placed in the lower two-thirds, "
            "cinematic lighting, no logos, no legible text rendered"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-cover-reversal",
        title="打脸反转封面",
        description="冷暖对切的竖屏封面：人物回眸停在反转落地的那一拍，上方留出标题带。",
        category=CreationSkillCategory.COVER_ASSET,
        prompt_suffix=(
            "vertical short-drama cover, cold-to-warm split lighting, one "
            "figure looking back over the shoulder at the turning point, top "
            "third title-safe blank band, no legible text rendered"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-cover-sweet-romance",
        title="甜宠暖金封面",
        description="暖金柔光的竖屏封面，两人关系用距离和光说完，标题区留白，不写字。",
        category=CreationSkillCategory.COVER_ASSET,
        prompt_suffix=(
            "vertical warm golden romance cover, soft highlight bloom, two "
            "figures in a quiet close distance, top third title-safe blank, "
            "flattering backlight, no legible text rendered"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-cover-suspense",
        title="悬疑青冷封面",
        description="低饱和青绿色调的竖屏封面，人物缩小在阴影里，上方留给标题。",
        category=CreationSkillCategory.COVER_ASSET,
        prompt_suffix=(
            "vertical teal noir cover, desaturated crushed shadows, one small "
            "figure in a large dark space, top third title-safe blank, visible "
            "film grain, no legible text rendered"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-cover-period-intrigue",
        title="古装权谋封面",
        description="戏曲式侧光的竖屏宫斗封面，单人礼服剪影，标题安全区留白。",
        category=CreationSkillCategory.COVER_ASSET,
        prompt_suffix=(
            "vertical period palace cover, strong opera sidelight, one "
            "costumed figure, rich textile texture, top third title-safe "
            "blank, no logos, no legible text rendered"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-cover-rebirth",
        title="重生闪回封面",
        description="同一人被一分为二：一侧暗的残片、一侧尚未发生的清晨，上方留白给标题。",
        category=CreationSkillCategory.COVER_ASSET,
        prompt_suffix=(
            "vertical rebirth-cover still, a brief dark flash of a future "
            "crisis split against a bright ordinary morning of the same "
            "person, top third title-safe blank, no legible text rendered"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-cover-identity-freeze",
        title="身份揭示定格封面",
        description="证据抛出后的表情定格封面，脸部占中下，上方留白，不写对白或标题字。",
        category=CreationSkillCategory.COVER_ASSET,
        prompt_suffix=(
            "vertical cover freeze on a reveal-beat close-up, collapsing "
            "expression held, top third title-safe blank, dramatic key light, "
            "no legible text rendered"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
    CatalogSkill(
        key="asset-cover-series-key-art",
        title="系列主视觉海报封面",
        description="系列级竖屏主视觉：电影感构图、大面积页眉留白，不放 logo 也不写片名。",
        category=CreationSkillCategory.COVER_ASSET,
        prompt_suffix=(
            "vertical series key art, cinematic hero composition, large empty "
            "header band reserved for a title, no logos, no legible text "
            "rendered"
        ),
        aspect_ratio="9:16",
        applicable_operations=_IMAGE_OPERATIONS,
    ),
)

_BY_KEY: dict[str, CatalogSkill] = {item.key: item for item in CATALOG}


def find(key: str) -> CatalogSkill | None:
    return _BY_KEY.get(key)
