import SwiftUI
import ZaolangKit

/// 空态：`states.empty` 规范要求「一句解释 + 一个出口动作」，禁止只写「暂无数据」。
struct EmptyStateView: View {
    let title: String
    let message: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        VStack(spacing: 12) {
            Text(title)
                .font(.headline)
                .foregroundStyle(Color.zl.text)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color.zl.textMuted)
                .multilineTextAlignment(.center)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.bordered)
                    .padding(.top, 4)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity)
    }
}

/// 错误态：能重试的给重试按钮；`request_id` 永不直接展示（`04-screens.md` 全局状态规范）。
struct ErrorStateView: View {
    let error: ApiError
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            Text(L10n.t("states.error"))
                .font(.headline)
                .foregroundStyle(Color.zl.text)
            Text(error.fallbackMessage)
                .font(.subheadline)
                .foregroundStyle(Color.zl.textMuted)
                .multilineTextAlignment(.center)
            Button(L10n.t("actions.retry"), action: retry)
                .buttonStyle(.bordered)
                .padding(.top, 4)
        }
        .padding(24)
        .frame(maxWidth: .infinity)
    }
}

/// 顶部离线横幅：「不遮挡内容」——用条状插在导航栏下面，不用全屏遮罩。
struct OfflineBanner: View {
    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "wifi.slash").accessibilityHidden(true)
            Text(L10n.t("states.offline"))
        }
        .font(.footnote.weight(.medium))
        .foregroundStyle(Color.zl.onPrimary)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .background(Color.zl.danger)
        .accessibilityElement(children: .combine)
    }
}

/// 404 与 `WORK_PRIVATE` 合并后的统一「不存在」呈现，标题/文案按调用方传入的命名空间 key 走
/// （作品详情用 `workPage.notFound`，个人主页用 handle 不存在直接复用 `states.notFound`）。
struct NotFoundView: View {
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "questionmark.circle")
                .font(.system(size: 32))
                .foregroundStyle(Color.zl.textMuted)
                .accessibilityHidden(true)
            Text(title)
                .font(.headline)
                .foregroundStyle(Color.zl.text)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color.zl.textMuted)
                .multilineTextAlignment(.center)
        }
        .padding(24)
        .frame(maxWidth: .infinity)
    }
}
