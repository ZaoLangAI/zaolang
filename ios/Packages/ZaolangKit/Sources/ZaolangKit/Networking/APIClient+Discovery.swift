import Foundation

/// 标签与个人主页相关端点，都是"一次取满"（后端只给 `limit`，不给 `cursor`）。
public extension APIClient {
    func listTags(limit: Int = 40) async throws -> Page<TagResponse> {
        try await send(.get("/v1/tags", query: [URLQueryItem(name: "limit", value: String(limit))]))
    }

    func profile(handle: String) async throws -> PublicProfileResponse {
        try await send(.get("/v1/profiles/\(handle)"))
    }

    func profileWorks(handle: String, cursor: String? = nil, limit: Int = 60) async throws -> Page<WorkSummary> {
        var query = [URLQueryItem(name: "limit", value: String(limit))]
        if let cursor { query.append(URLQueryItem(name: "cursor", value: cursor)) }
        return try await send(.get("/v1/profiles/\(handle)/works", query: query))
    }

    func asset(id: String) async throws -> AssetResponse {
        try await send(.get("/v1/assets/\(id)"))
    }
}
