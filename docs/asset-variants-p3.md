# 角色 / 场景 / 道具图片资产：P3 一致性打分设计

> 状态：**规划，待评审（2026-10-06）**。前置：P2-0 ~ P2-8 已上线；角色库改造 P0–P10 与资产创作 AC-1 ~ AC-10 已合入 `dev` 并上线（`dev` @ `8f95596`）。P2 设计见 [P2 生产线](asset-variants-p2.md)，数据模型见 [P1 设计](asset-variants-p1.md)。
>
> 本文涉及的不变量编号沿用 P1 / P2，另加一项：
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
> | PC | zaolang-platform-config |

## 1. 为什么要做 P3

P2 第 12 节把三件事顺延到 P3：VLM 一致性质检、服务端拼版及其 A/B、Seedream 组图复验。P2 之后 `dev` 变化很大：

- 图片工作台已删除（`d13ce76`），`general` / `cover` 图片在 API 层被拒；
- 资产创作改为在每张卡的工作区里进行（AC 系列：`asset_derive`、`look_fill`、资产图）；
- 角色库改造（P0–P10）加入了造型属性、角色音色和道具卡。

因此本文先按 2026-10-06 的 `dev` 重新核对代码，结论如下。

| 问题 | 现状（代码位置） |
|---|---|
| 没有视觉模型，也选不到 | `LlmProviderEndpoint.input_modalities` 的 `image` 只是声明，不派生任何能力（`back/app/platform_config/schemas.py` 第 748 行注释）。`llm/failover.py` 的 `general_candidates` / `_bound_candidates` 和 `llm/client.py:complete` 都不按模态筛选。模型目录里仅有的两个 general 模型（`glm-5.3-flash`、`qwen3.8-flash`）都只读文本 |
| 唯一的识图调用是碰运气 | 剧本识图（`domain/script_writing/extract.py:_extract_image`）借用 copy 智能体的绑定，以 base64 data URL 发送 `image_url` 片段。端点不支持图像时只能等上游报错 |
| 现有质检看不到图 | `agents/quality.py` 的系统提示词明说 `output` 只有宽高、供应商等元数据，"看不到实际媒体内容"不能判 fail。`run_agent` 只接受字符串 `user_prompt`，不支持图片片段 |
| 写回不比对锚点 | `execute_asset_output_link` → `append_reference_asset` → `asset_variants.service.file_generated` 只按槽位决定定稿或候选。`SkillAssetEntry` 没有分数、标记或元数据列 |
| 新入口都走同一条写回 | `asset_derive`（调整 / 派生 / 多机位）、`look_fill`（补齐缺失）、场景矩阵、全景都提交带 `asset_kind` 的普通任务，经由 `asset_graph` 的 `asset_output_link` 写回；部分交付（`_finish_partial_asset_job`）也复用它。所以**只在写回处接入一次**，就能覆盖所有入口 |

**目标**

- LLM 端点选择按模态筛选。带图片的请求只会发往声明了 `image` 的端点。
- 新增视觉评审智能体：把角色 / 场景 / 道具的生成图与卡片锚点比对，给出 0–100 的一致性分数和问题列表。
- 在写回前同步打分。打分**只做评分，不触发重生**：低于阈值的图以候选写入，并在界面上标出（P2 第 12 节第 3 条）。
- 先以影子模式上线：只打分、不降级，积累分数分布后再按类型定阈值。
- VLM 调用由平台承担：不改报价，也不改结算。

**不做**（理由见第 11 节）

- 服务端拼版 + A/B、Seedream 组图复验：再次顺延，第 9、10 节附设计草案。
- 不自动重生，也不把一致性分数并入现有 `quality_check` 的通过 / 重试判定。
- 不用人脸特征（ArcFace 等）做相似度。

## 2. 业界做法与本设计的对应

| 做法 | 代表 | 借鉴到本设计 |
|---|---|---|
| 用嵌入相似度衡量主体保持 | DreamBooth 评测里的 CLIP-I / DINO 分数；人脸场景常用 ArcFace 余弦 | 不采用。这些方法需要自托管模型，对动漫或风格化画面和场景结构不可靠，也解释不了"哪里不像" |
| 多模态模型按细则打分（VLM-as-judge） | VIEScore 一类的工作：用 VLM 按维度评估条件生成结果 | 采用。按类型给出维度细则，模型逐维打分，总分由 Python 加权计算，不信任模型自报的总分 |
| 人工挑选、系统只做提示 | Scenario、Leonardo 的一致角色流程 | 与 P2 的候选 / 定稿一致：系统只降级和标记，由用户决定是否定稿 |

## 3. 范围与依赖

```
P3-0 按模态选端点 ─┐
                   ├─ P3-1 视觉评审智能体 ─┐
P3-2 存储与配置 ───┴──────────────────────┴─ P3-3 写回前打分 ─┬─ P3-4 前端标记
                                                              └─ P3-5 校准与定阈值
```

| 编号 | 分支 | 内容 | 依赖 |
|---|---|---|---|
| P3-0 | `feature/p3-modality-endpoint-selection` | failover 按输入模态筛选端点；视觉绑定兜底；后台绑定提示；剧本识图随之受益 | — |
| P3-1 | `feature/p3-consistency-judge` | `quality` 角色新增 `consistency` 槽位与种子智能体；`run_agent` 支持图片；纯函数 `consistency.score()` | P3-0 |
| P3-2 | `feature/p3-consistency-storage` | `skill_asset_entries.consistency_json` 列与迁移；配置分区 `asset_consistency`（`off` / `shadow` / `enforce` 与阈值） | — |
| P3-3 | `feature/p3-consistency-writeback` | `asset_output_link`（含部分交付）在写回前打分；`enforce` 时低分以候选写入；任务响应带标记数；超时预算 | P3-1、P3-2 |
| P3-4 | `feature/p3-consistency-ui` | 条目视图返回所有者可见的打分结果；工作区和资产图标出低一致性；定稿时二次确认 | P3-3 |
| P3-5 | `feature/p3-consistency-calibration` | 分布报告脚本、离线标注集评测（兼作视觉模型选型）、阈值落到配置的流程 | P3-3 |

每项一个从 `dev` 切出的 `feature/*` 分支、一个 commit，按依赖顺序合并。见第 14 节的实施约束。

**发布批次**

- 第一批（P3-0 ~ P3-3）：`asset_consistency.mode` 默认为 `off`，上线后除剧本识图的端点选择外没有行为变化。上线后由运营在 `/admin/models` 添加支持图像的端点，在后台绑定视觉评审智能体，再把 `mode` 改为 `shadow`。
- 第二批（P3-4、P3-5）：影子模式积累 1–2 周后运行 P3-5 的报告，定阈值，改为 `enforce`。P3-4 的界面只在 `enforce` 下显示标记，可以与第一批同发，也可以稍后再发。

## 4. P3-0 按模态选择端点

### 4.1 failover

- `failover.general_candidates(config, *, required_modalities=frozenset())`：只保留 `required_modalities ⊆ endpoint.input_modalities` 的端点。`eligible_candidates`、`saturated_candidates`、`_bound_candidates` 透传这个参数。
- `llm_client.complete` / `stream_complete` 从 `messages` 推导所需模态（新函数 `_required_modalities(messages)`：出现 `image_url` 片段即要求 `image`），不新增调用参数。这样剧本识图不用改调用方，就只会发往支持图像的端点。
- `_content_char_len` 目前忽略图片片段，图片不进 token 估算。改为每个图片片段按固定 `IMAGE_PART_TOKEN_ESTIMATE`（1024）计入 `prompt_tokens`，避免 `output_budget` 低估。

### 4.2 绑定兜底

- `agents/base.py:effective_binding` / `_bound_endpoint` 增加 `required_modalities`。智能体绑定的端点（默认与备用）都不满足模态时，**视为未绑定**，从满足模态的共享池里选。这与"绑定的端点已从目录移除则视为未绑定"的现有规则一致，并记一条 `llm_binding_modality_fallback` 警告日志。
- 全池都没有满足模态的端点时，抛出新异常 `NoCapableEndpoint(ProviderTemporaryFailure)`，消息为"未配置支持图像输入的 LLM 端点"。调用方可以单独捕获它：一致性打分记为 `skipped: no_vision_endpoint`，剧本识图沿用现有错误映射。

### 4.3 后台

- `IMAGE_INPUT_SLOTS = {("quality", "consistency"), ("copy", "script_extract")}`（`back/app/agents/slots.py`）。
- 智能体编辑接口：拥有这些槽位的智能体如果绑定了不含 `image` 的端点，响应带 `warnings`，不拒绝保存。这与 `operations_json` 的"只提示"约定一致。
- `front/src/components/admin/models/llm-providers-panel.tsx` 已有模态开关；智能体绑定下拉框为支持图像的端点加"识图"标记。
- 更新 `schemas.py` 第 748 行的注释：`image` 现在是筛选条件。

### 4.4 测试

- `tests/unit/test_llm_gateway_failover.py`：模态筛选；绑定不满足时退回共享池；全池都不满足时抛 `NoCapableEndpoint`；带 `image_url` 的消息只路由到图像端点；token 估算计入图片。
- `tests/unit/test_agent_gateway.py`：`effective_binding` 的模态兜底。
- `tests/unit/test_script_source_extract.py`：剧本识图跳过只读文本的端点。

## 5. P3-1 视觉评审智能体

### 5.1 槽位与智能体

- `PROMPT_SLOTS["quality"]` 新增 `PromptSlot("consistency", "一致性评审", "比对生成图与角色/场景/道具卡锚点的一致程度并打分。")`。
- 在 `back/app/scripts/seed.py` 新增 `ensure_default_vision_agents`，写法同 `ensure_default_enhance_asset_agents`：幂等、只增不改。它创建 `quality` 角色的智能体 `vision-consistency`（视觉一致性评审），并把 `CONSISTENCY_SYSTEM_PROMPT` 发布到 `consistency` 槽位。
- 解析顺序：`find_profile(session, "quality", "vision-consistency")`，没有则用 `quality` 的默认智能体。提示词走 `agent_skills.service.resolve_prompt`，模块常量只用于种子和兜底（AG reference-prompts「Prompt resolution」）。
- 单独设一个智能体的理由：运营可以只给它绑定视觉端点，现有元数据质检仍用便宜的文本端点。

### 5.2 `run_agent` 支持图片

- `run_agent(..., user_content: list[dict] | None = None)`：传入时，user 消息的内容是 `[{"type": "text", ...}, {"type": "image_url", ...}, ...]`，`user_prompt` 作为第一个文本片段。
- `AgentRun` 的记录方式不变：`job_id`、`agent_profile_id`、`prompt_slot="consistency"`、`cost_micro_usd`（`costs.service.llm_call_cost_micro_usd`）。平台成本因此进入现有的运营统计。**不扣用户积分**（第 11 节第 4 条）。

### 5.3 图片准备

新模块 `back/app/domain/image_assets/consistency.py`：

- `prepare_image(session, asset_id, *, max_px)`：
    1. 从对象存储读字节；
    2. Pillow 转 RGB，`thumbnail` 到长边 `max_px`（默认 1024）；
    3. 编码为 JPEG（q=85），生成 base64 data URL。
- 用 data URL 而不用预签名 URL 的理由：
    - 本地 MinIO 的地址供应商访问不到（AG providers 第 2 条）；
    - 与剧本识图的做法一致；
    - 缩放后 token 和费用可控。
- 每次调用两张图：图 1 是锚点，图 2 是待评图。

### 5.4 比对规则

| 卡片类型 | 锚点 | 评分维度（权重） | 不比较 |
|---|---|---|---|
| 角色 | 已定稿的定妆照，否则卡片锚点（`asset_variants.service.identity_portrait` / `anchor`） | 五官与脸型 0.35、发型发色 0.2、肤色与体型 0.15、画风与媒介 0.15、服装 0.15 | 表情、姿态、机位、背景。目标造型不是锚点所在造型时（换装），去掉服装维度，其余维度按比例重新归一 |
| 场景 | `master_or_anchor`（目标变体的主图，否则主场景主图 / 锚点） | 空间结构与布局 0.4、关键陈设 0.3、材质与年代 0.2、画风 0.1 | 本次 `scene_*` 预设与锚点变体不同的轴（光照、天气、状态、年代），以及机位 |
| 道具 | 道具卡主图 / 锚点 | 外形轮廓 0.4、材质 0.25、配色与纹样 0.2、标志性细节 0.15 | `prop_state` 不同时的状态差异，以及机位 |

- 表情合集图按整张评：只看每格的人物身份，忽略表情差异和分格布局。
- 以下情况不打分，状态记为 `skipped`：
    - 卡片没有锚点（新卡的第一张图）；
    - 待评图就是锚点资产；
    - 全景（`panorama`，CL 第 20 条：它从来不作为参考）；
    - 视频产出（`character_action`）。

### 5.5 输出

- 提示词要求输出 JSON：`{"dimensions": {"<key>": 0-100}, "issues": ["…"], "notes": "…"}`。
- Python 端处理：
    1. 校验维度键，缺失的维度按 0 分计并记 `degraded`；
    2. 总分 = 各维度加权平均，取整数 0–100。持久化的数字一律为整数，不用浮点（与 `temperature_milli` 同一约定）；
    3. `issues` 最多 5 条，每条最多 60 字。
- `score(session, *, card, anchor_entry, output_asset_id, context) -> ConsistencyResult`，字段：
    - `status`：`scored` / `skipped` / `failed`；
    - `score`、`dimensions`、`issues`；
    - `anchor_entry_id`、`anchor_asset_id`；
    - `model`、`endpoint_id`、`rubric_version`；
    - `skip_reason`。
- **从不抛异常**：解析失败或调用失败一律返回 `failed`，写回照常进行。这与 `quality.FALLBACK` 的"评估器坏了不能连累用户"相同。
- `RUBRIC_VERSION = 1`。改动维度或权重时递增，P3-5 的报告按版本分组。

### 5.6 测试

新增 `tests/unit/test_consistency_judge.py`，用测试的假网关（`tests/fake_llm_gateway.py`）：

- 三种卡片的维度与权重；
- 换装时去掉服装维度后重新归一；
- 场景忽略不同的预设轴（提示词里列出忽略项）；
- 各类跳过规则；
- JSON 缺键或非法时的降级；
- 调用失败返回 `failed`；
- `prepare_image` 的尺寸上限与格式。

## 6. P3-2 存储与配置

### 6.1 列

`skill_asset_entries.consistency_json`：JSONB，可空。迁移文件为 `YYYYMMDD_HHMM_asset_entry_consistency.py`，时间戳取实施时，排在 `20261008_1000_scene_panorama_entry` 之后。只加列，没有数据迁移。

```json
{
  "v": 1,
  "status": "scored",
  "score": 62,
  "threshold": 70,
  "below": true,
  "mode": "enforce",
  "demoted": true,
  "dimensions": {"face": 55, "hair": 80, "body": 70, "medium": 75},
  "issues": ["脸型偏长", "眉形与锚点不同"],
  "anchor_entry_id": "ske_…",
  "anchor_asset_id": "ast_…",
  "model": "…",
  "rubric_version": 1,
  "scored_at": "2026-10-20T08:00:00Z",
  "owner_approved_at": null
}
```

- 选 JSONB 而不拆列：评分细则会演进，校准查询数量很少，用 `->>` 即可，不加索引。
- 字段含义：
    - `demoted`：只有原本会定稿（空槽）、因低分改为候选时才为真。原本就是候选的图只标 `below`；
    - `owner_approved_at`：所有者定稿一张 `below` 的条目时写入（`approve_entry`），作为 P3-5 校准的"误判"信号。
- **所有者可见、不公开**：`variant_views(approved_only=True)` 的公开 / 解锁投影、`project()`、iOS 兼容投影都不带它。
- **不复制**：`_derive_filing` 的 `copy_from_entry_id`、`set_members`、移动条目（`update_entry` 换造型）都不复制或保留分数到新条目；移动的是同一行，所以分数保留。
- 遵守 DM 第 11 条：先复制再修改。

### 6.2 配置分区 `asset_consistency`

在 `back/app/platform_config/schemas.py` 新增，并加入 `CONFIG_SCHEMAS` / `DEFAULT_CONFIGS`（PC：每个字段都要有默认值）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `mode` | `off` \| `shadow` \| `enforce` | `off` | `off` 不打分；`shadow` 只打分写库，不降级、不显示；`enforce` 低于阈值时降为候选并显示 |
| `kinds` | list[`character` \| `scene` \| `prop`] | 全部 | 按卡片类型开关 |
| `thresholds` | `{kind: {entry_type \| "*": int 0–100}}` | `{}` | 没有阈值的组合永远不算低分。查找顺序：先 `entry_type`，再 `"*"` |
| `max_image_px` | int 512–2048 | 1024 | 送审图的长边上限 |
| `max_outputs_per_job` | int 1–8 | 8 | 单个任务最多打几张，超出的记为 `skipped: budget`；多机位单任务最多 8 个机位 |

- 读取用 `config_service.get_typed`（Redis 缓存 30 秒），改动后台即时生效，不需要发版。
- 后台编辑：`/admin/config/asset_consistency`，沿用通用的历史、差异和回滚。如果 `runtime-config-panel.tsx` 不能按 schema 通用渲染这个分区，就在 P3-2 里补一个小表单。

### 6.3 测试

- 迁移往返；
- 配置的默认值与校验（阈值范围、未知 `entry_type` 返回 422）；
- 公开投影不含 `consistency_json`；
- `approve_entry` 写入 `owner_approved_at`；
- 派生复制不带分数。

## 7. P3-3 写回前同步打分

### 7.1 位置与顺序

在 `execute_asset_output_link` 内分两段执行。部分交付的 `_finish_partial_asset_job` 复用同一个函数，所以也覆盖到。

1. **打分段**（不写库）：
    - 解析目标卡片；
    - 读取写回开始时的锚点；
    - 对 `asset_outputs` 逐张调用 `consistency.score()`，结果按 `asset_id` 存进字典。
2. **写回段**（现有逻辑，每张图一个 savepoint）：`filing` 增加 `consistency`。`mode=enforce`、`score < threshold` 且 `status=scored` 时，`filing["candidate"] = True`。`file_generated` 已有 `candidate` 参数，所以槽位为空也会写成候选，不占锚点（只有定稿条目能成为锚点，CL 第 14 条）。

关键约定：

- **锚点取写回开始时的状态**：同一任务内先写回的图（例如新卡的第一张设定图自动成为锚点）不作为后续输出的锚点。同一任务的产出互不比较，结果因此是确定的。
- 自动新建的卡片没有锚点，全部 `skipped`。
- 先打分后写回，LLM 调用不会落在 savepoint 事务里。
- 打分不改变任务状态：任何打分失败都不让任务失败（GJ 写回规则：写回节点"never fails the job"）。
- 不跳过的情况：`dry_run`、`auto_attach_asset=False`、没有资产轴时整个写回都不执行，打分也随之不执行。

### 7.2 与现有规则的关系

| 规则 | 影响 |
|---|---|
| 不自动重生（P2 第 12 节第 3 条） | 只改写回状态。`quality_check` 的通过 / 重试判定不变 |
| 补齐缺失（CL 第 17 条） | 低分图以候选写入后，槽位显示"有候选待定稿"，不算缺失，`:fill` 不会重新生成，正好符合"不自动重生" |
| 调整修改（CL 第 16b 条） | 调整本来就一律写为候选，照常打分，只用于显示 |
| 定妆照锚点（`prefer_portrait_anchor`） | 低分的定妆照写为候选，不会夺走锚点；所有者定稿后照常接管 |
| 结算（CB 第 3、11 条） | 不变。降为候选的图已交付，按交付计费 |

### 7.3 任务响应与事件

- `GenerationJobResponse.flagged_entries`：读取时派生，写法同 `_candidate_entries_of`（`back/app/api/v1/jobs.py`）。统计本任务 `source_job_id` 下 `consistency_json.below` 为真、且 `mode=enforce` 的条目数。
- SUCCEEDED 事件 payload 增加 `consistency: {scored, flagged}`，只记数量。不新增事件类型（FE 第 18 条）。

### 7.4 时间预算

- `back/app/workers/tasks.py`：当 `mode != off` 且是资产任务时，按 `min(输出数, max_outputs_per_job)` 每张加 `_CONSISTENCY_PER_OUTPUT = {"soft_time_limit": 45, "time_limit": 60}`，仍受 `_IMAGE_GENERATION_CAP` 约束。
- 达到上限时，没打的图记为 `skipped: budget`，不中断写回。打分段在每次调用前检查剩余时间。
- worker 的 LLM 并发沿用现有上限，单任务内逐张串行调用。

### 7.5 测试

在 `tests/integration/test_generation_lifecycle.py` 中，假网关返回固定分数，覆盖：

- `shadow`：写入分数，不降级，`flagged_entries=0`；
- `enforce`：空槽的低分图写为候选、没拿到锚点、`demoted=true`；有定稿时只标 `below`；
- 高分图照常定稿；
- 没有视觉端点：`skipped: no_vision_endpoint`，写回照常；
- 打分失败：`failed`，写回照常；
- 部分交付：已交付的图同样打分；
- 多机位任务超过 `max_outputs_per_job`；
- 同一任务内的自动锚点不作为后续输出的比对对象。

另外：

- `tests/unit/test_look_fill.py`：低分候选不被重新生成；
- `tests/integration/test_asset_derive_api.py`：派生和多机位的产出都打了分。

## 8. P3-4 前端标记 / P3-5 校准

### 8.1 P3-4 前端

- 接口：`AssetEntryView`（`back/app/api/schemas/asset_variants.py`）增加只对所有者返回的 `consistency: {score, below, demoted, issues, mode} | null`。只在 `mode=enforce` 写入的记录里才有 `below`，影子期的分数不下发。然后运行 `make openapi`。
- 工作区和资产图：
    - `front/src/features/asset-workspace/slot-panel.tsx` 和 `front/src/components/asset-graph/` 的节点检查器里，`below` 条目显示"与锚点差异较大"警示徽章（语义色 token，FE 第 7 条）；悬停显示分数和问题列表；
    - `demoted` 的候选再加一句"因一致性低降为候选"。
- 定稿：定稿 `below` 条目时弹二次确认（"该图与锚点差异较大，仍要定稿？"）。确认后后端写入 `owner_approved_at`。
- 任务结果：工作区结果提示读 `flagged_entries`，显示"n 张与锚点差异较大，已存为候选"。
- 文案走 next-intl（FE 第 9 条），运行 vitest 和 `npm run check:messages`。

### 8.2 P3-5 校准与定阈值

- **分布报告**：新增 `back/app/scripts/consistency_report.py`，随镜像发布。在 prod 的 api 容器里执行：

    ```bash
    docker compose -f infra/docker-compose.prod.yml exec api python -m app.scripts.consistency_report --since 2026-10-20
    ```

    它只读数据库，按 `卡片类型 × entry_type × rubric_version` 输出：

    - 样本数，以及 p10 / p25 / 中位数；
    - `skipped` / `failed` 占比；
    - 平台成本合计（`agent_runs.prompt_slot='consistency'`）；
    - 低分且被所有者定稿的条目数；
    - 每档的抽样条目 id，供在后台技能浏览器里人工核对。

    报告只输出 id，不输出 URL 或用户信息。
- **离线标注集**：新增 `back/scripts/eval_consistency.py`，只在本地运行，不进镜像。
    - 数据：40–60 对图片，从种子库和内部测试卡里挑选，人工标注"同一主体 / 不是"；有意加入错配对：不同角色的设定图、同一场景不同建筑。
    - 方法：对选定端点跑 `consistency.score()`，输出正负样本的分数分布和 AUC。
    - 这个脚本同时用来**比较候选视觉模型**。视觉模型的型号在这一步确定（第 11 节第 2 条）。
- **定阈值**：
    1. 用影子期的分布加离线集的分界点，为每个 `kind × entry_type` 选阈值，目标是误降率 ≤ 10%；
    2. 写入 `asset_consistency.thresholds`，`mode` 改为 `enforce`；
    3. 决定和数值追加到第 11 节。

    这一步不改代码。

## 9. 顺延：服务端拼版 + A/B（设计草案）

本节不在 P3 实施，前置是 P3-1（需要用评审来打分）。

### 9.1 现状

- 表情合集和设定图都由模型一次画出多分格：
    - 表情：`_compose_expressions` + `expression_layout`，宫格来自 `vocabulary.EXPRESSION_GRID`；
    - 设定图：`CHARACTER_SHEET_LAYOUT_SUFFIX`。
- 两者都按 1 张计价（`requested_output_count`）。
- 仓库里没有任何 Pillow 拼图代码（Pillow 12.3.0 和 imagehash 4.3.2 已在 `back/requirements.txt` 中）。
- 落盘可参照 `media.service.extract_video_frame`：`s3.put_object` 写对象，再建 `Asset`。区别是拼版产出应走 `register_generated_asset` 的做法（`GENERATION_OUTPUT`、指纹、来源声明），并用 `asset_graph.service.link_job_output` 从各单图连边。
- 补齐缺失（CL 第 17 条）已经单独生成定妆照、正面单人和四个机位。**设定图可以直接用已定稿的单图拼出来，不需要额外生成**；表情拼版则会把张数和费用变成 N 倍（默认 6 倍）。

### 9.2 两个实验臂

| 对象 | A（现状） | B（拼版） | B 的额外成本 |
|---|---|---|---|
| 表情合集 | 一次生成 2×3 宫格 | 6 张单表情特写（1:1，以定妆照 / 正面设定图为参考；单张时可以用每个表情自己的负面词），用 Pillow 按同一宫格拼成 | 约 5 倍积分（标准档 12 → 72） |
| 设定图 | 模型画多分格 | 用已定稿的定妆照、0° 单人、90° / 180° / 270° 机位拼版，色板用 Pillow `quantize` 从图中提取 | 单图齐全时为 0；否则等于补齐单图的费用 |

实验前要先修正表情宫格的比例：`look_fill` 用 16:9（`fill.plan` 和 `asset_variants.py` 的 schema 默认值），工作区和派生用 1:1。否则 A 臂本身不统一。

### 9.3 离线配对评测（已决：不做线上分桶）

- **样本集**：24 个角色，写实 12、动漫 / 2D 12，覆盖性别、年龄段，其中 4 个戴眼镜或有显著配饰。每个角色先定稿定妆照，两臂使用相同的参考和档位（standard）。
- **指标**：
    1. 身份一致：P3-1 评审对每格的分数（A 臂按宫格几何裁切出每一格）。看平均分和最低格分。
    2. 版式缺陷率：格数不对、出现文字或标签、脸被裁切、表情重复。人工按清单检查。
    3. 表情准确率：每格是否是要求的表情。评审加人工抽查。
    4. 盲评偏好：3 名内部评审逐对二选一。
    5. 成本与耗时：积分、平台成本（`agent_runs` 加上 `generation_attempt_cost_micro_usd`）、墙钟时间。
- **采纳标准**：
    - 设定图：B 的偏好不低于 50%，且版式缺陷率不高于 A，即可采纳（成本接近 0）。
    - 表情合集：需要同时满足三条：
        - B 的偏好 ≥ 60%；
        - 最低格分数提升 ≥ 5，或缺陷率减半；
        - 产品确认"按张计价"的报价可以接受。
      否则维持 A。
- **实现落点（采纳后）**：
    - 设定图：新接口 `POST /v1/characters/{id}/looks/{look_id}:compose-sheet`，同步执行、不扣费，结果按 P2-1 槽位规则写成 `character_sheet`；
    - 表情：在 `asset_output_link` 开头合成。不能做成独立节点，因为部分交付路径会绕过它。

### 9.4 前置改动

上述两项采纳后，补齐缺失的波次要改为"定妆照 → 0° 单人 → 机位 → 拼设定图"。机位的来源也不再依赖 `camera_from_sheet`。

## 10. 顺延：Seedream 组图复验（设计草案）

### 10.1 现状（2026-10-06 核对）

- **适配器已经能发组图请求，但没有任何生产路径使用。**
    - `dmxapi_media._build_seedream_body` 在 `output_count > 1` 时发送 `sequential_image_generation: "auto"` 和 `sequential_image_generation_options.max_images`。
    - 张数不足仍按成功处理：`metadata.delivered_outputs` 记实际张数，多出的图放进 `extra_outputs`。
- **`GenerationRequest.output_count` 只在测试里设置。**
    - `execute_provider_generate`、sandbox 和视频分析构造请求时都不带它。
    - `jobs.service.quote_for`、`asset_derive._quote`、`look_fill` 里的 `output_count` 只用于计价，不会传到请求里。
- **router 不检查 `max_outputs_per_call`。** `base.py` 里说"router 只发给支持的能力"的注释已过时；`schemas/jobs.py` 里 `scene_variants` "from a single provider call" 的注释也已过时。
- **成本记账按 1 张算**：`nodes.py` 调用 `generation_attempt_cost_micro_usd` 时没有传 `generated_images`。
- **场景变体组仍然是每个变体一个 pass。**
- live 测试已存在：`back/tests/test_seedream_group_live.py`（`make test-llm`，需要 `DMXAPI_API_KEY`）。

### 10.2 live 检查方案（写任何代码之前）

- **矩阵**：
    - `max_images` 取 {2, 3, 4}；
    - 提示词三种：隐式"一组"、显式"共 N 张，图1…图N"、显式加 1 张参考图；
    - 每格 3 次，共 27 次调用。
    - 按 ¥0.30 / 张（1K）、平均 3 张估算，约 ¥25。
- **记录**：每次调用的 `delivered_outputs`、耗时、实际尺寸，输出 JSON 报告；保留原有的严格断言用例。
- **在 prod 的 api 容器里运行**：镜像不含 `tests/` 和 pytest，密钥只存在数据库的 `llm_providers` 里。做法：
    - 测试在 `DMXAPI_API_KEY` 为空时，用应用会话从 `llm_providers` 读取 DMXAPI 端点。密钥不打印，也不写进仓库；
    - 测试自行把 `s3.put_object` 替换为内存存储，不往生产对象存储写文件；
    - 用一次性容器挂载测试目录，并用 `--noconftest` 跳过本地测试库的夹具：

    ```bash
    docker compose -f infra/docker-compose.prod.yml run --rm -v "$PWD/back/tests:/app/tests" api sh -c "pip install pytest && pytest -m live tests/test_seedream_group_live.py --noconftest -p no:cacheprovider"
    ```

    需要用户的 prod SSH 权限规则放行。
- **判定**：显式提示词下 `delivered == requested` 的比例 ≥ 90%，才另立一项去接入组图：
    1. router 检查 `max_outputs_per_call`；
    2. 场景变体组一次调用多张；
    3. `extra_outputs` 逐张作为 pass 写回；
    4. 张数不足时剩余的 pass 改为逐张生成；
    5. 成本按实际张数记账。

    否则结案：删除闲置的组图代码和过时注释，并在 AG providers 里写明结论。

## 11. 已决与顺延（2026-10-06）

**已决**

1. **P3 只做 VLM 一致性打分**。拼版 A/B 和 Seedream 组图复验顺延，附设计草案（第 9、10 节）。
2. **视觉模型先不定型号**：代码只认端点的 `input_modalities` 是否含 `image`，由运营在后台绑定。型号在 P3-5 用离线标注集比较后确定。
3. **先影子模式，再定阈值**：上线后先只打分、不降级，积累 1–2 周的分布，再按 `kind × entry_type` 定阈值，改为 `enforce`。
4. **写回前同步打分**：在 `file_generated` 之前完成，低分直接以候选写入。不会出现"已定稿又被降级"，也不会出现锚点被低分图抢走。代价是每张图多约 5–15 秒。
5. **平台承担 VLM 费用**：不扣用户积分，报价和结算都不变；成本记在 `agent_runs.cost_micro_usd`。
6. **打分范围**：角色、场景、道具都打。全景和视频产出跳过。
7. **拼版 A/B 用离线配对评测**，不做线上分桶。现有的 flag 分桶不按 flag 加盐，定稿 / 删除也不留事件，线上指标拿不到。
8. 沿用 P2 已决：**只打分、降为候选、在界面提示，不自动重生**。

## 12. 数据模型、API、迁移汇总

| 类别 | 变更 | 所属 |
|---|---|---|
| 表结构 | `skill_asset_entries.consistency_json`（JSONB，可空） | P3-2 |
| 配置 | 新分区 `asset_consistency` | P3-2 |
| 智能体 | `quality` 角色的 `consistency` 槽位；种子智能体 `vision-consistency` | P3-1 |
| LLM 网关 | 按输入模态筛选；`NoCapableEndpoint`；图片 token 估算 | P3-0 |
| 后台接口 | 智能体绑定的 `warnings`（视觉槽位绑定了文本端点） | P3-0 |
| 任务响应 | `flagged_entries`；SUCCEEDED payload 的 `consistency` 计数 | P3-3 |
| 条目视图 | 所有者可见的 `consistency` | P3-4 |
| 数据迁移 | 无（只加列） | — |
| 计费 | 无 | — |

- 有接口变更的项都要运行 `make openapi`，并提交 `back/openapi.json` 和 `front/src/lib/api/schema.d.ts`。部署顺序为先后端、后前端。
- iOS 只读兼容投影，不受影响。
- 默认图（`ensure_default_templates`）不改结构，**不需要 GJ 第 17 条的模板数据迁移**：打分在现有 `asset_output_link` 节点内完成。

**需要同步的 skill 文档**（`test_skill_freshness.py` 会校验引用的路径和符号）：

- `zaolang-agent-gateway`：按模态选端点、`NoCapableEndpoint`、`consistency` 槽位；reference-prompts 的「Prompt resolution」补上视觉智能体。
- `zaolang-platform-config`：`input_modalities` 的 `image` 改为筛选条件；`asset_consistency` 分区。
- `zaolang-generation-jobs › reference-asset-pipeline`：写回前打分、锚点取写回开始时的状态、`flagged_entries`。
- `zaolang-creation-library`：第 14 条补"低一致性以候选写入"；`consistency_json` 只给所有者看，不复制。
- `zaolang-frontend-ui › reference-studios`：工作区的一致性徽章和定稿确认。
- `zaolang-data-model › reference-tables`：新列。

## 13. 风险

- **写回变慢**：每张图多一次视觉调用。多机位任务（最多 8 张）最坏多约 2 分钟。缓解措施：`max_outputs_per_job`、按剩余时间提前跳过、时间预算单独增加（第 7.4 节）。如果影子期观察到 p95 过长，再考虑异步方案（需要处理"定稿后降级"和锚点交还）。
- **误判伤害体验**：`enforce` 下误判会让本该定稿的图变成候选，补齐缺失也不会重新生成。缓解措施：
    - 影子期校准，目标误降率 ≤ 10%；
    - 所有者可以一键定稿；`owner_approved_at` 回流到校准报告；
    - 按 `kind × entry_type` 分别设阈值，没有阈值的组合永不降级。
- **评审对风格化画面不稳**：动漫和低多边形风格下五官维度可能失真。离线集要覆盖这些画风；必要时按画面媒介分阈值，这需要扩展配置键。
- **平台成本**：每张图一次调用（两张图约 2k 输入 token）。影子期报告会给出实际成本，超出预期就收窄 `kinds` 或降低 `max_image_px`。
- **剧本识图的路由变化**：P3-0 之后，没有任何支持图像的端点时，剧本识图直接报"未配置支持图像输入的端点"，不再碰运气发给文本端点。上线前要确认生产已有图像端点，否则这个功能会从"偶尔可用"变成"明确不可用"。发布说明里要写明。
- **删除信号丢失**：`remove_entry` 硬删除，不留事件，所以"低分后被删"的信号无法用于校准。暂时接受，见第 14 节问题 2。

## 14. 开放问题

1. 生产当前的 general 端点里有没有支持图像的？需要只读查看 prod 的 `llm_providers`（需要权限放行）。它决定 P3-0 上线时剧本识图会不会受影响。
2. 校准时是否需要"删除"信号？如果需要，可以在 `remove_entry` 打一条结构化日志，或者加一张轻量的条目事件表。默认不做。
3. 影子期是否要对内部账号提前显示分数（例如按 feature flag），方便人工核对？默认不做，用报告脚本加后台浏览。

实施中新出现的问题追加在这里。

**顺带发现、不在本期范围**（只记录，不排期）：

- 补齐缺失的表情宫格比例为 16:9，与工作区 / 派生的 1:1 不一致（`fill.plan`、`back/app/api/schemas/asset_variants.py` 的 `aspect_ratio` 默认值）。
- `POST /generation-jobs/quote` 与 `quote:batch` 计算 `requested_output_count` 时没有传 `camera_poses`，submit 和 `_requested_outputs_of` 都传了。如果有调用方用通用报价接口给多机位任务报价，会少报。

## 15. 实施约束

- 每项一个 `feature/*` 分支，从 `dev` 切出，一个 commit。未经用户要求，不 push、不合并。
- 测试使用独立库与 Redis：`TEST_DATABASE_URL=…/zaolang_test_p0img`，`REDIS_URL=redis://localhost:6380/9`。
- 调用 `conda run` 或 `make` 前先执行 `export CONDA_EXE=/opt/homebrew/Caskroom/miniforge/base/bin/conda`。
- 每项至少运行：相关单测与集成测试、`make lint`、`make typecheck`。另外：
    - 有接口变更时运行 `make openapi-check`；
    - 涉及前端时运行 vitest 和 `npm run check:messages`；
    - 有迁移时运行往返测试。
- 生产部署（单机 124.223.45.115）：
    - 只同步本次改动的文件：`git diff --name-only <上次部署>..dev | rsync --files-from=-`；
    - 用 `--diff-filter=D` 查出删除的文件，在生产上手动删除；
    - 执行 `make prod-up`，再检查健康状态。
    - 生产 SSH 写操作需要用户的权限规则放行。
- 不把任何密钥写进仓库或 skill 文档。live 测试的密钥在运行时从数据库读取，不打印。
