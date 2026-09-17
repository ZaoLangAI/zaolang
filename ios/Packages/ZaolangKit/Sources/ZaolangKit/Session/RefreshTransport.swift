import Foundation

/// 用 refresh token 换一次新的会话。抽成协议是因为现在的传输方式（手工 Cookie 头）
/// 是后端还没给原生 iOS 通道时的权宜方案；后端一旦补上专用续期接口，
/// 换一个新实现接进 `SessionManager` 就行，调用方完全不用动。
public protocol RefreshTransport: Sendable {
    func refresh(refreshToken: String) async throws -> RefreshResult
}

public struct RefreshResult: Sendable {
    public let accessToken: String
    public let expiresAt: Date
    /// 后端 `_issue_session` 每次都会轮换 cookie，理论上恒非 nil；
    /// 留 Optional 是防御性的——万一某次响应体解出来了但头没解出新 cookie，
    /// 那就继续用旧 refresh token，而不是直接判失败。
    public let newRefreshToken: String?
}

enum RefreshTransportError: Error {
    case missingRefreshCookieInResponse
}

/// 方案 A 的具体实现：`POST /v1/auth/refresh`，手工带上 `Cookie: zl_refresh=...`，
/// 从响应的 `Set-Cookie` 里解出轮换后的新值。
public struct URLSessionRefreshTransport: RefreshTransport {
    private let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL, session: URLSession) {
        self.baseURL = baseURL
        self.session = session
    }

    public func refresh(refreshToken: String) async throws -> RefreshResult {
        let url = baseURL.appendingPathComponent("/v1/auth/refresh")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        for (field, value) in CookieCodec.requestHeader(refreshToken: refreshToken, url: url) {
            request.setValue(value, forHTTPHeaderField: field)
        }

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request)
        } catch let urlError as URLError {
            throw ApiError.transport(urlError)
        }

        guard let http = response as? HTTPURLResponse else {
            throw ApiError.unexpectedResponse(status: 0)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw ApiError.from(status: http.statusCode, data: data)
        }

        let token = try JSONDecoder.zaolang.decode(TokenResponse.self, from: data)

        var stringHeaders: [String: String] = [:]
        for (key, value) in http.allHeaderFields {
            guard let keyString = key as? String else { continue }
            stringHeaders[keyString] = String(describing: value)
        }
        let newRefreshToken = CookieCodec.extractRefreshToken(headers: stringHeaders, url: url)

        return RefreshResult(accessToken: token.accessToken, expiresAt: token.expiresAt, newRefreshToken: newRefreshToken)
    }
}
