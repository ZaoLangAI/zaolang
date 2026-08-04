import SwiftUI
import ZaolangKit

/// 登录/注册 sheet。挂在 `RootView` 上，绑定 `AppEnvironment.isPresentingAuthSheet`——
/// 任何写操作走 `requireAuth` 未登录时都会弹出这一个共享实例，不是每个屏幕各自一份。
/// 字段与文案对齐 `front/src/components/auth/login-dialog.tsx`，两端不应各说各话。
struct AuthSheet: View {
    @Environment(AppEnvironment.self) private var environment

    private enum Mode { case signIn, signUp }

    @State private var mode: Mode = .signIn
    @State private var email = ""
    @State private var password = ""
    @State private var displayName = ""
    @State private var handle = ""
    @State private var ageConfirmed = false
    @State private var isSubmitting = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                if let label = environment.pendingAuthActionLabel {
                    Section {
                        Text(label)
                            .font(.subheadline)
                            .foregroundStyle(Color.zl.textMuted)
                    }
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .font(.subheadline)
                            .foregroundStyle(Color.zl.danger)
                    }
                }

                Section {
                    TextField(L10n.t("auth.email"), text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField(L10n.t("auth.password"), text: $password)
                        .textContentType(mode == .signUp ? .newPassword : .password)
                }

                if mode == .signUp {
                    Section {
                        TextField(L10n.t("auth.displayName"), text: $displayName)
                        TextField(L10n.t("auth.handle"), text: $handle)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        Toggle("18+", isOn: $ageConfirmed)
                    }
                }

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        HStack {
                            Spacer()
                            if isSubmitting {
                                ProgressView()
                            } else {
                                Text(mode == .signUp ? L10n.t("auth.signUp") : L10n.t("auth.signIn"))
                                    .font(.body.weight(.semibold))
                            }
                            Spacer()
                        }
                    }
                    .disabled(isSubmitting || !canSubmit)
                }

                Section {
                    Button(mode == .signUp ? L10n.t("auth.toSignIn") : L10n.t("auth.toSignUp")) {
                        mode = mode == .signUp ? .signIn : .signUp
                        errorMessage = nil
                    }
                }
            }
            .navigationTitle(mode == .signUp ? L10n.t("auth.signUpTitle") : L10n.t("auth.signInTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.t("actions.cancel")) {
                        environment.cancelAuthSheet()
                    }
                }
            }
        }
        .interactiveDismissDisabled(isSubmitting)
    }

    private var canSubmit: Bool {
        guard !email.isEmpty, !password.isEmpty else { return false }
        if mode == .signUp {
            return !displayName.isEmpty && !handle.isEmpty && ageConfirmed
        }
        return true
    }

    private func submit() async {
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }
        do {
            switch mode {
            case .signIn:
                try await environment.login(email: email, password: password)
            case .signUp:
                let payload = RegisterRequest(
                    email: email,
                    password: password,
                    displayName: displayName,
                    handle: handle,
                    region: CurrentAppLocale.suggestedRegion,
                    locale: CurrentAppLocale.value,
                    ageConfirmed: ageConfirmed
                )
                try await environment.register(payload)
            }
        } catch let error as ApiError {
            errorMessage = error.fallbackMessage
        } catch {
            errorMessage = L10n.t("auth.invalidCredentials")
        }
    }
}
