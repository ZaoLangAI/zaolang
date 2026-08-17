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

.PHONY: release-up
release-up: ## 本地构建镜像并启动一键体验编排
	docker compose -f infra/docker-compose.release.yml up -d --build

# --- remote production deployment ----------------------------------------
# Needs infra/.env.prod on the target host (see infra/.env.prod.example);
# that file carries real secrets and is never committed.

.PHONY: prod-up
prod-up: ## 构建镜像并启动生产编排（需要 infra/.env.prod）
	docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --build

.PHONY: prod-down
prod-down: ## 停止生产编排
	docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod down

.PHONY: prod-logs
prod-logs: ## 跟踪生产编排日志
	docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod logs -f

# --- database ------------------------------------------------------------

.PHONY: migrate
migrate: ## 升级数据库到最新迁移
	cd back && $(CONDA_RUN) alembic upgrade head

.PHONY: migration
migration: ## 生成迁移，用法 make migration m="add table"
	cd back && $(CONDA_RUN) alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## 导入种子数据（可选 make seed ARGS=--reset）
	cd back && $(CONDA_RUN) python -m app.scripts.seed $(ARGS)

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
dev: ## 同时启动 API、Worker、轮询 poller、Beat 与 Web
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) dev-api & \
	$(MAKE) dev-worker & \
	$(MAKE) dev-poller & \
	$(MAKE) dev-beat & \
	$(MAKE) dev-web & \
	wait

.PHONY: dev-api
dev-api: ## 启动 FastAPI（含 AgentOS）
	cd back && $(CONDA_RUN) uvicorn app.main:app --reload --host localhost --port 8000

.PHONY: dev-worker
dev-worker: ## 启动 Celery worker（生成与质检队列，不含供应商轮询）
	cd back && $(CONDA_RUN) celery -A app.workers.celery_app worker \
		-Q image_generation,video_generation_long,audio_generation,quality_check,webhook_reconcile,media_analysis \
		--loglevel=info

.PHONY: dev-poller
dev-poller: ## 启动供应商异步轮询 worker（独占 provider_task_polling）
	cd back && $(CONDA_RUN) celery -A app.workers.celery_app worker \
		-Q provider_task_polling --concurrency=1 \
		--loglevel=info

.PHONY: dev-purge-queues
dev-purge-queues: ## 清空 Celery 队列（seed --reset / 清库后使用，先停 worker）
	cd back && $(CONDA_RUN) celery -A app.workers.celery_app purge -f

.PHONY: dev-beat
dev-beat: ## 启动 Celery Beat（异步供应商轮询与超时回收）
	cd back && $(CONDA_RUN) celery -A app.workers.celery_app beat --loglevel=info

.PHONY: dev-web
dev-web: ## 启动 Next.js
	cd front && $(FNM_ENV) && npm run dev -- --hostname localhost

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
test-back: ## 后端测试（假网关 fixture 保证确定性，见 tests/fake_llm_gateway.py）
	cd back && $(CONDA_RUN) pytest -m "not live" --cov=app --cov-report=term-missing

.PHONY: test-llm
test-llm: ## LLM 网关连通性冒烟（需要真实密钥，不进 make check）
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
openapi-check: ## 校验生成的类型未过期
# 比对「重新生成前 / 后」而不是比对 HEAD：工作区里本来就会有未提交的 API 改动，
# 跟 HEAD 比会把「还没提交」误报成「没重新生成」。
	@cp back/openapi.json .openapi-check.json
	@cp front/src/lib/api/schema.d.ts .openapi-check.d.ts
	@$(MAKE) --no-print-directory openapi >/dev/null
	@diff -q .openapi-check.json back/openapi.json >/dev/null \
		&& diff -q .openapi-check.d.ts front/src/lib/api/schema.d.ts >/dev/null \
		|| (rm -f .openapi-check.json .openapi-check.d.ts; \
			echo "OpenAPI 类型已漂移，请提交 make openapi 的结果" && exit 1)
	@rm -f .openapi-check.json .openapi-check.d.ts

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
