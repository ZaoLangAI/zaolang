---
name: zaolang-ios-client
description: 造浪的原生 iOS 客户端：SwiftUI + Swift Concurrency、XcodeGen 工程、Foundation-only 的 ZaolangKit（网络/会话/DTO/媒体缓存/SSE）、四 Tab 外壳与深链接、设计令牌与三语文案的生成式同步、完整的登录注册与写操作闭环（发现/作品详情/创作链图谱/个人主页/学习/创作工作台/任务详情/发布/我的库/账号设置/通知/积分账单/推送/新手引导）。Use when working under ios/, when the user mentions the iOS app, SwiftUI screens, ZaolangKit, XcodeGen, project.yml, or asks to add/change an iOS screen, endpoint call, color token, or localized string on the iOS client.
disable-model-invocation: true
---

# 造浪 iOS 客户端

## 职责

`ios/` 是独立于 `front/`（Next.js）的原生客户端，同一套后端契约（`back/openapi.json`）。M0（地基）到
M5（上架准备）已全部实现：真实登录注册、四 Tab 全部有真实内容（发现/学习为游客可读，创作/我的库需要
登录）、点赞/收藏/关注/二创/发布/举报/合集/通知/设置/数据导出注销全部是真实写操作，APNs 推送已接（含
后端设备注册端点），积分购买按产品决策**不接 StoreKit**、只读展示余额与账本并引导去网页版购买。里程碑
定义、验收标准与后端契约缺口的历史存档见 [roadmap.md](roadmap.md)（M6 之后不排期的范围仍未做）。

**不实现任何 `admin*` 后台运维能力**——后台走独立登录与独立 cookie，C 端令牌打不进去，这是与
`zaolang-admin-console` / `zaolang-admin-ops` 明确切割的边界，不是遗漏。

## 关键路径

| 路径 | 内容 |
| --- | --- |
| `ios/project.yml` | XcodeGen 真源，`.xcodeproj` 不进仓，改完跑 `xcodegen generate` |
| `ios/Packages/ZaolangKit/Sources/ZaolangKit/Models/` | DTO（`WorkSummary`/`WorkDetail`/`LineageGraph`/`PublicProfileResponse`/`GenerationJobResponse`/`DraftResponse`/`NotificationResponse`/`CreditBalanceResponse`…），枚举用 `RawOrUnknown<T>` 包一层，未知值不崩 |
| `.../Networking/` | `APIClient` + 按功能拆的 `APIClient+*.swift`（`Works`/`Community`/`Uploads`/`Jobs`/`Drafts`/`Credits`/`Devices`/`Privacy`/`Profiles`/`Auth`/`Discovery`）、`ApiError`、`IdempotencyKeyStore` |
| `.../Session/` | `SessionManager`/`TokenStore`/`CookieCodec`/`AuthTransport`，手工接管 `zl_refresh` Cookie，登录注册走 `AuthTransport` 单独捕获 `Set-Cookie` |
| `.../Media/AssetCache.swift`、`.../Media/UploadTransport.swift` | 两级资源缓存；素材上传用 `UploadTransport` 直传预签名 URL（不走 `APIClient` 鉴权/幂等） |
| `.../Streaming/JobEventStream.swift` | SSE 帧解析 + `EventStreamClient.jobEvents(jobID:)`，任务详情页接了这个 + 5 秒轮询兜底 |
| `ios/App/Sources/Shell/` | `RootView`/`RootTabView`（四 Tab 自定义底栏，四个独立 `NavigationStack`）、`AppRouter`、`Routes`（各栈 Route enum）、`DeepLink`、`DebugSessionView`（仅 Debug） |
| `ios/App/Sources/DesignSystem/` | `Color.zl.*`、`ZLRadius`、`zlCardShadow`/`zlRaisedShadow`、`zlMotion` 环境值 |
| `ios/App/Sources/Common/` | 六态通用视图、`AuthorRow`/`TagChip`/`StatItem` 共享组件（登录墙已替换为 `AppEnvironment.requireAuth` + `AuthSheet`，见下方"登录与写操作"） |
| `ios/App/Sources/{Discover,WorkDetail,Lineage,Profile,Learn}/` | 五个游客可读功能栈，各自 `*View` + `*ViewModel` |
| `ios/App/Sources/{Create,Library,Auth,Onboarding}/` | 创作工作台/任务详情/发布/草稿详情、我的库/设置/通知/积分账单、登录注册 sheet、三页新手引导 |
| `ios/App/Sources/Support/PushManager.swift`、`ZaolangApp.swift` 里的 `AppDelegate` | APNs 注册、设备 token 上报、通知点击深链跳转 |
| `ios/App/Sources/Support/GenerationOperation.swift` | `Operation` 与 `Foundation.Operation`（`NSOperation`）撞名的别名规避，见下方不变量 13 |
| `ios/tools/gen-colors.py`、`gen-strings.py` | 从 `front/src/app/globals.css`、`front/src/i18n/messages/*.json` 生成 `Assets.xcassets/Colors` 与 `Localizable.xcstrings` |
| `ios/App/Sources/Support/L10n.swift` | `L10n.t("namespace.key", ["var": value])`，`{var}` 手工替换 |
| `ios/App/Resources/PrivacyInfo.xcprivacy`、`Zaolang.entitlements` | 隐私清单（`NSPrivacyCollectedDataTypes` 三项：邮箱、UGC、设备 ID）+ `aps-environment`（当前 `development`，上架前换 `production`） |

## 不可破坏的不变量

1. **生成产物不手改**：`Assets.xcassets/Colors/*.colorset`、`Localizable.xcstrings` 都是脚本产出，源头永远是 `front/src/app/globals.css` 与 `front/src/i18n/messages/*.json`。要改颜色或文案，改源头再重跑对应脚本。
2. **不新造 i18n key**：`gen-strings.py` 的 `NAMESPACES` 列表是当前实际导出的命名空间（`discover`/`work`/`workPage`/`lineagePanel`/`learnPage`/`profilePage`/`states`/`actions`/`a11y`/`nav`/`visibility`/`license`/`theme`/`region`/`brand`/`auth`/`collectionPage`/`createPage`/`remixPage`/`job`/`jobPage`/`publishPage`/`settingsPage`/`billingPage`/`notificationsPage`/`credits`/`iosOnboarding`，`iosOnboarding` 是 iOS 专属、Web 没有对应页面）。iOS 要用的文案必须先存在于 `front` 的三语消息文件里（三语键集合一致，见 `zaolang-i18n-region`），iOS 不能单边发明新词条或只写中文占位；命名空间不在列表里就先加进列表再重跑脚本。
3. **`ApiError` 把 404 与 `WORK_PRIVATE` 合并成同一个 case**：任何界面渲染"不存在"文案都走这一条，禁止出现"无权限"字样泄漏私有作品的存在性——与 Web 端同一条规则。
4. **`zl_refresh` 会话续期走客户端接管 Cookie 方案**：`URLSession` 已关掉默认 Cookie 容器（`httpShouldSetCookies = false`），`CookieCodec` 手工解析 `Set-Cookie` 存 Keychain、手工拼 `Cookie` 头发出。并发 401 由 `SessionManager` 单飞合并成一次刷新。这条如果后端改了 `zl_refresh` 的域名/path/属性会静默打断续期，改动要通知 iOS。
5. **减少动效读 `@Environment(\.zlMotion)`，不要各自读 `accessibilityReduceMotion`**：`zlMotion` 是"系统减少动效 OR 服务端 `reduce_motion` 偏好"的合并结果，由 `RootView` 统一写入。任何新增的 `.animation`/`withAnimation`/自定义 `.transition` 都要拿这个环境值做开关，为真时不跑或用近似 0 时长的过渡。
6. **Swift 合成 init 的可见性陷阱**：View struct 里如果混了**不带属性包裹器**的 `private let`/`private var`（例如布局用的固定常量），编译器合成的逐一成员初始化器会跟着降到 `private`，导致别的文件调不到这个 View 的构造函数。`@State`/`@GestureState` 等属性包裹器标 `private` 不受影响（合成 init 按 wrappedValue 类型生成，不暴露包裹器本身）。新增只在别的文件构造的 View 时，一旦混了非包裹器的私有存储属性就必须手写 `init`。
7. **`ref` 与 `source_work_id` 是两个概念**：灵感引用不建链不继承许可，二创建 lineage 边并触发回流分成。灵感预览的"用此 prompt 创作"（`InspirationPreviewSheet.onCreateFromPrompt`）落到 `StudioMode.new(operation:initialPrompt:)`——只预填提示词，不传 `source`；作品详情的"二创"落到 `StudioMode.remix(sourceWorkID:)`——`StudioViewModel` 据此决定要不要显示"保留原作者署名"条与素材继承。两条路径共用同一个 `StudioView`/`StudioViewModel`，不要拆成两个 View。
8. **分页统一走 `Page<T>` 解析**：后端只有 `GET /v1/works` 与 `/v1/credits/ledger` 真正支持 `cursor`，其余列表端点只有 `limit`（"一次取满"）。即便当前是一次取满，解析层也套 `Page<T>`，后端补游标后客户端零改动，不要为"一次取满"的端点单独写一套非分页解析。
9. **创作链图谱深度默认 3**（`LineageViewModel.depth`），区别于后端默认值 4——手机屏幕挤不下 4 层，这是有意的客户端决策，改动前先确认线框意图没变。
10. **金额是整数**、**枚举取值以 `back/app/models/enums.py` 为准**：与仓库其余部分同一条铁律，`RawOrUnknown<T>` 是应对后端加新枚举值时客户端不崩的降级路径，不是可以忽略的噪音。
11. **本机 XcodeGen 2.46.0 顶层 `resources:` 键不生效**（已用最小工程复现，是这个版本的真实缺陷，不是配置错误）：不会写出 `PBXResourcesBuildPhase`，`Assets.xcassets`/`Localizable.xcstrings` 编译进 App 后色板与三语文案全部读不到。已在 `project.yml` 里绕过——把资源放进 target 的 `sources:` 并显式加 `buildPhase: resources`。新增任何资源文件都要沿用这个写法，不要改回顶层 `resources:` 键。
12. **自定义 `Info.plist` 必须手写 `CFBundleIdentifier`/`CFBundleExecutable`/`CFBundlePackageType`/`CFBundleName`/`CFBundleInfoDictionaryVersion`**：`project.yml` 里 `GENERATE_INFOPLIST_FILE: NO` 时 Xcode 不会自动注入这五个键，缺了装不上模拟器/真机（报 `Invalid parameter ... installURL`）。已经补在 `App/Resources/Info.plist` 里，别删。
13. **`Operation` 与 `Foundation.Operation`（`NSOperation`）撞名**：任何文件只要同时 `import Foundation`（哪怕是间接需要 `Data`/`URL`/`UUID`）又 `import ZaolangKit` 并裸写 `Operation`，编译器会报 "ambiguous for type lookup"。**不能**用 `ZaolangKit.Operation` 消歧——`ZaolangKit` 模块内部还有一个同名命名空间枚举 `public enum ZaolangKit`，会把 `ZaolangKit.Operation` 解析成"那个枚举里找不到的嵌套类型"而报另一个错。唯一干净的办法：在不 `import Foundation` 的文件里用裸 `Operation` 定义别名（已有 `Support/GenerationOperation.swift` 的 `typealias GenerationOperation = Operation`），同时用到 `Foundation` 的文件改引用 `GenerationOperation`。`Routes.swift` 没有 `import Foundation` 依赖，故意保留裸 `Operation`。
14. **登录墙动作恢复走 `AppEnvironment.requireAuth`，不要再用旧的 `LoginWallSheet` 模式（已删除）**：任何写操作入口点击后调 `environment.requireAuth(actionLabel:) { /* 真正的动作 */ }`——已登录直接执行传入的闭包；未登录会弹 `AuthSheet`，登录/注册成功后自动把闭包补跑一次；用户主动取消则闭包被丢弃、绝不静默执行。新增任何"未登录不可用"的按钮都套这一层，不要自己再发明一种登录墙 UI。

## 登录与写操作

- **`AppEnvironment.requireAuth(actionLabel:action:)`** 是唯一的登录墙原语，见不变量 14。`actionLabel` 用于 `AuthSheet` 顶部提示"你正要做什么"，取值应为一个已存在的 i18n key（例如 `L10n.t("work.like")`），不要传硬编码英文/中文字面量。
- **`StudioMode` 是创作工作台唯一入口**：`.new(operation:initialPrompt:)`（创作中心三个模式卡片、灵感预览"用此 prompt 创作"）与 `.remix(sourceWorkID:)`（作品详情"二创"）共用 `CreateRoute.studio`，都必须切到创作 Tab 再 push（`RootTabView.startRemix`/`DiscoverView` 里的写法），不要在其他 Tab 的栈里直接 push 工作台。
- **推送**：`PushManager.shared.requestAuthorizationAndRegister()` 只在用户主动点"开启通知"（`SettingsView` 的通知分区）或首次引导页时调用，冷启动不自动弹系统权限框；拿到 device token 后 `AppEnvironment.registerPushToken` 调 `POST /v1/me/devices`；登出时 `AppEnvironment.signOut()` 会先 `DELETE` 这条设备记录。
- **积分购买**：产品决策是不接 StoreKit，`BillingView` 只读展示余额/账本/积分包，"购买"按钮用 `UIApplication.shared.open` 跳网页版 `/billing`，不要在这条链路上加 `POST /v1/credits/checkout` 调用或 `SFSafariViewController` 内嵌结账。

## 未实现范围（M6 之后，不排期）

APNs 之外更进一步的推送场景（静默推送刷新角标等）、StoreKit 内购（若未来产品决策反悔）、iPad 与横屏、
离线浏览增强、分享扩展、风格预设库。开工前先读 [roadmap.md](roadmap.md) 确认没有新的产品决策覆盖当前
默认项（会话续期方案、积分购买方案、APNs 均已按文档建议的默认项实现并落地）。

## 改造切入点

- **加一个新的读操作端点**：`ZaolangKit/Networking/APIClient+*.swift` 加方法 → 需要新 DTO 就加进 `Models/` → `cd ios/Packages/ZaolangKit && swift build` 自验 → 界面层调用。
- **加一个新的写操作/新屏幕**：新建 `App/Sources/<Feature>/` 目录，参照 `Create/`（`*View` + `*ViewModel`）的分法；写操作入口套 `environment.requireAuth`（见上方"登录与写操作"）；在 `Shell/Routes.swift` 加对应 Tab 的 Route case，在 `RootTabView` 的 `discoverDestination`/`createDestination`/`libraryDestination`/`learnDestination` 之类的 `@ViewBuilder` 函数里接线。
- **加一处文案**：先确认 key 在 `front/src/i18n/messages/{zh-CN,en,ja}.json` 里已存在且三语齐全；如果 iOS 要用的命名空间还没导出，去 `ios/tools/gen-strings.py` 的命名空间列表里加，再重跑脚本；代码里用 `L10n.t("namespace.key")`。
- **加一个颜色令牌**：先确认 `front/src/app/globals.css` 的 `:root` 与 `[data-theme='dark']` 两块都已定义该变量，重跑 `gen-colors.py`，代码里通过 `Color.zl.*`（`Color+ZL.swift`）消费，不要新增裸色值。
- **改导航结构**：四个 Tab 各自持有独立 `NavigationPath`（`AppRouter`），改跨 Tab 跳转逻辑在 `AppRouter.handle`/`selectTab`；改 Universal Links 解析在 `Shell/DeepLink.swift`，解析时忽略 URL 里的 `/{locale}/` 前缀，落点以 App 内当前语言为准。
- **补新屏幕的六态**：`Common/LoadableState.swift` 是 `loading/loaded/empty/failed` 四态，`offline` 与"未登录"是叠加维度——`offline` 走 `environment.reachability.isOffline` 判断（全局横幅已经在 `RootTabView` 接好，单屏一般不用重复画），"未登录"走点击写动作时套 `environment.requireAuth`，不要在数据层建一个"未登录"case。空态必须有一句解释 + 一个出口动作，不能只写"暂无数据"。

## 验证

```bash
cd ios/Packages/ZaolangKit && swift build     # 网络/会话/DTO/媒体缓存层改动的最快自验手段
cd ios && xcodegen generate                    # 改了 target/依赖/资源引用之后
xcodebuild -project ios/Zaolang.xcodeproj -scheme Zaolang \
  -destination 'platform=iOS Simulator,name=iPhone 17' build   # 本机已装完整 Xcode，这条能跑通，是界面层改动的命令行自验手段
```

真机/模拟器跑通关键路径仍建议在 Xcode 里过一遍：`open Zaolang.xcodeproj` → 选 iPhone 模拟器 → Run。
联调需要后端在跑：`make up && make migrate && make seed && make dev-api`（默认 `http://localhost:8000`，
与 `AppConfig.apiBaseURL` 一致）；推送/设备注册联调还需要 `back/app/api/v1/devices.py` 的两个端点已迁移
（`alembic upgrade head`）。

无障碍走查对齐 Web 端标准（与 `zaolang-testing-qa` 的 `make test-a11y`/`make qa-visual` 同一套目标）：
最大辅助字号下不截断不横向溢出、VoiceOver 图标按钮都有标签、减少动效开关下无超过 50ms 过渡、触控目标
最小 44×44pt。
