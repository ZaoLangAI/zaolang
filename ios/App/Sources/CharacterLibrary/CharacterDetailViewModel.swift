import Foundation
import Observation
import ZaolangKit

/// 一个角色的管理页（iOS 只读为主）：造型图 / 音色，加三种写操作——
/// 定稿候选图、设默认音色、生成试听；角色名与描述可编辑，关联剧本时可 AI 生成。
/// 其余编辑（新建造型、调整 / 派生、关系、音色设置）在网页端。
@MainActor
@Observable
final class CharacterDetailViewModel {
    let characterID: String
    private let apiClient: APIClient
    private let keys = IdempotencyKeyStore()

    private(set) var state: LoadableState<AssetGraphResponse> = .loading
    private(set) var scriptLinks: [CharacterScriptLink] = []
    private(set) var busyVoiceID: String?
    private(set) var approvingID: String?
    var message: String?

    init(characterID: String, apiClient: APIClient) {
        self.characterID = characterID
        self.apiClient = apiClient
    }

    var graph: AssetGraphResponse? { state.value }

    func load() async {
        do {
            state = .loaded(try await apiClient.fetchAssetGraph(kind: .character, id: characterID))
        } catch let error as ApiError {
            if state.value == nil { state = .failed(error) }
        } catch {
            if state.value == nil { state = .failed(.unexpectedResponse(status: 0)) }
        }
        scriptLinks = (try? await apiClient.characterScriptLinks(id: characterID)) ?? []
    }

    func approve(_ entry: AssetEntryView) async {
        approvingID = entry.id
        defer { approvingID = nil }
        do {
            _ = try await apiClient.approveAssetEntry(kind: .character, cardID: characterID, entryID: entry.id)
            message = L10n.t("iosCharacters.approved")
            await load()
        } catch let error as ApiError {
            message = error.fallbackMessage
        } catch {
            message = ApiError.unexpectedResponse(status: 0).fallbackMessage
        }
    }

    func makeDefault(_ voice: CharacterVoiceView) async {
        busyVoiceID = voice.id
        defer { busyVoiceID = nil }
        do {
            _ = try await apiClient.makeDefaultVoice(characterID: characterID, voiceID: voice.id)
            await load()
        } catch let error as ApiError {
            message = error.fallbackMessage
        } catch {
            message = ApiError.unexpectedResponse(status: 0).fallbackMessage
        }
    }

    /// 试听报价（`dry_run`），给确认弹窗用。
    func previewQuote(_ voice: CharacterVoiceView) async -> VoicePreviewResponse? {
        try? await apiClient.previewVoice(characterID: characterID, voiceID: voice.id, dryRun: true)
    }

    /// 提交一次试听；同一个音色复用同一个幂等键直到成功，然后轮询到任务结束再刷新。
    func generatePreview(_ voice: CharacterVoiceView) async {
        busyVoiceID = voice.id
        defer { busyVoiceID = nil }
        let operation = "voice-preview-\(voice.id)"
        do {
            let key = await keys.key(for: operation)
            let response = try await apiClient.previewVoice(
                characterID: characterID, voiceID: voice.id, dryRun: false, idempotencyKey: key
            )
            await keys.invalidate(operationID: operation)
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
                id: characterID,
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
            return try await apiClient.describeCharacter(id: characterID)
        } catch let error as ApiError {
            message = error.fallbackMessage
            return nil
        } catch {
            message = L10n.t("characters.describeFailed")
            return nil
        }
    }
}
