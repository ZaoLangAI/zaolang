# 工程与发布

## 构建检查

只有两条流水线作为 PR 必需状态检查，都带并发取消与路径过滤：

| 工作流 | 做什么 | 依赖 |
| --- | --- | --- |
| `backend.yml` | `ruff` → `mypy` → `alembic upgrade head` → `pytest` | service containers 起 `pgvector/pgvector:pg17`、`redis:8`、MinIO |
| `frontend.yml` | `eslint` → `prettier --check` → 文案校验 → `tsc --noEmit` → `next build` | 缓存 npm 与 `.next/cache` |

两条流水线的设计取舍：

- **后端跑真实依赖，不跑 mock。** schema 依赖 pgvector、部分索引和条件 UPDATE，限流与配置缓存依赖 Redis，上传链路依赖 S3 语义。用假实现只能证明假实现是对的。
- **CI 强制 `LLM_MODE=stub`。** 不需要密钥、不产生费用、结果确定。真实网关的连通性由本地 `make test-llm` 覆盖。
- **先跑迁移再跑测试。** `alembic upgrade head` 单独成步，证明迁移能作用于空库——这正是部署时会发生的事。
- **Node 版本读 `.node-version`。** 和本地 fnm 同一个来源，CI 不会偷偷用另一个大版本。

E2E、axe 无障碍扫描与 OpenAPI 类型漂移检查**不在 CI 里**，改由本地 `make check` 与 pre-commit 执行。已知代价：存在「本地没跑就合并」的风险。

## 本地门禁

`make hooks` 安装 pre-commit 钩子，覆盖 ruff / mypy / prettier / eslint / tsc / 文案校验，以及在后端 schema 变动时校验 OpenAPI 类型漂移。

```bash
make check   # 提交前跑一遍完整门禁
```

## 版本与发布

`release-please` 依据 Conventional Commits 推导版本号：

1. 往 main 推 `feat:` / `fix:` 等提交。
2. `release.yml` 维护一个 `chore(main): release x.y.z` 的 PR，里面是 CHANGELOG 与版本号变更。
3. 合并那个 PR → 打 tag → 建 GitHub Release。
4. Release 发布触发 `images.yml` 构建带语义化版本标签的镜像。

版本号会同步写进 `front/package.json`，构建时通过 `APP_VERSION` 注入前端页脚——AGPL 第 13 条要求网络用户能拿到对应版本的源码，页脚里的仓库链接加版本号就是这个要求的落点。

## 容器镜像

| 镜像 | 内容 |
| --- | --- |
| `ghcr.io/zaolangai/zaolang-back` | FastAPI + Celery worker（同一镜像，不同 command） |
| `ghcr.io/zaolangai/zaolang-front` | Next.js standalone 产物 |

- 架构：`linux/amd64` + `linux/arm64`（arm64 走 QEMU 模拟，靠 GHA 层缓存把重复构建时间压下来）。
- 每次推送附 SBOM 与 provenance 证明（`actions/attest-build-provenance`）。
- 标签：main 推 `edge` 与短 sha；release tag 推 `x.y.z`、`x.y`、`x`。

API 与 worker 共用一个镜像是刻意的：它们共享领域代码，分成两个镜像就有可能部署到两个不同的 revision，然后在状态机迁移上打架。

前端镜像有一个约束值得记住：`NEXT_PUBLIC_API_URL` 会被内联进浏览器 bundle，因此它是**构建期**参数（`build-args`），不是运行期环境变量。服务端读的 `API_INTERNAL_URL` 才是运行期配置。

## 一键体验

```bash
docker compose -f infra/docker-compose.release.yml up -d
ZAOLANG_VERSION=v1.2.3 docker compose -f infra/docker-compose.release.yml up -d  # 固定版本
```

编排里 `migrate` 是独立的一次性服务，`api` 与 `worker` 都等它 `service_completed_successfully`，这样 API 永远不会和 schema 赛跑。文件里的密钥是开发默认值，暴露到 localhost 之外前必须替换。

## 文档站

`pages.yml` 用 MkDocs Material 构建并部署到 GitHub Pages，构建前把后端导出的 `openapi.json` 拷进文档目录，所以接口参考始终跟着代码走。本地预览：

```bash
make docs
```
