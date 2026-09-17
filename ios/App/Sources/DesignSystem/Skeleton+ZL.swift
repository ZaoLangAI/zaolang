import SwiftUI

/// 骨架屏的呼吸动画。调用方负责给形状本身填 `Color.zl.skeleton`，这个修饰器只加动效；
/// 减少动效时直接给一个固定透明度，不跑循环动画。
private struct SkeletonPulseModifier: ViewModifier {
    @Environment(\.zlMotion) private var reduceMotion
    @State private var isPulsing = false

    func body(content: Content) -> some View {
        content
            .opacity(reduceMotion ? 0.7 : (isPulsing ? 0.45 : 0.85))
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.9).repeatForever(autoreverses: true), value: isPulsing)
            .task {
                guard !reduceMotion else { return }
                isPulsing = true
            }
    }
}

extension View {
    /// 用法：`RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse()`
    func zlSkeletonPulse() -> some View { modifier(SkeletonPulseModifier()) }
}
