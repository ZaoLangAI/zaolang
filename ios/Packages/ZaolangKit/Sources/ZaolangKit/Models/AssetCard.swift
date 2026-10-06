import Foundation

/// The three library card kinds behind 角色创作 / 场景创作 / 道具创作 —
/// `card_kind` on `GET /v1/{characters,scenes,props}/{id}/graph`.
public enum AssetCardKind: String, Codable, Sendable, CaseIterable, Hashable {
    case character
    case scene
    case prop

    /// The collection segment: `/v1/<segment>` on the API, `/create/<segment>` on the web.
    public var segment: String {
        switch self {
        case .character: "characters"
        case .scene: "scenes"
        case .prop: "props"
        }
    }

    /// The `asset_kind` an image job for this card carries.
    public var imageAssetKind: ImageAssetKind {
        switch self {
        case .character: .character
        case .scene: .scene
        case .prop: .prop
        }
    }
}

/// A camera viewpoint relative to the subject (`back/app/domain/image_assets/camera.py`):
/// azimuth 0 = facing the camera, 90 = its right side, 180 = its back (a
/// scene's reverse shot), 270 = its left; elevation in degrees; distance
/// `close` | `medium` | `wide`.
public struct CameraPose: Codable, Sendable, Equatable, Hashable {
    public let azimuth: Int
    public let elevation: Int
    public let distance: String

    public init(azimuth: Int, elevation: Int = 0, distance: String = "medium") {
        self.azimuth = azimuth
        self.elevation = elevation
        self.distance = distance
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        azimuth = try c.decode(Int.self, forKey: .azimuth)
        elevation = try c.decodeIfPresent(Int.self, forKey: .elevation) ?? 0
        distance = try c.decodeIfPresent(String.self, forKey: .distance) ?? "medium"
    }

    private enum CodingKeys: String, CodingKey {
        case azimuth, elevation, distance
    }
}
