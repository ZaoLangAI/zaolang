import Foundation

/// 学习内容难度等级，与 `back/app/models/enums.py:LearnPostLevel` 一一对应。
public enum LearnPostLevel: String, Codable, Sendable, CaseIterable {
    case beginner
    case intermediate
    case advanced
}

/// 学习内容审核状态。后端可能扩展取值，DTO 里一律包 `RawOrUnknown<LearnPostStatus>`
/// （照抄 `WorkSummary.visibility` 的用法），未知值不崩，只是这一项显示不出来。
public enum LearnPostStatus: String, Codable, Sendable, CaseIterable {
    case pending
    case approved
    case rejected
    case withdrawn
}

/// 列表卡片投影，风格对齐 `WorkSummary`。
public struct LearnPostSummary: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let title: String
    public let summary: String
    public let level: LearnPostLevel
    public let coverURL: String?
    public let author: AuthorSummary
    public let status: RawOrUnknown<LearnPostStatus>
    public let publishedAt: Date?

    private enum CodingKeys: String, CodingKey {
        case id, title, summary, level
        case coverURL = "cover_url"
        case author, status
        case publishedAt = "published_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        summary = try c.decode(String.self, forKey: .summary)
        level = try c.decode(LearnPostLevel.self, forKey: .level)
        coverURL = try c.decodeIfPresent(String.self, forKey: .coverURL)
        author = try c.decode(AuthorSummary.self, forKey: .author)
        status = try c.decode(RawOrUnknown<LearnPostStatus>.self, forKey: .status)
        publishedAt = try c.decodeIfPresent(Date.self, forKey: .publishedAt)
    }
}

/// 详情页投影：`LearnPostSummary` 全部字段 + markdown 正文 + 拒绝理由 + 创建时间。
/// `coverAssetID` 是详情独有的字段（列表投影没有），编辑回填时靠它把原封面素材带回
/// `PATCH` 请求，不用重新选图也不会清空封面。
///
/// `bodyMarkdown` 里的图片一律写成 `learn-asset:{assetId}` 这种不过期的自定义引用
/// （对象存储的签名 URL 会过期，不能写进持久化的正文）；`assetURLs` 是服务端在这次响应里
/// 临时解析出的 `{资产 id: 当下有效的签名 URL}` 映射，只给渲染时替换显示用
/// （见 `LearnAssetImageProvider`），客户端不需要也不应该自己再发请求解析。
public struct LearnPostDetail: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let title: String
    public let summary: String
    public let level: LearnPostLevel
    public let coverURL: String?
    public let coverAssetID: String?
    public let author: AuthorSummary
    public let status: RawOrUnknown<LearnPostStatus>
    public let publishedAt: Date?
    public let bodyMarkdown: String
    public let assetURLs: [String: String]
    public let rejectReason: String?
    public let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case id, title, summary, level
        case coverURL = "cover_url"
        case coverAssetID = "cover_asset_id"
        case author, status
        case publishedAt = "published_at"
        case bodyMarkdown = "body_markdown"
        case assetURLs = "asset_urls"
        case rejectReason = "reject_reason"
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        summary = try c.decode(String.self, forKey: .summary)
        level = try c.decode(LearnPostLevel.self, forKey: .level)
        coverURL = try c.decodeIfPresent(String.self, forKey: .coverURL)
        coverAssetID = try c.decodeIfPresent(String.self, forKey: .coverAssetID)
        author = try c.decode(AuthorSummary.self, forKey: .author)
        status = try c.decode(RawOrUnknown<LearnPostStatus>.self, forKey: .status)
        publishedAt = try c.decodeIfPresent(Date.self, forKey: .publishedAt)
        bodyMarkdown = try c.decodeIfPresent(String.self, forKey: .bodyMarkdown) ?? ""
        assetURLs = try c.decodeIfPresent([String: String].self, forKey: .assetURLs) ?? [:]
        rejectReason = try c.decodeIfPresent(String.self, forKey: .rejectReason)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
    }
}

/// 提交/编辑请求体，字段与 `LearnPostCreateRequest`/`LearnPostUpdateRequest` 在后端完全一致
/// （后端 `LearnPostUpdateRequest` 也直接继承自 `LearnPostCreateRequest`，无新增字段）。
public struct LearnPostCreateRequest: Encodable, Sendable {
    public var title: String
    public var summary: String
    public var level: LearnPostLevel
    public var coverAssetID: String?
    public var bodyMarkdown: String

    public init(
        title: String,
        summary: String,
        level: LearnPostLevel,
        coverAssetID: String? = nil,
        bodyMarkdown: String = ""
    ) {
        self.title = title
        self.summary = summary
        self.level = level
        self.coverAssetID = coverAssetID
        self.bodyMarkdown = bodyMarkdown
    }

    private enum CodingKeys: String, CodingKey {
        case title, summary, level
        case coverAssetID = "cover_asset_id"
        case bodyMarkdown = "body_markdown"
    }
}

public typealias LearnPostUpdateRequest = LearnPostCreateRequest
