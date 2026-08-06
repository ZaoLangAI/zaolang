---
name: zaolang-agent-gateway
description: 造浪的 Agno 智能网关与 LLM 接入：Safety/Planner/Quality/Copy Agent、纯规则 Router 评分、Generation Gateway Team 与 Workflow、工具白名单、OpenAI 兼容网关（AIHubMix）三档模式、响应规范化与 AgentRun 记录。Use when changing an agent prompt or tool, the routing score formula, provider candidates, the LLM client, response normalisation, model bindings, or stub/degradation behaviour.
disable-model-invocation: true
---

# Agno 智能网关与 LLM 接入

## 职责

智能体负责**判断**（安全、规划、质检、文案），供应商负责**产出**（图片、视频）。两者之间由纯规则的 Router 连接。LLM 只服务推理，不生成媒体。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/agents/safety.py` / `planner.py` / `quality.py` / `copywriter.py` | 四个 Agent（模块内常量作 fallback） |
| `back/app/domain/agent_skills/service.py` | `AgentNode` / `AgentSkill` 版本化 Prompt，`get_active_prompt(node_role)` |
| `back/app/agents/router.py` | 纯规则路由：`ProviderCapability` / `Candidate` / `RoutingDecision` / `route()` |
| `back/app/agents/tools.py` | **受控工具白名单**，Agent 唯一能碰领域服务的入口 |
| `back/app/agents/base.py` / `agent_os.py` | Agent 基类与 AgentOS 挂载（产品 FastAPI 作为 `base_app`） |
| `back/app/teams/generation_gateway.py`、`back/app/workflows/generation.py` | Team 与 Workflow 编排 |
| `back/app/providers/base.py` / `fake.py` | `ProviderCapability`（含 `provider_factory`）、`fake_open_workflow` 与 `fake_paid_api` 两条路线 |
| `back/app/providers/media_endpoints.py` | `dynamic_capabilities(session)`：把数据库里 `kind="media"` 的启用端点按能力展开成 `ProviderCapability`，供 `router.build_catalog` 合并 |
| `back/app/providers/aihubmix_media.py` | `AiHubMixMediaProvider`：图片/语音同步调用 + 视频建任务/轮询/下载 |
| `back/app/llm/client.py` | `complete()` / `probe()`，三档模式与降级 |
| `back/app/llm/failover.py` | LLM 网关独立 failover 池：并发占用、熔断、按主/备角色 + 优先级选端点（单一通用池，四个 Agent 角色共用，不再分场景） |
| `back/app/llm/normalize.py` | `strip_thinking` / `extract_json` / `normalize_completion` |
| `back/app/llm/capabilities.py` | 按错误反馈学习模型能力（温度、JSON 模式等） |
| `back/app/llm/stub.py` | 确定性 stub，测试与 CI 用 |

## 不可破坏的不变量

1. **Router 不接 LLM**。评分是固定公式、逐候选记录过滤理由，以代码与单测为准，保持「可解释规则，不用黑盒路由模型」。评分顺序：过滤 → 打分 → 确定性排序（`-total_score`, `effective_cost`, `provider`），同分必须稳定。
2. **权重来自配置中心** `routing_weights`（quality/latency/cost/reliability），代码里只有默认值。改权重是配置操作，不是代码操作。
3. **`effective_cost` 包含失败重试放大**；统计样本不足时用保守先验，不能假装成功率 100%。
4. **每个候选的淘汰理由都要落 `ProviderAttempt` / 决策记录**，后台「决策逐候选回放」依赖它。
5. **Agent 输出不是事实，落库才是**。Agent 只能通过 `tools.py` 白名单调领域服务；不要给 Agent 直接的 session 或任意 SQL。
6. **测试与 CI 强制 `LLM_MODE=stub`**。三档模式：`openai_compatible`（只走真实网关，失败即报错）、`stub`（确定性假响应）、`auto`（网关失败自动降级到 stub）。降级必须写入 `AgentRun` 的降级标记与原因，并在界面明确标识。
7. **每次调用写 `AgentRun`**：模型、token 用量、延迟、是否降级。后台智能体运维完全建立在这张表上。
8. **响应规范化不可跳过**：剥离 `<think>...</think>` 与 `reasoning_details`、从自由文本里提取最外层 JSON、解析失败先修复重试再降级。reasoning 模型（`ling-3.0-flash-free`）的推理 token 计入 `max_tokens`，**必须给足预算**，否则 `content` 为空且 `finish_reason=length`。
9. **密钥只从环境变量读**，不进日志、不进 prompt、不回显。
10. **LLM 推理端点走独立 failover 池**（`llm/failover.py`），与图片/视频/音频生成的 `router.py` 评分路由并行，不要混用同一套候选选择逻辑——两者共享同一个配置段 `llm_providers`（按 `kind` 区分 `general`/`media`），但端点一旦落到 `kind="media"`，就只服务 `router.py` 的打分目录，绝不会被 failover 池选中，反之亦然。
11. **媒体端点的主/备角色只是展示与审计元数据**：端点级 `role`/`backup_order` 不参与 `router.py` 的打分，胜出者始终由 quality/latency/cost/reliability 权重决定；只有 `kind="general"` 的 LLM 端点，端点级主/备才是 failover 硬路由依据。`capabilities` 仅声明能力 tag 与模型名。

## Prompt 与模型绑定

各 Agent 的 `SYSTEM_PROMPT` 已迁移为版本化 `AgentSkill`（后台可编辑/发布/回滚），`run_agent` 经 `get_active_prompt(node_role)` 读取，空库回退模块内硬编码默认值。模型绑定默认值如下（可在配置中心 `agents` 段热切换）：

| Agent | 默认模型 | 为什么 |
| --- | --- | --- |
| Safety | `doubao-seed-2-1-pro` | 输出干净 JSON，安全判定必须稳定可解析 |
| Planner | `kimi-k3` | |
| Quality | `kimi-k3` | |
| Copy | `ling-3.0-flash-free` | 免费、高频文案 |
| Router | 无 | 纯规则 |

网关**没有 embedding 模型**，语义检索用本地确定性实现（见 `zaolang-discovery-search`）。

## 改造切入点

- **加一个 Agent**：继承 `base.py` 的基类 → 在配置中心 `agents` 段加模型绑定字段 → 只经 `tools.py` 调领域服务 → 补 stub 分支，否则测试无法确定性运行。
- **给 Agent 加工具**：只加进 `tools.py`，函数签名保持窄（明确的参数、明确的返回），不要暴露 session。
- **加一个内置（假）供应商**：实现 `providers/base.py` 的协议 → 在 `router.py` 的 `PROVIDER_CATALOG` 登记能力、先验与 `provider_factory` → 在配置中心 `providers` 段加开关与限额 → 补 `ProviderStat` 统计。
- **加一个真实媒体供应商（管理台配置驱动）**：不改代码——去 `/admin/models` 新增一个 `kind="media"` 端点，勾选它支持的能力（文生图/图生图/文/图/视频生视频/音频生成）；`router.build_catalog(session)` 会在下一次路由时自动把它按能力展开进目录参与打分。只有当目标供应商的 HTTP 契约与 `aihubmix_media.py` 不同时才需要新写一个 `GenerationProvider` 实现。
- **改评分公式**：先对照现有 `router` 实现与单测；改了必须同步后台回放页的解释文案与单元测试。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_agent_gateway.py tests/unit/test_llm_normalize.py tests/unit/test_llm_gateway_modes.py tests/unit/test_llm_capabilities.py -v
make test-llm    # @pytest.mark.live 连通性冒烟，只在本地有密钥时跑，不进 CI
```
