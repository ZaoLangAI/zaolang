---
name: zaolang-testing-qa
description: 造浪的测试与 QA 体系：pytest 四层（单元 / hypothesis 属性 / 集成 / 真并发竞态）、fixture 与 committed_db、Playwright 三个 project（e2e / a11y / visual-qa）、会话复用与限流、双主题三视口与 reduced-motion 检查。Use when writing or fixing tests, adding a property or concurrency test, debugging a flaky or hanging test, or running the E2E, accessibility and visual QA suites.
disable-model-invocation: true
---

# 测试与 QA

## 后端四层

| 目录 | 跑什么 | 何时加用例 |
| --- | --- | --- |
| `back/tests/unit/` | 领域不变量、纯函数 | 任何 `app/domain/*` 改动 |
| `back/tests/unit/test_credits_properties.py` | hypothesis 生成账本操作序列与状态机走法 | 改账本或状态机 |
| `back/tests/integration/` | `TestClient` 走 `/v1`、后台越权与审计 | 任何接口改动 |
| `back/tests/concurrency/` | 真线程 + 独立连接的竞态 | 改并发敏感路径（账本、幂等、回调） |

关键 fixture 在 `back/tests/conftest.py`：`db`（回滚式，多数用例用它）、`committed_db`（真提交 + 事后 `truncate_all`）、`client`、`author` / `admin` / `reviewer` / `operator`、`make_user`；`viewer` 只在 `tests/integration/test_admin_security.py` 里局部定义。数据构造器在 `back/tests/factories.py`（`make_job` 等）。

## 不可破坏的测试约定

1. **`LLM_MODE=stub` 是测试的前提**（`make test-back` 已强制）。任何用例依赖真实网关就不再确定性；`@pytest.mark.live` 的用例必须被 `-m "not live"` 排除。
2. **属性测试与触发 `IntegrityError` 的用例必须用 `committed_db`**：`credits._apply` 在 `IntegrityError` 时会 `session.rollback()`，把整个工作单元（包括 fixture 建的用户）一起丢掉。用回滚式 `db` 会得到「外键指向不存在的用户」这种假失败。
3. **hypothesis 需要 `suppress_health_check=[HealthCheck.function_scoped_fixture]`**：每个例子重建 schema 会慢到不可用，因此每个例子自己隔离——用 SAVEPOINT，或用带 nonce 的唯一键。
4. **生成的字符串要排除控制字符与代理对**：Postgres text 列不接受 NUL，HTTP 头也带不了。
5. **并发用例不能用回滚式 session**：两个事务互相竞争在单事务里根本看不见。规则有两条，缺一会把失败变成挂死——
   - 每个 worker **一定结束自己的事务**（`tests/concurrency/conftest.py` 的 `race()` 在任何异常上先 rollback 再抛），否则输家坐在行锁上，赢家永远等下去；
   - 每个 session 设 `lock_timeout`（默认 5s），意外死锁表现为失败用例而不是卡住整个套件。
   `run_in_parallel()` 用 barrier 对齐 worker、daemon 线程 + 有界 join，**返回异常而不是抛出**——竞态里「输」是正确行为，判定交给用例。
6. **竞态断言的形状是「恰好一个赢家」**，并且要检查输家是因为并发原因失败（`Conflict` / `InsufficientCredits` / `SQLAlchemyError`），而不是碰巧因为别的错误。

## 前端三个 project

`front/playwright.config.ts`：`setup`（登录并存会话）→ `e2e`（`e2e/flows/*.spec.ts`）、`a11y`（`e2e/a11y.spec.ts`）、`visual-qa`（`e2e/visual.spec.ts`）。全部 `workers: 1`：三套共享同一个种子库，并行发布作品会互相污染断言。

支持文件：`e2e/support/session.ts`（`ACCOUNTS` / `STATE_FILES` / `signIn` / `watchForPageErrors`）、`support/axe.ts`、`support/theme.ts`、`setup/auth.setup.ts`。

1. **会话复用不是为了快**：`/v1/auth/login` 限流 10 次 / 5 分钟 / 每地址，这是正确的产品行为。每个用例都真登录会把这条保护变成 flaky 失败。因此 `setup` 只登录四次并存 `e2e/.auth/*.json`（已 gitignore），其余用例 `test.use({ storageState })`；**专门测登录的用例仍然真登录**。
2. **匿名用例要显式清空**：`test.use({ storageState: { cookies: [], origins: [] } })`，否则会继承上一个 project 的会话。
3. **`baseURL` 用 `localhost` 不用 `127.0.0.1`**：后台会话 cookie 是 `SameSite=Strict`，浏览器视这两个主机名为不同站点。后端 `CORS_ORIGINS` 要同时包含 3000 与 3100。
4. **`watchForPageErrors` 只放过已知的期望失败**（会话探测的 401），其余 4xx/5xx 与任何 JS 异常都算失败。不要为了让用例变绿而扩大白名单——那正是它要抓的东西。
5. **视觉套件断言的是机械事实**：三视口无横向溢出（`scrollWidth === clientWidth`）、无控制台错误、reduced-motion 下没有超过 50ms 的动画。截图只附在报告里便于人工查看，不参与通过/失败判定。
6. **无障碍套件对两套主题都扫**，含 `color-contrast`。命令面板是 combobox 而非 dialog，改标记会撞 ARIA 规则。

## 跑 E2E 的前置条件

```bash
make up && make migrate && make seed          # 真实数据库与种子数据
make dev-api                                   # 后端必须在 8000
cd front && npm run build && npx next start --port 3100
make test-e2e && make test-a11y && make qa-visual
```

`front/.env.local` 需要 `ALLOW_LOCAL_IMAGE_HOSTS=1`：Next 16 默认拒绝优化解析到私有地址的图片（SSRF 防护），本地 MinIO 正好是私有地址，不开这一项封面全是 400。生产不要设置。

## 验证

```bash
make test-back      # 480+ 用例，覆盖率写进终端
make check          # 全量本地门禁
```

用例写完问一句：**它能失败吗？** 把被测不变量临时改坏，确认用例真的红了，再改回来。
