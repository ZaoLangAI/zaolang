import Foundation

enum AppConfig {
    /// 本地联调地址（`make up && make migrate && make seed && make dev-api`）。
    /// 生产域名等前端有了正式域名再填；`Info.plist` 的 `NSAllowsLocalNetworking` 只放开了
    /// 本机回环地址，换成非 `localhost` 的公网 http 地址不会自动生效。
    static let apiBaseURL = URL(string: "http://localhost:8000")!

    /// 分享作品/主页用的 Web 域名，与 `Zaolang.entitlements` 里的 `applinks:` 占位域名保持一致，
    /// 上生产前一起换成正式域名。
    static let webBaseURLString = "https://zaolang.ai"
}
