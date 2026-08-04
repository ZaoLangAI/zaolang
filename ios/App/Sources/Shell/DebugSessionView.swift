import SwiftUI
import ZaolangKit

/// M0 验收用的调试屏：拉通 `GET /v1/auth/me` 与续期，只在 Debug 构建里可达
/// （见 `RootView` 的 `#if DEBUG` 入口），不进 Release 包。
struct DebugSessionView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.dismiss) private var dismiss

    @State private var sessionAuthenticated = false
    @State private var lastAction = ""
    @State private var isBusy = false

    var body: some View {
        NavigationStack {
            Form {
                Section("会话状态") {
                    LabeledContent("SessionManager.isAuthenticated", value: sessionAuthenticated ? "true" : "false")
                    LabeledContent("AppEnvironment.isAuthenticated", value: environment.isAuthenticated ? "true" : "false")
                }

                if let me = environment.me {
                    Section("/v1/auth/me") {
                        LabeledContent("id", value: me.id)
                        LabeledContent("email", value: me.email)
                        LabeledContent("region", value: me.region.rawDescription)
                        LabeledContent("locale", value: me.locale.rawDescription)
                        LabeledContent("theme", value: me.theme.rawDescription)
                        LabeledContent("credits", value: "\(me.availableCredits)")
                    }
                } else {
                    Section("/v1/auth/me") {
                        Text("游客态：me 为 nil，这是正常状态，不是错误。").foregroundStyle(.secondary)
                    }
                }

                Section("操作") {
                    Button("重新拉取 /v1/auth/me") {
                        Task { await run("refreshMe") { await environment.refreshMe() } }
                    }
                    Button("手动触发续期（refreshAccessToken）") {
                        Task {
                            await run("refreshAccessToken") {
                                _ = await environment.sessionManager.refreshAccessToken()
                            }
                        }
                    }
                    Button("清除本机会话（signOut）", role: .destructive) {
                        Task {
                            await run("signOut") {
                                await environment.sessionManager.signOut()
                                await environment.refreshMe()
                            }
                        }
                    }
                }

                if !lastAction.isEmpty {
                    Section("最近一次操作") { Text(lastAction) }
                }
            }
            .navigationTitle("M0 调试屏")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                }
            }
            .disabled(isBusy)
        }
        .task { await refreshDisplayedState() }
    }

    private func run(_ label: String, _ action: @escaping () async -> Void) async {
        isBusy = true
        await action()
        await refreshDisplayedState()
        lastAction = "\(label) · \(Date().formatted(date: .omitted, time: .standard))"
        isBusy = false
    }

    private func refreshDisplayedState() async {
        sessionAuthenticated = await environment.sessionManager.isAuthenticated
    }
}

private extension RawOrUnknown {
    var rawDescription: String {
        switch self {
        case .known(let value): "\(value.rawValue)"
        case .unknown(let raw): "unknown(\(raw))"
        }
    }
}
