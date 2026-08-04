import SwiftUI
import UserNotifications
import ZaolangKit

/// 账号与设置，对应 `(site)/settings/page.tsx`。单页 Form 承载全部分区——iOS 屏幕小，
/// Web 端的左侧分区导航（`navProfile`/`navPrivacy`/...）在这里合并成 Form 的 Section 标题。
struct SettingsView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase

    @State private var viewModel: SettingsViewModel?
    @State private var showDeleteConfirm = false
    @State private var deleteReason = ""
    @State private var showSignOutConfirm = false
    @State private var pushStatus: UNAuthorizationStatus = .notDetermined

    var body: some View {
        Form {
            if let viewModel {
                profileSection(viewModel)
                privacySection(viewModel)
                notificationsSection
                displaySection(viewModel)
                dataSection(viewModel)
                saveSection(viewModel)
            }
            signOutSection
        }
        .navigationTitle(L10n.t("settingsPage.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if viewModel == nil {
                viewModel = SettingsViewModel(environment: environment)
            }
            await refreshPushStatus()
        }
        .onChange(of: scenePhase) { _, newPhase in
            guard newPhase == .active else { return }
            Task { await refreshPushStatus() }
        }
        .confirmationDialog(
            L10n.t("settingsPage.deleteConfirmTitle"),
            isPresented: $showDeleteConfirm,
            titleVisibility: .visible
        ) {
            Button(L10n.t("settingsPage.deleteAccount"), role: .destructive) {
                Task { await viewModel?.requestDeletion(reason: deleteReason) }
            }
            Button(L10n.t("actions.cancel"), role: .cancel) {}
        } message: {
            Text(L10n.t("settingsPage.deleteConfirmBody"))
        }
        .confirmationDialog(L10n.t("auth.signOut"), isPresented: $showSignOutConfirm, titleVisibility: .visible) {
            Button(L10n.t("auth.signOut"), role: .destructive) {
                Task {
                    await environment.signOut()
                    dismiss()
                }
            }
            Button(L10n.t("actions.cancel"), role: .cancel) {}
        }
    }

    private func profileSection(_ viewModel: SettingsViewModel) -> some View {
        Section(L10n.t("settingsPage.profileSection")) {
            TextField(L10n.t("settingsPage.displayName"), text: Binding(
                get: { viewModel.displayName },
                set: { viewModel.displayName = $0 }
            ))
            TextField(L10n.t("settingsPage.bio"), text: Binding(
                get: { viewModel.bio },
                set: { viewModel.bio = $0 }
            ), axis: .vertical)
            TextField(L10n.t("settingsPage.location"), text: Binding(
                get: { viewModel.location },
                set: { viewModel.location = $0 }
            ))
        }
    }

    private func privacySection(_ viewModel: SettingsViewModel) -> some View {
        Section {
            Toggle(L10n.t("settingsPage.publicProfile"), isOn: Binding(
                get: { viewModel.publicProfile },
                set: { viewModel.publicProfile = $0 }
            ))
            Toggle(L10n.t("settingsPage.remixNotify"), isOn: Binding(
                get: { viewModel.notifyOnRemix },
                set: { viewModel.notifyOnRemix = $0 }
            ))
            Toggle(L10n.t("settingsPage.reduceMotion"), isOn: Binding(
                get: { viewModel.reduceMotion },
                set: { viewModel.reduceMotion = $0 }
            ))
        } header: {
            Text(L10n.t("settingsPage.privacySection"))
        } footer: {
            Text(L10n.t("settingsPage.publicProfileDesc"))
        }
    }

    /// 系统级推送权限跟 `settingsPage.remixNotify`（后端偏好，控制"要不要产生这条通知"）
    /// 是两件独立的事——这里管的是 iOS 有没有把这个 App 加进通知中心。已授权时按钮禁用，
    /// 只做状态展示；拒绝后引导去系统设置，App 内再弹一次系统权限框不会有任何效果。
    private var notificationsSection: some View {
        Section(L10n.t("settingsPage.notificationsSection")) {
            switch pushStatus {
            case .authorized, .provisional, .ephemeral:
                Label(L10n.t("settingsPage.pushEnable"), systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Color.zl.success)
            case .denied:
                Button {
                    PushManager.shared.openSystemSettings()
                } label: {
                    labeledRow(L10n.t("settingsPage.pushOpenSystemSettings"), hint: L10n.t("settingsPage.pushEnableDesc"))
                }
            case .notDetermined:
                Button {
                    PushManager.shared.requestAuthorizationAndRegister()
                    Task {
                        try? await Task.sleep(nanoseconds: 500_000_000)
                        await refreshPushStatus()
                    }
                } label: {
                    labeledRow(L10n.t("settingsPage.pushEnable"), hint: L10n.t("settingsPage.pushEnableDesc"))
                }
            @unknown default:
                EmptyView()
            }
        }
    }

    private func refreshPushStatus() async {
        pushStatus = await PushManager.shared.currentAuthorizationStatus()
    }

    private func displaySection(_ viewModel: SettingsViewModel) -> some View {
        Section {
            Picker(L10n.t("theme.label"), selection: Binding(get: { viewModel.theme }, set: { viewModel.theme = $0 })) {
                Text(L10n.t("theme.system")).tag(ThemePreference.system)
                Text(L10n.t("theme.dark")).tag(ThemePreference.dark)
                Text(L10n.t("theme.light")).tag(ThemePreference.light)
            }
            Picker(L10n.t("settingsPage.regionLabel"), selection: Binding(get: { viewModel.region }, set: { viewModel.region = $0 })) {
                Text(L10n.t("region.CN")).tag(Region.cn)
                Text(L10n.t("region.JP")).tag(Region.jp)
                Text(L10n.t("region.GLOBAL")).tag(Region.global)
            }
        } header: {
            Text(L10n.t("settingsPage.displaySection"))
        } footer: {
            Text(L10n.t("settingsPage.regionDesc"))
        }
    }

    private func dataSection(_ viewModel: SettingsViewModel) -> some View {
        Section(L10n.t("settingsPage.dataSection")) {
            Button {
                Task { await viewModel.requestExport() }
            } label: {
                labeledRow(L10n.t("settingsPage.exportData"), hint: L10n.t("settingsPage.exportDataDesc"))
            }
            .disabled(viewModel.isSubmittingDataRequest)

            Button(role: .destructive) {
                showDeleteConfirm = true
            } label: {
                labeledRow(L10n.t("settingsPage.deleteAccount"), hint: L10n.t("settingsPage.deleteAccountDesc"))
            }
            .disabled(viewModel.isSubmittingDataRequest)

            if let request = viewModel.lastDataRequest {
                Text(
                    request.type.value == .export
                        ? L10n.t("settingsPage.exportRequested")
                        : L10n.t("settingsPage.deleteRequested")
                )
                .font(.footnote)
                .foregroundStyle(Color.zl.textMuted)
            }
            if let error = viewModel.dataRequestError {
                Text(error).font(.footnote).foregroundStyle(Color.zl.danger)
            }
        }
    }

    private func labeledRow(_ title: String, hint: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
            Text(hint).font(.caption).foregroundStyle(Color.zl.textMuted)
        }
    }

    private func saveSection(_ viewModel: SettingsViewModel) -> some View {
        Section {
            Button {
                Task { await viewModel.save() }
            } label: {
                HStack {
                    Spacer()
                    if viewModel.isSaving {
                        ProgressView()
                    } else {
                        Text(L10n.t("actions.confirm")).font(.body.weight(.semibold))
                    }
                    Spacer()
                }
            }
            .disabled(viewModel.isSaving)

            if viewModel.saveSucceeded {
                Text(L10n.t("settingsPage.saved")).font(.footnote).foregroundStyle(Color.zl.success)
            }
            if let error = viewModel.saveError {
                Text(error).font(.footnote).foregroundStyle(Color.zl.danger)
            }
        }
    }

    private var signOutSection: some View {
        Section {
            Button(L10n.t("auth.signOut"), role: .destructive) {
                showSignOutConfirm = true
            }
        }
    }
}
