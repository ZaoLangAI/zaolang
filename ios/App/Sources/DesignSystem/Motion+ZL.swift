import SwiftUI

private struct ZLMotionKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    /// true 表示要收敛动效：系统"减少动效"开着，或者用户在造浪账号里单独把 `reduceMotion`
    /// 设成了 true——两者是"或"的关系，任一为真都收敛，由 `RootView` 在根上写入这个值。
    /// 屏幕内部一律读这个环境值，不要各自去读 `accessibilityReduceMotion`。
    var zlMotion: Bool {
        get { self[ZLMotionKey.self] }
        set { self[ZLMotionKey.self] = newValue }
    }
}
