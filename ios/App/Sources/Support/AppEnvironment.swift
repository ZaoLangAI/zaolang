import Observation
import SwiftUI
import ZaolangKit

/// 全局依赖的组装点：一个 `APIClient` + 一个 `SessionManager` + 一个 `AssetCache`，
/// 全 App 共用同一份，不在各屏幕里各自 new 一套（那样 401 单飞合并、磁盘缓存上限都会失效）。
/// 标 `@MainActor`：内部持有的 `ReachabilityMonitor` 是 MainActor-isolated，且这个类本来就只从
/// SwiftUI（`@State`/`@Environment`，天然主线程）读写，不需要跨线程访问。
@MainActor
@Observable
final class AppEnvironment {
    let apiClient: APIClient
    let sessionManager: SessionManager
    let assetCache: AssetCache
    let reachability: ReachabilityMonitor
    /// 提交生成 / 重试 / 发布三处写操作共用同一个键仓，按"这一次表单提交"的本地操作 id 复用键——
    /// 断网重发不会被后端当成用户点了两次。
    let idempotencyKeys = IdempotencyKeyStore()
    /// 上传素材第二步（把字节真正传到预签名 URL）复用同一个 `URLSession`，不走 `APIClient` 的鉴权/幂等。
    let uploadTransport: UploadTransport
    /// 任务详情页的 SSE 订阅入口；`authProvider` 是同一个 `SessionManager`，token 过期时自动带最新的。
    let eventStreamClient: EventStreamClient

    /// 游客态下恒为 nil；游客可用是常态，`nil` 是正常状态之一，不当错误处理。
    private(set) var me: MeResponse?
    private(set) var isBootstrapping = true

    var isAuthenticated: Bool { me != nil }

    /// 登录墙的"动作恢复"原语：未登录时点写操作，先存这个动作再弹登录 sheet；
    /// 登录/注册成功后把它取出来执行一次并清空，取消则直接丢弃——绝不静默执行。
    private(set) var pendingAuthAction: (() -> Void)?
    var isPresentingAuthSheet = false
    /// 登录 sheet 里展示的"你正要做什么"文案，与 `pendingAuthAction` 成对出现。
    var pendingAuthActionLabel: String?

    /// 写操作的统一入口：已登录直接执行；未登录暂存动作、弹登录 sheet。
    func requireAuth(actionLabel: String, action: @escaping () -> Void) {
        if isAuthenticated {
            action()
            return
        }
        pendingAuthAction = action
        pendingAuthActionLabel = actionLabel
        isPresentingAuthSheet = true
    }

    /// 登录/注册成功后调用：刷新 `/v1/auth/me`，把暂存的动作补跑一次。
    func authSucceeded() async {
        isPresentingAuthSheet = false
        await refreshMe()
        let action = pendingAuthAction
        pendingAuthAction = nil
        pendingAuthActionLabel = nil
        action?()
    }

    /// 用户在登录 sheet 里点了取消：动作按语义直接丢弃，绝不静默执行。
    func cancelAuthSheet() {
        isPresentingAuthSheet = false
        pendingAuthAction = nil
        pendingAuthActionLabel = nil
    }

    /// 服务端保存的主题偏好；游客没有这份偏好，交给系统外观设置。
    var colorSchemeOverride: ColorScheme? {
        switch me?.theme.value {
        case .dark: .dark
        case .light: .light
        case .system, nil: nil
        }
    }

    /// 服务端保存的减少动效偏好；系统那一半由 `RootView` 读 `accessibilityReduceMotion` 合并。
    var reduceMotionPreference: Bool { me?.reduceMotionPreference ?? false }

    init() {
        let session = URLSessionFactory.makeSession()
        let client = APIClient(configuration: .init(baseURL: AppConfig.apiBaseURL), session: session)
        let refreshTransport = URLSessionRefreshTransport(baseURL: AppConfig.apiBaseURL, session: session)
        let authTransport = URLSessionAuthTransport(baseURL: AppConfig.apiBaseURL, session: session)
        let manager = SessionManager(tokenStore: TokenStore(), refreshTransport: refreshTransport, authTransport: authTransport)

        apiClient = client
        sessionManager = manager
        assetCache = AssetCache(apiClient: client, rawSession: session)
        reachability = ReachabilityMonitor()
        uploadTransport = UploadTransport(session: session)
        eventStreamClient = EventStreamClient(baseURL: AppConfig.apiBaseURL, session: session, authProvider: manager)
    }

    /// App 启动时调一次：接上 `APIClient` 的鉴权提供者、恢复登录态、拉一次 `/v1/auth/me`。
    func bootstrap() async {
        await sessionManager.bootstrap()
        await apiClient.setAuthProvider(sessionManager)
        await refreshMe()
        isBootstrapping = false
    }

    /// 拉一次 `/v1/auth/me`。游客（没有 refresh token，或者刷新失败）时直接落回 `nil`，
    /// 这也是本地测试"续期失败自动回未登录"的验收路径——不需要额外的调试开关。
    func refreshMe() async {
        do {
            me = try await apiClient.fetchMe()
        } catch {
            me = nil
        }
    }

    /// 登录/注册失败时把 `ApiError.fallbackMessage` 抛给调用方显示，成功时补一次 `/v1/auth/me`
    /// 并执行登录墙暂存的动作——`AuthSheet` 是这两个方法唯一的调用方。
    func login(email: String, password: String) async throws {
        try await sessionManager.login(email: email, password: password)
        await authSucceeded()
    }

    func register(_ payload: RegisterRequest) async throws {
        try await sessionManager.register(payload)
        await authSucceeded()
    }

    func signOut() async {
        if let deviceID = registeredDeviceID {
            try? await apiClient.unregisterDevice(id: deviceID)
        }
        try? await apiClient.sendDiscardingBody(.post("/v1/auth/logout"))
        await sessionManager.signOut()
        me = nil
        registeredDeviceID = nil
        trackedJobs = [:]
        for task in trackingTasks.values { task.cancel() }
        trackingTasks = [:]
    }

    /// 设置页两个表单的提交口子。成功后都用返回值/重新拉取刷新 `me`，
    /// 保证"改完杀掉 App 重启仍生效"——真源永远是服务端，不在本地另存一份。
    func updatePreferences(_ payload: PreferencesRequest) async throws {
        me = try await apiClient.updatePreferences(payload)
    }

    func updateProfile(_ payload: ProfileUpdateRequest) async throws {
        _ = try await apiClient.updateProfile(payload)
        await refreshMe()
    }

    // MARK: - 推送设备注册

    private(set) var registeredDeviceID: String?

    /// `PushManager` 拿到 APNs token 后调用。未登录时静默跳过——登录成功后 `authSucceeded()`
    /// 不会重新触发注册，因为 token 本身没变，`PushManager` 会在权限状态变化时自己再调一次。
    func registerPushToken(_ token: String) async {
        guard isAuthenticated else { return }
        let payload = DeviceRegisterRequest(pushToken: token, locale: CurrentAppLocale.value.rawValue)
        do {
            let device = try await apiClient.registerDevice(payload)
            registeredDeviceID = device.id
        } catch {
            // 注册失败不影响其余功能，下次前台恢复时 `PushManager` 会重试。
        }
    }

    // MARK: - 任务追踪（创作 Tab 浮条）

    private(set) var trackedJobs: [String: GenerationJobResponse] = [:]
    private var trackingTasks: [String: Task<Void, Never>] = [:]

    /// 提交/重试后调用一次；非终态期间每 5 秒轮询一次直到终态，供创作 Tab 顶部浮条读取。
    /// 任务详情页自己接 SSE（更及时），这里只保证"切出任务详情页之后浮条仍在动"。
    func trackJob(id: String) {
        guard trackingTasks[id] == nil else { return }
        trackedJobs[id] = nil
        trackingTasks[id] = Task {
            defer { trackingTasks[id] = nil }
            while !Task.isCancelled {
                guard let job = try? await apiClient.fetchGenerationJob(id: id) else { return }
                trackedJobs[id] = job
                if job.status.value?.isTerminal ?? true { return }
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    /// 浮条只展示"最近一个还在跑的任务"，多任务并行时旁边标个数量即可（`RootTabView` 处理）。
    var activeJobs: [GenerationJobResponse] {
        trackedJobs.values
            .filter { $0.status.value?.isTerminal != true }
            .sorted { $0.createdAt > $1.createdAt }
    }
}
