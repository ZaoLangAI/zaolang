---
name: zaolang-platform-config
description: 造浪的运行时配置：pricing / royalty / feature_flags / shortform / llm_providers 与内容、学习、技能三类审核配置的强类型 schema、版本化写入、审计和回滚。Use when adding or relocating runtime settings, changing pricing or flags, or debugging why a config change did not take effect.
disable-model-invocation: true
---

# 运行时配置中心与 Feature Flag

## 职责

运行时配置按业务归属展示：配置中心首页直接展示全局 Feature Flag 与短视频规格；定价/分成及三类审核规则只由各业务列表“刷新”右侧的配置按钮打开弹窗。模型端点仍版本化存于 `llm_providers`，但只能通过专用掩码 API 管理；智能体供应商与模型绑定存 `AgentProfile`，不属于 `PlatformConfig`。端点级超时、并发在模型页维护，不另设全局 LLM 可靠性段。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/platform_config/schemas.py` | `CONFIG_SCHEMAS`（key → pydantic 类型）与 `DEFAULT_CONFIGS`（默认值） |
| `back/app/platform_config/service.py` | `get_typed` / `get_raw` / `set_value` / `rollback` / `history` / `invalidate` / `is_enabled` |
| `back/app/api/v1/admin/config.py` | 读接口 viewer 级、写接口与 rollback **admin 级** |
| `front/src/components/admin/config/runtime-config-panel.tsx` | 可复用表单/JSON、diff、理由、历史和回滚编辑器 |
| `front/src/components/admin/models/llm-providers-panel.tsx` | 模型管理：扁平主备列表 + 端点级主/备，支持增删改 |

九个 key：`pricing`、`royalty`、`marketplace`、`feature_flags`、`shortform`、`llm_providers`、`content_moderation`、`learning_moderation`、`skill_moderation`。`marketplace` 管解锁抽成与标价上限；`feature_flags.marketplace_enabled` 是市场总开关。旧 `providers`、`agents`、`moderation`、`llm_reliability` 只保留失活历史，不能读取或回滚。

`llm_providers` 里每个端点用 `kind` 二选一：`general`（文字与图片理解）或 `media`（图片/视频/音频生成）。判断类与辅助生成类 `AgentProfile` 手动选择默认供应商端点、兼容模型和可选备用端点；未显式绑定的非默认 Agent 才继承角色默认 Agent。`media` 端点声明一个模型 id（`model`）+ 输入/输出模态 + **`protocol`（HTTP 契约标准名，不是网关供应商）**；能力 tag 由 `capabilities_for_modalities` 推导，进入 `router.py` 的动态候选目录由 `intent_router` 的 LLM 选型挑选。媒体端点没有主备顺序和并发调度语义。`protocol` 落在这份 JSON 里，不改 SQLAlchemy / Alembic。

## 不可破坏的不变量

1. **读配置只走 `get_typed(session, key, Schema)`**，返回强类型对象。不要 `get_raw` 后直接下标取值，schema 校验是防止一次错误编辑把生产打挂的唯一屏障。
2. **写入是版本化追加**：`set_value` 新增一条 `PlatformConfig` 版本、失效 Redis 缓存、写 `AuditLog`（含操作者、前后值摘要、理由）。绕过 service 直接 UPDATE 表 = 丢历史、丢审计、缓存不失效。
3. **改配置必须带理由**，`rollback` 同样。后台高危操作走二次确认（见 `zaolang-admin-console`）。
4. **密钥类字段永不进入通用配置 API**：`llm_providers` 的 list/get/update/diff/history/rollback 全部拒绝，只能由专用模型 API 返回掩码与连通性状态。
5. **缓存失效不能靠 TTL 兜底**：`set_value` 与 `rollback` 都要 `invalidate(key)`。Redis 不可用时 service 退化为直读数据库（探测包在 `begin_nested` 里，不污染事务）。
6. **默认值必须能让空库正常工作**：`DEFAULT_CONFIGS` 是 `get_typed` 在数据库无该 key 时的回退，测试与全新部署都依赖它。
7. **不要再加回路由评分权重类的配置段**。供应商之间选谁由 `intent_router` 的 LLM 判断决定（`zaolang-agent-gateway` 不变量 #1），不是可调数值；这里只负责供应商目录本身「存不存在、开不开、限额多少」这类硬性开关。
8. **`get_typed` 校验失败会回退整份 `DEFAULT_CONFIGS["llm_providers"]`（空 `endpoints`）**，一次坏端点就能把路由目录清空。因此 `LlmProviderEndpoint.protocol` 必须可缺省（`None`）；缺字段时 `_migrate_legacy_fields` 按能力推断（仅视频 → `minimax`，否则 → `openai`）。`kind=general` 清空 `protocol`。Admin upsert 显式传入时严格匹配：未实现协议、`openai`+视频、`minimax`+图片/音频 → `ValidationFailed`（HTTP 422），禁止静默回退。存量跨协议混合端点在 `LlmProviderConfig` 上逐端点跳过并记 warning，不要让整份 config 挂掉。

## 改造切入点

**加一个配置项**

1. 在 `schemas.py` 对应 `ConfigSection` 加字段（**带默认值**，否则存量版本反序列化会炸）。
2. 同步 `DEFAULT_CONFIGS` 里的同名段。
3. 调用处改成读新字段，不要留 `getattr(cfg, "x", fallback)` 这种绕过类型的写法。
4. 前端 `config-console.tsx` 靠 JSON 编辑器自动支持，无需改代码；有专用面板的（定价、Flag、短视频）要同步面板——`runtime-config-panel.tsx` 的 `ShortformForm` 是手写字段列表，不是 schema 自动渲染，新字段要显式加控件（例如 `ShortformConfig.enable_clarifying_questions` / `enable_preview_picker` / `preview_candidate_count` 这三个短视频工作室的追问/预览开关）。
5. 写单元测试进 `back/tests/unit/test_platform_config.py`。

**加一个新配置段**：`CONFIG_SCHEMAS` 与 `DEFAULT_CONFIGS` 各加一项即可，`all_keys()` 自动带出，后台列表自动出现。

**加一个 Feature Flag**：`FeatureFlags` 加布尔字段 → 调用处 `is_enabled(session, "flag_name", user_id=...)`。灰度按 user_id 哈希，不要自己实现分流。短剧五旗（`drama_studio_enabled` / `web_editor_enabled` / `variant_export_enabled` / `editor_ai_enabled` / `editor_mcp_enabled`）默认 false；后三者依赖 `web_editor_enabled`。本地 `make seed` 会打开，不要把 seed 行为写进 `DEFAULT_CONFIGS`。见 `zaolang-editor-drama`。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_platform_config.py tests/integration/test_admin_ops_platform.py -v
```

改完在后台 `/admin/config` 实操一遍：编辑 → 看 diff → 回滚 → 看 `/admin/audit`（日志中心）里两条记录都带理由。
