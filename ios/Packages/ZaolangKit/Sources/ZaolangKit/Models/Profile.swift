import Foundation

/// `GET /v1/profiles/{handle}` 的响应：他人可见的公开主页。
public struct PublicProfileResponse: Codable, Sendable, Equatable, Identifiable {
    public var id: String { userID }
    public let userID: String
    public let handle: String
    public let displayName: String
    public let bio: String?
    public let location: String?
    public let avatarURL: String?
    public let coverURL: String?
    public let workCount: Int
    public let followerCount: Int
    public let followingCount: Int
    public let viewerFollowing: Bool
    public let isSelf: Bool

    private enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case handle
        case displayName = "display_name"
        case bio, location
        case avatarURL = "avatar_url"
        case coverURL = "cover_url"
        case workCount = "work_count"
        case followerCount = "follower_count"
        case followingCount = "following_count"
        case viewerFollowing = "viewer_following"
        case isSelf = "is_self"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        userID = try c.decode(String.self, forKey: .userID)
        handle = try c.decode(String.self, forKey: .handle)
        displayName = try c.decode(String.self, forKey: .displayName)
        bio = try c.decodeIfPresent(String.self, forKey: .bio)
        location = try c.decodeIfPresent(String.self, forKey: .location)
        avatarURL = try c.decodeIfPresent(String.self, forKey: .avatarURL)
        coverURL = try c.decodeIfPresent(String.self, forKey: .coverURL)
        workCount = try c.decodeIfPresent(Int.self, forKey: .workCount) ?? 0
        followerCount = try c.decodeIfPresent(Int.self, forKey: .followerCount) ?? 0
        followingCount = try c.decodeIfPresent(Int.self, forKey: .followingCount) ?? 0
        viewerFollowing = try c.decodeIfPresent(Bool.self, forKey: .viewerFollowing) ?? false
        isSelf = try c.decodeIfPresent(Bool.self, forKey: .isSelf) ?? false
    }
}
