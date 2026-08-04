import SwiftUI
import ZaolangKit

/// 创作 Tab 根屏，对应 `(site)/create/page.tsx`：三个模式卡片 + 最近草稿。
/// 未登录点任意卡片先弹登录墙（`requireAuth`），登录成功后直接把动作补跑一次。
struct CreateView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @Binding var path: NavigationPath

    @State private var viewModel: CreateViewModel

    init(path: Binding<NavigationPath>, apiClient: APIClient) {
        _path = path
        _viewModel = State(initialValue: CreateViewModel(apiClient: apiClient))
    }

    var body: some View {
        VStack(spacing: 0) {
            CreateJobBanner { jobID in path.append(CreateRoute.jobDetail(jobID: jobID)) }
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    header
                    modeCards
                    draftsSection
                }
                .padding(16)
            }
        }
        .navigationTitle(L10n.t("brand.name"))
        .task { await viewModel.load() }
        .refreshable { await viewModel.load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(L10n.t("createPage.eyebrow")).zlEyebrow()
            Text(L10n.t("createPage.title")).font(.title2.weight(.semibold))
            Text(L10n.t("createPage.subtitle")).font(.subheadline).foregroundStyle(Color.zl.textMuted)
        }
    }

    private var modeCards: some View {
        VStack(spacing: 12) {
            modeCard(
                title: L10n.t("createPage.modeTextToVideoTitle"),
                description: L10n.t("createPage.modeTextToVideoDesc"),
                tag: L10n.t("createPage.modeTextToVideoTag"),
                systemImage: "text.viewfinder"
            ) {
                start(.new(operation: .textToVideo, initialPrompt: nil))
            }
            modeCard(
                title: L10n.t("createPage.modeImageToVideoTitle"),
                description: L10n.t("createPage.modeImageToVideoDesc"),
                tag: L10n.t("createPage.modeImageToVideoTag"),
                systemImage: "photo.on.rectangle"
            ) {
                start(.new(operation: .imageToVideo, initialPrompt: nil))
            }
            modeCard(
                title: L10n.t("createPage.modeRemixTitle"),
                description: L10n.t("createPage.modeRemixDesc"),
                tag: L10n.t("createPage.modeRemixTag"),
                systemImage: "arrow.triangle.branch"
            ) {
                environment.requireAuth(actionLabel: L10n.t("createPage.modeRemixTitle")) {
                    router.selectTab(.discover)
                }
            }
        }
    }

    private func modeCard(title: String, description: String, tag: String, systemImage: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: systemImage)
                    .font(.title3)
                    .foregroundStyle(Color.zl.primary)
                    .frame(width: 36)
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Color.zl.text)
                    Text(description).font(.caption).foregroundStyle(Color.zl.textMuted)
                    Text(tag).font(.caption2.weight(.medium)).foregroundStyle(Color.zl.amber)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(Color.zl.textMuted)
            }
            .padding(16)
            .background(Color.zl.surface)
            .zlCornerRadius(ZLRadius.md)
        }
        .buttonStyle(.plain)
    }

    private func start(_ mode: StudioMode) {
        environment.requireAuth(actionLabel: L10n.t("createPage.startCreating")) {
            path.append(CreateRoute.studio(mode))
        }
    }

    @ViewBuilder
    private var draftsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L10n.t("createPage.recentDrafts")).zlEyebrow()
            switch viewModel.draftsState {
            case .loading:
                RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 72)
            case .empty:
                EmptyStateView(title: L10n.t("createPage.noDrafts"), message: L10n.t("createPage.noDraftsHint"))
            case .failed:
                EmptyView()
            case .loaded(let drafts):
                ForEach(drafts) { draft in
                    Button {
                        path.append(CreateRoute.draft(draftID: draft.id))
                    } label: {
                        HStack(spacing: 12) {
                            RemoteImage(url: draft.outputURL.flatMap(URL.init), aspectRatio: 1)
                                .frame(width: 48, height: 48)
                                .zlCornerRadius(ZLRadius.sm)
                            Text(draft.title ?? L10n.t("createPage.recentDrafts")).font(.subheadline).lineLimit(1)
                            Spacer()
                        }
                        .padding(12)
                        .background(Color.zl.surface)
                        .zlCornerRadius(ZLRadius.md)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}
