---
name: zaolang-editor-drama
description: 造浪短剧浏览器剪辑器：规范化时间线（整数 tick）、EpisodeCut 不可变修订、单写者租约、顺序导出、editor_planner、Remote MCP，以及 Series.kind 与角色名册的隔离。Use when working on /create/drama, EditCommand, cut revisions, editor leases, DeliveryVariant, EditorExport, bind-editor-export, editor_planner, /mcp, or Series kind=drama vs kind=cast.
disable-model-invocation: true
---

# 短剧剪辑（Drama Editor）

产品域与引擎都在造浪。对外只有 EditCommand 与规范化时间线，不要把外部剪辑器的项目/元素类型暴露到 API。

## 关键路径

| 路径 | 内容 |
| --- | --- |
| `front/src/features/editor/` | 适配器端口、canonical apply、租约会话、时间线 UI、顺序导出 runner |
| `front/src/features/editor/from-job.ts` | 任务页「进入剪辑」的唯一入口；禁止从 `features/editor` 桶文件静态拉整棵编辑器 |
| `front/src/app/[locale]/(site)/create/drama/` | 桌面 Chrome/Edge 门禁；窄屏只读提示，不进 `a11y-mobile` |
| `back/app/models/editor.py` | `drama_episodes` / `episode_cuts` / `cut_revisions` / 租约 / 变体 / 导出 / `MediaAnalysis` |
| `back/app/models/characters.py` | `Series.kind`（`cast` \| `drama`）与制作项目字段；禁止再建第二套剧集表 |
| `back/app/domain/editor/` | 修订 CAS、命令校验、租约、导出 complete（HEAD + checksum + ffprobe）、分析入队 |
| `back/app/domain/characters/service.py` | `/v1/series` 只认 `kind=cast`；drama 对名册 API 404 |
| `back/app/api/v1/editor.py` | `/v1/drama-series`、cuts、leases、revisions、exports、`bind-editor-export`、`episode-cuts:from-job` |
| `back/app/mcp/` | 自实现 `POST /mcp` Streamable HTTP；必须用 FastAPI `DbSession`，禁止 `session_scope()` |
| `back/app/agents/editor_planner.py` | 独立 planner，只读工具，结果记 `AgentRun`，不加假 `GenerationJob` |
| `back/app/scripts/seed.py` | `_seed_editor_flags` 本地打开五旗；`_seed_editor_demo` 给 `linhai` 一条 drama 项目 |
| `docs/editor.md` | 产品路径与 Phase 0 边界 |

## 不可破坏的不变量

1. **时间是整数 tick**，`120000 ticks = 1s`，校验 JS 安全整数。禁止浮点秒。
2. **规范文档在服务端** `cut_revisions.document_json`。MCP `apply_edit_plan` 不依赖打开的标签页。
3. **MCP `project_id` = `Series.id`**（`kind=drama`）。不要新建 Project 表。`Series` 是角色名册表的复用，不是第二套剧集模型。
4. **`/v1/series` 只返回 `kind=cast`。** `list_series` / `_owned_series` / `create_series` 显式 `SeriesKind.CAST`。drama id 打 `/v1/series/{id}` 必须 404（与不存在相同，不泄露制作项目）。创作中心「最近系列」与短视频工作室读的是名册，不是剪辑项目。
5. **剧集写走 `POST /v1/drama-series` 且 `kind=drama`。** `from-job` 可自动建 drama series。不要让名册 API 写出 drama 行。
6. **单写者租约**：条件更新，终态不能被心跳重开。丢租约变只读，不覆盖新 head。
7. **失败命令批次整批回滚**，head 不变。写修订带 `expected_revision_id` CAS。
8. **剪辑内部修订不写 `LineageEdge`。** 发布必须绑定明确成功的 `EditorExport.output_asset_id`。入口不在 PublishKit。
9. **手动剪辑与浏览器导出不计费。** AI 计划只记 `AgentRun`，不改账本唯一键。
10. **Feature flags 默认 false**：`drama_studio_enabled` / `web_editor_enabled` / `variant_export_enabled` / `editor_ai_enabled` / `editor_mcp_enabled`。export/ai/mcp 依赖 `web_editor_enabled`。关则 404。本地 `make seed` 会打开五旗；生产默认关。
11. **MCP audience 只能是 `mcp`。** 禁止 consumer/admin token。没有 publish 工具。
12. **不要嵌外部剪辑器整棵进 `front/`。** 渲染/导出只走本仓库的适配器与 `mediabunny`。
13. **任务页只引 `from-job.ts`。** 不要 `import … from '@/features/editor'`，否则会把 WASM / mediabunny 打进任务页。`export-runner.ts` 对 `mediabunny` 动态 import。
14. **分析走独立队列 `media_analysis`。** Beat 另有 `expire_editor_leases` / `expire_orphan_editor_uploads`（挂 `webhook_reconcile`）。`make dev-worker` 的 `-Q` 必须含 `media_analysis`。
15. **`make seed --reset` 删 drama 空壳，保留 cast 名册。** `Series` 不在 `RESET_TABLES`；`_reset` 额外 `DELETE FROM series WHERE kind = 'drama'`。剪辑子表在 `RESET_TABLES` 里。

## 产品路径

生成成功 →「进入剪辑」→ `/create/drama/{cutId}` → 顺序导出 → `POST /v1/drafts/{id}/bind-editor-export` → 八步发布。

## 本地库

以 `alembic heads` 为准，不要把文档里的某个 revision 当成当前库。剪辑表在 `20260814_0200_add_drama_editor.py`；其后还有 `20260814_0900_add_work_appeals_and_hide_reason.py`（`works.hide_reason` + `work_appeals`）和 `20260814_1400_add_editor_lease_active_unique_index.py`（活跃租约部分唯一索引）。拉代码后跑 `make migrate`。`alembic check` 上 `agent_nodes.category` / `provider_async_tasks` 的 server_default 噪音是既有问题，不要为此新开迁移。不要 `make reset` 除非明确要毁掉数据卷。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_editor_commands.py tests/integration/test_editor.py tests/integration/test_editor_mcp.py tests/integration/test_series.py -v
make openapi-check
make messages
```

`test_series.py` 必须覆盖「`/v1/series` 不含 drama、drama id 打名册 API 404」。Phase 0 金样：目标 Chrome/Edge 导出 10s MP4/WebM，且 `createIndependentEngines()` 可多实例。未在真实宽屏跑通不得宣称 Media 验收通过。
