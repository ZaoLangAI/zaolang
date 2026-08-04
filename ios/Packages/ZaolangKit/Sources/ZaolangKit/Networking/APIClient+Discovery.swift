import Foundation

/// 标签与个人主页相关端点，都是"一次取满"（后端只给 `limit`，不给 `cursor`）。
public extension APIClient {
    func listTags(limit: Int = 40) async throws -> Page<TagResponse> {
        try await send(.get("/v1/tags", query: [URLQueryItem(name: "limit", value: String(limit))]))
    }

    func profile(handle: String) async throws -> PublicProfileResponse {
        try await send(.get("/v1/profiles/\(handle)"))
    }

    func profileWorks(handle: String, limit: Int = 60) async throws -> Page<WorkSummary> {
        try await send(.get("/v1/profiles/\(handle)/works", query: [URLQueryItem(name: "limit", value: String(limit))]))
    }

    func asset(id: String) async throws -> AssetResponse {
        try await send(.get("/v1/assets/\(id)"))
    }
}
