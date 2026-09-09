"""Seed catalogue of `CreationSkill` templates: short-drama video recipes,
a "图片风格 image style" section for the image studio, a canvas section
(framing / lighting / staging / method) for composing a still before it is
animated, and a dual-shape 「图片资产」section (`character` / `scene_asset`
/ `cover_asset`).

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

Not every entry here has a cover in `seed_covers/`; the canvas section
ships without them for now and `ensure_catalog_skills` looks a cover up per
key rather than assuming one.

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
    (adding one for ~86 seed rows isn't worth a migration), so
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
