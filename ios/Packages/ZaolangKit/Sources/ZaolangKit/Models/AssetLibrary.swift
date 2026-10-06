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
/// needs the read-only list shape here, not the full skill lifecycle.
public struct CharacterResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let description: String?
    public let referenceAssets: [LibraryReferenceAsset]
    public let voiceDescription: String?
    /// Looks with their images (absent in older payloads).
    public let looks: [AssetVariantView]?
    public let anchorEntryID: String?
    /// The server's pick of the same image (absent in older payloads; the
    /// only source in a `?view=summary` list).
    public let heroUrl: String?

    private enum CodingKeys: String, CodingKey {
        case id, name, description, looks
        case referenceAssets = "reference_assets"
        case voiceDescription = "voice_description"
        case anchorEntryID = "anchor_entry_id"
        case heroUrl = "hero_url"
    }

    /// What a library row leads with — the approved anchor, else the
    /// approved identity portrait, else the legacy front sheet (mirrors the
    /// web `characterHeroUrl`).
    public var heroURL: String? {
        if let heroUrl { return heroUrl }
        let approved = (looks ?? []).flatMap(\.entries).filter { !$0.isCandidate && $0.url != nil }
        if let anchor = approved.first(where: { $0.id == anchorEntryID }) { return anchor.url }
        if let portrait = approved.first(where: { $0.entryType == "identity_portrait" }) { return portrait.url }
        return (referenceAssets.first { $0.view == CharacterViewAngle.front.rawValue } ?? referenceAssets.first)?.url
    }
}

/// A scene in the creator's library — mirrors `back/app/api/schemas/scenes.py::SceneResponse`.
public struct SceneResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let description: String?
    public let referenceAssets: [LibraryReferenceAsset]
    /// Variants with their images (empty in a `?view=summary` list).
    public let variants: [AssetVariantView]
    public let anchorEntryID: String?

    private enum CodingKeys: String, CodingKey {
        case id, name, description, variants
        case referenceAssets = "reference_assets"
        case anchorEntryID = "anchor_entry_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        referenceAssets = try c.decodeIfPresent([LibraryReferenceAsset].self, forKey: .referenceAssets) ?? []
        variants = try c.decodeIfPresent([AssetVariantView].self, forKey: .variants) ?? []
        anchorEntryID = try c.decodeIfPresent(String.self, forKey: .anchorEntryID)
    }

    /// The master plate a row leads with: an explicit establishing tag, else
    /// the first unlabelled asset, else the first (mirrors web `sceneHeroAsset`).
    public var heroURL: String? {
        (referenceAssets.first { $0.view == "establishing" }
            ?? referenceAssets.first { ($0.label ?? "").trimmingCharacters(in: .whitespaces).isEmpty }
            ?? referenceAssets.first)?.url
    }
}

/// A prop in the creator's library (道具创作, AC-4) — mirrors
/// `back/app/api/schemas/props.py::PropResponse`.
public struct PropResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let description: String?
    public let referenceAssets: [LibraryReferenceAsset]
    /// Conditions (道具状态) with their images.
    public let variants: [AssetVariantView]
    public let anchorEntryID: String?

    private enum CodingKeys: String, CodingKey {
        case id, name, description, variants
        case referenceAssets = "reference_assets"
        case anchorEntryID = "anchor_entry_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        referenceAssets = try c.decodeIfPresent([LibraryReferenceAsset].self, forKey: .referenceAssets) ?? []
        variants = try c.decodeIfPresent([AssetVariantView].self, forKey: .variants) ?? []
        anchorEntryID = try c.decodeIfPresent(String.self, forKey: .anchorEntryID)
    }

    /// The hero plate (the backend projects a prop's `master` as view
    /// `hero`), else the first image (mirrors web `propHeroAsset`).
    public var heroURL: String? {
        (referenceAssets.first { $0.view == "hero" } ?? referenceAssets.first)?.url
    }
}
