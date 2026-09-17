import Foundation

/// 会话的唯一入口。`APIClient` 只认 `AccessTokenProviding` 这个窄接口；
/// 这个类把"要不要刷新""并发 401 能不能合并成一次刷新""刷新失败要不要清空登录态"
/// 这些决策都收在一处。
public actor SessionManager: AccessTokenProviding {
    private let tokenStore: TokenStore
    private let refreshTransport: RefreshTransport
    private let authTransport: AuthTransport

    /// 并发场景下的单飞合并：同一时刻只发一次真实的 refresh 请求，
    /// 其余调用方等这个 Task 的结果，不会把一次网络抖动放大成 N 次刷新请求。
    private var inFlightRefresh: Task<Bool, Never>?

    public private(set) var isAuthenticated: Bool = false

    public init(tokenStore: TokenStore, refreshTransport: RefreshTransport, authTransport: AuthTransport) {
        self.tokenStore = tokenStore
        self.refreshTransport = refreshTransport
        self.authTransport = authTransport
    }

    /// App 启动时调用一次：Keychain 里有 refresh token 就先乐观标记为"已登录"，
    /// 真正的 access token 会在第一次真实请求 401 时按需换，不在启动时抢跑。
    public func bootstrap() async {
        isAuthenticated = await tokenStore.hasRefreshToken()
    }

    public func currentAccessToken() async -> String? {
        await tokenStore.currentAccessToken()
    }

    public func refreshAccessToken() async -> Bool {
        if let inFlightRefresh {
            return await inFlightRefresh.value
        }
        let task = Task { await performRefresh() }
        inFlightRefresh = task
        let result = await task.value
        inFlightRefresh = nil
        return result
    }

    /// 登录 / 注册成功后调用。
    public func establishSession(accessToken: String, expiresAt: Date, refreshToken: String) async {
        await tokenStore.setAccessToken(accessToken, expiresAt: expiresAt)
        await tokenStore.setRefreshToken(refreshToken)
        isAuthenticated = true
    }

    /// 邮箱密码登录；失败（凭据错误、限流……）直接把 `ApiError` 甩给调用方，
    /// 由界面层按错误码显示对应文案，这里不吞、不重试。
    public func login(email: String, password: String) async throws {
        let result = try await authTransport.login(email: email, password: password)
        await establishSession(accessToken: result.accessToken, expiresAt: result.expiresAt, refreshToken: result.refreshToken)
    }

    public func register(_ payload: RegisterRequest) async throws {
        let result = try await authTransport.register(payload)
        await establishSession(accessToken: result.accessToken, expiresAt: result.expiresAt, refreshToken: result.refreshToken)
    }

    /// 用户主动退出。只清本地令牌——`POST /v1/auth/logout` 那次网络调用（用来让后端清
    /// httpOnly cookie，纯粹是 Web 端会用到的语义）由调用方自己决定要不要顺带打一下，
    /// 这里不依赖 `APIClient` 以避免和它的 `authProvider` 反向持有成环。
    public func signOut() async {
        await tokenStore.clearAll()
        isAuthenticated = false
    }

    private func performRefresh() async -> Bool {
        guard let refreshToken = await tokenStore.refreshToken() else {
            isAuthenticated = false
            return false
        }
        do {
            let result = try await refreshTransport.refresh(refreshToken: refreshToken)
            await tokenStore.setAccessToken(result.accessToken, expiresAt: result.expiresAt)
            if let newRefreshToken = result.newRefreshToken {
                await tokenStore.setRefreshToken(newRefreshToken)
            }
            isAuthenticated = true
            return true
        } catch {
            // 刷新失败一律清空回未登录：半个有效令牌比没有令牌更危险，会让后续请求
            // 反复 401→刷新失败→401 地空转。
            await tokenStore.clearAll()
            isAuthenticated = false
            return false
        }
    }
}
