import Foundation

/// Universal Link 解析结果：落到哪个 Tab，再往那个 Tab 的栈里 push 什么。
enum DeepLink: Equatable {
    case discoverRoot
    case workDetail(workID: String)
    case profile(handle: String)
    case learnRoot
    case createRoot
    case jobDetail(jobID: String)

    /// Web 路由永远带 locale 前缀（`always`，见 `front/src/i18n/routing.ts`），
    /// 解析时忽略这段前缀，App 内语言以当前系统/App 语言为准，不跟着链接切换。
    private static let localePrefixes: Set<String> = ["zh-CN", "en", "ja"]

    init?(url: URL) {
        var segments = url.pathComponents.filter { $0 != "/" }
        if let first = segments.first, Self.localePrefixes.contains(first) {
            segments.removeFirst()
        }

        switch segments.first {
        case "discover", nil:
            self = .discoverRoot
        case "work":
            guard segments.count >= 2 else { return nil }
            self = .workDetail(workID: segments[1])
        case "profile":
            guard segments.count >= 2 else { return nil }
            self = .profile(handle: segments[1])
        case "learn":
            self = .learnRoot
        case "create":
            self = .createRoot
        case "jobs":
            guard segments.count >= 2 else { self = .createRoot; return }
            self = .jobDetail(jobID: segments[1])
        default:
            return nil
        }
    }
}
