---
name: zaolang-ci-release
description: 造浪的工程交付链：GitHub Actions（backend.yml / frontend.yml / images.yml / release.yml / pages.yml）、pre-commit 本地门禁、GHCR 多架构镜像、release-please 版本自动化、MkDocs Material 文档站与 AGPL 合规要求。Use when changing CI workflows, pre-commit hooks, Dockerfiles, container publishing, release automation, the docs site, or repository/licence baseline files.
disable-model-invocation: true
---

# CI、发布与文档站

## 职责

保证「能构建、能发布、能查文档」，以及 AGPL-3.0 的合规义务。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `.github/workflows/backend.yml` | `ruff` + `mypy` + `pytest`，service containers 起 pgvector/redis/minio，**强制 `LLM_MODE=stub`** |
| `.github/workflows/frontend.yml` | `eslint` + `tsc --noEmit` + `next build`，Node 版本读 `front/.node-version` |
| `.github/workflows/images.yml` | GHCR 多架构镜像（amd64/arm64）+ SBOM + provenance |
| `.github/workflows/release.yml` | release-please |
| `.github/workflows/pages.yml` | MkDocs 文档站部署 |
| `.pre-commit-config.yaml` | 本地门禁：ruff / mypy / eslint / prettier / OpenAPI 漂移 |
| `release-please-config.json` + `.release-please-manifest.json` | 版本策略与中文 changelog 分节 |
| `mkdocs.yml`（`strict: true`）+ `docs/` | 文档站，内嵌 `docs/openapi.json` |
| `back/Dockerfile`、`front/Dockerfile`、`infra/docker-compose.release.yml` | 生产镜像与一键体验编排 |

## 不可破坏的不变量

1. **CI 只有 backend 与 frontend 两条必需检查**。E2E、无障碍、类型漂移检查**刻意不进 CI**（需要真实数据库与种子数据），改由本地 `make` 与 pre-commit 执行。想把它们塞进 CI 前，先确认这个权衡是否真的要翻。
2. **CI 里 `LLM_MODE=stub` 不可放开**：测试必须确定性、不需要密钥、不产生费用。`@pytest.mark.live` 的冒烟测试永不进 CI。
3. **两条流水线都带并发取消与路径过滤**，不要为了「更保险」去掉路径过滤，那会让每个文档改动都跑满 CI。
4. **Conventional Commits 是硬要求**：release-please 靠它推导版本号与 CHANGELOG。提交信息乱写等于版本号乱跳。
5. **版本号有两处**：release-please 通过 `extra-files` 同步 `front/package.json` 的 `version`；不要手改。
6. **AGPL 第 13 条**：C 端页脚与后台「关于」必须提供源码仓库链接与构建版本号（`SOURCE_REPOSITORY_URL` / `APP_VERSION` 注入 `front/next.config.ts` 的 `env`）。**删掉页脚链接是许可证违规**，不是 UI 优化。
7. **`mkdocs.yml` 是 `strict: true`**：死链与孤儿页会让构建失败。加文档要同时加进 `nav`。
8. **`docs/openapi.json` 是导出物**：`make docs` / `make docs-build` 会从 `back/openapi.json` 拷贝，不要手改。
9. **镜像发布策略**：main 推 `edge`，release tag 推语义化版本，都带 SBOM 与 provenance。

## 改造切入点

- **加一条 CI 检查**：先想清楚它是否需要数据库。需要 → 放本地门禁；不需要 → 挂在现有两条流水线里，不要新开 workflow（必需检查越多，PR 越难合）。
- **加一个 pre-commit 钩子**：`.pre-commit-config.yaml` 加 hook，并确认 `make check` 里有等价命令——两者要一致，否则本地跑 `make check` 通过却被钩子拦住。
- **改 Dockerfile**：`front` 依赖 `output: 'standalone'`（已在 `next.config.ts`）；`back` 用 conda 之外的 pip 安装以缩小镜像。改完在本地 `docker build` 两个架构中至少一个。
- **加一页文档**：`docs/*.md` + `mkdocs.yml` 的 `nav`，然后 `make docs-build` 必须过。

## 需要在 GitHub 网页端手动开启的项

见 `docs/github-setup.md`：分支保护与必需状态检查（backend / frontend）、Actions 的 `packages: write`、Pages 来源设为 GitHub Actions。

## 验证

```bash
make check          # 与 CI 等价的本地全量门禁
make docs-build     # strict 模式构建文档站
cd back && docker build -t zaolang-back:local .
cd front && docker build -t zaolang-front:local .
```
