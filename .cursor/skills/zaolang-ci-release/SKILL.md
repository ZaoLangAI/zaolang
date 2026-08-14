---
name: zaolang-ci-release
description: 造浪的工程交付链：本地 make check 与 pre-commit 门禁、本地 Docker 镜像与一键体验编排、手改版本号、MkDocs Material 文档站与内部专有许可基线。Use when changing pre-commit hooks, Dockerfiles, the release compose file, version numbers, the docs site, or repository/licence baseline files.
disable-model-invocation: true
---

# 本地交付、镜像与文档站

## 职责

保证「能构建、能发布、能查文档」。本仓库是内部专有产品。仓库不使用 GitHub Actions、GHCR、release-please 或 GitHub Pages。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `Makefile` | 唯一门禁入口：`make check`；一键体验：`make release-up` |
| `.pre-commit-config.yaml` | 本地钩子：ruff / mypy / eslint / prettier / OpenAPI 漂移 |
| `front/package.json` 的 `version` + `APP_VERSION` | 发版时手改，注入页脚 |
| `mkdocs.yml`（`strict: true`）+ `docs/` | 文档站，内嵌 `docs/openapi.json` |
| `back/Dockerfile`、`front/Dockerfile`、`infra/docker-compose.release.yml` | 本地生产镜像与一键体验编排 |

## 不可破坏的不变量

1. **唯一门禁是 `make check`。** E2E 与无障碍需要真实数据库与种子数据，是额外的本地套件，不要为了「更保险」把它们塞进 `make check`（那会让每次提交都依赖一整套种子库）。
2. **`make check` 里 `LLM_MODE=stub` 不可放开**：测试必须确定性、不需要密钥、不产生费用。`@pytest.mark.live` 的冒烟测试永不进 `make check`。
3. **版本号有两处**：发版时手改 `front/package.json` 的 `version`，并同步 `APP_VERSION`。不要只改一处。
4. **内部专有，不是开源合规。** 本仓库软件许可是内部专有（根目录 `LICENSE`）。C 端页脚只展示 `APP_VERSION`，**不要**再加源码仓库外链或 AGPL 声明。第三方 NOTICE/LICENSE（如 OpenCut MIT）不得删除。
5. **`mkdocs.yml` 是 `strict: true`**：死链与孤儿页会让构建失败。加文档要同时加进 `nav`。
6. **`docs/openapi.json` 是导出物**：`make docs` / `make docs-build` 会从 `back/openapi.json` 拷贝，不要手改。
7. **Docker 镜像带 ffmpeg/ffprobe**：后端 worker 的 `complete` 与 `media_analysis` 依赖 ffprobe。`back/Dockerfile` 已安装。不要从镜像里拿掉。
8. **不要重新引入 GitHub 托管构建**：不新增 `.github/workflows`、不推 GHCR、不用 release-please、不部署 GitHub Pages。

## 改造切入点

- **加一条检查**：先想清楚它是否需要数据库。需要 → 单独的 `make` 目标，不要塞进 `make check`；不需要 → 挂进现有 `make check` / pre-commit。
- **加一个 pre-commit 钩子**：`.pre-commit-config.yaml` 加 hook，并确认 `make check` 里有等价命令——两者要一致，否则本地跑 `make check` 通过却被钩子拦住。
- **改 Dockerfile**：`front` 依赖 `output: 'standalone'`（已在 `next.config.ts`）；`back` 用 conda 之外的 pip 安装以缩小镜像。改完在本地 `docker build` 或 `make release-up`。
- **加一页文档**：`docs/*.md` + `mkdocs.yml` 的 `nav`，然后 `make docs-build` 必须过。

## 验证

```bash
make check          # 全量本地门禁
make docs-build     # strict 模式构建文档站
make release-up     # 本地构建镜像并启动一键体验编排
```
