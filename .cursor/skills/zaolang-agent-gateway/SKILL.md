---
name: zaolang-agent-gateway
description: 造浪的 Agno 智能网关与 LLM 接入：Safety/Planner/Quality/Copy/Intent Router Agent、硬过滤 + LLM 驱动的供应商选型、Generation Gateway Team 与 Workflow、工具白名单、OpenAI 兼容网关（AIHubMix）三档模式、响应规范化与 AgentRun 记录。Use when changing an agent prompt or tool, the routing/selection logic, provider candidates, the LLM client, response normalisation, model bindings, or stub/degradation behaviour.
disable-model-invocation: true
---

# Agno 智能网关与 LLM 接入

## 职责

智能体负责**判断**（安全、规划、质检、文案、路由选型），供应商负责**产出**（图片、视频）。两者之间由 `router.py` 的硬性能力/档位/启用状态过滤 + `intent_router` Agent 的 LLM 选型共同连接：过滤是代码，选谁是模型。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/agents/safety.py` / `planner.py` / `quality.py` / `copywriter.py` | 四个判断类 Agent（模块内常量作 fallback） |
| `back/app/agents/intent_router.py` | `classify()`（档位建议，只降不升）与 `select_provider()`（LLM 路由选型，见不变量 #1） |
| `back/app/domain/agent_skills/service.py` | `AgentNode`（角色）/ `AgentProfile`（智能体本体）/ `AgentSkill` 版本化 Prompt，`resolve_prompt(role, agent_id, slot)` |
| `back/app/domain/agent_skills/presets.py` | `ROLE_PRESETS`：管理台建智能体时角色下拉的**唯一**来源（代码维护的目录，不是表） |
| `back/app/domain/agent_skills/templates.py` | `SKILL_TEMPLATES`：技能编辑器「从模板填充」的起始提示词，内置五角色的模板直接引用各模块的 `SYSTEM_PROMPT` 常量 |
| `back/app/agents/custom.py` | `custom_agent` 节点用的通用判断执行器，角色在运行时由节点配置给出 |
| `back/app/agents/router.py` | 硬过滤 + LLM 选型编排：`ProviderCapability` / `Candidate` / `RoutingDecision` / `route()`，不含打分公式 |
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

1. **硬性过滤是代码，选谁是 LLM，没有兜底公式。** `router.route()` 先用代码过滤掉物理/业务上不可用的候选（能力不支持、档位不支持、供应商禁用、超预算延迟、本次 job 已失败过），只有过滤后仍合格的候选才会连同各自的成功率/延迟/成本一起交给 `intent_router.select_provider()`；LLM 返回哪个就用哪个，`reason` 就是它给出的理由。**LLM 不可用、降级或选了一个不在合格集合里的供应商时，`route()` 直接返回 `selected=None`（`reason="llm_selection_unavailable"`），绝不回退到任何加权公式或排序规则**——曾经的 `quality/latency/cost/reliability` 加权公式与 `routing_weights` 配置已被移除，不要凭直觉重新加回来。
2. **候选信息只做展示与输入，不做决策。** `Candidate` 的 `success_rate`/`avg_latency_ms`/`effective_cost`/`configured_weight` 是喂给 LLM 的上下文、也是后台「决策逐候选回放」的展示字段，但代码里不允许再出现按这些字段排序/加权选出胜者的逻辑——排序权只属于 `intent_router`。**创作类 `AgentProfile` 上配置的 `media_candidates` 是这条不变量的一处例外，但只在过滤方向上**：`(endpoint_id, capability)` 白名单会在硬过滤阶段收窄候选集（跟"供应商禁用"同一性质），每项的 `weight` 则原样透传成候选的 `configured_weight` 交给 LLM 权衡，代码不得据此排序。
3. **`effective_cost` 包含失败重试放大**；统计样本不足时用保守先验，不能假装成功率 100%。
4. **每个候选的淘汰理由都要落 `ProviderAttempt` / 决策记录**，后台「决策逐候选回放」依赖它。
5. **Agent 输出不是事实，落库才是**。Agent 只能通过 `tools.py` 白名单调领域服务；不要给 Agent 直接的 session 或任意 SQL。
6. **测试与 CI 强制 `LLM_MODE=stub`**。三档模式：`openai_compatible`（只走真实网关，失败即报错）、`stub`（确定性假响应）、`auto`（网关失败自动降级到 stub）。降级必须写入 `AgentRun` 的降级标记与原因，并在界面明确标识。
7. **每次调用写 `AgentRun`**：模型、token 用量、延迟、是否降级。后台智能体运维完全建立在这张表上。
8. **响应规范化不可跳过**：剥离 `<think>...</think>` 与 `reasoning_details`、从自由文本里提取最外层 JSON、解析失败先修复重试再降级。reasoning 模型（`ling-3.0-flash-free`）的推理 token 计入 `max_tokens`，**必须给足预算**，否则 `content` 为空且 `finish_reason=length`。
9. **密钥只从环境变量读**，不进日志、不进 prompt、不回显。
10. **LLM 推理端点走独立 failover 池**（`llm/failover.py`），与图片/视频/音频生成的 `router.py` 选型路由并行，不要混用同一套候选选择逻辑——两者共享同一个配置段 `llm_providers`（按 `kind` 区分 `general`/`media`），但端点一旦落到 `kind="media"`，就只服务 `router.py` 的候选目录，绝不会被 failover 池选中，反之亦然。**除非绑定的 `AgentProfile` 显式钉了模型**：填了 `default_endpoint_id`（可选再加 `backup_endpoint_id`）时，这两个端点会被排到 failover 池的最前面优先尝试，池里其余端点仍作为后续兜底，顺序不变——这是优先级调整，不是把池换掉。
11. **角色只能来自 `ROLE_PRESETS`。** 管理台建智能体时角色是下拉不是自由文本：工作流节点类型是代码白名单，没有任何节点类型认识的角色建出来也永远不会被执行。要让一个新的判断类角色能跑，要么给它加专属节点类型，要么用通用的 `custom_agent` 节点（角色由 `config.agent_role` 在运行时给出）。
12. **工作流按智能体 id 绑定，且绑定的智能体必须是该节点要求的角色。** 一个角色下可以有多个智能体（管理台按角色分组，但分组只是标题，可操作的对象只有智能体）；节点配置里的 `agent_id` / `selector_agent_id` 存的是 `AgentProfile.id`，不是名称也不是 key——名称随时可改，已发布的图必须一直指向同一个智能体。角色不匹配在发布时报错（`workflow_templates.service._binding_errors`），运行时也会拒绝并回落到角色默认智能体（`resolve_prompt`），因为拿文案智能体跑安全审核会把它产出的任何东西当成放行结论。留空表示该角色的默认智能体。
13. **媒体端点的主/备角色只是展示与审计元数据**：端点级 `role`/`backup_order` 不参与 `router.py` 的候选目录构建，胜出者始终由 `intent_router.select_provider()` 这次 LLM 调用决定；只有 `kind="general"` 的 LLM 端点，端点级主/备才是 failover 硬路由依据。`media` 端点一个模型 id + 输入/输出模态声明，能力 tag 由映射表推导，不再逐能力填模型名。

## Prompt 与模型绑定

各 Agent 的 `SYSTEM_PROMPT` 已迁移为版本化 `AgentSkill`（后台可编辑/发布/回滚），`run_agent` 经 `resolve_prompt()` 读取，空库回退模块内硬编码默认值。模型绑定按「智能体显式绑定 → 配置中心 `agents` 段角色默认值」两层解析（`base.py` 的 `effective_binding`），角色默认值如下（可在配置中心热切换）：

| Agent | 默认模型 | 为什么 |
| --- | --- | --- |
| Safety | `doubao-seed-2-1-pro` | 输出干净 JSON，安全判定必须稳定可解析 |
| Planner | `kimi-k3` | |
| Quality | `kimi-k3` | |
| Copy | `ling-3.0-flash-free` | 免费、高频文案 |
| Intent Router | `kimi-k3` | 一个 agent 身份、两次互不共享系统提示词的调用：`classify()` 判档位、`select_provider()` 选供应商（见 `intent_router.py` 顶部 docstring） |

网关**没有 embedding 模型**，语义检索用本地确定性实现（见 `zaolang-discovery-search`）。

## 改造切入点

- **加一个 Agent**：继承 `base.py` 的基类 → 在配置中心 `agents` 段加模型绑定字段 → 只经 `tools.py` 调领域服务 → 补 stub 分支，否则测试无法确定性运行。
- **加一个角色预设**：往 `presets.py` 的 `ROLE_PRESETS` 加一项（判断类还是创作类、创作类要锁哪些 `operations`）→ 判断类顺手在 `templates.py` 补一个起始模板 → 确认它能被某个节点类型调用（专属节点类型或 `custom_agent`），否则建出来的智能体不会执行。预设是代码目录不是表，加预设仍是一次工程改动，这正是"角色只能从预设选"想要的效果。
- **给 Agent 加工具**：只加进 `tools.py`，函数签名保持窄（明确的参数、明确的返回），不要暴露 session。
- **加一个内置（假）供应商**：实现 `providers/base.py` 的协议 → 在 `router.py` 的 `PROVIDER_CATALOG` 登记能力、先验与 `provider_factory` → 在配置中心 `providers` 段加开关与限额 → 补 `ProviderStat` 统计。
- **加一个真实媒体供应商（管理台配置驱动）**：不改代码——去 `/admin/models` 新增一个 `kind="media"` 端点，填它的模型 id，再勾选它支持的输入模态（文本/图片/视频）与输出模态（图片/视频/音频）；能力 tag 由 `capabilities_for_modalities` 自动推导，`router.build_catalog(session)` 会在下一次路由时把它按能力展开进候选目录，交给 `intent_router.select_provider()` 挑选。同一凭证要用不同模型服务不同能力就配多个端点。只有当目标供应商的 HTTP 契约与 `aihubmix_media.py` 不同时才需要新写一个 `GenerationProvider` 实现。
- **改选型逻辑**：不要在 `router.py` 里加任何排序/加权代码——那是刻意留白的（不变量 #1）。要改"选哪个供应商"的判断标准，去改 `intent_router.py` 的 `SELECT_PROVIDER_SYSTEM_PROMPT`（或后台可发布的 `AgentSkill` 版本），并同步 `llm/stub.py` 里 `_intent_router` 的确定性分支，否则 `LLM_MODE=stub` 下的路由测试会全部改变行为。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_agent_gateway.py tests/unit/test_llm_normalize.py tests/unit/test_llm_gateway_modes.py tests/unit/test_llm_capabilities.py -v
make test-llm    # @pytest.mark.live 连通性冒烟，只在本地有密钥时跑，不进 CI
```
