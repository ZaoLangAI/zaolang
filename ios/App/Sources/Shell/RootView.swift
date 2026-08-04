import SwiftUI

/// App 的根视图：先等 `AppEnvironment.bootstrap()`（恢复会话 + 拉一次 `/v1/auth/me`）
/// 跑完再解析 Universal Link，否则需要登录态才能判断归属的链接会被误判成未登录
/// （`03-information-architecture.md` 深链接一节）。
struct RootView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @State private var router = AppRouter()
    @State private var pendingLink: DeepLink?
    @State private var showDebug = false
    @State private var showOnboarding = !OnboardingState.hasSeen

    var body: some View {
        Group {
            if environment.isBootstrapping {
                launchScreen
            } else if showOnboarding {
                OnboardingView {
                    OnboardingState.hasSeen = true
                    showOnboarding = false
                }
            } else {
                RootTabView()
                    .environment(router)
            }
        }
        .environment(\.zlMotion, reduceMotion)
        .task { PushManager.shared.attach(environment: environment, router: router) }
        .onOpenURL { url in
            guard let link = DeepLink(url: url) else { return }
            if environment.isBootstrapping {
                pendingLink = link
            } else {
                router.handle(link)
            }
        }
        .onChange(of: environment.isBootstrapping) { _, isBootstrapping in
            guard !isBootstrapping, let link = pendingLink else { return }
            pendingLink = nil
            router.handle(link)
        }
        #if DEBUG
        .overlay(alignment: .topTrailing) {
            if !environment.isBootstrapping && !showOnboarding {
                Button {
                    showDebug = true
                } label: {
                    Image(systemName: "ladybug.fill")
                        .frame(width: 44, height: 44)
                        .background(.thinMaterial, in: Circle())
                }
                .accessibilityLabel("Debug session")
                .padding(.top, 44)
                .padding(.trailing, 8)
            }
        }
        .sheet(isPresented: $showDebug) { DebugSessionView() }
        #endif
        .sheet(isPresented: authSheetBinding) { AuthSheet() }
    }

    /// `AppEnvironment.isPresentingAuthSheet` 是登录墙动作恢复原语的一部分（见
    /// `AppEnvironment.requireAuth`），全 App 共用这一个 sheet 实例。
    private var authSheetBinding: Binding<Bool> {
        Binding(
            get: { environment.isPresentingAuthSheet },
            set: { newValue in if !newValue { environment.cancelAuthSheet() } }
        )
    }

    private var reduceMotion: Bool { systemReduceMotion || environment.reduceMotionPreference }

    private var launchScreen: some View {
        VStack(spacing: 12) {
            Image(systemName: "sparkles")
                .font(.system(size: 40))
                .foregroundStyle(Color.zl.primary)
                .accessibilityHidden(true)
            Text(L10n.t("brand.name")).font(.title2.weight(.bold))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.zl.bg)
    }
}
