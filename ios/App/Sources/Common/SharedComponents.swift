import SwiftUI
import ZaolangKit

/// 头像 + 显示名，作品卡片 / 详情 / 创作链节点面板到处都要用同一套。
struct AuthorRow: View {
    let author: AuthorSummary
    var avatarSize: CGFloat = 28
    var onTap: (() -> Void)?

    var body: some View {
        Button {
            onTap?()
        } label: {
            HStack(spacing: 8) {
                RemoteImage(url: author.avatarURL.flatMap(URL.init), aspectRatio: 1)
                    .frame(width: avatarSize, height: avatarSize)
                    .clipShape(Circle())
                Text(author.displayName)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.zl.text)
                    .lineLimit(1)
            }
        }
        .buttonStyle(.plain)
        .disabled(onTap == nil)
        .frame(minHeight: 44) // 头像本身常小于 44pt，靠透明内边距把点击区域补到 HIG 最小触控目标
        .contentShape(Rectangle())
    }
}

/// 标签 chip，发现页横滚、作品详情标签区、个人主页常用风格都用它。
struct TagChip: View {
    let label: String
    var selected: Bool = false

    var body: some View {
        Text(label)
            .font(.footnote.weight(.medium))
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .foregroundStyle(selected ? Color.zl.onPrimary : Color.zl.text)
            .background(selected ? Color.zl.primary : Color.zl.surfaceSoft)
            .zlCornerRadius(ZLRadius.lg)
    }
}

/// 点赞数 / 二创数一类的小图标+数字统计。图标本身对 VoiceOver 无意义，隐藏后靠
/// `a11yLabel` 补上"这个数字是什么"的语境，不然只读出孤零零一个数字。
struct StatItem: View {
    let systemImage: String
    let value: Int
    var a11yLabel: String?

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage).accessibilityHidden(true)
            Text("\(value)")
        }
        .font(.footnote.weight(.medium))
        .foregroundStyle(Color.zl.textMuted)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(a11yLabel.map { "\($0), \(value)" } ?? "\(value)")
    }
}

/// 可见性 + 是否可二创，作品卡片信息条常用的一小段拼接文案。
struct VisibilityBadge: View {
    let remixable: Bool

    var body: some View {
        Text(remixable ? L10n.t("visibility.public_remixable") : L10n.t("visibility.public_view_only"))
            .font(.caption2.weight(.medium))
            .foregroundStyle(Color.zl.textMuted)
    }
}
