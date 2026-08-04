import Foundation

/// 造浪的会话续期走**方案 A**：客户端自己接管 `zl_refresh` Cookie（读 `Set-Cookie`、存 Keychain、
/// 发请求时手工拼 `Cookie` 头），所以必须先关掉 `URLSession` 默认的 Cookie 容器——
/// 否则系统会把 Cookie 存进自己的 `HTTPCookieStorage`，跟我们手工管理的 Keychain 副本各存一份，
/// 两边一旦不同步（比如用户清了 App 但系统 Cookie 存储没清），行为会变得难以调试。
///
/// `APIClient` 和 `RefreshTransport` 的实现都必须用这里造出来的 session，不要在别处再建。
public enum URLSessionFactory {
    public static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.default
        configuration.httpCookieAcceptPolicy = .never
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        return URLSession(configuration: configuration)
    }
}
