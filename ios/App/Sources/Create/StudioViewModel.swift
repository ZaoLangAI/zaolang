import Foundation
import Observation
import ZaolangKit

/// 工作台是一个界面两种形态（`roadmap.md` D3/D4）：`StudioMode.new` 没有 `source`，
/// `StudioMode.remix` 带 `sourceWorkID`，二者共用同一份表单状态与提交逻辑。
/// 操作类型在文生视频 / 图生视频之间选，或走「图片创作」入口——`createPage` 入口卡片对应
/// 文生视频、图生视频、图片创作 + 二创、发布；图片创作不单独暴露"文生图/图生图"两个操作，
/// 而是共用一个 `.textToImage` 起点，`effectiveOperation` 按是否挂了参考图派生成 `.imageToImage`
/// （镜像 Web 端 `GenerationStudio` 的同一套派生逻辑）。视频转视频没有对应界面入口，不在这里
/// 暴露（YAGNI 仍然适用，只是范围缩小到这一项）。
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

    // "图片创作" — what this output is for, and which existing character/scene
    // (if any) it should read from and write back to. Only meaningful when
    // `operation.isImage`; see `back/app/models/enums.py::ImageAssetKind`.
    var assetKind: ImageAssetKind = .general
    var targetCharacterID: String?
    var targetSceneID: String?
    var autoAttachToRoster = true

    private(set) var characters: [CharacterResponse] = []
    private(set) var scenes: [SceneResponse] = []
    private(set) var isLoadingLibraries = false
    private(set) var libraryError: String?
    private(set) var completingCharacterID: String?

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

    var selectedCharacter: CharacterResponse? {
        characters.first { $0.id == targetCharacterID }
    }

    /// The operation actually priced and submitted. For the image family this
    /// is derived from whether a reference is attached rather than a
    /// separate toggle the user has to remember to flip — same pattern as
    /// the web studio. Picking `assetKind == .character` here always
    /// generates just the front view (`GenerationParams.characterViews`
    /// defaults to `[.front]`); the remaining two views are a standalone
    /// completion action on the character library card, not a studio option
    /// (see `CharacterLibraryViewModel.completeViews`).
    var effectiveOperation: GenerationOperation {
        guard operation.isImage else { return operation }
        return referenceAsset != nil ? .imageToImage : .textToImage
    }

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
        if operation.isImage {
            await loadLibraries()
        }
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

    /// Only fetched for the image-creation entry — the video/audio studio
    /// forms never show a character/scene target picker, so there is no
    /// reason to make every studio session pay for these two requests.
    private func loadLibraries() async {
        isLoadingLibraries = true
        libraryError = nil
        defer { isLoadingLibraries = false }
        do {
            async let charactersTask = environment.apiClient.listCharacters()
            async let scenesTask = environment.apiClient.listScenes()
            characters = try await charactersTask
            scenes = try await scenesTask
        } catch let error as ApiError {
            libraryError = error.fallbackMessage
        } catch {
            libraryError = L10n.t("remixPage.quoteFailed")
        }
    }

    func createCharacter(name: String, description: String?) async {
        do {
            let created = try await environment.apiClient.createCharacter(
                CharacterCreateRequest(name: name, description: description)
            )
            characters.append(created)
            targetCharacterID = created.id
            scheduleQuote()
        } catch let error as ApiError {
            libraryError = error.fallbackMessage
        } catch {
            libraryError = L10n.t("settingsPage.saveFailed")
        }
    }

    /// Step two of the guided flow (`assetKindSection`'s "角色图" option only
    /// ever produces the front view): borrows the front reference and asks
    /// for both remaining views in one job (`characterViews: [.side, .back]`)
    /// — `execute_asset_output_advance` loops it twice server-side, attaching
    /// both outputs back to this same character. Mirrors the web character
    /// library's `completeViews`.
    func completeViews(for character: CharacterResponse) async {
        guard let front = character.frontReference, character.canCompleteViews else { return }
        completingCharacterID = character.id
        defer { completingCharacterID = nil }
        let operationID = "complete-views-\(character.id)"
        do {
            let idempotencyKey = await environment.idempotencyKeys.key(for: operationID)
            let job = try await environment.apiClient.submitGeneration(
                GenerationJobCreateRequest(
                    operation: .imageToImage,
                    qualityTier: .standard,
                    params: GenerationParams(
                        prompt: character.description?.isEmpty == false ? character.description! : character.name,
                        aspectRatio: "3:4",
                        referenceAssetIDs: [front.assetID],
                        assetKind: .character,
                        characterViews: [.side, .back],
                        targetCharacterID: character.id,
                        autoAttachAsset: true
                    )
                ),
                idempotencyKey: idempotencyKey
            )
            let finished = try await pollUntilTerminal(jobID: job.id)
            await environment.idempotencyKeys.invalidate(operationID: operationID)
            guard finished.status.value == .succeeded else {
                libraryError = L10n.t("remixPage.completeViewsFailed")
                return
            }
            let refreshed = try await environment.apiClient.fetchCharacter(id: character.id)
            if let index = characters.firstIndex(where: { $0.id == refreshed.id }) {
                characters[index] = refreshed
            }
        } catch {
            libraryError = L10n.t("remixPage.completeViewsFailed")
        }
    }

    private func pollUntilTerminal(jobID: String, maxAttempts: Int = 40, intervalNanoseconds: UInt64 = 3_000_000_000) async throws -> GenerationJobResponse {
        for _ in 0..<maxAttempts {
            let job = try await environment.apiClient.fetchGenerationJob(id: jobID)
            if job.status.value?.isTerminal == true { return job }
            try await Task.sleep(nanoseconds: intervalNanoseconds)
        }
        return try await environment.apiClient.fetchGenerationJob(id: jobID)
    }

    func createScene(name: String, description: String?) async {
        do {
            let created = try await environment.apiClient.createScene(
                SceneCreateRequest(name: name, description: description)
            )
            scenes.append(created)
            targetSceneID = created.id
        } catch let error as ApiError {
            libraryError = error.fallbackMessage
        } catch {
            libraryError = L10n.t("settingsPage.saveFailed")
        }
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
        let effectiveOp = effectiveOperation
        do {
            quote = try await environment.apiClient.quoteGeneration(QuoteRequest(
                operation: effectiveOp,
                qualityTier: qualityTier,
                durationSeconds: effectiveOp.isVideo ? durationSeconds : 0
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
            scheduleQuote()
        } catch let error as ApiError {
            uploadError = error.fallbackMessage
        } catch {
            uploadError = L10n.t("settingsPage.saveFailed")
        }
    }

    func removeReference() {
        referenceAsset = nil
        scheduleQuote()
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
            let effectiveOp = effectiveOperation
            let referenceIDs = referenceAsset.map { [$0.id] } ?? []
            let isCharacterAssetKind = operation.isImage && assetKind == .character
            let params = GenerationParams(
                prompt: prompt,
                negativePrompt: negativePrompt.isEmpty ? nil : negativePrompt,
                aspectRatio: aspectRatio,
                durationSeconds: effectiveOp.isVideo ? durationSeconds : 0,
                referenceAssetIDs: referenceIDs,
                assetKind: operation.isImage ? assetKind : .general,
                targetCharacterID: isCharacterAssetKind ? targetCharacterID : nil,
                targetSceneID: (operation.isImage && assetKind == .scene) ? targetSceneID : nil,
                autoAttachAsset: isCharacterAssetKind ? autoAttachToRoster : true
            )
            let job = try await environment.apiClient.submitGeneration(
                GenerationJobCreateRequest(
                    operation: effectiveOp,
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
