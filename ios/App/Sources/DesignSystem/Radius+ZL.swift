import SwiftUI

/// 对应网页端 `--radius-sm/md/lg`（10/16/24px）。iOS 上一律用 `continuous`（squircle）角，
/// 跟系统控件的圆角手感一致，不用 `circular`。
enum ZLRadius {
    static let sm: CGFloat = 10
    static let md: CGFloat = 16
    static let lg: CGFloat = 24
}

extension View {
    func zlCornerRadius(_ radius: CGFloat) -> some View {
        clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}

extension RoundedRectangle {
    static func zl(_ radius: CGFloat) -> RoundedRectangle {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
    }
}
