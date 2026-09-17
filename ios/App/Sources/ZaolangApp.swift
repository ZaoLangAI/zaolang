import SwiftUI

/// 造浪 iOS 客户端入口。
///
/// 真正的四 Tab 壳在 `RootView`（见 `Shell/RootView.swift`），这里只做全局环境注入
/// 与启动引导：接鉴权提供者、恢复登录态、拉一次 `/v1/auth/me`。
@main
struct ZaolangApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var environment = AppEnvironment()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(environment)
                .preferredColorScheme(environment.colorSchemeOverride)
                .task { await environment.bootstrap() }
        }
    }
}
