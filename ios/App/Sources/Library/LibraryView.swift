import SwiftUI
import ZaolangKit

/// 我的库栈根屏，对应 `(site)/collection/page.tsx`：作品/草稿/收藏/合集四段。
/// 未登录时整屏是登录墙——库本身就是账号数据，没有游客态。
struct LibraryView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @Binding var path: NavigationPath

    @State private var viewModel: LibraryViewModel?
    @State private var segment: LibrarySegment = .works
    @State private var showNewCollectionSheet = false

    var body: some View {
        Group {
            if environment.isAuthenticated {
                content
            } else {
                signedOutState
            }
        }
        .navigationTitle(L10n.t("collectionPage.title"))
        .toolbar { toolbarContent }
        .task(id: environment.isAuthenticated) {
            guard environment.isAuthenticated else { return }
            if viewModel == nil {
                viewModel = LibraryViewModel(apiClient: environment.apiClient)
            }
            await viewModel?.load(handle: environment.me?.profile?.handle)
        }
        .refreshable {
            await viewModel?.load(handle: environment.me?.profile?.handle)
        }
        .sheet(isPresented: $showNewCollectionSheet) {
            NewCollectionSheet { name, isPublic in
                Task { await viewModel?.createCollection(name: name, isPublic: isPublic) }
            }
        }
    }

    private var signedOutState: some View {
        EmptyStateView(
            title: L10n.t("collectionPage.title"),
            message: L10n.t("collectionPage.subtitle"),
            actionTitle: L10n.t("auth.signIn")
        ) {
            environment.requireAuth(actionLabel: L10n.t("collectionPage.title")) {}
        }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        if environment.isAuthenticated {
            ToolbarItem(placement: .topBarLeading) {
                Button {
                    path.append(LibraryRoute.notifications)
                } label: {
                    ZStack(alignment: .topTrailing) {
                        Image(systemName: "bell")
                        if let count = viewModel?.unreadCount, count > 0 {
                            Circle()
                                .fill(Color.zl.danger)
                                .frame(width: 8, height: 8)
                                .offset(x: 2, y: -2)
                        }
                    }
                }
                .accessibilityLabel(L10n.t("notificationsPage.title"))
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    path.append(LibraryRoute.settings)
                } label: {
                    Image(systemName: "gearshape")
                }
                .accessibilityLabel(L10n.t("settingsPage.title"))
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        VStack(spacing: 0) {
            statRow
            segmentPicker
            ScrollView {
                segmentContent
                    .padding(.horizontal, 16)
                    .padding(.top, 12)
                    .padding(.bottom, 24)
            }
        }
    }

    private var statRow: some View {
        HStack {
            statTile(worksCount, L10n.t("collectionPage.statAll"))
            statTile(draftsCount, L10n.t("collectionPage.statDrafts"))
            statTile(bookmarksCount, L10n.t("collectionPage.tabBookmarks"))
            statTile(collectionsCount, L10n.t("collectionPage.collections"))
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
    }

    private var worksCount: Int { viewModel?.worksState.value?.count ?? 0 }
    private var draftsCount: Int { viewModel?.draftsState.value?.count ?? 0 }
    private var bookmarksCount: Int { viewModel?.bookmarksState.value?.count ?? 0 }
    private var collectionsCount: Int { viewModel?.collectionsState.value?.count ?? 0 }

    private func statTile(_ value: Int, _ label: String) -> some View {
        VStack(spacing: 2) {
            Text("\(value)").font(.subheadline.weight(.semibold))
            Text(label).font(.caption2).foregroundStyle(Color.zl.textMuted)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }

    private var segmentPicker: some View {
        Picker(L10n.t("collectionPage.title"), selection: $segment) {
            ForEach(LibrarySegment.allCases) { seg in
                Text(L10n.t(seg.titleKey)).tag(seg)
            }
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, 16)
        .padding(.top, 12)
    }

    @ViewBuilder
    private var segmentContent: some View {
        switch segment {
        case .works:
            worksGrid
        case .drafts:
            draftsList
        case .bookmarks:
            bookmarksGrid
        case .collections:
            collectionsGrid
        }
    }

    @ViewBuilder
    private var worksGrid: some View {
        switch viewModel?.worksState ?? .loading {
        case .loading:
            skeletonGrid
        case .empty:
            EmptyStateView(
                title: L10n.t("collectionPage.empty"),
                message: L10n.t("collectionPage.emptyHint"),
                actionTitle: L10n.t("collectionPage.createNew")
            ) { router.selectTab(.create) }
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load(handle: environment.me?.profile?.handle) } }
        case .loaded(let items):
            WaterfallGrid(items: items, aspectRatio: { $0.coverAspectRatio }) { work in
                WorkCardView(work: work, onTapCover: { path.append(LibraryRoute.workDetail(workID: work.id)) }, onTapAuthor: nil)
            }
        }
    }

    @ViewBuilder
    private var bookmarksGrid: some View {
        switch viewModel?.bookmarksState ?? .loading {
        case .loading:
            skeletonGrid
        case .empty:
            EmptyStateView(title: L10n.t("collectionPage.empty"), message: L10n.t("collectionPage.emptyHint"))
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load(handle: environment.me?.profile?.handle) } }
        case .loaded(let items):
            WaterfallGrid(items: items, aspectRatio: { $0.coverAspectRatio }) { work in
                WorkCardView(work: work, onTapCover: { path.append(LibraryRoute.workDetail(workID: work.id)) }, onTapAuthor: nil)
            }
        }
    }

    @ViewBuilder
    private var draftsList: some View {
        switch viewModel?.draftsState ?? .loading {
        case .loading:
            VStack(spacing: 12) {
                ForEach(0..<3, id: \.self) { _ in
                    RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 72)
                }
            }
        case .empty:
            EmptyStateView(
                title: L10n.t("createPage.noDrafts"),
                message: L10n.t("createPage.noDraftsHint"),
                actionTitle: L10n.t("createPage.startCreating")
            ) { router.selectTab(.create) }
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load(handle: environment.me?.profile?.handle) } }
        case .loaded(let items):
            VStack(spacing: 12) {
                ForEach(items) { draft in
                    DraftRow(
                        draft: draft,
                        onTap: {
                            router.selectTab(.create)
                            router.createPath.append(CreateRoute.draft(draftID: draft.id))
                        },
                        onDelete: { Task { await viewModel?.deleteDraft(id: draft.id) } }
                    )
                }
            }
        }
    }

    @ViewBuilder
    private var collectionsGrid: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                showNewCollectionSheet = true
            } label: {
                Label(L10n.t("collectionPage.newCollection"), systemImage: "plus.circle")
            }
            .buttonStyle(.bordered)

            switch viewModel?.collectionsState ?? .loading {
            case .loading:
                RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 80)
            case .empty:
                EmptyStateView(title: L10n.t("collectionPage.empty"), message: L10n.t("collectionPage.emptyHint"))
            case .failed(let error):
                ErrorStateView(error: error) { Task { await viewModel?.load(handle: environment.me?.profile?.handle) } }
            case .loaded(let items):
                ForEach(items) { collection in
                    CollectionRow(collection: collection)
                }
            }
        }
    }

    private var skeletonGrid: some View {
        HStack(spacing: 12) {
            ForEach(0..<2, id: \.self) { _ in
                VStack(spacing: 12) {
                    ForEach(0..<2, id: \.self) { _ in
                        RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().aspectRatio(3.0 / 4.0, contentMode: .fit)
                    }
                }
            }
        }
    }
}

private struct DraftRow: View {
    let draft: DraftResponse
    let onTap: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onTap) {
                HStack(spacing: 12) {
                    RemoteImage(url: draft.outputURL.flatMap(URL.init), aspectRatio: 1)
                        .frame(width: 56, height: 56)
                        .zlCornerRadius(ZLRadius.sm)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(draft.title ?? L10n.t("createPage.recentDrafts"))
                            .font(.subheadline.weight(.medium))
                            .lineLimit(1)
                        Text(draft.isRemix ? L10n.t("createPage.modeRemixTitle") : L10n.t("createPage.modeTextToVideoTitle"))
                            .font(.caption)
                            .foregroundStyle(Color.zl.textMuted)
                    }
                    Spacer()
                }
            }
            .buttonStyle(.plain)
            Button(role: .destructive, action: onDelete) {
                Image(systemName: "trash")
            }
            .frame(minWidth: 44, minHeight: 44)
        }
        .padding(12)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }
}

private struct CollectionRow: View {
    let collection: CollectionResponse

    var body: some View {
        HStack(spacing: 12) {
            HStack(spacing: -12) {
                ForEach(collection.coverURLs.prefix(3), id: \.self) { url in
                    RemoteImage(url: URL(string: url), aspectRatio: 1)
                        .frame(width: 40, height: 40)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay { RoundedRectangle(cornerRadius: 8).strokeBorder(Color.zl.bg, lineWidth: 2) }
                }
            }
            .frame(width: 56, alignment: .leading)

            VStack(alignment: .leading, spacing: 2) {
                Text(collection.name).font(.subheadline.weight(.medium))
                Text(L10n.t("profilePage.statWorks") + " \(collection.itemCount)")
                    .font(.caption)
                    .foregroundStyle(Color.zl.textMuted)
            }
            Spacer()
        }
        .padding(12)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }
}

private struct NewCollectionSheet: View {
    let onCreate: (String, Bool) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var isPublic = true

    var body: some View {
        NavigationStack {
            Form {
                TextField(L10n.t("collectionPage.collectionName"), text: $name)
                Toggle(L10n.t("collectionPage.collectionPublic"), isOn: $isPublic)
            }
            .navigationTitle(L10n.t("collectionPage.newCollection"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.t("actions.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L10n.t("actions.confirm")) {
                        onCreate(name, isPublic)
                        dismiss()
                    }
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }
}
