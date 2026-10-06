import Foundation

/// 一次生成请求的全部参数。字段与 `back/app/api/schemas/jobs.py::GenerationParams` 一一对应，
/// 客户端不做任何裁剪或改名——报价、提交、重试三处复用同一个类型。
public struct GenerationParams: Codable, Sendable, Equatable {
    public var prompt: String
    public var negativePrompt: String?
    public var seed: Int?
    public var aspectRatio: String
    public var durationSeconds: Int
    public var referenceAssetIDs: [String]
    public var stylePresetID: String?
    public var shortformProfile: String?
    public var characterIDs: [String]
    public var styleGalleryID: String?
    /// What a `text_to_image`/`image_to_image` output is *for* — selects the
    /// `(operation, asset_kind)` workflow template and which card the
    /// succeeded output(s) file into. An image job must name `character` /
    /// `scene` / `prop` (AC-8: 422 `IMAGE_ASSET_KIND_REQUIRED` otherwise);
    /// video jobs leave the `general` default.
    public var assetKind: ImageAssetKind
    /// Only meaningful with `assetKind == .character`: which of front/side/
    /// back this job produces, one at a time. `nil` means `[.front]` — a
    /// plain single-view request. iOS no longer sends it (the turnaround is
    /// the web workspace's camera poses).
    public var characterViews: [CharacterViewAngle]?
    /// The character skill this output auto-attaches to. Unset with a
    /// character `assetKind` creates a brand-new character skill instead.
    public var targetCharacterID: String?
    /// The scene this output auto-attaches to. Unset with `assetKind: .scene`
    /// leaves the output unattached — scenes have no auto-create path.
    public var targetSceneID: String?
    /// The prop this output files into (`assetKind: .prop`).
    public var targetPropID: String?
    /// The look / variant / condition of the target card the output files into.
    public var targetVariantID: String?
    /// The card's name, so the planner keeps the subject's identity.
    public var subjectNameHint: String?
    /// A character's identity portrait (定妆照, 3:4 head-and-shoulders).
    public var characterPortrait: Bool?
    /// A scene master's preset axes (`remixPage.presets.*` values).
    public var sceneLighting: String?
    public var sceneWeather: String?
    public var sceneState: String?
    public var scenePeriod: String?
    /// A prop master's condition: `new` | `worn` | `damaged` | `broken`.
    public var propState: String?
    /// Opts out of the auto-attach above while a borrowed reference (for
    /// side/back consistency) still shapes the generation itself.
    public var autoAttachAsset: Bool

    public init(
        prompt: String,
        negativePrompt: String? = nil,
        seed: Int? = nil,
        aspectRatio: String = "16:9",
        durationSeconds: Int = 0,
        referenceAssetIDs: [String] = [],
        stylePresetID: String? = nil,
        shortformProfile: String? = nil,
        characterIDs: [String] = [],
        styleGalleryID: String? = nil,
        assetKind: ImageAssetKind = .general,
        characterViews: [CharacterViewAngle]? = nil,
        targetCharacterID: String? = nil,
        targetSceneID: String? = nil,
        targetPropID: String? = nil,
        targetVariantID: String? = nil,
        subjectNameHint: String? = nil,
        characterPortrait: Bool? = nil,
        sceneLighting: String? = nil,
        sceneWeather: String? = nil,
        sceneState: String? = nil,
        scenePeriod: String? = nil,
        propState: String? = nil,
        autoAttachAsset: Bool = true
    ) {
        self.prompt = prompt
        self.negativePrompt = negativePrompt
        self.seed = seed
        self.aspectRatio = aspectRatio
        self.durationSeconds = durationSeconds
        self.referenceAssetIDs = referenceAssetIDs
        self.stylePresetID = stylePresetID
        self.shortformProfile = shortformProfile
        self.characterIDs = characterIDs
        self.styleGalleryID = styleGalleryID
        self.assetKind = assetKind
        self.characterViews = characterViews
        self.targetCharacterID = targetCharacterID
        self.targetSceneID = targetSceneID
        self.targetPropID = targetPropID
        self.targetVariantID = targetVariantID
        self.subjectNameHint = subjectNameHint
        self.characterPortrait = characterPortrait
        self.sceneLighting = sceneLighting
        self.sceneWeather = sceneWeather
        self.sceneState = sceneState
        self.scenePeriod = scenePeriod
        self.propState = propState
        self.autoAttachAsset = autoAttachAsset
    }

    private enum CodingKeys: String, CodingKey {
        case prompt
        case negativePrompt = "negative_prompt"
        case seed
        case aspectRatio = "aspect_ratio"
        case durationSeconds = "duration_seconds"
        case referenceAssetIDs = "reference_asset_ids"
        case stylePresetID = "style_preset_id"
        case shortformProfile = "shortform_profile"
        case characterIDs = "character_ids"
        case styleGalleryID = "style_gallery_id"
        case assetKind = "asset_kind"
        case characterViews = "character_views"
        case targetCharacterID = "target_character_id"
        case targetSceneID = "target_scene_id"
        case targetPropID = "target_prop_id"
        case targetVariantID = "target_variant_id"
        case subjectNameHint = "subject_name_hint"
        case characterPortrait = "character_portrait"
        case sceneLighting = "scene_lighting"
        case sceneWeather = "scene_weather"
        case sceneState = "scene_state"
        case scenePeriod = "scene_period"
        case propState = "prop_state"
        case autoAttachAsset = "auto_attach_asset"
    }
}

public struct QuoteRequest: Encodable, Sendable {
    public var operation: Operation
    public var qualityTier: QualityTier
    public var durationSeconds: Int
    /// Required for an image quote since AC-8 (`character` / `scene` / `prop`).
    public var assetKind: ImageAssetKind?

    public init(operation: Operation, qualityTier: QualityTier, durationSeconds: Int = 0, assetKind: ImageAssetKind? = nil) {
        self.operation = operation
        self.qualityTier = qualityTier
        self.durationSeconds = durationSeconds
        self.assetKind = assetKind
    }

    private enum CodingKeys: String, CodingKey {
        case operation
        case qualityTier = "quality_tier"
        case durationSeconds = "duration_seconds"
        case assetKind = "asset_kind"
    }
}

public struct QuoteResponse: Codable, Sendable, Equatable {
    public let credits: Int
    public let estimatedSeconds: Int
    public let breakdown: [String: Int]
    public let availableCredits: Int
    public let sufficient: Bool

    private enum CodingKeys: String, CodingKey {
        case credits
        case estimatedSeconds = "estimated_seconds"
        case breakdown
        case availableCredits = "available_credits"
        case sufficient
    }
}

/// `POST /v1/generation-jobs` 请求体。二创靠 `sourceWorkID` 是否非 nil 区分，
/// 不是另一套请求类型——工作台一个界面两种形态的后端投影。
public struct GenerationJobCreateRequest: Encodable, Sendable {
    public var operation: Operation
    public var qualityTier: QualityTier
    public var params: GenerationParams
    public var draftID: String?
    public var sourceWorkID: String?
    public var maxCredits: Int?

    public init(
        operation: Operation,
        qualityTier: QualityTier,
        params: GenerationParams,
        draftID: String? = nil,
        sourceWorkID: String? = nil,
        maxCredits: Int? = nil
    ) {
        self.operation = operation
        self.qualityTier = qualityTier
        self.params = params
        self.draftID = draftID
        self.sourceWorkID = sourceWorkID
        self.maxCredits = maxCredits
    }

    private enum CodingKeys: String, CodingKey {
        case operation
        case qualityTier = "quality_tier"
        case params
        case draftID = "draft_id"
        case sourceWorkID = "source_work_id"
        case maxCredits = "max_credits"
    }
}

/// One option on a `single_choice`/`multi_choice` follow-up question.
public struct JobInputQuestionOption: Codable, Sendable, Equatable, Identifiable {
    public var id: String { value }
    public let value: String
    public let label: String
}

/// A follow-up question a planning/`copy_generate` node is waiting on —
/// mirrors `JobInputQuestionView` (`back/app/domain/jobs/input_requests.py`).
/// Only three kinds exist; an unrecognized one decodes but the view treats
/// it as free text rather than crashing on an unknown case.
public struct JobInputQuestion: Codable, Sendable, Equatable, Identifiable {
    public enum Kind: String, Codable, Sendable {
        case singleChoice = "single_choice"
        case multiChoice = "multi_choice"
        case freeText = "free_text"
    }

    public let id: String
    public let kind: Kind
    public let prompt: String
    public let options: [JobInputQuestionOption]
    public let required: Bool

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decodeIfPresent(Kind.self, forKey: .kind) ?? .freeText
        prompt = try c.decode(String.self, forKey: .prompt)
        options = try c.decodeIfPresent([JobInputQuestionOption].self, forKey: .options) ?? []
        required = try c.decodeIfPresent(Bool.self, forKey: .required) ?? false
    }
}

/// What a job at `awaiting_input` is waiting on — `GET .../input-request`.
public struct JobInputRequestResponse: Codable, Sendable, Equatable {
    public let jobID: String
    public let nodeID: String
    public let questions: [JobInputQuestion]
    public let expiresAt: Date

    private enum CodingKeys: String, CodingKey {
        case jobID = "job_id"
        case nodeID = "node_id"
        case questions
        case expiresAt = "expires_at"
    }
}

/// One answer in `POST .../answer`'s body — `value` is a bare `String` for
/// `single_choice`/`free_text`, JSON-encoded as a `[String]` for
/// `multi_choice` (mirrors the web `QuestionAnswer` union; see
/// `AnswerValue` below for the client-side equivalent).
public enum AnswerValue: Sendable, Equatable {
    case text(String)
    case choices([String])

    public var isEmpty: Bool {
        switch self {
        case .text(let value): return value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .choices(let values): return values.isEmpty
        }
    }
}

extension AnswerValue: Encodable {
    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .text(let value): try container.encode(value)
        case .choices(let values): try container.encode(values)
        }
    }
}

public struct JobAnswerItem: Encodable, Sendable {
    public let questionID: String
    public let value: AnswerValue

    public init(questionID: String, value: AnswerValue) {
        self.questionID = questionID
        self.value = value
    }

    private enum CodingKeys: String, CodingKey {
        case questionID = "question_id"
        case value
    }
}

public struct JobAnswerRequest: Encodable, Sendable {
    public let answers: [JobAnswerItem]

    public init(answers: [JobAnswerItem]) {
        self.answers = answers
    }
}

public struct RouteSummary: Codable, Sendable, Equatable {
    public let provider: String
    public let providerKind: String
    public let modelOrWorkflow: String
    public let score: Double
    public let reason: String

    private enum CodingKeys: String, CodingKey {
        case provider
        case providerKind = "provider_kind"
        case modelOrWorkflow = "model_or_workflow"
        case score, reason
    }
}

public struct JobEventResponse: Codable, Sendable, Equatable, Identifiable {
    public var id: Int { sequence }
    public let sequence: Int
    public let eventType: String
    public let status: RawOrUnknown<JobStatus>
    public let progress: Int
    public let message: String
    public let internalCode: String?
    public let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case sequence
        case eventType = "event_type"
        case status, progress, message
        case internalCode = "internal_code"
        case createdAt = "created_at"
    }
}

/// 生成任务的完整投影：提交、列表、详情、取消、重试都回这同一个类型。
public struct GenerationJobResponse: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let status: RawOrUnknown<JobStatus>
    public let operation: RawOrUnknown<Operation>
    public let qualityTier: RawOrUnknown<QualityTier>
    public let progress: Int
    public let quotedCredits: Int
    public let reservedCredits: Int
    public let actualCredits: Int?
    public let estimatedSeconds: Int
    public let route: RouteSummary?
    public let outputAssetID: String?
    public let outputURL: String?
    /// Populated alongside the singular fields above for a multi-output job
    /// (several candidates or camera poses at once) — one entry per output.
    public let outputAssetIDs: [String]?
    public let outputURLs: [String]?
    /// An image job's kind; `general` / `cover` only on jobs from before AC-8.
    public let assetKind: RawOrUnknown<ImageAssetKind>?
    /// The card the output filed into (set at write-back).
    public let linkedCharacterID: String?
    public let linkedSceneID: String?
    public let linkedPropID: String?
    public let draftID: String?
    public let failureCode: String?
    public let failureMessage: String?
    public let cancelRequested: Bool
    public let createdAt: Date
    public let finishedAt: Date?
    public let events: [JobEventResponse]

    private enum CodingKeys: String, CodingKey {
        case id, status, operation
        case qualityTier = "quality_tier"
        case progress
        case quotedCredits = "quoted_credits"
        case reservedCredits = "reserved_credits"
        case actualCredits = "actual_credits"
        case estimatedSeconds = "estimated_seconds"
        case route
        case outputAssetID = "output_asset_id"
        case outputURL = "output_url"
        case outputAssetIDs = "output_asset_ids"
        case outputURLs = "output_urls"
        case assetKind = "asset_kind"
        case linkedCharacterID = "linked_character_id"
        case linkedSceneID = "linked_scene_id"
        case linkedPropID = "linked_prop_id"
        case draftID = "draft_id"
        case failureCode = "failure_code"
        case failureMessage = "failure_message"
        case cancelRequested = "cancel_requested"
        case createdAt = "created_at"
        case finishedAt = "finished_at"
        case events
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        status = try c.decode(RawOrUnknown<JobStatus>.self, forKey: .status)
        operation = try c.decode(RawOrUnknown<Operation>.self, forKey: .operation)
        qualityTier = try c.decode(RawOrUnknown<QualityTier>.self, forKey: .qualityTier)
        progress = try c.decodeIfPresent(Int.self, forKey: .progress) ?? 0
        quotedCredits = try c.decode(Int.self, forKey: .quotedCredits)
        reservedCredits = try c.decode(Int.self, forKey: .reservedCredits)
        actualCredits = try c.decodeIfPresent(Int.self, forKey: .actualCredits)
        estimatedSeconds = try c.decodeIfPresent(Int.self, forKey: .estimatedSeconds) ?? 0
        route = try c.decodeIfPresent(RouteSummary.self, forKey: .route)
        outputAssetID = try c.decodeIfPresent(String.self, forKey: .outputAssetID)
        outputURL = try c.decodeIfPresent(String.self, forKey: .outputURL)
        outputAssetIDs = try c.decodeIfPresent([String].self, forKey: .outputAssetIDs)
        outputURLs = try c.decodeIfPresent([String].self, forKey: .outputURLs)
        assetKind = try c.decodeIfPresent(RawOrUnknown<ImageAssetKind>.self, forKey: .assetKind)
        linkedCharacterID = try c.decodeIfPresent(String.self, forKey: .linkedCharacterID)
        linkedSceneID = try c.decodeIfPresent(String.self, forKey: .linkedSceneID)
        linkedPropID = try c.decodeIfPresent(String.self, forKey: .linkedPropID)
        draftID = try c.decodeIfPresent(String.self, forKey: .draftID)
        failureCode = try c.decodeIfPresent(String.self, forKey: .failureCode)
        failureMessage = try c.decodeIfPresent(String.self, forKey: .failureMessage)
        cancelRequested = try c.decodeIfPresent(Bool.self, forKey: .cancelRequested) ?? false
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        finishedAt = try c.decodeIfPresent(Date.self, forKey: .finishedAt)
        events = try c.decodeIfPresent([JobEventResponse].self, forKey: .events) ?? []
    }

    /// 自定义 `init(from:)` 会关掉编译器合成的逐一成员初始化器，这里手写一份补回来——
    /// SSE 帧到达时只想更新 status/progress 两项、其余字段照抄旧值，需要这个入口。
    public init(
        id: String,
        status: RawOrUnknown<JobStatus>,
        operation: RawOrUnknown<Operation>,
        qualityTier: RawOrUnknown<QualityTier>,
        progress: Int,
        quotedCredits: Int,
        reservedCredits: Int,
        actualCredits: Int?,
        estimatedSeconds: Int,
        route: RouteSummary?,
        outputAssetID: String?,
        outputURL: String?,
        outputAssetIDs: [String]? = nil,
        outputURLs: [String]? = nil,
        assetKind: RawOrUnknown<ImageAssetKind>? = nil,
        linkedCharacterID: String? = nil,
        linkedSceneID: String? = nil,
        linkedPropID: String? = nil,
        draftID: String?,
        failureCode: String?,
        failureMessage: String?,
        cancelRequested: Bool,
        createdAt: Date,
        finishedAt: Date?,
        events: [JobEventResponse]
    ) {
        self.id = id
        self.status = status
        self.operation = operation
        self.qualityTier = qualityTier
        self.progress = progress
        self.quotedCredits = quotedCredits
        self.reservedCredits = reservedCredits
        self.actualCredits = actualCredits
        self.estimatedSeconds = estimatedSeconds
        self.route = route
        self.outputAssetID = outputAssetID
        self.outputURL = outputURL
        self.outputAssetIDs = outputAssetIDs
        self.outputURLs = outputURLs
        self.assetKind = assetKind
        self.linkedCharacterID = linkedCharacterID
        self.linkedSceneID = linkedSceneID
        self.linkedPropID = linkedPropID
        self.draftID = draftID
        self.failureCode = failureCode
        self.failureMessage = failureMessage
        self.cancelRequested = cancelRequested
        self.createdAt = createdAt
        self.finishedAt = finishedAt
        self.events = events
    }

    /// SSE 帧只带 sequence/status/progress/message 四项；任务详情页用这个方法拼一份
    /// "只更新 status/progress、其余字段照抄"的副本做即时反馈，完整字段等终态时的下一次
    /// `GET` 再对齐（见 `JobDetailViewModel.applyStreamEvent`）。
    public func withStreamProgress(status: RawOrUnknown<JobStatus>, progress: Int) -> GenerationJobResponse {
        GenerationJobResponse(
            id: id,
            status: status,
            operation: operation,
            qualityTier: qualityTier,
            progress: progress,
            quotedCredits: quotedCredits,
            reservedCredits: reservedCredits,
            actualCredits: actualCredits,
            estimatedSeconds: estimatedSeconds,
            route: route,
            outputAssetID: outputAssetID,
            outputURL: outputURL,
            outputAssetIDs: outputAssetIDs,
            outputURLs: outputURLs,
            assetKind: assetKind,
            linkedCharacterID: linkedCharacterID,
            linkedSceneID: linkedSceneID,
            linkedPropID: linkedPropID,
            draftID: draftID,
            failureCode: failureCode,
            failureMessage: failureMessage,
            cancelRequested: cancelRequested,
            createdAt: createdAt,
            finishedAt: finishedAt,
            events: events
        )
    }
}
