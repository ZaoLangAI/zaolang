SHELL := /bin/bash
COMPOSE := docker compose --env-file infra/.env.example -f infra/docker-compose.yml
CONDA_RUN := conda run -n zaolang --no-capture-output
FNM_ENV := eval "$$(fnm env --use-on-cd)" && fnm use --install-if-missing

.DEFAULT_GOAL := help

.PHONY: help
help: ## 列出所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- setup ---------------------------------------------------------------

.PHONY: setup
setup: setup-back setup-front ## 安装前后端依赖

.PHONY: setup-back
setup-back: ## 创建/更新 conda 环境并安装 Python 依赖
	@conda env list | grep -q '^zaolang ' || conda env create -f back/environment.yml
	$(CONDA_RUN) pip install -r back/requirements.txt -r back/requirements-dev.txt
	@test -f back/.env || cp back/.env.example back/.env

.PHONY: setup-front
setup-front: ## 安装前端依赖（fnm 管理 Node 版本）
	cd front && $(FNM_ENV) && npm install
	@test -f front/.env.local || cp front/.env.example front/.env.local

# --- infrastructure ------------------------------------------------------

.PHONY: up
up: ## 启动 postgres / redis / minio 容器
	$(COMPOSE) up -d --wait postgres redis minio
	$(COMPOSE) up minio-init

.PHONY: down
down: ## 停止容器
	$(COMPOSE) down

.PHONY: reset
reset: ## 销毁容器与数据卷后重建
	$(COMPOSE) down -v
	$(MAKE) up migrate seed

.PHONY: logs
logs: ## 跟踪容器日志
	$(COMPOSE) logs -f

# --- database ------------------------------------------------------------

.PHONY: migrate
migrate: ## 升级数据库到最新迁移
	cd back && $(CONDA_RUN) alembic upgrade head

.PHONY: migration
migration: ## 生成迁移，用法 make migration m="add table"
	cd back && $(CONDA_RUN) alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## 导入种子数据（会先清空业务表）
	cd back && $(CONDA_RUN) python -m app.scripts.seed

.PHONY: import-assets
import-assets: ## 导入 assets-pack/manifest.json 描述的真实素材
	cd back && $(CONDA_RUN) python -m app.scripts.import_assets_pack --manifest ../assets-pack/manifest.json

.PHONY: check-assets
check-assets: ## 只校验素材清单，不写库
	cd back && $(CONDA_RUN) python -m app.scripts.import_assets_pack --manifest ../assets-pack/manifest.json --dry-run

.PHONY: backup
backup: ## pg_dump 到 .backups/ 并按需上传 MinIO
	./infra/scripts/backup.sh

.PHONY: restore
restore: ## 从备份恢复，用法 make restore f=.backups/xxx.dump
	./infra/scripts/restore.sh "$(f)" --confirm

# --- development ---------------------------------------------------------

.PHONY: dev
dev: ## 同时启动 API、Worker 与 Web
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) dev-api & \
	$(MAKE) dev-worker & \
	$(MAKE) dev-web & \
	wait

.PHONY: dev-api
dev-api: ## 启动 FastAPI（含 AgentOS）
	cd back && $(CONDA_RUN) uvicorn app.main:app --reload --port 8000

.PHONY: dev-worker
dev-worker: ## 启动 Celery worker（订阅全部队列）
	cd back && $(CONDA_RUN) celery -A app.workers.celery_app worker \
		-Q moderation_short,image_generation,video_generation_long,quality_check,webhook_reconcile \
		--loglevel=info

.PHONY: dev-web
dev-web: ## 启动 Next.js
	cd front && $(FNM_ENV) && npm run dev

# --- quality gates -------------------------------------------------------

.PHONY: check
check: lint typecheck messages openapi-check test ## 提交前的完整本地门禁

.PHONY: hooks
hooks: ## 安装 pre-commit 钩子
	$(CONDA_RUN) pre-commit install
	$(CONDA_RUN) pre-commit run --all-files || true

.PHONY: messages
messages: ## 校验三语文案键一致且代码引用的键都存在
	cd front && $(FNM_ENV) && npm run check:messages

.PHONY: lint
lint: ## 静态检查
	cd back && $(CONDA_RUN) ruff check . && $(CONDA_RUN) ruff format --check .
	cd front && $(FNM_ENV) && npm run lint

.PHONY: format
format: ## 自动格式化
	cd back && $(CONDA_RUN) ruff check --fix . && $(CONDA_RUN) ruff format .
	cd front && $(FNM_ENV) && npm run format

.PHONY: typecheck
typecheck: ## 类型检查
	cd back && $(CONDA_RUN) mypy app
	cd front && $(FNM_ENV) && npm run typecheck

.PHONY: test
test: test-back test-front ## 全部测试

.PHONY: test-back
test-back: ## 后端测试（强制 stub 模式保证确定性）
	cd back && LLM_MODE=stub $(CONDA_RUN) pytest -m "not live" --cov=app --cov-report=term-missing

.PHONY: test-llm
test-llm: ## LLM 网关连通性冒烟（需要真实密钥，不进 CI）
	cd back && $(CONDA_RUN) pytest -m live -v

.PHONY: test-front
test-front: ## 前端构建与类型检查
	cd front && $(FNM_ENV) && npm run typecheck && npm run build

.PHONY: test-e2e
test-e2e: ## Playwright 端到端测试
	cd front && $(FNM_ENV) && npm run test:e2e

.PHONY: test-a11y
test-a11y: ## axe 无障碍扫描（深浅两套主题）
	cd front && $(FNM_ENV) && npm run test:a11y

.PHONY: qa-visual
qa-visual: ## 深浅两套主题 × 三视口截图
	cd front && $(FNM_ENV) && npm run qa:visual

# --- contracts & docs ----------------------------------------------------

.PHONY: openapi
openapi: ## 导出 OpenAPI 并生成前端类型
	cd back && $(CONDA_RUN) python -m app.scripts.export_openapi
	cd front && $(FNM_ENV) && npm run gen:api

.PHONY: openapi-check
openapi-check: openapi ## 校验生成的类型未过期
	@git diff --exit-code -- front/src/lib/api/schema.d.ts back/openapi.json \
		|| (echo "OpenAPI 类型已漂移，请提交 make openapi 的结果" && exit 1)

.PHONY: docs
docs: ## 本地预览文档站
	cd back && $(CONDA_RUN) python -m app.scripts.export_openapi
	cp back/openapi.json docs/openapi.json
	$(CONDA_RUN) mkdocs serve

.PHONY: docs-build
docs-build: ## 构建文档站（strict，链接错误即失败）
	cd back && $(CONDA_RUN) python -m app.scripts.export_openapi
	cp back/openapi.json docs/openapi.json
	$(CONDA_RUN) mkdocs build --strict
