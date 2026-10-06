import SwiftUI
import ZaolangKit

/// 角色 / 场景 / 道具创作的库列表：每张卡一行（代表图、名称、描述、完备度），点进卡片的资产板。
/// 新建卡片在网页端（`zaolang-ios-client` › reference-roadmap）。
struct AssetListView: View {
    let kind: AssetCardKind

    @Environment(AppEnvironment.self) private var environment
    @Environment(\.openURL) private var openURL
    @State private var viewModel: AssetListViewModel?

    var body: some View {
        content
            .navigationTitle(L10n.t(AssetSlots.titleKey(kind)))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { openWeb() } label: {
                        Label(L10n.t(AssetSlots.newCardKey(kind)), systemImage: "plus")
                    }
                }
            }
            .task {
                if viewModel == nil { viewModel = AssetListViewModel(kind: kind, apiClient: environment.apiClient) }
                await viewModel?.load()
            }
            .refreshable { await viewModel?.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            List {
                ForEach(0..<4, id: \.self) { _ in
                    RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 72)
                }
            }
            .listStyle(.plain)
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load() } }
        case .empty:
            EmptyStateView(
                title: L10n.t("\(kind.segment).emptyTitle"),
                message: L10n.t("\(kind.segment).emptyHint"),
                actionTitle: L10n.t(AssetSlots.newCardKey(kind))
            ) { openWeb() }
        case .loaded(let rows):
            List(rows) { row in
                NavigationLink(value: CreateRoute.assetDetail(kind: kind, cardID: row.id, variantID: nil)) {
                    rowView(row)
                }
            }
            .listStyle(.plain)
        }
    }

    private func rowView(_ row: AssetListRow) -> some View {
        HStack(alignment: .top, spacing: 12) {
            RemoteImage(url: row.heroURL.flatMap(URL.init(string:)), aspectRatio: 1)
                .frame(width: 64, height: 64)
                .zlCornerRadius(ZLRadius.sm)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(row.name).font(.subheadline.weight(.semibold)).foregroundStyle(Color.zl.text)
                if let description = row.description, !description.isEmpty {
                    Text(description).font(.caption).foregroundStyle(Color.zl.textMuted).lineLimit(2)
                }
                if let voice = row.voiceDescription, !voice.isEmpty {
                    Text("\(L10n.t("characters.voiceLabel")): \(voice)")
                        .font(.caption2).foregroundStyle(Color.zl.textMuted).lineLimit(1)
                }
                if let completeness = row.completeness {
                    Text(L10n.t("assetWorkspace.completeness", ["done": completeness.done, "total": completeness.total]))
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(completeness.done == completeness.total ? Color.zl.success : Color.zl.amber)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func openWeb() {
        if let url = AssetSlots.webURL(kind) { openURL(url) }
    }
}
