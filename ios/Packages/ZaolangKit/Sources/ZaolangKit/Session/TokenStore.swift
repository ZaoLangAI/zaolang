import Foundation

/// access token 只留在内存（进程重启即失效，逼着走一次 refresh）；
/// refresh token 落 Keychain，跨进程存活。两者的读写都收在这一个 actor 里，
/// 避免调用方各自持有一份状态导致不同步。
public actor TokenStore {
    private var accessToken: String?
    private var accessTokenExpiresAt: Date?
    private let keychain: KeychainStore

    public init(keychain: KeychainStore = KeychainStore()) {
        self.keychain = keychain
    }

    /// 留 30 秒安全余量：临近过期就当已过期，逼着提前刷新，避免"刚判断有效、发请求时刚好过期"的竞态。
    private static let expiryLeeway: TimeInterval = 30

    public func currentAccessToken() -> String? {
        guard let accessToken, let expiresAt = accessTokenExpiresAt else { return nil }
        guard expiresAt.timeIntervalSinceNow > Self.expiryLeeway else { return nil }
        return accessToken
    }

    public func setAccessToken(_ token: String, expiresAt: Date) {
        accessToken = token
        accessTokenExpiresAt = expiresAt
    }

    public func clearAccessToken() {
        accessToken = nil
        accessTokenExpiresAt = nil
    }

    public func refreshToken() -> String? {
        keychain.read()
    }

    public func setRefreshToken(_ value: String) {
        keychain.write(value)
    }

    public func hasRefreshToken() -> Bool {
        keychain.read() != nil
    }

    public func clearAll() {
        clearAccessToken()
        keychain.delete()
    }
}
