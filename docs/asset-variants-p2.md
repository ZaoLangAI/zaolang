# 角色造型 / 场景变体：P2 生产线设计

> 状态：**P2-0 ~ P2-7 已实现并合入 `dev`（2026-10-03）；P2-8 已实现，待第一批上线后合并**。前置：P0 与 P1-1 ~ P1-3 已上线（`dev` @ `a99bc85`，生产同版本），设计见 [P1 设计](asset-variants-p1.md)。
>
> 本文涉及的不变量编号沿用 P1：
>
> | 缩写 | 对应 |
> |---|---|
> | DM | zaolang-data-model |
> | CL | zaolang-creation-library |
> | GJ | zaolang-generation-jobs |
> | MA | zaolang-media-assets |
> | AG | zaolang-agent-gateway |
> | CB | zaolang-credits-billing |
> | FE | zaolang-frontend-ui |

## 1. 为什么要做 P2

P1 把造型 / 变体做成了有外键的子表，但"一张卡要配齐哪些图、怎么一步步做出来"仍然要用户手动拼。2026-10-02 对 `dev` 的代码核对发现以下问题：

| 问题 | 现状（代码位置） |
|---|---|
| 多 pass 任务很脆弱 | `attempt_number` 按任务累计（`nodes.execute_route_score`），第 2 个 pass 起 `quality.evaluate` 的 `attempt_number > MAX_QUALITY_RETRIES` 恒成立，质检不合格就无法重试；后续 pass 失败走 `execute_fail` 全额退款，已出的图不会写回（`asset_output_link` 只在 `done` 之后执行） |
| 补全视角缺少参考 | 同一任务里，侧面 / 背面补全 pass 只用任务原来的 `reference_asset_ids`，不会引用本任务刚生成的正面图；补全提示词却写的是"参考本图生成侧面图"。工作台也已不再发起补全任务（`inline-image-result.tsx`），目前**没有任何界面入口能生成侧面 / 背面图** |
| 生成结果会静默覆盖 | 写回时 `CHARACTER_SHEET` / `VIEW` 会替换同造型同视角的旧条目（`characters.service.append_reference_asset`）。`candidate` 状态存在，但所有写入路径都硬写 `approved`，前端也没有任何地方读它 |
| 没有身份锚点生产路径 | `IDENTITY_PORTRAIT`（定妆照）类型存在，但没有哪种 pass 产出它；锚点由第一张设定图自动充当。`default_subset` 只在锚点是定妆照时才把它带进其他造型，所以**一个空的新造型发起换装生成时拿不到任何参考图**，换装只能靠用户手动勾选 |
| 场景变体只能单轴 | 工作台 `sceneVariantCombos` 一次只能改一个维度（2–4 张），没有多维组合，也没有批量报价 |
| 小缺口 | `VariantPresets.age_stage` 是自由字符串，没人读；`presets_json` 不按造型 / 变体类型校验；`ReferenceResolver` 的 `shot_hint` / `emotion_hint` 接收了但从未使用，也没有调用方传入；JSON 镜像（P1-4）仍待移除 |

**目标**

- 一张角色卡可以按"定妆照 → 设定图 → 侧 / 背视角 → 表情"的顺序做出来，缺什么一键补什么，每一步都以身份锚点为准。
- 生成结果先进候选，由用户定稿；已定稿的图不会被新结果静默替换。
- 场景可以按"光照 × 天气 × 状态 × 年代"矩阵批量出变体，提交前给出准确总价。
- 多 pass 任务部分成功时按交付张数结算，已出的图正常写回。

**不做**（理由见第 12 节）

- VLM 一致性质检、服务端拼版及其 A/B 实验、Seedream 组图复验：顺延到 P3。
- `action_clips` 不并入条目表。
- 白膜（blockout）不在本系列范围内。

## 2. 业界做法与本设计的对应

| 做法 | 代表产品 / 工具 | 借鉴到本设计 |
|---|---|---|
| 用一张干净的人脸图做身份参考，再用权重控制"像不像" | Midjourney `--cref`（V6）/ `--oref` + `--ow`（V7 Omni Reference） | 定妆照作为身份锚点（P2-2）；参考图说明里写清"图1 只取面部与发型"（P2-3） |
| 人脸特征注入，单张证件照式正脸效果最好 | ComfyUI 的 IP-Adapter FaceID、InstantID、PuLID | 定妆照规格：正面、中性表情、均匀柔光、纯色背景、无遮挡（P2-2）。我们走的是云端模型的提示词级参考，不做本地特征注入 |
| 主体库：一个主体由多角度多张图组成，生成时按需挑选 | 可灵（Kling）主体 / 多图参考、Vidu 参考生视频 | P1 的造型 / 条目表已对应；P2-7 按景别 / 情绪挑选 |
| 先出正面，再以正面为参考派生侧 / 背面（turnaround） | 角色设定图、三视图 LoRA 工作流 | 同一任务内，前一个 pass 的产出作为后续补全 pass 的参考图 1（P2-4） |
| 多出几张，人工挑选后入库，再用入库的图作为后续参考或训练集 | Scenario、Leonardo 的 consistent character | 候选 / 定稿流程（P2-1） |
| 自动一致性打分（人脸特征余弦、VLM 评审） | InsightFace / ArcFace 相似度、多模态评审 | 顺延 P3；已决定"只打分并降为候选，不自动重生"（第 12 节） |

## 3. 范围与依赖

```
P2-0 多 pass 部分交付 ─┐
P2-1 候选 / 定稿 ──────┼─ P2-2 定妆照锚点 ─ P2-3 换装 ─┬─ P2-4 补齐缺失
                       │                              └─ P2-6 年龄阶段词表
                       ├─ P2-5 场景矩阵批量
                       └─ P2-7 景别 / 情绪排序（软依赖 P2-2）
P2-8 移除 JSON 镜像（P1-4，放在第二批发布）
```

| 编号 | 分支 | 内容 | 依赖 |
|---|---|---|---|
| P2-0 | `feature/p2-multipass-partial` | 质检重试按 pass 计数；部分交付按张数结算并写回 | — |
| P2-1 | `feature/p2-entry-candidates` | 写回的候选 / 定稿规则、`:approve` 接口、库页面分组与定稿 UI | — |
| P2-2 | `feature/p2-identity-portrait` | 定妆照 pass、锚点优先级、设定图以定妆照为准 | P2-1 |
| P2-3 | `feature/p2-outfit-change` | 换装：造型描述与服装参考注入、空造型的身份参考兜底 | P2-2 |
| P2-4 | `feature/p2-look-fill-missing` | "补齐缺失"：缺口计算、分波提交、任务内视角链式参考 | P2-0、P2-3 |
| P2-5 | `feature/p2-scene-matrix` | 场景矩阵批量生成与批量报价 | P2-0、P2-1 |
| P2-6 | `feature/p2-age-stage` | `age_stage` 封闭词表、按类型校验预设、提示词接入 | P2-3 |
| P2-7 | `feature/p2-reference-ranking` | `shot_hint` / `emotion_hint` 排序 | P2-1 |
| P2-8 | `feature/p2-remove-reference-mirror` | P1-4：迁移 B，移除 `reference_assets` 镜像 | P2-1，且在第一批上线之后 |

每项一个从 `dev` 切出的 `feature/*` 分支、一个 commit，按依赖顺序合并。见第 11 节的实施约束。

## 4. P2-0 多 pass 部分交付

### 4.1 质检重试按 pass 计数

- `_start_next_asset_pass` 已经重置 `route_attempts`，再增加重置 `pass_attempt`；`execute_route_score` 每次尝试时同时累加 `attempt_seq`（全任务，用于对象键）和 `pass_attempt`（本 pass）。
- `execute_quality_check` 调 `quality.evaluate` 时传 `pass_attempt`，不再传 `attempt_number`。`MAX_QUALITY_RETRIES = 1` 的语义变为"每个 pass 最多重试 1 次"。
- 不改图结构，所以不需要模板数据迁移（GJ 第 17 条）。

### 4.2 部分交付

触发条件：任务带资产轴（`asset_kind=character|scene`），某个 pass 最终失败（路由耗尽，或质检不合格且不再重试），且 `asset_outputs` 里已有至少 1 张。

处理：在 `execute_fail` 开头分流到新的 `_finish_partial_asset_job`，**不改图**：

1. 对已交付的输出执行与 `execute_asset_output_link` 相同的写回（抽出共享函数，两处调用）。
2. 结算：`settlement_credits` 增加 `requested_outputs` / `delivered_outputs` 参数，资产任务按 `max(1, reserved * d // N)` 结算，整数运算；`capture` 仍取 `min(实际, 预留)`，余额释放（CB 第 1、3 条）。
3. 任务状态记为 `SUCCEEDED`，`output_asset_ids` 只含已交付的图；SUCCEEDED 事件 payload 带 `delivered_outputs`、`requested_outputs` 和失败 pass 的 `failure_code`。
4. 前端 `job-progress.tsx` / `inline-image-result.tsx`：显示"已交付 d / N 张，未完成部分已退回 X 积分"。

不带资产轴的任务、一张都没交付的任务，仍走原来的全额退款。

### 4.3 测试

- `test_generation_lifecycle.py`：3 视角任务第 3 个 pass 路由耗尽 → 2 张写回、按 2/3 结算、事件带交付数；第 2 个 pass 质检第一次不合格 → 能重试一次。
- `test_settlement_pricing.py`：按交付比例结算的边界值（d=0 不走此路径；N=1；整除与不整除）。
- `tests/concurrency`：账本路径有改动，需覆盖。

## 5. P2-1 候选 / 定稿

### 5.1 槽位与写回规则

**槽位**指同一造型 / 变体里同一类单张位置：

| 类型 | 槽位键 |
|---|---|
| `identity_portrait` | 卡片级（只存在于默认造型） |
| `character_sheet` | (造型, `character_sheet`) |
| `view` | (造型, `view`, 视角) |
| `expression_sheet` | (造型, 表情集合)，表情集合按排序后的 `expressions_json` 比较 |
| `master` | (变体, `master`) |
| 其余（`pose`、`outfit_detail`、`prop`、`shot`、`other`） | 无槽位，累加，一律定稿 |

写回（`asset_output_link`，含 P2-0 的部分交付）时：**槽位里还没有定稿条目就直接定稿，否则写为候选**。不再替换旧条目。

用户手动上传（库页面）仍然直接定稿，并按现有规则替换同槽位；P1 的老接口翻译不变。

### 5.2 候选不设上限

- 候选全部保留，系统从不自动移除，由用户自行删除。
- 为了不让候选挤掉写回，`MAX_ENTRIES_PER_VARIANT` / `MAX_ENTRIES_PER_SKILL` 改为**只统计定稿条目**。候选条目数量不受限。
- 定稿时如果会让定稿数超限，返回 422（与 P1 的手动添加一致）。写回本身只会新增候选或填空槽，因此不会因上限被跳过；填空槽时若定稿数已满，改为写成候选。
- 库页面每个槽位显示候选数，提供"清空本槽候选"的批量删除（二次确认）。

### 5.3 定稿

- 新增 `POST /v1/{characters|scenes}/{id}/entries/{entry_id}:approve`。在同一事务内完成：
    1. 槽位里原来的定稿条目改为候选；
    2. 目标条目改为定稿；
    3. 原定稿条目是锚点时，锚点随之移到新条目（先清后设，满足部分唯一索引）。
- 现有 PATCH `status=approved` 改为走同一个函数；PATCH `status=candidate` 不能作用于锚点（422）。
- 定稿是所有者编辑，按 CL 第 3 条调用 `withdraw_after_edit`。

### 5.4 读路径只认定稿

以下位置只读定稿条目：

- `project()`（兼容投影 `reference_assets`，iOS 与旧调用方）；
- 镜像（P2-8 之前）；
- 自动锚点；
- 未解锁 / 已解锁的公开详情投影。

已经只认定稿的位置不变：`default_subset`，以及买家可用参考（`skill_library.service` 的 `APPROVED` 判断）。

所有者在 `looks[].entries` 里能看到候选；所有者显式勾选候选作为参考（`asset_ids`）仍然允许。

### 5.5 前端

- `asset-variants-sheet.tsx` 的条目网格按类型分组：定妆照 / 设定图 / 视角 / 表情 / 细节·其他（P1 设计第 10 节）。
- 候选条目淡显并带"候选"徽章，操作为"定稿"和"删除"；同槽位的候选与定稿并排显示，方便对比。
- 图片工作台结果卡：写回为候选时提示"已存为候选，去定稿"，链接打开对应卡片的造型面板。写回结果从 SUCCEEDED 事件 payload 的 `filed: [{asset_id, variant_id, entry_id, status}]` 读取。
- 文案走 next-intl（FE 第 9 条）。

### 5.6 测试

- `test_asset_variants_service.py`：槽位判定、空槽定稿 / 有槽候选、上限只统计定稿（大量候选不阻塞写回）、`approve` 交换与锚点迁移、锚点不可降为候选。
- `test_asset_planning.py`：写回不再替换定稿条目。
- `test_asset_variants_api.py`：`:approve` 权限（非所有者 404）、撤下发布。
- 前端 vitest：分组与候选徽章。

## 6. P2-2 定妆照锚点

### 6.1 新 pass

- `GenerationParams.character_portrait: bool = False`。仅 `asset_kind=character` 可用，与 `character_expressions`、`character_outfit_label` 互斥，`character_views` 只能为空或 `[front]`。
- `AssetPass.IDENTITY_PORTRAIT`。`resolve_pass` 在 `character_portrait` 为真时返回它。
- 提示词 `_compose_identity_portrait`：
    - 单人、正面、**头肩构图**（取景到锁骨下方）、中性表情、双眼直视镜头；
    - 均匀柔光、浅灰纯色背景、面部无遮挡（头发、配饰、手不挡脸）；
    - 套用 `apply_visual_medium`。
    - 负面词：多人、多分格、侧脸、夸张表情、强烈阴影、文字水印。
    - `sanitize_enhancements` 对它和表情 pass 一样过滤设定图标记。
- 计价同单张（`requested_output_count` = 1）。

### 6.2 写回与锚点优先级

- 定妆照写回默认造型，`entry_type=identity_portrait`，按 P2-1 的槽位规则定稿或进候选。
- 锚点优先级：已定稿的 `identity_portrait` 高于设定图。定妆照定稿时，如果当前锚点是设定图，就自动改为定妆照；如果当前锚点已经是定妆照，则不动。
- 不加"锚点来源"列：设定图锚点一律视为可被定妆照取代。用户事后仍可手动把锚点设回设定图。
- `default_subset` 已支持"定妆照锚点跨造型带入"，无需修改。

### 6.3 设定图以定妆照为准

- `_compose_character_sheet` 在参考图 1 是定妆照时（由 resolver 写入的 `reference_labels` 判断），前置 `IDENTITY_LOCK_PREFIX`："以参考图1中人物的面部、发型、肤色为准，生成同一人物的设定图……"。
- 与 `OUTFIT_CHANGE_PREFIX` 合并：换装时用一句，不叠两句。

### 6.4 需要保持一致的五处（AG reference-prompts 第 22–31 行）

`planner`、`prompt_builder`、copywriter 的 coach 及其修复、`front/src/lib/characters.ts`。新 pass 要在这五处同步说明。

### 6.5 前端

- 图片工作台角色类型增加"定妆照"输出选项（与表情互斥）。
- 角色库新建角色后，空卡片的造型面板首格提示"先生成定妆照"。

### 6.6 测试

`test_image_asset_prompt_builder.py`（新 pass 文本与负面词）、`test_jobs_asset_kind.py`（互斥校验）、`test_asset_planning.py`（写回类型与锚点切换）、`test_reference_resolver.py`（定妆照锚点进入非默认造型）。

## 7. P2-3 换装

### 7.1 目标造型信息注入

- `reference_resolver.resolve` 在有 `target_variant_id`（角色）时，向 params 写入服务端字段 `target_look = {name, description, age_stage}`。与 `reference_labels` 一样，先 `pop` 掉客户端传入的同名字段。
- `prompt_builder` 的设定图 / 定妆照 / 表情 pass 读取 `target_look`：
    - 名称和描述作为服装描述，替代 `character_outfit_label` 的句子；
    - `OUTFIT_CHANGE_PREFIX` 改为使用造型描述。
- `character_outfit_label` 保留，作为"按名称找或建造型"的快捷方式（P1 第 6.1 节）。

### 7.2 换装的参考图

目标造型为空时，`default_subset` 改为：

1. 卡片的定妆照锚点（已有逻辑）；
2. 没有定妆照时，兜底取默认造型的定稿设定图，标签写为 `角色「林夏」·默认造型·设定图（仅取面部与体型，忽略服装）`；
3. 目标造型里的 `outfit_detail` 条目（用户上传的服装参考），标签 `角色「林夏」·婚礼·服装参考（只取服装）`。

上限仍为 3。参考图说明（legend）因此能告诉模型哪张管脸、哪张管衣服。

### 7.3 前端

- 造型面板"新建造型"表单增加"服装描述"和"上传服装参考"（作为 `outfit_detail` 条目）。
- "在此生成"按钮带上 `variantId`，工作台显示"换装：婚礼"并预览将使用的参考图。

### 7.4 测试

- `test_reference_resolver.py`：空造型有定妆照、空造型无定妆照的兜底、带服装参考。
- `test_image_asset_prompt_builder.py`：`target_look` 注入，并与 outfit label 互斥。
- `test_generation_lifecycle.py`：换装端到端，写回新造型，默认造型的设定图不受影响。

## 8. P2-4 补齐缺失

### 8.1 缺口

一个造型的标准配置：

| 槽位 | 范围 | 说明 |
|---|---|---|
| 定妆照 | 卡片级 | 只在默认造型检查 |
| 正面设定图 | 每个造型 | `character_sheet` |
| 侧面、背面 | 每个造型 | `view` side / back |
| 基础表情 | 每个造型 | 至少一张定稿 `expression_sheet`。缺失时生成**一张**多宫格合集图（一个任务、计 1 张）：默认 neutral、smile、anger、sad、shock、fear，2×3 宫格；用户可在 1–9 个之间增减，宫格按 `EXPRESSION_GRID` 排布 |

只看定稿条目；某槽位只有候选时，显示"有 n 个候选待定稿"，不算缺失，也不重复生成。

### 8.2 接口

`POST /v1/characters/{id}/looks/{look_id}:fill`

- **请求**：`{slots?: [...], expressions?: [...], quality_tier, dry_run}`。`slots` 默认取全部缺口。
- **响应**：
    - `gaps`：缺口与候选状态；
    - `waves`：分波计划，每行 `{slot, params}`；
    - `quote`：全部行的 `quote_for` 之和，与 `quote:batch` 同口径，含 `within_spend_limit` 和 `sufficient`；
    - `submitted`：`dry_run=false` 时本次提交的任务 id。
- **分波**：后一波要用前一波的产出做参考，所以每次只提交依赖已满足的一波：
    1. 第 1 波：定妆照（如果缺）；
    2. 第 2 波：一个视角任务，`character_views` 取缺的 front / side / back；
    3. 第 3 波：表情任务（需要正面设定图或定妆照作参考）。
- **续跑**：前端在一波全部结束后再调一次 `:fill`。缺口每次都按卡片当前状态重新计算，所以调用天然幂等；用户中途离开，下次点"补齐缺失"会从断点继续。
- **扣费**：每个任务独立 `reserve`。报价显示全部波次的总价，并说明"后续波次在提交时扣费"。提交前按总价预检余额和月度上限（CB 第 10、12 条）。
- **约束**：
    - 请求头一个 `Idempotency-Key`，服务端按 `{key}:{slot}` 派生每个任务的键（FE 第 5 条）；
    - 限流用 `generation_submit`，按提交的任务数计数；
    - 所有者以外返回 404。

### 8.3 任务内的视角链式参考

- 视角任务中，`front` pass 产出后，后续 `side` / `back` 补全 pass 在 `_pass_params` 里把这张图放到参考图 1（其余参考顺延，总数仍受 9 和模型上限约束），标签为"本任务生成的正面设定图"。
- 如果造型已有定稿正面设定图且本次不生成 front，补全 pass 由 resolver 把它放在参考图 1。
- 这样补全提示词"参考本图生成侧面图"始终指向正面图。

### 8.4 前端

- 造型面板增加"补齐缺失"按钮：打开对话框，列出缺口（可勾选），显示总报价，提交后显示分波进度。
- 当前一波全部成功后自动开始下一波，不逐波确认（总报价在提交时已展示）；任何一波失败则停下，提示重试。
- 进度复用 `job-progress` 的轮询；任务都在同一张卡上，所以对话框关闭后，库页面刷新即可看到结果。

### 8.5 测试

- 新增 `test_look_fill.py`：缺口计算（含只有候选的情况）、分波顺序、dry_run 报价等于逐行 `quote_for` 之和、续跑幂等、余额不足 402、非所有者 404。
- `test_asset_planning.py`：链式参考位置与标签。
- 前端 vitest：对话框状态机（等待 → 提交 → 下一波 → 完成 / 失败）。

## 9. P2-5 场景矩阵批量

### 9.1 接口

`POST /v1/scenes/{id}/variants:matrix`

- **请求**：`{axes: {lighting?: [...], weather?: [...], state?: [...], period?: [...]}, quality_tier, dry_run}`。值用 P0 词汇表校验，每轴最多 4 个值。
- **单元**：各轴取值的笛卡尔积，每次请求最多 12 个单元。
- **跳过**：已有定稿主图且 `presets_json` 等值的单元；已有候选的单元标记为"有候选"，默认也跳过。
- **容量**：场景卡不再限制变体数量。`MAX_VARIANTS_PER_SKILL`（12，2026-10-05 起为 48）只对角色造型保留；场景卡同时取消 `MAX_ENTRIES_PER_SKILL`，只保留每个变体 24 条的上限。
- 每次请求最多 12 个单元，这是单次提交的大小限制，不是卡片容量；更多组合分几次提交。
- **响应**：`cells: [{presets, label, status: new|exists|candidate, variant_id?}]`、`quote`（同 8.2 口径），以及 `dry_run=false` 时的 `submitted`。

### 9.2 提交方式

- **每个单元一个任务**：走现有单组预设路径（`scene_lighting` 等 + `target_scene_id`），写回按 `presets_json` 找或建变体。
- 一个单元一个任务的好处：失败互不影响、单格可重试，也不依赖 P0 组图。
- **参考图**：新变体为空，`default_subset` 兜底取卡片锚点（主场景主图）。`SCENE_VARIANT_PREFIX` 把建筑结构锁定到参考图 1。
- **不预建变体**：避免失败后留下空变体。
- **扣费与幂等**：
    - 先按总价预检，再逐个 `submit`；
    - 中途失败（例如月度上限竞争）时，返回逐行结果，已提交的任务照常执行；
    - 幂等键派生同 8.2，按 `{key}:{presets 规范化串}`。

### 9.3 前端

- 场景库变体面板增加"批量变体"对话框：四个轴多选，矩阵预览以二维表展示（行列取前两个有值的轴，其余轴分页），已有 / 候选格打标记。
- 变体数量不再受限后，变体面板的标签行改为可按预设筛选的列表（按光照 / 天气 / 状态 / 年代过滤），避免几十个标签挤在一行。
- 显示单元数和总报价，提交后按格展示进度。
- 工作台原有的单轴组图（`scene_variants` 2–4）保留，供快速试几张使用。

### 9.4 测试

- 新增 `test_scene_matrix.py`：笛卡尔积与单次上限、跳过规则、场景卡超过 12 个变体仍可写入、报价求和、部分提交结果、幂等。
- 前端 vitest：矩阵预览与单元计数。

## 10. 收尾项

### 10.1 P2-6 年龄阶段词表

- `vocabulary.py` 新增 `AgeStage = Literal["child", "teen", "youth", "adult", "middle_aged", "elderly"]`，对应童年（6–12）、少年（13–17）、青年（18–29）、壮年（30–44）、中年（45–59）、老年（60+）。
- 新增 `AGE_STAGE_PRESETS`：
    - 提示词示例："年龄阶段：少年（约 13–17 岁），面部更圆润……保持参考图1人物的五官比例与辨识特征"；
    - 负面词约束不要变成另一个人。
- `VariantPresets` 拆为两种：
    - `LookPresets{age_stage}`：只用于造型；
    - `ScenePresets{lighting, weather, state, period}`：只用于场景变体。
    - 服务层按 `kind` 校验，修掉"造型能存场景预设"的缺口。
- `target_look.age_stage`（P2-3）进入设定图 / 定妆照 / 表情 pass 的提示词。
- **数据迁移**：
    - 实施时先只读统计线上 `presets_json.age_stage` 的取值；
    - 能映射到词表的（含中文标签）转为对应值，其余置空，并在迁移日志里计数；
    - 同时清理造型上残留的场景轴和场景变体上的 `age_stage`。
- **前端**：造型表单增加年龄阶段下拉；词表标签加在 `front/src/features/image-assets/vocabulary.ts`。流程为 Literal → `make openapi` → 前端标签（AG reference-prompts 第 35 行）。
- **测试**：词表单测、预设校验、迁移测试、提示词片段。

### 10.2 P2-7 景别 / 情绪参考排序

- `GenerationParams` 新增可选字段：
    - `reference_shot_size`：沿用白膜词表 `blocking.vocabulary.ShotSize`，不新造；
    - `reference_emotion`：`CharacterExpression`。
- **景别来源**：
    1. 显式参数；
    2. 否则 resolver 从提示词的"镜头："行用 `blocking.camera_language.parse_camera_text` 解析。剧本分段视频的提示词由 `script-prompts.ts` 生成，已带这一行，所以剧本批量视频不需要改前端就能生效。
- **排序**（仍受每卡 3 / 2 张的上限）：

| 景别 | 角色 | 场景 |
|---|---|---|
| `extreme_close` / `close` / `medium_close` | 定妆照 → 匹配情绪的表情合集（有 `reference_emotion` 时）→ 正面设定图 | 机位 / 细节 `shot` → 主图 |
| `medium` 或未知 | 现有默认顺序 | 现有默认顺序 |
| `full` / `wide` / `extreme_wide` | 设定图 → 侧 / 背视角 → 定妆照 | 主图 → 机位 |

- 只影响 `variant_id` 或默认选择；显式 `asset_ids` 不重排。
- **前端**：视频工作台的参考图选择器增加可选"情绪"下拉，景别不加 UI。
- **测试**：`test_reference_resolver.py` 覆盖三档景别、情绪匹配、显式勾选不受影响、"镜头："解析。

### 10.3 P2-8 移除 JSON 镜像（P1-4）

**迁移 B**（`YYYYMMDD_HHMM_drop_reference_assets_mirror.py`）：

- upgrade：从角色 / 场景卡的 `params_json` 删除 `reference_assets`（先复制再修改，DM 第 11 条）。
- downgrade：用表数据按 `project()` 重建 JSON。所以迁移 B 可以无损回滚，迁移 A 的 downgrade 前提（JSON 里有全部条目）也随之恢复。这一点写进发布说明。

**代码**：

- 删除 `sync_mirror` 及其在服务内的 9 处调用；
- `catalog.params_json()`、`create_character`、`create_scene` 不再写空的 `reference_assets`；
- `_public_params` 的剥离逻辑保留一个版本，防止残留；
- `skill-mention.ts` 删除读原始 JSON 的兜底；
- 改正 `enums.py`、`_ensure_seeded_reference` 中过时的注释。

**测试**：

- 改写以下断言镜像的测试：`test_asset_variants_service.py`、`test_skill_library_catalog.py`、`test_skill_context.py`；
- 新增迁移 B 的往返测试（upgrade 后 JSON 无此键；downgrade 后与 `project()` 一致）。

**时机**：P1 已在生产运行一个版本。P2-8 放在第二批发布，至少与第一批（P2-0 ~ P2-4）间隔一次上线。

## 11. 数据模型、API、迁移汇总

| 类别 | 变更 | 所属 |
|---|---|---|
| 表结构 | 无新表、无新列 | — |
| 枚举 | `AssetPass.IDENTITY_PORTRAIT`（非持久化） | P2-2 |
| 词表 | `AgeStage`、`AGE_STAGE_PRESETS` | P2-6 |
| 任务参数 | `character_portrait`；服务端写入的 `target_look`；`reference_shot_size`、`reference_emotion` | P2-2 / P2-3 / P2-7 |
| 结算 | `settlement_credits(requested_outputs, delivered_outputs)` | P2-0 |
| 上限常量 | 条目上限只统计定稿；场景卡取消变体数与整卡条目数上限 | P2-1 / P2-5 |
| 接口 | `entries/{id}:approve`；`looks/{id}:fill`；`variants:matrix` | P2-1 / P2-4 / P2-5 |
| 接口 schema | `VariantPresets` 拆为 `LookPresets` / `ScenePresets` | P2-6 |
| 事件 | SUCCEEDED payload 增加 `delivered_outputs`、`requested_outputs`、`filed` | P2-0 / P2-1 |
| 数据迁移 | `age_stage` 规范化；迁移 B | P2-6 / P2-8 |

有接口变更的项都要 `make openapi`，并提交 `back/openapi.json` 和 `front/src/lib/api/schema.d.ts`。部署顺序为先后端、后前端（P0 风险条目）。iOS 只读投影，不受影响；投影只含定稿条目后，iOS 只会少看到候选。

**需要同步的 skill 文档**（`test_skill_freshness.py` 会校验引用的路径与符号）：

- `zaolang-creation-library`：第 9、11 条，加入候选 / 定稿、槽位、锚点优先级；镜像移除。
- `zaolang-generation-jobs › reference-asset-pipeline`：部分交付、链式参考、写回规则。
- `zaolang-credits-billing`：第 11 条的结算例外增加资产任务部分交付。
- `zaolang-agent-gateway › reference-prompts`：定妆照 pass、`target_look`、年龄阶段。
- `zaolang-frontend-ui › reference-studios`：补齐与矩阵对话框、工作台定妆照选项。
- `zaolang-data-model`：镜像移除后 JSON 的说明。

## 12. 已决与顺延（2026-10-02）

**已决**

1. **P2 主线**：生产线 + 候选 / 定稿、场景矩阵批量；收尾项做 P1-4 镜像移除、`age_stage` 词表、景别 / 情绪排序。
2. **写回规则**：槽位为空则定稿，否则进候选；已定稿的图不被静默替换。
3. **VLM 质检的处置方式**（P3 实施时遵循）：只打分，低于阈值的产出降为候选并在界面提示，不自动重生。
4. **`action_clips` 不并入条目表**：只有一条写入路径和一处只读展示，语义是视频动作片段而不是参考图，也不参与 `ReferenceResolver`。等到需要"按造型区分动作片段"时再评估。
5. **多 pass 部分交付**：不改图结构，在 `execute_fail` 分流处理，避免默认模板数据迁移。
6. **候选全部保留**：系统不自动移除候选，由用户删除；条目上限只统计定稿。
7. **基础表情**：补齐时合成到一张多宫格合集图里（默认 6 个，2×3），不逐张生成。
8. **场景变体数量不限**：场景卡取消变体数与整卡条目数上限；角色造型仍有上限（2026-10-05 起 48 个造型、整卡 480 张定稿）。矩阵单次提交最多 12 格。
9. **补齐缺失自动续跑**：上一波成功后自动开始下一波。
10. **定妆照为头肩构图**。

**顺延到 P3**

- **VLM 一致性质检**：需要一个视觉模型绑定。目前 `LlmProviderEndpoint.input_modalities` 的 `image` 只是声明，`failover` 不按它筛选；剧本识图借用的是 copy 智能体的绑定。所以要先补"按模态筛端点"，再做质检节点。
- **服务端拼版 + A/B**：表情宫格和设定图目前都由模型直接画多分格。可以改为逐张单图生成后用 Pillow 拼版（依赖已有 Pillow、imagehash；落盘可参照 `extract_video_frame` 的写对象 + 建 `Asset` 流程）。拼版会让张数和费用成倍增加，需要先做 A/B。
- **Seedream 组图复验**：文档说明 `auto` 模式下张数由模型按提示词决定，`max_images` 只是上限。另外 `output_count` 目前没有接到节点和 router（`execute_provider_generate` 从不设置它），重新启用不只是改 `max_group_outputs`。

## 13. 风险

- **部分交付改变计费语义**：以前"后续 pass 失败 = 全额退款"，现在按交付张数扣费。前端结果卡必须写清已交付张数和退款额。账本路径要跑并发测试。
- **候选和场景变体会持续增长**：没有上限后，卡片详情的响应体和库页面会随之变大。`list_variants` 已用 `selectinload` 一次取回；如果单卡条目上百，再考虑候选分页或按需加载。
- **定稿会撤下已发布卡片**（CL 第 3 条）：对已发布卡片的所有者，这是额外的一步。在定稿按钮上提示。
- **矩阵并发**：一次最多提交 12 个任务，会同时占用队列和供应商并发。提交时按 `generation_submit` 计数，必要时把单次上限调小。
- **锚点自动切换**：定妆照定稿后会取代设定图锚点，剧本和视频的默认参考会随之变化，需要回归剧本批量视频。
- **默认参考变化**：P2-3 的兜底和 P2-7 的排序都会改变任务实际使用的参考图，结果可能与以前不同（符合预期）。在发布说明里写明。

## 14. 开放问题

原列的 5 个问题已于 2026-10-02 确认，见第 12 节第 6–10 条。实施中新出现的问题追加在这里。

## 15. 实施约束

- 每项一个 `feature/*` 分支，从 `dev` 切出，一个 commit。未经用户要求，不 push、不合并。
- 测试使用独立库与 Redis：`TEST_DATABASE_URL=…/zaolang_test_p0img`，`REDIS_URL=redis://localhost:6380/9`。
- 调用 `conda run` 或 `make` 前先执行 `export CONDA_EXE=/opt/homebrew/Caskroom/miniforge/base/bin/conda`。
- 每项至少运行：相关单测与集成测试、`make lint`、`make typecheck`；有接口变更时运行 `make openapi-check`；有账本改动时运行 `tests/concurrency`；涉及前端时运行 vitest 和 `npm run check:messages`。
- 生产部署（单机 124.223.45.115）：只同步本次改动的文件，执行 `make prod-up`，再检查健康状态。生产 SSH 写操作需要用户的权限规则放行。
- 不把任何密钥写进仓库或 skill 文档。
