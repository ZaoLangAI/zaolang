import SwiftUI
import ZaolangKit

/// 一张图的全屏查看：同组版本横排可切换，候选版本可「定稿这张」。
struct EntryViewerSheet: View {
    let graph: AssetGraphResponse
    let viewModel: CharacterDetailViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var current: AssetEntryView

    init(graph: AssetGraphResponse, entry: AssetEntryView, viewModel: CharacterDetailViewModel) {
        self.graph = graph
        self.viewModel = viewModel
        _current = State(initialValue: entry)
    }

    private var group: [AssetEntryView] {
        let index = CharacterGraphModel.versionIndex(graph)
        let head = index.headOf[current.id] ?? current.id
        return index.versions[head] ?? [current]
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                RemoteImage(url: current.url.flatMap(URL.init(string:)), aspectRatio: 1, contentMode: .fit)
                    .frame(maxWidth: .infinity)
                Text(L10n.t("assetVariants.type.\(current.entryType)"))
                    .font(.subheadline)
                    .foregroundStyle(Color.zl.textMuted)
                if group.count > 1 {
                    Text(L10n.t("assetGraph.sectionVersions", ["count": group.count]))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.zl.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(group) { version in
                                Button { current = version } label: {
                                    RemoteImage(url: version.url.flatMap(URL.init(string:)), aspectRatio: 1)
                                        .frame(width: 64, height: 64)
                                        .zlCornerRadius(ZLRadius.sm)
                                        .overlay {
                                            RoundedRectangle.zl(ZLRadius.sm)
                                                .stroke(version.id == current.id ? Color.zl.primary : Color.zl.border, lineWidth: 2)
                                        }
                                        .opacity(version.isCandidate ? 0.7 : 1)
                                }
                                .buttonStyle(.plain)
                                .frame(minWidth: 44, minHeight: 44)
                                .accessibilityLabel(
                                    version.isCandidate ? L10n.t("assetVariants.candidate") : L10n.t("assetGraph.versionCurrent")
                                )
                            }
                        }
                    }
                }
                if current.isCandidate {
                    Button {
                        Task {
                            await viewModel.approve(current)
                            dismiss()
                        }
                    } label: {
                        Text(L10n.t("iosCharacters.approve")).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(viewModel.approvingID != nil)
                }
                Spacer(minLength: 0)
            }
            .padding(16)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L10n.t("actions.close")) { dismiss() }
                }
            }
        }
    }
}
