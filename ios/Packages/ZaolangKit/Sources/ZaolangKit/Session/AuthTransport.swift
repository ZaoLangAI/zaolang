import Foundation

/// 登录 / 注册跟 `RefreshTransport` 同样的顾虑：响应体拿 `access_token`，
/// 但新的 `zl_refresh` 走 `Set-Cookie`，`APIClient.send` 那条路径不暴露响应头，
/// 所以这两个端点也得绕开 `APIClient` 走一次原始 `URLSession` 请求。
public protocol AuthTransport: Sendable {
    func login(email: String, password: String) async throws -> AuthResult
    func register(_ payload: RegisterRequest) async throws -> AuthResult
}

public struct AuthResult: Sendable {
    public let accessToken: String
    public let expiresAt: Date
    public let refreshToken: String
}

public struct URLSessionAuthTransport: AuthTransport {
    private let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL, session: URLSession) {
        self.baseURL = baseURL
        self.session = session
    }

    public func login(email: String, password: String) async throws -> AuthResult {
        try await perform(path: "/v1/auth/login", body: LoginRequest(email: email, password: password))
    }

    public func register(_ payload: RegisterRequest) async throws -> AuthResult {
        try await perform(path: "/v1/auth/register", body: payload)
    }

    private func perform<Body: Encodable>(path: String, body: Body) async throws -> AuthResult {
        let url = baseURL.appendingPathComponent(path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder.zaolang.encode(body)

        let data: Data
        let response: URLResponse
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
        guard let refreshToken = CookieCodec.extractRefreshToken(headers: stringHeaders, url: url) else {
            throw RefreshTransportError.missingRefreshCookieInResponse
        }
        return AuthResult(accessToken: token.accessToken, expiresAt: token.expiresAt, refreshToken: refreshToken)
    }
}
