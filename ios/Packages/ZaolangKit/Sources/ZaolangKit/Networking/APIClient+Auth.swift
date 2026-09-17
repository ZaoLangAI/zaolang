import Foundation

public extension APIClient {
    /// M0 调试屏与 App 启动时都靠这一个端点判断"游客还是已登录"、拿主题/语言偏好。
    func fetchMe() async throws -> MeResponse {
        try await send(.get("/v1/auth/me"))
    }

    func updatePreferences(_ payload: PreferencesRequest) async throws -> MeResponse {
        try await send(.patch("/v1/auth/me/preferences", body: payload))
    }

    func updateProfile(_ payload: ProfileUpdateRequest) async throws -> ProfileResponse {
        try await send(.patch("/v1/auth/me/profile", body: payload))
    }
}
