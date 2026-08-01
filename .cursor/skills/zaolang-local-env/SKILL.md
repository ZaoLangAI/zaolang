---
name: zaolang-local-env
description: 造浪的本地环境与命令入口：conda/fnm 双工具链、OrbStack 容器（pgvector 5433 / Redis 6380 / MinIO 9000）、Makefile 目标、环境变量与端口约定、种子账号。Use when starting or fixing the local stack, editing the Makefile, docker-compose, .env files, ports, conda or fnm setup, or when a command like make up / make seed / make dev fails.
disable-model-invocation: true
---

# 本地环境与命令入口

## 职责

把「跑起来」这件事收敛到 `Makefile`：容器、迁移、种子、三个开发进程、质量门禁全部有对应目标，不要在终端里手拼命令。

## 关键路径

| 路径 | 作用 |
| --- | --- |
| `Makefile` | 唯一入口。`make help` 列全部目标 |
| `infra/docker-compose.yml` | postgres(pgvector/pg17) / redis / minio / minio-init |
| `infra/.env.example` | compose 变量（端口、MinIO 凭据、桶名） |
| `back/environment.yml` + `back/requirements*.txt` | conda 环境 `zaolang`，Python 3.12 |
| `back/.env.example` → `back/.env` | 后端配置，含 `LLM_MODE`、`LLM_API_KEY`、`CORS_ORIGINS` |
| `front/.node-version` | fnm 读的 Node 版本 |
| `front/.env.example` → `front/.env.local` | `API_INTERNAL_URL`（RSC 用）与 `NEXT_PUBLIC_API_URL`（浏览器与 SSE 用） |
| `back/app/config.py` | pydantic-settings，所有默认值的唯一来源 |

## 不可破坏的约定

- **端口刻意错开**：Postgres `5433`、Redis `6380`，避开机器上已有服务。改端口要同时改 `infra/.env.example` 与 `back/.env`。
- **密钥只进 `back/.env`**（已 gitignore）。`.env.example` 只放占位符；日志、Agent prompt、配置中心界面都不得回显密钥。
- **两条工具链不混用**：后端命令一律 `conda run -n zaolang`，前端一律先 `fnm use`。Makefile 里的 `CONDA_RUN` / `FNM_ENV` 已经封好。
- **`make seed` 会先 TRUNCATE 业务表**，只在本地与测试环境用；后台的 seed 面板在生产环境直接拒绝。
- Alembic 只有一条线性迁移链，`make migrate` 必须能在空库上一路升到 head。

## 常用目标

```bash
make setup          # 建 conda 环境、装前后端依赖、复制 .env
make up             # 起容器并创建 MinIO 桶
make migrate seed   # 建表 + 种子数据
make dev            # 并行起 API(8000) / Celery worker / Web(3000)
make reset          # 销毁数据卷后重建（up + migrate + seed）
make logs
```

种子账号统一密码 `Zaolang2026`：`linhai`（作者）、`mizuki`（二创者）、`reviewer`、`operator`、`admin`、`driftwood`（已封禁，用来验证 401 与后台用户运维）。全部邮箱形如 `<handle>@zaolang.dev`。

## 改造切入点

- **新增外部依赖**：先加进 `infra/docker-compose.yml` 并带健康检查（`make up` 用 `--wait`），再在 `back/app/config.py` 加配置项与默认值，最后进 `back/app/api/health.py` 的探针，否则后台系统健康页看不到它。
- **新增环境变量**：`config.py` 加字段 → `back/.env.example` 加占位符 → 如果 CI 需要，改 `.github/workflows/backend.yml` 的 env。三处缺一，别人 clone 下来就跑不起来。
- **新增 Celery 队列**：`back/app/workers/celery_app.py` 注册路由后，务必同步 `Makefile` 的 `dev-worker` 的 `-Q` 列表与后台健康页的队列清单。

## 验证

```bash
make up && make migrate && make seed
curl -s localhost:8000/health | jq        # 依赖探针全 ok
make dev                                  # 三个进程都不报错
```

容器起不来先看 `orb start`；`pgvector` 扩展由迁移创建，`psql -c '\dx'` 里应能看到。
