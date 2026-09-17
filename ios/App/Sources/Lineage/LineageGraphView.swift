import SwiftUI
import ZaolangKit

/// 创作链图谱，整屏 push。深度默认 3，可选到 8——
/// 手机屏幕上超过 3 层就挤得看不清，Web 默认值 4 不适合直接搬（见 `zaolang-ios-client` skill 已确认事实）。
struct LineageGraphView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.zlMotion) private var reduceMotion
    let workID: String
    let onOpenWork: (String) -> Void

    @State private var viewModel: LineageViewModel?

    var body: some View {
        content
            .navigationTitle(L10n.t("lineagePanel.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { depthMenu }
            }
            .task {
                if viewModel == nil {
                    viewModel = LineageViewModel(workID: workID, apiClient: environment.apiClient)
                }
                await viewModel?.load()
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            VStack(spacing: 12) {
                RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 220).padding(16)
                Text(L10n.t("lineagePanel.loading")).font(.footnote).foregroundStyle(Color.zl.textMuted)
                Spacer()
            }
        case .empty:
            EmptyView() // 取数不会产生这个态，graph 至少总有当前作品这一个节点（见 ViewModel 注释）
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load() } }
        case .loaded(let graph):
            graphBody(graph)
        }
    }

    private func graphBody(_ graph: LineageGraph) -> some View {
        ZStack(alignment: .bottom) {
            VStack(spacing: 0) {
                LineageCanvas(
                    graph: graph,
                    selectedNodeID: viewModel?.selectedNodeID,
                    onSelect: { viewModel?.selectNode($0) }
                )
                .frame(maxHeight: .infinity)

                if graph.nodes.count == 1 {
                    Text(L10n.t("lineagePanel.selectHint"))
                        .font(.caption)
                        .foregroundStyle(Color.zl.textMuted)
                        .padding(.vertical, 8)
                } else if graph.truncated {
                    Text(L10n.t("lineagePanel.truncated", ["count": graph.totalDescendants]))
                        .font(.caption)
                        .foregroundStyle(Color.zl.textMuted)
                        .padding(.vertical, 8)
                }
            }

            if let selectedID = viewModel?.selectedNodeID, let node = graph.nodes.first(where: { $0.id == selectedID }) {
                VersionDiffPanel(
                    node: node,
                    diffState: viewModel?.diffState ?? .empty,
                    onOpenWork: { onOpenWork(node.workID) },
                    onDismiss: { viewModel?.clearSelection() }
                )
                .padding(16)
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: viewModel?.selectedNodeID)
    }

    private var depthMenu: some View {
        Menu {
            ForEach([1, 2, 3, 4, 5, 6, 7, 8], id: \.self) { value in
                Button {
                    viewModel?.depth = value
                } label: {
                    if viewModel?.depth == value {
                        Label("\(value)", systemImage: "checkmark")
                    } else {
                        Text("\(value)")
                    }
                }
            }
        } label: {
            HStack(spacing: 4) {
                Text("\(viewModel?.depth ?? 3)")
                Image(systemName: "chevron.down")
            }
            .font(.footnote.weight(.medium))
            .frame(minWidth: 44, minHeight: 44)
        }
    }
}
