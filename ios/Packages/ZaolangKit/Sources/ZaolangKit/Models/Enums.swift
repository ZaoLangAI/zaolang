import Foundation

// 全部取值以 `back/app/models/enums.py` 为准，不在客户端另立一套。
//
// 每个枚举都实现 `unknownCase`（若有）或整体降级为可选，这样后端新增取值时
// 老版本 App 不会直接解码失败崩溃——只是这一项显示不出来。

/// 作品可见性。`publicViewOnly` 是产品强制的默认值。
public enum Visibility: String, Codable, Sendable, CaseIterable {
    case publicRemixable = "public_remixable"
    case publicViewOnly = "public_view_only"
    case `private` = "private"

    public var allowsRemix: Bool { self == .publicRemixable }
}

/// 作品从不硬删除，下架也要保留墓碑节点让创作链可解析。
public enum LifecycleStatus: String, Codable, Sendable, CaseIterable {
    case active
    case hidden
    case tombstone
}

public enum MediaType: String, Codable, Sendable, CaseIterable {
    case image
    case video
    case audio
}

public enum QualityTier: String, Codable, Sendable, CaseIterable {
    case preview
    case standard
    case cinematic
}

public enum Operation: String, Codable, Sendable, CaseIterable {
    case textToImage = "text_to_image"
    case textToVideo = "text_to_video"
    case imageToVideo = "image_to_video"
    case videoToVideo = "video_to_video"

    public var isVideo: Bool {
        switch self {
        case .textToVideo, .imageToVideo, .videoToVideo: true
        case .textToImage: false
        }
    }
}

public enum JobStatus: String, Codable, Sendable, CaseIterable {
    case created
    case queued
    case submitted
    case running
    case succeeded
    case failed
    case cancelled
    case expired

    public var isTerminal: Bool {
        switch self {
        case .succeeded, .failed, .cancelled, .expired: true
        case .created, .queued, .submitted, .running: false
        }
    }

    public var isCancellable: Bool {
        switch self {
        case .created, .queued, .submitted, .running: true
        case .succeeded, .failed, .cancelled, .expired: false
        }
    }
}

public enum LicenseType: String, Codable, Sendable, CaseIterable {
    case ccBy40 = "cc_by_4.0"
    case ccBySa40 = "cc_by_sa_4.0"
    case ccByNc40 = "cc_by_nc_4.0"
    case allRightsReserved = "all_rights_reserved"
}

public enum NotificationType: String, Codable, Sendable, CaseIterable {
    case jobProgress = "job_progress"
    case jobSucceeded = "job_succeeded"
    case jobFailed = "job_failed"
    case workLiked = "work_liked"
    case workRemixed = "work_remixed"
    case royaltyReceived = "royalty_received"
    case newFollower = "new_follower"
    case moderation
    case system
}

public enum LedgerEntryType: String, Codable, Sendable, CaseIterable {
    case grant
    case purchase
    case reserve
    case capture
    case release
    case refund
    case adjustment
    case royaltyOut = "royalty_out"
    case royaltyIn = "royalty_in"
}

public enum Region: String, Codable, Sendable, CaseIterable {
    case cn = "CN"
    case global = "GLOBAL"
    case jp = "JP"
}

/// 与后端 `Locale` 枚举同名；避免与 `Foundation.Locale` 混淆，使用处一律写 `ZaolangKit.AppLocale`。
public enum AppLocale: String, Codable, Sendable, CaseIterable {
    case zhCN = "zh-CN"
    case en
    case ja
}

public enum ThemePreference: String, Codable, Sendable, CaseIterable {
    case system
    case dark
    case light
}

public enum DataRequestType: String, Codable, Sendable, CaseIterable {
    case export
    case delete
}

public enum DataRequestStatus: String, Codable, Sendable, CaseIterable {
    case pending
    case approved
    case rejected
    case completed
}

public enum ReportReason: String, Codable, Sendable, CaseIterable {
    case copyright
    case sexualContent = "sexual_content"
    case violence
    case hate
    case minorSafety = "minor_safety"
    case fraud
    case other
}

/// 后端未知取值不应崩溃整条解码链路：包一层 `RawOrUnknown` 兜底。
///
/// 用于枚举字段可能被后端扩展、但客户端只需要"认得就用、不认得就降级"的场景，
/// 例如创作链节点里的 `author` 是自由 object，或未来新增的许可类型。
public enum RawOrUnknown<T: RawRepresentable & Codable & Sendable & Equatable>: Codable, Sendable, Equatable where T.RawValue == String {
    case known(T)
    case unknown(String)

    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = T(rawValue: raw).map(Self.known) ?? .unknown(raw)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .known(let value): try container.encode(value.rawValue)
        case .unknown(let raw): try container.encode(raw)
        }
    }

    public var value: T? {
        if case .known(let v) = self { return v }
        return nil
    }
}
