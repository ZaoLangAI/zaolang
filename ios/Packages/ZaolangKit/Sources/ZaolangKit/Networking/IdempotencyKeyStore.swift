import Foundation

/// 按"操作标识"（通常是一次表单提交在本地生成的 UUID）复用同一个幂等键，
/// 这样网络抖动导致的自动重试不会被后端当成用户点了两次（对应 `Idempotency-Key` 请求头）。
///
/// M1 全是只读请求用不上，但按 M0 验收要求先落地；M2 的点赞/二创/发布会直接复用。
public actor IdempotencyKeyStore {
    private var keysByOperation: [String: String] = [:]

    public init() {}

    public func key(for operationID: String) -> String {
        if let existing = keysByOperation[operationID] {
            return existing
        }
        let generated = UUID().uuidString
        keysByOperation[operationID] = generated
        return generated
    }

    /// 操作彻底结束（成功，或用户主动放弃）后调用，避免键无限堆积。
    public func invalidate(operationID: String) {
        keysByOperation.removeValue(forKey: operationID)
    }
}
