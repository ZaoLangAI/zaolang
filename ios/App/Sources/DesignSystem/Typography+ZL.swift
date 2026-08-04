import SwiftUI

/// 对应网页端 `.eyebrow`：卡片/区块顶部那种小号强调标签（"DISCOVER"、"FEATURED"……）。
private struct EyebrowModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(.system(size: 11, weight: .semibold))
            .tracking(11 * 0.18) // CSS 的 letter-spacing: 0.18em，换算成点值
            .textCase(.uppercase)
            .foregroundStyle(Color.zl.amber)
    }
}

extension View {
    func zlEyebrow() -> some View { modifier(EyebrowModifier()) }
}
