import Foundation

/// `profile(handle:)` / `profileWorks(handle:limit:)` 已经在 `APIClient+Discovery.swift` 里，
/// 这里只补我的库要用的 `/v1/me/bookmarks`。
public extension APIClient {
    func myBookmarks(limit: Int = 24) async throws -> Page<WorkSummary> {
        try await send(.get("/v1/me/bookmarks", query: [URLQueryItem(name: "limit", value: String(limit))]))
    }
}
