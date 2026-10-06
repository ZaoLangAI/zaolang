# 视频提示词格式

这份文档是改写 `back/app/agents/copywriter.py` 里那几条教练型提示词时的事实基础，也是
`back/app/domain/skill_library/catalog.py` 里 `fmt-*` 格式预设的语料来源。改动那些提示词之前
先读这里，别凭印象写规则——本文档里有好几条被广泛传播的"官方规范"其实不是官方写的。

调研截止 2026-09-10，覆盖 11 家厂商的官方提示词文档、专业影视分镜惯例与中英文实践社区。

**证据强度标记**贯穿全文：

| 标记 | 含义 |
| --- | --- |
| 官方明文 | 一手官网/官方文档，原文已抓取核对 |
| 官方受阻 | 官方文档确认存在但页面无法抓取，内容经多处独立二手来源交叉核对 |
| 社区实践 | 实践社区、工具厂商博客或第三方整理 |
| 影视惯例 | 传统影视工业的既有做法，与 AI 模型无关 |

## 一、厂商官方字段清单

### 需要先纠正的三处传播错误

**Google Veo 的字段名。** 当前官方版本（Vertex AI prompt guide，2026-09-03）的 "Anatomy of a
prompt" 是 11 个章节：`Subject` / `Action` / `Scene or context` / `Camera angles` /
`Camera movements` / `Lens and optical effects` / `Visual style & aesthetics`（官方明说拆为
`Lighting` / `Tone or mood` / `Artistic style` / `Ambiance` 四个子成分）/ `Temporal elements` /
`Audio` / `Cinematic terms` / `Negative prompts`。

- 广泛流传的 `Cinematography + Subject + Action + Context + Style & Ambiance` **是 Luma 官方
  文档里对 Veo 的总结**，不是 Google 写的。
- 更早流传的 `shot / subject / context / action / style / camera motion / composition /
  ambiance` 是 Veo 2 时代 prompt guide 的表格列名，`composition` 现在已不是顶层字段。
- 官方对必填性的态度："You don't need to use all elements in every prompt."

**"Veo 3 JSON 提示词"不是官方规范。** 见下一节。

**三家厂商根本没有官方提示词指南。** Pika（只有 dev.pika.art 的 API 参数文档）、MiniMax
Hailuo 02（已被官方列为 Legacy，当前主力是 H3，官方只有能力页 + 示例页 + API 参考）、可灵
2.x 专属公式（官方 quickstart 指南对应 "AI video model 2.0"，无版本专属公式，也没有名为
「存稿」的官方文档）。网上流传的这三家的"公式"来自非官方站点。

### OpenAI Sora 2（官方明文）

官方 Descriptive Prompt Template 的段标签骨架：

```text
[Prose scene description in plain language.]

Cinematography:
Camera shot: [framing and angle]
Mood: [overall tone]

Actions:
- [Action 1: a clear, specific beat or gesture]
- [Action 2: another distinct beat within the clip]

Dialogue:
[short natural lines]
```

正文示例里的完整段标签：`Style:` / `Cinematography:`（下含 `Camera:`、`Lens:`、`Lighting:`、
`Mood:`）/ `Actions:` / `Background Sound:`。

超长制作简报（Going Ultra-Detailed）的官方段标签：`Format & Look` / `Lenses & Filtration` /
`Grade / Palette` / `Lighting & Atmosphere` / `Location & Framing` /
`Wardrobe / Props / Extras` / `Sound` / `Optimized Shot List` /
`Camera Notes (Why It Reads)` / `Finishing`。

官方自己不神化这套模板："This is not a one-size-fits-all recipe for success, but it gives you
a clear framework and makes it easier to be consistent."

关键约束：

- 每个镜头一个运镜 + 一个动作："Each shot should have one clear camera move and one clear
  subject action."
- 短片段更可控（反直觉）："you may see better results by stitching together two 4 second clips
  in editing instead of generating a single 8 second clip."
- 允许一条提示词写多镜头，但每个 shot block 要独立："one camera setup, one subject action,
  and one lighting recipe at a time."
- 动作写成 beats/counts。官方弱→强对照：`Actor walks across the room.` →
  `Actor takes four steps to the window, pauses, and pulls the curtain in the final second.`
- 容器参数不能写进散文："resolution, duration, and character references will not change based
  on prose like 'make it longer.'"
- 对白必须放在散文描述下方的独立块，说话人标签 + 冒号 + 引号；4 秒镜头容纳一到两轮短对白。
- Characters API：上传 2–4 秒 MP4 得到角色 ID，生成时用角色名指代，官方建议每次生成不超过
  2 个角色。
- 色板锚定："Naming three to five colors helps keep the palette stable across shots."

### Google Veo 3 / 3.1（官方明文）

字段清单见上。这一家的差异化在音频与负面提示词。

**音频三分类**（官方原文定义 + 示例）：

| 官方字段 | 官方示例 |
| --- | --- |
| `Sound effects` | "the sound of a phone ringing", "water splashing in the background" |
| `Ambient noise` | "the sounds of city traffic and distant sirens", "the quiet hum of an office" |
| `Dialogue` | "the man in the red hat says: Where is the rabbit?" |

官方要求："Clearly specify if you want audio. We recommend that you use separate sentences in
your prompt to describe the audio."

官方对白语法是 **`角色描述 + says: + 台词`（冒号，不加引号）**，而非社区流传的引号包裹。
社区流传的 `SFX:` 前缀语法不是官方的。

**负面提示词**——Veo 是唯一把语法写进官方指南的厂商：

> Not recommended: using instructive language or words such as "no" or "don't". For example,
> avoid prompts such as "no walls" or "don't show walls".
> Recommended: Describe what you don't want to see. For example, "wall, frame".

两处官方免责声明（教练提示词必须内化）："Some advanced camera angles are not officially
supported. The results and reliability may vary."，以及镜头焦段的同款声明。

Veo 的 prompt guide 里**没有**「一次只写一个动作」的节奏配额，相反 `Action` 章节鼓励动作序列
（官方示例串了 5 个 beat）。也**没有**参考图提示词章节——「首尾帧只写运动」这类说法来自
第三方渠道页面，不是 Google 官方。

### 快手可灵 Kling（官方明文）

三套场景化公式（官方原文）：

```text
文生视频：Prompt = Subject（Subject Description）+ Subject Movement
                 + Scene（Scene Description）+（Camera Language + Lighting + Atmosphere）
图生视频：Prompt = Subject + Movement，Background + Movement
视频续写：Prompt = Subject + Movement
```

括号内可选。官方明确最基础三件套："The most fundamental components of the aforementioned
formula are the subject, motion, and setting."

`Camera Language` 官方词条：`ultra-wide angle shots` / `bokeh` / `close-ups` /
`telephoto shots` / `low-angle shots` / `high-angle shots` / `aerial views` /
`depth of field`。官方专门加注 "(Note: This should be differentiated from camera motion
control.)"——**镜头语言（景别/视角）与运镜控制是两套东西**，这条直接影响本仓库剧本 `camera`
色块该怎么拆。

**图生视频的反向陷阱**（这是本次调研里最容易被忽略、又最实用的一条官方说明）：

> if you want to have Mona Lisa in the painting wear sunglasses, when we simply input 'wear
> sunglasses', the model may have difficulty understanding the instruction... When 'Kling'
> determines that it is a painting, it is more likely to generate a video with panning effects
> of the painting exhibition, which is also the reason why photos are prone to generating
> static videos. Therefore, we need to describe 'subject + movement'.

即：有参考图时不要重复外貌，但**必须点名主体**；只写一个动作动词会得到"画作展览平移"。

其他官方约束：视觉内容尽量简单，5–10 秒内完成；避免复杂物理运动；模型对数字不敏感
（"10 只小狗"这类计数难以保持）；续写时提示词需与原片主体一致，否则"text may cause camera
cut or transition"——把切镜当故障而非功能。

支持 16:9 / 9:16 / 1:1。官方另有一条选题相关的 Tip：用 "Oriental mood" / "China" / "Asia"
这类词更容易生成中式风格与华人形象。

### Runway Gen-4 / Gen-4.5（官方明文）

Runway 官方同时存在四套字段清单，且**对顺序是否重要自相矛盾**（见分歧一节）。

```text
Gen-4 图生视频四要素：Subject motion / Camera motion / Scene motion / Style descriptors
Gen-4.5 推荐结构：[Camera] shot of [a subject/object] [action] in [environment]. [Supporting descriptions]
Resources 四段公式：[Camera Movement] + [Scene] + [Action] + [Details]
Camera 七段公式：[Shot size] + [Angle] + [Movement + direction + speed] + [Subject & action]
                + [Lens/look] + [Lighting/mood] + [What the shot reveals]
```

Gen-4.5 文生视频的十个成分分两大类：Visual（`Subject appearance` / `Environment` /
`Lighting` / `Composition/Framing` / `Style`）与 Motion（`Subject action` /
`Environmental motion` / `Camera motion` / `Motion style & timing` / `Direction & speed`）。

**Runway 是节奏与否定规则最严格的一家**（官方原文）：

- "Keep it under 10 seconds"
- "One action per prompt"——反例 `Woman walks to door, opens it, walks through, closes it,
  walks down hallway.`
- "Avoid temporal references: Don't use 'then,' 'next,' 'after that.' Each prompt is
  independent."
- "Choose one primary movement per prompt. Multiple camera directions in a single prompt
  confuse the AI and create chaotic, unusable results."
- "Negative phrasing is not supported and may produce unpredictable or even opposite results."
  机制解释："When you write 'No camera shake,' the AI might focus on the word 'shake' and give
  you exactly that." 正确写法：`Locked camera. The camera remains still.`
- "Abstract concepts force the model to interpret your intention, often resulting in random or
  unexpected movements."
- 参考图："Reiterating elements that exist within the image in high detail can lead to reduced
  motion or unexpected results."；用 "the subject" 或代词指代，避免模型
  "reinterpreting subject details already present in your image"。
- 多阶段运镜："describe what's revealed at each stage rather than stacking movement verbs. If a
  clip drifts or warps, reduce to a single move and generate the next beat as a separate clip."
- 主体与镜头用关系动词连接：`Camera follows the cyclist` / `Camera trucks left, matching the
  runner's speed.`

**但 Gen-4.5 官方支持时间戳**（与"避免 then/next"并存）：

```text
[00:00 through 00:02] looking away, then turns towards camera
[00:02 through 00:03] rapidly crash zoom to closely frame his eyes
```

官方注明 "though it may not be perfectly precise"，并要求校验动作时长的合理性。

Runway 官方文档里有全行业**唯一**一条字幕泄漏防治写法：
`Character turns to camera and says: Welcome to the future of creativity. (no subtitles)`

Scene motion 的两种官方写法：`Insinuated motion`（"The subject runs across the dusty desert"）
更自然，`Described motion`（"...Dust trails behind them as they move"）更强调该元素。

Runway 官方还明说 Text-to-Video 不适合做一致性："works well when exact character or scene
consistency isn't the priority—like creating B-roll, stock effects, or background plates."

### 阿里通义万相 Wan 2.x / 3.0（官方明文）

官方公式最完整、镜头语言词典最详尽的一家，五套场景化公式：

```text
基础：提示词 = 主体 + 场景 + 运动
进阶：提示词 = 主体（主体描述）+ 场景（场景描述）+ 运动（运动描述）+ 美学控制 + 风格化
图生视频：提示词 = 运动 + 运镜
声音：提示词 = 主体 + 场景 + 运动 + 声音描述（人声/音效/背景音乐）
多镜头：提示词 = 总体描述 + 镜头序号 + 时间戳 + 分镜内容
参考生视频：提示词 = 参考指代 + 动作 + 场景 + 台词（可选）+ 背景音乐（可选）
```

`美学控制` 官方定义包含"光源、光线环境、景别、视角、镜头、运镜"；`运动描述` 要求写"幅度、
速率和运动作用的效果"。图生视频公式官方解释："图像已经确定了主体、场景与风格，因此提示词
主要描述动态过程及运镜需求。"

**音频三层子公式**（最细的一家）：

```text
人声 = 角色说话的内容 + 情绪 + 语调 + 语速 + 音色 + 口音
音效 = 音源材质 + 行为 + 环境音
背景音乐 = 背景音乐/配乐 + 风格
```

官方台词语法是中文全角引号，且"在提示词中描述到台词内容时，如 xx说：'xxx'，模型会保持该
台词内容不变进行生成"。

**"不写 = 模型自己加"是这一家最重要的机制说明**："若提示词中未描述台词，则模型会自由发挥
添加台词。"／"当提示词不描述背景音乐时，模型会根据题材和内容自行发挥。" 所以静默场景必须
显式关闭：`无台词` / `No dialogue.` / `无背景音乐` / `No background music.` / `生成单镜头` /
`Generate single shot.`

**参考素材指代语法**（最规范的一家）："使用'图n'或'视频n'在提示词中指代参考文件，n 为该文件
在该类型中的序号。图和视频分别计数。中文写为'图1'、'视频1'，英文写为 `Image 1`、`Video 1`。
英文字母和数字之间有空格，首字母大写。"

万相把公式当 system message 喂给 LLM 生成提示词是官方推荐做法，中间产物用中文键值分段
（`主体：` / `场景：` / `运动：` / `声音描述：`），但**最后仍要合并成一段自然语言**。

### Vidu（官方明文）

```text
Subject/Scene + Scene Description + Environment Description + Art Style/Medium
```

四条官方书写规则：避免主体过多或分散；避免歧义词；用流畅自然的措辞、避免过度文学化；
描述要丰富准确完整。展开逻辑："Start with the subject + scene + action, then layer in
lighting, color tone, texture, and camera feel."

**Vidu 是唯一有官方键值块语法的厂商**（不是 JSON）：

```text
# Subject
The train starts moving forward, the front of the train gradually gets larger...
# Requirements:
Camera movement: follow to the right
```

漫剧三段结构（官方）：

```text
Part 1. Style / Shot Size / Camera Position / Composition / Camera Movement (optional)
Part 2. Scene Description
Part 3. Image Reference
        Image 1 is [scene]; Image 2 is [character xx]; Image 3 is [prop xx]
```

**Vidu 是唯一给出竖屏短剧明文构图规则的厂商**（Image Input Guide → Environments）：

> Avoid long shots (rarely used in short dramas, especially vertical format). Avoid including
> characters in environment shots. Prefer medium/close shots.

后半句"环境镜头里不要出现人物"与本仓库场景空镜教练的既有规则完全吻合，可作为外部佐证。

角色参考侧官方要求 "Close-up + three-view (front, side, back)"，且"Keep input character
styles consistent within the same video"。**注意这与即梦官方结论相反**（见分歧一节）。

Vidu 官方**允许组合运镜**："Movements can be combined (e.g., 'zoom in + clockwise orbit')."

两个很有教学价值的官方反直觉案例：`The train starts moving forward` 有时会让火车看起来在
倒退，修法是用"主体与背景的尺寸比例"制造前进感（车头逐渐变大、松树缩向远处）；主体走路
不自然可能是因为机位静止，**加一个运镜（zoom out）能让主体动作看起来更自然**。

### MiniMax 海螺 H3（官方明文，但无提示词指南）

MiniMax 没有独立提示词写法指南，只有能力页 + H3 亮点功能示例 + API 参考。但**官方示例本身
就是最贴近竖屏短剧的一批语料**，呈现出一致的制作简报排版：
`时长 + 画幅 + 品类` → `参考素材职责绑定` → `核心故事` → `整体气质/风格对标` → `镜头与音频约束`。

官方竖屏短剧示例（原文）：

```text
生成一支 15 秒、9:16 竖屏海外真人吸血鬼爱情短剧预告片段。男女主外形参考图1，场景参考图2，
保持身份一致。故事：……。风格对标海外 ReelShort / DramaBox 吸血鬼爱情短剧预告，暗黑浪漫、
危险吸引力、宿命感。人物以中近景、特写为主，突出脸、眼神与关系张力。
```

动画示例里的景别约束："人物露脸只在近景或特写；远景只用背影、侧背或环境空镜。"

素材职责绑定的官方模式是「[维度] 参考 [图N]」，一图一职责，并显式写「保持…一致」：
`整体氛围、场景和胶片质感参考图1；包袋资产参考图3；人物资产参考图2；品牌 ending logo 参考图4`。

**MiniMax 官方示例反其道而行**：动画示例极详尽地重复列举参考图里的外貌特征（`保持黑色半扎
长发、银色镂空发冠、黛蓝发带、浅色层叠汉服……一致`），与 Runway / 可灵 / Luma 的"不要重描
外貌"方向相反。

硬参数：H3 输出 4–15 秒（仅整数）、提示词上限 7000 字符、参考图 ≤9 张、参考视频 ≤3 段且总
时长 ≤15 秒、混合输入总上限 12 个文件。

H3-Context-IR 是全行业唯一的官方"结构化提示词生成"接口（"通过复杂逻辑推理生成结构化表达"，
只返回增强提示词不创建视频），但**官方未公开该结构化表达的 schema**。

### PixVerse（官方明文，带实测方法论）

官方三句式，50–80 词：

```text
[Subject] + [one action] + [location].
[One camera movement] + [specific style, lens, lighting, or composition].
[Positive constraints: what must remain stable, what should be absent, and whether audio is needed].
```

三条官方结论，都带机制解释：

- **"Longer Prompts Produce Worse Output, Not Better"**："long AI video prompts often dilute
  the main instruction. The first sentence carries the most control, while later details can
  become weak suggestions that compete with each other." 官方测出 80 词后控制力下降。
- **"Stacking Camera Movements Produces Jitter"**："Camera movement is spatial... When several
  are stacked, the model has to decide which one dominates and when to switch. The result can
  be a visible wobble at the transition point." 修法是一个主运镜 + 一个质感修饰词。
- **"There Are No Negative Prompts"**："In most AI video generators, this is not a real
  negative prompt field. It is just more text... the model still reads the words 'jitter,'
  'bent limbs,' and 'deformation.'" 修法是正向约束句：`Face remains stable.` /
  `Lighting remains consistent with no flicker.`
- **"'Cinematic' Is Nearly Useless"**："too broad to be reliable. It can mean horror shadows,
  romantic golden light, documentary realism, sci-fi haze..." 替换清单：导演风格构图、布光
  方案、镜头行为、画幅比例、色板。
- `fast` 这个词会降低质量："Speed is not only a style. It is a temporal demand." 改为描述
  速度的物理表征。

音频统一用 `Audio:` 前缀：`Audio: rain on pavement, distant traffic, soft neon hum.`

注意 PixVerse 自身的矛盾：官方博客说"没有真正的 negative prompt"，但自家 API 确实有
`negative_prompt` 字段。合理解读是博客在讲"写在正文里的 `negative:` 前缀无效"。

### Luma Ray3 / Ray 3.2（官方明文）

```text
Create a video of [SUBJECT] [MID-ACTION VERB] in [SETTING], [SECONDARY MOTION/CONSEQUENCE],
[CAMERA MOVEMENT if any], [LIGHTING/MOOD].
```

**Luma 是唯一点名具体禁用词的厂商**（官方 DON'T 列表原文）：

> Avoid using: "vibrant," "whimsical," "hyper-realistic" – these tend to degrade quality
> Avoid vague descriptors like "beautiful," "amazing," "stunning"
> Don't use temporal phrases like "begins to" or "starts to"

官方 DO 列表：用进行中的动词（"running" 而非 "begins to run"）；"'Positive only' model.
Negative prompting is counterproductive."；补二级后果（风吹头发、布料运动、反射、扬尘、
水波）；提示词约 100 词、动作导向、现在时；有关键帧时"describe only what CHANGES"。

Ray 3.2 的 V2V 禁令另开一套且更严："Do not write commands. Do not describe the transformation
process. Do not describe what happens over time. Describe the final image qualities that
should exist in the transformed video."；禁 `make` / `turn` / `change` / `transform`；禁
`throughout` / `as it moves` / `over time` / `when` / `then` / `gradually`；禁
`no` / `not` / `without` / `devoid of` / `missing`——"Negation can bias the model toward the
thing you are trying to exclude."

Luma 自家 DO/DON'T 有一处互相拉扯：DO 里写着 "Default to cinematic style unless otherwise
specified"，DON'T 里却禁掉了其他同类模糊质量词。

参考图侧官方原文："the prompt should describe the scene/action, and the reference image
handles identity"；"You don't have to re-describe the character's physical appearance if using
a reference — let the reference image do that work."；"For portraits, avoid stacking several
facial changes into one prompt."

动作数量官方原文："One clear action often works better than asking the model to change the
camera, subject, lighting, expression, and background at the same time."

Ray 3.2 有一条对教练型提示词定位很重要的话："with this system — especially when you're using
multiple keyframes — your settings often matter more than your prompt."

Luma 支持 6 种比例（`9:16` / `3:4` / `1:1` / `4:3` / `16:9` / `21:9`），是比例最多的一家；
但模型无原生音频。

### 字节 Seedance / 即梦 Dreamina（官方受阻）

火山引擎官方提示词指南确实存在（`volcengine.com/docs/82379/2222480` 等），但页面正文由
客户端渲染，抓取只得到 JS 空壳。以下内容来自三处独立二手来源，它们都声明同步自上述官方
文档，且在核心公式、特殊字符、分镜时序上完全一致。**引用时不要标为"官方明文"。**

```text
基础：主体＋动作 + 场景环境 + 视觉风格 + 运镜切镜 + 声音
      └─必写─┘ └────────── 可选，不需要就省略 ──────────┘
进阶：精准主体 + 动作细节 + 场景环境 + 光影色调 + 镜头运镜 + 视觉风格 + 画质 + 约束条件
```

官方心智模型："Seedance 本质是多模态 AI 导演，内部把请求拆成空间层（画面里有什么）和
时间层（如何随时间变化）。好提示词是工程型指令而非文案型形容。"

**特殊字符规范**（这一家独有，也是全行业最明确的音频信息分型语法）：

| 信息类型 | 符号 | 示例 |
| --- | --- | --- |
| 音乐 | `（）` | `（背景中播放着快节奏的摇滚乐）` |
| 音效 | `<>` | `<远处传来狗叫声>` |
| 台词 | `{}` | `{你好，世界}` |
| 字幕 | `【】` | `【第一章：启程】` |

**分镜时序上官方修正了旧写法**：改用「镜头1 / 镜头2 / 镜头3」按事件顺序组织，不强制限制
每段时长，理由是"模型对精确时间（如 0–3 秒）的支持不稳定，强行限制时长可能导致生成异常"。
每个镜头内部顺序四步：① 运镜或切换方式 → ② 主体动作与表情 → ③ 位置/空间变化 → ④ 音频信息。
内部节奏靠**相对节奏副词**（`快速` / `急促` / `缓慢` / `徐徐` / `短暂停顿` / `片刻后` /
`定格一瞬` / `随即` / `紧接着` / `话音未落`），精确卡点**锚定到音频而非数字**。

主体定义与素材绑定句式：

```text
将<图片/视频N>中的[主体核心特征]定义为<主体N>
@图片1用于<主体>的<外貌、服装、结构或材质>。
@视频1用于<动作、运镜或节奏>。
@音频1用于<角色或声音类型>的<音色、台词、环境声或音乐>。
```

核心特征用 2–3 个稳定静态特征；多主体分别定义并用唯一稳定标签区分，**后续全程沿用同一
标签**；越要精准参考的素材放越靠前。

**人物 ID 漂移的官方修法里有一条与 Vidu 相反**：不要用人物三视图/多视图，理由是"模型易把
不同角度当成多个主体，反而加剧漂移"，改用大头照 + 全身照分开绑定。

情绪具象外化对照表（可直接用）：

| 抽象情绪 | 外化为动作与细节 |
| --- | --- |
| 悲伤 | 低头、肩膀微颤、眼眶泛红、手指攥紧衣角、泪在眼眶打转未落 |
| 喜悦 | 嘴角抑制不住上扬、眉眼舒展、脚步轻快、哼起小曲 |
| 紧张 | 频繁看表、手指敲桌、呼吸急促、眼神闪躲、啃咬指甲 |
| 愤怒 | 双拳紧握、下颌紧绷、胸口剧烈起伏、从牙缝挤出话 |
| 释然 | 长舒一口气、肩膀放松、淡淡微笑、抬头望向远方 |

官方还明说"不要把完整剧本当 prompt"——"文案内容过度冗余易造成模型理解混乱"。

字幕泄漏三步修法：加约束词；参考素材里的非必要文字先用工具去除；**优先横屏生成**（横屏出
字幕概率明显低于竖屏），后期再裁竖屏。最后这条与本产品定位冲突，见「未采纳的发现」。

### Pika（未找到官方提示词文档）

只有 API 参数文档。可确认的官方事实：`negative_prompt` 参数存在；图生视频的 `prompt` 是
**可选**参数，官方说明写着 "The source image carries the subject."；T2V 仅 5 秒。

官方 T2V 示例提示词末尾用了 `No text, no logos, no wordmarks, no watermarks.`——与
Runway/Luma 的"禁用否定句"立场相反，但这是 Pika 自己写的示例。

## 二、JSON 提示词的定性

**零家厂商官方推荐 JSON 提示词。** Vertex AI prompt guide（2026-09-03）与 Gemini API video
页已完整抓取，无任何 JSON 示例、无 schema、无"结构化提示词"推荐。JSON 只出现在 API 请求体
层面。流传甚广的"Veo 3 JSON 提示词"全部来自第三方（教程视频、prompt generator 站点、渠道
博客），**属社区经验，未获任何厂商文档背书**。

官方有背书的结构化写法是**带标签的分段纯文本**：

- Sora 2 的 `Cinematography:` / `Actions:` / `Dialogue:` 段标签（官方明文）
- Vidu 的 `# Subject` / `# Requirements` 键值块（官方明文）
- 万相的中文键值分段作为 LLM 中间产物，但最后要合并成自然语言（官方明文）
- 即梦的 `（）<>{}【】` 符号分型（官方受阻）

这套写法既有 JSON 的字段可定位性与可迭代性，又不违背 Runway / 可灵 / Vidu 官方明确表达的
"自然语言优先"偏好——Runway 原文："natural language usually gives you more control. When you
write in full sentences, you provide context... Keywords are useful for setting a general
direction—think of them as suggestions."

产品内与提示词里都不要出现"JSON 是某厂商官方推荐"这种表述。

## 三、跨厂商共识

按官方明文重叠数排序。前七条每条都有 4 家以上官方明文且无厂商反对，可以当硬规则写。

1. **主体 + 动作是唯一必填层**，场景/风格/镜头/光影/音频都是可选层。可灵、万相、Vidu、
   即梦、Runway、Veo、Sora 2、PixVerse 共 8 家，7 家官方明文。
2. **单次生成 = 一个连续动作 + 一个主运镜**。Sora 2、Runway、可灵、PixVerse、Luma、即梦
   共 6 家，5 家官方明文。
3. **抽象形容词与情绪词无效，必须外化为可见的物理细节**。Sora 2、Runway、PixVerse、Luma、
   Vidu、Veo、即梦共 7 家，其中三家点名 `cinematic`。
4. **提示词正文里的否定句式会适得其反，改用正向表述**。Runway、Luma、PixVerse、Veo 四家
   全官方明文——注意连"支持 negative 字段"的 Veo 也认同"不要写 no/don't"，这条的一致性比
   表面看起来强得多。**但要区分两件事**：正文里的否定句（4 家一致反对）不等于独立的
   negative prompt 参数字段（见分歧二）。
5. **有参考图/首帧时，不要重复描述外貌，笔墨给动作 + 运镜 + 环境变化**。可灵、Runway、
   Luma、万相、Sora 2、Pika 六家全官方明文。但可灵额外提醒必须点名主体，MiniMax 官方示例
   则反其道而行。
6. **一致性靠"复用同一段措辞 + 结构化素材绑定"，不靠反复形容**。Sora 2、即梦、万相、Vidu、
   MiniMax、Luma、Runway 共 7 家。"一图一职责 + 显式绑定 + 全程沿用同一标签"是全行业收敛
   的做法。
7. **运镜要用具体电影术语 + 方向 + 速度，不能只写"运镜"**。Veo、Luma、Runway、万相、Vidu、
   即梦、PixVerse 共 7 家。
8. **时长与画幅是 API/面板参数，不要写进提示词**。Sora 2 与即梦写成了明确规则，另 4 家
   在参数层体现。但即梦同时建议把时长写进约束当双保险，MiniMax 官方示例也把时长写在首句。
9. **5–10 秒是单条提示词的有效动作预算**。可灵、Runway、Sora 2、Luma、Pika 五家官方明文。
   例外：MiniMax H3 4–15 秒、即梦最长 30 秒、万相 3.0 最长 30 秒——新一代长时长模型正在
   打破这条。
10. **对白要短、要放在独立块或用明确定界符**。6 家认同"要有明确定界"，但定界符各家不同
    （`Dialogue:` 块 / `says:` 无引号 / 中文全角引号 / `{}` / 英文引号），共识不在符号本身。
11. **音频必须显式描述，且分三层：对白 / 环境音 / 音效**。Veo、万相、即梦、Sora 2、
    PixVerse、Runway 共 6 家。万相的"不写 = 模型自己加台词和 BGM"是最重要的机制说明。
12. **分镜要显式编号或分块，不要靠 then / next / 然后 串联**。万相、即梦、Sora 2、Runway、
    Luma 共 5 家。用编号还是用秒数有分歧（见分歧四）。
13. **提示词更长 ≠ 更可控，冗余会互相竞争**。PixVerse、Runway、Luma、即梦、可灵、Sora 2
    共 6 家。Sora 2 的措辞最微妙：长提示词不是"更差"，而是"更可控但更不可靠"。
14. **迭代式加细节，一次只改一个变量**。Sora 2、Runway、Vidu、PixVerse 共 5 处官方表述。
    Sora 2 的诊断流程最可操作："If a shot keeps misfiring, strip it back: freeze the camera,
    simplify the action, clear the background."
15. **竖屏短剧偏中近景与特写、少用大远景**。**仅 Vidu 与 MiniMax 两家官方明文**，但两家都
    直接绑到了竖屏短剧场景，对本产品最直接可用。不要当行业共识写。

## 四、分歧（不要在提示词里写死）

以下六项厂商结论直接冲突，给统一建议一定会在某些模型上适得其反。教练提示词里只给"本平台
的默认做法"并说明理由。

1. **字段顺序是否重要。** PixVerse 说"第一句承载最多控制力"，Runway Resources 说"先指定
   镜头类型"，但 **Runway Help Center 直接问答"Is the beginning of my prompt prioritized?"
   答"No. The order in which elements are introduced in a prompt do not matter."**——Runway
   官方内部就是矛盾的。实操取舍：把核心主体+动作放最前是零成本的，对顺序敏感的模型有收益、
   对不敏感的无损失。
2. **negative prompt 字段存在性。** 有字段且有官方语法：Veo。有 API 字段但指南不提：可灵、
   PixVerse、Pika。官方明确不支持或反效果：Runway、Luma。无字段无规则：Sora 2、万相、
   Vidu、MiniMax。正确表述是"否定内容优先放进独立 negative 字段（若该模型有），正文里一律
   写正向约束句"。
3. **单条提示词能否写多镜头。** 支持并有官方多镜头公式：万相、即梦、Sora 2、Vidu q3、
   PixVerse。不建议、一次生成当一个场景：Runway Gen-4、可灵、Luma。**与模型代际强相关**：
   支持方都是 2026 年的新一代长时长模型。
4. **时间戳 vs 镜头编号。** 官方支持时间戳并给语法：Runway Gen-4.5、万相。官方劝退精确
   秒数：即梦（"模型对精确时间的支持不稳定"）。官方禁止一切时间性词汇：Luma Ray 3.2。用
   beats 而非秒数：Sora 2。默认用「镜头1/2/3」编号 + 相对节奏副词更安全。**本产品的
   breakpoint 机制本身就是镜头编号式切分而非秒数标注，与即梦官方建议天然一致。**
5. **提示词长度上限，跨度接近 30 倍。** MiniMax H3 上限 7000 字符、Vidu 5000 characters、
   PixVerse 推荐 50–80 词、Luma 约 100 词 / 2–4 句、Sora 2 的 ultra-detailed 官方示例达
   数百词与 10+ 段标题、Runway 明说 "There's no ideal prompt length"。默认按 80–120 词
   写覆盖多数模型的舒适区。
6. **参考图要不要三视图。** Vidu 官方推荐 "Close-up + three-view (front, side, back)"；
   即梦官方明确禁止三视图，理由是"模型易把不同角度当成多个主体，反而加剧漂移"。两家的机制
   解释都合理，很可能取决于模型是否有专门的 subject-consistency 模块。
7. **运镜能否组合。** Vidu 官方允许（"zoom in + clockwise orbit"）；PixVerse、即梦、
   Runway、Sora 2 四家反对且给了失败机理（transition point wobble）。反对方占优。
8. **`cinematic` 该不该写。** 五家反对（PixVerse 专章、Sora 2 标为 Weak、Luma 禁同类词、
   Runway 禁概念化语言、即梦反例），但万相官方画质推荐词就有 `电影质感`、可灵官方示例有
   `cinematic color grading`、Vidu 官方扩写示例大量用 `cinematic`、Luma 自家 DO 列表还写着
   "Default to cinematic style"。**可行的调和**：反对方的真实主张不是禁用这个词，而是它
   不能替代具体信息——Sora 2 的弱→强对照正是这个逻辑（`"Cinematic look"` →
   `"Anamorphic 2.0x lens, shallow DOF, volumetric light"`）。允许作基调，但必须同时给出
   至少两个可测量的视觉锚点。
9. **字幕泄漏防治，全行业最不成熟的一块。** 唯一有官方文档背书的是 Runway 的内联
   `(no subtitles)`，而它本身是否定句式；PixVerse（`no text overlay`）、Pika（`No text, no
   logos`）、万相（`不要加入文字。`）的官方示例也都在用否定词；即梦给了唯一的量化洞察
   （横屏出字幕概率低于竖屏）；Sora 2、可灵、Luma、Vidu、MiniMax 五家完全无说明，MiniMax
   甚至把"文字字幕"列为卖点能力。
10. **竖屏的一等公民地位。** Luma 六种比例、PixVerse 八种、可灵三种、Sora 2 支持
    `1080x1920`（pro）；Veo 只有 16:9 与 9:16，且据 Luma 官方观测竖屏一度锁定 720p。
11. **"开场 1–2 秒抓人"与"预告片结构"没有任何厂商官方指引。** 11 家全部没有，这两块是纯
    社区与运营经验。最接近的是 MiniMax 官方示例里的对标写法（`风格对标海外 ReelShort /
    DramaBox 吸血鬼爱情短剧预告`），但那是对标而非结构。

## 五、术语中英对照

### 景别（影视惯例）

| 中文 | 英文 | 缩写 | 画面范围 |
| --- | --- | --- | --- |
| 大远景 | Extreme Wide / Extreme Long Shot | EWS / ELS | 人极小，环境为主 |
| 远景 | Wide Shot / Long Shot | WS / LS | 全身 + 大量环境 |
| 全景 | Full Shot | FS | 头到脚 |
| 中远景 | Medium Wide / Medium Long Shot | MWS / MLS | 膝上 |
| 中景 | Medium Shot | MS | 腰上 |
| 中近景 | Medium Close-Up | MCU | 胸上 |
| 近景 | Close Shot | CS | 肩上 |
| 特写 | Close-Up | CU | 面部 |
| 大特写 | Extreme Close-Up | ECU | 眼/手/局部 |
| 微距特写 | Macro Close-Up | — | 纹理级 |
| 过肩 | Over-The-Shoulder | OTS | 越过一人肩看另一人 |
| 双人镜 | Two-Shot | 2S | 两人同框 |
| 主观镜 | Point of View | POV | 代表角色视线 |
| 插入镜 | Insert | INT | 物件细节 |

万相官方中文词表与此基本一致：`特写` / `近景` / `中近景` / `中景` / `中全景` / `全景` /
`广角` / `极端全景`，另有镜头类型 `干净的单人镜头` / `双人镜头` / `群像镜头` / `定场镜头`。

### 运镜与角度（影视惯例 + Veo 官方词表）

| 中文 | 英文 | 说明 |
| --- | --- | --- |
| 推 | Dolly In / Push In | 机身向主体靠近，有透视变化 |
| 拉 | Dolly Out / Pull Out | 机身远离 |
| 变焦推近/拉远 | Zoom In / Zoom Out | 只变焦距，机身不动，无透视变化 |
| 左右摇 | Pan Left / Right | 机位不动，水平转向 |
| 上下摇 | Tilt Up / Down | 机位不动，垂直转向 |
| 平移 | Truck / Track / Lateral Slide | 机身横向位移 |
| 跟拍 | Follow / Tracking Shot | 跟随运动主体 |
| 环绕 | Orbit / Arc | 绕主体弧线运动 |
| 升 / 降 | Pedestal / Crane / Jib Up-Down | 垂直位移 |
| 航拍 | Aerial / Drone Shot | — |
| 手持 | Handheld | 微抖 |
| 固定 | Static / Locked-off / Fixed | 三脚架锁死 |
| 甩镜 | Whip Pan | 高速摇带运动模糊 |
| 移焦 | Rack Focus | 焦点在前后景间转移 |
| 滑动变焦 | Dolly Zoom / Vertigo Effect | 推轨与变焦反向 |
| 平视 / 仰拍 / 俯拍 / 荷兰角 | Eye Level / Low Angle / High Angle / Dutch Tilt | 角度四态 |

Veo 官方对 `Zoom` 的区分原文："is different from a dolly, as the camera itself doesn't move."

### 光线（影视惯例 + 万相官方词表）

主光 Key / 补光 Fill / 逆光 Backlight / 轮廓光 Rim / 实用光源 Practical（画面内可见的灯）/
动机光 Motivated（被画面内光源合理化的补光）/ 硬光 Hard / 柔光 Soft / 反射光 Bounce /
高调 High-key / 低调 Low-key / 明暗对照 Chiaroscuro / 伦勃朗光 Rembrandt / 剪影 Silhouette /
黄金时段 Golden Hour。

**明暗比（key-to-fill）可以直接写进提示词，比"有质感的光"有效得多**：

| 比值 | 效果 |
| --- | --- |
| 1:1 | 平光 |
| 2:1 | 适度对比 |
| 4:1 | 戏剧性 |
| 8:1 | 黑色电影 / 恐怖 |

万相官方光源词表：`日光` / `晴天光` / `阴天光` / `火光` / `月光` / `实用光` / `荧光` /
`混合光`；光线类型：`柔光` / `硬光` / `侧光` / `边缘光` / `背光` / `逆光` / `顶光` /
`剪影` / `高对比度` / `低对比度`。

### 分镜表字段

英文 shot list 四个独立来源收敛的字段集（影视惯例）：Scene / Shot # / Shot size / Angle /
Movement / Lens / Subject & Action / Location / Duration / Audio notes / Equipment /
Priority / Notes。编号惯例是**场次号 + 设置字母**（12A、12B），会一路贯穿场记单、摄影报告
和剪辑日志。

中文分镜头脚本通用表头：镜号 | 景别 | 角度 | 方法（摄法）| 内容 | 音乐 | 音响 | 人声 |
时长 | 备注。短视频/AI 向简化版：镜号 | 时长 | 景别&运镜 | 画面描述 | 台词/字幕 |
BGM&音效 | 备注，并明确要求"画面描述要具体到可以直接当 AI 提示词用"。

## 六、可换算的经验值

这些数字来自传统影视教材与中文短剧行业文章（影视惯例 / 社区实践），不是厂商规范，但可以
直接变成算法默认值。

**景别决定时长基线**：远景 10 秒 / 全景 8 秒 / 中景 6 秒 / 近景 4 秒。

**台词密度**：1 秒约 3–4 个字；60 秒短视频文案不超过 180 字。

这两条配合平台的单段时长上限，就能给出 breakpoint 的建议切分点，而不是让作者拍脑袋。

**竖屏安全区**：没有通用像素规范，业界做法是保守的中央安全区——底部预留 120–160px 给字幕
和 App UI，顶部三分之一给环境与标题条，中部与中上部给脸和主要动作。特写把眼睛放在上三分
之一线。

**竖屏双人对话**：不要左右并排。三种可用解法是上下堆叠错位的紧凑双人镜、竖屏过肩（下方
主体上方留负空间）、用前景/中景/背景三层纵深代替横向关系。调度上让演员沿垂直线移动而非
水平弧线，入画从上/下而非只从左右。镜头焦段 35–50mm 等效做中近景，85mm 等效做紧特写压缩
背景。

**竖屏短剧的规模与节奏**（社区实践 / 行业报道）：微短剧月活 7.18 亿、人均单日 129 分钟；
广电总局定义单集"几十秒到 15 分钟左右"；主流竖屏单集 2–5 分钟；节奏惯例被概括为"3 秒一个
钩子、5 秒一个反转、10 秒一次冲突"；94% 的手机视频用户以竖屏观看；爱奇艺的创作方法论明确
提出**主要角色不要超过 3 人**，因为人物多会导致用户混乱弃看。

**60 秒节奏骨架**（两个独立来源高度一致）：

```text
0-3s   爆点钩子（羞辱/冲突/崩坏）
3-8s   冲突升级
8-15s  信息缺口（谜团/身份伏笔）
15-30s 第一次反转
30-50s 情绪堆叠
50-55s 峰值爆炸
55-60s 留债钩子
```

**开场钩子三类**：直接冲突型（当众打脸、甩离婚协议）、强悬念型（枪口对准主角、掉落化验
单、神秘来电）、极致反差型（婚礼现场撕破脸、豪门太太变弃妇）。

**集末钩子六类**：悬念断、危机断、反转断、揭示断、选择断、情感断。规则是同一种不连续使用
超过 2 次、6 集内覆盖至少 4 种。

**预告片结构**（影视惯例）：冷开场 → [Logo] → 第一幕前提/人物 → 第二幕冲突/反派 →
第三幕高能快切 → 标题卡 → [Button/Stinger]。要点是冷开场必须短、有趣、几乎不需要上下文；
**能量曲线不是一路走高**（"如果全程高能，就等于全程不高能"），开场强 → 回落 → 逐步建高到
高潮；在高潮峰值处结束然后上标题卡；素材只取影片前 40% 左右，永不展示结局。

## 七、反例库

按「症状 → 成因 → 修法」组织。多数条目有厂商官方背书，见前文引用。

| 坑 | 症状 | 修法 |
| --- | --- | --- |
| 一镜两个运镜 | 抖动、漂移、非预期转场 | 一镜一运镜；多阶段改为描述每阶段揭示了什么 |
| 一段塞多个动作 | 变形、多肢体 | 一个可读的物理动作 + 一个小的收束反应；5 秒内不超 3 个节拍 |
| 抽象动词 | "喝咖啡""使用产品"→ 主体在动作里漂浮 | 换成带计数的节拍（敲三下、走两步） |
| 抽象情绪词 | "她看起来很伤心"→ 无表演 | 外化为生理信号：肩膀微颤、眼眶泛红、手指攥紧衣角 |
| 形容词堆叠 | cinematic / 8K / masterpiece → 画面反而平庸 | 换成镜头看得见的：焦段、景深、光向、材质 |
| "bustling" 这类词 | 强迫模型发明几十个运动元素 → 时序崩溃 | 简化动作，限制画面内运动主体数量 |
| `fast` | 不稳定运动 | 描述速度的物理表征而非速度本身 |
| 假负面提示词 | 普通提示框把 "no X" 整句当指令读 | 有独立负面框就填「X」而不是「no X」；没有就改写成正向约束 |
| 30 词负面表 | 画面僵硬、失去运动和细节 | 5–8 个，上限 12–15 |
| 光线方向不锁 | 跨镜曝光和阴影乱跳 | 点名动机光源和方向，跨镜保持一致 |
| 矛盾指令 | 慢动作 + 快节奏、极简 + 繁复、锁定机位 + 手持 | 生成前做冲突自检 |
| 图生视频重述参考图 | 冗余描述让模型困惑，运动量下降 | 只写运动，但**仍要点名主体**，用"该主体/她"指代 |
| 图生视频只写动作不点主体 | 模型判定输入是画作 → 生成"画作展览平移"静态视频 | 写「主体 + 动作」，这是可灵官方明文 |
| 要求可读文字/Logo | 渲染成乱码字形 | 后期合成；提示词里改为"留出纯色暗场区域" |
| 开场铺垫超 10 秒 | 用户直接划走 | 0–3 秒出冲突画面 |
| 结尾没钩子 | 转下一集数据暴跌 | 卡在情绪最高点直接黑屏 |
| 写成剧本而非画面 | 心理描写、前情交代无法拍 | 只写镜头能拍到的 |
| 把完整剧本塞进 prompt | 模型理解混乱 | 分镜 prompt 必须精简聚焦，只留指令性内容 |

通用负面基线（社区实践）：`blur, distort, low quality, warping fingers, frozen lips,
jittery eyes`；中文版：变形扭曲、形态渐变、面部扭曲、多余手指、模糊纹理、抖动运动、伪影。

## 八、格式模板语料（11 大类 104 条）

这是 `catalog.py` 里 `fmt-*` 预设的选材来源。大类之间按"它约束提示词的哪一段"划分，互不
重叠：A 管整段结构，B–D 管画面内容的三个正交轴（时间入口 / 表演 / 空间），E–G 管三种拍摄
语言（机器 / 光 / 声），H–I 管跨片段关系，J 管特殊交付物，K 管排除项。

每条格式：**中文名** — 说明。`英文骨架关键词`（来源类型｜适用素材：【动】角色动作片段
【转】转场衔接片段 【预】预告封面视频）

### A 整段骨架与字段顺序（10 条）

一条提示词只能选一个 A 类骨架。

1. **五要素基础式** — 主体+运动+场景+镜头+光影，最小可用骨架。`subject + motion + scene + camera language + lighting`（官方明文｜动）
2. **六段通用式** — 五要素后追加风格/氛围。`subject, action, environment, camera, lighting, style`（社区实践｜动转预）
3. **摄影优先倒装式** — 景别与运镜提到句首，先锁空间再渲染主体。`camera + framing first, then subject + action`（社区实践｜转预）
4. **官方十一段式** — 按 Veo 当前官方章节顺序逐项填。`subject, action, scene, angles, movements, lens, style, temporal, audio`（官方明文｜动预）
5. **散文加标签块式** — 一段自然语言场景，再挂 Cinematography / Actions / Dialogue 标签块。`prose scene; Cinematography:; Actions:; Dialogue:`（官方明文｜动）
6. **键值块式** — 用 `# Subject` / `# Requirements` 分块，官方背书的结构化写法。`# Subject ... # Requirements: camera movement`（官方明文｜动转）
7. **运动独立成块式** — 把 motion 从 action 里拆出来单列。`... + camera + explicit motion block`（社区实践｜动转）
8. **约束收尾式** — 六段末尾固定挂一个 Constraints 段。`... + constraints: one camera move, wardrobe holds`（官方明文｜动）
9. **三句配额式** — 第一句主体动作地点、第二句镜头风格、第三句约束，总长 50–80 词。`sentence1 subject+action+location; sentence2 camera+style; sentence3 constraints`（官方明文｜动转预）
10. **篇幅配额式** — 整段设 80–120 词上限，防止维度互相稀释注意力。`80-120 word cap`（社区实践｜动转预）

### B 开场钩子与首秒冲击（9 条）

只约束片段的第 0–2 秒。厂商官方对此无任何指引，全部是社区与影视惯例。

11. **首帧冲突定格式** — 第 0 帧即冲突画面本身，不给铺垫。`opens mid-conflict, no establishing`（影视惯例｜动预）
12. **一句话身份反转式** — 开场台词同时交代身份、关系和反转。`single line reveals identity + relationship + twist`（社区实践｜动）
13. **悬念物件特写式** — 开场给一个高信息量物件特写。`ECU on a story-critical object`（影视惯例｜动预）
14. **冲向镜头急停式** — 主体从远处冲向镜头并急停，靠纯运动量抓停留。`sprints toward camera, stops abruptly`（社区实践｜动预）
15. **直视镜头开口式** — 主体转头直视镜头说一句 12 词以内的话。`turns to camera, one line under 12 words`（社区实践｜动预）
16. **极致反差落差式** — 同一镜内完成从高位到跌落的两态切换。`status high to low within one shot`（影视惯例｜动）
17. **声音先入式** — 声音事件先于画面出现。`sound event precedes image`（影视惯例｜动预）
18. **中断式冷开场** — 从一个动作的中段进入，不交代前情。`cold open, enters mid-action, no context`（影视惯例｜预）
19. **可见倒计时式** — 画面内有可见的倒计时、进度条或逼近物制造紧迫。`visible countdown in frame`（影视惯例｜动预）

### C 单动作节拍（10 条）

20. **一动作一反应式** — 一个可读的物理动作 + 一个小的收束反应。`one physical action, then one small reaction`（官方明文｜动）
21. **身体部位级写法** — 写到手指、下颌、肩膀、脊柱，而不是整体状态。`body-part level: fingers curl, jaw tightens`（社区实践｜动）
22. **计数节拍式** — 用可数量词锁时长：敲三下、走两步、眨一次眼。`counted beats: taps three times, two steps`（官方明文｜动）
23. **相对节奏副词式** — 用"随即/短暂停顿/话音未落"代替硬秒数，规避模型对精确时间不稳定。`relative pacing adverbs instead of timestamps`（官方受阻｜动预）
24. **情绪外化式** — 禁用情绪形容词，改写为可见生理信号。`no emotion adjectives; visible physical tells only`（官方明文｜动）
25. **速度物理表征式** — 不写 fast，改写速度的可见证据（扬尘、衣摆、拖影）。`physical signs of speed, not the word fast`（官方明文｜动）
26. **入画出画式** — 用 enters frame / exits frame 描述进出，避免主体瞬移。`enters frame from bottom, exits left`（影视惯例｜动转）
27. **物理接触式** — 写受力点与接触细节。`force-based verbs, heel-first contact, weight transfer`（社区实践｜动）
28. **单主体独占式** — 一镜只给一个主体主动作，其余人物明确写为静止。`one active subject, others hold still`（官方明文｜动）
29. **动作留白收尾式** — 动作做完保留半秒静止，给剪辑留切点。`holds still for a beat at the end`（影视惯例｜动转）

### D 景别构图与竖屏适配（10 条）

30. **标准景别缩写式** — 统一使用 ECU/CU/MCU/MS/MWS/WS/EWS，消灭"近一点"这类表达。`ECU / CU / MCU / MS / MWS / WS / EWS`（影视惯例｜动转预）
31. **景别递进三层式** — 全景→中景→特写的三镜推进。`WS to MS to CU ladder`（影视惯例｜动）
32. **竖屏中央安全区式** — 脸、手和关键道具留在中央安全区，边缘让给平台 UI 和字幕。`center-safe framing, 9:16, avoid edges`（社区实践｜动预）
33. **底部字幕留白式** — 底部预留不放关键信息的带状区域给烧录字幕。`bottom safe band reserved for captions`（社区实践｜动预）
34. **竖屏中近景优先式** — 竖屏短剧偏中近景与特写，远景只用背影或环境空镜。`medium and close shots, long shots only as empty plates`（官方明文｜动预）
35. **竖屏三层纵深式** — 前景手/中景脸/后景事件，用纵深代替横向并排。`foreground / midground / background stacking`（社区实践｜动）
36. **竖屏双人错位式** — 双人上下错位或紧凑堆叠，不左右并排。`vertical two-shot, staggered faces`（社区实践｜动）
37. **竖屏过肩式** — 下方主体过肩看上方主体。`vertical OTS, negative space above lower subject`（影视惯例｜动）
38. **上三分之一眼位式** — 特写把眼睛放在画面上三分之一线。`eyes on upper third`（影视惯例｜动）
39. **角度四态式** — 明确写平视/仰拍/俯拍/荷兰角。`eye level / low angle / high angle / dutch tilt`（官方明文｜动预）
40. **焦段与景深式** — 85mm 压缩做紧特写、24–35mm 做环境，浅景深隔离主体。`85mm shallow DOF / 24-35mm deep focus`（官方明文｜动预）

### E 运镜描述（10 条）

最容易和 C 类混写出错的一段。

41. **一镜一运镜式** — 一个片段只允许一个运镜动作，多运镜必抖。`one camera move per clip`（官方明文｜动转预）
42. **运镜与动作分写式** — 先写主体动作句，另起一句写镜头，不混在同一子句。`separate sentence for camera`（官方明文｜动）
43. **术语加方向加速度式** — 运镜必须三件齐全，不能只写"镜头移动"。`term + direction + speed`（官方明文｜动转）
44. **中英双标式** — 中文描述加英文术语括注。`缓慢推进（slow push in）`（社区实践｜动转）
45. **镜头语言与运镜分离式** — 景别/视角属"镜头语言"，推拉摇移属"运镜控制"，两槽分开填。`framing slot and motion slot filled separately`（官方明文｜动）
46. **关系动词衔接式** — 用关系动词把主体运动和镜头运动连起来。`camera follows the cyclist, matching speed`（官方明文｜动转）
47. **阶段揭示式** — 多阶段运镜写"每阶段揭示了什么"，而不是堆动词。`describe what each stage reveals`（官方明文｜转预）
48. **锁定机位式** — 三脚架锁死，时序一致性最高的默认选择。`static locked-off tripod shot`（官方明文｜动）
49. **手持微抖式** — 写微幅漂移而不是"晃动"，避免抖成噪点。`subtle handheld micro-drift`（社区实践｜动）
50. **主运镜加质感式** — 一个主运镜 + 一个质感修饰词，是唯一安全的"组合"。`main motion plus one texture modifier`（官方明文｜动转）

### F 光线与质感（10 条）

把"电影感"这种废词转成可执行指令的关键一段。

51. **命名光源式** — 点名真实光源，禁止"美丽的光线"。`named source: tungsten desk lamp, neon sign`（官方明文｜动转预）
52. **光位方向式** — 明确写主光来向。`key light from camera-left, above`（影视惯例｜动预）
53. **色温对撞式** — 暖冷双源并存制造层次。`warm key + cool practical fill`（影视惯例｜动预）
54. **明暗比式** — 用 key-to-fill 比值量化对比。`4:1 key-to-fill ratio`（影视惯例｜动预）
55. **高低调式** — high-key 明亮均匀 / low-key 深阴影高对比。`high-key / low-key lighting`（影视惯例｜动预）
56. **轮廓光分离式** — 用逆光把人从背景剥离，竖屏小屏尤其必要。`rim light separating subject from background`（影视惯例｜动预）
57. **画内实用光源式** — 让光源本体出现在画面里。`practical light visible in frame`（影视惯例｜动）
58. **动机光式** — 补光必须被画面内某个光源合理化，方向与色温一致。`motivated lighting matching the practical`（影视惯例｜动）
59. **胶片质感式** — 用具体胶片语言代替"质感好"。`35mm film grain, halation, micro-scratches`（社区实践｜动预）
60. **材质纹理式** — 写表面材质而不是"高级感"。`matte / brushed / weathered / dust-covered`（社区实践｜动预）

### G 对白与音频（10 条）

竖屏短剧最容易被忽略的一段，且"不写就等于让模型自己加"。

61. **显式音频声明式** — 音频必须单独成句显式描述，不写模型会自己发挥。`separate sentences describing audio`（官方明文｜动）
62. **三层音频式** — 对白 / 环境音 / 音效分三层分别写。`dialogue / ambient noise / sound effects`（官方明文｜动转）
63. **台词长度配额式** — 8 秒片段内英文 ≤12 词，中文按 1 秒 3–4 字折算。`under 12 words per 8s clip`（官方明文｜动）
64. **独立对白块式** — 对白放在散文描述下方的独立块，与画面描述明确分离。`Dialogue: block below the prose`（官方明文｜动）
65. **说话人标签式** — 说话人用固定标签，同一角色全程同一写法。`consistent speaker labels, alternating turns`（官方明文｜动）
66. **人声六件套式** — 台词内容 + 情绪 + 语调 + 语速 + 音色 + 口音。`line + emotion + tone + pace + timbre + accent`（官方明文｜动）
67. **音效跟随触发式** — 音效紧跟触发它的视觉描述之后。`sfx placed right after its visual trigger`（社区实践｜动转）
68. **环境音底噪式** — 环境音放句尾，避免盖过主音效和对白。`ambient bed at prompt end`（社区实践｜动转）
69. **显式静音式** — 不需要台词或 BGM 时必须显式关闭。`no dialogue / no background music, ambient only`（官方明文｜转预）
70. **节奏锚点式** — 静默镜头也给一个声音节奏锚，而不是完整配乐。`one rhythm cue, not a soundtrack`（官方明文｜动转）

### H 转场与衔接（10 条）

输出的是可拼接的接口而不是内容。

71. **甩镜方向加模糊式** — 显式写方向 + 重横向运动模糊，只写"快"不产生拖影。`whips hard right, heavy horizontal motion blur`（社区实践｜转）
72. **同向配对式** — A 尾与 B 头必须同方向同速，反向会被读成弹回。`match whip direction and speed on both halves`（影视惯例｜转）
73. **末尾崩坏容忍式** — 剧烈运动放在片段最后几帧，前段保持稳定。`stable start, whip only in final frames`（社区实践｜转）
74. **匹配剪辑式** — 两端共享同一形状、颜色或运动方向，且在屏幕同一位置。`match cut on shared shape, same screen position`（影视惯例｜转）
75. **穿越遮挡式** — 镜头穿过前景遮挡物完成换场。`push through foreground occluder`（影视惯例｜转）
76. **光效擦除式** — 用光斑、白闪或耀斑扫过画面完成擦除。`light wipe sweeping across frame`（社区实践｜转）
77. **首尾帧过渡式** — 指定首帧与尾帧，让模型只负责中间的运动。`first frame + last frame, generate motion between`（官方明文｜转）
78. **纯运镜空镜式** — 无人物的纯环境运动片段，做万能垫片与呼吸点。`empty environment, single slow move, no people`（影视惯例｜转）
79. **焦点转移过渡式** — 用移焦从前景切到后景，做同一空间内的软切。`rack focus from foreground to background`（影视惯例｜转）
80. **转场动词前置式** — 把"移动的过程"写成动词短语，而不只描述两端。`camera pushes in fast, blur dissolves into next shot`（社区实践｜转）

### I 一致性锁定与参考素材（11 条）

唯一一类要求跨多条提示词共享文本的格式。

81. **身份锚定段式** — 一段固定的主体描述块，逐字复用不改写。`identity block pasted verbatim atop every prompt`（社区实践｜动预）
82. **措辞复用式** — 跨镜头复用同一段措辞而不是重新形容一遍。`reuse phrasing across shots for continuity`（官方明文｜动）
83. **一图一职责式** — 每张素材显式声明它锁的是什么维度。`image1 for wardrobe, video1 for camera rhythm`（官方明文｜动转）
84. **素材指代语法式** — 用规范的图号/视频号指代素材，图与视频分别计数。`Image 1 / Video 1, capitalized with a space`（官方明文｜动转）
85. **标签定义复用式** — 先把素材定义为命名主体，后续全程沿用同一标签。`define subject label once, reuse it throughout`（官方受阻｜动）
86. **点名主体加动作式** — 有参考图时不重描外貌，但必须点名主体，只写动作会得到静态平移。`name the subject plus the movement, skip appearance`（官方明文｜动转）
87. **代词指代式** — 用"该主体/她"承接身份，避免模型重新解释外貌细节。`refer as the subject or a pronoun`（官方明文｜动转）
88. **只写变化式** — 有关键帧时只描述发生变化的部分，不重述静态元素。`describe only what changes`（官方明文｜转）
89. **色板锚定式** — 点名三到五个颜色，稳定跨镜头色调。`name three to five palette colors`（官方明文｜动预）
90. **光向跨镜锁定式** — 整场戏统一主光方向与色温，防止曝光和阴影跳变。`same key direction and color temperature across the scene`（影视惯例｜动）
91. **媒介锚定式** — 全局写一次视觉媒介锚点，压住风格漂移。`single global medium anchor, stated once`（社区实践｜动转预）

### J 预告封面与收尾（8 条）

92. **冷开场钩式** — 前 2 秒一个无需任何上下文就成立的高能瞬间。`cold open, self-contained beat, no setup`（影视惯例｜预）
93. **首两秒三信号式** — 人脸或身体 + 一个运动或声音炸点 + 一句制造好奇缺口的短台词。`face + kinetic beat + curiosity-gap line`（社区实践｜预）
94. **能量回落式** — 开场强 → 主动回落 → 再建高，避免全程高能等于全程平淡。`start high, dip, rebuild to climax`（影视惯例｜预）
95. **不剧透素材约束式** — 只用前 40% 剧情的画面，不出现任何解决画面。`first-act footage only, no resolution shots`（影视惯例｜预）
96. **疑问句留白式** — 台词只给问句不给答案。`question line, answer withheld`（影视惯例｜预）
97. **峰值截断式** — 在情绪最高点直接切黑，不等余波。`cut to black at peak`（影视惯例｜预）
98. **标题安全区留白式** — 结尾留出纯色暗场区域供后期压字，不让模型生成文字。`clean dark band at the end for later titling`（社区实践｜预）
99. **无缝循环式** — 首尾构图与运动方向一致，做可循环封面。`loopable, first and last frame match`（官方明文｜预）

### K 否定约束与自检（5 条）

100. **正向约束替代式** — 把否定要求改写成正向陈述句，模型会盯住否定词本身。`camera stays steady, hands remain natural`（官方明文｜动转预）
101. **独立负面框式** — 有独立负面字段就填「X」而不是「no X」，字段本身已表示排除。`negative field: wall, frame`（官方明文｜动转预）
102. **精简负面词表式** — 负面词控制在 5–8 个，上限 12–15，超量会让画面僵硬。`5-8 negative terms max`（社区实践｜动转预）
103. **互斥指令自检式** — 提交前扫一遍互斥组合：慢动作与快节奏、锁定机位与手持、极简与繁复。`conflict check before submit`（官方明文｜动转预）
104. **遮挡自检式** — 逐个名词回问"隔着这层遮挡看得见吗"，看不见就降级成光色。`occlusion audit: unseen nouns become light only`（社区实践｜动转）

## 九、未采纳的发现

**即梦官方建议"优先横屏生成、后期裁竖屏"**，理由是横屏出多余字幕的概率明显低于竖屏。这是
字幕泄漏这块唯一的量化洞察，但与本产品竖屏短剧的定位直接冲突——我们的 `aspect_ratio` 默认
就是 `9:16`，改成横屏生成再裁会同时损失构图控制与竖屏安全区规则。记录在此，不写进提示词。

**MiniMax 官方示例的"详尽重复参考图外貌"写法**与六家官方的"不要重描外貌"相反。考虑到反对
方数量与机制解释都更充分，本产品沿用"点名主体 + 不重描外貌"，但如果将来发现某个具体端点
在这条上表现异常，这里是回溯的起点。

**参考图三视图**在 Vidu（推荐）与即梦（明确禁止）之间无法调和。本仓库的角色资产是多分区
设定图（`ENHANCE_SYSTEM_PROMPT_CHARACTER`），走的是 Vidu 那一侧；如果接入的端点出现"把
不同角度当成多个主体"的漂移，需要按端点分支而不是全局改规则。

## 十、来源清单

**厂商官方**：
[Sora 2 Prompting Guide](https://developers.openai.com/cookbook/examples/sora/sora2_prompting_guide)
· [Veo 视频生成提示词指南（Vertex AI）](https://cloud.google.com/vertex-ai/generative-ai/docs/video/video-gen-prompt-guide)
· [Gemini API · Veo](https://ai.google.dev/gemini-api/docs/veo)
· [Veo 3.1 Ultimate Prompting Guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1)
· [DeepMind Veo Prompt Guide](https://deepmind.google/models/veo/prompt-guide/)
· [Kling Text to Video Prompt Guide](https://kling.ai/quickstart/text-to-video-prompt-guide)
· [Kling Image to Video Guide](https://kling.ai/quickstart/image-to-video-guide)
· [Runway Gen-4 Video Prompting Guide](https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide)
· [Runway Text to Video Prompting Guide](https://help.runwayml.com/hc/en-us/articles/47313737321107-Text-to-Video-Prompting-Guide)
· [Runway AI Camera Prompts](https://runway.com/resources/ai-camera-prompts)
· [万相文生视频/图生视频提示词指南](https://help.aliyun.com/zh/model-studio/text-to-video-prompt)
· [万相 wan3.0 视频生成调用指南](https://help.aliyun.com/zh/model-studio/wan3-video-generation-guide)
· [Vidu Video Generation Prompt Guide](https://help.aliyun.com/en/model-studio/vidu-video-generation-prompt-guide)
· [Vidu Text to Video API](https://platform.vidu.com/docs/text-to-video)
· [MiniMax 视频生成](https://platform.minimaxi.com/docs/guides/video-generation)
· [MiniMax H3 亮点功能示例](https://platform.minimaxi.com/docs/guides/video-prompt)
· [PixVerse AI Video Prompt Guide: 7 Tested Fixes](https://pixverse.ai/en/blog/ai-video-prompt-guide-7-tested-fixes)
· [Luma Video Models Field Guide](https://lumalabs.ai/learning-hub/luma-video-models-guide-ray3.14-veo-sora-kling-compared)
· [Ray 3.2 Prompting, Outputs & Controls](https://lumalabs.ai/learning-center/articles/ray-3-2-prompting-outputs-and-controls)
· [Luma 20 Image-to-Video Prompts](https://lumalabs.ai/news/image-video-prompts)
· [Pika API 文档](https://dev.pika.art/models/pika/pika-2.5/text-to-video)

**火山引擎官方（抓取受阻，经二手交叉核对）**：
[Seedance 2.0 系列提示词指南](https://www.volcengine.com/docs/82379/2222480)
· [Seedance 2.5 提示词指南](https://docs.volcengine.com/docs/82379/2291680)
· [Seedance 1.0 系列提示词指南](https://docs.volcengine.com/docs/82379/1631633)
· 交叉核对来源：[mantoufan/seedance-prompts-skill](https://github.com/mantoufan/seedance-prompts-skill/blob/main/skills/seedance-prompts-skill/references/seedance-prompt-guide.md)
· [morphic Seedance 2.5 指南](https://morphic.com/zh/resources/how-to/seedance-2-5-guide)
· [best.xiaohu.ai 官方指南解读](https://best.xiaohu.ai/article/seedance-25-prompt-guide/)

**开源导演 Skill（只借方法，未复制文字）**：
[liyue-aigc/seedance-2-5-video-director](https://github.com/liyue-aigc/seedance-2-5-video-director)（MIT）
——表演反应链、物理因果顺序、视频专有互斥项、视频编辑「A 改成 B + 生效区间 + 保持项」结构、
参考图借用范围；未使用其中整理自厂商手册的能力与示例文件。

**影视分镜与术语**：
[Tools for Film · Shot List](https://www.toolsforfilm.com/blog/how-to-write-a-shot-list)
· [Storyflow · Shot List 2026](https://storyflow.so/blog/how-to-make-a-shot-list-2026)
· [TechSmith · How to Write a Shot List](https://www.techsmith.com/blog/how-to-write-a-shot-list/)
· [StudioBinder 灯光术语](https://www.studiobinder.com/blog/film-lighting-terms/)
· [StudioBinder Lighting Ratios](https://www.studiobinder.com/blog/lighting-ratios/)
· [No Film School 灯光术语](https://nofilmschool.com/lighting-terms)
· [分镜头脚本表格](https://hcnote.cn/2023/03/30/4286.html)
· [专业视频分镜脚本完整写法](https://www.zhongli-tech.com/new/768733145265622016)
· [Derek Lieu · 预告片结构](https://www.derek-lieu.com/blog/2017/9/10/the-matrix-is-a-trailer-editors-dream)
· [StudioBinder · How to Make a Movie Trailer](https://www.studiobinder.com/blog/how-to-make-a-movie-trailer/)

**竖屏短剧**：
[快手研究院微短剧发展研究报告](https://news.iresearch.cn/yx/2026/07/559686.shtml)
· [人民网 · 微短剧高质量发展路径](http://ent.people.com.cn/n1/2024/0418/c1012-40218273.html)
· [第一财经 · 竖屏短剧上桌](https://www.yicai.com/news/102826866.html)
· [爱奇艺微短剧创作方法论](https://news.qq.com/rain/a/20250329A06N7H00)
· [拆解 100+ 部爆款短剧节奏公式](https://www.163.com/dy/article/L30RCS1005340TH8.html)
· [Character App 9:16 框架指南](https://www.character.app/blog/vertical-drama-video-size-9-16)
· [Vertical-First Production Pipeline](https://reliably.live/vertical-first-production-pipeline-from-script-to-short-form)

**一致性与转场**：
[PixMind 角色一致性指南](https://www.pixmind.io/posts/ai-video-character-consistency-guide)
· [invideo 续接锚点](https://invideo.io/faq/what-is-a-continuation-prompt-anchor-and-how-does-it/)
· [Arcloop 角色连续性手册](https://arcloop.ai/handbook/zh-CN/ai-character-bible-drama-production)
· [MindStudio 转场工作流](https://www.mindstudio.ai/blog/ai-video-intros-location-transitions-runway-seedance)
· [Seedance 转场指南](https://www.seedance.tv/blog/seedance-video-transitions-guide-2026)
· [ZOOOP Whip Pan](https://zooop.ai/glossary/camera/whip-pan)

**反例与负面提示词**：
[VIDEOAI.ME · 12 个 Kling 提示词错误](https://videoai.me/blog/kling-ai-prompt-mistakes)
· [VIDEOAI.ME · 负面提示词](https://videoai.me/blog/kling-ai-negative-prompts)
· [QuestStudio · 25 个错误](https://queststudio.io/blog/ai-video-prompt-mistakes-25)
· [PixVerse · 7 个坏习惯](https://pixverse.blog/en/tutorials/ai-video-prompt-mistakes-and-how-to-fix-them/)

## 可信度声明

调研中出现的多个"实测数据"——参考图一致性 24/30 对比纯文字 9/30、加关键帧后首次可用率从
20% 升到 70%、每片段节省 1.8 次重抽——**全部来自工具厂商自己的博客，属自报数据，没有第三方
验证**。这些只作方向性参考，不得进产品文案，也不要写进提示词当作依据。

同样地，本文档区分"官方明文"与"社区实践"不是形式主义：第一节里 Veo 字段名、JSON 提示词、
三家厂商"官方公式"这三处传播错误，都是社区整理被反复转载后当成官方规范的结果。新增规则时
先问一句"这句话的一手来源是谁"。
