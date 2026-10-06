import Foundation

// A card's management graph (`GET /v1/{characters,scenes,props}/{id}/graph`,
// `back/app/api/schemas/asset_graph.py`): its looks / variants with their
// images, the typed relations between them, its voices (characters only)
// and jobs still filling it. iOS
// renders it read-mostly (`zaolang-ios-client` › reference-roadmap). Free
// strings stay `String` — an unknown entry type or relation must not fail
// the whole decode.

public struct CustomAttribute: Codable, Sendable, Equatable, Hashable {
    public let key: String
    public let value: String
}

public struct VariantAttributes: Codable, Sendable, Equatable {
    public let outfit: String?
    public let state: String?
    public let sceneNote: String?
    public let custom: [CustomAttribute]

    private enum CodingKeys: String, CodingKey {
        case outfit, state, custom
        case sceneNote = "scene_note"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        outfit = try c.decodeIfPresent(String.self, forKey: .outfit)
        state = try c.decodeIfPresent(String.self, forKey: .state)
        sceneNote = try c.decodeIfPresent(String.self, forKey: .sceneNote)
        custom = try c.decodeIfPresent([CustomAttribute].self, forKey: .custom) ?? []
    }
}

public struct SceneLinkView: Codable, Sendable, Equatable {
    public let sceneID: String
    public let sceneName: String
    public let variantName: String?

    private enum CodingKeys: String, CodingKey {
        case sceneID = "scene_id"
        case sceneName = "scene_name"
        case variantName = "variant_name"
    }
}

public struct AssetEntryView: Codable, Sendable, Equatable, Identifiable, Hashable {
    public let id: String
    public let assetID: String
    public let url: String?
    /// `AssetEntryType` (`back/app/models/enums.py`), e.g. `character_sheet`.
    public let entryType: String
    public let view: String?
    /// The viewpoint a 多机位 image shows (`view` / `shot` entries); `nil`
    /// for older images, which fall back to their coarse `view`.
    public let camera: CameraPose?
    public let expressions: [String]
    public let label: String?
    /// `candidate` | `approved`.
    public let status: String
    public let isAnchor: Bool
    public let sourceJobID: String?
    public let createdAt: Date?

    public var isCandidate: Bool { status == "candidate" }

    private enum CodingKeys: String, CodingKey {
        case id, url, view, camera, expressions, label, status
        case assetID = "asset_id"
        case entryType = "entry_type"
        case isAnchor = "is_anchor"
        case sourceJobID = "source_job_id"
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        assetID = try c.decode(String.self, forKey: .assetID)
        url = try c.decodeIfPresent(String.self, forKey: .url)
        entryType = try c.decode(String.self, forKey: .entryType)
        view = try c.decodeIfPresent(String.self, forKey: .view)
        camera = try c.decodeIfPresent(CameraPose.self, forKey: .camera)
        expressions = try c.decodeIfPresent([String].self, forKey: .expressions) ?? []
        label = try c.decodeIfPresent(String.self, forKey: .label)
        status = try c.decode(String.self, forKey: .status)
        isAnchor = try c.decodeIfPresent(Bool.self, forKey: .isAnchor) ?? false
        sourceJobID = try c.decodeIfPresent(String.self, forKey: .sourceJobID)
        createdAt = try c.decodeIfPresent(Date.self, forKey: .createdAt)
    }
}

public struct AssetVariantView: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let description: String?
    /// Enumerated presets (`age_stage`, `period`; a scene's four axes).
    public let presets: [String: String]
    public let attributes: VariantAttributes?
    public let sceneLink: SceneLinkView?
    public let voiceID: String?
    public let isDefault: Bool
    public let sortOrder: Int
    public let entries: [AssetEntryView]

    private enum CodingKeys: String, CodingKey {
        case id, name, description, presets, attributes, entries
        case sceneLink = "scene_link"
        case voiceID = "voice_id"
        case isDefault = "is_default"
        case sortOrder = "sort_order"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        let raw = try c.decodeIfPresent([String: String?].self, forKey: .presets) ?? [:]
        presets = raw.compactMapValues { $0 }
        attributes = try c.decodeIfPresent(VariantAttributes.self, forKey: .attributes)
        sceneLink = try c.decodeIfPresent(SceneLinkView.self, forKey: .sceneLink)
        voiceID = try c.decodeIfPresent(String.self, forKey: .voiceID)
        isDefault = try c.decodeIfPresent(Bool.self, forKey: .isDefault) ?? false
        sortOrder = try c.decodeIfPresent(Int.self, forKey: .sortOrder) ?? 0
        entries = try c.decodeIfPresent([AssetEntryView].self, forKey: .entries) ?? []
    }
}

public struct AssetEdgeView: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    /// `variant` | `entry` | `voice`.
    public let level: String
    public let sourceID: String
    public let targetID: String
    /// `AssetRelation` values (`age`, `outfit`, `edit`, `params`…).
    public let relations: [String]
    public let label: String?
    /// `auto` | `manual`.
    public let origin: String

    private enum CodingKeys: String, CodingKey {
        case id, level, relations, label, origin
        case sourceID = "source_id"
        case targetID = "target_id"
    }
}

public struct AssetGraphPendingJob: Codable, Sendable, Equatable {
    public let jobID: String
    public let status: String
    /// `orbit` (camera poses), `panorama`, `adjust`, `derive`…; `nil` for a
    /// plain slot job.
    public let mode: String?
    public let targetVariantID: String?
    public let sourceEntryID: String?
    public let targetVoiceID: String?

    private enum CodingKeys: String, CodingKey {
        case status, mode
        case jobID = "job_id"
        case targetVariantID = "target_variant_id"
        case sourceEntryID = "source_entry_id"
        case targetVoiceID = "target_voice_id"
    }
}

public struct VoiceAudioView: Codable, Sendable, Equatable {
    public let assetID: String
    public let url: String?

    private enum CodingKeys: String, CodingKey {
        case url
        case assetID = "asset_id"
    }
}

public struct VoiceParams: Codable, Sendable, Equatable {
    public let speed: Double?
    public let emotion: String?
}

public struct VoiceAttributes: Codable, Sendable, Equatable {
    public let ageStage: String?
    public let emotion: String?
    /// `dialogue` | `inner_monologue` | `narration`.
    public let use: String?
    public let custom: [CustomAttribute]

    private enum CodingKeys: String, CodingKey {
        case emotion, use, custom
        case ageStage = "age_stage"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ageStage = try c.decodeIfPresent(String.self, forKey: .ageStage)
        emotion = try c.decodeIfPresent(String.self, forKey: .emotion)
        use = try c.decodeIfPresent(String.self, forKey: .use)
        custom = try c.decodeIfPresent([CustomAttribute].self, forKey: .custom) ?? []
    }
}

/// A character voice (P7, `CharacterVoiceView`).
public struct CharacterVoiceView: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let description: String?
    /// `preset` | `clone`.
    public let source: String
    public let model: String?
    public let voice: String?
    public let params: VoiceParams?
    public let attributes: VoiceAttributes?
    public let preview: VoiceAudioView?
    public let previewText: String?
    public let isDefault: Bool
    public let lookIDs: [String]

    private enum CodingKeys: String, CodingKey {
        case id, name, description, source, model, voice, params, attributes, preview
        case previewText = "preview_text"
        case isDefault = "is_default"
        case lookIDs = "look_ids"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        source = try c.decode(String.self, forKey: .source)
        model = try c.decodeIfPresent(String.self, forKey: .model)
        voice = try c.decodeIfPresent(String.self, forKey: .voice)
        params = try c.decodeIfPresent(VoiceParams.self, forKey: .params)
        attributes = try c.decodeIfPresent(VoiceAttributes.self, forKey: .attributes)
        preview = try c.decodeIfPresent(VoiceAudioView.self, forKey: .preview)
        previewText = try c.decodeIfPresent(String.self, forKey: .previewText)
        isDefault = try c.decodeIfPresent(Bool.self, forKey: .isDefault) ?? false
        lookIDs = try c.decodeIfPresent([String].self, forKey: .lookIDs) ?? []
    }
}

public struct AssetGraphResponse: Codable, Sendable, Equatable {
    public let cardID: String
    /// `character` | `scene` | `prop` (`AssetCardKind`).
    public let cardKind: String
    public let name: String
    public let description: String?
    public let voiceDescription: String?
    public let anchorEntryID: String?
    public let variants: [AssetVariantView]
    public let edges: [AssetEdgeView]
    public let pending: [AssetGraphPendingJob]
    public let voices: [CharacterVoiceView]

    private enum CodingKeys: String, CodingKey {
        case name, description, variants, edges, pending, voices
        case cardID = "card_id"
        case cardKind = "card_kind"
        case voiceDescription = "voice_description"
        case anchorEntryID = "anchor_entry_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        cardID = try c.decode(String.self, forKey: .cardID)
        cardKind = try c.decode(String.self, forKey: .cardKind)
        name = try c.decode(String.self, forKey: .name)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        voiceDescription = try c.decodeIfPresent(String.self, forKey: .voiceDescription)
        anchorEntryID = try c.decodeIfPresent(String.self, forKey: .anchorEntryID)
        variants = try c.decodeIfPresent([AssetVariantView].self, forKey: .variants) ?? []
        edges = try c.decodeIfPresent([AssetEdgeView].self, forKey: .edges) ?? []
        pending = try c.decodeIfPresent([AssetGraphPendingJob].self, forKey: .pending) ?? []
        voices = try c.decodeIfPresent([CharacterVoiceView].self, forKey: .voices) ?? []
    }
}

// ---- writes ------------------------------------------------------------------------

/// `PATCH /v1/characters/{id}` with text fields only — never
/// `reference_asset_ids` (a flat replace that would drop images).
public struct CharacterProfileUpdate: Encodable, Sendable {
    public var name: String?
    public var description: String?
    public var voiceDescription: String?

    public init(name: String? = nil, description: String? = nil, voiceDescription: String? = nil) {
        self.name = name
        self.description = description
        self.voiceDescription = voiceDescription
    }

    private enum CodingKeys: String, CodingKey {
        case name, description
        case voiceDescription = "voice_description"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(name, forKey: .name)
        try c.encodeIfPresent(description, forKey: .description)
        try c.encodeIfPresent(voiceDescription, forKey: .voiceDescription)
    }
}

public struct CharacterScriptLink: Codable, Sendable, Equatable, Identifiable {
    public let episodeID: String
    public let episodeTitle: String
    public let seriesTitle: String
    public let characterName: String

    public var id: String { episodeID }

    private enum CodingKeys: String, CodingKey {
        case episodeID = "episode_id"
        case episodeTitle = "episode_title"
        case seriesTitle = "series_title"
        case characterName = "character_name"
    }
}

public struct CharacterDescribeRequest: Encodable, Sendable {
    public var episodeID: String?
    public var fields: [String]

    public init(episodeID: String? = nil, fields: [String] = ["description", "voice_description"]) {
        self.episodeID = episodeID
        self.fields = fields
    }

    private enum CodingKeys: String, CodingKey {
        case fields
        case episodeID = "episode_id"
    }
}

public struct CharacterDescribeResponse: Codable, Sendable, Equatable {
    public let description: String?
    public let voiceDescription: String?

    private enum CodingKeys: String, CodingKey {
        case description
        case voiceDescription = "voice_description"
    }
}

public struct VoicePreviewRequest: Encodable, Sendable {
    public var dryRun: Bool
    public var qualityTier: String

    public init(dryRun: Bool, qualityTier: String = "standard") {
        self.dryRun = dryRun
        self.qualityTier = qualityTier
    }

    private enum CodingKeys: String, CodingKey {
        case dryRun = "dry_run"
        case qualityTier = "quality_tier"
    }
}

public struct VoicePreviewResponse: Codable, Sendable, Equatable {
    public let credits: Int
    public let availableCredits: Int
    public let sufficient: Bool
    public let jobID: String?

    private enum CodingKeys: String, CodingKey {
        case credits, sufficient
        case availableCredits = "available_credits"
        case jobID = "job_id"
    }
}

struct MakeDefaultVoice: Encodable {
    let makeDefault = true

    private enum CodingKeys: String, CodingKey {
        case makeDefault = "make_default"
    }
}

struct EmptyBody: Encodable {}
