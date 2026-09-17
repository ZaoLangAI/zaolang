# 「提示词格式」封面美术方向

`back/app/domain/skill_library/catalog.py` 的 `COVERS_PENDING` 里登记了 120 个
`fmt-*` 目录条目（「提示词格式」`FORMAT` 类目全部）还没有封面 JPEG。这份文档是补齐它们
之前的事实基础——别凭感觉现画，先读这里定下的色彩系统、图示原型和逐条映射表。

6 个 key 已有可直接复用的 SVG 源文件，见 `docs/skill-format-covers-samples/`；配套的
可视化预览（色板、9 种图示原型、这 6 张样稿的真实渲染效果）额外发布在
`https://claude.ai/artifact/NqAWdWQ68T9PEi2WJfXYgY`（私有 Artifact，仅供评审参考，
不作为落地规格——落地以本文档 + `skill-format-covers-samples/` 里的 SVG 源为准）。

## 为什么不能沿用照片式封面

`seed_covers/` 里已有的 86 张封面是写实短剧静帧，服务 `lens`/`scene`/`style`/
`character`/`scene_asset`/`cover_asset` 六类——它们都"有画面可拍"。`FORMAT` 类目讲的是
**怎么写提示词**，不是拍什么：「三要素最小式」没有一个可以拍下来的镜头，硬配一张写实
剧照只会是文不对题的假图，违背 `front/src/components/media/poster.tsx` 顶部注释定的
规矩——"the design forbids placeholder art, so a missing cover renders as an honest
empty surface ... rather than as fake imagery"。

解法是换一套诚实的图示语言：不假装是照片，而是像摄影/剪辑规范手册的插图页，用几何图形把
"三个槽位""一个运镜""左右对齐"这类结构性规则画出来。**封面本身不含标题文字**——
`front/src/components/skills/skill-card.tsx:86` 已经把 `skill.title` 单独渲染在封面下方，
图像只负责讲清这条规则的"形状"，这一点与现有 86 张照片封面（同样不在照片里烧字）保持一致。

## 技术规格

- 画布 `1280×720`（16:9，与 `Poster` 组件 `aspect="video"` 一致）。
- 统一底色 `#14171a`，叠加一层轻微径向渐变（中心 `#1a1e22`→边缘 `#0e1013`）增加纵深，
  不要用照片式的颗粒/晕影，保持扁平、编辑排版的质感。
- 顶部 6px 纯色系统条 `#ff795b`（产品品牌珊瑚色），是这 120 张封面唯一共享的"这是格式类目"
  标记——分类徽章和标题已经由 UI 渲染，图内不再重复文字标签。
- 每条按下表归入的规则组，使用该组主色绘制图示线条/填充。
- **产出格式**：仓库内没有 `rsvg-convert`/`cairosvg`/`resvg` 等 SVG 转码工具，
  `CatalogSkill.cover_path()`（`catalog.py:138-141`）又硬编码只认 `<key>.jpg`。落地路径是：
  手写 SVG → 用 headless 浏览器截图导出 JPEG → 存为
  `back/app/domain/skill_library/seed_covers/<key>.jpg` → 从 `COVERS_PENDING`
  里删掉这个 key → 跑 `test_ensure_catalog_skills_backfills_a_cover_for_every_entry`
  确认这条不再被判定为缺封面。

## 规则组配色

| 组前缀 | 规则组 | 主色 |
| --- | --- | --- |
| `frame-` | 取景构图 | `#5b7a99` |
| `hook-` | 开场钩子 | `#d94a4a` |
| `action-` | 动作描述 | `#e0952b` |
| `vertical-` | 竖屏专属 | `#2f9e8f` |
| `camera-` | 运镜语法 | `#5b62c9` |
| `light-` | 光影参数 | `#d9b23c` |
| `audio-` | 声音分层 | `#8b5fbf` |
| `transition-` | 转场衔接 | `#3aa8c9` |
| `lock-` | 一致性锁定 | `#7a8088` |
| `teaser-` | 预告剪辑 | `#c9457a` |
| `guard-` | 提交前自检 | `#4caf6e` |

## 九种图示原型

120 条规则按"讲的是哪种结构"归入下面 9 种可复用版式之一，而不是每条单独发明构图——
这样才可能被规模化生产，也让用户扫过整墙卡片时能读出规律。

| 原型 | 说明 | 典型使用场景 |
| --- | --- | --- |
| `FORMULA` 公式槽位 | 横排若干标签槽 + 连接箭头/分隔线 | 按顺序列组件的"公式类"规则（三要素、五槽式、六件套…） |
| `TIMELINE` 节拍时间轴 | 横向节拍条，标出关键刻度/波峰 | 开场钩子、计数节拍、能量曲线等时序规则 |
| `VECTOR` 方向矢量 | 一条或几条箭头表达方向/轴线 | 运镜方向、视线轴、进出画、单轴限定 |
| `SAFEZONE` 竖屏安全区 | 手机剪影 + 高亮区块 | 仅用于 `vertical-` 组与两条留白类规则 |
| `CHAIN` 连续性锁链 | 多个相同小卡片 + 等号/链接符 | `lock-` 组的跨镜头一致性规则 |
| `GAUGE` 参数仪表 | 比例条/刻度盘，把形容词换成可读数值 | 光比、焦段、色温、字数配额等量化规则 |
| `COMPARE` 对照改写 | 左右两格，✗ 抽象写法对 ✓ 具体写法 | "别写形容词，写可见证据/参数"一类规则 |
| `CHECKLIST` 自检清单 | 提交前的扫描动作 | `guard-` 组里真正是"自检动作"的条目 |
| `FOCUS` 取景框聚焦 | 十字准星圈住单一主体/物件 | 物件特写、单主体独占、局部聚焦类规则 |

## 共享图形词汇

为保证 120 张封面出自同一套系统而非各自发挥，图示内部统一用这些几何符号，不使用具象插画：

- 圆形 = 主体/人物
- 箭头（直线+箭头头） = 动作/运镜移动
- 方形 = 场景/道具/地点
- 三角形 = 镜头/取景
- 菱形 = 光
- 手机圆角矩形剪影 = 竖屏画幅
- 两个方块 + 等号/链接线 = 跨镜头一致（继承）
- ✓ / ✗（勾线/交叉线） = 对/错、留/删
- 正弦波折线 = 音频/声音

## 逐条映射表

按 `catalog.py` 里的分组顺序排列，`图示要点`是给实际画 SVG 的人（或后续脚本）的最小指令，
不是最终文案。

### 取景构图 `frame-`（主色 `#5b7a99`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-frame-minimal-core` | 三要素最小式 | FORMULA | 3 槽：主体/动作/场景，箭头连接，无多余槽位 |
| `fmt-frame-five-slot-video` | 五槽视频式 | FORMULA | 5 槽，前 3 实框后 2 虚框（镜头/光影为增量层） |
| `fmt-frame-camera-first` | 摄影优先倒装式 | FORMULA | 槽位顺序调换，"镜头/景别"槽提到最前并高亮 |
| `fmt-frame-eleven-section` | 分项十一段式 | FORMULA | 11 个小槽密排成网格，部分槽标"可省略"虚化 |
| `fmt-frame-prose-plus-blocks` | 散文加标签块式 | FORMULA | 顶部一条长散文条 + 下方 3 个标签块（摄影/动作/台词） |
| `fmt-frame-key-value-block` | 键值块式 | FORMULA | 2 个键值卡片：`# 主体` / `# 要求` |
| `fmt-frame-motion-block` | 运动独立成块式 | FORMULA | 2 块并列：静态描述块 / 运动描述块，中间箭头分隔 |
| `fmt-frame-constraints-tail` | 约束收尾式 | FORMULA | 正文槽位序列 + 末尾一个高亮"约束"标签 |
| `fmt-frame-three-sentence` | 三句配额式 | TIMELINE | 3 句节拍条，每句下方词数刻度 50–80 |
| `fmt-frame-word-budget` | 篇幅配额式 | GAUGE | 单段字数仪表，刻度区间 80–120 |

### 开场钩子 `hook-`（主色 `#d94a4a`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-hook-open-mid-conflict` | 首帧冲突式 | TIMELINE | 时间轴起点即冲突高点，无铺垫段 |
| `fmt-hook-one-line-identity` | 一句话身份反转式 | TIMELINE | 起点对话气泡 + 12 词以内刻度 |
| `fmt-hook-object-ecu` | 悬念物件特写式 | FOCUS | 十字准星圈住物件图标，人物图标虚化在后 |
| `fmt-hook-charge-to-camera` | 冲向镜头急停式 | VECTOR | 主体由远及近三级放大 + 收束急停线 |
| `fmt-hook-direct-address` | 直视镜头开口式 | FOCUS | 锁定机位符号 + 正对镜头的视线箭头 |
| `fmt-hook-status-drop` | 极致反差落差式 | COMPARE | 同格内左右两态：举杯手 vs 僵住手 |
| `fmt-hook-sound-first` | 声音先入式 | TIMELINE | 波形先行，画面图标延迟半拍出现 |
| `fmt-hook-cold-open` | 中断式冷开场 | TIMELINE | 时间轴从中段截断处起始，无起点标记 |
| `fmt-hook-visible-countdown` | 可见倒计时式 | GAUGE | 倒计时表盘/进度条仪表 |
| `fmt-hook-three-signal-open` | 首两秒三信号式 | FORMULA | 3 槽：脸/冲击/台词，压在 2 秒刻度内 |

### 动作描述 `action-`（主色 `#e0952b`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-action-one-beat-reaction` | 一动作一反应式 | TIMELINE | 2 拍：动作波峰 + 收束波谷 |
| `fmt-action-body-part` | 身体部位级式 | FOCUS | 十字准星圈住手指/下颌局部 |
| `fmt-action-counted-beats` | 计数节拍式 | TIMELINE | 编号刻度 1-2-3，每格一次动作 |
| `fmt-action-relative-pacing` | 相对节奏副词式 | TIMELINE | 节拍间用波浪连接符代替精确刻度 |
| `fmt-action-emotion-externalized` | 情绪外化式 | COMPARE | ✗ 情绪词划掉 → ✓ 生理信号图标（低头/攥拳） |
| `fmt-action-speed-evidence` | 速度物理表征式 | COMPARE | ✗ "快"字划掉 → ✓ 尘土/拖影图标 |
| `fmt-action-enter-exit-frame` | 入画出画式 | VECTOR | 箭头从画面一侧入、另一侧出 |
| `fmt-action-physical-contact` | 受力接触式 | FOCUS | 准星圈住接触点（掌心贴面） |
| `fmt-action-single-active-subject` | 单主体独占式 | FOCUS | 一个高亮主体 + 多个灰色静止剪影 |
| `fmt-action-hold-tail` | 动作留白收尾式 | TIMELINE | 动作波峰后接一段静止延长条 |

### 竖屏专属 `vertical-`（主色 `#2f9e8f`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-vertical-shot-size-codes` | 标准景别缩写式 | FORMULA | 阶梯状嵌套取景框 ECU→EWS，逐级标注 |
| `fmt-vertical-overlay-safe-area` | 遮挡安全区式 | SAFEZONE | 手机剪影，中央安全框 + 四边 UI 占位标记 |
| `fmt-vertical-caption-band` | 底部字幕留白式 | SAFEZONE | 手机剪影，底部横带高亮为字幕安全区 |
| `fmt-vertical-medium-close-first` | 中近景优先式 | SAFEZONE | 手机剪影内主体占大半，角落小图标示远景例外 |
| `fmt-vertical-depth-layers` | 三层纵深式 | SAFEZONE | 手机剪影内前中后三层色块 |
| `fmt-vertical-two-shot-stagger` | 双人错位式 | SAFEZONE | 手机剪影内两个头像上下错位而非并排 |
| `fmt-vertical-over-shoulder` | 竖屏过肩式 | SAFEZONE | 手机剪影，近侧主体压底部，上方留负空间 |
| `fmt-vertical-eyes-upper-third` | 上三分之一眼位式 | SAFEZONE | 手机剪影 + 上三分线 + 眼位标记点 |
| `fmt-vertical-angle-four` | 角度四态式 | VECTOR | 四向机位角度图：平视/仰/俯/荷兰角 |
| `fmt-vertical-focal-length` | 焦段与景深式 | GAUGE | 焦距刻度盘 24mm–85mm + 景深虚化条 |

### 运镜语法 `camera-`（主色 `#5b62c9`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-camera-one-move` | 一镜一运镜式 | VECTOR | 单一方向箭头 + "只此一个"标记 |
| `fmt-camera-separate-sentence` | 运镜与动作分写式 | FORMULA | 2 独立槽：动作句 / 运镜句 |
| `fmt-camera-term-direction-speed` | 术语加方向加速度式 | FORMULA | 3 槽：术语/方向/速度 |
| `fmt-camera-bilingual-term` | 中英双标式 | FORMULA | 中文术语卡 + 括注英文术语 |
| `fmt-camera-framing-vs-motion` | 镜头语言与运镜分槽式 | FORMULA | 2 槽：景别视角 / 推拉摇移 |
| `fmt-camera-relational-verb` | 关系动词衔接式 | VECTOR | 两条同速箭头以连接线绑定同步 |
| `fmt-camera-stage-reveal` | 阶段揭示式 | TIMELINE | 分阶段揭示条，每阶段露出新内容 |
| `fmt-camera-locked-off` | 锁定机位式 | VECTOR | 三脚架图标 + 锁定符号，零位移线 |
| `fmt-camera-handheld-micro-drift` | 手持微抖式 | VECTOR | 细微波浪箭头 + 振幅刻度（厘米级） |
| `fmt-camera-move-plus-texture` | 主运镜加质感式 | FORMULA | 运镜槽 + 质感修饰槽（浅景深图标） |

### 光影参数 `light-`（主色 `#d9b23c`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-light-named-source` | 命名光源式 | FOCUS | 准星圈住具体光源图标（台灯/霓虹/屏幕） |
| `fmt-light-key-direction` | 光位方向式 | VECTOR | 光线箭头从指定方位射向主体 |
| `fmt-light-ratio` | 明暗比式 | GAUGE | 主光/补光矩形比例条 + 数值比 "4:1" |
| `fmt-light-adjective-to-parameter` | 形容词转光参数式 | COMPARE | ✗ "电影感的光" → ✓ 4 个参数芯片 |
| `fmt-light-high-low-key` | 高低调式 | GAUGE | 明暗基调滑块（高调/低调两端） |
| `fmt-light-continuity-across-shots` | 光向跨镜一致式 | CHAIN | 多个镜头小卡片重复同一光向箭头 |
| `fmt-light-material-nouns` | 材质纹理名词式 | COMPARE | ✗ "质感很好" → ✓ 材质色块（哑光/拉丝/风化木） |
| `fmt-light-time-of-day-anchor` | 时段锚定式 | GAUGE | 时段刻度盘（黄金时段/正午/蓝调/深夜） |

### 声音分层 `audio-`（主色 `#8b5fbf`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-audio-explicit-declaration` | 显式音频声明式 | COMPARE | ✗ 留空自动填充 → ✓ 显式波形句 |
| `fmt-audio-three-layers` | 三层音频式 | FORMULA | 3 层堆叠条：对白/环境底噪/音效 |
| `fmt-audio-line-budget` | 台词长度配额式 | GAUGE | 字数/秒仪表（中文 3–4 字/秒） |
| `fmt-audio-dialogue-block` | 独立对白块式 | FORMULA | 画面块 + 独立对白块分离 |
| `fmt-audio-speaker-label` | 说话人标签式 | CHAIN | 多行台词重复同一说话人标签 |
| `fmt-audio-voice-six` | 人声六件套式 | FORMULA | 6 槽：台词/情绪/语调/语速/音色/口音 |
| `fmt-audio-sfx-after-trigger` | 音效跟随触发式 | TIMELINE | 触发画面图标紧接音效波形 |
| `fmt-audio-explicit-silence` | 显式静音式 | COMPARE | ✗ 默认配乐 → ✓ 静音图标 + 环境底噪线 |

### 转场衔接 `transition-`（主色 `#3aa8c9`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-transition-whip-direction` | 甩镜方向加模糊式 | VECTOR | 方向箭头 + 强烈横向拖影线 |
| `fmt-transition-match-pair` | 同向配对式 | CHAIN | 两镜头卡片，同方向箭头对齐连接 |
| `fmt-transition-late-chaos` | 末尾崩坏容忍式 | TIMELINE | 前段平稳，尾段标出"允许崩坏区" |
| `fmt-transition-match-cut` | 匹配剪辑式 | CHAIN | 两卡片同形状/同屏幕位置高亮重叠 |
| `fmt-transition-occluder-pass` | 穿越遮挡式 | FOCUS | 前景遮挡物图标推近至满屏 |
| `fmt-transition-light-wipe` | 光效擦除式 | VECTOR | 光带扫过箭头，末端过曝为白 |
| `fmt-transition-first-last-frame` | 首尾帧过渡式 | CHAIN | 首帧卡片 ↔ 尾帧卡片，虚线路径连接 |
| `fmt-transition-empty-plate` | 纯运镜空镜式 | FOCUS | 空环境图标 + 缓慢运镜箭头，无人物 |
| `fmt-transition-single-axis` | 单轴运动式 | VECTOR | 单一轴线箭头（水平/垂直/纵深三选一） |
| `fmt-transition-verb-forward` | 转场动词前置式 | VECTOR | 过程箭头贯穿两端，而非两个静止端点 |

### 一致性锁定 `lock-`（主色 `#7a8088`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-lock-identity-block` | 身份锚定段式 | CHAIN | 身份文字块在多帧间逐字复制 |
| `fmt-lock-verbatim-reuse` | 措辞逐字复用式 | CHAIN | 同场景措辞标签重复出现 |
| `fmt-lock-one-ref-one-job` | 一图一职责式 | FORMULA | 参考图芯片各自标注职责（服装/场景/节奏） |
| `fmt-lock-ref-numbering` | 素材指代语法式 | FORMULA | 编号芯片：图1/图2/视频1 |
| `fmt-lock-named-label` | 标签定义复用式 | FORMULA | 命名标签定义一次，后续多处引用 |
| `fmt-lock-name-subject-plus-motion` | 点名主体加动作式 | FORMULA | 2 槽：主体名 + 动作，外观留白（来自参考） |
| `fmt-lock-changes-only` | 只写变化式 | COMPARE | ✗ 全量重述 → ✓ 仅变化量高亮 |
| `fmt-lock-palette` | 色板锚定式 | GAUGE | 3–5 色色板条，跨镜头重复 |
| `fmt-lock-light-direction` | 光向锁定式 | CHAIN | 多帧重复同一光向箭头符号 |
| `fmt-lock-wardrobe-state` | 服装状态锁定式 | CHAIN | 多帧重复同一服装图标（含破损细节） |
| `fmt-lock-hair-state` | 发型状态锁定式 | CHAIN | 多帧重复同一发型状态图标 |
| `fmt-lock-prop-position` | 道具位置锁定式 | CHAIN | 多帧重复同一道具位置图标 |
| `fmt-lock-eyeline-axis` | 视线轴线锁定式 | VECTOR | 180 度线示意图，机位固定同侧 |
| `fmt-lock-screen-direction` | 银幕方向锁定式 | VECTOR | 出画箭头（左）↔ 入画箭头（右）镜像 |
| `fmt-lock-handoff-frame` | 衔接帧锁定式 | CHAIN | 上一段尾帧 = 下一段首帧，完全重叠标记 |
| `fmt-lock-ground-wetness` | 地面状态锁定式 | CHAIN | 地面纹理图标在多帧间累积不减少 |
| `fmt-lock-makeup-damage` | 妆面损耗锁定式 | CHAIN | 泪痕/血迹图标只增不减，箭头单向 |
| `fmt-lock-time-of-day` | 时段推进锁定式 | GAUGE | 时段刻度盘单向推进（不可回退） |
| `fmt-lock-weather-grade` | 天气连续锁定式 | GAUGE | 天气强度仪表保持恒定或单向变化 |
| `fmt-lock-body-carryover` | 体位承接式 | CHAIN | 上一拍结束姿势 = 下一拍开始姿势 |
| `fmt-lock-injury-progression` | 伤情推进锁定式 | CHAIN | 伤情图标单向加重，标位置（左/右） |
| `fmt-lock-crowd-density` | 背景人数锁定式 | GAUGE | 人群密度仪表保持恒定刻度 |
| `fmt-lock-camera-height` | 机位高度锁定式 | VECTOR | 机位高度水平线跨镜头保持一致 |
| `fmt-lock-focal-length` | 焦段锁定式 | GAUGE | 焦距刻度盘全场保持同一刻度 |
| `fmt-lock-color-temperature` | 色温锁定式 | GAUGE | 色温渐变条固定同一位置 |
| `fmt-lock-audio-bed` | 环境声底锁定式 | CHAIN | 环境波形在多帧间重复 |
| `fmt-lock-distance-between` | 人物间距锁定式 | GAUGE | 距离刻度（步数）保持或单向缩短 |
| `fmt-lock-object-count` | 物件数量锁定式 | GAUGE | 可数物件计数器跨镜头保持恒定 |

### 预告剪辑 `teaser-`（主色 `#c9457a`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-teaser-energy-dip` | 能量回落式 | TIMELINE | 能量曲线：高→回落→再攀升 |
| `fmt-teaser-first-act-only` | 不剧透素材式 | GAUGE | 进度条只填至 40%，后段灰化 |
| `fmt-teaser-question-line` | 疑问句留白式 | COMPARE | 问号气泡 ✓，答案气泡打叉 ✗ |
| `fmt-teaser-cut-at-peak` | 峰值截断式 | TIMELINE | 能量曲线在峰值处硬切为黑 |
| `fmt-teaser-title-safe-band` | 标题安全区留白式 | SAFEZONE | 底部纯色暗块，预留给后期标题 |
| `fmt-teaser-seamless-loop` | 无缝循环式 | CHAIN | 首帧=尾帧，循环箭头首尾相接 |
| `fmt-teaser-montage-ratio` | 快切配额式 | TIMELINE | 密集短刻度，每格一个瞬间 |
| `fmt-teaser-genre-anchor` | 对标品类锚定式 | FOCUS | 品类标签图标作为锚点 |

### 提交前自检 `guard-`（主色 `#4caf6e`）

| key | 标题 | 原型 | 图示要点 |
| --- | --- | --- | --- |
| `fmt-guard-positive-phrasing` | 正向约束替代式 | COMPARE | ✗ 划掉的抖动线 → ✓ 打勾的稳定线 |
| `fmt-guard-negative-field` | 独立负面框式 | FORMULA | 独立字段芯片：仅裸名词，非否定句 |
| `fmt-guard-short-negative-list` | 精简负面词表式 | GAUGE | 负面词计数仪表，刻度上限 5–8/12–15 |
| `fmt-guard-conflict-check` | 互斥指令自检式 | CHECKLIST | 清单勾选，标出互斥项冲突红线 |
| `fmt-guard-occlusion-audit` | 遮挡自检式 | FOCUS | 遮挡层后的物体轮廓虚化自检 |
| `fmt-guard-no-container-params` | 容器参数不入正文式 | COMPARE | ✗ 时长写入正文 → ✓ 移至参数面板图标 |
| `fmt-guard-adjective-to-shootable` | 形容词换可拍参数式 | COMPARE | ✗ "高级感" → ✓ 焦段/景深/光向等参数芯片 |
| `fmt-guard-caption-leak` | 字幕泄漏防治式 | SAFEZONE | 底部干净带 + 招牌文字虚化处理 |

## 已渲染样稿

以下 6 个 key 已经按本规格产出可用的 SVG 源与渲染预览（见配套 Artifact），可直接作为
其余 114 条的实现参照：`fmt-frame-five-slot-video`、`fmt-hook-charge-to-camera`、
`fmt-vertical-caption-band`、`fmt-lock-wardrobe-state`、`fmt-light-ratio`、
`fmt-guard-positive-phrasing`。

## 未覆盖的另外两批待办

`COVERS_PENDING` 里还有 104 个可拍摄条目（24 个 `frame-`/`light-`/`stage-`/`method-`
canvas 静帧 + 80 个 `drama-` 剧情/情绪静帧），走的是完全不同的路径——真实调用生成服务
产出写实静帧，而不是本文档这套图示语言。那批不在这次美术方向设计范围内。
