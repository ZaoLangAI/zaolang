---
name: zaolang-platform-config
description: 造浪的运行时配置中心与 Feature Flag：八个配置段（pricing / routing_weights / providers / agents / royalty / feature_flags / moderation / llm_providers）的强类型 schema、版本化写入、Redis 缓存失效、审计与一键回滚。Use when adding a runtime-configurable setting, changing tier pricing or routing weights, adding a feature flag, rebinding an agent model, or debugging why a config change did not take effect.
disable-model-invocation: true
---

# 运行时配置中心与 Feature Flag

## 职责

凡是「上线后可能要调」的数值都不写死在代码里：档位定价、路由评分权重、供应商开关与限额、各智能体的模型绑定、回流分成规则、审核阈值、Feature Flag。全部存 `PlatformConfig`，后台可热改、可看 diff、可回滚，每次变更进 `AuditLog`。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/platform_config/schemas.py` | `CONFIG_SCHEMAS`（key → pydantic 类型）与 `DEFAULT_CONFIGS`（默认值） |
| `back/app/platform_config/service.py` | `get_typed` / `get_raw` / `set_value` / `rollback` / `history` / `invalidate` / `is_enabled` |
| `back/app/api/v1/admin/config.py` | 读接口 viewer 级、写接口与 rollback **admin 级** |
| `front/src/components/admin/config/config-console.tsx` | 编辑器 + 版本历史 + JSON diff |
| `front/src/components/admin/config/feature-flags-panel.tsx` | Flag 灰度开关 |
| `front/src/components/admin/providers/routing-weights-panel.tsx` | 路由权重面板 |
| `front/src/components/admin/providers/llm-providers-console.tsx` | LLM 网关端点目录 |

八个 key：`pricing`、`routing_weights`、`providers`、`agents`、`royalty`、`feature_flags`、`moderation`、`llm_providers`。

## 不可破坏的不变量

1. **读配置只走 `get_typed(session, key, Schema)`**，返回强类型对象。不要 `get_raw` 后直接下标取值，schema 校验是防止一次错误编辑把生产打挂的唯一屏障。
2. **写入是版本化追加**：`set_value` 新增一条 `PlatformConfig` 版本、失效 Redis 缓存、写 `AuditLog`（含操作者、前后值摘要、理由）。绕过 service 直接 UPDATE 表 = 丢历史、丢审计、缓存不失效。
3. **改配置必须带理由**，`rollback` 同样。后台高危操作走二次确认（见 `zaolang-admin-console`）。
4. **密钥类字段永不回显**：接口与界面只返回掩码与连通性状态。新增敏感字段时同步 schema 的脱敏逻辑。
5. **缓存失效不能靠 TTL 兜底**：`set_value` 与 `rollback` 都要 `invalidate(key)`。Redis 不可用时 service 退化为直读数据库（探测包在 `begin_nested` 里，不污染事务）。
6. **默认值必须能让空库正常工作**：`DEFAULT_CONFIGS` 是 `get_typed` 在数据库无该 key 时的回退，测试与全新部署都依赖它。
7. **路由权重四项 `quality/latency/cost/reliability` 的语义与顺序由网关实现固定**，只能调数值，不能改评分公式（改公式见 `zaolang-agent-gateway`）。

## 改造切入点

**加一个配置项**

1. 在 `schemas.py` 对应 `ConfigSection` 加字段（**带默认值**，否则存量版本反序列化会炸）。
2. 同步 `DEFAULT_CONFIGS` 里的同名段。
3. 调用处改成读新字段，不要留 `getattr(cfg, "x", fallback)` 这种绕过类型的写法。
4. 前端 `config-console.tsx` 靠 JSON 编辑器自动支持，无需改代码；有专用面板的（定价、权重、Flag）要同步面板。
5. 写单元测试进 `back/tests/unit/test_platform_config.py`。

**加一个新配置段**：`CONFIG_SCHEMAS` 与 `DEFAULT_CONFIGS` 各加一项即可，`all_keys()` 自动带出，后台列表自动出现。

**加一个 Feature Flag**：`FeatureFlags` 加布尔字段 → 调用处 `is_enabled(session, "flag_name", user_id=...)`。灰度按 user_id 哈希，不要自己实现分流。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_platform_config.py tests/integration/test_admin_ops_platform.py -v
```

改完在后台 `/admin/config` 实操一遍：编辑 → 看 diff → 回滚 → 看 `/admin/audit`（日志中心）里两条记录都带理由。
