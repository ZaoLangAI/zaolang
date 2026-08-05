import Foundation

/// `GET /v1/learn/posts*` 相关端点，对齐 `APIClient+Works.swift` 的 `WorksQuery` 模式。
/// 这几个端点目前都是"一次取满"（`nextCursor` 恒为 `nil`），仍套 `Page<T>` 解析，
/// 后端补游标后客户端零改动（不变量 8）。
public extension APIClient {
    struct LearnPostsQuery: Sendable {
        public var level: LearnPostLevel?
        public var cursor: String?
        public var limit: Int = 12

        public init(level: LearnPostLevel? = nil, cursor: String? = nil, limit: Int = 12) {
            self.level = level
            self.cursor = cursor
            self.limit = limit
        }

        var queryItems: [URLQueryItem] {
            var items: [URLQueryItem] = [URLQueryItem(name: "limit", value: String(limit))]
            if let level { items.append(URLQueryItem(name: "level", value: level.rawValue)) }
            if let cursor { items.append(URLQueryItem(name: "cursor", value: cursor)) }
            return items
        }
    }

    /// 游客可访问，只返回 `approved` 内容。
    func listLearnPosts(_ query: LearnPostsQuery) async throws -> Page<LearnPostSummary> {
        try await send(.get("/v1/learn/posts", query: query.queryItems))
    }

    /// 需登录，返回当前用户全部状态的发表内容。
    func myLearnPosts() async throws -> Page<LearnPostSummary> {
        try await send(.get("/v1/learn/posts/mine"))
    }

    /// `approved` 所有人可见，其它状态仅作者本人可见，否则 404（`ApiError.notFound` 已合并私有语义）。
    func fetchLearnPost(id: String) async throws -> LearnPostDetail {
        try await send(.get("/v1/learn/posts/\(id)"))
    }

    /// 创建型写接口，必须带幂等键。
    func createLearnPost(_ payload: LearnPostCreateRequest, idempotencyKey: String) async throws -> LearnPostDetail {
        try await send(try .post("/v1/learn/posts", body: payload, idempotencyKey: idempotencyKey))
    }

    /// 仅作者本人；后端有意把状态重置回 `pending`，改过内容必须重新过审。
    func updateLearnPost(id: String, _ payload: LearnPostUpdateRequest) async throws -> LearnPostDetail {
        try await send(try .patch("/v1/learn/posts/\(id)", body: payload))
    }

    /// 仅作者本人，幂等。
    func withdrawLearnPost(id: String) async throws -> LearnPostDetail {
        try await send(.post("/v1/learn/posts/\(id)/withdraw"))
    }
}
