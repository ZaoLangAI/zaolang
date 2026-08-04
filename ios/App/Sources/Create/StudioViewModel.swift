import Foundation
import Observation
import ZaolangKit

/// 工作台是一个界面两种形态（`roadmap.md` D3/D4）：`StudioMode.new` 没有 `source`，
/// `StudioMode.remix` 带 `sourceWorkID`，二者共用同一份表单状态与提交逻辑。
/// 操作类型只在文生视频 / 图生视频之间选——`createPage` 三个入口卡片就只有这两种 + 二创，
/// 文生图 / 视频转视频没有对应界面入口，不在这里暴露（YAGNI）。
@MainActor
@Observable
final class StudioViewModel {
    let mode: StudioMode
    private let environment: AppEnvironment

    private(set) var isLoadingSource = false
    private(set) var sourceWork: WorkDetail?
    private(set) var sourceLoadError: ApiError?

    var operation: GenerationOperation = .textToVideo
    var prompt: String = ""
    var negativePrompt: String = ""
    var aspectRatio: String = "16:9"
    var durationSeconds: Int = 5
    var qualityTier: QualityTier = .standard
    var rightsConfirmed = false

    private(set) var referenceAsset: AssetResponse?
    private(set) var isUploadingReference = false
    private(set) var uploadError: String?

    private(set) var quote: QuoteResponse?
    private(set) var isQuoting = false
    private(set) var quoteError: String?
    private var quoteTask: Task<Void, Never>?

    private(set) var isSubmitting = false
    private(set) var submitError: String?
    private(set) var submittedJobID: String?

    var sourceWorkID: String? {
        if case .remix(let workID) = mode { return workID }
        return nil
    }

    var needsReferenceImage: Bool { operation == .imageToVideo }

    var canSubmit: Bool {
        guard !isSubmitting, !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        if needsReferenceImage && referenceAsset == nil { return false }
        if sourceWorkID != nil && !rightsConfirmed { return false }
        if let quote, !quote.sufficient { return false }
        return true
    }

    init(mode: StudioMode, environment: AppEnvironment) {
        self.mode = mode
        self.environment = environment
        if case .new(let operation, let initialPrompt) = mode {
            self.operation = operation
            if let initialPrompt { prompt = initialPrompt }
        }
    }

    func load() async {
        guard let sourceWorkID else {
            scheduleQuote()
            return
        }
        isLoadingSource = true
        defer { isLoadingSource = false }
        do {
            let detail = try await environment.apiClient.fetchWork(id: sourceWorkID)
            sourceWork = detail
            if prompt.isEmpty { prompt = detail.reusableParams?.prompt ?? "" }
            if negativePrompt.isEmpty { negativePrompt = detail.reusableParams?.negativePrompt ?? "" }
        } catch let error as ApiError {
            sourceLoadError = error
        } catch {
            sourceLoadError = .unexpectedResponse(status: 0)
        }
        scheduleQuote()
    }

    /// 报价只取决于 operation/quality/duration，跟提示词/参考图无关——这三项一变就重新报价，
    /// 400ms 去抖避免用户连点分段控件时打一串请求。
    func scheduleQuote() {
        quoteTask?.cancel()
        quoteTask = Task {
            try? await Task.sleep(nanoseconds: 400_000_000)
            guard !Task.isCancelled else { return }
            await refreshQuote()
        }
    }

    private func refreshQuote() async {
        isQuoting = true
        quoteError = nil
        do {
            quote = try await environment.apiClient.quoteGeneration(QuoteRequest(
                operation: operation,
                qualityTier: qualityTier,
                durationSeconds: operation.isVideo ? durationSeconds : 0
            ))
        } catch let error as ApiError {
            quote = nil
            quoteError = error.fallbackMessage
        } catch {
            quote = nil
            quoteError = L10n.t("remixPage.quoteFailed")
        }
        isQuoting = false
    }

    func uploadReference(data: Data, filename: String, mimeType: String) async {
        isUploadingReference = true
        uploadError = nil
        defer { isUploadingReference = false }
        do {
            let checksum = UploadTransport.sha256Hex(of: data)
            let presign = try await environment.apiClient.presignUpload(UploadPresignRequest(
                filename: filename,
                mimeType: mimeType,
                sizeBytes: data.count,
                checksumSHA256: checksum,
                purpose: .generationReference
            ))
            try await environment.uploadTransport.put(data: data, to: presign.uploadURL, requiredHeaders: presign.requiredHeaders)
            referenceAsset = try await environment.apiClient.completeUpload(sessionID: presign.uploadSessionID)
        } catch let error as ApiError {
            uploadError = error.fallbackMessage
        } catch {
            uploadError = L10n.t("settingsPage.saveFailed")
        }
    }

    func removeReference() {
        referenceAsset = nil
    }

    /// 提交 = 先建一份草稿（携带 `source_work_id`，供发布时继承许可与创作链），再拿草稿 id
    /// 提交生成任务；两步共用同一个幂等键——断网重发时账本只会留一条预扣记录。
    func submit() async {
        guard canSubmit else { return }
        isSubmitting = true
        submitError = nil
        defer { isSubmitting = false }
        do {
            let draft = try await environment.apiClient.createDraft(DraftCreateRequest(sourceWorkID: sourceWorkID))
            let idempotencyKey = await environment.idempotencyKeys.key(for: draft.id)
            let params = GenerationParams(
                prompt: prompt,
                negativePrompt: negativePrompt.isEmpty ? nil : negativePrompt,
                aspectRatio: aspectRatio,
                durationSeconds: operation.isVideo ? durationSeconds : 0,
                referenceAssetIDs: referenceAsset.map { [$0.id] } ?? []
            )
            let job = try await environment.apiClient.submitGeneration(
                GenerationJobCreateRequest(
                    operation: operation,
                    qualityTier: qualityTier,
                    params: params,
                    draftID: draft.id,
                    sourceWorkID: sourceWorkID,
                    maxCredits: quote?.credits
                ),
                idempotencyKey: idempotencyKey
            )
            await environment.idempotencyKeys.invalidate(operationID: draft.id)
            environment.trackJob(id: job.id)
            submittedJobID = job.id
        } catch let error as ApiError {
            submitError = error.fallbackMessage
        } catch {
            submitError = L10n.t("settingsPage.saveFailed")
        }
    }
}
