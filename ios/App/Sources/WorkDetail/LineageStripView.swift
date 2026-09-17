import SwiftUI
import ZaolangKit

/// 对应 `components/work/lineage-strip.tsx`：最近 3 个祖先头像 + 箭头 + 当前作品高亮节点 +
/// 下游数量气泡。墓碑祖先占位但不显示头像，缺席会让链条看起来像是"从天而降"。
struct LineageStripView: View {
    let workID: String
    let ancestors: [LineageAncestor]
    let author: AuthorSummary
    let descendantCount: Int
    let onOpenLineage: () -> Void

    /// 由远到近排序：`chain.first` 是最远的祖先（原作），`chain.last` 是当前作品的直接父版本。
    private var chain: [LineageAncestor] { ancestors.sorted { $0.depth > $1.depth } }
    private var shown: [LineageAncestor] { Array(chain.suffix(3)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                HStack(spacing: 6) {
                    Text(L10n.t("work.lineage")).font(.subheadline.weight(.semibold))
                    Text("\(L10n.t("work.remix")) \(descendantCount)")
                        .font(.caption)
                        .foregroundStyle(Color.zl.textMuted)
                }
                Spacer()
                Button(action: onOpenLineage) {
                    HStack(spacing: 2) {
                        Text(L10n.t("work.viewLineage"))
                        Image(systemName: "chevron.right").accessibilityHidden(true)
                    }
                    .font(.caption)
                    .foregroundStyle(Color.zl.textMuted)
                    .frame(minHeight: 44)
                }
                .contentShape(Rectangle())
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 4) {
                    ForEach(shown) { ancestor in
                        node(
                            name: ancestor.author?.displayName ?? L10n.t("lineagePanel.tombstone"),
                            avatarURL: ancestor.author?.avatarURL,
                            caption: ancestor.depth == chain.count ? L10n.t("work.original") : L10n.t("work.remix"),
                            isTombstone: ancestor.isTombstone,
                            isCurrent: false
                        )
                        arrow
                    }

                    node(
                        name: author.displayName,
                        avatarURL: author.avatarURL,
                        caption: L10n.t("work.remix"),
                        isTombstone: false,
                        isCurrent: true
                    )

                    if descendantCount > 0 {
                        arrow
                        Button(action: onOpenLineage) {
                            VStack(spacing: 6) {
                                Circle()
                                    .fill(Color.zl.surfaceSoft)
                                    .frame(width: 40, height: 40)
                                    .overlay {
                                        Text("\(descendantCount)+").font(.caption.weight(.medium))
                                    }
                                Text(L10n.t("lineagePanel.descendants"))
                                    .font(.system(size: 11))
                                    .foregroundStyle(Color.zl.textMuted)
                                    .frame(width: 64)
                                    .lineLimit(1)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .padding(16)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }

    private var arrow: some View {
        Image(systemName: "arrow.right")
            .font(.footnote)
            .foregroundStyle(Color.zl.textMuted)
            .padding(.top, 14)
            .accessibilityHidden(true) // 纯视觉分隔符，读出来对 VoiceOver 只是噪音
    }

    private func node(name: String, avatarURL: String?, caption: String, isTombstone: Bool, isCurrent: Bool) -> some View {
        VStack(spacing: 6) {
            if isTombstone {
                Circle()
                    .strokeBorder(Color.zl.border, style: StrokeStyle(lineWidth: 1, dash: [3]))
                    .frame(width: 40, height: 40)
                    .overlay {
                        Image(systemName: "xmark.seal")
                            .foregroundStyle(Color.zl.textMuted)
                    }
            } else {
                RemoteImage(url: avatarURL.flatMap(URL.init), aspectRatio: 1)
                    .frame(width: 40, height: 40)
                    .clipShape(Circle())
                    .overlay {
                        Circle().strokeBorder(isCurrent ? Color.zl.primary : .clear, lineWidth: 2)
                    }
            }
            Text(name).font(.system(size: 11)).lineLimit(1).frame(width: 64)
            Text(caption).font(.system(size: 11)).foregroundStyle(Color.zl.textMuted)
        }
        .accessibilityElement(children: .combine)
    }
}
