import AVFoundation
import UIKit

/// Extracts and caches the first video frame so draft cards can show a still
/// instead of handing a signed MP4 to `RemoteImage`.
@MainActor
final class VideoFirstFrameLoader {
    static let shared = VideoFirstFrameLoader()

    private let memoryCache = NSCache<NSString, UIImage>()

    private init() {
        memoryCache.countLimit = 80
    }

    func cached(_ url: URL) -> UIImage? {
        memoryCache.object(forKey: cacheKey(url) as NSString)
    }

    func load(_ url: URL) async -> UIImage? {
        if let cached = cached(url) { return cached }
        let asset = AVURLAsset(url: url)
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 720, height: 720)
        generator.requestedTimeToleranceBefore = .zero
        generator.requestedTimeToleranceAfter = CMTime(seconds: 0.1, preferredTimescale: 600)
        do {
            let (cgImage, _) = try await generator.image(at: .zero)
            let image = UIImage(cgImage: cgImage)
            memoryCache.setObject(image, forKey: cacheKey(url) as NSString)
            return image
        } catch {
            return nil
        }
    }

    private func cacheKey(_ url: URL) -> String {
        var parts = URLComponents(url: url, resolvingAgainstBaseURL: false)
        parts?.query = nil
        return parts?.string ?? url.absoluteString
    }
}
