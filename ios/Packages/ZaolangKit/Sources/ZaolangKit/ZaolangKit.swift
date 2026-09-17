/// ZaolangKit：造浪 iOS 客户端的纯 Foundation 层。
///
/// 只放不依赖 UIKit / SwiftUI 的代码：网络、会话、数据模型、媒体缓存、SSE。
/// 这一层的正确性用 `swift build` 在本机就能验证，App 层（SwiftUI）要在 Xcode 里跑。
public enum ZaolangKit {
    /// iPhone 17（402×874pt）基准机型尺寸，供调试与日志使用。
    public static let referenceCanvas = (width: 402.0, height: 874.0)
}
