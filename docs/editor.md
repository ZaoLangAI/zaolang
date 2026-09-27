# 短剧剪辑

浏览器时间线插在生成 Asset 与草稿发布之间。产品契约是造浪自己的 EditCommand 与整数 tick 时间线。

## 路径

```text
/create/short 或视频生成 → 任务成功 → 「进入剪辑」（新标签页）
  → Series(kind=drama) + DramaEpisode + EpisodeCut
  → /studio-editor/{cutId}（独立全屏标签页，无站点导航栏）
  → DeliveryVariant 顺序导出
  → POST /v1/drafts/{id}/bind-editor-export
  → 八步发布
```

桌面 Chrome/Edge 硬门禁。窄屏只显示提示，不进入手机无障碍扫描清单。

编辑器界面（`front/src/features/editor/studio/`）参考 OpenCut
（`opencut-app/opencut-classic`，MIT）的布局/面板结构改造：左侧素材库
（我的素材 + 文字/字幕）、中间预览+时间线、右侧属性与导出面板，均为
`react-resizable-panels` 驱动的可拖拽分栏。仅采用其 UI 外壳，时间线数据
模型、命令引擎、导出/合成逻辑仍是造浪自有实现——见下方「不要」条目。
`(studio)` 路由组（`front/src/app/[locale]/(studio)/`）独立于
`(site)`，不挂载站点顶栏/登录弹窗/通知栈，只挂载 `SessionProvider`。

素材库读取 `GET /v1/assets:mine`（`back/app/api/v1/uploads.py`），列出
调用者自己的 `generation_output`/`editor_source` 资产，并排除
`asset_kind=character`/`scene` 的任务产出图（角色设定图 / 场景图留在各自
库里选）；插入时间线复用既有 `insert_clip` 命令，不新增命令类型或轨道。

## 能力对齐（Phase 1-5）

在 UI 外壳改造之后，又分五个阶段把编辑能力对齐到专业 NLE 水平——同样只
参考 OpenCut 的设计/文档作为思路，从未照搬其引擎代码：

1. **多轨道**：`document.py` 的轨道新增 `order`/`label`/`muted`；
   `add_track`/`remove_track`/`set_track_order`/`set_track_muted`。
   仅 video/audio 轨道可增删，字幕轨与角标轨永远各一条。同一时刻的画面
   取最高 `order` 且有内容的视频轨；预览与导出的音频都基于
   `resolveAudioLayers` 混音（`engine/audio-mixer.ts` 用
   `AudioBufferSourceNode`，导出用 `OfflineAudioContext`）。
2. **特效与蒙版**：`add_effect`/`remove_effect`/`update_effect_params`/
   `set_clip_mask`。特效类型闭集 `blur`/`brightness`/`contrast`/
   `saturate`/`grayscale`——`blur` 走已向量化确认可用的 OpenCut 原生 WASM
   `gaussian-blur` 着色器，其余始终是 Canvas2D `ctx.filter`（这是当前
   vendored 版本 Rust 管线里唯一注册的着色器，不要假设还有别的）。蒙版
   统一走 Canvas2D 羽化，不经 WASM 的 `applyMaskFeather`。
3. **粗粒度关键帧**：`set_keyframe`/`delete_keyframe`/`clear_keyframes`，
   `property` 是闭集枚举（`opacity`/`transform.*`四项），带独立数值范围
   校验——不是 `validate_batch` 永久禁止的通用 path/value 更新。手动打点，
   非逐帧动画，不引入 diff 修订存储。
4. **贴纸与转场**：贴纸就是 `insert_clip` 的 `element_type: "sticker"`，
   结构与普通片段完全一样。转场是片段自身的 `transition_in`/
   `transition_out` 字段，只在同一轨道上两个片段被手动拖出重叠区间时才
   会真正渲染（`compositor.ts` 的 `resolveOverlap`）。
5. **字幕转写**：复用 `MediaAnalysis` 表的第二个 analyzer 身份
   (`whisper-asr`)，同一 `media_analysis` 队列，不新增管线。凭证从
   `llm_providers` 里支持 `audio_generation` 的端点直接取，不走
   `app.agents.router` 的 AI 选型。`editor.request_transcription` MCP
   工具可被 AI 触发，但只入队分析、绝不自动写字幕——真正生成
   `insert_caption` 命令的唯一入口是
   `front/src/features/editor/transcript-review-panel.tsx` 的人工审核。

细节与「不要」条目见 `zaolang-editor-drama` skill 里渲染、混音、特效与蒙版、
关键帧、贴纸转场和字幕转写的条目。

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
