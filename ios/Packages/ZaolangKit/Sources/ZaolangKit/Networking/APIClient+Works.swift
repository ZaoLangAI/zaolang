import Foundation

/// `GET /v1/works` 相关端点。**只有这个列表和 `credits/ledger` 支持游标分页**，
/// 其余列表端点（标签、他人主页作品、相似作品）只有 `limit`，按"一次取满"调用。
public extension APIClient {
    struct WorksQuery: Sendable {
        public var q: String?
        public var tag: String?
        public var remixable: Bool = false
        public var sort: WorksSort = .recent
        public var cursor: String?
        public var limit: Int = 24

        public init(
            q: String? = nil,
            tag: String? = nil,
            remixable: Bool = false,
            sort: WorksSort = .recent,
            cursor: String? = nil,
            limit: Int = 24
        ) {
            self.q = q
            self.tag = tag
            self.remixable = remixable
            self.sort = sort
            self.cursor = cursor
            self.limit = limit
        }

        var queryItems: [URLQueryItem] {
            var items: [URLQueryItem] = [
                URLQueryItem(name: "remixable", value: remixable ? "true" : "false"),
                URLQueryItem(name: "sort", value: sort.rawValue),
                URLQueryItem(name: "limit", value: String(limit)),
            ]
            if let q, !q.isEmpty { items.append(URLQueryItem(name: "q", value: q)) }
            if let tag, !tag.isEmpty { items.append(URLQueryItem(name: "tag", value: tag)) }
            if let cursor { items.append(URLQueryItem(name: "cursor", value: cursor)) }
            return items
        }
    }

    func listWorks(_ query: WorksQuery) async throws -> Page<WorkSummary> {
        try await send(.get("/v1/works", query: query.queryItems))
    }

    func fetchWork(id: String) async throws -> WorkDetail {
        try await send(.get("/v1/works/\(id)"))
    }

    func similarWorks(workID: String, limit: Int = 8) async throws -> Page<WorkSummary> {
        try await send(.get("/v1/works/\(workID)/similar", query: [URLQueryItem(name: "limit", value: String(limit))]))
    }

    func lineage(workID: String, depth: Int = 3) async throws -> LineageResponse {
        try await send(.get("/v1/works/\(workID)/lineage", query: [URLQueryItem(name: "depth", value: String(depth))]))
    }

    func versionDiff(childVersionID: String) async throws -> VersionDiffResponse {
        try await send(.get("/v1/work-versions/\(childVersionID)/diff"))
    }
}
