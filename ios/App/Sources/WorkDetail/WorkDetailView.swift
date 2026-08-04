import SwiftUI
import ZaolangKit

/// 作品详情，对应 `(site)/work/[workId]/page.tsx`（`04-screens.md` 第 6 屏）。
/// 404 与 `WORK_PRIVATE` 已经在 `ApiError.notFound` 合并，这里只需要统一渲染一种「不存在」。
struct WorkDetailView: View {
    @Environment(AppEnvironment.self) private var environment
    let workID: String
    let onOpenLineage: (String) -> Void
    let onOpenAuthor: (String) -> Void
    let onOpenWork: (String) -> Void
    let onRemix: (String) -> Void

    @State private var viewModel: WorkDetailViewModel?
    @State private var showReportSheet = false

    var body: some View {
        content
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarContent }
            .task {
                if viewModel == nil {
                    viewModel = WorkDetailViewModel(workID: workID, apiClient: environment.apiClient)
                }
                await viewModel?.load()
            }
            .sheet(isPresented: $showReportSheet) {
                ReportSheet(workID: workID, apiClient: environment.apiClient)
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            ScrollView { skeleton }
        case .empty:
            NotFoundView(title: L10n.t("states.notFound"), message: L10n.t("workPage.notFound"))
        case .failed(let error):
            if error.isOffline {
                ErrorStateView(error: error) { Task { await viewModel?.load() } }
            } else {
                NotFoundView(title: L10n.t("states.notFound"), message: L10n.t("workPage.notFound"))
            }
        case .loaded(let detail):
            detailBody(detail)
        }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Button {
                    environment.requireAuth(actionLabel: L10n.t("work.report")) {
                        showReportSheet = true
                    }
                } label: {
                    Label(L10n.t("work.report"), systemImage: "flag")
                }
            } label: {
                Image(systemName: "ellipsis")
            }
            .accessibilityLabel(L10n.t("actions.more"))
        }
        if let detail = viewModel?.state.value, let url = shareURL(for: detail.id) {
            ToolbarItem(placement: .topBarTrailing) {
                ShareLink(item: url)
            }
        }
    }

    private func shareURL(for workID: String) -> URL? {
        URL(string: "\(AppConfig.webBaseURLString)/work/\(workID)")
    }

    private func detailBody(_ detail: WorkDetail) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                WorkMediaStage(
                    mediaType: detail.mediaType,
                    mediaURL: detail.currentVersion?.mediaURL,
                    coverURL: detail.coverURL,
                    aspectRatio: detail.coverAspectRatio,
                    isTombstoned: detail.isTombstoned,
                    isOffline: environment.reachability.isOffline
                )

                titleAndAuthor(detail)
                statsRow(detail)

                if !detail.ancestors.isEmpty || detail.descendantCount > 0 {
                    sourceAndLicenseSection(detail)
                }

                if let description = detail.description, !description.isEmpty || !detail.tags.isEmpty {
                    descriptionSection(detail)
                }

                if let params = detail.reusableParams, !params.isEmpty {
                    ReusableParamsSection(params: params, version: detail.currentVersion)
                }

                if let vm = viewModel {
                    SimilarWorksSection(state: vm.similarState, onOpenWork: onOpenWork, onOpenAuthor: onOpenAuthor)
                }
            }
            .padding(16)
            .padding(.bottom, 96) // 留出固定底部按钮的空间
        }
        .safeAreaInset(edge: .bottom) { bottomBar(detail) }
    }

    private func titleAndAuthor(_ detail: WorkDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(detail.title).font(.title2.weight(.semibold)).foregroundStyle(Color.zl.text)
            HStack {
                AuthorRow(author: detail.author, avatarSize: 32) { onOpenAuthor(detail.author.handle) }
                Spacer()
                if detail.author.id != environment.me?.id {
                    let following = viewModel?.isFollowingAuthor ?? false
                    Button(L10n.t(following ? "profilePage.following" : "profilePage.follow")) {
                        environment.requireAuth(actionLabel: L10n.t("profilePage.follow")) {
                            Task { await viewModel?.toggleFollowAuthor(userID: detail.author.id) }
                        }
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
            }
            if let publishedAt = detail.publishedAt {
                Text(L10n.t("work.publishedOn", ["date": publishedAt.formatted(date: .abbreviated, time: .omitted)]))
                    .font(.caption)
                    .foregroundStyle(Color.zl.textMuted)
            }
        }
    }

    private func statsRow(_ detail: WorkDetail) -> some View {
        let liked = viewModel?.isLiked ?? detail.viewerLiked
        let likeCount = viewModel?.likeCount ?? detail.stats.likeCount
        let bookmarked = viewModel?.isBookmarked ?? detail.viewerBookmarked
        return HStack(spacing: 20) {
            Button {
                environment.requireAuth(actionLabel: L10n.t("work.like")) {
                    Task { await viewModel?.toggleLike() }
                }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: liked ? "heart.fill" : "heart")
                    Text("\(likeCount)")
                }
                .frame(minHeight: 44)
            }
            .accessibilityLabel("\(L10n.t(liked ? "work.liked" : "work.like")), \(likeCount)")
            Button {
                environment.requireAuth(actionLabel: L10n.t("work.bookmark")) {
                    Task { await viewModel?.toggleBookmark() }
                }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: bookmarked ? "star.fill" : "star")
                    Text(L10n.t("work.bookmark"))
                }
                .frame(minHeight: 44)
            }
            HStack(spacing: 4) {
                Image(systemName: "arrow.triangle.branch")
                Text(L10n.t("workPage.lineageCount", ["count": detail.stats.remixCount]))
            }
            .foregroundStyle(Color.zl.textMuted)
        }
        .font(.subheadline.weight(.medium))
        .foregroundStyle(Color.zl.text)
        .buttonStyle(.plain)
    }

    private func sourceAndLicenseSection(_ detail: WorkDetail) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L10n.t("workPage.sourceAndLicense")).font(.subheadline.weight(.semibold))

            if let closest = detail.ancestors.min(by: { $0.depth < $1.depth }) {
                Text(closest.author.map { "@\($0.handle) · \(closest.title)" } ?? closest.title)
                    .font(.footnote)
                    .foregroundStyle(Color.zl.textMuted)
            }

            if let license = detail.license {
                Text(license.attributionText)
                    .font(.caption)
                    .foregroundStyle(Color.zl.amber)
            }

            LineageStripView(
                workID: detail.id,
                ancestors: detail.ancestors,
                author: detail.author,
                descendantCount: detail.descendantCount,
                onOpenLineage: { onOpenLineage(detail.id) }
            )
        }
    }

    private func descriptionSection(_ detail: WorkDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("workPage.description")).font(.subheadline.weight(.semibold))
            if let description = detail.description, !description.isEmpty {
                Text(description).font(.footnote).foregroundStyle(Color.zl.textMuted)
            }
            if !detail.tags.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(detail.tags, id: \.self) { TagChip(label: $0) }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func bottomBar(_ detail: WorkDetail) -> some View {
        // 墓碑态二创按钮整块隐藏（`04-screens.md` 第 6 屏"两个特殊态"），不留占位条。
        if !detail.isTombstoned {
            VStack(spacing: 6) {
                if !detail.canRemix {
                    Text(L10n.t("work.notRemixable"))
                        .font(.caption)
                        .foregroundStyle(Color.zl.textMuted)
                    Button(L10n.t("work.remixThis")) {}
                        .buttonStyle(.borderedProminent)
                        .frame(maxWidth: .infinity)
                        .disabled(true)
                } else {
                    Button(L10n.t("work.remixThis")) {
                        environment.requireAuth(actionLabel: L10n.t("work.remixThis")) {
                            onRemix(detail.id)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .background(.bar)
        }
    }

    private var skeleton: some View {
        VStack(alignment: .leading, spacing: 16) {
            RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().aspectRatio(16.0 / 9.0, contentMode: .fit)
            RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 22).frame(maxWidth: 220)
            RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 16).frame(maxWidth: 140)
        }
        .padding(16)
    }
}
