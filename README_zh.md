# 造浪 ZaoLang

[English](README.md)

全球 AI 图片与短视频二创共享平台。

「造浪」让用户从「看见灵感」直接进入「创作新版本」。每一次二创都会留下版本化的创作链（`LineageEdge`），继承原作者署名与许可快照；生成任务经由可解释的智能网关路由，在开源工作流与商业 API 之间选择有效成本更低的路线。

核心约束（不可妥协）：

- 前后端完全分离，浏览器不直连模型供应商、支付服务或裸 ComfyUI。
- PostgreSQL 是作品、任务、积分、授权与创作链的**唯一事实源**；智能体输出必须落库后才成为事实。
- 默认许可为「公开 · 仅展示」，作者必须主动开启二创授权。
- 生成前预扣积分，成功后结算实际消耗，失败或取消必须释放余额。
- 删除父作品不破坏后代溯源，采用隐藏或墓碑状态。

## 在线试用

对外可访问的部署实例是一个**测试试用环境**，用于端到端演示与验证功能，并非生产服务。其可用性、数据与生成内容可能随时被重置或清空，请勿依赖其中的任何内容。

## 技术栈

| 层 | 选型 |
|---|---|
| Web | Next.js 16 · React 19 · TypeScript · Tailwind v4 · next-intl |
| API | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic |
| 智能体 | Agno AgentOS，经 OpenAI 兼容网关接入模型 |
| 队列 | Redis · Celery |
| 数据 | PostgreSQL 17 + pgvector |
| 对象存储 | 腾讯云 COS（默认）或 MinIO（自建，S3 兼容，按需启动） |

前端用 [fnm](https://github.com/Schniz/fnm) 管理 Node 版本，后端用 conda 管理 Python 环境，外部依赖全部跑在本地容器。

## 支持的模型供应商

后台 `/admin/models` 的「服务商 → 已知模型」目录来自 `back/app/providers/model_catalog.py`。浏览器不直连这些站点；密钥只存在于后端。下列主页供运营核对渠道与价目。同一名义上游模型在不同渠道的价格不得混用。

### 接入渠道

| 目录 ID | 供应商 | 主页 | 文档 / 控制台 |
|---|---|---|---|
| `aihubmix` | AiHubMix（国际，USD） | [aihubmix.com](https://aihubmix.com) | [文档](https://docs.aihubmix.com) · [控制台](https://console.aihubmix.com) |
| `dmxapi` | DMXAPI（国内，CNY） | [www.dmxapi.cn](https://www.dmxapi.cn) | [文档](https://doc.dmxapi.cn) |
| `metaso` | 秘塔 | [metaso.cn](https://metaso.cn) | [MiniMax H3 价目](https://metaso.cn/minimax-h3) |
| `fal` | fal.ai | [fal.ai](https://fal.ai) | [文档](https://fal.ai/docs) |

目录中的已知模型：

- **AiHubMix**：MiniMax H3、通义万相 2.7 视频编辑、豆包 Seedance 2.5、GPT Image 2
- **DMXAPI**：MiniMax H3、MiniMax H3 视频再生成、豆包 Seedance 2.5、通义万相 3.0、豆包 Seedream 5.0 Pro、智谱 GLM-5.3-Flash、通义千问 Qwen3.8-Flash
- **秘塔**：MiniMax H3（官方 Video V2）
- **fal.ai**：MiniMax H3 Max

自定义端点仍可手填任意 `base_url` / 模型名；上表只覆盖目录预填项。

### 上游厂商

| 厂商 | 主页 |
|---|---|
| MiniMax | [minimax.io](https://www.minimax.io) · [开放平台（国内）](https://platform.minimaxi.com) |
| OpenAI | [openai.com](https://openai.com) |
| 火山引擎 / 豆包 | [volcengine.com](https://www.volcengine.com) · [火山方舟](https://ark.volcengine.com) |
| BytePlus | [byteplus.com](https://www.byteplus.com) |
| 阿里云 / 通义 | [aliyun.com](https://www.aliyun.com) |
| 智谱 | [zhipuai.cn](https://www.zhipuai.cn) · [开放平台](https://open.bigmodel.cn) |

## 快速开始

```bash
make setup     # 创建 conda 环境、安装前后端依赖
make up        # 启动 postgres / redis 容器
make migrate   # 执行数据库迁移
make seed      # 导入种子数据
make dev       # 同时启动 API、Worker 与 Web
```

打开 http://localhost:3000 进入 C 端，http://localhost:3000/zh-CN/admin 进入后台管理。种子账号见 `docs/local-development.md`。

完整命令见 `make help`。

## 目录结构

```text
front/        Next.js 前端，含 (site) C 端与 (admin) 后台两套外壳
back/         FastAPI 后端，含领域服务、智能体、供应商适配器与 Celery worker
infra/        docker-compose 与本地基础设施
assets-pack/  媒体素材投放目录
docs/         文档站源码与运维手册
.cursor/      按模块拆分的 Agent Skills
```

## 文档

- [本地开发指南](docs/local-development.md)
- [架构说明](docs/architecture.md)
- [运维手册](docs/ops-runbook.md)

## 参与贡献

提交信息建议遵循 [Conventional Commits](https://www.conventionalcommits.org/)。发版时手改 `front/package.json` 的 `version` 与 `APP_VERSION`。提交前请运行 `make check`。

## 许可

Apache License 2.0，见 [LICENSE](LICENSE)。第三方组件（如 OpenCut）保留其原有开源声明。
