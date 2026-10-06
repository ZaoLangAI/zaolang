import Foundation
import Observation
import ZaolangKit

/// One card's workspace on iOS (read-mostly): the 创作 board, the look /
/// variant outline and — for a character — its voices. Writes: 定稿 a
/// candidate, a quick generate of the primary slot (quote → confirm →
/// idempotent draftless submit → 3s poll); for a character also set the
/// default voice, generate a voice preview and edit name / descriptions
/// (with an AI draft from linked scripts). Everything else continues on the web.
@MainActor
@Observable
final class AssetDetailViewModel {
    let kind: AssetCardKind
    let cardID: String
    private let environment: AppEnvironment
    private var apiClient: APIClient { environment.apiClient }

    private(set) var state: LoadableState<AssetGraphResponse> = .loading
    private(set) var scriptLinks: [CharacterScriptLink] = []
    private(set) var busyVoiceID: String?
    private(set) var approvingID: String?
    /// `variantID|slotID` of the primary slot being submitted / polled.
    private(set) var generatingSlot: String?
    var message: String?

    init(kind: AssetCardKind, cardID: String, environment: AppEnvironment) {
        self.kind = kind
        self.cardID = cardID
        self.environment = environment
    }

    var graph: AssetGraphResponse? { state.value }

    func load() async {
        do {
            state = .loaded(try await apiClient.fetchAssetGraph(kind: kind, id: cardID))
        } catch let error as ApiError {
            if state.value == nil { state = .failed(error) }
        } catch {
            if state.value == nil { state = .failed(.unexpectedResponse(status: 0)) }
        }
        if kind == .character {
            scriptLinks = (try? await apiClient.characterScriptLinks(id: cardID)) ?? []
        }
    }

    func approve(_ entry: AssetEntryView) async {
        approvingID = entry.id
        defer { approvingID = nil }
        do {
            _ = try await apiClient.approveAssetEntry(kind: kind, cardID: cardID, entryID: entry.id)
            message = L10n.t("iosCharacters.approved")
            await load()
        } catch let error as ApiError {
            message = error.fallbackMessage
        } catch {
            message = ApiError.unexpectedResponse(status: 0).fallbackMessage
        }
    }

    // MARK: - Primary slot

    nonisolated static func slotKey(variantID: String, slotID: String) -> String { "\(variantID)|\(slotID)" }

    /// The price of one primary-slot image at `tier`.
    func quotePrimary(tier: QualityTier) async -> Result<QuoteResponse, ApiError> {
        do {
            return .success(try await apiClient.quoteGeneration(
                QuoteRequest(operation: .textToImage, qualityTier: tier, assetKind: kind.imageAssetKind)
            ))
        } catch let error as ApiError {
            return .failure(error)
        } catch {
            return .failure(.unexpectedResponse(status: 0))
        }
    }

    /// Submits one draftless job for the primary slot (one idempotency key
    /// per card · variant · slot until the submit succeeds), tracks it in the
    /// create banner, then polls every 3s and reloads the board once it ends.
    /// The API's own message is shown on refusal (e.g. 422).
    func generate(_ slot: AssetSlots.Slot, variant: AssetVariantView, tier: QualityTier, quote: QuoteResponse) async {
        guard let graph, let params = AssetSlots.primaryJobParams(kind, graph: graph, variant: variant, slot: slot) else { return }
        let key = Self.slotKey(variantID: variant.id, slotID: slot.id)
        generatingSlot = key
        defer { generatingSlot = nil }
        let operationID = "asset-slot-\(cardID)-\(key)"
        do {
            let idempotencyKey = await environment.idempotencyKeys.key(for: operationID)
            let job = try await apiClient.submitGeneration(
                GenerationJobCreateRequest(operation: .textToImage, qualityTier: tier, params: params, maxCredits: quote.credits),
                idempotencyKey: idempotencyKey
            )
            await environment.idempotencyKeys.invalidate(operationID: operationID)
            environment.trackJob(id: job.id)
            message = L10n.t("iosAssets.generating")
            await load()
            while true {
                try await Task.sleep(for: .seconds(3))
                let current = try await apiClient.fetchGenerationJob(id: job.id)
                guard let status = current.status.value else { break }
                guard status.isTerminal else { continue }
                if status != .succeeded {
                    message = current.failureMessage ?? L10n.t("iosAssets.generateFailed")
                }
                break
            }
            await load()
        } catch is CancellationError {
            return
        } catch let error as ApiError {
            message = error.fallbackMessage
        } catch {
            message = L10n.t("iosAssets.generateFailed")
        }
    }

    // MARK: - Character voices & profile

    func makeDefault(_ voice: CharacterVoiceView) async {
        busyVoiceID = voice.id
        defer { busyVoiceID = nil }
        do {
            _ = try await apiClient.makeDefaultVoice(characterID: cardID, voiceID: voice.id)
            await load()
        } catch let error as ApiError {
            message = error.fallbackMessage
        } catch {
            message = ApiError.unexpectedResponse(status: 0).fallbackMessage
        }
    }

    /// 试听报价（`dry_run`），给确认弹窗用。
    func previewQuote(_ voice: CharacterVoiceView) async -> VoicePreviewResponse? {
        try? await apiClient.previewVoice(characterID: cardID, voiceID: voice.id, dryRun: true)
    }

    /// 提交一次试听；同一个音色复用同一个幂等键直到成功，然后轮询到任务结束再刷新。
    func generatePreview(_ voice: CharacterVoiceView) async {
        busyVoiceID = voice.id
        defer { busyVoiceID = nil }
        let operation = "voice-preview-\(voice.id)"
        do {
            let key = await environment.idempotencyKeys.key(for: operation)
            let response = try await apiClient.previewVoice(
                characterID: cardID, voiceID: voice.id, dryRun: false, idempotencyKey: key
            )
            await environment.idempotencyKeys.invalidate(operationID: operation)
            await load()
            guard let jobID = response.jobID else { return }
            while true {
                try await Task.sleep(for: .seconds(3))
                let job = try await apiClient.fetchGenerationJob(id: jobID)
                if job.status.value?.isTerminal ?? true {
                    if job.status.value != .succeeded { message = L10n.t("iosCharacters.previewFailed") }
                    break
                }
            }
            await load()
        } catch is CancellationError {
            return
        } catch let error as ApiError {
            message = error.fallbackMessage
        } catch {
            message = L10n.t("iosCharacters.previewFailed")
        }
    }

    func saveProfile(name: String, description: String, voiceDescription: String) async -> Bool {
        do {
            _ = try await apiClient.updateCharacterProfile(
                id: cardID,
                CharacterProfileUpdate(name: name, description: description, voiceDescription: voiceDescription)
            )
            message = L10n.t("iosCharacters.saved")
            await load()
            return true
        } catch let error as ApiError {
            message = error.fallbackMessage
            return false
        } catch {
            message = ApiError.unexpectedResponse(status: 0).fallbackMessage
            return false
        }
    }

    /// 根据关联剧本起草描述；只返回草稿，不保存。
    func describe() async -> CharacterDescribeResponse? {
        do {
            return try await apiClient.describeCharacter(id: cardID)
        } catch let error as ApiError {
            message = error.fallbackMessage
            return nil
        } catch {
            message = L10n.t("characters.describeFailed")
            return nil
        }
    }
}
