import Foundation

/// `profile(handle:)` / `profileWorks(handle:limit:)` 已经在 `APIClient+Discovery.swift` 里，
/// 这里只补我的库要用的 `/v1/me/bookmarks`。
public extension APIClient {
    func myBookmarks(cursor: String? = nil, limit: Int = 24) async throws -> Page<WorkSummary> {
        var query = [URLQueryItem(name: "limit", value: String(limit))]
        if let cursor { query.append(URLQueryItem(name: "cursor", value: cursor)) }
        return try await send(.get("/v1/me/bookmarks", query: query))
    }
}
