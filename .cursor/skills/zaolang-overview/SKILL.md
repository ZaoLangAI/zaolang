---
name: zaolang-overview
description: 造浪（zaolang）仓库的总索引与路由表：说明 front/back/infra 的分工、19 个模块 skill 的边界，以及按修改意图该显式加载哪一个。Use when working anywhere in the zaolang repository, or when the user mentions 造浪 / zaolang, 作品与创作链 (works, lineage), 积分账本 (credits ledger), 生成任务 (generation jobs), 智能网关 (agent gateway), 后台运维台 (admin console), or asks where a feature lives in this codebase.
---

# 造浪（zaolang）总览

全球 AI 二创共享平台。**先读这张路由表，再显式加载对应模块 skill**，不要凭猜测改代码——本仓库的不变量集中在积分账本、任务状态机、许可与创作链三处，破坏后不会在类型检查里暴露。

## 仓库分工

| 路径 | 内容 |
| --- | --- |
| `back/` | FastAPI + Agno AgentOS，conda 环境 `zaolang`，Python 3.12 |
| `front/` | Next.js 16 App Router + Tailwind v4，fnm 读 `front/.node-version`；C 端与后台同一工程、会话与 API 隔离 |
| `infra/` | docker-compose：PostgreSQL 17 (pgvector) `5433`、Redis `6380`、MinIO `9000` |
| `docs/` | MkDocs 文档站源与运维手册 |
| `assets-pack/` | 用户素材投放目录，`manifest.json` 定义导入契约 |

后端分层：`api/v1`（HTTP 契约）→ `domain/*`（不变量所在）→ `models`（SQLAlchemy）。`agents` / `teams` / `workflows` / `providers` / `workers` 挂在 domain 之上，**Agent 只能通过 `app/agents/tools.py` 的白名单调用领域服务，返回值必须落库才算事实**。

## 按修改意图加载

| 你要改什么 | 加载 |
| --- | --- |
| 起服务、容器、环境变量、Makefile | `zaolang-local-env` |
| 加表、改列、写迁移 | `zaolang-data-model` |
| 加接口、改错误码、幂等、限流、鉴权 | `zaolang-api-contract` |
| 档位定价、路由权重、Feature Flag、智能体模型绑定 | `zaolang-platform-config` |
| 可见性、二创授权、许可快照、创作链边与墓碑 | `zaolang-domain-licensing-lineage` |
| 积分预扣与结算、回流分成、对账、支付 webhook | `zaolang-credits-billing` |
| 任务提交、状态机、SSE、Celery 队列、取消与重试 | `zaolang-generation-jobs` |
| Safety/Planner/Quality/Copy Agent、Router 评分、LLM 网关与响应规范化 | `zaolang-agent-gateway` |
| 上传预签名、私密对象下载、pHash 指纹、AI 溯源清单 | `zaolang-media-assets` |
| 检索、标签、pgvector 相似作品、风格预设 | `zaolang-discovery-search` |
| 审计日志、数据导出与删除、备份与生命周期 | `zaolang-compliance-audit` |
| C 端页面、共享组件、登录弹窗与动作恢复、命令面板 | `zaolang-frontend-ui` |
| 颜色令牌、深浅主题、SSR 无闪烁 | `zaolang-theming` |
| 三语文案、locale 与 region、货币日期格式 | `zaolang-i18n-region` |
| 创作链 DAG 图谱、版本参数 diff | `zaolang-lineage-graph` |
| 后台外壳、独立登录、RBAC 导航、表格与危险操作组件 | `zaolang-admin-console` |
| 后台十个运维域的接口与页面 | `zaolang-admin-ops` |
| GitHub Actions、Docker 镜像、release-please、文档站 | `zaolang-ci-release` |
| 写测试、跑 E2E、无障碍与视觉 QA | `zaolang-testing-qa` |

跨模块改动按依赖方向加载：`data-model` → `domain/*` → `api-contract` → 前端。

## 三条全局铁律

1. **以仓库实现为准。** 需求有歧义时读现有代码、`docs/` 与测试，不要凭空发明产品行为。
2. **金额是整数**（credits 与 minor unit），任何浮点参与金额计算都是 bug。
3. **ID 带类型前缀**（`u_` / `w_` / `job_` / `k_`…），由 `back/app/models/base.py:new_id` 生成，不要手写字符串 ID。

## 全量验证

```bash
make check   # lint + typecheck + 三语文案 + OpenAPI 漂移 + 全部测试
```

单项命令见各模块 skill 的「验证」一节。
