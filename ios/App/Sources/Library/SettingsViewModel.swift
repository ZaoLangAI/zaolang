import Observation
import ZaolangKit

@MainActor
@Observable
final class SettingsViewModel {
    private let environment: AppEnvironment

    var displayName = ""
    var bio = ""
    var location = ""
    var publicProfile = true
    var notifyOnRemix = true
    var reduceMotion = false
    var theme: ThemePreference = .system
    var region: Region = .global

    private(set) var isSaving = false
    private(set) var saveError: String?
    private(set) var saveSucceeded = false

    private(set) var isSubmittingDataRequest = false
    private(set) var dataRequestError: String?
    private(set) var lastDataRequest: MyDataRequestResponse?

    init(environment: AppEnvironment) {
        self.environment = environment
        seed(from: environment.me)
    }

    func seed(from me: MeResponse?) {
        guard let me else { return }
        displayName = me.profile?.displayName ?? ""
        bio = me.profile?.bio ?? ""
        location = me.profile?.location ?? ""
        publicProfile = me.profile?.publicProfile ?? true
        notifyOnRemix = me.profile?.notifyOnRemix ?? true
        reduceMotion = me.profile?.reduceMotion ?? false
        theme = me.theme.value ?? .system
        region = me.region.value ?? .global
    }

    /// 资料与偏好是后端两个不同端点，但设置页只有一个"保存"按钮——都失败也只报一条错误，
    /// 用户重试即可，不需要区分是哪半边没存上。
    func save() async {
        isSaving = true
        saveError = nil
        saveSucceeded = false
        defer { isSaving = false }
        do {
            try await environment.updateProfile(ProfileUpdateRequest(
                displayName: displayName,
                bio: bio,
                location: location,
                publicProfile: publicProfile
            ))
            try await environment.updatePreferences(PreferencesRequest(
                region: region,
                theme: theme,
                reduceMotion: reduceMotion,
                notifyOnRemix: notifyOnRemix
            ))
            saveSucceeded = true
        } catch let error as ApiError {
            saveError = error.fallbackMessage
        } catch {
            saveError = L10n.t("settingsPage.saveFailed")
        }
    }

    func requestExport() async {
        await submitDataRequest(.export, reason: nil)
    }

    func requestDeletion(reason: String) async {
        await submitDataRequest(.delete, reason: reason)
    }

    private func submitDataRequest(_ type: DataRequestType, reason: String?) async {
        isSubmittingDataRequest = true
        dataRequestError = nil
        defer { isSubmittingDataRequest = false }
        do {
            lastDataRequest = try await environment.apiClient.createDataRequest(
                DataRequestCreateRequest(type: type, reason: reason)
            )
        } catch let error as ApiError {
            dataRequestError = error.fallbackMessage
        } catch {
            dataRequestError = L10n.t("settingsPage.saveFailed")
        }
    }
}
