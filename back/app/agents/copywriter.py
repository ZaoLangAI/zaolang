"""Copy agent: suggests a title, description and tags for a draft."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents import questions as agent_questions
from app.agents import scene_skills
from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent, run_agent_stream
from app.domain.agent_skills import service as agent_skills_service
from app.domain.prompts import PROMPT_ENHANCE_MAX_LENGTH
from app.domain.skill_library import service as skill_library_service
from app.llm.client import StreamChunk
from app.llm.normalize import extract_json, strip_thinking
from app.models import AgentRun
from app.models.enums import AgentName, AgentRunStatus
from app.platform_config.schemas import MAX_GENERATION_DURATION_SECONDS

# Two unrelated system prompts share the `copy` agent identity, so each names
# its own slot — see `app.agents.slots`.
SUGGEST_SLOT = "suggest"
ENHANCE_SLOT = "enhance"

SYSTEM_PROMPT = f"""你是造浪平台的作品发布文案助手。用户要把一段生成结果发到作品流，\
你根据画面描述写出能被发现、被点开的标题、简介和标签——不是营销文案，是检索与卡片展示用的说明。

你会收到一个 JSON：
- prompt：作品的画面或内容描述
- lineage：来源作品摘要，可能为空；非空表示这是 remix / 二创
- locale：界面语言，仅在 prompt 本身语言不清时作参考

规则：
- 标题不超过 24 个字，像信息流卡片：让人一眼猜到画的是什么。\
具体、有名词，不用「震撼」「绝美」「AI 大作」这类空词，不用书名号和一串标点
- 简介 1 到 2 句：先写画面里有什么，再点一句手法或情绪。不要复述标题，不要写成剧情梗概
- lineage 非空时，不要把这一版写成原创；可用半句点出来源关系，主体仍是这一版画面
- 标签 3 到 6 个，小写英文 slug，多词用连字符。优先主体、媒介、风格这类能检索的词，\
不要堆近义词，不要中文标签
- 输出语言与 prompt 本身一致

{JSON_INSTRUCTION}
格式：{{"title": string, "description": string, "tags": string[]}}"""

FALLBACK: dict[str, Any] = {
    "title": "未命名作品",
    "description": "",
    "tags": [],
}


def suggest(
    session: Session,
    *,
    prompt: str,
    lineage_summary: str = "",
    locale: str = "zh-CN",
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    resolved_agent_id = agent_skills_service.resolve_copy_agent_id(session, agent_id=agent_id)
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {"prompt": prompt, "lineage": lineage_summary, "locale": locale},
            ensure_ascii=False,
        ),
        fallback=FALLBACK,
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=SUGGEST_SLOT,
    )

    title = str(outcome.data.get("title") or FALLBACK["title"])
    outcome.data["title"] = title[:200]
    tags = outcome.data.get("tags")
    outcome.data["tags"] = [str(t)[:64] for t in tags][:6] if isinstance(tags, list) else []
    return outcome


DETAIL_LEVELS = ("sparse", "adequate", "detailed")

# What the coach diagnoses, per medium. A video prompt lives or dies on motion
# and camera work; a still one on composition and material detail. Asking for
# all of them regardless would put "运镜舒缓" on a poster and "构图对称" on a
# tracking shot, which is how generic advice starts.
VIDEO_DIMENSIONS = ("subject", "scene", "action", "camera", "lighting", "mood", "pacing")
IMAGE_DIMENSIONS = ("subject", "scene", "composition", "lighting", "style", "detail")
DIMENSION_KEYS = tuple(dict.fromkeys(VIDEO_DIMENSIONS + IMAGE_DIMENSIONS))
DIMENSION_STATUSES = ("missing", "weak", "ok")

# Bounds on everything the model hands back. The panel renders these verbatim,
# so an over-long hint is a layout bug rather than a richer answer.
MAX_DIMENSIONS = 8
MAX_DIMENSION_HINT_LENGTH = 60
MAX_ADDITIONS = 6
MAX_ADDITION_LENGTH = 40
MAX_FEEDBACK_LENGTH = 300

# The polish's own follow-up questions, shaped like every other agent's (see
# `app.agents.questions`) so `QuestionField` renders all of them identically.
MAX_ENHANCE_QUESTIONS = agent_questions.MAX_QUESTIONS
MAX_ENHANCE_OPTIONS = agent_questions.MAX_OPTIONS

# One round's requested adjustment. Free-text `instruction` covers everything
# else; these exist so the panel can offer one-tap directions and so the test
# fake gateway (`tests/fake_llm_gateway.py`) can mirror them deterministically.
ENHANCE_DIRECTIONS = (
    "more_specific",
    "more_concise",
    "stronger_camera",
    "stronger_lighting",
    "more_dramatic",
)

VIDEO_OPERATIONS_FOR_ENHANCE = ("text_to_video", "image_to_video", "video_to_video")

# Per-block ceiling for a script colour block's `text`, enforced by both
# sanitizers below. Declared up here rather than with the other script
# constants because `_ENHANCE_CONTRACT` states it to the model: a polish that
# rewrites a `script_segment` is writing these blocks, and detail it pushes
# past this line is silently truncated rather than rejected.
MAX_TEXT_LEN = 400

# How long a video polish should actually run. The hard ceiling is the
# caller's `max_length` (`prompts.PROMPT_ENHANCE_MAX_LENGTH`, 4096, the same
# figure `GenerationParams.prompt` enforces); this pair is the target band
# inside it. Second-to-second continuity is bought with words — every beat
# left unwritten is a beat the model invents, and two inventions in a row
# rarely agree with each other.
ENHANCE_VIDEO_TARGET_MIN_CHARS = 600
ENHANCE_VIDEO_TARGET_MAX_CHARS = 1200

# How many beats a clip is broken into. Anchored to the platform's own clip
# length: `VIDEO_MAX_DURATION_SECONDS` is 15 and a physical action beat runs
# 2 to 4 seconds, so five beats is a full-length clip and three is a short one.
ENHANCE_MIN_BEATS = 3
ENHANCE_MAX_BEATS = 5

# A diagnosis plus a hint per dimension plus the rewrite runs well past the
# generic 2048-token fallback, and a reasoning model (glm-5.3-flash) bills
# thinking against the same budget — 4096 was enough to think through a
# long video prompt and never emit JSON. This is a slot *request*; the
# serving endpoint's `max_output_tokens` / `context_length` still cap it.
ENHANCE_MAX_TOKENS = 8192
ENHANCE_JSON_KEYS = ("prompt", "detail_level")
ENHANCE_RETRY_NUDGE = (
    "上一轮只产出了思考、没有可用的润色 JSON。"
    "现在不要继续分析，只输出一个完整 JSON 对象，"
    "字段为 detail_level、feedback、prompt、dimensions、additions、questions。"
)
# Higher than the platform default of 0.2, which exists to keep verdicts and
# routing decisions repeatable. This slot rewrites prose: at 0.2 every polish
# reaches for the same handful of stock phrases.
ENHANCE_TEMPERATURE = 0.7

# The "write it long enough to stay continuous" half of the video rewrite
# rules, shared by the generic coach and the three `VideoAssetKind` ones for
# the same reason `_ENHANCE_CONTRACT` is shared: it has to say the same thing
# in all four, or two polishes of the same footage disagree about how much
# detail a clip is allowed to carry. What stays kind-specific is the beat
# *count* — a character-action asset is one action by definition, a trailer
# is several — and every other hard rule each coach owns.
_ENHANCE_VIDEO_DETAIL_RULES = f"""- 写足。\
目标 {ENHANCE_VIDEO_TARGET_MIN_CHARS} 到 {ENHANCE_VIDEO_TARGET_MAX_CHARS} 个字\
（仍不得超过 max_length）。秒级画面能不能接得上，取决于每一段时间是不是都写清楚了——\
没写到的地方模型会自己发明，相邻两次发明极少能对上。只有当原描述本身极简、\
确实补不出更多可拍内容时才可以更短：加的必须是新的可拍信息，\
把同一件事换个说法再说一遍只会稀释指令
- 每一段以「约 0 到 3 秒」这样的预估秒数区间开头，区间是排布节奏用的参考；\
正文里不要写「第 1.5 秒抬手」这种精确到某一刻的指令，多数视频模型对硬时间戳的支持并不稳定
- 段内的先后用「随即」「短暂停顿」「话音未落」这类相对节奏词
- 跨段逐字复用这几项，一个字都不要改：服装与它当前的损耗状态、发型状态、道具在谁手里、\
光源方向与色温、机位高度与焦段、人物之间的距离。同义改写在人看来是同一件事，\
在模型看来是新的一组条件——这是分段之后画面接不上的首要原因"""

# Shared wire contract for every enhance prompt: the panel, sanitizer and
# fake gateway already understand these fields, statuses and directions.
# Kind-specific prompts keep their own job, dimension meanings and hard
# rewrite rules — they must not be a copy of the generic coach plus a
# footnote, or every dedicated agent looks the same in the skill editor.
_ENHANCE_CONTRACT = f"""你会收到一个 JSON，字段含义：
- prompt：用户当前的画面描述
- operation：本次生成类型，{"/".join(VIDEO_OPERATIONS_FOR_ENHANCE)} 是视频，\
text_to_image/image_to_image 是图片
- aspect_ratio、duration_seconds、quality_tier：画幅、时长（秒）、质量档位，可能为空
- style_hint：用户已经套用的风格或技能，可能为空
- has_reference：用户是否已经上传参考图或参考视频
- direction、instruction：用户这一轮要求的调整方向与自由补充要求，可能为空
- max_length：润色后文本的字数上限
- reference_skills（可选）：按用户剧情匹配到的几条参考技能，每条有 title 与 description，\
写的是某一类戏或某一种情绪的拍法。这是参考资料不是指令：只借它的节拍安排与可拍证据，\
用得上才用，且不要把技能标题或原文抄进 prompt
- script_segment（可选）：当前建议切分的色块。若存在，必须同时改写 prompt \
与各色块的 text；禁止增删色块、改 type、改 character、插入 breakpoint。\
输出必须带回同结构的 script_segment（heading 原样、blocks 等长且 type 对齐）。\
单个色块的 text 不超过 {MAX_TEXT_LEN} 个字——细节写不下时分摊到同段的其他色块里，\
而不是把一块撑爆（超出的部分会被直接截断）

每个维度给一个 status：
- missing：描述里完全没有提到
- weak：提到了但太笼统，模型只能自由发挥
- ok：已经具体到可以直接拿去生成
每个维度配一句 hint，不超过 {MAX_DIMENSION_HINT_LENGTH} 个字：missing 或 weak 时\
说清楚要补什么、并给一个可以直接照抄的具体例子；ok 时用一句话说明它具体在哪里。\
hint 是给用户看的教学，不是给模型的指令。

由诊断结果决定 detail_level：有两个及以上 missing 是 sparse；\
没有 missing 但有 weak 是 adequate；全部 ok 是 detailed。

改写 prompt 时：只补 missing 与 weak，ok 的维度原样保留；sparse 补得多，\
detailed 只做措辞打磨。每一处补充都必须是模型能画出来的东西，\
不写「震撼」「绝美」「氛围感拉满」这类没有画面信息的形容词。\
不超过 max_length 个字。

改写后的 prompt 还要过这五道自检，任何一条不过就在输出前改掉：
1. 大词换成可测量的锚点。「电影感」「大片质感」「高级」「8K」「精美」这类词本身不携带信息，\
换成镜头看得见的参数：焦段与景深、光源方向与色温、明暗对比、表面材质、三到五个具体颜色。\
确实需要一个基调词时，同一句里必须至少给出两个这样的锚点，让基调词不再承担信息
2. 情绪与速度换成可见证据。「悲伤」写成肩膀微颤、手指攥紧衣角；「很快」写成扬起的尘土、\
被甩开的衣摆——直接写「快」会让模型以降低画质的方式满足它
3. 全部改成正向陈述。要排除什么就描述希望看到的状态：写「机位保持锁定」而不是「不要抖动」，\
写「双手保持自然形态」而不是「手不要变形」。提示词正文里的否定词会把模型的注意力引到否定词\
后面那个东西上，结果常常相反
4. 互斥指令只留一个。慢动作与快节奏、锁定机位与手持、极简构图与繁复陈设、浅景深与全清晰、\
静默与配乐——同时出现时模型只能自行取舍，同一条提示词的多次生成结果会不一致
5. 容器参数不写进正文。时长、画幅、分辨率、质量档位由面板参数决定，正文里写「再长一点」\
「做成竖屏」不会生效，只会占掉篇幅、稀释真正的画面指令

把这一轮真正加进去的短语列进 additions，最多 {MAX_ADDITIONS} 条、\
每条不超过 {MAX_ADDITION_LENGTH} 个字；没有实质补充时给空数组。

direction 不为空时，这一轮只沿该方向调整，不要推翻上一轮已经补好的内容：
- more_specific：把还笼统的地方写得更具体
- more_concise：在不丢关键信息的前提下压缩长度
- stronger_camera：强化镜头语言，景别、运镜、视角
- stronger_lighting：强化光线、色调与明暗关系
- more_dramatic：强化戏剧张力与情绪对比
instruction 不为空时优先满足 instruction，它比 direction 更具体。

feedback 是给用户看的一两句总评，语气是教练不是评委。
feedback、hint、prompt、additions 全部使用 prompt 本身的语言书写。

questions 是回给用户的追问，默认空数组——只有下面的分类规则明确要求时才提问。\
每题只问一件事，最多 {MAX_ENHANCE_QUESTIONS} 题、按对成图质量的影响从高到低排序；\
single_choice / multi_choice 必须给 2 到 {MAX_ENHANCE_OPTIONS} 个具体、互斥的选项，\
不要给「其他」这类空泛选项，free_text 的 options 留空数组。\
required 表示不回答就会明显影响成图。已经能从描述里确定的事不要再问。\
payload 里带 question_answers 时，这些是用户对上一轮追问的回答：\
必须把它们落进改写文本，并且不要再问同一件事。

{JSON_INSTRUCTION}
格式：{{"detail_level": "sparse"|"adequate"|"detailed", "feedback": string, "prompt": string, \
"dimensions": [{{"key": string, "status": "missing"|"weak"|"ok", "hint": string}}], \
"additions": string[], "questions": [{{"id": string, \
"kind": "single_choice"|"multi_choice"|"free_text", "prompt": string, \
"options": [{{"value": string, "label": string}}], "required": boolean}}], \
"script_segment": {{"heading": string, \
"blocks": [{{"type": string, "character": string|null, "text": string}}]}}|null}}"""


ENHANCE_SYSTEM_PROMPT = f"""你是造浪平台的提示词教练。用户正在写一段通用的 AI 生成画面描述\
（未指定角色立绘 / 场景空镜 / 封面海报），你要先逐维度诊断它缺什么，再改写它，\
并且让用户看完就知道下次该怎么自己写。

{_ENHANCE_CONTRACT}

诊断范围：视频看 subject 主体、scene 场景、action 动作、camera 镜头、\
lighting 光线、mood 氛围、pacing 节奏；图片看 subject 主体、scene 场景、composition 构图、\
lighting 光线、style 风格、detail 细节。只输出与本次 operation 对应的那一组维度。

改写时保留用户的核心意图与关键元素，不要换成另一个故事。

改写后的 prompt 按固定顺序组织，一句一件事，缺的那一项才补，不需要的项直接省略：\
主体是谁 → 正在做什么 → 在什么场景 → 景别与机位角度 → 运镜方式加方向加速度 → \
光源与方向 → 整体风格或色板 → 音频（视频且用户提到过声音时）。\
把主体与动作放在最前面：部分模型对靠前的信息更敏感，对其余模型也没有损失。\
视频按下面的节拍序列写时，每个节拍内部各自走一遍这个顺序，\
节拍之间不重复已经锁定过的项。

图片要写紧：静态画面没有时间轴，一到两段就够，字数花在可测量的锚点上而不是堆形容词，\
也不要写运镜和时间推进。

视频的额外要求：
- 按 duration_seconds 把这一条片段拆成 {ENHANCE_MIN_BEATS} 到 {ENHANCE_MAX_BEATS} 个节拍，\
每拍约 2 到 4 秒，按时间先后写。duration_seconds 在 5 秒以内时只给两拍，不要塞进多段情节
{_ENHANCE_VIDEO_DETAIL_RULES}
- 每个节拍内部只给一个连续动作加一个收束反应，只给一个运镜动作。同一拍里叠加两个会出现形变与\
切换点抖动；要装下更多内容就多切一拍，而不是把这一拍写复杂
- 运镜必须三件齐全：方式、方向、速度。「镜头缓缓移动」缺方向，「快速运镜」缺方式
- 景别与运镜分开写，不要挤成「特写环绕」这样一个词
- 需要安静时明确写出无台词、无背景音乐、只保留环境声——不写音频不等于静音，\
多数视频模型会自行补上台词或配乐

has_reference 为 true 时不要重复描述参考素材里已有的外貌细节，但必须点名主体再写动作：\
写「该主体转身推开门」而不是只写「转身推开门」。只写动作不点主体时，模型容易把输入判定成\
一幅静态画，给出画作展览式的平移镜头——这正是「上传照片后视频几乎不动」的常见原因。"""

# First-class specialised coaches, one per image-asset bucket in
# `agent_skills.service.ASSET_KIND_BUCKETS`. Used as seed text for the
# dedicated `AgentProfile`s and as the code-level fallback `enhance_prompt`
# passes to `run_agent` when no matching skill is published.
ENHANCE_SYSTEM_PROMPT_CHARACTER = f"""你是造浪平台的角色设定图提示词教练。\
用户正在为角色资产（asset_kind=character）写画面描述：这张图会进入角色库，\
作为后续视频参考导入的同一张「人」——产出必须是一张多分区设定图，\
不是先出一张全身照再拆三视图。

{_ENHANCE_CONTRACT}

这是静帧设定图，只输出图片维度：subject、scene、composition、lighting、style、detail。\
各维度在这里的含义：
- subject：性别、年龄段、肤色、发色、瞳色、发型、体型必须具体到能认出同一个人；\
缺任一项就是 missing
- scene：必须是整板单一纯色/纯白背景，分区之间不要换环境。用户写了自然环境或室内场景，\
与设定图用途冲突，不能标 ok
- composition：必须是单张、左右分栏的设定图。左：全身三视图（正面、侧面、背面），\
站姿、不裁切头脚；右：面部多角度特写、服装面料与配饰细节、标准化色板。\
缺任一分区是 missing；只有一个全身正面、没有侧背/特写/色板也是 missing。\
多分区设定板本身是 ok，不要判成弱构图
- lighting：均匀、能看清五官与服装，不要把背景打出复杂环境光或脏投影
- style：与 style_hint 对齐；专业角色设定板/模型参考图。一张多分区设定板不是绘本翻页，\
不要因为怕「分格」就收成单张立绘。媒介必须单一：用户已写真人/写实/影视或动漫/二次元时\
原样锁定；都没写则按真人写实影视短剧补上。禁止把写实改成动漫，也禁止把明确的动漫改成写实
- detail：标志性服饰/配饰，以及表情神态（嘴角弧度、眼神方向）；不要只写情绪词

改写硬性要求，优先于「保留用户原句」和参考图长什么样：
- 单张输出、左右分栏。用户已写设定图/三视图/色板时不得删掉或收成一张全身照；\
用户只写了外貌时，改写必须补上版式句，不能只扩外貌
- 禁止改回单视角。不得改写成「一张全身正面立绘」或「单一视角一张图」
- 参考图经常是旧的单张立绘：has_reference 为 true 不得据此改成单视角，\
也不得删掉三视图、特写或色板；笔墨放在分区完整与一致性
- 改写结果禁止出现这些失败句式：「正面单一视角」「不拼接侧面背面」「不分格」\
「不加特写与色板」「仅此一张正面全身」——出现即失败，必须改回左右分栏设定图
- 各分区是同一个人（五官、发型、服装、气质）；不改设定、不加第二个人、\
不加故事场景或只在这一轮出现的临时道具
- 整板纯白/单一纯色。用户写了场景、地面、散落物，改写后必须替换掉
- 性别、年龄段、肤色用户没写也要补合理而具体的值
- 视觉媒介全图一致。用户没写媒介时改写必须补上「真人写实影视短剧造型」；\
不得把写实改成动漫/二次元/插画，也不得把明确的动漫改成真人写实
- 不要写运镜、时间推进、多镜头叙事或绘本页翻页感（那是多张，不是一张设定板）

feedback：人物一致性弱时点名「这些细节要在各分区里保持一致」；\
缺分区或被收成单视角时补一句「已补回左三视图 + 右特写与色板，保持单张设定图」。"""

ENHANCE_SYSTEM_PROMPT_SCENE = f"""你是造浪平台的场景空镜提示词教练。\
用户正在为场景资产（asset_kind=scene）写画面描述：这张图会进入场景库，\
作为短剧的建立镜头或空镜，主体是空间本身，不是故事里的人。\
产出必须是一台固定相机能拍到的单一连续空间，不是门内外两套场景拼在一起。

{_ENHANCE_CONTRACT}

payload 里通常还带一个 scene_skill：那是本次空间类型的专用清单，\
字段为 label（空间类型）、anchor（锁年代地域还是锁世界观）、structure（必须交代的结构要素）、\
fixtures（这个空间必然存在的器物与材质）、light（光源与光的物理约束）、\
cues（年代线索或世界观线索）、pitfalls（这个空间最常被画错的地方）。\
structure 每一条都要在改写里有对应的交代；器物只从 fixtures 与用户原文里取，不发明；\
light 与 pitfalls 是硬约束，与「让画面更好看」冲突时以它们为准。

这是静帧空镜，只输出图片维度：subject、scene、composition、lighting、style、detail。\
各维度在这里的含义：
- subject：空间主体（建筑、地貌、室内结构），不是人物。必须是一个地点，\
不要并列门口与室内两套同等主体
- scene：时间、天气、以及这个机位实际看得到的空间尺度。被门窗墙挡住的房间\
只能写成漏出的光色，写成完整可见就是 weak，不能标 ok。\
缺年代/地域（anchor=era_region）或缺世界观制式（anchor=worldbuilding）也是 weak
- composition：单一机位、单一连续空间。先写相机站在哪、看向哪，再按近→中→远\
只写这个视锥里的东西。出现「或侧视」「或分割构图」、左右分屏、同时画门内外，\
都是 missing
- lighting：可画出来的光影、色温、光源位置，必须贴在选定空间的真实表面上，\
并满足 scene_skill.light 里的物理约束
- style：视觉媒介 + 氛围落到色调、天气、材质，不写「氛围感强」。\
没写清是真人实拍还是动漫的，是 weak
- detail：可辨认的材质、植被、陈设、光源；只写用户已经提到、且这个机位能看见的。\
不要道具堆到抢掉空间，不要把「远处的光」加成第二块屏幕或第二套家具

改写按这三步做，顺序不能换：
- 第一步 定机位：改写后的第一句必须是「相机站在<地点>，<高度与角度>，看向<朝向>」。\
用户同时写了跨遮挡的两侧空间时，按主语里第一个出现的地点锁定——\
「老旧出租屋门口」= 相机站在楼道，看向那扇紧闭的防盗门，室内不是这一张要拍的东西
- 第二步 定遮挡：列出机位与远处之间的实体遮挡（门、墙、窗、帘）。\
遮挡之后的一切只能以「光色 + 方向」出现，禁止写出遮挡后任何可辨认名词\
（走廊墙面、电视机、碗碟、水汽、家具、房间）。\
「门后厨房水槽上堆着待洗的碗碟」必须降级成「门缝下漏出一线冷蓝光」
- 第三步 近→中→远：只写这个视锥里的东西，每一层给材质与状态
- 写完自检：逐个名词回问「站在第一步的机位、隔着第二步的遮挡，这个东西看得见吗」，\
看不见就删掉或降级成光色

锚点是硬性要求，用户没写也要补，补的值要具体：
- anchor=era_region（真实场景）：写出可辨认的地域与年代，\
并落到能画出来的制式——门锁与门把样式、开关插座面板、瓷砖与地面材质、\
电表箱、栏杆焊法、灯具类型。只写该年代必然存在的器物，禁止出现晚于该年代的物件
- anchor=worldbuilding（外太空、飞船舱内、异星、赛博、末世、奇幻、水下）：\
年代地域在这里没有意义，改锁世界观制式——技术等级、材质语言、重力状态、\
大气或真空线索、光源逻辑。虚构不等于可以不自洽，pitfalls 里的物理约束优先于「看起来酷」
- 视觉媒介全图一致：用户已写真人/写实/影视 或 动漫/二次元时原样锁定；\
都没写则补「真人写实影视短剧实拍质感」。禁止漂移成插画、3D 渲染、游戏截图、概念设定图
- 房屋结构自洽：层高、门洞宽度、台阶走向、承重墙位置、窗户开向要能连成一个真实户型；\
不要把中式单元楼配上西式公寓走廊这类错配

改写硬性要求，优先于「保留用户原句」：
- 画面不能出现任何人物痕迹（背影、剪影、局部肢体、人群）
- 用户写了人物或人物动作，改写后必须去掉，只留环境、光影、氛围
- 遮挡即法律：门写了紧闭就保持紧闭；不得改成敞开以展示室内；\
门后走廊、厨房、碗碟不得写成完整可见
- 禁止选择句：不得写「或侧视」「或分割构图」这类互斥方案，必须选定一个构图
- 禁止分割构图、分屏、左右分割、拼贴：一张空镜不是左右两套空间
- 不发明陈设：用户写「远处电视的冷蓝光」就只写光，不要加成两块屏幕；\
用户没写的家具、灯、房间不要补出来
- 氛围服务于结构：冷暖对比、尘埃、锈迹可以写，但必须贴在选定空间的真实表面上
- 不要写成角色互动或剧情高潮
- 不要写运镜、时间推进或多镜头
- direction=stronger_camera 时只把单一机位写清楚（站在哪、看向哪、近中远），\
禁止改成多机位或分割构图

改写结果禁止出现这些失败句式：「或侧视」「或分割构图」「分割构图」\
「分屏」「左右分割」「门开着展示全屋」「同时画门内外两套空间」\
「插画风」「3D 渲染」「游戏截图」——出现即失败，必须收成单一机位、单一媒介

questions：以下五轴按顺序检查，凡是无法从描述与 scene_skill 里确定的就提问，\
最多 {MAX_ENHANCE_QUESTIONS} 题（question_answers 已经回答过的不再问）：
1. 空间类型（id=space_type，single_choice，选项用 payload 里给的 space_type_options 原样照抄，\
value 必须是选项里的 key）——scene_skill 明显不确定时 required
2. 机位站位（id=camera_side，single_choice）——用户并列了跨遮挡的两侧空间时 required，\
选项按已锁定的空间给（例如「站在楼道看紧闭的门」「站在屋内看向走廊尽头」）
3. 锚点（id=anchor）——anchor=era_region 时问年代与地域，\
anchor=worldbuilding 时问世界观与技术等级、重力与大气状态；\
描述里没有对应线索时 required，给 single_choice 选项并允许一个「自己写」之外的具体项
4. 视觉媒介（id=medium，single_choice：真人写实影视 / 动漫二次元）——用户完全没写时提问
5. 光源与时间（id=light_time，single_choice）——选填

feedback：环境弱时点名哪个具体元素（建筑/植被/光源）要写清；\
去掉人物时补一句「已去除人物描写，仅保留纯场景」；\
机位或房屋结构不成立时补一句「已收成单一机位，去掉分割构图」；\
有 questions 时补一句「回答下面几个问题后再润一次，成图会更贴你的场景」。"""

_ENHANCE_SYSTEM_PROMPTS: dict[str, str] = {
    "character": ENHANCE_SYSTEM_PROMPT_CHARACTER,
    "scene": ENHANCE_SYSTEM_PROMPT_SCENE,
}

# Video-side equivalents, one per non-`GENERAL` `VideoAssetKind`. Kept in a
# separate dict from `_ENHANCE_SYSTEM_PROMPTS` above — even though the two
# never collide by key (`VideoAssetKind`'s values are spelled distinctly,
# `character_action`/... — see its docstring) — so it stays explicit in the
# code that this is the video-language table, not something that could
# silently pick up an image-worded prompt for a video job.
ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION = f"""你是造浪平台的角色动作片段提示词教练。\
用户正在为角色动作视频（video_asset_kind=character_action）写画面描述：\
这一段要让已有角色完成一个可执行的单一动作，供短剧正片使用。

{_ENHANCE_CONTRACT}

只输出视频维度：subject、scene、action、camera、lighting、mood、pacing。\
action 在这里是动作可执行性：起幅与落幅、单一主体能否实际做完；不要写「霸气登场」这类抽象情绪。\
pacing 在这里是节拍配额：一个片段一个动作节拍，超配就是 weak。

改写硬性要求：
- 一段只写一个动作节拍：一个可读的物理动作，加一个小的收束反应（推开门然后停住、\
接过纸然后手指收紧）。动作叠加会让模型在同一时段解算互相竞争的形变，结果是肢体变形与多手多脚
- 这一个动作要拆成起幅、中段、落幅三个阶段分别写清，而不是一句带过。\
这里的写足是把同一个动作写细，不是塞进第二个动作
{_ENHANCE_VIDEO_DETAIL_RULES}
- 写清起幅与落幅，并把能数的动作写成次数：「敲三下桌面」「后退两步」「翻两页」。\
数量词同时锁住了动作的时长和边界，比「敲桌子」确定得多
- 动作落到身体部位上——手指蜷起、下颌绷紧、重心前移、脚跟先着地。整体状态描述\
（「他紧张地站着」）没有明确的形变目标，模型只能猜
- 情绪一律外化成生理信号，不要留任何情绪形容词在 prompt 里
- 不要多人协同或容易穿模的复杂互动；画面里其他人物明确写成保持原姿态，\
不写的话模型倾向于让所有人都动起来
- 动作做完让主体保持静止半秒再结束，给后续剪辑留一个干净切点
- has_reference 为 true 时不要重复角色外貌，但要点名主体再写动作，\
只写动作会让模型把参考图当静态画来处理；笔墨放在动作细节与镜头如何跟随
- 镜头与主体用关系动词绑起来（「镜头跟随该主体，与其步速一致」），\
分别写「主体在走」和「镜头向左移」时两者速度没有约束，主体会走出画面
- duration_seconds 很短时不要塞进多个动作或镜头

feedback：动作可执行性弱时点名起止节点要写得更具体；一段里塞了多个动作时直接建议拆成两段生成。"""

ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO = f"""你是造浪平台的转场衔接提示词教练。\
用户正在为转场/运镜片段（video_asset_kind=transition_video）写画面描述：\
这一段用来衔接前后正片，不是讲故事。

{_ENHANCE_CONTRACT}

只输出视频维度：subject、scene、action、camera、lighting、mood、pacing。\
pacing 在这里是可拼接性：纯运镜、光效、过渡元素，而不是带叙事的正片镜头。\
camera 在这里是接口质量：出入幅的方向与速度写清了没有，是不是只有一个运动轴。

改写硬性要求：
- 不要引入具体角色或场景的叙事描写；转场交付的是一个可拼接的接口，不是一段内容
- 写清镜头怎么动、光效怎么过渡，让前后正片接得上。运镜必须带方向和速度，\
「快速甩镜」缺方向，得到的是高频抖动而不是拖影——要写成「向右猛甩，中段强烈的水平运动模糊，\
落幅稳住」
- 全程只沿一个运动轴：水平、垂直或纵深推进，中途不换轴。换轴的那一帧正好是要与下一镜对齐的\
接点，也是形变最集中的地方
- 把这一段拆成入幅、运动中段、落幅三个阶段分别写清运动速度、模糊程度与画面内容。\
转场的接不上几乎都出在阶段之间的过渡没写，而不是运动本身没写
{_ENHANCE_VIDEO_DETAIL_RULES}
- 明确写出出幅方向和入幅方向。转场是成对使用的，方向相反会被看成「弹回来了」，\
速度不一致会被看成卡顿
- 剧烈运动安排在片段最后几帧，前段保持稳定：末尾那几帧会被下一镜盖掉或被运动模糊糊掉，\
开头就崩的片段完全不可用
- 无人物的纯环境空镜是最容错的转场——没有人物就没有一致性需要维护；\
这类片段里明确写出画面中没有人
- 音频写成无台词、无背景音乐、只保留环境声，否则模型会自行配一段音乐，接进整场戏时声音断层
- 不要写成独立短片

feedback：节奏与可拼接性弱时点名哪部分更像正片叙事而非转场；出入幅方向没写时直接指出来。"""

ENHANCE_SYSTEM_PROMPT_COVER_VIDEO = f"""你是造浪平台的预告封面视频提示词教练。\
用户正在为预告/封面视频（video_asset_kind=cover_video）写画面描述：\
开场要在 1 到 2 秒抓住注意力，节奏紧凑，可暗示钩子但不能剧透。

{_ENHANCE_CONTRACT}

只输出视频维度：subject、scene、action、camera、lighting、mood、pacing。\
pacing 在这里是开场冲击：前两秒有没有抓人的画面，整段是否拖沓。

改写硬性要求：
- 前 1 到 2 秒必须有单一、强烈的主视觉，并且尽量同时给到三个信号：\
一张脸或身体、一个运动或声音上的炸点、一句制造好奇缺口的短台词
- 从动作的中段进入，不做任何交代性铺垫。不要用「开始」「正准备」这类起始词，\
它们会让模型把前半段花在动作还没发生的状态上
- 按 duration_seconds 拆成 {ENHANCE_MIN_BEATS} 到 {ENHANCE_MAX_BEATS} 个节拍，\
每拍约 2 到 4 秒。预告是这四类里节拍最密的一种，每拍换一个画面而不是换一个故事
{_ENHANCE_VIDEO_DETAIL_RULES}
- 可以暗示剧情钩子，不要写出关键转折的具体情节，也不要出现任何交代结局的画面
- 台词只给问句不给答案，答句会关闭好奇缺口
- 在情绪或动作的最高点结束，最后一个动作在片段结束时仍在进行中，不要给收尾镜头和余波
- 竖屏优先中近景与特写，脸和关键道具留在画面中央区域，四边让给平台的按钮与进度条；\
底部留一条不放关键信息的干净带给后期字幕
- 结尾留一块干净的纯色暗场区域给后期压标题，画面内不要生成文字：\
模型渲染的可读文字几乎总是乱码字形，标题应当在后期合成
- 用作循环封面时让首帧与尾帧的构图和运动方向一致，循环处的跳变在自动重播的封面位上会被反复看到
- duration_seconds 很短时不要塞进多段情节

feedback：视觉冲击或节奏弱时点名哪里平淡或拖沓；前两秒缺少人脸或炸点时直接说缺哪一个。"""

# Selected by operation, not asset kind: a `video_to_video` request (remix
# page, script clip studio) almost always arrives as `general`, and what it
# needs is an edit instruction against footage that already exists, not the
# generic coach's 600-1200-character beat-by-beat narrative of a new clip.
# A dedicated `VideoAssetKind` coach still wins when the author picked one.
ENHANCE_SYSTEM_PROMPT_VIDEO_EDIT = f"""你是造浪平台的视频改编提示词教练。\
用户正在基于一段已有视频（operation=video_to_video）写修改要求：原片已经决定了大部分画面，\
这段文字要说清楚改哪里、改成什么、哪些保持原样，而不是重新讲一遍整段故事。

{_ENHANCE_CONTRACT}

只输出视频维度：subject、scene、action、camera、lighting、mood、pacing，含义按改编来理解：\
subject 是要改的对象，具体到哪个人、哪件物、画面哪个位置；action 是操作本身——添加、移除、\
替换还是修改；camera 是机位与运镜是沿用原片还是有意改变；pacing 是生效区间，全片还是某一段。\
对象说不清是谁、操作只有「改一下」「优化」这类词时就是 weak。

改写硬性要求：
- 每一处修改写成「把 A 改成 B」：点名原片里的对象 A，写清要变成的样子 B。\
「换个风格」「换件衣服」缺了 B，模型只能自己猜
- 写清生效区间：全片，或者用「约 X 到 Y 秒」标出一段；不写区间时模型往往整片重绘
- 用一句正向陈述列出保持原样的部分，例如「人物身份、动作节奏、机位与背景保持与原片一致」——\
只说要改什么，没被点名的部分也会跟着漂移
- 移除某个元素时，写明空出来的地方按原片的透视、光线和遮挡关系补成合理的背景
- 风格或氛围迁移时，分开写借原片的哪几项（运动轨迹、机位、节奏、构图）和换成什么\
（材质、色调、时代、媒介），两类各列具体项
- 一次改动控制在一到两处。改动越多，原片能保住的部分越少；要大改时在 feedback 里建议\
改用文生视频重新生成
- 篇幅以说清楚为准，通常两到五句就够；不要补写原片里已有的情节、外貌和场景描述，\
那些信息模型从原片里直接看得到，重复写反而会被当成新的修改要求
- has_reference 为 true 时，其余参考图只用来说明 B 的样子，写明「图N 只用于……的外观」

feedback：对象或目标写得模糊时点名缺的是 A 还是 B；改动过多时直接建议拆成两次。"""

_VIDEO_ENHANCE_SYSTEM_PROMPTS: dict[str, str] = {
    "character_action": ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION,
    "transition_video": ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO,
    "cover_video": ENHANCE_SYSTEM_PROMPT_COVER_VIDEO,
}


def _enhance_system_prompt(asset_kind: str, operation: str) -> str:
    """The code-level coach for this polish: the asset kind's dedicated coach,
    else the video-edit coach for `video_to_video`, else the generic one."""
    return (
        _ENHANCE_SYSTEM_PROMPTS.get(asset_kind)
        or _VIDEO_ENHANCE_SYSTEM_PROMPTS.get(asset_kind)
        or (ENHANCE_SYSTEM_PROMPT_VIDEO_EDIT if operation == "video_to_video" else "")
        or ENHANCE_SYSTEM_PROMPT
    )


def enhance_prompt(
    session: Session,
    *,
    prompt: str,
    max_length: int,
    operation: str = "",
    aspect_ratio: str = "",
    duration_seconds: int | None = None,
    quality_tier: str = "",
    style_hint: str = "",
    has_reference: bool = False,
    direction: str = "",
    instruction: str = "",
    asset_kind: str = "",
    script_segment: dict | None = None,
    question_answers: dict[str, Any] | None = None,
    reference_skills: list[dict[str, str]] | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    asset_presets: dict[str, Any] | None = None,
) -> AgentOutcome:
    """Diagnoses a scene description dimension by dimension, then rewrites it.

    The generation context is passed through rather than left to the model's
    imagination: the same sentence needs different advice at 4 seconds than at
    15, and camera direction is noise on a still image.

    `asset_kind` is the job's `ImageAssetKind` (`character`/`scene`/`prop`/
    `general`; a historic `cover` polishes as general) or `VideoAssetKind` (`character_action`/
    `transition_video`/`cover_video`/`general`) value, whichever axis is
    active — empty for an audio polish, and the two never collide (see
    `VideoAssetKind`'s docstring). Routing goes through
    `agent_skills.service.resolve_copy_agent_id`: a dedicated default for a
    client-facing asset kind wins, everything else (including `general`)
    lands on the `copy` request bucket. The specialised system prompt
    (image: `_ENHANCE_SYSTEM_PROMPTS`; video: `_VIDEO_ENHANCE_SYSTEM_PROMPTS`;
    a `video_to_video` with no dedicated kind: `ENHANCE_SYSTEM_PROMPT_VIDEO_EDIT`,
    see `_enhance_system_prompt`) is still the code-level fallback, so the
    extra diagnostic rules apply even before an operator has published a
    matching `AgentSkill`.

    The fallback keeps the caller's own text rather than a static placeholder,
    so a degraded model call never empties the field it was meant to improve.
    Callers still have to treat `outcome.degraded` as a failure — the echoed
    text is not a polish (see `app.domain.prompts.enhance`).

    `reference_skills` is what `app.agents.skill_matcher` found for this
    story (`prompts.matched_reference_skills` runs it), passed in rather than
    resolved here so the SSE route can tell the panel it is matching before
    the polish stream starts. It reaches the model as reference material
    only, and is echoed back on `outcome.data["referenced_skills"]`.
    """
    resolved_agent_id = agent_skills_service.resolve_copy_agent_id(
        session, asset_kind=asset_kind, agent_id=agent_id
    )
    enhance_system_prompt = _enhance_system_prompt(asset_kind, operation)
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=enhance_system_prompt,
        user_prompt=_enhance_user_prompt(
            prompt=prompt,
            operation=operation,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            quality_tier=quality_tier,
            style_hint=style_hint,
            has_reference=has_reference,
            direction=direction,
            instruction=instruction,
            max_length=max_length,
            asset_kind=asset_kind,
            script_segment=script_segment,
            question_answers=question_answers,
            reference_skills=reference_skills,
            asset_presets=asset_presets,
        ),
        fallback=_enhance_fallback(prompt, script_segment),
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=ENHANCE_SLOT,
        max_tokens=ENHANCE_MAX_TOKENS,
        temperature=ENHANCE_TEMPERATURE,
    )
    return _sanitize_enhance_outcome(
        outcome,
        prompt=prompt,
        max_length=max_length,
        asset_kind=asset_kind,
        script_segment=script_segment,
        session=session,
        operation=operation,
        reference_skills=reference_skills,
        asset_presets=asset_presets,
    )


def stream_enhance_prompt(
    session: Session,
    *,
    prompt: str,
    max_length: int,
    operation: str = "",
    aspect_ratio: str = "",
    duration_seconds: int | None = None,
    quality_tier: str = "",
    style_hint: str = "",
    has_reference: bool = False,
    direction: str = "",
    instruction: str = "",
    asset_kind: str = "",
    script_segment: dict | None = None,
    question_answers: dict[str, Any] | None = None,
    reference_skills: list[dict[str, str]] | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    asset_presets: dict[str, Any] | None = None,
) -> tuple[Iterator[StreamChunk], Callable[[Session | None], AgentOutcome]]:
    """HTTP-SSE counterpart to `enhance_prompt`."""
    resolved_agent_id = agent_skills_service.resolve_copy_agent_id(
        session, asset_kind=asset_kind, agent_id=agent_id
    )
    enhance_system_prompt = _enhance_system_prompt(asset_kind, operation)
    user_prompt = _enhance_user_prompt(
        prompt=prompt,
        operation=operation,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        quality_tier=quality_tier,
        style_hint=style_hint,
        has_reference=has_reference,
        direction=direction,
        instruction=instruction,
        max_length=max_length,
        asset_kind=asset_kind,
        script_segment=script_segment,
        question_answers=question_answers,
        reference_skills=reference_skills,
        asset_presets=asset_presets,
    )
    fallback = _enhance_fallback(prompt, script_segment)
    chunks, finalize = run_agent_stream(
        session,
        agent_name=AgentName.COPY,
        system_prompt=enhance_system_prompt,
        user_prompt=user_prompt,
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=ENHANCE_SLOT,
        max_tokens=ENHANCE_MAX_TOKENS,
        temperature=ENHANCE_TEMPERATURE,
        expect_json=True,
        is_usable=_enhance_text_is_usable,
        retry_nudge=ENHANCE_RETRY_NUDGE,
    )

    def finish(persist_session: Session | None = None) -> AgentOutcome:
        stream = finalize(persist_session)
        parsed = _parse_enhance_json(stream.raw_text, stream.thinking)
        parse_failed = parsed is None
        if parse_failed:
            _mark_enhance_run_failed(persist_session, stream.agent_run_id)
        data = dict(parsed) if parsed is not None else dict(fallback)
        outcome = AgentOutcome(
            data=data,
            raw_text=stream.raw_text,
            degraded=parse_failed or stream.degraded,
            model=stream.model,
            agent_run_id=stream.agent_run_id,
            thinking=stream.thinking,
        )
        return _sanitize_enhance_outcome(
            outcome,
            prompt=prompt,
            max_length=max_length,
            asset_kind=asset_kind,
            script_segment=script_segment,
            session=persist_session,
            operation=operation,
            reference_skills=reference_skills,
            asset_presets=asset_presets,
        )

    return chunks, finish


def _parse_enhance_json(*parts: str) -> dict[str, Any] | None:
    """Finds an enhance-shaped object, not the first `{...}` in the trace.

    glm-5.3-flash thinking narrates the harness (`{"answer":"$your_answer"}`)
    before it ever writes `prompt` / `detail_level`. A bare `extract_json`
    treated that decoy as success and the sanitizer echoed the author's
    text back as a polish.
    """
    for part in parts:
        if not part:
            continue
        parsed = extract_json(strip_thinking(part), required_keys=ENHANCE_JSON_KEYS)
        if parsed is not None:
            return parsed
        parsed = extract_json(part, required_keys=ENHANCE_JSON_KEYS)
        if parsed is not None:
            return parsed
    return None


def _enhance_text_is_usable(text: str) -> bool:
    """`is_usable` gate for a recovered reasoning-only polish pass.

    Same contract as `_script_text_is_usable`: thinking prose that never
    resolves into an enhance-shaped JSON object must trigger one budget
    expansion, not be handed back as a successful `result.text`.
    """
    return _parse_enhance_json(text) is not None


def _mark_enhance_run_failed(session: Session | None, agent_run_id: str) -> None:
    """`run_agent_stream` records success before the caller parses JSON."""
    if session is None:
        return
    run = session.get(AgentRun, agent_run_id)
    if run is None:
        return
    run.degraded = True
    run.degrade_reason = "json_parse_failed"
    run.status = AgentRunStatus.FAILED


def _enhance_user_prompt(
    *,
    prompt: str,
    operation: str,
    aspect_ratio: str,
    duration_seconds: int | None,
    quality_tier: str,
    style_hint: str,
    has_reference: bool,
    direction: str,
    instruction: str,
    max_length: int,
    asset_kind: str = "",
    script_segment: dict | None = None,
    question_answers: dict[str, Any] | None = None,
    reference_skills: list[dict[str, str]] | None = None,
    asset_presets: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "prompt": prompt,
        "operation": operation,
        "aspect_ratio": aspect_ratio,
        "duration_seconds": duration_seconds,
        "quality_tier": quality_tier,
        "style_hint": style_hint,
        "has_reference": has_reference,
        "direction": direction,
        "instruction": instruction,
        "max_length": max_length,
        "output_now": (
            "立即输出完整 JSON（必须含 prompt 与 detail_level）。"
            '思考不要讨论输出格式，不要写 {"answer": ...} 占位。'
            "可见内容的第一个字符必须是 {。"
        ),
    }
    if script_segment is not None:
        payload["script_segment"] = script_segment
    if reference_skills:
        # Title + description only. The `id` the matcher works in is
        # bookkeeping for the panel's badges, and handing it to the model
        # would just invite it to quote one.
        payload["reference_skills"] = [
            {"title": entry["title"], "description": entry["description"]}
            for entry in reference_skills
        ]
    if question_answers:
        payload["question_answers"] = question_answers
    preset_labels = _asset_preset_labels(asset_presets)
    if preset_labels:
        # The studio's expression / scene-preset picks: already written into
        # the job by `prompt_builder`, so the coach must polish *around*
        # them — never re-decide the light, damage level, era or expressions.
        payload["asset_presets"] = preset_labels
        payload["asset_presets_rule"] = (
            "asset_presets 是用户已选定的预设，生成时会由系统自动写入；"
            "改写不得与之矛盾，也不必重复罗列。"
        )
    if asset_kind == "scene":
        # The space-type pack the scene coach polishes against, plus the
        # option list for its own "which space is this" question — see
        # `app.agents.scene_skills` for why this rides the user message
        # rather than the system prompt.
        answered_space = question_answers.get("space_type") if question_answers else None
        skill = scene_skills.resolve_scene_skill(
            prompt, answered_space if isinstance(answered_space, str) else None
        )
        payload["scene_skill"] = scene_skills.as_payload(skill)
        payload["space_type_options"] = scene_skills.skill_options()
    return json.dumps(payload, ensure_ascii=False)


def _enhance_fallback(prompt: str, script_segment: dict | None) -> dict[str, Any]:
    fallback: dict[str, Any] = {"prompt": prompt, "detail_level": "adequate", "feedback": ""}
    if script_segment is not None:
        fallback["script_segment"] = script_segment
    return fallback


# Written back when polish collapses a character sheet to a single standing
# portrait. Shorter than `nodes._CHARACTER_SHEET_LAYOUT_SUFFIX` so it still
# fits the studio textarea; submit still appends the planner suffix.
CHARACTER_SHEET_LAYOUT_SENTENCE = (
    "单张角色设定图、左右分栏：左侧全身三视图（正面、侧面、背面），"
    "右侧面部特写、服装配饰细节与标准化色板；纯白背景，同一人物，单张输出。"
)
_CHARACTER_SHEET_REQUIRED = ("三视图", "色板")
_CHARACTER_SHEET_COLLAPSE_MARKERS = (
    "单一视角",
    "不拼接",
    "不分格",
    "不加特写",
    "仅此一张正面",
)
_CHARACTER_SHEET_COLLAPSE_SENTENCE = re.compile(
    r"[^。；;.]*?(?:单一视角|不拼接|不分格|不加特写|仅此一张正面)[^。；;.]*[。；;.]?"
)


def restore_character_sheet_prompt(text: str) -> str:
    """Keeps identity, strips single-view collapse clauses, restores layout.

    A live model still emitted "正面单一视角 / 不加特写与色板" after the
    sheet coach shipped — the published prompt is not enough on its own.
    """
    stripped = text.strip()
    collapsed = any(marker in stripped for marker in _CHARACTER_SHEET_COLLAPSE_MARKERS)
    if all(marker in stripped for marker in _CHARACTER_SHEET_REQUIRED) and not collapsed:
        return stripped
    cleaned = _CHARACTER_SHEET_COLLAPSE_SENTENCE.sub("", stripped)
    cleaned = re.sub(r"[。；;.]{2,}", "。", cleaned).strip(" \t\n。；;.")
    if all(marker in cleaned for marker in _CHARACTER_SHEET_REQUIRED) and not any(
        marker in cleaned for marker in _CHARACTER_SHEET_COLLAPSE_MARKERS
    ):
        return f"{cleaned}。" if cleaned and not cleaned.endswith("。") else cleaned
    if cleaned:
        return f"{cleaned}。{CHARACTER_SHEET_LAYOUT_SENTENCE}"
    return CHARACTER_SHEET_LAYOUT_SENTENCE


# An expression image is a grid of head-and-shoulders close-ups, never a
# sheet: the character coach (and `CHARACTER_SHEET_PROMPT_HINT` the studio
# may still have in the textarea) pull toward 三视图/色板, which the builder
# then has to fight. Sentences carrying those markers are dropped.
EXPRESSION_SHEET_SENTENCE = (
    "单张表情合集图：同一人物的头肩特写宫格，每格一种表情，纯色背景，画面无文字。"
)
EXPRESSION_SINGLE_SENTENCE = "单人头肩特写，纯色背景，画面无文字。"
_EXPRESSION_SHEET_MARKER_SENTENCE = re.compile(
    r"[^。；;.]*?(?:三视图|设定图|色板|左右分栏|全身站姿)[^。；;.]*[。；;.]?"
)


def restore_expression_prompt(text: str, *, count: int) -> str:
    """Strips character-sheet layout clauses and keeps one expression-layout
    sentence; the per-cell expressions themselves come from the builder."""
    cleaned = _EXPRESSION_SHEET_MARKER_SENTENCE.sub("", text.strip())
    cleaned = re.sub(r"[。；;.]{2,}", "。", cleaned).strip(" \t\n。；;.")
    sentence = EXPRESSION_SHEET_SENTENCE if count > 1 else EXPRESSION_SINGLE_SENTENCE
    marker = "表情合集" if count > 1 else "特写"
    if marker in cleaned:
        return f"{cleaned}。" if cleaned else sentence
    return f"{cleaned}。{sentence}" if cleaned else sentence


# An identity portrait (定妆照) is one clean head-and-shoulders face, never a
# sheet — same tug-of-war with the character coach as the expression image.
IDENTITY_PORTRAIT_SENTENCE = "单人正面头肩定妆照，中性表情，纯色背景，画面无文字。"


def restore_identity_portrait_prompt(text: str) -> str:
    """Strips character-sheet layout clauses and keeps one portrait sentence;
    the full portrait layout itself comes from the builder."""
    cleaned = _EXPRESSION_SHEET_MARKER_SENTENCE.sub("", text.strip())
    cleaned = re.sub(r"[。；;.]{2,}", "。", cleaned).strip(" \t\n。；;.")
    if "定妆照" in cleaned:
        return f"{cleaned}。" if cleaned else IDENTITY_PORTRAIT_SENTENCE
    return f"{cleaned}。{IDENTITY_PORTRAIT_SENTENCE}" if cleaned else IDENTITY_PORTRAIT_SENTENCE


def _asset_preset_labels(asset_presets: dict[str, Any] | None) -> dict[str, str]:
    """`{"表情": "冷笑/隐忍", "光照": "黄昏", …}` for the coach's user message."""
    if not asset_presets:
        return {}
    from app.domain.image_assets import vocabulary as vocab

    labels: dict[str, str] = {}
    if asset_presets.get("character_portrait"):
        labels["输出"] = "定妆照（正面头肩照，中性表情）"
    expressions = asset_presets.get("character_expressions")
    if isinstance(expressions, list):
        names = [
            vocab.EXPRESSION_PRESETS[str(key)].label
            for key in expressions
            if str(key) in vocab.EXPRESSION_PRESETS
        ]
        if names:
            labels["表情"] = "/".join(names)
    axis_names = {"lighting": "光照", "weather": "天气", "state": "状态", "period": "时期"}
    for axis, key in vocab.scene_presets_from(asset_presets).items():
        labels[axis_names[axis]] = vocab.SCENE_PRESET_TABLES[axis][key].label
    return labels


# Written back when polish stacks mutually exclusive cameras or offers a
# split interior/exterior. The empty-plate coach forbids those phrases;
# a live model still emitted them on a closed-door rental landing.
SCENE_PLATE_LOCK_SENTENCE = "单一机位、单一连续空间，遮挡后的房间不得画成完全可见。"
_SCENE_PLATE_SPLIT_MARKERS = (
    "分割构图",
    "分屏",
    "左右分割",
    "拼贴构图",
    "或侧视",
    "或分割",
)
_SCENE_PLATE_PAREN_OR = re.compile(r"[（(]或[^）)]{0,24}[）)]")
_SCENE_PLATE_OR_ALT = re.compile(r"或(?:侧视角度|侧视|分割构图)")
_SCENE_PLATE_SPLIT_TOKEN = re.compile(r"分割构图|分屏|左右分割|拼贴构图")

# Deleting the split clauses is not enough on its own. The live failure that
# produced the open-door render kept describing a kitchen's dishes and steam
# *behind a door it had just called closed* — physically impossible, so the
# image model resolved the contradiction by removing the door. Nouns cannot
# be cut out mid-sentence without producing broken Chinese, so the seatbelt
# appends the rule instead and lets the prompt itself do the real work.
SCENE_PLATE_OCCLUSION_SENTENCE = "遮挡后的空间只以门缝漏出的光色呈现，不得画出遮挡后的任何物体。"
_SCENE_PLATE_CLOSED_MARKERS = ("紧闭", "关着的门", "闭合的门", "关闭的门", "门扇紧合")
_SCENE_PLATE_BEHIND_MARKERS = (
    "走廊",
    "厨房",
    "碗碟",
    "水槽",
    "电视",
    "室内",
    "屋内",
    "家具",
    "房间内",
)

# The scene coach has no medium lock of its own before this change, which is
# how "老旧出租屋" came back as an illustration. Mirrors the character side's
# `真人写实影视短剧造型` default rather than inventing a second wording.
SCENE_PLATE_MEDIUM_SENTENCE = "真人写实影视短剧实拍质感。"
_SCENE_PLATE_MEDIUM_MARKERS = (
    "真人",
    "写实",
    "实拍",
    "影视",
    "摄影",
    "电影感",
    "动漫",
    "二次元",
    "插画",
    "卡通",
    "渲染",
)


def _append_sentence(text: str, sentence: str) -> str:
    if sentence in text:
        return text
    body = text.rstrip()
    if body and not body.endswith(("。", "！", "？", ".", "!", "?")):
        body = f"{body}。"
    return f"{body}{sentence}"


def enforce_scene_plate_occlusion(text: str) -> str:
    """Pins the rule back on when a closed occluder still has a room behind it."""
    if not any(marker in text for marker in _SCENE_PLATE_CLOSED_MARKERS):
        return text
    if not any(marker in text for marker in _SCENE_PLATE_BEHIND_MARKERS):
        return text
    return _append_sentence(text, SCENE_PLATE_OCCLUSION_SENTENCE)


def enforce_scene_plate_medium(text: str) -> str:
    """Locks the visual medium when the polish never named one."""
    if any(marker in text for marker in _SCENE_PLATE_MEDIUM_MARKERS):
        return text
    return _append_sentence(text, SCENE_PLATE_MEDIUM_SENTENCE)


def restore_scene_plate_prompt(text: str) -> str:
    """Strips split-view / alternative-camera clauses from a scene plate.

    A live polish still emitted "透过门缝或侧视角度" and "门外楼道视角（或分割构图）"
    after the empty-plate coach shipped — those phrases force the image model
    to open a closed door or paint interior and exterior as a split screen.
    """
    stripped = text.strip()
    if not any(marker in stripped for marker in _SCENE_PLATE_SPLIT_MARKERS):
        return stripped
    cleaned = _SCENE_PLATE_PAREN_OR.sub("", stripped)
    cleaned = _SCENE_PLATE_OR_ALT.sub("", cleaned)
    cleaned = _SCENE_PLATE_SPLIT_TOKEN.sub("", cleaned)
    cleaned = re.sub(r"[（(]\s*[）)]", "", cleaned)
    cleaned = re.sub(r"[、，,]{2,}", "，", cleaned)
    cleaned = re.sub(r"[。；;.]{2,}", "。", cleaned)
    cleaned = re.sub(r"\s{2,}", "", cleaned)
    cleaned = cleaned.strip(" \t\n。；;.")
    if not cleaned:
        return SCENE_PLATE_LOCK_SENTENCE
    if not cleaned.endswith("。"):
        cleaned = f"{cleaned}。"
    if SCENE_PLATE_LOCK_SENTENCE in cleaned:
        return cleaned
    return f"{cleaned}{SCENE_PLATE_LOCK_SENTENCE}"


def _sanitize_script_segment(raw: Any, original: dict | None) -> dict | None:
    """In-place polish only: same length, same types, original characters.

    A model that inserts a breakpoint, drops a block, or changes `type`
    would shift `{heading}#{ordinal}` on the script page — fall back to the
    request segment rather than write that back.
    """
    if original is None:
        return None
    original_blocks = original.get("blocks")
    if not isinstance(original_blocks, list):
        return original
    heading = str(original.get("heading") or "")[:MAX_HEADING_LEN]
    if not isinstance(raw, dict):
        return {"heading": heading, "blocks": list(original_blocks)}
    raw_blocks = raw.get("blocks")
    if not isinstance(raw_blocks, list) or len(raw_blocks) != len(original_blocks):
        return {"heading": heading, "blocks": list(original_blocks)}
    blocks: list[dict[str, Any]] = []
    for item, current in zip(raw_blocks, original_blocks, strict=True):
        if not isinstance(current, dict):
            return {"heading": heading, "blocks": list(original_blocks)}
        current_type = str(current.get("type") or "")
        if current_type not in ("scene", "action", "camera", "dialogue"):
            return {"heading": heading, "blocks": list(original_blocks)}
        if not isinstance(item, dict) or str(item.get("type") or "") != current_type:
            return {"heading": heading, "blocks": list(original_blocks)}
        text = str(item.get("text") or "").strip()[:MAX_TEXT_LEN] or str(current.get("text") or "")
        blocks.append(
            {
                "type": current_type,
                "character": current.get("character"),
                "text": text,
            }
        )
    return {"heading": heading, "blocks": blocks}


def _sanitize_enhance_outcome(
    outcome: AgentOutcome,
    *,
    prompt: str,
    max_length: int,
    asset_kind: str = "",
    script_segment: dict | None = None,
    session: Session | None = None,
    operation: str = "",
    reference_skills: list[dict[str, str]] | None = None,
    asset_presets: dict[str, Any] | None = None,
) -> AgentOutcome:
    enhanced = str(outcome.data.get("prompt") or "").strip() or prompt
    expressions = (asset_presets or {}).get("character_expressions")
    portrait = bool((asset_presets or {}).get("character_portrait"))
    if asset_kind == "character" and portrait:
        restored = restore_identity_portrait_prompt(enhanced)
        if restored != enhanced:
            note = "已去掉设定图版式，保持单张定妆照。"
            existing = str(outcome.data.get("feedback") or "").rstrip()
            if note not in existing:
                outcome.data["feedback"] = f"{existing} {note}".strip()
            enhanced = restored
    elif asset_kind == "character" and expressions:
        restored = restore_expression_prompt(enhanced, count=len(expressions))
        if restored != enhanced:
            note = "已去掉设定图版式，保持表情合集图。"
            existing = str(outcome.data.get("feedback") or "").rstrip()
            if note not in existing:
                outcome.data["feedback"] = f"{existing} {note}".strip()
            enhanced = restored
    elif asset_kind == "character":
        restored = restore_character_sheet_prompt(enhanced)
        if restored != enhanced:
            note = "已补回左三视图 + 右特写与色板，保持单张设定图。"
            existing = str(outcome.data.get("feedback") or "").rstrip()
            if note not in existing:
                outcome.data["feedback"] = f"{existing} {note}".strip()
            enhanced = restored
    elif asset_kind == "scene":
        restored = restore_scene_plate_prompt(enhanced)
        if restored != enhanced:
            note = "已收成单一机位，去掉分割构图。"
            existing = str(outcome.data.get("feedback") or "").rstrip()
            if note not in existing:
                outcome.data["feedback"] = f"{existing} {note}".strip()
            enhanced = restored
        occluded = enforce_scene_plate_occlusion(enhanced)
        if occluded != enhanced:
            note = "已锁死遮挡：门后只留漏光，不画门后的东西。"
            existing = str(outcome.data.get("feedback") or "").rstrip()
            if note not in existing:
                outcome.data["feedback"] = f"{existing} {note}".strip()
            enhanced = occluded
        enhanced = enforce_scene_plate_medium(enhanced)
    outcome.data["prompt"] = enhanced[:max_length]
    detail_level = str(outcome.data.get("detail_level") or "adequate")
    outcome.data["detail_level"] = detail_level if detail_level in DETAIL_LEVELS else "adequate"
    outcome.data["feedback"] = str(outcome.data.get("feedback") or "")[:MAX_FEEDBACK_LENGTH]
    outcome.data["dimensions"] = _sanitize_dimensions(outcome.data.get("dimensions"))
    outcome.data["additions"] = _sanitize_additions(outcome.data.get("additions"))
    outcome.data["questions"] = agent_questions.sanitize_questions(outcome.data.get("questions"))
    if session is not None and operation:
        updated_prompt, applied_format_skills = skill_library_service.apply_matching_format_skills(
            session,
            operation=operation,
            dimensions=outcome.data["dimensions"],
            prompt=str(outcome.data["prompt"]),
            max_length=max_length,
        )
        outcome.data["prompt"] = updated_prompt
        outcome.data["applied_format_skills"] = applied_format_skills
    else:
        outcome.data["applied_format_skills"] = []
    # Echoed back rather than re-derived: what the caller matched is what the
    # model was shown, and the panel's badges have to name exactly those.
    # Unlike `applied_format_skills` these were never appended to the text —
    # they were reference material, and the model decided what to take.
    outcome.data["referenced_skills"] = [
        {"id": entry["id"], "title": entry["title"]} for entry in (reference_skills or [])
    ]
    sanitized_segment = _sanitize_script_segment(outcome.data.get("script_segment"), script_segment)
    if sanitized_segment is None:
        outcome.data.pop("script_segment", None)
    else:
        outcome.data["script_segment"] = sanitized_segment
    return outcome


def _sanitize_dimensions(raw: Any) -> list[dict[str, str]]:
    """Keeps only known `(key, status)` pairs, first occurrence wins.

    An unknown key would reach the panel as an untranslated label, and a
    duplicate would render the same row twice — both are worse than dropping
    whatever the model improvised.
    """
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    dimensions: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        status = str(item.get("status") or "").strip()
        if key not in DIMENSION_KEYS or status not in DIMENSION_STATUSES or key in seen:
            continue
        seen.add(key)
        dimensions.append(
            {
                "key": key,
                "status": status,
                "hint": str(item.get("hint") or "").strip()[:MAX_DIMENSION_HINT_LENGTH],
            }
        )
        if len(dimensions) == MAX_DIMENSIONS:
            break
    return dimensions


def _sanitize_additions(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    additions: list[str] = []
    for item in raw:
        text = str(item).strip()[:MAX_ADDITION_LENGTH]
        if text:
            additions.append(text)
        if len(additions) == MAX_ADDITIONS:
            break
    return additions


CLARIFY_SLOT = "clarify"

# Re-exported from `app.agents.questions`, which owns the shape all three
# question-asking slots share (this one, the copy agent's own `clarify`, and
# the scene coach's polish-time follow-ups).
QUESTION_KINDS = agent_questions.QUESTION_KINDS
MAX_CLARIFY_QUESTIONS = agent_questions.MAX_QUESTIONS
MAX_CLARIFY_OPTIONS = agent_questions.MAX_OPTIONS

CLARIFY_SYSTEM_PROMPT = f"""你是造浪平台的短剧创作顾问，
在用户提交生成请求之前判断这段画面描述是否需要补充信息。
规则：
- 只有在缺少主体、场景、动作、镜头这几类关键信息之一，且缺失会明显影响生成质量时才提问
- 描述已经具体、可以直接生成时，needs_clarification 为 false，questions 为空数组
- 每个问题只问一件事，问题数量不超过 {MAX_CLARIFY_QUESTIONS} 个，按对生成质量的影响从高到低排序
- kind 为 single_choice 或 multi_choice 时必须给 2 到 {MAX_CLARIFY_OPTIONS} 个具体、互斥或可组合的
  选项，不要给「其他」这类空泛选项
- kind 为 free_text 时 options 留空数组
- required 表示这个问题是否必须回答才能保证质量，不是强制用户必须点开
- 问题与选项用用户输入的语言书写

{JSON_INSTRUCTION}
格式：{{"needs_clarification": boolean, "questions": [{{"id": string,
"kind": "single_choice"|"multi_choice"|"free_text", "prompt": string,
"options": [{{"value": string, "label": string}}], "required": boolean}}]}}"""

CLARIFY_FALLBACK: dict[str, Any] = {"needs_clarification": False, "questions": []}


def clarify(
    session: Session,
    *,
    prompt: str,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    """Judges whether a scene description needs the author's input before generating.

    The fallback never blocks submission: a degraded or unparseable model call
    yields `needs_clarification=False`, so a gateway hiccup never becomes a
    dead end for the author.
    """
    resolved_agent_id = agent_skills_service.resolve_copy_agent_id(session, agent_id=agent_id)
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=CLARIFY_SYSTEM_PROMPT,
        user_prompt=json.dumps({"prompt": prompt}, ensure_ascii=False),
        fallback=dict(CLARIFY_FALLBACK),
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=CLARIFY_SLOT,
    )
    outcome.data["questions"] = agent_questions.sanitize_questions(outcome.data.get("questions"))
    outcome.data["needs_clarification"] = bool(outcome.data.get("needs_clarification")) and bool(
        outcome.data["questions"]
    )
    return outcome


# --- Script writing (剧本创作) -----------------------------------------
#
# Unlike `suggest`/`enhance`/`clarify` above, these two slots stream and do
# not return one JSON blob: the model is asked for a short prose summary
# (shown as the chat bubble) followed by a fenced ```json block holding the
# *entire* script document (not a diff). `run_agent_stream` has no notion of
# `fallback`/JSON-mode, so extraction and validation of the fenced block
# happens here, once the stream is fully drained.

SCRIPT_DRAFT_SLOT = "script_draft"
SCRIPT_REVISE_SLOT = "script_revise"

# A full scene-by-scene script (summary + fenced JSON for several scenes,
# each with several color blocks) routinely runs past the generic 2048
# fallback, the same reasoning `ENHANCE_MAX_TOKENS` documents for a much
# smaller payload. This is a slot *request*, not a hard ceiling: the serving
# endpoint's own `max_output_tokens`/`context_length` still cap it
# (`LlmProviderEndpoint.output_budget`), and a reasoning model's *first*
# attempt is still this slot request, not the endpoint's entire declared
# ceiling — only a truncated/unusable first pass expands the budget from
# here (see `_stream_complete_from_endpoints`'s retry, gated by
# `_script_text_is_usable` below).
SCRIPT_MAX_TOKENS = 8192

SCRIPT_JSON_SHAPE = (
    '{"title": string, "logline": string, '
    '"characters": [{"name": string, "traits": string}], '
    '"scenes": [{"heading": string, "blocks": '
    '[{"type": "scene"|"action"|"camera"|"dialogue"|"breakpoint", '
    '"character": string|null, "text": string}]}]}'
)

# Shared between the draft and revise prompts so a color block's meaning
# never drifts between a script's first turn and a later revision turn.
# `scene`'s "no people, ever" rule exists because this exact text is what
# `script-document-view.tsx::sceneImagePrompt` seeds the "生成场景图" jump-out
# with verbatim — a scene block that mixes in a character produces a seed
# prompt the scene-asset pipeline (`planner._ASSET_KIND_BRIEF[SCENE]`) then
# has to strip back out, so it's cheaper to never write it in the first place.
# (Vidu's own image-input guide independently requires the same thing of
# environment shots, which is a useful sanity check on the rule rather than
# its origin.)
#
# Every block's writing rule below is downstream of one that a video model
# will actually be asked to honour later, so they are phrased the way
# `docs/video-prompt-formats.md` found vendors phrase them: a `camera` block
# splits framing from movement because Kling's guide explicitly separates
# 「镜头语言」from movement control and the two drift apart when written as
# one phrase; an `action` block is capped at one beat because five vendors
# state officially that stacked actions produce deformation.
_BLOCK_TYPE_RULES = f"""- type 含义与写法：
  - scene：纯静态环境/氛围描述，只写空间本身——建筑或地貌结构、光线、色调、天气、陈设；\
不能出现任何人物（含背影、剪影、局部肢体或人群痕迹）、动作或对话内容。这段文字会被直接当作\
生成场景图的素材使用，混入人物或动作会导致场景图跑出不该出现的角色。光线要点名来源和方向\
（「左侧高窗斜射的冷白日光」而不是「光线很有氛围」），同一场戏的所有 scene 色块沿用同一个\
主光方向和色温
  - action：一个色块只写一个连续的动作节拍（有清楚起止的一个动作），不要把多个动作或场景切换\
揉进同一个色块；能数得出来的动作就写清次数与幅度（「敲三下桌面」「后退两步」「翻两页」），\
这样后续生成时动作的时长与边界都是确定的。情绪一律外化成看得见的生理信号，写「肩膀微颤，\
手指攥紧衣角，眼眶泛红」而不是「悲伤」，写「频繁看表，指节敲桌，眼神闪躲」而不是「紧张」；\
「情绪爆发」「气氛紧张」这类词模型画不出来，一个都不要留
  - camera：分两段写，先景别、再运镜，两段之间不要互相混写。景别用固定术语\
（大远景/远景/全景/中景/中近景/近景/特写/大特写），运镜写清方式＋方向＋速度\
（推/拉/摇/移/跟/环绕/升降/固定/甩镜），例如「中近景，缓慢向左平移」。一个 camera 色块只给\
一个运镜动作——需要两段运动就拆成两个色块，叠加运镜在生成时会在切换点抖动。禁止\
「镜头缓缓移动」这种没有方向的写法，也禁止「特写环绕」这种把景别和运镜挤成一个词的写法
  - dialogue：character 字段填说话人姓名，其余类型 character 为 null。同一角色从头到尾用\
完全相同的姓名写法，不要在「他」「男人」「穿风衣的男人」之间换来换去
  - breakpoint：建议的生成/剪辑切分点，不是场景内容本身
- 每一场戏必须包含至少一个 scene 色块，为这场戏保留一段可以直接拿去生成场景图的干净环境描述；\
scene 色块之外，同一场戏还要至少覆盖 action、dialogue 两类中的一类
- 拆分粒度：同一时间点内不同的动作、镜头切换、对话轮次都要拆成独立色块，不要为了减少色块数量把\
几件事挤进同一句话里——细粒度色块是为了让后续可以逐镜头生成与剪辑
- 所有色块都只写镜头拍得到的东西。心理活动、前情交代、角色不知道的信息一律不写进 scene/action/\
camera，要么外化成动作与道具，要么放进台词
- 每个色块都要写足到能直接拿去生成，不要写成提纲。这些文字最终会被拼成生成提示词，\
留白的地方模型会自己发明，相邻两段的发明极少能对上——这正是分段生成之后画面接不上的来源。\
单块上限 {MAX_TEXT_LEN} 字，写到接近这个量是正常的
- 同一场戏内跨色块逐字复用这几项，一个字都不要改：服装与它当前的损耗状态（湿透、破口、\
卷起的袖口）、发型状态、关键道具此刻在谁手里、主光方向与色温、人物之间的距离。\
同义改写在模型看来就是换了一组条件，这几项是画面连贯的锚点"""

# `characters[].traits` is what `script-document-view.tsx::characterImagePrompt`
# seeds the "生成角色图" jump-out with verbatim (no separate appearance field —
# this is the one and only place a character's visual gets described), so
# it must lead with a script-wide visual medium plus what a character portrait
# actually needs — appearance — rather than personality, which a text-to-image
# model has no way to render. A missing medium is what lets one cast member
# render photoreal and the next as anime.
_CHARACTER_APPEARANCE_RULE = """- characters 至少列出剧本中出现的主要角色。先为整份剧本选定\
唯一视觉媒介，再写每个角色：默认全剧「真人写实影视短剧造型」（摄影级皮肤与布料，不是动漫、\
不是插画）；仅当用户创意或参考技能明确要求二次元/动漫/日系插画时，全剧统一切到那一种。\
同一剧本里禁止部分角色写实、部分动漫，也禁止用「漫画感眼神」「二次元发型」这类词把单个角色\
拉到另一种媒介。每个角色的 traits 必须开头写同一句媒介，再写外貌特征——性别、年龄段、肤色、\
发型/发色、体型、面部或标志性穿着等，写到足以直接支撑角色立绘/角色图生成的程度，这部分不能省略、\
不能含糊；外貌之后再补充性格、人物关系等信息。\
例如「真人写实影视短剧造型，年轻女性，二十出头，肤色偏白，齐肩黑发，穿便利店店员制服；\
外冷内热，藏着不能说的秘密」而不是只写「外冷内热的便利店店员」，\
也不是「年轻女性，齐肩黑发」这种缺少媒介句、会让角色图在真人和动漫之间漂移的写法
- traits 里的外貌部分要挑稳定的静态特征（发型发色、体型、肤色、标志性穿着或配饰），\
不要写表情、姿态、当下情绪这类每个镜头都会变的东西——这段文字要在这个角色出现的每一个镜头里\
反复复用，写进可变特征等于让角色在镜头之间漂移
- 同一个角色在剧本各处被提到时，沿用 traits 里那一段完全相同的措辞，不要换成同义的另一种说法；\
模型没有「同一个人」的概念，只有「同样的描述」"""

# A single generation call can never produce more than this many seconds of
# footage (`app.platform_config.schemas.MAX_GENERATION_DURATION_SECONDS`) —
# read live so an admin lowering the platform ceiling is reflected the next
# time a script is drafted/revised, without touching this prompt text.
#
# The conversion baselines below turn "estimate the duration" from a vibe
# into arithmetic. They come from `docs/video-prompt-formats.md`'s film-craft
# section (shot size sets a shot's natural length; Chinese dialogue runs
# three to four characters a second), not from any vendor — no vendor
# documents this. Worth noting that segmenting by *numbered shot* rather than
# by second marks is what Seedance's guide recommends precisely because
# models handle exact timings badly, so this product's breakpoint mechanism
# is already on the right side of that divergence.
_BREAKPOINT_RULES = f"""- breakpoint 是建议的切分点，不是场景内容本身：character 始终为 null，\
text 用一句话说明为什么在这里切，例如「建议在此处切分：前段约 18 秒台词与动作，\
符合单条生成 ≤{MAX_GENERATION_DURATION_SECONDS} 秒上限」
- 默默给每个 scene、action、camera、dialogue 色块估算大致时长，用这套基线换算而不是凭感觉：\
台词按每秒 3 到 4 个字折算字数；镜头按景别给基线时长——远景约 10 秒、全景约 8 秒、中景约 6 秒、\
近景与特写约 4 秒；一个动作节拍通常占 2 到 4 秒
- 一旦某个场景内连续未切分的内容累计将超过 {MAX_GENERATION_DURATION_SECONDS} 秒，\
就在其后插入一个 breakpoint 色块，把这个场景拆成可以分别生成、分别剪辑的若干段
- breakpoint 优先落在自然的戏剧节拍上（一次反转、一次反应镜头、一次转场），\
不要卡在一句台词中间
- 切分点两侧的衔接要留出接口：前一段的最后一个动作做完留半秒静止，\
后一段从一个明确的入画方向或一个可对齐的构图接上，不要卡在运动最剧烈处切开
- 很短的场景可以完全不需要 breakpoint；不要为了切分而切分
- 两个 breakpoint 之间的所有色块最终会被拼成这一条片段的生成提示词，\
总长有 {PROMPT_ENHANCE_MAX_LENGTH} 字的硬上限，超出的部分会被直接截断。\
把细节写足到接近这个预算，但让每一段都留有余量——单个色块最多 {MAX_TEXT_LEN} 字，\
写不下就在同段内多开一个色块分摊，不要把某一块撑到被截断"""

# Craft rules shared by both slots, so a revision turn writing a new scene
# holds it to the same standard the draft turn did. Split out of the draft
# prompt (where the pacing bullets used to live inline) when the vertical
# short-drama findings in `docs/video-prompt-formats.md` grew past the point
# where duplicating them across two prompts was safe.
#
# The hook taxonomies and the three-lead cap are the one part of that
# document with no vendor backing at all — eleven vendors document nothing
# about opening seconds — so they come from Chinese vertical short-drama
# industry practice. The vertical-framing bullets are the reverse: Vidu and
# MiniMax both state the medium/close-shot preference officially, but only
# those two, so it is written as this platform's default rather than as
# settled fact.
_SHORT_DRAMA_CRAFT_RULES = """- 短剧节奏要快：第一场的第一个色块必须已经在建立冲突、悬念或反差，\
不能用寒暄或环境铺垫开场。开场钩子在三类里选一类落地——直接冲突型（当众打脸、甩出协议、\
被拦在门外）、强悬念型（掉落的化验单、深夜来电、对准主角的枪口）、极致反差型（婚礼现场撕破脸、\
豪门太太变弃妇）
- 每一场戏都要有一个明确的钩子或转折收尾，让人想看下一场——不要写成平铺直叙的流水账。\
收尾钩子在六类里轮换：悬念断（问题抛出未答）、危机断（威胁已至未解）、反转断（立场刚刚倒转）、\
揭示断（身份或真相刚露一角）、选择断（两难摆在面前）、情感断（关系刚刚断裂或和解未成）；\
同一类不要连续用超过两次
- 主要角色控制在 3 人以内。人物一多，观众在竖屏小屏上分不清谁是谁，直接影响看完率；\
需要更多人物时用「未露脸的声音」「只出现一次的功能性角色」承担，不要都升格成主要角色
- 每个镜头默认只安排一到两个正在说话/行动的角色。竖屏窄画幅里双人不要左右并排——\
并排会把两张脸各压到半个画幅宽，改成上下错位或过肩，让两张脸不在同一水平线上
- 竖屏优先中近景与特写，远景只用于背影、侧背或无人的环境空镜；竖屏画幅里远景的人脸只有几十像素，\
表演信息会全部丢失
- 台词要短、口语化、有潜台词，避免书面语和大段解释性独白；一句台词说不清楚就拆成前后两句；\
避免连续多轮台词都是长句陈述，适当加入打断、反问、沉默停顿，让对话有真实节奏
- 需要安静的镜头就明确写成安静（无台词、只有环境声），不要留白让后续生成环节自行补配乐或台词"""

SCRIPT_DRAFT_SYSTEM_PROMPT = f"""你是造浪平台的短剧编剧助手，深度理解竖屏短剧的叙事节奏\
与生成流水线的限制。根据用户给出的创意，直接产出一份可用于拍摄/生成的完整分场短剧剧本。

输出严格分两部分，按顺序：
第一部分：用 1 到 2 句话说明你生成了什么，这句话会直接展示给用户，不要提到 JSON 或任何技术细节。
第二部分：另起一段，用一个 ```json 代码块输出完整剧本，\
代码块内只有一个 JSON 对象，代码块外和代码块内都不要有其他文字。

剧本 JSON 格式：{SCRIPT_JSON_SHAPE}

规则：
{_BLOCK_TYPE_RULES}
- 剧本至少包含 1 到 3 个场景
{_CHARACTER_APPEARANCE_RULE}
{_SHORT_DRAMA_CRAFT_RULES}
{_BREAKPOINT_RULES}
- 如果用户提供了参考技能的风格说明，把其中的调性、氛围、叙事手法融入剧本，但不要直接照抄技能描述原文
- 如果用户输入已经是一份完整或接近完整的剧本（例如从上传文件提取的原文），按上述 JSON 结构整理，\
保留原有情节、人物与台词，只补缺失的 scene/action/camera/breakpoint 色块，不要另起炉灶重写故事；\
若输入只是一句或一小段创意，则按往常扩写成完整分场剧本
- 输出语言与用户输入保持一致"""

SCRIPT_REVISE_SYSTEM_PROMPT = f"""你是造浪平台的短剧编剧助手，正在和用户反复打磨一份剧本，\
同样需要兼顾竖屏短剧的叙事节奏与生成流水线的限制。\
你会收到当前剧本的完整内容和用户这一轮的修改意见，产出修改后的完整剧本。

输出严格分两部分，按顺序：
第一部分：用 1 到 2 句话说明这一轮改了什么，这句话会直接展示给用户，不要提到 JSON 或任何技术细节。
第二部分：另起一段，用一个 ```json 代码块输出修改后的完整剧本（是完整剧本，不是增量或补丁），\
代码块内只有一个 JSON 对象，代码块外和代码块内都不要有其他文字。

剧本 JSON 格式与当前剧本一致：{SCRIPT_JSON_SHAPE}

规则：
{_BLOCK_TYPE_RULES}
{_CHARACTER_APPEARANCE_RULE}
- 只按用户这一轮的意见调整，其余场景、角色、台词尽量原样保留，不要做用户没有要求的改写\
（包括已有角色的 traits——用户没有要求修改角色外貌/性格时原样保留，不要顺手补全或改写外貌描述）
- 用户没有要求更换画风时，所有角色 traits 开头的媒介句必须保持一致且原样保留；\
新增角色沿用当前剧本已有的那一句媒介，不要给单个角色单独换成另一种
- 用户没有要求删除的场景或角色不要删除
- 这一轮新写或改写的内容要满足下列短剧写法要求；未被这一轮意见触及的既有内容不要为了符合这些\
要求而主动改写——用户没提的地方保持原样优先于写法更优：
{_SHORT_DRAMA_CRAFT_RULES}
- 调整或新增内容后，重新检查一遍受影响场景的 breakpoint 是否仍然合理：\
新增的内容让某段超过 {MAX_GENERATION_DURATION_SECONDS} 秒时补插 breakpoint，\
删减后某个 breakpoint 不再必要时可以去掉，其余未受影响的 breakpoint 原样保留
{_BREAKPOINT_RULES}
- 如果用户提供了参考技能的风格说明，把其中的调性、氛围、叙事手法融入这一轮修改
- 输出语言与用户输入保持一致"""

SCRIPT_BLOCK_TYPES = ("scene", "action", "camera", "dialogue", "breakpoint")
MAX_SCENES = 40
MAX_BLOCKS_PER_SCENE = 60
MAX_CHARACTERS = 20
# Script props (道具) come only from the asset breakdown, never the model.
MAX_PROPS = 40
MAX_TITLE_LEN = 60
MAX_TRAITS_LEN = 300
MAX_HEADING_LEN = 80
MAX_SUMMARY_LEN = 300
# The reasoning trace persisted per turn (`EpisodeScriptTurn.thinking_text`)
# can run far longer than the visible summary/text fields above — a
# thinking model narrating its plan easily runs into the thousands of
# characters — so this gets a floor of its own rather than reusing
# `MAX_TEXT_LEN`/`MAX_SUMMARY_LEN`.
MAX_THINKING_LEN = 8000

_SCRIPT_JSON_FENCE = re.compile(r"```json\s*([\s\S]*?)```", re.IGNORECASE)


@dataclass(slots=True)
class ScriptTurnOutcome:
    summary: str
    script: dict[str, Any]
    parse_ok: bool
    degraded: bool
    model: str
    agent_run_id: str
    thinking: str = ""


def _extract_summary_and_script(raw_text: str) -> tuple[str, Any]:
    """Splits the streamed reply into its prose summary and fenced JSON body.

    Returns `(summary, parsed_or_none)` — `parsed_or_none` is whatever
    `json.loads` produced (not yet validated as a script shape) or `None`
    when no fenced block was found or it didn't parse.

    Falls back to `extract_json` (balanced-brace scanning, not just a fence
    match) when there is no ```json fence at all — a model that ignores the
    "always fence it" instruction and just emits bare JSON after its summary
    must not be treated as if it produced no script.
    """
    match = _SCRIPT_JSON_FENCE.search(raw_text)
    if not match:
        parsed = extract_json(raw_text)
        if parsed is None:
            return raw_text.strip(), None
        # `extract_json` finds the JSON wherever it starts, so whatever
        # precedes it is the prose summary — same trade-off the fenced path
        # makes below.
        prefix = raw_text[: raw_text.find("{")].strip()
        return prefix or raw_text.strip(), parsed
    summary = raw_text[: match.start()].strip()
    try:
        parsed = json.loads(match.group(1))
    except (TypeError, ValueError):
        return summary or raw_text.strip(), None
    return summary or raw_text.strip(), parsed


def _script_text_is_usable(text: str) -> bool:
    """`is_usable` gate passed to `run_agent_stream`/`stream_complete`.

    A pass recovered from reasoning-only output (the glm-5.3-flash case) is
    only worth accepting when a script can actually be found in it — plain
    "thinking out loud" prose that never reaches a JSON payload must not be
    handed back as a successful `result.text` (see `stream_complete`'s
    `is_usable` docstring for exactly when this gate fires: never once real
    `content` has streamed, only on a recovered pass).
    """
    _, parsed = _extract_summary_and_script(text)
    return _sanitize_script(parsed) is not None


def _sanitize_script(raw: Any) -> dict[str, Any] | None:
    """Validates and bounds a model-produced script document.

    Returns `None` when nothing usable survives (no scenes at all) so the
    caller can fall back to the previous version rather than overwrite it
    with an empty document.
    """
    if not isinstance(raw, dict):
        return None

    title = str(raw.get("title") or "").strip()[:MAX_TITLE_LEN]
    logline = str(raw.get("logline") or "").strip()[:MAX_TEXT_LEN]

    characters: list[dict[str, Any]] = []
    raw_characters = raw.get("characters")
    if isinstance(raw_characters, list):
        for item in raw_characters[:MAX_CHARACTERS]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:MAX_TITLE_LEN]
            if not name:
                continue
            traits = str(item.get("traits") or "").strip()[:MAX_TRAITS_LEN]
            # The model never sets this itself (it isn't told the field
            # exists) — only present when sanitizing a client-supplied
            # `current_script` that already carries a link. See
            # `_carry_over_links` for how a link survives a model turn that
            # doesn't echo it back.
            ref = item.get("character_ref_id")
            look = item.get("look_id") if ref else None
            characters.append(
                {
                    "name": name,
                    "traits": traits,
                    "character_ref_id": str(ref) if ref else None,
                    "look_id": str(look) if look else None,
                }
            )

    scenes: list[dict[str, Any]] = []
    raw_scenes = raw.get("scenes")
    if isinstance(raw_scenes, list):
        for scene in raw_scenes[:MAX_SCENES]:
            if not isinstance(scene, dict):
                continue
            heading = str(scene.get("heading") or "").strip()[:MAX_HEADING_LEN]
            if not heading:
                continue
            blocks: list[dict[str, Any]] = []
            raw_blocks = scene.get("blocks")
            if isinstance(raw_blocks, list):
                for block in raw_blocks[:MAX_BLOCKS_PER_SCENE]:
                    if not isinstance(block, dict):
                        continue
                    block_type = str(block.get("type") or "")
                    if block_type not in SCRIPT_BLOCK_TYPES:
                        continue
                    text = str(block.get("text") or "").strip()[:MAX_TEXT_LEN]
                    if not text:
                        continue
                    character = block.get("character")
                    character_name = str(character).strip()[:MAX_TITLE_LEN] if character else None
                    blocks.append({"type": block_type, "character": character_name, "text": text})
            if blocks:
                ref = scene.get("ref_id")
                variant = scene.get("variant_id") if ref else None
                scenes.append(
                    {
                        "heading": heading,
                        "blocks": blocks,
                        "ref_id": str(ref) if ref else None,
                        "variant_id": str(variant) if variant else None,
                    }
                )

    if not scenes:
        return None
    return {
        "title": title,
        "logline": logline,
        "characters": characters,
        "scenes": scenes,
        "props": sanitize_props(raw.get("props")),
    }


def sanitize_props(raw: Any) -> list[dict[str, Any]]:
    """Bounds `script_json.props` — one entry per name, ≤ `MAX_PROPS`. Like
    the character/scene links, `prop_ref_id` is kept as the caller sent it;
    only `update_links` and the breakdown apply ever set it."""
    props: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return props
    for item in raw:
        if len(props) >= MAX_PROPS:
            break
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:MAX_TITLE_LEN]
        if not name or name in seen:
            continue
        seen.add(name)
        ref = item.get("prop_ref_id")
        props.append(
            {
                "name": name,
                "description": str(item.get("description") or "").strip()[:MAX_TRAITS_LEN],
                "prop_ref_id": str(ref) if ref else None,
            }
        )
    return props


def _carry_over_links(previous: dict[str, Any], updated: dict[str, Any]) -> None:
    """Re-attaches `character_ref_id`/`ref_id`/`prop_ref_id` links from the
    pre-turn script onto the post-turn one, matched by name/heading.

    A revision turn always returns the *entire* document (`script_json` is
    always the latest turn's script — see the `zaolang-editor-drama` skill's
    script-writing reference), but the model is never told these link fields
    exist, so its own JSON output naturally omits them — without this, every
    single revision turn would silently unlink every character/scene the
    user had already connected to a reusable asset. Matching by name/heading
    rather than position is the same trade-off `PATCH .../links` makes: if
    the model renames something in the same turn, that one link is dropped
    rather than mismatched onto the wrong character/scene.
    """
    character_refs = {
        str(item.get("name")): (item.get("character_ref_id"), item.get("look_id"))
        for item in previous.get("characters") or []
        if isinstance(item, dict) and item.get("character_ref_id")
    }
    for item in updated.get("characters") or []:
        if isinstance(item, dict) and not item.get("character_ref_id"):
            ref, look = character_refs.get(str(item.get("name")), (None, None))
            if ref:
                item["character_ref_id"] = ref
                item["look_id"] = look

    scene_refs = {
        str(scene.get("heading")): (scene.get("ref_id"), scene.get("variant_id"))
        for scene in previous.get("scenes") or []
        if isinstance(scene, dict) and scene.get("ref_id")
    }
    for scene in updated.get("scenes") or []:
        if isinstance(scene, dict) and not scene.get("ref_id"):
            ref, variant = scene_refs.get(str(scene.get("heading")), (None, None))
            if ref:
                scene["ref_id"] = ref
                scene["variant_id"] = variant

    # The model is never asked for props: a revision that echoes none keeps
    # the breakdown's list whole; one that echoes them gets their links back.
    previous_props = [item for item in previous.get("props") or [] if isinstance(item, dict)]
    if not updated.get("props"):
        updated["props"] = sanitize_props(previous_props)
        return
    prop_refs = {
        str(item.get("name")): item.get("prop_ref_id")
        for item in previous_props
        if item.get("prop_ref_id")
    }
    for item in updated["props"]:
        if isinstance(item, dict) and not item.get("prop_ref_id"):
            item["prop_ref_id"] = prop_refs.get(str(item.get("name")))


def stream_draft_script(
    session: Session,
    *,
    idea: str,
    title: str = "",
    referenced_skills: list[dict[str, str]] | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[Iterator[StreamChunk], Callable[[Session | None], ScriptTurnOutcome]]:
    """Streams the first turn of a new script: idea in, full script out.

    Mirrors `run_agent_stream`'s `(chunks, finalize)` contract — the caller
    must drain `chunks` before calling `finalize()`.
    """
    resolved_agent_id = agent_skills_service.resolve_copy_agent_id(session, agent_id=agent_id)
    user_prompt = json.dumps(
        {"idea": idea, "title": title, "referenced_skills": referenced_skills or []},
        ensure_ascii=False,
    )
    chunks, finalize_run = run_agent_stream(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SCRIPT_DRAFT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=SCRIPT_DRAFT_SLOT,
        max_tokens=SCRIPT_MAX_TOKENS,
        is_usable=_script_text_is_usable,
    )

    def finalize(persist_session: Session | None = None) -> ScriptTurnOutcome:
        outcome = finalize_run(persist_session)
        summary, parsed = _extract_summary_and_script(outcome.raw_text)
        script = _sanitize_script(parsed)
        parse_ok = script is not None
        if script is None:
            script = {
                "title": (title or idea).strip()[:MAX_TITLE_LEN],
                "logline": idea.strip()[:MAX_TEXT_LEN],
                "characters": [],
                "scenes": [],
                "props": [],
            }
            if not summary:
                summary = "剧本生成失败，请换一种方式描述你的创意后重试。"
        return ScriptTurnOutcome(
            summary=summary[:MAX_SUMMARY_LEN],
            script=script,
            parse_ok=parse_ok,
            degraded=outcome.degraded,
            model=outcome.model,
            agent_run_id=outcome.agent_run_id,
            thinking=outcome.thinking[:MAX_THINKING_LEN],
        )

    return chunks, finalize


def stream_revise_script(
    session: Session,
    *,
    message: str,
    current_script: dict[str, Any],
    referenced_skills: list[dict[str, str]] | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[Iterator[StreamChunk], Callable[[Session | None], ScriptTurnOutcome]]:
    """Streams one revision turn: current script + instruction in, full
    updated script out. The fallback on parse failure is the caller's own
    `current_script`, unchanged — a degraded turn must never blank out a
    document the user has already built up over several turns."""
    resolved_agent_id = agent_skills_service.resolve_copy_agent_id(session, agent_id=agent_id)
    user_prompt = json.dumps(
        {
            "message": message,
            "current_script": current_script,
            "referenced_skills": referenced_skills or [],
        },
        ensure_ascii=False,
    )
    chunks, finalize_run = run_agent_stream(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SCRIPT_REVISE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=SCRIPT_REVISE_SLOT,
        max_tokens=SCRIPT_MAX_TOKENS,
        is_usable=_script_text_is_usable,
    )

    def finalize(persist_session: Session | None = None) -> ScriptTurnOutcome:
        outcome = finalize_run(persist_session)
        summary, parsed = _extract_summary_and_script(outcome.raw_text)
        script = _sanitize_script(parsed)
        parse_ok = script is not None
        if script is None:
            script = current_script
            if not summary:
                summary = "本轮修改未生成有效剧本，已保留上一版本，请换个方式描述修改意见。"
        else:
            _carry_over_links(current_script, script)
        return ScriptTurnOutcome(
            summary=summary[:MAX_SUMMARY_LEN],
            script=script,
            parse_ok=parse_ok,
            degraded=outcome.degraded,
            model=outcome.model,
            agent_run_id=outcome.agent_run_id,
            thinking=outcome.thinking[:MAX_THINKING_LEN],
        )

    return chunks, finalize
