import SwiftUI
import ZaolangKit

/// 选中节点的详情 + 与父版本的参数差异，对应 `04-screens.md` 第 7 屏底部面板。
struct VersionDiffPanel: View {
    let node: LineageGraph.Node
    let diffState: LoadableState<VersionDiffResponse>
    let onOpenWork: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Capsule().fill(Color.zl.border).frame(width: 36, height: 4)
                Spacer()
            }

            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(node.title).font(.subheadline.weight(.semibold))
                    if let author = node.author {
                        Text("@\(author.handle)").font(.caption).foregroundStyle(Color.zl.textMuted)
                    }
                }
                Spacer()
                Button {
                    onDismiss()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(Color.zl.textMuted)
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel(L10n.t("actions.close"))
            }

            diffContent

            Button(L10n.t("lineagePanel.openWork"), action: onOpenWork)
                .buttonStyle(.borderedProminent)
                .frame(maxWidth: .infinity)
        }
        .padding(16)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.lg)
        .zlRaisedShadow()
    }

    @ViewBuilder
    private var diffContent: some View {
        switch diffState {
        case .loading:
            VStack(alignment: .leading, spacing: 6) {
                ForEach(0..<3, id: \.self) { _ in
                    RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 14)
                }
            }
        case .empty:
            Text(L10n.t("lineagePanel.diffEmpty"))
                .font(.footnote)
                .foregroundStyle(Color.zl.textMuted)
        case .failed(let error):
            Text(error.fallbackMessage).font(.footnote).foregroundStyle(Color.zl.textMuted)
        case .loaded(let diff):
            VStack(alignment: .leading, spacing: 8) {
                Text(L10n.t("lineagePanel.diffTitle")).font(.caption.weight(.semibold)).foregroundStyle(Color.zl.textMuted)
                ForEach(diff.entries.filter { $0.changed }, id: \.field) { entry in
                    HStack(alignment: .top, spacing: 8) {
                        Text(entry.field)
                            .font(.caption)
                            .foregroundStyle(Color.zl.amber)
                            .frame(width: 72, alignment: .leading)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(entry.parentValue?.displayString ?? "—")
                                .font(.caption2)
                                .foregroundStyle(Color.zl.textMuted)
                                .strikethrough()
                            Text(entry.childValue?.displayString ?? "—")
                                .font(.caption)
                                .foregroundStyle(Color.zl.text)
                        }
                    }
                }
            }
        }
    }
}
