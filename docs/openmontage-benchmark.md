# OpenMontage 对标分析

> 对标对象：[calesthio/OpenMontage](https://github.com/calesthio/OpenMontage)（AGPLv3，分析基于 HEAD `08e2151`，2026-09-05）。
> 分析方式：12 路只读调研（OpenMontage 架构、产品与 UI、zaolang 能力地图，以及 9 个领域逐项对标），每条结论对照 `.cursor/skills` 中对应 skill 的不变量编号；合规与测试相关结论经二次抽查确认。
>
> **许可说明**：OpenMontage 采用 AGPLv3。本文只借鉴其设计思路，**不复制任何代码**进入本仓库。

不变量缩写：GJ = zaolang-generation-jobs，AG = zaolang-agent-gateway（AGR = 其 reference.md），CB = zaolang-credits-billing，CV = zaolang-canvas，ED = zaolang-editor-drama，MA = zaolang-media-assets，CA = zaolang-compliance-audit，LL = zaolang-domain-licensing-lineage，DS = zaolang-discovery-search，PC = zaolang-platform-config。

## 1. 摘要

- **总判断**：zaolang 在工程硬度（账本、状态机、续跑、过期回收、路由硬过滤）、多租户、后台与测试分层上全面领先。OpenMontage 值得借鉴的是 **"剧本 → 成片"闭环的产品设计**（结构化分镜、表演指导、自动混音、成片体检、生产看板）和几项**工程防护**（网络守卫、指令完整性测试、契约测试）。
- **不借鉴**：7 维 provider 打分公式、区间报价、看画面评审等，与 zaolang 不变量直接冲突。
- **已核实的风险**（详见第 6 节）：
    1. 声音克隆与真人肖像参考**没有任何授权强制**；
    2. 导出文件本身没有 AI 生成标识；
    3. 后端测试在当前配置下可能写入真实腾讯 COS 桶；
    4. media-assets skill 与代码存在漂移。

**P0 清单**（本轮实施范围，口型同步暂缓）：

| 类别 | 项 |
|---|---|
| 合规与测试安全 | 声音/肖像授权强制；AI 生成标识写入导出文件；测试存储与网络守卫；skill 保鲜测试 |
| 核心创作闭环 | 剧本 → 一键粗剪；字幕自动折行；角色声线 + 表演指导；剧本确定性 lint；分镜关键帧确认环；批量报价 + 月度消费上限；单集生产看板 |
| 质量与稳定 | 跨作业媒体熔断；导出后体检；自动闪避 + 响度归一 |

## 2. 两个项目的本质差异

| | OpenMontage | zaolang |
|---|---|---|
| 形态 | 单机开源工具；IDE 编码 agent（Claude Code、Cursor 等）**本身就是编排器**，运行时不调用 LLM；Python 只提供约 136 个工具与校验 | 多租户 SaaS；服务端 Agno agent + Celery DAG + 积分账本 |
| 管线 | 13 条 YAML 管线（`pipeline_defs/*.yaml`）：research → proposal → script → scene_plan → assets → edit → compose → publish，每阶段产出 schema 校验的 JSON 工件 | 文案创作 → 断点 → 批量生成角色/场景/视频/配音 → 时间线编辑器 → 浏览器导出 → 发布/分发 |
| 强制力 | 只有人审闸门与 checkpoint 写入在代码中强制；SEND_BACK、修订上限、预算追踪器基本只存在于提示词或测试 | 账本、状态机、续跑、过期回收、路由硬过滤全部由代码强制 |
| 成片 | 服务端 Remotion / HyperFrames / FFmpeg | 浏览器 WebCodecs + mediabunny（桌面 Chrome/Edge） |
| UI | 只读 Backlot 看板，操控全靠聊天 | 完整 Web 应用：工作室、画布、剧本、编辑器、后台 |

## 3. 分领域对标

### 3.1 编排 · 人审闸门 · 评审回路 · 预算

对照 skill：generation-jobs、agent-gateway、credits-billing、canvas。

| 功能点 | OpenMontage | zaolang | 结论 |
|---|---|---|---|
| 阶段定义 | YAML 清单声明 skill、产物、审查要点、成功标准、是否人审，由 `pipeline_manifest.schema.json` 校验 | 可视化 DAG（`workflows/defaults.py`、`registry.py`、`graph.py::validate`），模板有版本、提交时锁定 | zaolang 更灵活，无需改 |
| 工件校验 | `lib/checkpoint.py`：completed/待人审阶段必须带规范工件并通过 schema | 节点间 `ctx.state` 无类型约束 | P2：节点 `output_schema` |
| 人审闸门 | 写入层强制：人审阶段写 completed 必须 `human_approved=True`，否则 GATE VIOLATION；前序未完成即拒绝；管线名写错 fail-closed | 只有追问挂起与画布 Agent 待确认；普通生成作业无"先审方案再生成"闸门 | P1：通用 `approval_gate` 节点（复用追问挂起，GJ #1） |
| 续跑与回放 | 临时文件 + 原子替换，旧版本归档 `history/`，Backlot 回放 | 外部任务 checkpoint + `resume`、`fast_retry`、SSE 断点续传、路由回放、逐节点 AgentRun 回放 | zaolang 更强 |
| SEND_BACK / 修订上限 | 只写在 EP 提示词里；修订上限 reviewer 写 2 轮、EP 写 3 次，自相矛盾 | 质检只有 通过/重试/失败 | P2：质检输出修改建议 |
| 评审严重度 | critical/suggestion/nitpick/investigation；无修复方案的 critical 降级 | 只有通过/失败 + 三项评分；最多重试 1 次 | P2：`findings` 分级，无修复方案不触发付费重试（AG #11 只指向元数据） |
| 决策日志 | append-only，记录备选与置信度；但 `approval_policy` 类别不在 schema 枚举内 | 选路轨迹记淘汰原因（AG #4）；分辨率降级只在事件里 | P2：只追加决策表，评分只展示（AG #2） |
| 预算 | `cost_tracker.py`：estimate→reserve→reconcile、observe/warn/cap、单次审批阈值；**只被测试调用**，未接入工具链 | 账本预留/扣款/释放唯一约束，余额条件写在 SQL WHERE（CB #1/#2/#4）；无用户级上限 | **P0：月度消费上限**（条件写进 `_apply` WHERE） |
| 区间报价 | 按参考片估算 + 1.3× 重试缓冲，给低/高区间 | 报价即价格（CB #4），重试成本平台吸收 | 不借鉴 |
| 追问 | creative-intake：一次一问、最多 7 问、区分用户明说与推断 | `questions.py` 最多 4 题，资产类关闭追问 | P2：标注 `inferred_fields` |

**不借鉴**：首次使用供应商审批与"未经同意不换供应商"（AG #1）；备选评分排序（AG #2）；agent 自建脚本（AG #5）；文件型 checkpoint 与整体覆写的成本日志（无并发控制与租户隔离）。

### 3.2 剪辑 · 合成渲染 · 字幕 · 成片质检

对照 skill：editor-drama、media-assets、frontend-ui。

| 功能点 | OpenMontage | zaolang | 结论 |
|---|---|---|---|
| 时间线模型 | `edit_decisions.schema.json`：浮点秒，cut 带 in/out、speed、layer、transform、字符串转场 | 整数 tick（120000/秒），关键帧带 easing，闭集转场（ED #1/#25） | zaolang 更严谨 |
| 转场 | Remotion 单片段淡到背景色，并非两画面叠化 | 同轨重叠双层混合（`compositor.ts` `resolveOverlap`） | zaolang 更正确 |
| 字幕生成 | 逐词时间戳切条（每条 ≤8 词、每行 ≤42 字符）+ 纠错词表 | whisper-1 句段级，人工审核后写入（ED #26） | P1：审核面板切分 + 热词表 |
| 字幕排版 | 分页、逐词高亮，中文专门处理 | `drawCaptions` 单行不换行，竖屏长句出画 | **P0：自动折行（≤2 行）** |
| SRT/VTT | 可导出 sidecar | `ports.ts` 已定义 `'sidecar'`，`export-panel.tsx` 写死 burned | P1 |
| 渲染引擎 | 提案阶段锁定，禁止静默换引擎 | 单一浏览器运行时（ED #12） | 服务端渲染不做（ED #12/#9） |
| 渲染前校验 | 交付承诺运动比例、幻灯片风险分 | `export-precheck.ts` 只查空白帧与出画 | P1：补字幕溢出、转场重叠、黑色空隙、超规格时长 |
| 渲染后体检 | ffprobe 时长偏差、抽帧黑帧、volumedetect 静音与削波 | 只要求 ffprobe 能读出时长 | **P0：导出后体检**（仅提示事件，不回滚终态，ED #29） |
| AI 剪辑 | edit-director 产出完整剪辑决策表 | `editor_planner` 输出 ≤40 条命令，apply 时才校验 | P1：预演 + 节奏软规则 |

**不借鉴**：浮点秒时间线（ED #1）、开放字符串转场（ED #25）、`slideshow_risk`/`delivery_promise`（面向解说片的静图启发，对全视频短剧无意义）、`_tokenize` 英文正则转写比对（会剔除全部中文）、`video_trimmer` 默认 codec copy（不帧精确）、自动 ASR→字幕（ED #26）。

### 3.3 音频全链路

对照 skill：generation-jobs、agent-gateway、media-assets、editor-drama。

| 功能点 | OpenMontage | zaolang | 结论 |
|---|---|---|---|
| 角色声线 | 文字层 `voice_map` | `characters/service.py` 写入 `extra.character_voice_profiles`，**但没有任何 provider 读取**；批量配音整批只用一个 voice | **P0：角色绑定声线** |
| 表演指导 | `script.schema.json` 的 `voice_performance`、`delivery_cues`；provider 映射与先试听门槛 | TTS 请求只发 model/input/voice；`tts-pro` 多一个 emotion | **P0：表演指导透传**（GJ #14 只增不改默认） |
| 发音词典 | `pronunciation_guides` | 无 | P1 |
| 时长对账 | 实际时长 >1.15× 计划即 SEND_BACK 让剧本删字 | provider 返回 `duration_ms` 但不对账 | P1：标红并建议删字，由用户确认 |
| 声音克隆 | ElevenLabs 专业克隆需验证；fish_audio 复用 `reference_id` | fal 一次调用克隆+朗读，`custom_voice_id` 被丢弃；**无授权校验** | **P0：授权强制**（第 6 节）；P1：克隆声线存到角色 |
| 混音 | sidechaincompress ducking（ratio 9、attack 200ms、release 500ms）、loudnorm −16 LUFS | 每层 GainNode + 音量关键帧；无压缩、无响度处理 | **P0：自动 ducking（写音量关键帧）+ 导出响度归一**（ED #19 预览/导出同源） |
| BGM / SFX | 曲库、Pixabay、Freesound；SFX 靠导演文档 | 只有生成（music-3.0、minimax-music、ElevenLabs SFX） | P2：授权曲库、SFX 候选、节拍吸附 |

**顺带发现的既有缺陷**：导出音量在关键帧之间是阶梯而非渐变；`toAudioLayer`/`buildClipLayer` 把音量钳到 ≤1，200% 关键帧不生效。

**不借鉴**：Piper 本地 TTS（中文差、绕开计费）、本地曲库与 Freesound 检索（授权风险）、后端 ffmpeg 混音（违反 ED #19）、tts 打分公式（AG #1）、librosa 全套节拍分析。

### 3.4 剧本 · 提案 · 分镜 · 风格 · 技能分层

对照 skill：editor-drama、agent-gateway、canvas。

| 功能点 | OpenMontage | zaolang | 结论 |
|---|---|---|---|
| 同质化检测 | `variation_checker.py` 8 项代码检查（景别占比、连续同景别、静止镜头比、空洞词占比等） | 规则只写在 copywriter 提示词里，无事后检查 | **P0：剧本确定性 lint**（纯代码、只提示、与提示词共享词表） |
| 多概念提案 | `proposal_packet` ≥3 个概念，差异度检查 | 只出一份稿 | P1：先出 3 个 logline |
| 分镜字段 | `shot_language`、`shot_intent`、`narrative_role`、`hero_moment` | camera 块自由文本 | P1：断点可选 `role`/`hero`（只加字段，CV #13） |
| 剧本结构 | 段落起止秒、表演提示、发音 | 五色块（scene/action/camera/dialogue/breakpoint） | P1：dialogue 块加 `emotion`（与音频 P0 合并） |
| 风格手册 | `styles/*.yaml` + schema + 对比度检查，taste 三旋钮 | 30 条 STYLE 技能以 `prompt_suffix` 形式存在 | P1：剧集级风格手册（CV #47 不加 GenerationParams 字段） |
| 技能分层 | 工具 → 导演手册 → 技术包，纯 markdown | ~310 条技能、@ 提及、自动匹配、付费解锁、AgentSkill 版本化 | zaolang 更完整 |

**不借鉴**：调研与联网（AG #5）、提案内供应商排名（AG #1）、每阶段强制停等、templated/atelier 模式、英文枚举 `shot_language` 作生成参数（CV #47）、稳定场景 id（会推翻 CV #13 前提）。

### 3.5 Provider 契约 · 选择 · 降级 · 缓存

对照 skill：agent-gateway、platform-config、generation-jobs。

OpenMontage 的 `BaseTool` 契约有约 30 个字段，但多数是"写给 agent 看的声明"：`retry_policy`、`idempotency_key()`、`find_fallback()` 基本没有运行时调用方，全仓没有熔断，轮询是进程内阻塞 while 循环。zaolang 的异步检查点（Beat 每 15s 查一次、租约、2h 上限）、硬过滤与统一错误码更扎实。

| 功能点 | 结论 |
|---|---|
| 跨作业熔断 | OpenMontage 无；zaolang 只有 LLM 熔断，媒体端点"未建"（AG #1 原文）→ **P0：媒体熔断作为硬过滤**（二元过滤、留痕，AG #2/#4） |
| 错误分类 | zaolang HTTP<500 一律 INVALID_RESPONSE → P1：`error_class` 子分类（顶层三码不变） |
| 契约测试 | OpenMontage 参数化遍历全部工具 + socket 断网 → P1：跨协议契约测试 |
| 选择理由 | P1：intent_router 输出 `alternatives[{provider, why_not}]`，仅展示 |
| 供应商覆盖 | P1：Kling 官方、火山 Ark Seedance；P2：即梦、混元、ComfyUI、Veo、Runway |

**不借鉴**：7 维加权公式、preferred 容差、数值 task_fit（AG #1/#2、PC #7）；进程内阻塞轮询；从 env 推导可用性（AG #9）；静态 fallback 名单；本地硬链接片段缓存；provider 内自动改时长；`__init_subclass__` 隐式包装。

### 3.6 角色一致性 · 口型 · 动画 · 画面增强

对照 skill：media-assets、generation-jobs、canvas。

| 功能点 | OpenMontage | zaolang | 结论 |
|---|---|---|---|
| 角色设定 | 结构化 JSON（表情、动作、道具），不出图 | 多分区设定图 + 介质锁定 + 角色库 | zaolang 领先 |
| 跨镜头一致性 | 逐镜原样重复 3–6 个外观属性 | 9 槽参考图 + `fmt-lock-*` 规则 + seed；尾帧衔接已撤回 | P1：身份描述块确定性注入、手动"用上一段尾帧" |
| 口型同步 | `kling_lip_sync`：先识别人脸、多人必须显式选脸、可指定音频区间 | 无 | P0 候选，**本轮暂缓**（待选定可商用云端供应商，AGR #15） |
| 画面增强 | 本地 Real-ESRGAN、CodeFormer、rembg | 仅 MiniMax-H3 重生成升 2K | P1：导出统一 LUT；P2：云端超分/抠像 |

**不借鉴**：SVG rig / GSAP / ink-theater / AnimatedDrawings（面向卡通涂鸦）；本地 GPU 工具（AG #6；Wav2Lip 官方权重非商用）；continuity 加权公式（AG #1）；Blender/Three.js 世界。

### 3.7 素材分析 · 授权合规 · 溯源 · 发布

对照 skill：discovery-search、media-assets、compliance-audit、domain-licensing-lineage、editor-drama。

| 功能点 | OpenMontage | zaolang | 结论 |
|---|---|---|---|
| 参考片拆解 | 5 维结构化拆解，不适用维度必须写 N/A，产出喂给下游 | 一次视觉模型调用，只把 `composed_prompt` 带到下游 | P1：扩展字段 + 导入分镜 |
| 语义检索 | CLIP 512 维 + MMR 多样性 | `search/embeddings.py` 仍是 256 维哈希占位 | P1：真实 EmbeddingProvider（DS #3/#4/#5） |
| 授权元数据 | `asset_manifest` 记 license/来源（自由文本，不强制） | Asset 无授权字段 | P1：Asset 授权字段冻结进快照（LL #2） |
| 声音/肖像授权 | 全仓无 consent/likeness 机制 | **无强制**（第 6 节） | **P0** |
| AI 标识 | 仅透传服务商水印开关 | 发布有用户声明勾选，导出文件无标识 | **P0** |
| 导出包 / 平台规格 | `export_bundle`、9 个平台预设 | 抖音/快手 OAuth 发帖；规格只配了抖音 | P1：导出包、补快手/TikTok/Shorts/Reels |
| 本地化配音 | localization-dub 管线（先字幕、保护词表、时长容差、先样音） | 只有 `caption_language` 字段 | P1（依赖授权 P0） |
| 二创血缘与版税、内容安全 | 无 | zaolang 独有且完善 | 保持 |

**不借鉴**：yt-dlp 抓任意 URL（MA #9 与版权风险）、本地 torch CLIP 文件语料、屏幕录制与公共档案源、自由文本授权、本地 `exports/` 目录。

### 3.8 可观测 · 测试 · 评测 · CI · 上手

对照 skill：admin-ops、admin-statistics、testing-qa、ci-release、local-env。

zaolang 在事件入库（JobEvent/ProviderAttempt/AgentRun + OTel）、后台、测试四层、pre-commit lint 上明显领先；OpenMontage 的 bench/replay/视觉基准多为半成品（golden 场景写死作者本机 Windows 路径）。

| 项 | 结论 |
|---|---|
| 网络/存储守卫 | **P0**（第 6 节） |
| skill 保鲜测试 | **P0**：引用路径、make 目标、队列列表、上传用途与 MIME 白名单自动核对 |
| prompt/agent 评测集 | P1：确定性部分进 `make check`，`make eval-llm` 走 live |
| 指令完整性 | P1：覆盖 planner/safety/quality/intent_router 的 SYSTEM_PROMPT，并与 `fake_llm_gateway.py` 共享约束常量 |
| 模拟作业 demo | P1：`make demo-job` |
| IDE 入口 | P1：`CLAUDE.md`/`AGENTS.md` 一行 stub 指向 zaolang-overview |

**不借鉴**：JSONL 事件 + 吞错（审计需与业务同事务）、GitHub Actions（ci-release #8）、`py_compile` 式 lint。

## 4. UI / 交互对标

OpenMontage 唯一的 GUI 是只读 Backlot 看板（FastAPI + watchfiles → SSE，原生 ES modules），完全由磁盘上的 checkpoint、工件与事件日志推导；审批需回到聊天中回复。

| 主题 | OpenMontage | zaolang | 结论 |
|---|---|---|---|
| 全局进度 | 阶段轨道 ✓/◉/◈/✕ + 抽屉 | 分散在剧集徽标、剧本页一行完成数、单作业阶段点 | **P0：单集生产看板** |
| 分镜总览 | 胶片条，卡片宽 ∝ 时长，take 数、HERO、成本徽标 | 断点虚线 + chip；剧集页两列海报网格无顺序/时长 | **P0**（并入看板） |
| 审批点 | 按工件类型定制面板，「Approval unlocks X」，跳过闸门审计 | 批量对话框有报价；画布 plan→报价→确认 | P1：确认闸门面板 |
| 花费 | 页头计量条（75%/90% 变色） | 余额只在 /create 页 | P1 → 并入看板「你在本集已花 / 可用」 |
| 决策可解释 | 决策日志（只显示最新、revised） | 只显示模型名；降档不可见 | P1：决策卡（不露供应商名） |
| 长任务等待 | LIVE / STALLED（10 分钟无活动）、诚实占位 | 进度 + 阶段 + 推理流；**无停滞检测** | P1：`jobLiveness` |
| 上手 | 按能力分级给 3 条起步 prompt（聊天内） | 空状态单按钮 | P1：起步三连 |
| 主题 / 可访问性 / i18n | 内联颜色、`div onclick`、英文写死 | 两层 token、三态主题、WCAG AA、Cmd+K、三语 | zaolang 更完善 |

**单集生产看板布局草图**：

```
第3集 · 雨夜重逢   ◉生成中2 ◈等你确认1   你在本集已花 1,240 / 可用 8,600 ▓▓░
✓剧本─✓角色4/4─◉场景3/5─◉分镜6/9─○配音0/12─○剪辑─○成片─○发布
[S01#0 8s T2][S01#1 6s ◉][S02#0 未定时长 ⚑缺角色卡][S03#0 12s ◈] →
```

所有数据来自现有接口：剧本回合、角色/场景关联计数、断点绑定、配音 key、剪辑、导出、发布状态；实时更新复用通知中心，不新开 SSE（每用户 ≤8 流）。

**UI 侧不借鉴**：羊皮纸/放映室主题 + localStorage（theming #1/#4）；Courier Prime 稿纸作默认剧本视图（无中日字形）；"回聊天批准"（扣费须为带幂等键的按钮）；整体时间回放；抽屉原始 JSON 与决策日志露出供应商名；`$` 拼接金额（i18n #5）；`EventSource` 整页重拉（不能带 Bearer、绕过流配额）。

## 5. 统一路线图

### 5.1 需决策点与默认值

| 决策 | 默认 |
|---|---|
| 服务端渲染 | 不做（ED #12 单一浏览器运行时、#9 导出免费） |
| 视觉质检 | 不做（AG #11），由 ffmpeg 体检覆盖 |
| 一键粗剪遇到已有「主剪辑」 | 新建名为「粗剪」的 cut，重复点击复用 |
| 口型同步 | 暂缓，选型后单独分支 |
| 真人肖像判定 | 上传时用户声明 |
| 系列级生产汇总 | 先做单集，系列级待聚合接口 |

### 5.2 P0（本轮实施，分支 `feature/openmontage-p0`，每项独立提交）

1. 测试存储与网络守卫
2. skill 保鲜测试 + media-assets skill 修正
3. 声音克隆 / 真人肖像授权强制
4. AI 生成标识（MP4 元数据 + 可选角标 + provenance 记录）
5. 字幕自动折行
6. 剧本确定性 lint
7. 剧本 → 一键粗剪
8. 单集生产看板
9. 角色声线 + 表演指导
10. 自动 ducking + 响度归一 + 音量两处缺陷修复
11. 跨作业媒体熔断
12. 导出后体检
13. 批量报价 + 月度消费上限
14. 分镜关键帧确认环

### 5.3 P1 / P2

见各领域小节中标注为 P1、P2 的条目；按领域汇总为：编排与预算（approval_gate、报价明细）、剪辑与字幕（切分、sidecar、预检、planner 预演）、音频（时长对账、试听、发音词典）、剧本与风格（3 提案、role/hero、风格手册、追问）、角色（身份块、尾帧、介质、参考槽提示、LUT）、Provider（错误子分类、契约测试、alternatives、Kling/Ark）、素材与发布（参考片拆解、语义检索、授权字段、导出包、平台规格、本地化）、UI（确认面板、停滞检测、决策卡、起步三连）、工程（评测集、指令完整性、demo、IDE 入口、vitest 进 `make check`）。

## 6. 已核实的风险与 skill 漂移

### 6.1 声音克隆 / 肖像授权无强制（当日已修复）

首次审计时，声音克隆与真人肖像参考缺少服务端强制的授权校验：`AssetConsent` 记录已定义但业务链路从未读取，理论上可以为任意音频/肖像素材发起生成而不触发同意检查。依据：《互联网信息服务深度合成管理规定》第十四条（编辑他人人脸、人声须取得单独同意）。

修复：`app/domain/consent/service.py` 新增服务端强制校验，声纹样本或标记 `depicts_real_person` 的参考图在提交生成任务时会被拒绝，直到存在对应类型的有效 `AssetConsent`。详见 `zaolang-compliance-audit` 不变量 #9。本节仅保留结论供追溯，不再列出具体触发路径。

### 6.2 导出文件无 AI 生成标识

发布流程已要求用户勾选 AI 生成声明（`back/app/api/v1/drafts.py` 的 `ai_disclosure_confirmed`），但编辑器导出链路不写入任何标识。mediabunny 1.29.1 支持 `Output.setMetadataTags` 写 MP4 元数据。依据：《人工智能生成合成内容标识办法》。不得宣称已做 C2PA 签名（MA #7）。

### 6.3 测试可能写入真实 COS

`back/.env` 设置 `STORAGE_BACKEND=tencent_cos`，`back/tests/conftest.py` 只设置 `APP_ENV=test`，`app/config.py` 对 test 无存储覆盖，`app/storage/factory.py` 的 `get_backend()` 无测试替身；测试只逐个 patch `s3.presign_get`。约 12 个测试文件直接调用 `put_object`/`head_object`，会打到真实桶。

### 6.4 skill 漂移

- media-assets skill 写"13 种上传用途"，实际为 14 种（新增 `voice_sample`）。
- media-assets 不变量 #2 的 MIME 白名单漏写 `audio/mpeg`、`audio/wav`。
- 其余 357 条 skill 路径引用中仅 1 条失效（运行时文件 `infra/.env.prod`），make 目标与 Celery 队列列表一致。

## 7. 附：OpenMontage 自身值得注意的问题

引用 OpenMontage 设计时需注意：

- `docs/ARCHITECTURE.md` 标注 2026-03-28 更新，工具数量已过期，也未提及 Backlot。
- `config.yaml` 的 `llm` 配置段在运行时未被使用；`lib/providers/` 为空目录。
- `tools/cost_tracker.py` 只被测试调用，没有接入工具执行链。
- 修订轮次规则自相矛盾（reviewer 2 轮 vs EP/管线 3 次）；`approval_policy` 类别不在 `decision_log` schema 枚举内。
- CI 只有一个 Python job，`make lint` 只对 4 个文件做 `py_compile`。
