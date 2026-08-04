import Foundation

/// 造浪后端的通用 HTTP 执行器。只做四件事：拼 URL、注入 Bearer、解运行时错误信封、
/// 按 `Retry-After` 退避——业务语义（哪个端点、返回什么类型）都在 `APIClient+*.swift` 的扩展里，
/// 这个文件本身不认识任何一个具体端点。
public actor APIClient {
    public struct Configuration: Sendable {
        public var baseURL: URL
        /// 服务端 `Retry-After` 超过这个上限就不自动等了，直接把限流错误抛给调用方，
        /// 避免一次请求因为后端配置异常而挂起半天。
        public var maxRetryAfterWait: TimeInterval

        public init(baseURL: URL, maxRetryAfterWait: TimeInterval = 30) {
            self.baseURL = baseURL
            self.maxRetryAfterWait = maxRetryAfterWait
        }
    }

    private let configuration: Configuration
    private let session: URLSession

    /// 会话层实现（`SessionManager`）事后注入，打破 Kit 内网络层→会话层的构造期循环依赖。
    public var authProvider: AccessTokenProviding?

    public init(configuration: Configuration, session: URLSession, authProvider: AccessTokenProviding? = nil) {
        self.configuration = configuration
        self.session = session
        self.authProvider = authProvider
    }

    public func setAuthProvider(_ provider: AccessTokenProviding?) {
        authProvider = provider
    }

    /// 发一个请求并把响应体解码成 `Response`。
    public func send<Response: Decodable & Sendable>(_ request: APIRequest) async throws -> Response {
        let data = try await sendRaw(request, allowRefreshRetry: true, allowRateLimitRetry: true)
        do {
            return try JSONDecoder.zaolang.decode(Response.self, from: data)
        } catch {
            throw ApiError.decodingFailed(underlying: String(describing: error))
        }
    }

    /// 不关心响应体、只关心成功与否的调用（未来的写操作会用得上）。
    public func sendDiscardingBody(_ request: APIRequest) async throws {
        _ = try await sendRaw(request, allowRefreshRetry: true, allowRateLimitRetry: true)
    }

    private func sendRaw(
        _ request: APIRequest,
        allowRefreshRetry: Bool,
        allowRateLimitRetry: Bool
    ) async throws -> Data {
        let urlRequest = try await buildURLRequest(request)

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch is CancellationError {
            throw CancellationError()
        } catch let urlError as URLError {
            throw ApiError.transport(urlError)
        } catch {
            throw ApiError.transport(URLError(.unknown))
        }

        guard let http = response as? HTTPURLResponse else {
            throw ApiError.unexpectedResponse(status: 0)
        }

        if (200..<300).contains(http.statusCode) {
            return data
        }

        if http.statusCode == 401, allowRefreshRetry, let provider = authProvider {
            let refreshed = await provider.refreshAccessToken()
            if refreshed {
                return try await sendRaw(request, allowRefreshRetry: false, allowRateLimitRetry: allowRateLimitRetry)
            }
        }

        if http.statusCode == 429 {
            let retryAfter = Self.parseRetryAfter(http)
            if allowRateLimitRetry, let retryAfter, retryAfter <= configuration.maxRetryAfterWait {
                try await Task.sleep(nanoseconds: UInt64(retryAfter * 1_000_000_000))
                return try await sendRaw(request, allowRefreshRetry: allowRefreshRetry, allowRateLimitRetry: false)
            }
            throw ApiError.from(status: http.statusCode, data: data, retryAfter: retryAfter)
        }

        throw ApiError.from(status: http.statusCode, data: data)
    }

    private func buildURLRequest(_ request: APIRequest) async throws -> URLRequest {
        guard var components = URLComponents(url: configuration.baseURL.appendingPathComponent(request.path), resolvingAgainstBaseURL: false) else {
            throw ApiError.unexpectedResponse(status: 0)
        }
        if !request.query.isEmpty {
            components.queryItems = request.query
        }
        guard let url = components.url else {
            throw ApiError.unexpectedResponse(status: 0)
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = request.method.rawValue
        urlRequest.httpBody = request.body
        urlRequest.setValue("application/json", forHTTPHeaderField: "Accept")
        if request.body != nil {
            urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let key = request.idempotencyKey {
            urlRequest.setValue(key, forHTTPHeaderField: "Idempotency-Key")
        }
        if let token = await authProvider?.currentAccessToken() {
            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return urlRequest
    }

    /// 后端只发整数秒（`str(retry_after_seconds)`），不需要处理 HTTP-date 形式。
    private static func parseRetryAfter(_ response: HTTPURLResponse) -> TimeInterval? {
        guard let raw = response.value(forHTTPHeaderField: "Retry-After"), let seconds = TimeInterval(raw) else {
            return nil
        }
        return seconds
    }
}
