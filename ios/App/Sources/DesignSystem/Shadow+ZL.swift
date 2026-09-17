import SwiftUI

/// 对应网页端 `--card-shadow` / `--card-shadow-raised`。CSS 原值带负 `spread`，
/// SwiftUI 的 `.shadow` 没有 spread 参数，这里取整体视觉相近的近似值——
/// 等你装好 Xcode 能跑真机/模拟器预览后，可以照着网页效果再微调这两个数字。
private struct ZLCardShadowModifier: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        content.shadow(color: .black.opacity(colorScheme == .dark ? 0.40 : 0.08), radius: 1, x: 0, y: 1)
    }
}

private struct ZLRaisedShadowModifier: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        content.shadow(color: .black.opacity(colorScheme == .dark ? 0.55 : 0.20), radius: 20, x: 0, y: 10)
    }
}

extension View {
    /// 普通卡片的贴地阴影。
    func zlCardShadow() -> some View { modifier(ZLCardShadowModifier()) }

    /// 悬浮层 / 弹出内容用的更重阴影。
    func zlRaisedShadow() -> some View { modifier(ZLRaisedShadowModifier()) }
}
