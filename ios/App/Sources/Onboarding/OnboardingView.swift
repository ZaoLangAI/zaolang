import SwiftUI

/// 三页首次启动引导（`roadmap.md` M4）。文案来自 `iosOnboarding` 命名空间——iOS 专属界面，
/// 没有对应的 Web 页面，源头仍然是 `front/src/i18n/messages/*.json`，不在客户端单边发明文案
/// （新增时先把 key 加进三语消息文件，再补进 `gen-strings.py` 的命名空间列表）。
struct OnboardingView: View {
    let onFinished: () -> Void

    private let pages: [(systemImage: String, titleKey: String, bodyKey: String)] = [
        ("arrow.triangle.branch", "iosOnboarding.page1Title", "iosOnboarding.page1Body"),
        ("wand.and.stars", "iosOnboarding.page2Title", "iosOnboarding.page2Body"),
        ("sparkles.rectangle.stack", "iosOnboarding.page3Title", "iosOnboarding.page3Body"),
    ]

    @State private var pageIndex = 0

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                Button(L10n.t("iosOnboarding.skip")) { onFinished() }
                    .font(.subheadline)
                    .foregroundStyle(Color.zl.textMuted)
                    .padding(16)
            }

            TabView(selection: $pageIndex) {
                ForEach(pages.indices, id: \.self) { index in
                    pageView(pages[index]).tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .always))

            Button {
                if pageIndex == pages.count - 1 {
                    onFinished()
                } else {
                    withAnimation { pageIndex += 1 }
                }
            } label: {
                Text(pageIndex == pages.count - 1 ? L10n.t("iosOnboarding.getStarted") : L10n.t("iosOnboarding.next"))
                    .font(.body.weight(.semibold))
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .padding(16)
        }
        .background(Color.zl.bg)
    }

    private func pageView(_ page: (systemImage: String, titleKey: String, bodyKey: String)) -> some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: page.systemImage)
                .font(.system(size: 64))
                .foregroundStyle(Color.zl.primary)
                .accessibilityHidden(true)
            Text(L10n.t(page.titleKey))
                .font(.title2.weight(.bold))
                .multilineTextAlignment(.center)
            Text(L10n.t(page.bodyKey))
                .font(.body)
                .foregroundStyle(Color.zl.textMuted)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Spacer()
            Spacer()
        }
    }
}

/// 首次启动判定：`UserDefaults` 存一个布尔位，看没看过引导跟登录态无关——
/// 游客也该看一遍，不是登录后才判断。
enum OnboardingState {
    private static let key = "ai.zaolang.hasSeenOnboarding"

    static var hasSeen: Bool {
        get { UserDefaults.standard.bool(forKey: key) }
        set { UserDefaults.standard.set(newValue, forKey: key) }
    }
}
