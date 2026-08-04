import CryptoKit
import Foundation

public enum AssetCacheError: Error, Sendable {
    case missingSignedURL
    case transport(URLError)
    case unexpectedStatus(Int)
}

/// 按 `asset_id` 做键的两级缓存（内存 `NSCache` + 磁盘，磁盘有总量上限）。
///
/// `GET /v1/assets/{id}` 返回的签名 URL **没有任何过期字段**，服务端 TTL 对客户端不可见，
/// 所以缓存键必须是 `asset_id` 本身而不是签名 URL；命中 403（签名过期）就回源换一次新签名重试一次。
public actor AssetCache {
    public struct Configuration: Sendable {
        public var maxDiskBytes: Int64
        public var maxMemoryBytes: Int

        public init(maxDiskBytes: Int64 = 200 * 1024 * 1024, maxMemoryBytes: Int = 64 * 1024 * 1024) {
            self.maxDiskBytes = maxDiskBytes
            self.maxMemoryBytes = maxMemoryBytes
        }
    }

    private let apiClient: APIClient
    private let rawSession: URLSession
    private let configuration: Configuration
    private let memoryCache = NSCache<NSString, NSData>()
    private let diskDirectory: URL
    private var inFlight: [String: Task<Data, Error>] = [:]

    public init(
        apiClient: APIClient,
        rawSession: URLSession,
        configuration: Configuration = .init(),
        diskDirectoryName: String = "ZaolangAssetCache"
    ) {
        self.apiClient = apiClient
        self.rawSession = rawSession
        self.configuration = configuration
        memoryCache.totalCostLimit = configuration.maxMemoryBytes
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        diskDirectory = base.appendingPathComponent(diskDirectoryName, isDirectory: true)
        try? FileManager.default.createDirectory(at: diskDirectory, withIntermediateDirectories: true)
    }

    /// 取一个资产的字节。命中内存/磁盘直接返回；否则拉签名 URL 下载，下载完写回两级缓存。
    public func data(forAssetID assetID: String) async throws -> Data {
        if let cached = memoryCache.object(forKey: assetID as NSString) {
            return cached as Data
        }
        if let onDisk = readDisk(assetID) {
            memoryCache.setObject(onDisk as NSData, forKey: assetID as NSString, cost: onDisk.count)
            return onDisk
        }
        if let existing = inFlight[assetID] {
            return try await existing.value
        }

        let task = Task { try await self.fetchAndStore(assetID: assetID) }
        inFlight[assetID] = task
        defer { inFlight[assetID] = nil }
        return try await task.value
    }

    public func evictAll() {
        memoryCache.removeAllObjects()
        try? FileManager.default.removeItem(at: diskDirectory)
        try? FileManager.default.createDirectory(at: diskDirectory, withIntermediateDirectories: true)
    }

    private func fetchAndStore(assetID: String) async throws -> Data {
        let data = try await downloadSignedURL(assetID: assetID, allowResignRetry: true)
        memoryCache.setObject(data as NSData, forKey: assetID as NSString, cost: data.count)
        writeDisk(assetID, data: data)
        evictDiskIfNeeded()
        return data
    }

    private func downloadSignedURL(assetID: String, allowResignRetry: Bool) async throws -> Data {
        let asset = try await apiClient.asset(id: assetID)
        guard let urlString = asset.url, let url = URL(string: urlString) else {
            throw AssetCacheError.missingSignedURL
        }

        let (data, status) = try await rawGet(url: url)
        if status == 403, allowResignRetry {
            // 签名过期：/v1/assets/{id} 没有过期字段可判断，只能靠 403 反推，回源换一次新签名重试一次。
            return try await downloadSignedURL(assetID: assetID, allowResignRetry: false)
        }
        guard (200..<300).contains(status) else {
            throw AssetCacheError.unexpectedStatus(status)
        }
        return data
    }

    private func rawGet(url: URL) async throws -> (Data, Int) {
        do {
            let (data, response) = try await rawSession.data(from: url)
            guard let http = response as? HTTPURLResponse else { throw AssetCacheError.unexpectedStatus(0) }
            return (data, http.statusCode)
        } catch let urlError as URLError {
            throw AssetCacheError.transport(urlError)
        }
    }

    // MARK: - 磁盘层

    private func diskURL(for assetID: String) -> URL {
        diskDirectory.appendingPathComponent(Self.safeFileName(assetID))
    }

    private func readDisk(_ assetID: String) -> Data? {
        try? Data(contentsOf: diskURL(for: assetID))
    }

    private func writeDisk(_ assetID: String, data: Data) {
        try? data.write(to: diskURL(for: assetID), options: .atomic)
    }

    /// 超过总量上限就按最后修改时间做 LRU：先删最旧的，直到降回上限以内。
    private func evictDiskIfNeeded() {
        guard let entries = try? FileManager.default.contentsOfDirectory(
            at: diskDirectory,
            includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey]
        ) else { return }

        var items: [(url: URL, date: Date, size: Int64)] = entries.compactMap { url in
            guard let values = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey]),
                  let date = values.contentModificationDate,
                  let size = values.fileSize
            else { return nil }
            return (url, date, Int64(size))
        }

        var total = items.reduce(Int64(0)) { $0 + $1.size }
        guard total > configuration.maxDiskBytes else { return }

        items.sort { $0.date < $1.date }
        for item in items {
            guard total > configuration.maxDiskBytes else { break }
            try? FileManager.default.removeItem(at: item.url)
            total -= item.size
        }
    }

    /// asset_id 理论上是后端生成的安全字符串，但文件名一律走一次哈希，
    /// 不直接信任外部字符串拼路径。
    private static func safeFileName(_ assetID: String) -> String {
        let digest = SHA256.hash(data: Data(assetID.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}
