# 本地开发

## 前置条件

| 工具 | 用途 | 说明 |
| --- | --- | --- |
| [OrbStack](https://orbstack.dev/) 或 Docker Desktop | 跑 PostgreSQL / Redis / MinIO | 首次使用先 `orb start` |
| [fnm](https://github.com/Schniz/fnm) | 管理 Node 版本 | 版本号读 `front/.node-version` |
| conda | 管理 Python 3.12 环境 | 环境名 `zaolang`，定义在 `back/environment.yml` |
| `pg_dump` / `pg_restore` | 备份与恢复 | 后台「触发备份」直接调用 `pg_dump` |

## 一次性初始化

```bash
make setup     # 创建 conda 环境、装前后端依赖、复制 .env
make up        # 启动 postgres / redis / minio，并创建 MinIO 桶
make migrate   # 迁移到最新版本
make seed      # 导入种子数据
make hooks     # 安装 pre-commit 钩子
```

`make setup` 会把 `back/.env.example` 复制成 `back/.env`、`front/.env.example` 复制成 `front/.env.local`。两个文件都在 `.gitignore` 里，密钥只放这里。

## 日常开发

```bash
make dev       # 同时起 API(8000)、Celery worker、Celery beat、Web(3000)
make dev-api   # 只起 FastAPI
make dev-worker # 只起 Celery worker（订阅七个队列）
make dev-beat  # 只起 Celery Beat（异步轮询与超时回收）
make dev-web   # 只起 Next.js
make dev-purge-queues  # 清空 Celery 队列（先停 worker）
```

`make seed ARGS=--reset`（或任何会 `TRUNCATE generation_jobs` 的操作）只会清 PostgreSQL，
**不会**清 Redis 里已入队的 Celery 消息。旧 `job_id` 仍会被 worker 取到并报
`job ... not found`，还会短暂占住并发槽。清库后请先停 worker，再执行
`make dev-purge-queues`（或 `redis-cli -p 6380 -n 0 FLUSHDB`），然后重启 worker。

- C 端：<http://localhost:3000/zh-CN/discover>
- 后台运维台：<http://localhost:3000/zh-CN/admin>
- API 文档：<http://localhost:8000/docs>
- MinIO 控制台：<http://localhost:9001>

本地开发的页面入口和媒体签名一律走 `localhost`，不要用机器网卡 IP 打开前端或写入 `S3_PUBLIC_ENDPOINT_URL` / `LOCAL_MEDIA_HOST`。网卡 IP 会随 DHCP / 换网变化：SigV4 签的是 `Host` 头，Next `/_next/image` 的 allowlist 也只认 `localhost:9000` 与 `127.0.0.1:9000`，写成 `192.168.*` 后封面和沙盒预览会 403 或约 5s 后 500。

### 受信任局域网访问

`make dev` 默认让 Web 与 API 只监听 `localhost`。这是本机开发的正确形态。

跨设备用局域网 IP 打开页面**不能**靠把 `S3_PUBLIC_ENDPOINT_URL` 或 `LOCAL_MEDIA_HOST` 改成当前网卡 IP 来凑：地址一变就要改配置、重启服务，签名与图片优化器会一起挂。媒体签名在本地必须保持 `http://localhost:9000`；`LOCAL_MEDIA_HOST` 保持空。需要给其他设备看时，用稳定的主机名或反向代理，而不是会变的 DHCP 地址。

不要把开发默认密钥、MinIO 凭据或 HTTP 服务直接暴露到公网；公网部署必须更换密钥并使用 HTTPS/反向代理。

!!! note "端口刻意错开"
    Postgres 用 `5433`、Redis 用 `6380`，避免和你机器上已有的本地服务抢端口。改端口时同时改 `infra/.env.example` 与 `back/.env`。

## 种子账号

`make seed` 后所有账号共用密码 `Zaolang2026`：

| 邮箱 | 角色 | 用来验证什么 |
| --- | --- | --- |
| `linhai@zaolang.dev` | 作者 | 原作者视角、许可开关、回流分成入账 |
| `mizuki@zaolang.dev` | 二创者（JP / ja） | 二创链第二层、地区与语言差异 |
| `ava@zaolang.dev` | 二创者（GLOBAL / en） | 第三层创作链、货币与日期格式 |
| `reviewer@zaolang.dev` | reviewer | 审核队列、举报处理、隐藏作品 |
| `operator@zaolang.dev` | operator | 任务重放与终止、封禁、调账、备份 |
| `admin@zaolang.dev` | admin | 配置中心、Feature Flag、角色授予、种子重置 |
| `driftwood@zaolang.dev` | 已封禁用户 | 解封流程；登录会被拒绝 |

种子数据还会刻意留下几处「不健康」现场，否则运维台每个页面都是空的：一个卡在 `running`
且预扣已超时的任务（同时出现在卡死任务与悬挂预扣两个视图）、一个失败并已正确退款的任务、
一条待审批的数据导出请求，以及一次因 JSON 解析失败而降级的 Copy Agent 调用。

后台会话与 C 端会话完全独立：`/admin/login` 签发 audience 为 `admin` 的 token 并存在 `zl_admin_session` cookie 里，拿 C 端 token 打 `/v1/admin/*` 一律 401。

## LLM 网关

生产代码只有一种调用行为：始终调用 `/admin/models` 配置好的真实网关；模型未绑定、没有可用端点，或网关调用失败，一律立即抛 `ProviderTemporaryFailure`（503），绝不会静默降级成假数据。任务级别的容错交给 Celery 重试，而不是单次 agent 调用内部换成假数据。

测试的确定性不再靠环境变量切换生产代码路径，而是由 `back/tests/conftest.py` 里的 autouse fixture 用 `back/tests/fake_llm_gateway.py` 把 `llm_client.complete`/`stream_complete` 换成确定性假实现，对每条测试自动生效（`make test-back` 不需要任何 `LLM_MODE` 前缀）。只有标了 `@pytest.mark.live`（真连通性冒烟）或 `@pytest.mark.real_gateway_seams`（要测网关自身故障转移/熔断/报错逻辑）的用例才会绕过假网关，走真实的 `app.llm.client`。

本地想跑真实模型，把 AIHubMix 的 key 放进 `back/.env` 的 `LLM_API_KEY`，然后：

```bash
make test-llm  # @pytest.mark.live 连通性冒烟，验证三个模型可用
```

没有密钥时这条命令会跳过全部用例，`make test-back` 完全不受影响。

## 质量门禁

```bash
make check          # lint + typecheck + 文案校验 + OpenAPI 漂移 + 全部测试
make lint           # ruff / eslint
make typecheck      # mypy / tsc
make messages       # 三语文案键一致，且代码引用的键都存在
make openapi-check  # 重新导出 OpenAPI 并检查生成的前端类型有没有漂移
make test-back      # pytest（假网关 fixture 保证确定性，见 tests/fake_llm_gateway.py）
make test-front     # tsc + next build
make test-e2e       # Playwright 主流程（需要先起服务与种子数据）
make test-a11y      # axe 扫描，深浅两套主题
make qa-visual      # 双主题 × 三视口截图
```

E2E 与无障碍是额外的本地套件：它们需要真实数据库与种子数据，不进 `make check`。代价是「本地没跑就合并」的风险，因此提交前应跑 `make check`，pre-commit 钩子会拦住大部分静态问题。

### 后端测试分层

`make test-back` 一次跑完四层，其中后两层需要真实 Postgres：

| 目录 | 跑的是什么 |
| --- | --- |
| `tests/unit/` | 领域不变量与纯函数，例子由人挑 |
| `tests/unit/test_credits_properties.py` | hypothesis 随机生成账本操作序列与状态机走法，断言的是不变量本身 |
| `tests/integration/` | 走 `TestClient` 的 `/v1` 契约、后台越权与高危操作审计 |
| `tests/concurrency/` | 真线程 + 独立连接的竞态：积分双花、capture/release 双结算、幂等键竞争、回调乱序 |

并发用例不能用回滚式的 `db` fixture——两个事务互相竞争在单事务里根本看不见，所以它们真提交，跑完 `TRUNCATE`。每个 session 都带 `lock_timeout`，失败的一方一定回滚，因此死锁会变成失败用例而不是挂住整个套件。

### 跑 E2E 需要什么

```bash
make up && make migrate && make seed   # 真实数据库与种子数据
make dev-api                            # 后端必须在 8000，CORS 允许 3000/3100
cd front && npm run build && npx next start --port 3100
make test-e2e
```

Playwright 的 `baseURL` 用 `localhost:3100` 而不是 `127.0.0.1:3100`：后台会话 cookie 是 `SameSite=Strict`，浏览器把这两个主机名当成不同站点，用 IP 会静默丢掉后端设的 cookie，所有需要登录的用例都会失败。`e2e/setup/auth.setup.ts` 只登录四次并存下会话，其余用例复用——既省时间，也避免把登录接口每五分钟十次的限流当成 flaky 失败。

`front/.env.local` 里的 `ALLOW_LOCAL_IMAGE_HOSTS=1` 是本地专用：Next 16 默认拒绝优化解析到私有地址的图片（防 SSRF），而本地 MinIO 正好是私有地址，不开这一项种子作品的封面全是 400。生产部署不要设置它。

## 常见问题

**改了后端 schema，前端类型对不上。** 跑 `make openapi`，把 `back/openapi.json` 与 `front/src/lib/api/schema.d.ts` 一起提交。`make openapi-check` 就是防止只改一半。

**测试报「current transaction is aborted」。** 通常是探针类查询在测试 schema 里失败污染了事务。领域代码里所有可能失败的探测都要包在 `session.begin_nested()` 里。

**登录测试忽然返回 429。** 限流计数器在 Redis 里，事务回滚不会撤销它。`tests/conftest.py` 的 `_clear_redis_state` fixture 负责清理，新增限流桶时要一并加进去。

**封面或沙盒预览 `/_next/image` 报 500。** 媒体 URL 被签成了机器网卡 IP（`http://192.168.*:9000/...`）而不是 `http://localhost:9000`。把 `S3_PUBLIC_ENDPOINT_URL` 拉回 `http://localhost:9000`，`LOCAL_MEDIA_HOST` 留空，用 <http://localhost:3000> 打开页面，然后重启 API 与 Next（`get_public_client()` 有缓存）。不要把查询串剥掉再打开对象路径：桶是私有的，无签名会 403。

**素材是占位图。** 真实媒体没到位前，链路里跑的是标记为 `PROTOTYPE` 的极少量临时媒体。素材包到位后：

```bash
make check-assets   # 只校验 assets-pack/manifest.json
make import-assets  # 导入并替换占位素材
```
