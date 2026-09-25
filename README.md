# ZaoLang

[中文文档](README_zh.md)

A global platform for AI-generated image and short-video remixing.

ZaoLang takes users straight from "seeing inspiration" to "creating a new version". Every remix records a versioned lineage edge that inherits the original author's attribution and a license snapshot, while generation jobs are routed by an explainable gateway that picks the lowest effective-cost route across open workflows and commercial APIs.

Non-negotiable constraints:

- Strict frontend/backend separation. The browser never talks directly to model providers, payment services, or a bare ComfyUI.
- PostgreSQL is the single source of truth for works, jobs, credits, licensing, and lineage. Agent output only becomes fact after it is persisted.
- The default license is public view-only; authors must explicitly opt in to remixing.
- Credits are reserved before generation, captured on success, and released on failure or cancellation.
- Deleting a parent work never breaks descendant provenance; it becomes hidden or a tombstone.

## Try it

The publicly reachable deployment of this project is a **testing/trial environment**, used to demo and validate features end-to-end — it is not a production service. Availability, data, and generated content on it may be reset or wiped at any time without notice; do not rely on it for anything you need to keep.

## Stack

| Layer | Choice |
|---|---|
| Web | Next.js 16 · React 19 · TypeScript · Tailwind v4 · next-intl |
| API | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic |
| Agents | Agno AgentOS over an OpenAI-compatible gateway |
| Queue | Redis · Celery |
| Data | PostgreSQL 17 + pgvector |
| Object storage | Tencent Cloud COS (default) or MinIO (self-hosted, S3-compatible, started on demand) |

Node versions are managed with [fnm](https://github.com/Schniz/fnm), Python with conda, and all external dependencies run in local containers.

## Supported model vendors

The `/admin/models` "service provider → known model" picker is backed by `back/app/providers/model_catalog.py`. The browser never talks to these sites; credentials live only on the backend. Use the pages below to verify a channel and its list prices. Two catalogue vendors are never assumed to charge the same amount for the same nominal upstream model.

### Gateway channels

| Catalog ID | Vendor | Homepage | Docs / console |
|---|---|---|---|
| `aihubmix` | AiHubMix (international, USD) | [aihubmix.com](https://aihubmix.com) | [Docs](https://docs.aihubmix.com) · [Console](https://console.aihubmix.com) |
| `dmxapi` | DMXAPI (domestic, CNY) | [www.dmxapi.cn](https://www.dmxapi.cn) | [Docs](https://doc.dmxapi.cn) |
| `metaso` | Metaso | [metaso.cn](https://metaso.cn) | [MiniMax H3 pricing](https://metaso.cn/minimax-h3) |
| `fal` | fal.ai | [fal.ai](https://fal.ai) | [Docs](https://fal.ai/docs) |

Known models in the catalogue:

- **AiHubMix**: MiniMax H3, Wan 2.7 video edit, Doubao Seedance 2.5, GPT Image 2
- **DMXAPI**: MiniMax H3, MiniMax H3 video regeneration, Doubao Seedance 2.5, Wan 3.0, Doubao Seedream 5.0 Pro, GLM-5.3-Flash, Qwen3.8-Flash
- **Metaso**: MiniMax H3 (official Video V2)
- **fal.ai**: MiniMax H3 Max

A custom endpoint can still take any typed `base_url` / model id; the table above only covers catalogue presets.

### Upstream vendors

| Vendor | Homepage |
|---|---|
| MiniMax | [minimax.io](https://www.minimax.io) · [China platform](https://platform.minimaxi.com) |
| OpenAI | [openai.com](https://openai.com) |
| Volcengine / Doubao | [volcengine.com](https://www.volcengine.com) · [Ark](https://ark.volcengine.com) |
| BytePlus | [byteplus.com](https://www.byteplus.com) |
| Alibaba Cloud / Tongyi | [aliyun.com](https://www.aliyun.com) |
| Zhipu | [zhipuai.cn](https://www.zhipuai.cn) · [Open platform](https://open.bigmodel.cn) |

## Getting started

```bash
make setup     # create the conda env, install frontend/backend dependencies
make up        # start the postgres / redis containers
make migrate   # run database migrations
make seed      # load seed data
make dev       # run the API, worker, and web app together
```

Open http://localhost:3000 for the consumer app and http://localhost:3000/en/admin for the admin console. Seed accounts are listed in `docs/local-development.md`.

See `make help` for the full command list.

## Repository layout

```text
front/        Next.js frontend, with (site) consumer and (admin) console shells
back/         FastAPI backend: domain services, agents, provider adapters, Celery workers
infra/        docker-compose and local infrastructure
assets-pack/  media asset drop-in directory
docs/         documentation site source and ops runbooks
.cursor/      module-scoped Agent Skills
```

## Documentation

- [Local development guide](docs/local-development.md)
- [Architecture](docs/architecture.md)
- [Ops runbook](docs/ops-runbook.md)

## Contributing

Commit messages should follow [Conventional Commits](https://www.conventionalcommits.org/). Bump `version` in `front/package.json` and `APP_VERSION` by hand when releasing. Run `make check` before submitting.

## License

Apache License 2.0, see [LICENSE](LICENSE). Third-party components (such as OpenCut) retain their original open-source notices.
