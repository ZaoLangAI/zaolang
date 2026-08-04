import SwiftUI
import ZaolangKit

/// 对应 Web 端 `work-card.tsx` / `inspiration-card.tsx` 共同的视觉：封面（左上角墓碑/可二创徽章）
/// + 标题 + 作者名与点赞数。两个 Web 组件的差异只在点击行为——瀑布墙卡片开预览 sheet，
/// 别处的卡片直接 push 详情，这里用两个可选闭包让调用方自己决定，不必分裂成两个视图。
struct WorkCardView: View {
    let work: WorkSummary
    var onTapCover: () -> Void
    var onTapAuthor: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: onTapCover) {
                RemoteImage(url: work.coverURL.flatMap(URL.init), aspectRatio: work.coverAspectRatio)
                    .zlCornerRadius(ZLRadius.md)
                    .overlay(alignment: .topLeading) { badge }
                    .grayscale(work.isTombstoned ? 1 : 0)
                    .opacity(work.isTombstoned ? 0.6 : 1)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 2) {
                Text(work.title)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.zl.text)
                    .lineLimit(1)

                HStack {
                    Button(work.author.displayName) { onTapAuthor?() }
                        .buttonStyle(.plain)
                        .font(.caption)
                        .foregroundStyle(Color.zl.textMuted)
                        .lineLimit(1)
                        .disabled(onTapAuthor == nil)

                    Spacer(minLength: 8)

                    StatItem(systemImage: "heart.fill", value: work.stats.likeCount, a11yLabel: L10n.t("work.likes"))
                }
            }
        }
    }

    @ViewBuilder
    private var badge: some View {
        if work.isTombstoned {
            Label(L10n.t("work.tombstoned"), systemImage: "xmark.seal.fill")
                .zlBadge(tone: .danger)
        } else if work.remixable {
            Text(L10n.t("work.remix"))
                .zlBadge(tone: .amber)
        }
    }
}

private enum BadgeTone {
    case danger, amber
}

private struct BadgeModifier: ViewModifier {
    let tone: BadgeTone

    func body(content: Content) -> some View {
        content
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(Color.zl.onPrimary)
            .background(tone == .danger ? Color.zl.danger : Color.zl.amber)
            .zlCornerRadius(ZLRadius.sm)
            .padding(6)
    }
}

private extension View {
    func zlBadge(tone: BadgeTone) -> some View { modifier(BadgeModifier(tone: tone)) }
}
