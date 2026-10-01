# 角色造型 / 场景变体：P1 数据模型设计

> 状态：P1-1（表与服务）、P1-2（任务集成）已实现；P1-3、P1-4 待做。前置：文生图 P0 已上线（`dev` @ `5adb138`），包括：
>
> - 表情合集图、造型名 label、场景预设；
> - 参考图勾选（`character_ref_selection` / `scene_ref_selection`）；
> - 参考图说明（legend）；
> - 场景变体逐张生成。
>
> 本文涉及的不变量编号：
>
> | 缩写 | 对应 |
> |---|---|
> | DM | zaolang-data-model |
> | CL | zaolang-creation-library |
> | GJ | zaolang-generation-jobs |
> | MA | zaolang-media-assets |
> | AG | zaolang-agent-gateway |

## 1. 为什么要做 P1

P0 在不改表的前提下，用 `params_json["character"|"scene"]["reference_assets"]` 里每个条目的 `label` 模拟了"造型 / 变体"。这个做法已经到头：

| 问题 | 现状 |
|---|---|
| 造型不是一等对象 | 造型只是条目上的一个字符串，无法给造型写服装描述、设默认、排序或改名。改名要逐条改 label |
| 容量 | 角色最多 12 条、场景最多 8 条，按层级淘汰。一个主角有 3 套造型 × 三视图 + 表情图，就已经放不下 |
| 无法按"造型"引用 | 剧本、视频只能逐个 asset id 勾选（`character_ref_selection`），无法表达"第 3 场林夏穿婚礼造型" |
| 场景变体没有结构 | 变体的光照、天气、状态、时期只存在于 label 文字里，无法按预设查询或复用 |
| 一致性与引用安全 | JSON 无外键：资产被删后会留下悬空条目。`media.service._is_shared` 不认技能参考，作品删除可能连带删掉角色参考图 |
| 读路径分散 | 画布 `_first_reference_asset_id` 和前端 `firstSkillReferenceAssetId` 直接读原始 JSON，绕过了服务层 |

**目标**

- 造型 / 变体成为有外键、有约束的子表，与 `CreationSkill` 的生命周期一致。
- 生成任务、剧本链接、写回、参考图说明都能"按造型 / 变体"工作。
- 现有 API 和 iOS 不破坏。

**不做**

- 不迁移 `action_clips`（视频片段，独立关注点，仍留在 JSON 中）。
- 不在 P1 处理白膜。
- 不在 P1 做按景别 / 情绪自动选图的完整策略（只留接口）。

## 2. 概念模型

```
CreationSkill（category=character | scene_asset，不变：权限、发布、售卖、审核的单位）
 ├─ anchor_entry_id → 身份锚点（角色定妆照 / 场景主图），每个技能至多 1 个
 └─ SkillAssetVariant  ×N   角色叫"造型 look"，场景叫"变体 variant"
      ├─ is_default（每个技能恰好 1 个）
      ├─ name / description / presets_json / sort_order
      └─ SkillAssetEntry ×N  （一张参考图 / 视频）
           entry_type、view、expressions、label、status（候选 / 定稿）
```

- **一个技能 = 一张角色卡 / 场景卡。** 这一层保持不动：所有权、发布、定价、解锁、`uq_creation_skills_owner_character_title`、画布 `binding_skill_id`、剧本 `character_ref_id` / `ref_id` 都继续指向 skill id。
- **造型 / 变体是卡内结构。** 不单独发布、不单独售卖；解锁一张卡就获得卡内全部造型。
- **条目是图片的角色定位。** 同一个 asset 在同一造型内只出现一次，可以出现在不同造型里（例如同一张定妆照）。

## 3. 表结构

新表都放在 `back/app/models/skill_library.py`（与 `CreationSkill` 同模块），并从 `models/__init__.py` 导出。

### 3.1 `skill_asset_variants`（前缀 `skv`）

| 列 | 类型 | 约束 / 说明 |
|---|---|---|
| `id` | String(40) | `id_column("skv")` |
| `skill_id` | String(40) | FK → `creation_skills.id`，`ondelete=CASCADE`，not null，有索引 |
| `kind` | String(16) | `look` \| `scene_variant`。CHECK 约束；由服务层按技能类别写入 |
| `name` | String(40) | not null。`UNIQUE (skill_id, name)` |
| `description` | Text | 可空。造型的服装 / 配饰描述，或变体说明，≤2000 |
| `presets_json` | JSONB | not null，默认 `{}`。场景变体存 `{lighting, weather, state, period}`（P0 词汇表）；造型存 `{outfit_label?, age_stage?}` |
| `is_default` | Boolean | not null，默认 false。部分唯一索引 `uq_skill_asset_variants_default` ON (`skill_id`) WHERE `is_default` |
| `sort_order` | Integer | not null，默认 0 |
| `created_at` / `updated_at` | | `TimestampMixin` |

另加 `UNIQUE (id, skill_id)`，供条目表的复合外键引用（见 3.2）。

### 3.2 `skill_asset_entries`（前缀 `ske`）

| 列 | 类型 | 约束 / 说明 |
|---|---|---|
| `id` | String(40) | `id_column("ske")` |
| `variant_id` | String(40) | not null |
| `skill_id` | String(40) | not null，冗余存储，便于按技能查询和做锚点唯一 |
| — | | 复合 FK (`variant_id`, `skill_id`) → `skill_asset_variants(id, skill_id)`，`ondelete=CASCADE`。数据库层保证条目与其造型属于同一张卡 |
| `asset_id` | String(40) | FK → `assets.id`，`ondelete=CASCADE`，not null，有索引。资产真被清除时条目随之消失，不留悬空引用 |
| `entry_type` | String(24) | `AssetEntryType`（见 3.3），CHECK 约束 |
| `view` | String(16) | 可空。front / side / back / three_quarter，或 establishing / reverse / detail |
| `expressions_json` | JSONB | 可空。表情合集图包含哪些表情（P0 的 `CharacterExpression`） |
| `label` | String(60) | 可空，用户备注 |
| `status` | String(12) | `candidate` \| `approved`，默认 `approved`（迁移来的与写回的默认都算定稿，候选流程在 P2 引入） |
| `is_anchor` | Boolean | 默认 false。部分唯一索引 ON (`skill_id`) WHERE `is_anchor`：每张卡至多一个锚点 |
| `source_job_id` | String(40) | 可空，**不加外键**（追踪用，同 DM 第 12 条） |
| `sort_order` | Integer | 默认 0 |
| `created_at` | | |

- `UNIQUE (variant_id, asset_id)`。
- 索引 `ix_skill_asset_entries_skill` (`skill_id`, `variant_id`, `sort_order`)。

### 3.3 枚举（`back/app/models/enums.py`，以字符串持久化）

```python
class AssetVariantKind(StrEnum): LOOK = "look"; SCENE_VARIANT = "scene_variant"

class AssetEntryType(StrEnum):
    # 角色
    IDENTITY_PORTRAIT = "identity_portrait"   # 定妆照（推荐作为锚点）
    CHARACTER_SHEET = "character_sheet"       # P0 的多分区设定图
    VIEW = "view"                             # 单视角全身（配合 view 列）
    EXPRESSION_SHEET = "expression_sheet"     # 表情合集（配合 expressions_json）
    POSE = "pose"
    OUTFIT_DETAIL = "outfit_detail"
    PROP = "prop"
    # 场景
    MASTER = "master"                         # 主场景图（推荐作为锚点）
    SHOT = "shot"                             # 其他机位 / 细节（配合 view 列）
    # 通用
    OTHER = "other"
```

`entry_type` 与技能类别的匹配由服务层校验：角色卡不接受 `master` / `shot`，场景卡只接受 `master` / `shot` / `other`。

### 3.4 上限（服务层常量，与 P0 风格一致）

| 常量 | 值 | 说明 |
|---|---|---|
| `MAX_VARIANTS_PER_SKILL` | 12 | 角色造型 / 场景变体 |
| `MAX_ENTRIES_PER_VARIANT` | 24 | |
| `MAX_ENTRIES_PER_SKILL` | 120 | |

- 超过上限时返回 **422**，**不再静默淘汰**。P0 的 `_trim_to_cap` 是为 4 / 12 / 8 个槽位设计的，表化后去掉。
- 写回节点（`asset_output_link`）遇到上限时，按 GJ 写回规则记录日志并跳过，不让任务失败。

## 4. 领域层

新模块 `back/app/domain/asset_variants/service.py`，角色和场景共用。`characters.service` / `scenes.service` 改为调用它，`CharacterView` / `SceneView` 的投影保持不变。

| 函数 | 说明 |
|---|---|
| `list_variants(skill)` → 带条目 | 一次查询加 `selectinload`，避免 N+1 |
| `ensure_default_variant(skill)` | 创建卡片时同步创建：角色叫"默认造型"，场景叫"主场景" |
| `create_variant` / `update_variant` / `delete_variant` | 默认造型不能删，只能先把另一个设为默认（事务内切换，满足部分唯一索引） |
| `add_entry(variant, asset_id, entry_type, view, …)` | 校验资产归属与媒体类型（沿用 `_validate_reference_assets` 的规则） |
| `update_entry` / `remove_entry` / `set_anchor(entry)` | `set_anchor` 先清空旧锚点再设置新锚点，两步在同一事务内 |
| `find_or_create_variant(skill, *, name=None, presets=None)` | 写回用：场景按 `presets_json` 等值匹配，角色按造型名匹配 |
| `entries_for(skill, variant_id=None)` | 解析器和投影都用它 |

**沿用的不变量**

- **内容编辑撤下发布**（CL 第 3 条）：卡片已发布时，增删改造型 / 条目都调用 `skill_library_service.withdraw_after_edit`。生成任务写回保持 P0 的行为：`append_reference_asset` 不撤下发布。
- **审核文本**（CL 第 2 条）：`publish()` 的 `skill_moderation` 目前只读 `text_values(params_json)`。表化后要把造型名、描述、条目 label 也纳入审核文本。
- **删除卡片**：`skill_library_service.delete` 是硬删，新表靠 `ondelete=CASCADE` 跟随删除。
- **JSONB**：`presets_json` / `expressions_json` 遵守"先复制再修改"（DM 第 11 条）。

## 5. 兼容投影：现有 API 与 iOS 不破坏

`CharacterView.reference_assets` / `SceneView.reference_assets` 改为从表投影，形状不变：`{asset_id, view, label, created_at}`。

- **排序**：默认造型在前，然后按造型 `sort_order`、条目 `sort_order` 排列。
- **`view`**：
    - 角色的 `character_sheet` 映射为 `front`，`view` 条目映射为它自己的 view，其余为 `general`；
    - 场景的 `master` 映射为 `establishing`，`shot` 映射为它自己的 view，缺省为 `general`。
- **`label`**：非默认造型 / 变体的条目，label 用造型名（与 P0 语义一致：label 就是造型）；默认造型的条目保留它自己的 label。
- **新增字段**：`variant_id`、`entry_type`、`is_anchor`。只增不改，iOS 的 `LibraryReferenceAsset` 解码会忽略未知字段。

这样以下调用方**不需要改动**：

- iOS 的 `frontReference` / `referenceAssets`；
- 前端 `referenceByView`、`sceneHeroAsset`、`defaultCharacterReferenceIds`；
- `admin_reference_assets`、`label_references`。

**老写接口**：`POST/PATCH /characters` 的扁平 `reference_asset_ids` 和 `PATCH /reference-assets/{asset_id}` 继续保留，在服务层翻译：

- 扁平列表作用于**默认造型**：已有的条目保留类型，新增的条目记为 `other`；
- 设置 view 时：角色设为 front，对应 `character_sheet`；场景设为 establishing，对应 `master`；
- 设置 label：按"label = 造型名"把条目挪到对应造型（没有就创建）。

`characters.service.default_reference_asset_ids` 改为：

1. 有锚点时，锚点优先；
2. 然后取默认造型下已定稿的 `character_sheet` / `view` 条目，按 front → side → back 排序；
3. 最多 3 张。场景同理：锚点（主图）加默认变体的第一张 `shot`，最多 2 张。

## 6. 生成任务集成

### 6.1 请求参数（`back/app/api/schemas/jobs.py`）

- `CharacterRefSelection` / `SceneRefSelection` 增加可选字段 `variant_id`，`asset_ids` 改为可空。三种写法：
    - 只给 `variant_id`：使用该造型的默认子集（规则同第 5 节，限定在该造型内）；
    - 只给 `asset_ids`：沿用 P0 行为；
    - 两者都给：`asset_ids` 必须都属于该造型，否则 422。
- 新增 `target_variant_id`（只对 `asset_kind=character|scene` 有效）：写回到哪个造型 / 变体。
- `character_outfit_label` 保留，作为"按名称找或建造型"的快捷方式。与 `target_variant_id` 互斥。

### 6.2 `ReferenceResolver`（`back/app/domain/image_assets/reference_resolver.py`）

由它统一负责三件事，取代目前分散在 `apply_character_refs`、`apply_scene_refs`、`label_references`、`ensure_expression_reference` 里的选图、预算和标签逻辑：

- **输入**：
    - `character_ids`、`scene_ids`、`*_ref_selection`（含 `variant_id`）；
    - 显式的 `reference_asset_ids`；
    - 槽位预算 9。
- **输出**：有序的 `reference_asset_ids` 和 `reference_labels`。标签格式如 `角色「林夏」·婚礼·设定图`、`场景「客厅」·黄昏·主图`。
- **扩展点**：`shot_hint`（close / medium / wide）和 `emotion_hint`。P1 只定义签名、走默认策略，P2 再实现按景别 / 情绪排序。
- **调用位置**：`jobs.service.submit` 中原来的那几行调用合并为 `reference_resolver.resolve(session, user_id, params)`；`_MUTATED_PARAM_KEYS` 不变。

### 6.3 写回（`nodes.execute_asset_output_link`）

先确定目标造型：

1. `target_variant_id`；
2. 否则 `character_outfit_label`：按名称找或建；
3. 场景本次 pass 的预设（P0 的 `_pass_params`）：按 `presets_json` 找或建，名称取 `scene_preset_label`；
4. 都没有时用默认造型。

条目类型按本次 pass 推断：

| pass | `entry_type` |
|---|---|
| 正面设定图 | `character_sheet` |
| 侧面 / 背面补全 | `view`（side / back） |
| 表情合集 | `expression_sheet`，并写入 `expressions_json` |
| 场景，目标变体还没有主图 | `master` |
| 场景，其他情况 | `shot` |

`source_job_id` 记为当前任务 id。卡片还没有锚点时，第一张定妆照或主图自动设为锚点。

### 6.4 剧本与画布

- `ScriptCharacter` 增加可选 `look_id`，`ScriptScene` 增加可选 `variant_id`：
    - 通过 `PATCH /v1/scripts/{id}/links` 设置，模型不会写这两个字段（同 `ref_id` 规则）；
    - 分段视频（`planSegmentVideos`、`resolveBreakpointRefs`）把它们带成 `*_ref_selection.variant_id`。
- 场景标题解析出的日 / 夜（P0 `parseScenePresets`）在关联场景时，按预设匹配已有变体，作为默认值。
- 画布 `_first_reference_asset_id` 改为读锚点或投影的第一张，不再读原始 JSON。

## 7. 权限、售卖与资产安全

| 问题 | P1 处理 |
|---|---|
| 解锁后 `/v1/skills/{id}` 的 `params` 暴露原始 `reference_assets` 条目 | 表化后 `params_json` 不再含条目。解锁后的详情改为返回经签名的造型 / 条目投影（只读）。未解锁仍为空 |
| 买家能否把他人卡片的参考图用于生成 | 目前 `asset_is_usable_skill_reference` 只放行封面。P1 扩展为：已发布、公开、且查看者已解锁的卡片，其**定稿条目**可作为参考图 |
| `/v1/skills` 的 PATCH 会整体覆盖场景的 `params_json` | 与角色一致：`_reject_character_category` 扩展为拒绝所有图片资产类卡片的 POST/PATCH，改走 `/v1/scenes` |
| `media.service._is_shared` 不认技能参考 | 增加对 `skill_asset_entries.asset_id` 的检查，作品删除时不连带删除被卡片引用的资产（MA 第 7 条要求新增指针列时同步加分支） |
| 后台技能浏览器缺少场景参考 | `admin_reference_assets` 改为读表，场景一并补上 |

## 8. 迁移计划

线上存量很小（2026-10-01 只读统计）：

| 类别 | 卡片数 | 条目数 | 说明 |
|---|---|---|---|
| 角色 | 27 | 20 | 全部 view=front，最多 1 条 / 卡，无 label；`action_clips` 共 7 条 |
| 场景 | 18 | 22 | view：scene 14 条、establishing 8 条；最多 3 条 / 卡；无 label |

因此一次迁移即可完成，不需要双写期。

**迁移 A：建表并回填**（`YYYYMMDD_HHMM_skill_asset_variants.py`）

1. 建两张表、约束和索引。
2. 遍历 `category IN ('character','scene_asset')` 的卡片：
    - 创建默认造型 / 变体；
    - 按第 5 节映射的逆向，把 `reference_assets` 写成条目：
        - 角色：front → `character_sheet`；side / back → `view`；general → `other`；
        - 场景：establishing → `master`；其余 → `shot`（`view=null`）；
        - 有 label 的条目：label 以 `表情·` 开头的进默认造型，类型为 `expression_sheet`；其余 label 按名称找或建造型 / 变体。
    - 锚点：角色取第一张 `character_sheet`，场景取 `master_entry` 规则选出的那张。
    - 指向已不存在资产的条目直接丢弃，并在迁移日志中计数。
3. **不删除** JSON 里的 `reference_assets`，保留一个版本作为回滚兜底；读路径从此只读表。

**迁移 B：清理 JSON**（下一个版本）

- 从 `params_json` 中移除 `reference_assets`。
- `catalog.params_json()` 和 `_ensure_seeded_reference` 改为写表（目录卡片的封面成为默认造型的锚点）。

**回滚**：迁移 A 的 downgrade 直接删表。由于 JSON 还在，读路径回退后数据可用，但 A 之后通过新接口写入的造型 / 条目会丢失。这一点要写在发布说明里。

**其他配套**

- `RESET_TABLES`：新表跟随 `creation_skills` 的 `TRUNCATE … CASCADE` 一起清空，不需要单独列出（DM 第 5 条）。
- 迁移测试：仿照 `test_character_view_merge_migration.py`，覆盖 front / side / back、general、带 label、表情 label、establishing 和悬空资产。

## 9. API（`/v1`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/characters/{id}` | 响应增加 `looks: [{id, name, description, presets, is_default, sort_order, entries: [...]}]` 和 `anchor_entry_id`；`reference_assets` 继续返回投影 |
| POST | `/characters/{id}/looks` | 新建造型 |
| PATCH | `/characters/{id}/looks/{look_id}` | 改名、描述、默认、排序 |
| DELETE | `/characters/{id}/looks/{look_id}` | 默认造型返回 422 |
| POST | `/characters/{id}/looks/{look_id}/entries` | 添加已有资产 `{asset_id, entry_type, view?, expressions?, label?}` |
| PATCH | `/characters/{id}/entries/{entry_id}` | 修改类型 / 视角 / label / 状态，或移到另一个造型（`variant_id`） |
| DELETE | `/characters/{id}/entries/{entry_id}` | |
| POST | `/characters/{id}/entries/{entry_id}:anchor` | 设为身份锚点 |
| — | `/scenes/{id}/variants…` | 与角色同构，`presets` 使用 P0 词汇表校验 |

- 所有写接口都是仅所有者可用，不存在或无权限一律返回 404（同现有 `_owned_*`）。
- 限流分组用 `authenticated_write`。
- 新增错误码沿用 `ValidationFailed` 的 fields 形式。

## 10. 前端

- **角色库**（`/create/characters`）：卡片详情页改为"造型"分栏。
    - 每个造型展示：设定图 / 三视图 / 表情 / 细节分组的网格，以及"补齐缺失"按钮（P2）。
    - 支持定稿标记和设为锚点。
- **场景库**：变体列表，每个变体显示预设徽章，主图 + 机位网格。
- **生成工作台**：
    - `ReferenceImagePicker` 升级为"先选造型、再选图"，默认只选造型（发送 `variant_id`）；
    - 图片工作台的"造型名称"输入改为"目标造型"下拉，可新建。
- **剧本**：`ScriptLinkPicker` 关联角色 / 场景后，可以再选造型 / 变体。
- `skill-mention.ts:firstSkillReferenceAssetId` 改为用响应里的 `anchor` / 投影，不再读原始 JSON。

## 11. 分期与测试

| 子阶段 | 内容 | 主要测试 |
|---|---|---|
| **P1-1** 表与服务 | 模型、枚举、迁移 A、`asset_variants.service`、兼容投影、老接口翻译、`_is_shared` 分支、审核文本 | 新增 `test_asset_variants_service.py` 和迁移测试；现有 `test_characters*` / `test_scenes*` 全部保持通过（验证兼容） |
| **P1-2** 任务集成 | `variant_id` 选择、`target_variant_id`、`ReferenceResolver`、写回定位、解锁后可用的定稿条目 | `test_reference_resolver.py`；`test_asset_planning.py` 写回用例；`test_generation_lifecycle.py` 造型端到端用例 |
| **P1-3** API 与前端 | 造型 / 变体接口、库页面、工作台和剧本选择器、画布读路径、技能详情投影 | 接口集成测试；前端 vitest；e2e 的角色库流程 |
| **P1-4** 清理 | 迁移 B、目录卡片写表、文档 | 目录与种子数据测试 |

每个子阶段一个 `feature/*` 分支、一个 commit，按依赖顺序合并进 `dev`。

**需要同步更新的 skill 文档**：

- `zaolang-creation-library`：第 9、11 条重写为表模型；
- `zaolang-data-model`：新表与前缀 `skv` / `ske`；
- `zaolang-generation-jobs › reference-asset-pipeline`：写回定位；
- `zaolang-media-assets`：第 7 条新增指针分支。

## 12. 已决问题（2026-10-01，按建议）

1. **造型不单独售卖**：随卡解锁，`access_credits` 仍只在卡片上。
2. **年龄阶段**：用造型的 `presets_json.age_stage` 表达，词汇表到 P2 再定。
3. **候选 / 定稿**：P1 中迁移和写回的条目默认都是定稿（`approved`），候选流程在 P2 引入。
4. **`action_clips`**：留在 JSON 中，P2 再评估是否并入条目表。
5. **迁移 B 的时机**：至少隔一个线上版本再执行。

## 13. P1-1 实现补充：JSON 镜像

P1-1 期间，表是唯一的数据源。但每次变更造型 / 条目之后，都会把第 5 节的投影**回写**到 `params_json[...]["reference_assets"]`（`asset_variants.service.sync_mirror`）。这样做有三个好处：

- 仍直接读取原始 JSON 的地方（画布缩略图、前端 `firstSkillReferenceAssetId`、技能详情的 `params`）在 P1-3 改造之前继续正确；
- 迁移 A 的 downgrade 不会丢失数据；
- 迁移 B 把镜像连同 JSON 字段一起删掉。
