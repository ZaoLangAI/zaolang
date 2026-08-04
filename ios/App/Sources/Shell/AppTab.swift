import SwiftUI

/// 四个 Tab，跟 Web 顶栏的发现/创作/学习/我的库一一对应，各自持有独立 `NavigationStack`。
/// iOS 没有独立的"账号"入口——设置/通知/账单都挂在我的库栈下（`LibraryRoute`）。
enum AppTab: String, CaseIterable, Identifiable {
    case discover
    case create
    case learn
    case library

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .discover: "nav.discover"
        case .create: "nav.create"
        case .learn: "nav.learn"
        case .library: "nav.collection"
        }
    }

    var systemImage: String {
        switch self {
        case .discover: "safari"
        case .create: "wand.and.stars"
        case .learn: "graduationcap"
        case .library: "square.stack"
        }
    }
}
