import MarkdownUI
import SwiftUI
import ZaolangKit

/// 学习内容详情，与 Web 端 `learn-body-view.tsx` 同构：正文是 markdown 源码，
/// 用 `MarkdownUI` 渲染，插图引用通过 `LearnAssetImageProvider` 换成真实签名 URL。
struct LearnPostDetailView: View {
    @Environment(AppEnvironment.self) private var environment
    let postID: String
    let onOpenAuthor: (String) -> Void

    @State private var viewModel: LearnPostDetailViewModel?

    var body: some View {
        content
            .navigationBarTitleDisplayMode(.inline)
            .task {
                if viewModel == nil {
                    viewModel = LearnPostDetailViewModel(postID: postID, apiClient: environment.apiClient)
                }
                await viewModel?.load()
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            ScrollView { skeleton }
        case .empty:
            NotFoundView(title: L10n.t("states.notFound"), message: L10n.t("states.notFoundHint"))
        case .failed(let error):
            if error.isOffline {
                ErrorStateView(error: error) { Task { await viewModel?.load() } }
            } else {
                NotFoundView(title: L10n.t("states.notFound"), message: L10n.t("states.notFoundHint"))
            }
        case .loaded(let detail):
            detailBody(detail)
        }
    }

    private var skeleton: some View {
        VStack(alignment: .leading, spacing: 16) {
            RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 200)
            RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 24).frame(maxWidth: 220)
            RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 80)
        }
        .padding(16)
    }

    private func detailBody(_ detail: LearnPostDetail) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                RemoteImage(url: detail.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0, contentMode: .fill)
                    .zlCornerRadius(ZLRadius.md)

                Text(L10n.t(levelKey(detail.level))).font(.caption.weight(.medium)).foregroundStyle(Color.zl.amber)
                Text(detail.title).font(.title3.weight(.semibold))
                Text(detail.summary).font(.subheadline).foregroundStyle(Color.zl.textMuted)

                AuthorRow(author: detail.author) { onOpenAuthor(detail.author.handle) }

                if detail.status.value == .rejected, let reason = detail.rejectReason {
                    Text(L10n.t("learnPage.rejectReasonLabel", ["reason": reason]))
                        .font(.footnote)
                        .foregroundStyle(Color.zl.danger)
                }

                Divider().padding(.vertical, 4)

                Markdown(detail.bodyMarkdown)
                    .markdownImageProvider(LearnAssetImageProvider(assetURLs: detail.assetURLs))
                    .markdownTextStyle(\.text) { ForegroundColor(Color.zl.text) }
                    .markdownTextStyle(\.link) { ForegroundColor(Color.zl.primary) }
            }
            .padding(16)
        }
        .navigationTitle(detail.title)
    }

    private func levelKey(_ level: LearnPostLevel) -> String {
        switch level {
        case .beginner: "learnPage.levelBeginner"
        case .intermediate: "learnPage.levelIntermediate"
        case .advanced: "learnPage.levelAdvanced"
        }
    }
}
