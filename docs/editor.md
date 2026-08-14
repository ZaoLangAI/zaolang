# 短剧剪辑

浏览器时间线插在生成 Asset 与草稿发布之间。产品契约是造浪自己的 EditCommand 与整数 tick 时间线。

## 路径

```text
/create/short 或视频生成 → 任务成功 → 「进入剪辑」
  → Series(kind=drama) + DramaEpisode + EpisodeCut
  → /create/drama/{cutId}
  → DeliveryVariant 顺序导出
  → POST /v1/drafts/{id}/bind-editor-export
  → 八步发布
```

桌面 Chrome/Edge 硬门禁。窄屏只显示提示，不进入手机无障碍扫描清单。

## 时间与命令

- `120000 ticks = 1 秒`，API 只接受 JS 安全整数。
- 共享 schema：`back/app/domain/editor/schemas/edit_command.schema.json`。
- 禁止通用 `path`/`value` 更新。失败批次整批回滚。

## Feature flags

默认关闭：`drama_studio_enabled`、`web_editor_enabled`、`variant_export_enabled`、`editor_ai_enabled`、`editor_mcp_enabled`。后三者依赖 `web_editor_enabled`。关闭时接口 404。

## MCP

`POST /mcp`，协议 `2026-07-28`（兼容 `2025-11-25`）。独立 JWT audience `mcp` 与 `MCP_JWT_SECRET`。`project_id` 等于 `Series.id`。没有 publish 工具。

## Phase 0

没有 10 秒 Chrome/Edge 金样之前，不要宣称媒体验收通过。
