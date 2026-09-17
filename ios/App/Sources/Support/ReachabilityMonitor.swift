import Network
import Observation

/// 离线横幅用的网络状态观测。`NWPathMonitor` 的回调不在主线程，所有对 `isOffline` 的写入
/// 都跳回 `@MainActor`，避免 SwiftUI 观察到跨线程写入。
@MainActor
@Observable
final class ReachabilityMonitor {
    private(set) var isOffline = false
    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "ai.zaolang.reachability")

    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.isOffline = path.status != .satisfied
            }
        }
        monitor.start(queue: queue)
    }

    deinit {
        monitor.cancel()
    }
}
