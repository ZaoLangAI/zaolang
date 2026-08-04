import Foundation

/// 手工编解码 `zl_refresh` Cookie，专门用来绕开被我们关掉的默认 Cookie 容器
/// （见 `URLSessionFactory`）。两个方向都用 Foundation 自带的 `HTTPCookie` 解析器，
/// 不自己写正则——`Set-Cookie` 里 `Expires` 属性自带逗号，手写分割极易踩坑。
enum CookieCodec {
    static let refreshCookieName = "zl_refresh"

    /// 从响应头里把 `zl_refresh` 的值抠出来；同一响应可能还带别的头，只挑这一个 Cookie。
    static func extractRefreshToken(headers: [String: String], url: URL) -> String? {
        let cookies = HTTPCookie.cookies(withResponseHeaderFields: headers, for: url)
        return cookies.first { $0.name == refreshCookieName }?.value
    }

    /// 手工拼 `Cookie` 请求头。只带这一个 Cookie，不需要 `HTTPCookieStorage` 参与。
    static func requestHeader(refreshToken: String, url: URL) -> [String: String] {
        guard
            let cookie = HTTPCookie(properties: [
                .name: refreshCookieName,
                .value: refreshToken,
                .domain: url.host ?? "",
                .path: "/",
            ])
        else {
            return [:]
        }
        return HTTPCookie.requestHeaderFields(with: [cookie])
    }
}
