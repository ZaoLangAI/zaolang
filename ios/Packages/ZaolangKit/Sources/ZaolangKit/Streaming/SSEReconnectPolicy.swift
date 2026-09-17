import Foundation

/// 断线重连的退避序列：1 / 2 / 5 / 10 / 30 秒，到顶后不再增长，避免用户等太久。
/// 一旦重新收到过事件就 `reset()`，下次掉线重新从 1 秒开始——短暂抖动不该被记成"一直不稳定"。
public struct SSEReconnectPolicy: Sendable {
    private static let steps: [TimeInterval] = [1, 2, 5, 10, 30]
    private var attempt = 0

    public init() {}

    public mutating func nextDelay() -> TimeInterval {
        let delay = Self.steps[min(attempt, Self.steps.count - 1)]
        attempt += 1
        return delay
    }

    public mutating func reset() {
        attempt = 0
    }
}
