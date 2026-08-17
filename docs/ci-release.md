# 工程与发布

仓库不使用 GitHub Actions、GHCR、release-please 或 GitHub Pages。构建、门禁、镜像与文档站都在本机完成。

## 本地门禁

唯一质量门禁是 `make check`（lint + typecheck + 文案校验 + OpenAPI 漂移 + 前后端测试）。`make hooks` 安装 pre-commit 钩子，覆盖 ruff / mypy / prettier / eslint / tsc / 文案校验，以及在后端 schema 变动时校验 OpenAPI 类型漂移。

```bash
make check   # 提交前跑一遍完整门禁
```

设计取舍：

- **后端跑真实依赖，不跑 mock。** schema 依赖 pgvector、部分索引和条件 UPDATE，限流与配置缓存依赖 Redis，上传链路依赖 S3 语义。用假实现只能证明假实现是对的。
- **`make check` 不绕过假网关 fixture。** 生产代码只有一种 LLM 调用行为（真实网关，失败即报错），测试的确定性靠 `back/tests/conftest.py` 的 autouse fixture 自动把 `llm_client.complete`/`stream_complete` 换成 `tests/fake_llm_gateway.py` 的假实现，不需要密钥、不产生费用、结果确定。真实网关的连通性由本地 `make test-llm`（`@pytest.mark.live`）覆盖，不进 `make check`。
- **先跑迁移再跑测试。** 本地 `make migrate` 证明迁移能作用于空库——这正是部署时会发生的事。
- **Node 版本读 `.node-version`。** 和 fnm 同一个来源，不要另开一套版本号。

E2E、axe 无障碍扫描是额外的本地套件（需要真实数据库与种子数据），不进 `make check`。已知代价：存在「本地没跑就合并」的风险，因此提交前应跑 `make check`，钩子会拦住大部分静态问题。

## 版本

发版时手改两处，并按需更新 `CHANGELOG.md`：

1. `front/package.json` 的 `version`
2. `APP_VERSION`（`front/.env.example` / `back/.env.example`，构建时注入页脚）

提交信息建议遵循 [Conventional Commits](https://www.conventionalcommits.org/)，方便人读历史，但不再驱动自动升版。

构建时通过 `APP_VERSION` 注入前端页脚，方便对照本次运行的构建。页脚只展示版本号，不再提供源码仓库链接。

## 容器镜像

| 镜像 | 内容 |
| --- | --- |
| `zaolang-back:local` | FastAPI + Celery worker/beat/poller（同一镜像，不同 command） |
| `zaolang-front:local` | Next.js standalone 产物 |

从仓库里的 `back/Dockerfile` 与 `front/Dockerfile` 本地构建，不推远程仓库。后端镜像必须带 ffmpeg/ffprobe：worker 的 `complete` 与 `media_analysis` 依赖它。

API、worker、poller 与 beat 共用一个镜像是刻意的：它们共享领域代码，分成多个镜像就有可能部署到不同 revision，然后在状态机迁移上打架。Beat 必须常驻；异步供应商轮询、卡死任务回收和积分释放都依赖它调度。

前端镜像有一个约束值得记住：`NEXT_PUBLIC_API_URL` 会被内联进浏览器 bundle，因此它是**构建期**参数（`build-args`），不是运行期环境变量。服务端读的 `API_INTERNAL_URL` 才是运行期配置。

## 一键体验

```bash
make release-up
```

等价于 `docker compose -f infra/docker-compose.release.yml up -d --build`。编排里 `migrate` 是独立的一次性服务，`api` 与 `worker` 都等它 `service_completed_successfully`，这样 API 永远不会和 schema 赛跑。文件里的密钥是开发默认值，暴露到 localhost 之外前必须替换。

## 文档站

MkDocs Material 只在本地构建。`make docs` / `make docs-build` 会先把后端导出的 `openapi.json` 拷进文档目录，所以接口参考始终跟着代码走。

```bash
make docs         # 本地预览
make docs-build   # strict 模式构建，死链即失败
```
