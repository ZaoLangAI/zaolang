import Foundation

/// `GET /v1/assets/{id}` 的响应。**没有任何过期字段**——`url` 是服务端即时签名，
/// TTL 只在服务端配置，客户端必须按 `id` 做缓存键，403 时回源换新签名（见 `Media/AssetCache.swift`）。
public struct AssetResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let mediaType: MediaType
    public let mimeType: String
    public let sizeBytes: Int
    public let width: Int?
    public let height: Int?
    public let durationMS: Int?
    public let url: String?
    public let moderationStatus: String
    public let isPrototype: Bool
    public let aiGenerated: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case mediaType = "media_type"
        case mimeType = "mime_type"
        case sizeBytes = "size_bytes"
        case width, height
        case durationMS = "duration_ms"
        case url
        case moderationStatus = "moderation_status"
        case isPrototype = "is_prototype"
        case aiGenerated = "ai_generated"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        mediaType = try c.decode(MediaType.self, forKey: .mediaType)
        mimeType = try c.decode(String.self, forKey: .mimeType)
        sizeBytes = try c.decode(Int.self, forKey: .sizeBytes)
        width = try c.decodeIfPresent(Int.self, forKey: .width)
        height = try c.decodeIfPresent(Int.self, forKey: .height)
        durationMS = try c.decodeIfPresent(Int.self, forKey: .durationMS)
        url = try c.decodeIfPresent(String.self, forKey: .url)
        moderationStatus = try c.decode(String.self, forKey: .moderationStatus)
        isPrototype = try c.decodeIfPresent(Bool.self, forKey: .isPrototype) ?? false
        aiGenerated = try c.decodeIfPresent(Bool.self, forKey: .aiGenerated) ?? false
    }
}
