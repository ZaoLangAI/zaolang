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

    public init(
        prompt: String,
        negativePrompt: String? = nil,
        seed: Int? = nil,
        aspectRatio: String = "16:9",
        durationSeconds: Int = 0,
        referenceAssetIDs: [String] = [],
        stylePresetID: String? = nil,
        shortformProfile: String? = nil,
        characterIDs: [String] = []
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
    }
}

public struct QuoteRequest: Encodable, Sendable {
    public var operation: Operation
    public var qualityTier: QualityTier
    public var durationSeconds: Int

    public init(operation: Operation, qualityTier: QualityTier, durationSeconds: Int = 0) {
        self.operation = operation
        self.qualityTier = qualityTier
        self.durationSeconds = durationSeconds
    }

    private enum CodingKeys: String, CodingKey {
        case operation
        case qualityTier = "quality_tier"
        case durationSeconds = "duration_seconds"
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
