import Foundation

public enum HTTPMethod: String, Sendable {
    case get = "GET"
    case post = "POST"
    case put = "PUT"
    case patch = "PATCH"
    case delete = "DELETE"
}

/// 一次 API 调用的描述。`path` 只写相对路径（如 `/v1/works`），host 由 `APIClient.Configuration` 提供，
/// 这样本地 `localhost:8000` 和未来的生产域名切换只改一处配置。
public struct APIRequest: Sendable {
    public var method: HTTPMethod
    public var path: String
    public var query: [URLQueryItem]
    public var body: Data?
    /// 对应 `Idempotency-Key` 请求头；M1 全是读请求，这里留空。
    public var idempotencyKey: String?

    public init(
        method: HTTPMethod,
        path: String,
        query: [URLQueryItem] = [],
        body: Data? = nil,
        idempotencyKey: String? = nil
    ) {
        self.method = method
        self.path = path
        self.query = query
        self.body = body
        self.idempotencyKey = idempotencyKey
    }

    public static func get(_ path: String, query: [URLQueryItem] = []) -> APIRequest {
        APIRequest(method: .get, path: path, query: query)
    }

    /// 无请求体的写操作（`POST /works/{id}/like`、`DELETE /works/{id}/bookmark` 之类）。
    public static func post(_ path: String, idempotencyKey: String? = nil) -> APIRequest {
        APIRequest(method: .post, path: path, idempotencyKey: idempotencyKey)
    }

    public static func delete(_ path: String) -> APIRequest {
        APIRequest(method: .delete, path: path)
    }

    /// 带 JSON 请求体的写操作，统一走 `JSONEncoder.zaolang` 保证日期格式与后端一致。
    public static func post<Body: Encodable>(
        _ path: String, body: Body, idempotencyKey: String? = nil
    ) throws -> APIRequest {
        APIRequest(method: .post, path: path, body: try JSONEncoder.zaolang.encode(body), idempotencyKey: idempotencyKey)
    }

    public static func patch<Body: Encodable>(_ path: String, body: Body) throws -> APIRequest {
        APIRequest(method: .patch, path: path, body: try JSONEncoder.zaolang.encode(body))
    }
}

/// `APIClient` 依赖的最小会话接口：只要"给不给我一个当前 token"和"401 了帮我刷新一下"。
/// 具体的 Keychain / Cookie / 单飞合并逻辑都在 `SessionManager` 里，`APIClient` 不关心。
public protocol AccessTokenProviding: Sendable {
    func currentAccessToken() async -> String?
    /// 触发一次刷新（内部会把并发调用合并成一次），返回是否刷新成功拿到新 token。
    func refreshAccessToken() async -> Bool
}
