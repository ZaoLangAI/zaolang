import Foundation

/// 作者摘要，出现在作品卡片、创作链祖先节点等处。
public struct AuthorSummary: Codable, Sendable, Equatable, Identifiable {
    public let id: String // = userId，Identifiable 需要
    public let displayName: String
    public let handle: String
    public let avatarURL: String?

    public init(id: String, displayName: String, handle: String, avatarURL: String?) {
        self.id = id
        self.displayName = displayName
        self.handle = handle
        self.avatarURL = avatarURL
    }

    private enum CodingKeys: String, CodingKey {
        case id = "user_id"
        case displayName = "display_name"
        case handle
        case avatarURL = "avatar_url"
    }
}

/// 浏览 / 点赞 / 评论 / 二创的计数，全部有默认值 0，后端字段本身也全是可选。
public struct WorkStats: Codable, Sendable, Equatable {
    public let viewCount: Int
    public let likeCount: Int
    public let commentCount: Int
    public let remixCount: Int

    public static let zero = WorkStats(viewCount: 0, likeCount: 0, commentCount: 0, remixCount: 0)

    public init(viewCount: Int, likeCount: Int, commentCount: Int, remixCount: Int) {
        self.viewCount = viewCount
        self.likeCount = likeCount
        self.commentCount = commentCount
        self.remixCount = remixCount
    }

    private enum CodingKeys: String, CodingKey {
        case viewCount = "view_count"
        case likeCount = "like_count"
        case commentCount = "comment_count"
        case remixCount = "remix_count"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        viewCount = try c.decodeIfPresent(Int.self, forKey: .viewCount) ?? 0
        likeCount = try c.decodeIfPresent(Int.self, forKey: .likeCount) ?? 0
        commentCount = try c.decodeIfPresent(Int.self, forKey: .commentCount) ?? 0
        remixCount = try c.decodeIfPresent(Int.self, forKey: .remixCount) ?? 0
    }
}

/// 许可快照：类型、署名文案、细粒度权限位。二创发布时把这份快照原样带到新版本上。
public struct LicenseInfo: Codable, Sendable, Equatable {
    public let licenseType: RawOrUnknown<LicenseType>
    public let attributionText: String
    public let permissions: [String: Bool]
    public let capturedAt: Date?

    private enum CodingKeys: String, CodingKey {
        case licenseType = "license_type"
        case attributionText = "attribution_text"
        case permissions
        case capturedAt = "captured_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        licenseType = try c.decode(RawOrUnknown<LicenseType>.self, forKey: .licenseType)
        attributionText = try c.decode(String.self, forKey: .attributionText)
        permissions = try c.decodeIfPresent([String: Bool].self, forKey: .permissions) ?? [:]
        capturedAt = try c.decodeIfPresent(Date.self, forKey: .capturedAt)
    }
}

/// 二创可继承的参数。许可禁止衍生时后端只回空对象，字段全是可选。
public struct ReusableParams: Codable, Sendable, Equatable {
    public let prompt: String?
    public let negativePrompt: String?
    public let seed: Int?
    public let styleTags: [String]
    public let workflowVersionID: String?
    public let extra: [String: JSONValue]

    private enum CodingKeys: String, CodingKey {
        case prompt
        case negativePrompt = "negative_prompt"
        case seed
        case styleTags = "style_tags"
        case workflowVersionID = "workflow_version_id"
        case extra
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        prompt = try c.decodeIfPresent(String.self, forKey: .prompt)
        negativePrompt = try c.decodeIfPresent(String.self, forKey: .negativePrompt)
        seed = try c.decodeIfPresent(Int.self, forKey: .seed)
        styleTags = try c.decodeIfPresent([String].self, forKey: .styleTags) ?? []
        workflowVersionID = try c.decodeIfPresent(String.self, forKey: .workflowVersionID)
        extra = try c.decodeIfPresent([String: JSONValue].self, forKey: .extra) ?? [:]
    }

    /// prompt 与参数都为空时，说明这份许可不允许带走任何东西——UI 应隐藏"可复用参数"整块，
    /// 而不是显示一个空卡片。
    public var isEmpty: Bool {
        prompt == nil && negativePrompt == nil && seed == nil && styleTags.isEmpty && extra.isEmpty
    }
}

/// 当前发布版本的摘要，嵌在 `WorkDetail.currentVersion` 里。
public struct WorkVersionSummary: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let versionNumber: Int
    public let title: String
    public let description: String?
    public let coverURL: String?
    public let mediaURL: String?
    public let mediaType: MediaType?
    public let aiGenerated: Bool
    public let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case id
        case versionNumber = "version_number"
        case title
        case description
        case coverURL = "cover_url"
        case mediaURL = "media_url"
        case mediaType = "media_type"
        case aiGenerated = "ai_generated"
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        versionNumber = try c.decode(Int.self, forKey: .versionNumber)
        title = try c.decode(String.self, forKey: .title)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        coverURL = try c.decodeIfPresent(String.self, forKey: .coverURL)
        mediaURL = try c.decodeIfPresent(String.self, forKey: .mediaURL)
        mediaType = try c.decodeIfPresent(MediaType.self, forKey: .mediaType)
        aiGenerated = try c.decodeIfPresent(Bool.self, forKey: .aiGenerated) ?? true
        createdAt = try c.decode(Date.self, forKey: .createdAt)
    }
}

/// 瀑布墙 / 网格用的卡片投影。发现页、个人主页、我的库都吃这个类型。
public struct WorkSummary: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let title: String
    public let visibility: RawOrUnknown<Visibility>
    public let lifecycleStatus: RawOrUnknown<LifecycleStatus>
    public let coverURL: String?
    public let coverWidth: Int?
    public let coverHeight: Int?
    public let mediaType: MediaType?
    public let author: AuthorSummary
    public let stats: WorkStats
    public let tags: [String]
    public let remixable: Bool
    public let publishedAt: Date?

    private enum CodingKeys: String, CodingKey {
        case id, title, visibility
        case lifecycleStatus = "lifecycle_status"
        case coverURL = "cover_url"
        case coverWidth = "cover_width"
        case coverHeight = "cover_height"
        case mediaType = "media_type"
        case author, stats, tags, remixable
        case publishedAt = "published_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        visibility = try c.decode(RawOrUnknown<Visibility>.self, forKey: .visibility)
        lifecycleStatus = try c.decode(RawOrUnknown<LifecycleStatus>.self, forKey: .lifecycleStatus)
        coverURL = try c.decodeIfPresent(String.self, forKey: .coverURL)
        coverWidth = try c.decodeIfPresent(Int.self, forKey: .coverWidth)
        coverHeight = try c.decodeIfPresent(Int.self, forKey: .coverHeight)
        mediaType = try c.decodeIfPresent(MediaType.self, forKey: .mediaType)
        author = try c.decode(AuthorSummary.self, forKey: .author)
        stats = try c.decodeIfPresent(WorkStats.self, forKey: .stats) ?? .zero
        tags = try c.decodeIfPresent([String].self, forKey: .tags) ?? []
        remixable = try c.decodeIfPresent(Bool.self, forKey: .remixable) ?? false
        publishedAt = try c.decodeIfPresent(Date.self, forKey: .publishedAt)
    }

    /// 瀑布墙按封面真实宽高比排版；后端没给尺寸时退回 3:4，避免除零或布局塌陷。
    public var coverAspectRatio: Double {
        guard let w = coverWidth, let h = coverHeight, w > 0, h > 0 else { return 3.0 / 4.0 }
        return Double(w) / Double(h)
    }

    public var isTombstoned: Bool { lifecycleStatus.value == .tombstone }
}

/// 作品详情页的完整投影：`WorkSummary` 的全部字段 + 描述、当前版本、许可、创作链摘要。
public struct WorkDetail: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let title: String
    public let visibility: RawOrUnknown<Visibility>
    public let lifecycleStatus: RawOrUnknown<LifecycleStatus>
    public let coverURL: String?
    public let coverWidth: Int?
    public let coverHeight: Int?
    public let mediaType: MediaType?
    public let author: AuthorSummary
    public let stats: WorkStats
    public let tags: [String]
    public let remixable: Bool
    public let publishedAt: Date?
    public let description: String?
    public let currentVersion: WorkVersionSummary?
    public let reusableParams: ReusableParams?
    public let license: LicenseInfo?
    public let ancestors: [LineageAncestor]
    public let descendantCount: Int
    public let viewerLiked: Bool
    public let viewerBookmarked: Bool
    public let canRemix: Bool
    public let remixBlockReason: String?

    private enum CodingKeys: String, CodingKey {
        case id, title, visibility
        case lifecycleStatus = "lifecycle_status"
        case coverURL = "cover_url"
        case coverWidth = "cover_width"
        case coverHeight = "cover_height"
        case mediaType = "media_type"
        case author, stats, tags, remixable
        case publishedAt = "published_at"
        case description
        case currentVersion = "current_version"
        case reusableParams = "reusable_params"
        case license
        case ancestors
        case descendantCount = "descendant_count"
        case viewerLiked = "viewer_liked"
        case viewerBookmarked = "viewer_bookmarked"
        case canRemix = "can_remix"
        case remixBlockReason = "remix_block_reason"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        visibility = try c.decode(RawOrUnknown<Visibility>.self, forKey: .visibility)
        lifecycleStatus = try c.decode(RawOrUnknown<LifecycleStatus>.self, forKey: .lifecycleStatus)
        coverURL = try c.decodeIfPresent(String.self, forKey: .coverURL)
        coverWidth = try c.decodeIfPresent(Int.self, forKey: .coverWidth)
        coverHeight = try c.decodeIfPresent(Int.self, forKey: .coverHeight)
        mediaType = try c.decodeIfPresent(MediaType.self, forKey: .mediaType)
        author = try c.decode(AuthorSummary.self, forKey: .author)
        stats = try c.decodeIfPresent(WorkStats.self, forKey: .stats) ?? .zero
        tags = try c.decodeIfPresent([String].self, forKey: .tags) ?? []
        remixable = try c.decodeIfPresent(Bool.self, forKey: .remixable) ?? false
        publishedAt = try c.decodeIfPresent(Date.self, forKey: .publishedAt)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        currentVersion = try c.decodeIfPresent(WorkVersionSummary.self, forKey: .currentVersion)
        reusableParams = try c.decodeIfPresent(ReusableParams.self, forKey: .reusableParams)
        license = try c.decodeIfPresent(LicenseInfo.self, forKey: .license)
        ancestors = try c.decodeIfPresent([LineageAncestor].self, forKey: .ancestors) ?? []
        descendantCount = try c.decodeIfPresent(Int.self, forKey: .descendantCount) ?? 0
        viewerLiked = try c.decodeIfPresent(Bool.self, forKey: .viewerLiked) ?? false
        viewerBookmarked = try c.decodeIfPresent(Bool.self, forKey: .viewerBookmarked) ?? false
        canRemix = try c.decodeIfPresent(Bool.self, forKey: .canRemix) ?? false
        remixBlockReason = try c.decodeIfPresent(String.self, forKey: .remixBlockReason)
    }

    public var coverAspectRatio: Double {
        guard let w = coverWidth, let h = coverHeight, w > 0, h > 0 else { return 16.0 / 9.0 }
        return Double(w) / Double(h)
    }

    public var isTombstoned: Bool { lifecycleStatus.value == .tombstone }
}

/// 标签的三语标签由后端一次给全，客户端按自己的语言选一个，一份响应服务多语言。
public struct TagResponse: Codable, Sendable, Equatable, Identifiable {
    public var id: String { slug }
    public let slug: String
    public let labelZH: String
    public let labelEN: String
    public let labelJA: String
    public let usageCount: Int

    private enum CodingKeys: String, CodingKey {
        case slug
        case labelZH = "label_zh"
        case labelEN = "label_en"
        case labelJA = "label_ja"
        case usageCount = "usage_count"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        slug = try c.decode(String.self, forKey: .slug)
        labelZH = try c.decode(String.self, forKey: .labelZH)
        labelEN = try c.decode(String.self, forKey: .labelEN)
        labelJA = try c.decode(String.self, forKey: .labelJA)
        usageCount = try c.decodeIfPresent(Int.self, forKey: .usageCount) ?? 0
    }

    /// 按 `AppLocale` 选对应语言的标签文案。
    public func label(for locale: AppLocale) -> String {
        switch locale {
        case .zhCN: labelZH
        case .en: labelEN
        case .ja: labelJA
        }
    }
}

/// 发现页排序方式，对应 `GET /v1/works?sort=`。
public enum WorksSort: String, Codable, Sendable, CaseIterable {
    case recent
    case popular
    case remixed
}
