import MarkdownUI
import SwiftUI

/// 把正文里的 `learn-asset:{assetId}` 自定义引用换成真实图片。
///
/// 后端把插图写成这种不过期引用（对象存储签名 URL 会过期，不能写进持久化 markdown），
/// 每次读接口响应会带一份 `asset_urls: { assetId: 这次响应有效的签名 URL }`，客户端只需要
/// 原样查表，不用再发请求解析。
///
/// 已实测确认 cmark-gfm 会把 `learn-asset:xxx` 原样保留成图片节点的 `src`（不校验 scheme），
/// `URL(string:)` 也能正常解析出这个非标准 scheme 的 URL；但其 `host`/`path` 拆分行为不可靠，
/// 所以这里一律用 `absoluteString` 做前缀匹配取 assetId，不读 `host`/`path`。
struct LearnAssetImageProvider: ImageProvider {
    static let scheme = "learn-asset:"

    let assetURLs: [String: String]

    func makeImage(url: URL?) -> some View {
        RemoteImage(url: resolvedURL(from: url), aspectRatio: 16.0 / 9.0, contentMode: .fit)
    }

    private func resolvedURL(from url: URL?) -> URL? {
        guard let raw = url?.absoluteString, raw.hasPrefix(Self.scheme) else { return url }
        let assetID = String(raw.dropFirst(Self.scheme.count))
        guard let signedURLString = assetURLs[assetID] else { return nil }
        return URL(string: signedURLString)
    }
}
