import Observation
import ZaolangKit

/// 发布页：验收要点是"两个确认框未勾时按钮不可点、默认可见性是 `public_view_only`"
/// （`roadmap.md` M3 验收清单），这两条都在 `canPublish`/`visibility` 初值上体现。
@MainActor
@Observable
final class PublishViewModel {
    private let apiClient: APIClient
    let draftID: String

    private(set) var loadState: LoadableState<DraftResponse> = .loading

    var title = ""
    var description = ""
    var visibility: Visibility = .publicViewOnly
    var tagsText = ""
    var rightsConfirmed = false
    var aiDisclosureConfirmed = false

    private(set) var isPublishing = false
    private(set) var publishError: String?
    private(set) var publishResult: PublishResponse?

    init(draftID: String, apiClient: APIClient) {
        self.draftID = draftID
        self.apiClient = apiClient
    }

    var canPublish: Bool {
        !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && rightsConfirmed && aiDisclosureConfirmed && !isPublishing
    }

    func load() async {
        loadState = .loading
        do {
            let draft = try await apiClient.fetchDraft(id: draftID)
            if draft.publishedWorkID != nil || draft.outputAssetID == nil {
                loadState = .empty
                return
            }
            if title.isEmpty { title = draft.title ?? "" }
            loadState = .loaded(draft)
        } catch let error as ApiError {
            loadState = .failed(error)
        } catch {
            loadState = .failed(.unexpectedResponse(status: 0))
        }
    }

    func publish() async {
        guard canPublish, let draft = loadState.value else { return }
        isPublishing = true
        publishError = nil
        defer { isPublishing = false }
        let tags = tagsText
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        do {
            publishResult = try await apiClient.publishDraft(id: draftID, PublishRequest(
                title: title,
                description: description.isEmpty ? nil : description,
                visibility: visibility,
                tags: tags,
                coverAssetID: draft.outputAssetID,
                rightsConfirmed: rightsConfirmed,
                aiDisclosureConfirmed: aiDisclosureConfirmed
            ))
        } catch let error as ApiError {
            publishError = error.fallbackMessage
        } catch {
            publishError = L10n.t("settingsPage.saveFailed")
        }
    }
}
