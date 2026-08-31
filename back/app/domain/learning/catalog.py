"""Seed catalogue of platform-curated `LearnPost` tutorials.

`learnPage.heroSubtitle` (`front/src/i18n/messages/zh-CN.json`) sets the
product's own scope for this page: "面向大众用户的短课程，讲清提示词、镜头、
授权、成本与发布" -- short courses that explain prompts, shots, licensing,
cost, and publishing. The nine entries below are grouped by
`LearnPostLevel` and were written to cover exactly that scope plus the
platform's own asset/script features (character/scene libraries, script
writing beats, episode planning), each one naming a real route/feature this
repository actually has (`/skills`, `/create/characters`, `/create/scenes`,
`/create/script`, `/create/short`, `/publish/[draftId]`, `/remix/[workId]`)
rather than an invented one.

General 2026 AI-short-drama production practices (asset-driven character
consistency over single-reference prompting, shot-level generation over
whole-episode generation, the golden-hook pacing rhythm, "subject + action +
scene + lighting + shot + style + quality + constraints" as a prompt
skeleton, pre-release licensing checklists) were consulted only to keep this
content credible -- every `title`/`summary`/`body_markdown` below is
original text written for this product, describing this product's own
features, not excerpted or adapted from any single external source.

`ensure_catalog_posts` (`app.domain.learning.service`) is what turns this
table into real `LearnPost` rows -- this module only declares *what* to
seed and never touches a session or an ORM class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models.enums import LearnPostLevel

# AI-generated cover stills shipped alongside this module (one JPEG per
# `LearnPostSeed.key`), committed to the repo as system-default content —
# `ensure_catalog_posts` uploads whichever of these exist and are still
# missing from a seeded post's `cover_asset_id`. Looked up per-key rather
# than assumed, same as `skill_library.catalog`.
_COVERS_DIR = Path(__file__).parent / "seed_covers"


@dataclass(frozen=True, slots=True)
class LearnPostSeed:
    """One seeded `LearnPost` template.

    `key` is this catalogue's own stable identity for tests/tooling -- it
    is never persisted. `LearnPost` has no dedicated catalogue-key column
    (adding one for 9 seed rows isn't worth a migration), so
    `ensure_catalog_posts` matches an existing row by `(author_user_id,
    title)` instead; `title` is therefore the real identity once seeded.
    """

    key: str
    title: str
    summary: str
    level: LearnPostLevel
    body_markdown: str

    def cover_path(self) -> Path | None:
        """This entry's seeded cover JPEG, or `None` if none was shipped."""
        candidate = _COVERS_DIR / f"{self.key}.jpg"
        return candidate if candidate.is_file() else None


_PROMPT_101_BODY = """## 别急着写一整段话

刚打开"创作视频"（`/create/new`）时，很多人会把脑子里的画面一股脑塞进一句话里，结果生成结果和想象差很远。提示词其实是可以拆成几块分别写清楚的：

- **主体**：谁在画面里，穿什么、什么发型、大概年龄——写具体，不写"一个漂亮女生"这种模糊描述。
- **动作**：这个人正在做什么，动作要慢、要连续。AI 生成短片段最怕"又跑又转又说话"一次塞太多动作。
- **场景**：在哪儿，环境里有什么关键元素（霓虹招牌、雨夜路面、玻璃幕墙办公室……）。
- **光影**：白天还是夜晚、暖光还是冷光、逆光还是顺光。
- **镜头语言**：特写、过肩、俯拍仰拍、手持跟拍——不确定怎么写术语没关系，见下一篇"技能库广场入门"。
- **风格**：都市情感、悬疑、甜宠、赛博朋克……风格词决定整体调性。
- **画质与约束**：加上"4K 超高清、画面稳定、无抖动、无模糊"这类兜底词，减少糊脸、变形的概率。

## 一个可以照抄的顺序

把上面几块按"主体 → 动作 → 场景 → 光影 → 镜头 → 风格 → 画质 → 约束"的顺序写成一段话，就是一条能直接提交的提示词。先用短句练习，跑通一次生成之后再逐步加细节，比一开始就写长段落更容易调对。

## 新手常见翻车点

- 一段提示词里塞两三个不同动作——AI 会各生成一部分，画面容易断裂。
- 只写"一致的人物"却不描述具体长相——这句话对模型来说信息量太少，效果不稳定，更可靠的做法见"人物不跳脸"那篇。
- 完全不写镜头语言——默认镜头往往是最普通的正面中景，缺乏短剧感。

先用一条简单的提示词跑通"创作视频"的完整流程，比一开始追求完美更重要。"""

_SKILL_PLAZA_BODY = """## 技能库里的三类"配方"

打开"技能库广场"（`/skills`），除了角色、场景这类资产型技能，还有三类可以直接套用到任意生成里的模板：

- **镜头（lens）**：比如"过肩镜头·正面对峙""俯拍/仰拍·权力落差"——描述的是机位和运镜方式。
- **场景（scene）**：比如"都市霓虹后巷""医院走廊·生死时刻"——已经写好的环境细节。
- **风格（style）**：比如"都市打脸·冷暖对切""悬疑·青冷胶片颗粒"——决定色调和整体质感。

## 怎么用

打开一个技能卡片，先看它的说明——写的是这条配方适合什么情景（对峙戏、追逐戏、反转前的铺垫……）。选中后它会作为附加参数折进你本次生成的提示词里，不需要你自己再去拼写术语。免费技能直接用，标了积分的技能需要先解锁。

## 小技巧

- 先确定这一段戏的情绪（压迫感？温情？悬疑？），再去技能库里按情绪找配方，比盲目翻页更快。
- 同一集里不同场次可以换不同的"风格"技能，用色温和质感的变化替观众"读"出情绪转折，比堆台词更有短剧感。
- 自己调出满意的参数组合后，也可以在生成结果页把它"存为技能"，攒成自己的常用配方库。"""

_CREDITS_BODY = """## 提交的那一刻，钱已经"预留"了

点击生成按钮时，系统会先按这次任务的类型和参数预估一笔积分，从你的账户里预留（不是立刻扣光，而是先冻结）。等任务真正跑完，才会按实际结果结算：

- **成功**：预留的积分按实际费用结算，多退少不补的差额会自动处理。
- **失败**：预留会被释放，不会真的从余额里扣掉——因为你没有拿到可用的输出。
- **人工终止一个卡住的任务**：系统走的是标准的任务状态机，预留同样会被正确释放，不会出现"钱没了任务也没了"的情况。

## 不同创作类型，成本差别很大

图片创作和创作视频、语音生成的基础积分门槛不一样（"创作中心"每张卡片上会标基础起价），同一类型里参数越复杂（分辨率、时长、是否带参考图/参考视频）积分也会相应变化。提交前留意页面上给出的预计消耗，心里有数再点确认。

## 一个实用习惯

正式生成前，先用一条简单提示词小范围试一次，确认方向对了，再加细节、加参考图去生成正式版本——比一上来就跑高参数任务更省积分，也更容易控制成本。"""

_CHARACTER_BODY = """## 为什么同一个人总是"跳脸"

短剧最容易穿帮的地方就是同一个角色在不同镜头里长得不一样。原因通常不是提示词没写"同一角色"，而是**没有一份可以反复复用的角色资产**——每次生成都是重新描述一遍长相，模型自然会有偏差。

## 用"角色库"而不是临时描述

打开"角色库"（`/create/characters`）新建一个角色，把这几件事一次性定下来：

- **正面 / 侧面 / 背面**三视图：只有一张正面照片不够，多角度参考能让模型在不同机位下都认得出这是同一个人。
- **固定不变的部分**：脸型、发型、标志性服装或道具——写清楚哪些是"绝不能变"的。
- **可以随剧情变化的部分**：表情、姿势、天气造成的湿发这类细节可以留一定弹性，不用锁死。

## 生成时怎么用

在"创作视频"里选择这个角色作为参考，之后每一段涉及这个角色出镜的生成都引用同一份资产，而不是重新打字描述一遍长相。角色资产也可以分享到技能库广场（需要确认拥有分享这个形象的权利），设置解锁价格后，其他创作者也可以用积分购买套用。

## 小提醒

角色不是做完就一成不变——如果中途换了造型（比如剧情走到换发型的节点），建议给这套造型单独建一版参考，而不是覆盖掉原来的资产，方便前后剧情对照复用。"""

_SCENE_BODY = """## 场景也会"穿帮"

角色会跳脸，场景同样会"变样"——同一个"总裁办公室"，上一集是暖光落地窗，下一集变成了完全不同的布局，观众一样会出戏。

## 用场景库固定空间

打开"场景库"（`/create/scenes`）新建一个场景资产，把空间本身的细节写清楚：

- 空间类型和布局（客厅的落地窗方向、走廊的长度、后巷的路面材质）。
- 固定的光影基调（这个场景默认是冷调还是暖调、白天还是夜晚）。
- 标志性道具或背景元素（一盏灯、一幅画、一块霓虹招牌）——这些细节是观众识别"这是同一个地方"的关键。

场景资产的说明里**不要**出现具体人物，它只负责空间本身，人物一致性交给角色库处理，两者分开维护更容易复用。

## 一个场景，多种用法

同一个场景资产可以在系列里反复引用：不同集数在同一个客厅发生不同的冲突，观众靠环境认出这是"同一个家"，剧情的连续感就建立起来了。场景库和角色库一样支持分享到技能库广场，标好价格后其他创作者也能购买使用。"""

_SCRIPT_WRITING_BODY = """## 短剧靠的是"防划走节奏"

短剧和长剧最大的区别，是每一秒都在跟观众划走的手指较劲。行业里公认的做法是：开场 3 秒内必须抛出冲突或悬念，不做人物介绍式铺垫；每二三十秒给一次情绪节点；结尾必须留一个具体的、能在后续一两集兑现的钩子，而不是"敬请期待"式的空泛悬念。

## 技能库广场里现成的"剧本节拍"

打开"技能库广场"（`/skills`），除了镜头和风格，还有一类专门服务剧本结构的技能，比如：

- **三秒钩子·开场即冲突**：第一句台词或第一个画面就是冲突本身。
- **身份反转·打脸结构**：羞辱 → 隐忍不辩解 → 关键道具/来电/证件揭示身份 → 对方态度瞬间崩塌，四拍缺一不可。
- **去 AI 味·口语化对白**：台词要有停顿、重复、打断，避免"你以为……殊不知……"这类网文腔。

这些技能的说明文字本身就是可以直接参考的写作规则，不需要你自己去总结套路。

## 在"文案创作"里落地

打开"文案创作"（`/create/script`），把想法讲给助手，然后在对话里 @ 引用上面这些节拍技能，让它按这套结构帮你搭建单集大纲和台词。写完的剧本会保留在同一个短剧项目下，后续可以直接进入分集管理和剪辑流程，不用另外导入。"""

_REMIX_LICENSING_BODY = """## 默认规则：谁能碰你的作品

一件作品发布后，**默认只有作者本人**可以在它的基础上继续二创。别人想拿你的作品当素材，必须等你主动打开"允许二创"的开关——这是一个明确的选择，不是默认行为。

## 打开二创之后，会发生什么

一旦作者开放二创，别人在"二创"（`/remix/[workId]`）页面上重新生成的新版本会带上一份**许可快照**：记录当时的授权条件是什么样的，这份快照会跟着这条创作链一直往下传，即使原作后来关闭了二创，已经产生的二创作品和它们携带的授权记录不受影响。

## 创作链留下的痕迹

每一次二创都会在系统里留下一条"从哪来"的记录，作品详情页可以看到这条链路——原作者、二创者、以及各自的许可状态都能追溯，这既是对原作者的保护，也是对二创者的说明责任。

## 给创作者的建议

- 上传角色形象、他人肖像作为参考素材前，先确认自己确实拥有分享这个形象的权利——角色分享到技能库广场时，系统会要求明确的授权确认。
- 如果你不希望作品被二创，保持默认（不开启"允许二创"）即可，不需要额外操作。
- 想让别人基于你的作品继续创作、甚至设置积分解锁价格，主动开启二创并设置价格是唯一入口。"""

_EPISODE_MAP_BODY = """## 一集只讲一件事，但结尾必须"欠"观众一个钩子

把一个长故事拆成几十集短剧时，最常见的问题是某几集"只是过渡"，看完什么都没记住。更可靠的做法是给每一集都定一个具体的钩子——一个观众能说得出来的、悬而未决的问题，并且这个钩子要能在接下来一两集里兑现，不能无限期欠着不还。

## 大小情绪点搭配着放

行业里常见的节奏是：每一集设置一个"小情绪点"（解决一个小麻烦、赢下一次小对峙），每隔几集再安排一次"大情绪点"（一次彻底的反转或高潮）。小情绪点负责留住观众不弃剧，大情绪点负责形成记忆点，两者交替使用比全程平铺直叙效果更好。

## 在"创作中心 · 短剧"里落地

打开"短剧"（`/create/short`），新建一个系列后，在系列详情页规划每一集的定位——先用一两句话写清楚这一集要解决什么、结尾留什么钩子，再进入"文案创作"具体展开台词。这样即使中途换人接手某一集，也能一眼看懂整体的分集节奏，不会写出前后接不上的剧情。

## 小技巧

写分集大纲时，可以先把每一集的"结尾钩子"单独列一张清单，检查相邻几集之间钩子是否都有兑现，不要出现连续几集都在"欠债"而不"还债"的情况。"""

_FROM_DRAFT_TO_PUBLISH_BODY = """## 生成只是第一步

一段视频生成完成后，你手上的是一个"草稿"（Draft），还不是正式发布的作品。这中间有几种常见的走法，按需要选择：

- **直接发布**：如果这段生成结果已经满意，可以直接走"发布"（`/publish/[draftId]`）流程，走完必要的信息填写和确认后进入平台展示。
- **先进入剪辑再发布**：如果想拼接多段素材、加字幕、调音量，可以从生成结果页"进入剪辑"，打开浏览器端的剪辑工作台，做时间线级别的精修。

## 剪辑之后怎么变成可发布的作品

在剪辑工作台里完成时间线编辑后，通过"导出"生成一份最终成片。导出完成的成片需要**绑定**回一个草稿，才能走标准的发布流程——这一步系统通常会自动处理（复用原来的草稿，或在需要时新建一个），你只需要在发布前确认一下绑定的就是你想发布的那份成片。

## 发布前最后检查一遍

- 确认标题、简介、封面已经填好。
- 如果这段作品用到了别人开放二创的素材，确认授权链路清晰（详情见上一篇"二创授权全解"）。
- 想清楚是否要开放"允许二创"——这个开关发布后仍然可以调整，但默认是关闭的。

确认无误后提交发布，作品就会正式出现在你的主页和相关的发现页面里。"""


CATALOG: tuple[LearnPostSeed, ...] = (
    # ---------------------------------------------------------------- 新手 beginner
    LearnPostSeed(
        key="prompt-101-first-clip",
        title="从一句话开始：写好提示词，生成你的第一支短剧片段",
        summary=(
            "主体+动作+场景+光影+镜头+风格+画质+约束——学会这套提示词公式，"
            "新手也能一次生成能直接用的画面。"
        ),
        level=LearnPostLevel.BEGINNER,
        body_markdown=_PROMPT_101_BODY,
    ),
    LearnPostSeed(
        key="skill-plaza-lens-style",
        title="技能库广场入门：一键套用镜头与调色配方",
        summary=(
            '不会写"过肩镜头""冷暖对切"这些术语？去技能库广场（/skills）'
            "找现成配方，套进你的提示词里就能用。"
        ),
        level=LearnPostLevel.BEGINNER,
        body_markdown=_SKILL_PLAZA_BODY,
    ),
    LearnPostSeed(
        key="credits-and-cost-basics",
        title="看懂积分账本：每次生成花的是什么钱",
        summary=(
            "提交任务时积分怎么扣、失败会不会退——搞懂预扣与结算规则，"
            "创作前先算清楚这笔账。"
        ),
        level=LearnPostLevel.BEGINNER,
        body_markdown=_CREDITS_BODY,
    ),
    # ---------------------------------------------------------------- 进阶 intermediate
    LearnPostSeed(
        key="character-consistency-library",
        title="人物不跳脸：用角色库留住同一张脸",
        summary=(
            "靠一张参考图不够稳——建一个带正/侧/背视图的角色资产，"
            '每次生成都用它，把"这是谁"锁死。'
        ),
        level=LearnPostLevel.INTERMEDIATE,
        body_markdown=_CHARACTER_BODY,
    ),
    LearnPostSeed(
        key="scene-asset-space-continuity",
        title="场景资产怎么用：让每一集共享同一个空间",
        summary=(
            "都市霓虹后巷、豪门客厅——用场景库固定空间细节，"
            '同一个场景在多集里不"重新装修"。'
        ),
        level=LearnPostLevel.INTERMEDIATE,
        body_markdown=_SCENE_BODY,
    ),
    LearnPostSeed(
        key="script-writing-hook-beats",
        title="用文案创作搭反转结构：三秒钩子怎么落地",
        summary=(
            '配合技能库里"三秒钩子""身份反转打脸"这类剧本节拍技能，'
            "让文案创作助手按套路帮你搭好单集结构。"
        ),
        level=LearnPostLevel.INTERMEDIATE,
        body_markdown=_SCRIPT_WRITING_BODY,
    ),
    # ---------------------------------------------------------------- 高阶 advanced
    LearnPostSeed(
        key="remix-licensing-explained",
        title="二创授权全解：什么能改、什么不能改",
        summary=(
            "默认只有作者自己能继续创作——主动开放二创后，来源、作者和许可"
            "快照才会随创作链一路带下去。"
        ),
        level=LearnPostLevel.ADVANCED,
        body_markdown=_REMIX_LICENSING_BODY,
    ),
    LearnPostSeed(
        key="episode-map-hook-density",
        title="分集地图：把一个故事拆成能追更的短剧",
        summary=(
            "每集结尾都要留一个能在一两集内兑现的钩子——用分集节奏规划系列剧，"
            '而不是"敬请期待"式空转。'
        ),
        level=LearnPostLevel.ADVANCED,
        body_markdown=_EPISODE_MAP_BODY,
    ),
    LearnPostSeed(
        key="from-draft-to-publish",
        title="从生成到发布：进入剪辑、导出与发布流程",
        summary=(
            "片段生成之后去哪儿？进入剪辑精修、导出成片、绑定草稿，"
            "走完发布前的完整链路。"
        ),
        level=LearnPostLevel.ADVANCED,
        body_markdown=_FROM_DRAFT_TO_PUBLISH_BODY,
    ),
)

_BY_KEY: dict[str, LearnPostSeed] = {item.key: item for item in CATALOG}


def find(key: str) -> LearnPostSeed | None:
    return _BY_KEY.get(key)
