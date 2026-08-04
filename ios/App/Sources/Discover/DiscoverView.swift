import SwiftUI
import ZaolangKit

/// 发现栈的根屏。对应 `(site)/discover/page.tsx`：Hero + 标签横滚 + 排序/筛选 + 双列瀑布墙。
/// 灵感预览用 sheet（不进栈），作品详情 / 创作链 / 他人主页用 push。
struct DiscoverView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @Binding var path: NavigationPath

    @State private var viewModel: DiscoverViewModel
    @State private var searchHistory = SearchHistoryStore()
    @State private var searchText = ""
    @State private var previewWork: WorkSummary?

    init(path: Binding<NavigationPath>, apiClient: APIClient) {
        _path = path
        _viewModel = State(initialValue: DiscoverViewModel(apiClient: apiClient))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                heroSection
                inspirationSection
            }
            .padding(.bottom, 24)
        }
        .navigationTitle(L10n.t("brand.name"))
        .searchable(text: $searchText, prompt: L10n.t("actions.search"))
        .searchSuggestions {
            ForEach(searchHistory.recentQueries, id: \.self) { query in
                Button {
                    searchText = query
                    submitSearch()
                } label: {
                    Label(query, systemImage: "clock.arrow.circlepath")
                }
            }
        }
        .onSubmit(of: .search) { submitSearch() }
        .refreshable { await viewModel.refresh() }
        .task { await viewModel.loadInitial() }
        .sheet(item: $previewWork) { work in
            NavigationStack {
                InspirationPreviewSheet(
                    work: work,
                    apiClient: environment.apiClient,
                    onCreateFromPrompt: { prompt in
                        previewWork = nil
                        environment.requireAuth(actionLabel: L10n.t("discover.createFromPrompt")) {
                            router.selectTab(.create)
                            router.createPath.append(CreateRoute.studio(.new(operation: .textToVideo, initialPrompt: prompt)))
                        }
                    },
                    onOpenLineage: {
                        previewWork = nil
                        path.append(DiscoverRoute.lineage(workID: work.id))
                    },
                    onOpenWork: {
                        previewWork = nil
                        path.append(DiscoverRoute.workDetail(workID: work.id))
                    }
                )
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(L10n.t("actions.close")) { previewWork = nil }
                    }
                }
            }
        }
    }

    private func submitSearch() {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }
        searchHistory.record(query)
        path.append(DiscoverRoute.searchResults(query: query))
    }

    // MARK: - Hero

    @ViewBuilder
    private var heroSection: some View {
        switch viewModel.heroState {
        case .loading:
            RoundedRectangle.zl(ZLRadius.md)
                .fill(Color.zl.skeleton)
                .zlSkeletonPulse()
                .aspectRatio(16.0 / 9.0, contentMode: .fit)
                .padding(.horizontal, 16)
        case .empty, .failed:
            EmptyView()
        case .loaded(let work):
            heroCard(work)
        }
    }

    private func heroCard(_ work: WorkSummary) -> some View {
        Button {
            path.append(DiscoverRoute.workDetail(workID: work.id))
        } label: {
            ZStack(alignment: .bottomLeading) {
                RemoteImage(url: work.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0, contentMode: .fill)

                LinearGradient(
                    colors: [.clear, .black.opacity(0.75)],
                    startPoint: .center,
                    endPoint: .bottom
                )

                VStack(alignment: .leading, spacing: 4) {
                    Text(L10n.t("discover.featuredLabel"))
                        .zlEyebrow()
                    Text(work.title)
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(.white)
                    HStack(spacing: 6) {
                        Text(work.author.displayName)
                        Text("·")
                        VisibilityBadge(remixable: work.remixable)
                    }
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.85))
                }
                .padding(16)
            }
        }
        .buttonStyle(.plain)
        .zlCornerRadius(ZLRadius.md)
        .padding(.horizontal, 16)
        .zlCardShadow()
    }

    // MARK: - 灵感瀑布墙

    private var inspirationSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(L10n.t("discover.inspiration")).zlEyebrow()
                Text(L10n.t("discover.inspirationHint"))
                    .font(.footnote)
                    .foregroundStyle(Color.zl.textMuted)
            }
            .padding(.horizontal, 16)

            tagsRow

            filterRow

            feedContent
        }
    }

    @ViewBuilder
    private var tagsRow: some View {
        if case .loaded(let tags) = viewModel.tagsState {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    Button {
                        Task { await viewModel.setTag(nil) }
                    } label: {
                        TagChip(label: L10n.t("discover.allTags"), selected: viewModel.selectedTag == nil)
                    }
                    ForEach(tags) { tag in
                        Button {
                            Task { await viewModel.setTag(tag.slug) }
                        } label: {
                            TagChip(label: tag.label(for: CurrentAppLocale.value), selected: viewModel.selectedTag == tag.slug)
                        }
                    }
                }
                .padding(.horizontal, 16)
            }
        }
    }

    private var filterRow: some View {
        HStack {
            Menu {
                ForEach(WorksSort.allCases, id: \.self) { sort in
                    Button(sortLabel(sort)) { Task { await viewModel.setSort(sort) } }
                }
            } label: {
                Label(sortLabel(viewModel.sort), systemImage: "arrow.up.arrow.down")
                    .font(.footnote.weight(.medium))
                    .frame(minHeight: 44)
            }

            Spacer()

            Toggle(
                L10n.t("discover.remixableOnly"),
                isOn: Binding(
                    get: { viewModel.remixableOnly },
                    set: { value in Task { await viewModel.setRemixableOnly(value) } }
                )
            )
            .font(.footnote)
            .foregroundStyle(Color.zl.textMuted)
            .fixedSize()
        }
        .padding(.horizontal, 16)
    }

    private func sortLabel(_ sort: WorksSort) -> String {
        switch sort {
        case .recent: L10n.t("discover.sortRecent")
        case .popular: L10n.t("discover.sortPopular")
        case .remixed: L10n.t("discover.sortRemixed")
        }
    }

    @ViewBuilder
    private var feedContent: some View {
        switch viewModel.feedState {
        case .loading:
            skeletonGrid
        case .empty:
            EmptyStateView(
                title: L10n.t("discover.emptyFeed"),
                message: L10n.t("discover.emptyFeedHint")
            )
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel.loadFeed(reset: true) } }
        case .loaded(let items):
            WaterfallGrid(items: items, aspectRatio: { $0.coverAspectRatio }) { work in
                WorkCardView(
                    work: work,
                    onTapCover: { previewWork = work },
                    onTapAuthor: { path.append(DiscoverRoute.profile(handle: work.author.handle)) }
                )
                .task { await viewModel.loadMoreIfNeeded(currentItem: work) }
            }
            .padding(.horizontal, 16)

            if viewModel.isLoadingMore {
                ProgressView().padding(.top, 12).frame(maxWidth: .infinity)
            }
        }
    }

    private var skeletonGrid: some View {
        HStack(spacing: 12) {
            ForEach(0..<2, id: \.self) { _ in
                VStack(spacing: 12) {
                    ForEach(0..<3, id: \.self) { _ in
                        RoundedRectangle.zl(ZLRadius.md)
                            .fill(Color.zl.skeleton)
                            .zlSkeletonPulse()
                            .aspectRatio(3.0 / 4.0, contentMode: .fit)
                    }
                }
            }
        }
        .padding(.horizontal, 16)
    }
}
