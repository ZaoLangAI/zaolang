import Foundation

public struct OkResponse: Codable, Sendable, Equatable {
    public let ok: Bool
    public init(ok: Bool = true) { self.ok = ok }
}

public struct CountResponse: Codable, Sendable, Equatable {
    public let count: Int
}

public struct NotificationResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let type: RawOrUnknown<NotificationType>
    public let titleKey: String
    public let payload: [String: JSONValue]
    public let targetType: String?
    public let targetID: String?
    public let read: Bool
    public let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case id, type
        case titleKey = "title_key"
        case payload
        case targetType = "target_type"
        case targetID = "target_id"
        case read
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        type = try c.decode(RawOrUnknown<NotificationType>.self, forKey: .type)
        titleKey = try c.decode(String.self, forKey: .titleKey)
        payload = try c.decodeIfPresent([String: JSONValue].self, forKey: .payload) ?? [:]
        targetType = try c.decodeIfPresent(String.self, forKey: .targetType)
        targetID = try c.decodeIfPresent(String.self, forKey: .targetID)
        read = try c.decodeIfPresent(Bool.self, forKey: .read) ?? false
        createdAt = try c.decode(Date.self, forKey: .createdAt)
    }
}

public struct CollectionCreateRequest: Encodable, Sendable {
    public var name: String
    public var description: String?
    public var isPublic: Bool

    public init(name: String, description: String? = nil, isPublic: Bool = true) {
        self.name = name
        self.description = description
        self.isPublic = isPublic
    }

    private enum CodingKeys: String, CodingKey {
        case name, description
        case isPublic = "is_public"
    }
}

public struct CollectionResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let description: String?
    public let isPublic: Bool
    public let itemCount: Int
    public let coverURLs: [String]

    private enum CodingKeys: String, CodingKey {
        case id, name, description
        case isPublic = "is_public"
        case itemCount = "item_count"
        case coverURLs = "cover_urls"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        isPublic = try c.decode(Bool.self, forKey: .isPublic)
        itemCount = try c.decodeIfPresent(Int.self, forKey: .itemCount) ?? 0
        coverURLs = try c.decodeIfPresent([String].self, forKey: .coverURLs) ?? []
    }
}

public struct ReportCreateRequest: Encodable, Sendable {
    public var subjectType: String
    public var subjectID: String
    public var reason: ReportReason
    public var detail: String?

    public init(subjectType: String, subjectID: String, reason: ReportReason, detail: String? = nil) {
        self.subjectType = subjectType
        self.subjectID = subjectID
        self.reason = reason
        self.detail = detail
    }

    private enum CodingKeys: String, CodingKey {
        case subjectType = "subject_type"
        case subjectID = "subject_id"
        case reason, detail
    }
}

/// `POST /v1/me/devices`：只在拿到 APNs device token 后调用一次；重装 App 换新 token 会
/// 落一条新行，旧行不用客户端清理。
public struct DeviceRegisterRequest: Encodable, Sendable {
    public var pushToken: String
    public var platform: String
    public var locale: String

    public init(pushToken: String, platform: String = "ios", locale: String) {
        self.pushToken = pushToken
        self.platform = platform
        self.locale = locale
    }

    private enum CodingKeys: String, CodingKey {
        case pushToken = "push_token"
        case platform, locale
    }
}

public struct DeviceResponse: Codable, Sendable, Equatable {
    public let id: String
    public let platform: String
    public let locale: String
}

public struct DataRequestCreateRequest: Encodable, Sendable {
    public var type: DataRequestType
    public var reason: String?

    public init(type: DataRequestType, reason: String? = nil) {
        self.type = type
        self.reason = reason
    }
}

public struct MyDataRequestResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let type: RawOrUnknown<DataRequestType>
    public let status: RawOrUnknown<DataRequestStatus>
    public let reason: String?
    public let createdAt: Date
    public let handledAt: Date?
    public let downloadURL: String?

    private enum CodingKeys: String, CodingKey {
        case id, type, status, reason
        case createdAt = "created_at"
        case handledAt = "handled_at"
        case downloadURL = "download_url"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        type = try c.decode(RawOrUnknown<DataRequestType>.self, forKey: .type)
        status = try c.decode(RawOrUnknown<DataRequestStatus>.self, forKey: .status)
        reason = try c.decodeIfPresent(String.self, forKey: .reason)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        handledAt = try c.decodeIfPresent(Date.self, forKey: .handledAt)
        downloadURL = try c.decodeIfPresent(String.self, forKey: .downloadURL)
    }
}

public struct CreditBalanceResponse: Codable, Sendable, Equatable {
    public let available: Int
    public let reserved: Int
    public let currency: String
}

public struct LedgerEntryResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let type: RawOrUnknown<LedgerEntryType>
    public let amount: Int
    public let balanceAfter: Int
    public let jobID: String?
    public let reason: String?
    public let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case id, type, amount
        case balanceAfter = "balance_after"
        case jobID = "job_id"
        case reason
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        type = try c.decode(RawOrUnknown<LedgerEntryType>.self, forKey: .type)
        amount = try c.decode(Int.self, forKey: .amount)
        balanceAfter = try c.decode(Int.self, forKey: .balanceAfter)
        jobID = try c.decodeIfPresent(String.self, forKey: .jobID)
        reason = try c.decodeIfPresent(String.self, forKey: .reason)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
    }
}

/// 只读展示用；本客户端不接 `POST /v1/credits/checkout`（产品决策：不接 StoreKit，
/// 余额不足引导去网页版购买，见 `zaolang-ios-client` skill 的路线图）。
public struct CreditPackageResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let slug: String
    public let credits: Int
    public let bonusCredits: Int
    public let priceMinor: Int
    public let currency: String
    public let region: String

    private enum CodingKeys: String, CodingKey {
        case id, slug, credits
        case bonusCredits = "bonus_credits"
        case priceMinor = "price_minor"
        case currency, region
    }
}
