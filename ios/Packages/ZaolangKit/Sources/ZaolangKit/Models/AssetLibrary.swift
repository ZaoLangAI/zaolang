import Foundation

/// A single reference image on a character skill or a scene, tagged by
/// `view` (an `ImageAssetKind` value on the character side, a lighter scene
/// label on the scene side — both are free strings server-side, so this
/// wraps a plain `String` rather than the closed `ImageAssetKind` enum).
public struct LibraryReferenceAsset: Codable, Sendable, Equatable, Identifiable {
    public let assetID: String
    public let view: String
    public let label: String?
    public let url: String?
    public let createdAt: Date?

    public var id: String { assetID }

    private enum CodingKeys: String, CodingKey {
        case assetID = "asset_id"
        case view, label, url
        case createdAt = "created_at"
    }
}

/// A character in the creator's library. Since `character-into-skill-library`,
/// this is a `CreationSkill` (`category=character`) under the hood — see
/// `back/app/api/schemas/characters.py::CharacterResponse` — but the app only
/// needs the read-only shape here (list + pick), not the full skill lifecycle.
public struct CharacterResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let description: String?
    public let referenceAssets: [LibraryReferenceAsset]
    public let voiceDescription: String?

    private enum CodingKeys: String, CodingKey {
        case id, name, description
        case referenceAssets = "reference_assets"
        case voiceDescription = "voice_description"
    }

    /// The character's front view, if it has one — what the "补全侧面/背面"
    /// completion action borrows so the side/back stay recognisably the
    /// same person (mirrors the web character library's `completeViews`).
    public var frontReference: LibraryReferenceAsset? {
        referenceAssets.first { $0.view == CharacterViewAngle.front.rawValue }
    }

    public var sideReference: LibraryReferenceAsset? {
        referenceAssets.first { $0.view == CharacterViewAngle.side.rawValue }
    }

    public var backReference: LibraryReferenceAsset? {
        referenceAssets.first { $0.view == CharacterViewAngle.back.rawValue }
    }

    /// Guided step two: shown once a front view exists and either the side
    /// or back is still missing (mirrors the web library's
    /// `canCompleteViews`).
    public var canCompleteViews: Bool {
        frontReference != nil && (sideReference == nil || backReference == nil)
    }
}

public struct CharacterCreateRequest: Encodable, Sendable {
    public var name: String
    public var description: String?

    public init(name: String, description: String? = nil) {
        self.name = name
        self.description = description
    }
}

/// A scene in the creator's library — mirrors `back/app/api/schemas/scenes.py::SceneResponse`.
public struct SceneResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let description: String?
    public let referenceAssets: [LibraryReferenceAsset]

    private enum CodingKeys: String, CodingKey {
        case id, name, description
        case referenceAssets = "reference_assets"
    }
}

public struct SceneCreateRequest: Encodable, Sendable {
    public var name: String
    public var description: String?

    public init(name: String, description: String? = nil) {
        self.name = name
        self.description = description
    }
}
