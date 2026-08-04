# iOS 客户端路线图与后端契约缺口

规划期文档已删除，本文件是里程碑定义、验收标准与后端契约缺口的存档。M0–M5 均已实现，本文件保留作为
"当时为什么这么定"的存档；M6 之后再开工前先读这份，尤其是下面的三个已拍板决策和验收清单。

## 开工前必须拍板的三件事（改变工程结构，不能边做边定）——三条均已拍板并实现

| 决策 | 选项 | 已落地的选择 |
| --- | --- | --- |
| 会话续期方式 | A 客户端接管 `zl_refresh` Cookie / B 后端补原生刷新通道 | **A**（`CookieCodec` + Keychain） |
| 积分购买 | A 接 StoreKit 2 / B 不提供购买入口，引导去网页版 | **B**——`BillingView` 只读展示余额与账本，余额不足或想购买时用 `UIApplication.shared.open` 跳网页版 `/billing`，不接 `POST /v1/credits/checkout` |
| APNs 推送 | 首版做 / 延后用回前台轮询兜底 | **首版做**——后端新增 `Device` 模型 + `POST/DELETE /v1/me/devices`，客户端 `PushManager` 接完整注册/点击跳转链路，`back/app/domain/notifications/push.py` 的真实 APNs 发送仍是日志占位（没有真实 APNs 证书） |

## 里程碑

- **M0 地基**（已完成）：网络层、`Page<T>` 解析、设计令牌、媒体缓存键策略、三语文案接入。
- **M1 只读闭环**（已完成）：发现（Hero/瀑布墙/无限滚动/标签/排序/搜索）、灵感预览、作品详情、创作链图谱、个人主页、学习，全部游客可用，不含任何写操作。
- **M2 账号与会话**（已完成）：`AuthSheet` 登录注册、`AppEnvironment.requireAuth` 的"动作恢复"三条语义（已登录直接执行 / 未登录暂存并恢复 / 取消则丢弃且绝不静默执行）、点赞收藏关注（乐观更新）、我的库（作品/草稿/收藏/合集四段）、账号区（`SettingsView`）、通知列表、数据导出注销申请。
- **M3 创作闭环**（已完成）：创作中心（`CreateView`）、工作台（`StudioView`/`StudioViewModel`，新建/二创共用同一形态，靠 `StudioMode` 区分）、素材上传（`UploadTransport` 直传预签名 URL）、报价（400ms 去抖）、提交（草稿 + 生成任务共用一个幂等键）、任务详情（SSE + 5 秒轮询兜底，`JobDetailViewModel`）、发布（`PublishView`，两个确认框默认不勾、默认可见性 `public_view_only`）、创作 Tab 顶部浮条（`CreateJobBanner`）。
- **M4 入门路径**（已完成）：三页新手引导（`OnboardingView`，`iosOnboarding` i18n 命名空间，`UserDefaults` 记录已读位，跟登录态无关）。新手改写建议 chip / 等待期同源作品推荐 / 埋点等更细的体验优化未做，不阻塞可用性，视为待优化项而非缺口。
- **M5 上架准备**（已完成）：`PrivacyInfo.xcprivacy`（隐私清单）、`aps-environment` entitlement（当前 `development`，上架前换 `production`）、`UIBackgroundModes: remote-notification`。App Store 素材（截图/描述文案）、年龄分级问卷、崩溃与性能监控（如 Crashlytics）仍需要在 App Store Connect 后台手工完成，不是代码改动范围。
- **M6 之后（不排期，仍未做）**：更进一步的推送场景（静默推送）、StoreKit 内购（若未来产品决策反悔）、合集内的更多管理操作、风格预设、iPad 与横屏、离线浏览增强、分享扩展。

## 后端契约缺口（五处，两处仍未解决，一处已用变通方案绕开，两处已补后端接口解决）

1. **刷新令牌只走 httpOnly Cookie**（仍未解决，风险仍在）：`POST /v1/auth/refresh` 只从 `Set-Cookie: zl_refresh` 读，没有 body/header 备用通道。已按方案 A 实现（客户端接管），风险是后端改 Cookie 属性会静默打断续期——Cookie 名与属性写成常量并配一条集成测试，见 `zaolang-ios-client` SKILL.md 不变量 4。
2. **APNs 设备注册端点**（已解决）：后端新增 `back/app/models/platform.py` 的 `Device` 模型 + `back/app/api/v1/devices.py` 的 `POST/DELETE /v1/me/devices`；`back/app/domain/notifications/push.py` 的 `notify()` 在任务终态/二创/分成到账时写通知行，`_dispatch_push` 目前只打日志（没有真实 APNs 证书）。
3. **部分列表未落地游标**（仍未解决）：只有 `GET /v1/works`、`GET /v1/credits/ledger` 支持 `cursor`；`GET /v1/generation-jobs`（`limit` 上限 50）、`GET /v1/notifications`、`GET /v1/drafts`（上限 50）、`GET /v1/me/bookmarks`、`GET /v1/profiles/{handle}/works` 只能一次取满。客户端统一按 `Page<T>` 写解析层，`nextCursor` 为 `nil` 时不显示"加载更多"，后端补游标后零改动。
4. **支付合规**（已用变通方案绕开）：`POST /v1/credits/checkout` 走浏览器结账，App Store 对 App 内数字消费要求 IAP。产品决策选方案 B——`BillingView` 不调用这个端点，只读展示余额/账本/积分包，购买入口是 `UIApplication.shared.open` 跳网页版 `/billing`，规避了"把 `checkout_url` 塞 `SFSafariViewController`"这条高风险路径。
5. **SSE 需要客户端自实现**（已解决，简化版）：`ZaolangKit/Streaming/`（`EventStreamClient`/`SSEReconnectPolicy`/`SSEFrameParser`）在 M0 就已经有帧解析 + 1s→2s→5s→10s→30s 退避重连，`JobEventStream.swift` 在这之上加了 `jobEvents(jobID:)` 的任务专用解码。`JobDetailViewModel` 接入时**没有**实现"连续三次重连失败降级为轮询"的计数器状态机，而是让 SSE 与一个独立的 5 秒轮询循环一直并行跑（SSE 到就提前更新 `status`/`progress`，轮询兜底保证最多 5 秒内和服务端状态对齐，终态时都会补一次完整 `GET`）。这个简化在正确性上等价、实现更简单，但如果未来要精确复刻"实时连接不可用，正在定时刷新"的界面文案，需要重新设计这部分状态机。

## 全局验收清单（每个里程碑合并前都要过一遍）

- **功能正确性**：金额字段全代码搜索无 `Double`/`Float`；ID 不手写，一律用后端返回值；`ref` 与 `source_work_id` 两条路径在代码与 UI 上可区分；私有作品 404 一律呈现"不存在或已撤回"不出现"无权限"；提交生成/重试/结账三处都带客户端持有的 `Idempotency-Key`；取消按钮只在可取消状态出现、重试只在终态出现；发布页默认 `public_view_only` 且确认框不预勾。
- **体验**：新增屏幕的六态（default/loading/empty/error/offline/未登录）都要实现；骨架屏占真实高度不跳版；空态必须"一句解释 + 一个出口动作"；工作台与发布页的成交按钮固定在底部安全区之上不随滚动消失；有非终态任务时创作 Tab 顶部常驻浮条。
- **无障碍**：标准与 Web 端 `make test-a11y`/`make qa-visual` 一致——浅色主题正文对比度 4.5:1、大字 3:1；最大辅助字号下无截断无横向溢出；VoiceOver 图标按钮都有 `a11y.*` 标签；减少动效开关下无超过 50ms 过渡；触控目标最小 44×44pt。
- **性能**：冷启动到发现页首帧 < 1.5s（含会话恢复）；瀑布墙滚动 60fps 无掉帧；长时间滚动发现页内存不持续增长；详情页进入到视频起播 < 1s。
- **与 Web 一致性**：文案 key 与 `front/src/i18n/messages/` 对齐，新增 key 三语同时加；枚举取值以 `back/app/models/enums.py` 为准；深色色值与 Web 截图并排比对；契约以 `back/openapi.json` 为准，后端跑 `make openapi` 后客户端同步核对。

## D3/D4 工作台形态（已实现，`StudioView`/`StudioViewModel`）

工作台是一个界面两种形态，靠 `StudioMode` 区分，没有拆成两个 View：

| | 新建（`StudioMode.new(operation:initialPrompt:)`） | 二创（`StudioMode.remix(sourceWorkID:)`） |
| --- | --- | --- |
| 入参 | 操作类型 + 可选预填 prompt（灵感预览"用此 prompt 创作"用得到） | 只传 `sourceWorkID`，`StudioViewModel.load()` 自己拉一次 `WorkDetail` |
| 素材 | 只有自己上传的参考图（`needsReferenceImage`，仅图生视频需要） | 同一套上传逻辑，另外把源作品的 `reusableParams.prompt`/`negativePrompt` 预填进表单 |
| 归属提示 | 无 | "我保留原作者署名"确认框（`rightsSection`，未勾选不能提交） |
| 提交体 | `sourceWorkID` 为 `nil` | 草稿携带 `sourceWorkID`，发布时用于继承许可、写入创作链 |

单列布局：来源卡片（二创时）→ 操作类型分段 → 提示词 → 参考图（按需）→ 画幅/时长 → 质量档位 → 归属确认
（二创时），报价与提交按钮用 `.safeAreaInset(edge: .bottom)` 固定在底部安全区之上。

## 进行中任务浮条（已实现，`CreateJobBanner`）

`CreateView` 顶部常驻挂 `CreateJobBanner`：`AppEnvironment.activeJobs`（非终态任务，按创建时间排序取
第一个）驱动显示进度条，点击 push 到 `CreateRoute.jobDetail`；任务进终态后 8 秒内继续显示为结果提示，
用户可以点右上角关闭或等 8 秒自动消失（`TimelineView(.periodic(from:by:))` 周期性重新求值，不需要额外
计时器状态）。任务追踪状态在 `AppEnvironment.trackJob(id:)`/`trackedJobs` 里，提交/重试成功后调用一次，
5 秒轮询直到终态——独立于任务详情页自己的 SSE 订阅，两者互不依赖，切出任务详情页之后浮条仍在动。
