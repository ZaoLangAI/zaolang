import SwiftUI

/// 封面 / 头像等字段（`WorkSummary.coverURL`、`AuthorSummary.avatarURL`……）后端已经给出
/// **签名好的完整 URL**，不是 `asset_id`——所以这里只做一层按 URL 字符串键的内存缓存，
/// 不复用 `ZaolangKit.AssetCache`（那个按 `asset_id` 做键、专门处理 403 回源换签名，
/// 适配的是"客户端只有 asset_id"的场景，这两处数据形状不一样，勉强套用反而增加耦合）。
@MainActor
final class RemoteImageLoader {
    static let shared = RemoteImageLoader()

    private let memoryCache = NSCache<NSString, UIImage>()

    private init() {
        memoryCache.countLimit = 200
    }

    func cached(_ url: URL) -> UIImage? {
        memoryCache.object(forKey: url.absoluteString as NSString)
    }

    func load(_ url: URL) async throws -> UIImage {
        if let cached = cached(url) { return cached }
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
              let image = UIImage(data: data)
        else {
            throw URLError(.cannotDecodeContentData)
        }
        memoryCache.setObject(image, forKey: url.absoluteString as NSString, cost: data.count)
        return image
    }
}
