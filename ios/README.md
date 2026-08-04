# 造浪 iOS 客户端

`ios/` 是一份可以打开跑起来的 XcodeGen 工程，M0 地基 + M1 只读闭环已实现。`project.pbxproj` 不进仓，
工程文件由 `project.yml` 生成——改了 target/依赖/资源引用记得重新 `xcodegen generate`，手改
`.xcodeproj` 会在下一次生成时被覆盖。**改这个客户端前先加载
[`zaolang-ios-client`](../.cursor/skills/zaolang-ios-client/SKILL.md) skill**，规划期的线框图与效果
图已经蒸馏进那份 skill 后删除，不要在仓库里找 `ios/docs/`、`ios/mockups/`。

## 目录结构

```
ios/
  project.yml                  XcodeGen 配置：target、依赖、签名占位、deployment target
  App/
    Sources/                   SwiftUI 源码，按功能分包（见下表）
    Resources/
      Info.plist                含 NSAllowsLocalNetworking（放开 localhost 明文 http）
      Zaolang.entitlements       Universal Links 的 applinks: 占位域名
      Assets.xcassets/Colors/    gen-colors.py 从 globals.css 生成的 18 个 Color Set，不手改
      Localizable.xcstrings      gen-strings.py 从 front i18n 生成的字符串表，不手改
  Packages/ZaolangKit/          只依赖 Foundation 的 SwiftPM 包：网络层、DTO、会话、媒体缓存、SSE
  tools/
    gen-colors.py                front/src/app/globals.css → Assets.xcassets/Colors
    gen-strings.py                front/src/i18n/messages/*.json → Localizable.xcstrings
```

规划期的 `docs/`（范围/需求/API 映射/信息架构/线框图/设计令牌/上手路径/路线图 7 份文档）与
`mockups/`（10 张高保真效果图 + 1 张总跳转图）已经在 M0/M1 落地后删除，蒸馏进了
[`.cursor/skills/zaolang-ios-client/`](../.cursor/skills/zaolang-ios-client/SKILL.md)
——后续要改这个客户端，先加载那个 skill 而不是去找已删除的规划文档。

`App/Sources` 内部分包：

| 目录 | 内容 |
| --- | --- |
| `Shell/` | `RootView`/`RootTabView`（四 Tab 自定义底栏）、`AppRouter`、`DeepLink`（Universal Links 解析）、`DebugSessionView`（M0 验收调试屏，仅 Debug） |
| `Support/` | `AppEnvironment`（DI 容器）、`AppConfig`、`L10n`、`ReachabilityMonitor`、`CurrentAppLocale` |
| `DesignSystem/` | `Color.zl.*`、`ZLRadius`、卡片阴影、eyebrow 样式、骨架脉冲、`zlMotion` 减少动效环境值 |
| `Common/` | 六态通用视图（`EmptyStateView`/`ErrorStateView`/`OfflineBanner`/`NotFoundView`）、登录墙 `LoginWallSheet`、`AuthorRow`/`TagChip`/`StatItem` 等共享小组件 |
| `Media/` | `RemoteImage` + 内存态 `RemoteImageLoader`（M1 直接用后端签名 URL，未接 `ZaolangKit` 的两级 `AssetCache`） |
| `Discover/` `WorkDetail/` `Lineage/` `Profile/` `Learn/` | 五个已实现功能栈的视图 + 视图模型（M1 只读范围） |

`Packages/ZaolangKit/Sources/ZaolangKit` 内部分包：`Models/`（DTO）、`Networking/`（`APIClient`/`ApiError`/幂等键）、
`Session/`（`SessionManager`/`TokenStore`/Cookie 手工编解码）、`Media/`（`AssetCache`）、`Streaming/`（SSE 帧解析，M1 未接界面）。

## 本地跑起来

1. 装 Xcode（≥ 16，对应 iOS 17 SDK）与 XcodeGen：`brew install xcodegen`。
2. 生成并打开工程：
   ```bash
   cd ios
   xcodegen generate
   open Zaolang.xcodeproj
   ```
3. 起后端（仓库根目录）：`make up && make migrate && make seed && make dev-api`，默认监听
   `http://localhost:8000`，与 `AppConfig.apiBaseURL` 一致，不用改代码。
4. 选 iPhone 模拟器直接 Run。首次启动会拉 `GET /v1/auth/me`——游客态返回未认证是正常状态，
   不是错误；已有 Debug 构建可以点右上角的调试图标验证会话链路（`DebugSessionView`，只在
   `#if DEBUG` 下可达，不进 Release 包）。

### 两层验证方式不一样

- `ZaolangKit` 只依赖 Foundation，命令行 `swift build`/`swift test` 能编译，改完网络层/DTO/会话逻辑先在这一层自验：
  ```bash
  cd ios/Packages/ZaolangKit && swift build
  ```
- `App/` 是 SwiftUI + AVKit，依赖 iOS SDK，本机命令行编译不了（除非本机 `xcode-select` 指到完整 Xcode 且已同意许可协议），改完界面层要在 Xcode 里跑一遍才算数。

## 重新生成色板 / 文案

`Assets.xcassets/Colors` 与 `Localizable.xcstrings` 都是生成产物，源头改了就重新跑脚本，不要手改生成结果：

```bash
python3 ios/tools/gen-colors.py    # front/src/app/globals.css 两套主题块变了之后跑
python3 ios/tools/gen-strings.py   # front/src/i18n/messages/*.json 里 iOS 用到的命名空间变了之后跑
```

`gen-strings.py` 只导 M1 用到的命名空间（`discover`/`work`/`workPage`/`lineagePanel`/`learnPage`/
`profilePage`/`states`/`actions`/`a11y`/`nav`/`visibility`/`license`/`theme`/`region`/`brand`），新增
界面用到别的命名空间要去脚本里加，不要在 `Localizable.xcstrings` 里手写词条。

## 当前进度与边界

M0（网络/会话/设计令牌/媒体缓存/三语地基）与 M1（发现、灵感预览、搜索、作品详情、创作链图谱、
个人主页、学习页，全部只读、游客可用）已实现。写动作（点赞/收藏/关注/二创/发布……）的入口照常渲染，
点击统一弹 `LoginWallSheet` 登录墙占位，真实鉴权与创作流留给 M2/M3（里程碑定义、验收标准、尚未解决
的后端契约缺口见 [`zaolang-ios-client`](../.cursor/skills/zaolang-ios-client/SKILL.md) skill 的
「未实现范围」一节）。**不含任何 `admin*` 后台运维能力**——后台是独立桌面场景，走独立登录，C 端令牌
打不进去。

## 与 front/ back/ 的对应关系

```
back/openapi.json          契约真源。改接口后跑 make openapi 防漂移
back/app/models/enums.py   所有枚举的真源（可见性、许可、任务状态、账本类型）
front/src/app/[locale]/(site)/   15 个 C 端页面，iOS 逐屏对照
front/src/components/            共享组件族，iOS 视图按同名功能对照（见 zaolang-ios-client skill）
front/src/i18n/messages/*.json   三语文案真源，iOS 用 gen-strings.py 复用同一套 key 与命名空间
front/src/app/globals.css        设计令牌真源，iOS 用 gen-colors.py 复用同一套色值
```

## 术语表

| 词 | 含义 |
| --- | --- |
| 作品 Work | 已发布的可见实体，带可见性与许可 |
| 作品版本 WorkVersion | 一次发布的快照，创作链的节点就是版本 |
| 创作链 Lineage | 版本之间的父子有向边，作品被删也保留墓碑节点 |
| 二创 Remix | 基于他人可二创作品的新版本，建 lineage 边、继承许可、触发回流分成 |
| 灵感引用 ref | 只借 prompt、**不建链不继承许可**的弱引用，与二创是两回事 |
| 积分 Credits | 整数，永不用浮点。预扣（reserve）→ 结算（capture）或释放（release） |
| 档位 QualityTier | `preview` / `standard` / `cinematic`，决定价格与耗时 |
| 区域 Region | `CN` / `GLOBAL` / `JP`，只管定价与货币，**与界面语言解耦** |

## 三条必须守住的红线

1. **金额是整数**。credits 与货币 minor unit 一律 `Int`，任何 `Double` 参与金额计算都是 bug。
2. **`ref` 不等于 `source_work_id`**。前者是灵感引用，后者建创作链并触发署名与分成。UI 与代码都不许混用。
3. **组件不写死颜色**。只消费语义令牌 `Color.zl.*`（`App/Sources/DesignSystem/Color+ZL.swift`），深色
   色值锁定不得漂移，新增色值走 `tools/gen-colors.py` 重新生成而不是手写。
