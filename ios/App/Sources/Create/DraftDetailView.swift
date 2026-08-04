import SwiftUI
import ZaolangKit

/// 我的库/创作中心点开一条草稿落到这里：展示当前产出，按草稿状态给出下一步动作——
/// 还在跑就去任务详情，跑完没发布就去发布页，已发布就去作品详情。三条路径互斥，
/// 不需要单独的 ViewModel 文件，状态机简单到直接在 View 里 `task` 一次拉取即可。
struct DraftDetailView: View {
    @Environment(AppEnvironment.self) private var environment
    let draftID: String
    let onOpenJob: (String) -> Void
    let onOpenPublish: (String) -> Void
    let onOpenWork: (String) -> Void

    @State private var state: LoadableState<DraftResponse> = .loading

    var body: some View {
        content
            .navigationTitle(L10n.t("createPage.recentDrafts"))
            .navigationBarTitleDisplayMode(.inline)
            .task { await load() }
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading:
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        case .empty:
            EmptyStateView(title: L10n.t("states.notFound"), message: L10n.t("publishPage.draftMissing"))
        case .failed(let error):
            ErrorStateView(error: error) { Task { await load() } }
        case .loaded(let draft):
            body(draft)
        }
    }

    private func body(_ draft: DraftResponse) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            RemoteImage(url: draft.outputURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0)
                .zlCornerRadius(ZLRadius.md)

            Text(draft.title ?? L10n.t("createPage.recentDrafts")).font(.title3.weight(.semibold))

            actionButton(draft)

            Spacer()
        }
        .padding(16)
    }

    @ViewBuilder
    private func actionButton(_ draft: DraftResponse) -> some View {
        if let workID = draft.publishedWorkID {
            Button(L10n.t("publishPage.viewWork")) { onOpenWork(workID) }
                .buttonStyle(.borderedProminent)
        } else if draft.outputAssetID != nil {
            Button(L10n.t("job.publish")) { onOpenPublish(draft.id) }
                .buttonStyle(.borderedProminent)
        } else if let jobID = draft.latestJobID {
            Button(L10n.t("jobPage.title")) { onOpenJob(jobID) }
                .buttonStyle(.borderedProminent)
        } else {
            Text(L10n.t("createPage.noDraftsHint")).font(.footnote).foregroundStyle(Color.zl.textMuted)
        }
    }

    private func load() async {
        state = .loading
        do {
            state = .loaded(try await environment.apiClient.fetchDraft(id: draftID))
        } catch let error as ApiError {
            state = error.isOffline ? .failed(error) : .empty
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
        }
    }
}
