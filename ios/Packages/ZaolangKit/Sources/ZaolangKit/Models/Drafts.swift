import Foundation

public struct DraftCreateRequest: Encodable, Sendable {
    public var sourceWorkID: String?
    public var title: String?
    public var params: [String: JSONValue]

    public init(sourceWorkID: String? = nil, title: String? = nil, params: [String: JSONValue] = [:]) {
        self.sourceWorkID = sourceWorkID
        self.title = title
        self.params = params
    }

    private enum CodingKeys: String, CodingKey {
        case sourceWorkID = "source_work_id"
        case title, params
    }
}

/// 工作台的落地状态：新建走 `sourceWorkVersionID == nil`，二创非 nil——与 `GenerationJobCreateRequest`
/// 里 `sourceWorkID` 的两态判断是同一条产品规则，只是这里存的是版本 id 不是作品 id。
public struct DraftResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let sourceWorkVersionID: String?
    public let title: String?
    public let description: String?
    public let params: [String: JSONValue]
    public let license: LicenseInfo?
    public let latestJobID: String?
    public let outputAssetID: String?
    public let outputURL: String?
    public let publishedWorkID: String?
    public let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case id
        case sourceWorkVersionID = "source_work_version_id"
        case title, description, params, license
        case latestJobID = "latest_job_id"
        case outputAssetID = "output_asset_id"
        case outputURL = "output_url"
        case publishedWorkID = "published_work_id"
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        sourceWorkVersionID = try c.decodeIfPresent(String.self, forKey: .sourceWorkVersionID)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        params = try c.decodeIfPresent([String: JSONValue].self, forKey: .params) ?? [:]
        license = try c.decodeIfPresent(LicenseInfo.self, forKey: .license)
        latestJobID = try c.decodeIfPresent(String.self, forKey: .latestJobID)
        outputAssetID = try c.decodeIfPresent(String.self, forKey: .outputAssetID)
        outputURL = try c.decodeIfPresent(String.self, forKey: .outputURL)
        publishedWorkID = try c.decodeIfPresent(String.self, forKey: .publishedWorkID)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
    }

    public var isRemix: Bool { sourceWorkVersionID != nil }
}

/// `POST /v1/drafts/{id}/publish` 请求体。`visibility` 默认 `publicViewOnly`，
/// 两个确认框默认不勾——发布页的确认状态在 UI 层维护，提交前必须都为 true。
public struct PublishRequest: Encodable, Sendable {
    public var title: String
    public var description: String?
    public var visibility: Visibility
    public var tags: [String]
    public var coverAssetID: String?
    public var rightsConfirmed: Bool
    public var aiDisclosureConfirmed: Bool

    public init(
        title: String,
        description: String? = nil,
        visibility: Visibility = .publicViewOnly,
        tags: [String] = [],
        coverAssetID: String? = nil,
        rightsConfirmed: Bool = false,
        aiDisclosureConfirmed: Bool = false
    ) {
        self.title = title
        self.description = description
        self.visibility = visibility
        self.tags = tags
        self.coverAssetID = coverAssetID
        self.rightsConfirmed = rightsConfirmed
        self.aiDisclosureConfirmed = aiDisclosureConfirmed
    }

    private enum CodingKeys: String, CodingKey {
        case title, description, visibility, tags
        case coverAssetID = "cover_asset_id"
        case rightsConfirmed = "rights_confirmed"
        case aiDisclosureConfirmed = "ai_disclosure_confirmed"
    }
}

public struct PublishResponse: Codable, Sendable, Equatable {
    public let workID: String
    public let workVersionID: String
    public let visibility: RawOrUnknown<Visibility>
    public let lineageEdgeID: String?
    public let royaltiesPaid: [JSONValue]

    private enum CodingKeys: String, CodingKey {
        case workID = "work_id"
        case workVersionID = "work_version_id"
        case visibility
        case lineageEdgeID = "lineage_edge_id"
        case royaltiesPaid = "royalties_paid"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        workID = try c.decode(String.self, forKey: .workID)
        workVersionID = try c.decode(String.self, forKey: .workVersionID)
        visibility = try c.decode(RawOrUnknown<Visibility>.self, forKey: .visibility)
        lineageEdgeID = try c.decodeIfPresent(String.self, forKey: .lineageEdgeID)
        royaltiesPaid = try c.decodeIfPresent([JSONValue].self, forKey: .royaltiesPaid) ?? []
    }
}

public struct VisibilityUpdateRequest: Encodable, Sendable {
    public var visibility: Visibility

    public init(visibility: Visibility) {
        self.visibility = visibility
    }
}
