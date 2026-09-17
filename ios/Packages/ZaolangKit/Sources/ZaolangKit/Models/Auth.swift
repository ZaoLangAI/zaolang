import Foundation

/// 嵌在 `MeResponse.profile` 里的资料，注意 `reduceMotion` 在这一层，不在顶层。
public struct ProfileResponse: Codable, Sendable, Equatable {
    public let displayName: String
    public let handle: String
    public let bio: String?
    public let location: String?
    public let avatarAssetID: String?
    public let coverAssetID: String?
    public let publicProfile: Bool
    public let notifyOnRemix: Bool
    public let reduceMotion: Bool

    private enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case handle, bio, location
        case avatarAssetID = "avatar_asset_id"
        case coverAssetID = "cover_asset_id"
        case publicProfile = "public_profile"
        case notifyOnRemix = "notify_on_remix"
        case reduceMotion = "reduce_motion"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        displayName = try c.decode(String.self, forKey: .displayName)
        handle = try c.decode(String.self, forKey: .handle)
        bio = try c.decodeIfPresent(String.self, forKey: .bio)
        location = try c.decodeIfPresent(String.self, forKey: .location)
        avatarAssetID = try c.decodeIfPresent(String.self, forKey: .avatarAssetID)
        coverAssetID = try c.decodeIfPresent(String.self, forKey: .coverAssetID)
        publicProfile = try c.decodeIfPresent(Bool.self, forKey: .publicProfile) ?? true
        notifyOnRemix = try c.decodeIfPresent(Bool.self, forKey: .notifyOnRemix) ?? true
        reduceMotion = try c.decodeIfPresent(Bool.self, forKey: .reduceMotion) ?? false
    }
}

/// `GET /v1/auth/me`。`theme` / `locale` / `region` 在顶层；`reduceMotion` 在 `profile` 里——
/// 两处归属不同，读的时候别弄混。
public struct MeResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let email: String
    public let roles: [String]
    public let status: String
    public let region: RawOrUnknown<Region>
    public let locale: RawOrUnknown<AppLocale>
    public let theme: RawOrUnknown<ThemePreference>
    public let ageGateConfirmed: Bool
    public let profile: ProfileResponse?
    public let availableCredits: Int
    public let reservedCredits: Int

    private enum CodingKeys: String, CodingKey {
        case id, email, roles, status, region, locale, theme
        case ageGateConfirmed = "age_gate_confirmed"
        case profile
        case availableCredits = "available_credits"
        case reservedCredits = "reserved_credits"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        email = try c.decode(String.self, forKey: .email)
        roles = try c.decodeIfPresent([String].self, forKey: .roles) ?? []
        status = try c.decode(String.self, forKey: .status)
        region = try c.decode(RawOrUnknown<Region>.self, forKey: .region)
        locale = try c.decode(RawOrUnknown<AppLocale>.self, forKey: .locale)
        theme = try c.decode(RawOrUnknown<ThemePreference>.self, forKey: .theme)
        ageGateConfirmed = try c.decode(Bool.self, forKey: .ageGateConfirmed)
        profile = try c.decodeIfPresent(ProfileResponse.self, forKey: .profile)
        availableCredits = try c.decodeIfPresent(Int.self, forKey: .availableCredits) ?? 0
        reservedCredits = try c.decodeIfPresent(Int.self, forKey: .reservedCredits) ?? 0
    }

    /// 无障碍规则要求"系统减少动效 **或** 服务端偏好任一为真就收敛动画"，
    /// `reduceMotion` 只是服务端那一半，系统那一半在 App 层的 `zlMotion` 环境值里判断。
    public var reduceMotionPreference: Bool { profile?.reduceMotion ?? false }
}

/// `POST /v1/auth/login|register|refresh` 的响应；`refresh_token` 本身不在这里——
/// 它随 `Set-Cookie: zl_refresh=...` 走，由 `Session/CookieCodec.swift` 单独解析。
public struct TokenResponse: Codable, Sendable, Equatable {
    public let accessToken: String
    public let tokenType: String
    public let expiresAt: Date

    private enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case tokenType = "token_type"
        case expiresAt = "expires_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        accessToken = try c.decode(String.self, forKey: .accessToken)
        tokenType = try c.decodeIfPresent(String.self, forKey: .tokenType) ?? "Bearer"
        expiresAt = try c.decode(Date.self, forKey: .expiresAt)
    }
}

/// `POST /v1/auth/login` 请求体。
public struct LoginRequest: Encodable, Sendable {
    public var email: String
    public var password: String

    public init(email: String, password: String) {
        self.email = email
        self.password = password
    }
}

/// `POST /v1/auth/register` 请求体。`handle` 只允许 `[a-z0-9_]`，与后端 `pattern` 校验一致，
/// 客户端先做一次同样的校验能省一趟往返。
public struct RegisterRequest: Encodable, Sendable {
    public var email: String
    public var password: String
    public var displayName: String
    public var handle: String
    public var region: Region
    public var locale: AppLocale
    public var ageConfirmed: Bool

    public init(
        email: String,
        password: String,
        displayName: String,
        handle: String,
        region: Region,
        locale: AppLocale,
        ageConfirmed: Bool
    ) {
        self.email = email
        self.password = password
        self.displayName = displayName
        self.handle = handle
        self.region = region
        self.locale = locale
        self.ageConfirmed = ageConfirmed
    }

    private enum CodingKeys: String, CodingKey {
        case email, password
        case displayName = "display_name"
        case handle, region, locale
        case ageConfirmed = "age_confirmed"
    }
}

/// `PATCH /v1/auth/me/preferences` 的请求体，M1 不写但先落地供 M2 复用。
public struct PreferencesRequest: Codable, Sendable {
    public var region: Region?
    public var locale: AppLocale?
    public var theme: ThemePreference?
    public var reduceMotion: Bool?
    public var notifyOnRemix: Bool?

    public init(
        region: Region? = nil,
        locale: AppLocale? = nil,
        theme: ThemePreference? = nil,
        reduceMotion: Bool? = nil,
        notifyOnRemix: Bool? = nil
    ) {
        self.region = region
        self.locale = locale
        self.theme = theme
        self.reduceMotion = reduceMotion
        self.notifyOnRemix = notifyOnRemix
    }

    private enum CodingKeys: String, CodingKey {
        case region, locale, theme
        case reduceMotion = "reduce_motion"
        case notifyOnRemix = "notify_on_remix"
    }
}

/// `PATCH /v1/auth/me/profile` 的请求体。`nil` 字段表示"不改这一项"，
/// 不是"清空这一项"——`bio`/`location` 想清空要传空字符串而不是 nil。
public struct ProfileUpdateRequest: Encodable, Sendable {
    public var displayName: String?
    public var bio: String?
    public var location: String?
    public var avatarAssetID: String?
    public var coverAssetID: String?
    public var publicProfile: Bool?

    public init(
        displayName: String? = nil,
        bio: String? = nil,
        location: String? = nil,
        avatarAssetID: String? = nil,
        coverAssetID: String? = nil,
        publicProfile: Bool? = nil
    ) {
        self.displayName = displayName
        self.bio = bio
        self.location = location
        self.avatarAssetID = avatarAssetID
        self.coverAssetID = coverAssetID
        self.publicProfile = publicProfile
    }

    private enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case bio, location
        case avatarAssetID = "avatar_asset_id"
        case coverAssetID = "cover_asset_id"
        case publicProfile = "public_profile"
    }
}
