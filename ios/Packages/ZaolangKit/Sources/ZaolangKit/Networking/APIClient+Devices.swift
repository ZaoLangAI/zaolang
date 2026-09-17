import Foundation

/// APNs 设备令牌注册。真实推送发送在后端（也是占位实现，见后端
/// `app.domain.notifications.push`），这里只负责让后端知道"这个用户在这台设备上"。
public extension APIClient {
    func registerDevice(_ payload: DeviceRegisterRequest) async throws -> DeviceResponse {
        try await send(.post("/v1/me/devices", body: payload))
    }

    func unregisterDevice(id: String) async throws {
        try await sendDiscardingBody(.delete("/v1/me/devices/\(id)"))
    }
}
