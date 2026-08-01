# 仓库设置清单

仓库创建后，下面几项**必须在 GitHub 网页端手动开启**，代码里改不了。

## 必须做

### 1. 分支保护

`Settings → Branches → Add branch ruleset`，作用于 `main`：

- 要求 PR 才能合并。
- 必需状态检查：`backend / ruff + mypy + pytest` 与 `frontend / eslint + tsc + build`。
- 要求分支在合并前与 main 同步。
- 禁止强推与删除分支。

### 2. Actions 权限

`Settings → Actions → General`：

- Workflow permissions 设为 **Read repository contents and packages permissions**。各工作流已在文件里声明自己需要的更高权限（`images.yml` 需要 `packages: write` 与 `id-token: write`）。
- 勾选 **Allow GitHub Actions to create and approve pull requests**——否则 release-please 建不出发布 PR。

### 3. GitHub Pages

`Settings → Pages`：Source 选 **GitHub Actions**。选错成 branch 部署会让 `pages.yml` 静默失败。

### 4. 包可见性

首次 `images.yml` 跑完后，两个 GHCR 包默认是 private。要让别人能 `docker pull`，在 `Packages → zaolang-back / zaolang-front → Package settings` 里改成 Public，并把仓库连到包上（`Connect repository`），这样包页面才会显示 README 与许可。

## 建议做

### 仓库变量

`Settings → Secrets and variables → Actions → Variables`：

| 变量 | 用途 | 不设的后果 |
| --- | --- | --- |
| `PUBLIC_API_URL` | 前端镜像构建时内联的浏览器侧 API 地址 | 回落到 `http://localhost:8000`，镜像只能本机自玩 |

**不要**在仓库 secrets 里放 `LLM_API_KEY`：CI 强制 `LLM_MODE=stub`，不需要密钥，放进去只是多一个泄露面。

### Secret scanning

`Settings → Code security`：开启 Secret scanning 与 push protection。本项目没有启用 CodeQL、Dependabot 与 gitleaks，依赖与密钥风险靠这两项加人工兜底。

## 已知的手动环节

- 首次发布前需要在 AIHubMix 控制台轮换一次 LLM key，仓库是公开的，任何进过对话记录或提交历史的 key 都应视为已泄露。
- `release-please` 的第一次运行会从 `0.0.0` 起算，如果仓库已经有历史 tag，需要手动对齐 `.release-please-manifest.json`。
