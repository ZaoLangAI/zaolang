import Foundation

/// 点赞 / 收藏 / 关注 / 举报 / 合集 / 通知——全是写操作，M1 只弹登录墙，这些方法从 M2 起才有调用方。
public extension APIClient {
    func likeWork(id: String) async throws -> CountResponse {
        try await send(.post("/v1/works/\(id)/like"))
    }

    func unlikeWork(id: String) async throws -> CountResponse {
        try await send(.delete("/v1/works/\(id)/like"))
    }

    func bookmarkWork(id: String) async throws -> OkResponse {
        try await send(.post("/v1/works/\(id)/bookmark"))
    }

    func unbookmarkWork(id: String) async throws -> OkResponse {
        try await send(.delete("/v1/works/\(id)/bookmark"))
    }

    func updateWorkVisibility(id: String, visibility: Visibility) async throws -> WorkSummary {
        try await send(.patch("/v1/works/\(id)/visibility", body: VisibilityUpdateRequest(visibility: visibility)))
    }

    func followUser(id: String) async throws -> OkResponse {
        try await send(.post("/v1/users/\(id)/follow"))
    }

    func unfollowUser(id: String) async throws -> OkResponse {
        try await send(.delete("/v1/users/\(id)/follow"))
    }

    func createReport(_ payload: ReportCreateRequest) async throws -> OkResponse {
        try await send(.post("/v1/reports", body: payload))
    }

    // MARK: - 通知

    func listNotifications(unreadOnly: Bool = false, limit: Int = 20) async throws -> Page<NotificationResponse> {
        try await send(.get(
            "/v1/notifications",
            query: [
                URLQueryItem(name: "unread_only", value: unreadOnly ? "true" : "false"),
                URLQueryItem(name: "limit", value: String(limit)),
            ]
        ))
    }

    func unreadNotificationCount() async throws -> CountResponse {
        try await send(.get("/v1/notifications/unread-count"))
    }

    /// `notificationID` 为 nil 时把全部未读标为已读。
    func markNotificationsRead(notificationID: String? = nil) async throws -> CountResponse {
        var query: [URLQueryItem] = []
        if let notificationID { query.append(URLQueryItem(name: "notification_id", value: notificationID)) }
        return try await send(APIRequest(method: .post, path: "/v1/notifications/read", query: query))
    }

    // MARK: - 合集

    func createCollection(_ payload: CollectionCreateRequest) async throws -> CollectionResponse {
        try await send(.post("/v1/collections", body: payload))
    }

    func listCollections(limit: Int = 20) async throws -> Page<CollectionResponse> {
        try await send(.get("/v1/collections", query: [URLQueryItem(name: "limit", value: String(limit))]))
    }

    /// 后端这个端点的 `work_id` 是普通标量参数，FastAPI 按查询参数解析（不是 JSON body）。
    func addWorkToCollection(collectionID: String, workID: String) async throws -> OkResponse {
        try await send(APIRequest(
            method: .post,
            path: "/v1/collections/\(collectionID)/items",
            query: [URLQueryItem(name: "work_id", value: workID)]
        ))
    }

    func removeWorkFromCollection(collectionID: String, workID: String) async throws -> OkResponse {
        try await send(.delete("/v1/collections/\(collectionID)/items/\(workID)"))
    }
}
