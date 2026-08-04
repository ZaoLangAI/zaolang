import Foundation

/// 运行时错误信封：`{"error": {code, message, details, request_id}}`。
/// 注意 OpenAPI 声明的 `HTTPValidationError` 只是文档噪音——422 在运行时走的是这同一个信封
/// （见 `back/app/api/errors.py`），因此这里不单独建模 422 的形状。
struct ApiErrorEnvelope: Decodable {
    let code: String
    let message: String
    let details: JSONValue
    let requestID: String?

    private enum CodingKeys: String, CodingKey {
        case code, message, details
        case requestID = "request_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        code = try c.decode(String.self, forKey: .code)
        message = try c.decode(String.self, forKey: .message)
        details = try c.decodeIfPresent(JSONValue.self, forKey: .details) ?? .object([:])
        requestID = try c.decodeIfPresent(String.self, forKey: .requestID)
    }
}

private struct ApiErrorWrapper: Decodable {
    let error: ApiErrorEnvelope
}

/// `ZaolangKit` 统一的错误类型：
///
/// - **404 与 `WORK_PRIVATE` 在这一层就合并**成 `.notFound`：私有作品与真正不存在的作品，
///   UI 只会看到"这个作品不存在"，永远不泄漏"你没权限看"的措辞。
/// - 传输层错误（离线、超时、DNS 失败……）单独一个 case，UI 靠它判断要不要显示离线横幅，
///   而不是把网络问题和业务错误混在一条文案里。
/// - 429 带 `Retry-After` 由 `APIClient` 先自动退避重试一次；重试后仍限流才会到这里。
public enum ApiError: Error, Sendable {
    case transport(URLError)
    case unauthorized(message: String)
    case notFound
    case rateLimited(retryAfter: TimeInterval?, message: String)
    case domain(code: String, message: String, details: JSONValue, status: Int)
    case decodingFailed(underlying: String)
    case unexpectedResponse(status: Int)

    /// 判断要不要显示离线横幅：只有传输层里"确实连不上"的那几种才算，
    /// 服务端 5xx 属于业务错误，不算离线。
    public var isOffline: Bool {
        guard case .transport(let urlError) = self else { return false }
        switch urlError.code {
        case .notConnectedToInternet, .networkConnectionLost, .cannotConnectToHost,
             .cannotFindHost, .dnsLookupFailed, .timedOut, .internationalRoamingOff, .dataNotAllowed:
            return true
        default:
            return false
        }
    }

    /// 面向用户的兜底文案；具体屏幕通常会用 `code` 或状态码挑更精确的本地化文案，
    /// 这里只保证任何 case 都有一句能直接显示的话。
    public var fallbackMessage: String {
        switch self {
        case .transport: "网络连接失败，请检查网络后重试。"
        case .unauthorized(let message): message
        case .notFound: "内容不存在。"
        case .rateLimited(_, let message): message
        case .domain(_, let message, _, _): message
        case .decodingFailed: "服务返回的数据无法解析。"
        case .unexpectedResponse: "服务暂时不可用，请稍后重试。"
        }
    }

    static func from(status: Int, data: Data, retryAfter: TimeInterval? = nil) -> ApiError {
        guard let wrapper = try? JSONDecoder.zaolang.decode(ApiErrorWrapper.self, from: data) else {
            return .unexpectedResponse(status: status)
        }
        let envelope = wrapper.error
        switch status {
        case 404:
            return .notFound
        case 401:
            return .unauthorized(message: envelope.message)
        case 429:
            return .rateLimited(retryAfter: retryAfter, message: envelope.message)
        default:
            return .domain(code: envelope.code, message: envelope.message, details: envelope.details, status: status)
        }
    }
}
