import SwiftUI
import ZaolangKit

/// 学习栈根屏，对应 `(site)/learn/page.tsx`：Hero + 用户发表的学习内容列表 + 创作者安全区块。
/// 内容完全由已通过审核的 `LearnPost` 驱动，不再借用作品封面或本地硬编码课程。
struct LearnView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @Binding var path: NavigationPath

    @State private var viewModel: LearnViewModel?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                hero
                pathsSection
                safetySection
            }
            .padding(16)
        }
        .navigationTitle(L10n.t("nav.learn"))
        .task {
            if viewModel == nil {
                viewModel = LearnViewModel(apiClient: environment.apiClient)
            }
            await viewModel?.load()
        }
        .refreshable { await viewModel?.load() }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 0) {
            RemoteImage(url: viewModel?.heroPost?.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0, contentMode: .fill)
                .zlCornerRadius(ZLRadius.md)

            VStack(alignment: .leading, spacing: 10) {
                Text(L10n.t("learnPage.eyebrow")).zlEyebrow()
                Text(L10n.t("learnPage.heroTitle")).font(.title2.weight(.bold))
                Text(L10n.t("learnPage.heroSubtitle"))
                    .font(.subheadline)
                    .foregroundStyle(Color.zl.textMuted)

                Button {
                    router.selectTab(.create)
                } label: {
                    Label(L10n.t("learnPage.startFirst"), systemImage: "sparkles")
                }
                .buttonStyle(.borderedProminent)
            }
            .padding(.top, 16)
        }
    }

    @ViewBuilder
    private var pathsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(L10n.t("learnPage.listTitle")).font(.headline)
                Text(L10n.t("learnPage.listHint")).font(.caption).foregroundStyle(Color.zl.textMuted)
            }

            switch viewModel?.postsState ?? .loading {
            case .loading:
                RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 140)
            case .empty:
                EmptyStateView(
                    title: L10n.t("learnPage.empty"),
                    message: L10n.t("learnPage.emptyHint"),
                    actionTitle: L10n.t("learnPage.startFirst")
                ) {
                    environment.requireAuth(actionLabel: L10n.t("createPage.modeLearnPublishTitle")) {
                        path.append(LearnRoute.publish)
                    }
                }
            case .failed(let error):
                ErrorStateView(error: error) { Task { await viewModel?.load() } }
            case .loaded(let posts):
                ForEach(posts) { post in
                    Button {
                        path.append(LearnRoute.postDetail(postID: post.id))
                    } label: {
                        LearnPostCardView(post: post)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var safetySection: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "shield.fill")
                .foregroundStyle(Color.zl.amber)
                .frame(width: 36, height: 36)
                .background(Color.zl.amber.opacity(0.15))
                .zlCornerRadius(ZLRadius.sm)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4) {
                Text(L10n.t("learnPage.safetyEyebrow")).zlEyebrow()
                Text(L10n.t("learnPage.safetyTitle")).font(.headline)
                Text(L10n.t("learnPage.safetyBody"))
                    .font(.footnote)
                    .foregroundStyle(Color.zl.textMuted)

                if let example = viewModel?.heroPost {
                    Button(L10n.t("learnPage.viewExample")) {
                        path.append(LearnRoute.postDetail(postID: example.id))
                    }
                    .buttonStyle(.bordered)
                    .padding(.top, 4)
                }
            }
        }
        .padding(16)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }
}

/// 学习内容卡片：封面 + 等级 chip + 标题 + 简介 + 作者，替代旧的硬编码课程卡。
private struct LearnPostCardView: View {
    let post: LearnPostSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            RemoteImage(url: post.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0, contentMode: .fill)

            VStack(alignment: .leading, spacing: 4) {
                Text(L10n.t(levelKey)).font(.caption2.weight(.medium)).foregroundStyle(Color.zl.amber)
                Text(post.title).font(.subheadline.weight(.semibold)).foregroundStyle(Color.zl.text)
                Text(post.summary).font(.caption).foregroundStyle(Color.zl.textMuted).lineLimit(2)
                Text(L10n.t("learnPage.byAuthor", ["name": post.author.displayName]))
                    .font(.caption2)
                    .foregroundStyle(Color.zl.textMuted)
            }
            .padding(12)
        }
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }

    private var levelKey: String {
        switch post.level {
        case .beginner: "learnPage.levelBeginner"
        case .intermediate: "learnPage.levelIntermediate"
        case .advanced: "learnPage.levelAdvanced"
        }
    }
}
