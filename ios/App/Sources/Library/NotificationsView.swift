import SwiftUI
import ZaolangKit

/// 通知列表，对应 `notification-list.tsx`。挂在我的库栈下（`LibraryRoute.notifications`）。
struct NotificationsView: View {
    @Environment(AppEnvironment.self) private var environment
    let onOpenWork: (String) -> Void
    let onOpenJob: (String) -> Void

    @State private var viewModel: NotificationsViewModel?
    @State private var filterUnreadOnly = false

    var body: some View {
        content
            .navigationTitle(L10n.t("notificationsPage.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L10n.t("notificationsPage.markAllRead")) {
                        Task { await viewModel?.markAllRead() }
                    }
                    .disabled((viewModel?.unreadCount ?? 0) == 0)
                }
            }
            .task {
                if viewModel == nil {
                    viewModel = NotificationsViewModel(apiClient: environment.apiClient)
                }
                await viewModel?.load()
            }
            .refreshable { await viewModel?.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            List { ForEach(0..<6, id: \.self) { _ in skeletonRow } }.listStyle(.plain)
        case .empty:
            EmptyStateView(title: L10n.t("notificationsPage.empty"), message: L10n.t("notificationsPage.emptyHint"))
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load() } }
        case .loaded(let items):
            listBody(items)
        }
    }

    private func listBody(_ items: [NotificationResponse]) -> some View {
        let shown = filterUnreadOnly ? items.filter { !(viewModel?.isRead($0) ?? true) } : items
        return List {
            Section {
                Picker(L10n.t("notificationsPage.title"), selection: $filterUnreadOnly) {
                    Text(L10n.t("notificationsPage.filterAll")).tag(false)
                    Text(L10n.t("notificationsPage.filterUnread")).tag(true)
                }
                .pickerStyle(.segmented)
                .listRowSeparator(.hidden)
            }
            ForEach(shown) { item in
                row(item)
            }
        }
        .listStyle(.plain)
    }

    private func row(_ item: NotificationResponse) -> some View {
        let isRead = viewModel?.isRead(item) ?? item.read
        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: item.group.systemImage)
                .frame(width: 32, height: 32)
                .background(Color.zl.surfaceSoft, in: Circle())
                .foregroundStyle(Color.zl.textMuted)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(L10n.t(item.group.labelKey)).font(.caption).foregroundStyle(Color.zl.textMuted)
                    if !isRead {
                        Circle().fill(Color.zl.primary).frame(width: 6, height: 6)
                    }
                }
                Text(item.bodyText).font(.subheadline)
                Text(item.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption2)
                    .foregroundStyle(Color.zl.textMuted)
            }

            Spacer()

            if item.destination != nil {
                Button(L10n.t("notificationsPage.open")) {
                    Task { await viewModel?.markRead(id: item.id) }
                    open(item)
                }
                .font(.caption.weight(.medium))
            }
        }
        .padding(.vertical, 4)
        .listRowBackground(isRead ? Color.clear : Color.zl.primary.opacity(0.05))
    }

    private func open(_ item: NotificationResponse) {
        guard let destination = item.destination else { return }
        switch destination {
        case .work(let workID): onOpenWork(workID)
        case .job(let jobID): onOpenJob(jobID)
        }
    }

    private var skeletonRow: some View {
        HStack(spacing: 12) {
            Circle().fill(Color.zl.skeleton).zlSkeletonPulse().frame(width: 32, height: 32)
            VStack(alignment: .leading, spacing: 6) {
                RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 12).frame(maxWidth: 200)
                RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 12).frame(maxWidth: 120)
            }
        }
    }
}
