# 造浪 ZaoLang

[English](#english) · [简体中文](#简体中文)

全球 AI 图片与短视频二创共享平台。发现作品、查看来源与授权、复用素材与参数、通过智能网关生成新版本，并在不可断开的创作链中完成署名、授权与发布。

---

## 简体中文

### 这是什么

「造浪」让用户从「看见灵感」直接进入「创作新版本」。每一次二创都会留下版本化的创作链（`LineageEdge`），继承原作者署名与许可快照；生成任务经由可解释的智能网关路由，在开源工作流与商业 API 之间选择有效成本更低的路线。

核心约束（不可妥协）：

- 前后端完全分离，浏览器不直连模型供应商、支付服务或裸 ComfyUI。
- PostgreSQL 是作品、任务、积分、授权与创作链的**唯一事实源**；智能体输出必须落库后才成为事实。
- 默认许可为「公开 · 仅展示」，作者必须主动开启二创授权。
- 生成前预扣积分，成功后结算实际消耗，失败或取消必须释放余额。
- 删除父作品不破坏后代溯源，采用隐藏或墓碑状态。

### 技术栈

| 层 | 选型 |
|---|---|
| Web | Next.js 16 · React 19 · TypeScript · Tailwind v4 · next-intl |
| API | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic |
| 智能体 | Agno AgentOS，经 OpenAI 兼容网关接入模型 |
| 队列 | Redis · Celery |
| 数据 | PostgreSQL 17 + pgvector |
| 对象存储 | MinIO（本地，S3 兼容） |

前端用 [fnm](https://github.com/Schniz/fnm) 管理 Node 版本，后端用 conda 管理 Python 环境，外部依赖全部跑在本地容器。

### 快速开始

```bash
make setup     # 创建 conda 环境、安装前后端依赖
make up        # 启动 postgres / redis / minio 容器
make migrate   # 执行数据库迁移
make seed      # 导入种子数据
make dev       # 同时启动 API、Worker 与 Web
```

打开 http://localhost:3000 进入 C 端，http://localhost:3000/zh-CN/admin 进入后台管理。种子账号见 `docs/local-development.md`。

完整命令见 `make help`。

### 目录结构

```text
front/        Next.js 前端，含 (site) C 端与 (admin) 后台两套外壳
back/         FastAPI 后端，含领域服务、智能体、供应商适配器与 Celery worker
infra/        docker-compose 与本地基础设施
assets-pack/  媒体素材投放目录
docs/         文档站源码与运维手册
.cursor/      按模块拆分的 Agent Skills
```

### 文档

- [本地开发指南](docs/local-development.md)
- [架构说明](docs/architecture.md)
- [运维手册](docs/ops-runbook.md)

### 参与贡献

提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/)，版本号与 CHANGELOG 由 release-please 自动生成。提交前请运行 `make check`。

### 许可

[AGPL-3.0](LICENSE)。若你把本项目或其修改版本作为网络服务提供给他人使用，AGPL 第 13 条要求你向这些用户提供对应的完整源码。

---

## English

### What is this

ZaoLang is a global platform for AI-generated image and short-video remixing. It takes users straight from "seeing inspiration" to "creating a new version". Every remix records a versioned lineage edge that inherits the original author's attribution and a license snapshot, while generation jobs are routed by an explainable gateway that picks the lowest effective-cost route across open workflows and commercial APIs.

Non-negotiable constraints:

- Strict frontend/backend separation. The browser never talks directly to model providers, payment services, or a bare ComfyUI.
- PostgreSQL is the single source of truth for works, jobs, credits, licensing, and lineage. Agent output only becomes fact after it is persisted.
- The default license is public view-only; authors must explicitly opt in to remixing.
- Credits are reserved before generation, captured on success, and released on failure or cancellation.
- Deleting a parent work never breaks descendant provenance; it becomes hidden or a tombstone.

### Stack

| Layer | Choice |
|---|---|
| Web | Next.js 16 · React 19 · TypeScript · Tailwind v4 · next-intl |
| API | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic |
| Agents | Agno AgentOS over an OpenAI-compatible gateway |
| Queue | Redis · Celery |
| Data | PostgreSQL 17 + pgvector |
| Object storage | MinIO (local, S3-compatible) |

Node versions are managed with fnm, Python with conda, and all external dependencies run in local containers.

### Getting started

```bash
make setup && make up && make migrate && make seed && make dev
```

Then open http://localhost:3000. See [docs/local-development.md](docs/local-development.md) for seeded accounts and the full command list.

### License

[AGPL-3.0](LICENSE). If you offer this software (or a modified version) to users over a network, section 13 requires you to provide those users with the corresponding source.
