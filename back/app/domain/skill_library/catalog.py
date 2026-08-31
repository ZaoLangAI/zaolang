"""Seed catalogue of `CreationSkill` templates: short-drama video recipes
plus a smaller "图片风格 image style" section for the image studio.

Genre/shot/scene *naming conventions* here are informed by patterns common to
several open-source "AI short-drama" Agent Skill suites (Claude/Codex
`SKILL.md` instruction sets), and the image-style section's naming is
informed by publicly documented 2026 Nano Banana / GPT-Image prompt-trend
write-ups — see `THIRD_PARTY_NOTICES.md` in this package for sources and
licences. None of that is a `CreationSkill.params_json` template to begin
with: an Agent Skill's `SKILL.md` drives an LLM coding agent through a
multi-file production pipeline, and a prompt-trend write-up is prose about a
technique, not a flat `prompt_suffix`/`aspect_ratio` dict a job folds in.
Every `title` / `description` / `prompt_suffix` below is original text
written for this catalogue.

`ensure_catalog_skills` (`app.domain.skill_library.service`) is what turns
this table into real `CreationSkill` rows — this module only declares *what*
to seed and never touches a session or an ORM class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
# image. The "图片风格 image style" section further down is the deliberate
# exception: those rows use `_IMAGE_OPERATIONS` instead so they surface in
# the image studio's `@` menu (`text_to_image`/`image_to_image`) and stay
# out of the video one, mirroring the same category (`STYLE`) rather than
# needing a new `CreationSkillCategory` value.
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
    (adding one for 42 seed rows isn't worth a migration), so
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

    def params_json(self) -> dict[str, str]:
        return {"prompt_suffix": self.prompt_suffix, "aspect_ratio": self.aspect_ratio}

    def cover_path(self) -> Path | None:
        """This entry's seeded cover JPEG, or `None` if none was shipped."""
        candidate = _COVERS_DIR / f"{self.key}.jpg"
        return candidate if candidate.is_file() else None


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
)

_BY_KEY: dict[str, CatalogSkill] = {item.key: item for item in CATALOG}


def find(key: str) -> CatalogSkill | None:
    return _BY_KEY.get(key)
