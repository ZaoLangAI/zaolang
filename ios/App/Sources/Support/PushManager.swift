import UIKit
import UserNotifications

/// APNs 注册与前台/点击回调的唯一入口。真实推送发送在后端仍是日志占位（见
/// `back/app/domain/notifications/push.py` 顶部注释），这里先把客户端这一半接完整：
/// 权限申请 → `didRegisterForRemoteNotificationsWithDeviceToken` → 上报后端 → 点击跳转。
@MainActor
final class PushManager: NSObject {
    static let shared = PushManager()

    private weak var environment: AppEnvironment?
    private weak var router: AppRouter?

    private override init() { super.init() }

    /// `RootView` 在拿到 `environment`/`router` 之后调用一次；两者都是弱引用，
    /// App 生命周期内只有一份，不会出现悬垂。
    func attach(environment: AppEnvironment, router: AppRouter) {
        self.environment = environment
        self.router = router
    }

    /// 已授权则静默补注册（例如重装后 token 变化），未授权则真正弹系统权限框——
    /// 只在用户主动点"开启通知"（设置页）或首次引导页时调用，不在冷启动自动弹。
    func requestAuthorizationAndRegister() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            switch settings.authorizationStatus {
            case .authorized, .provisional:
                DispatchQueue.main.async { UIApplication.shared.registerForRemoteNotifications() }
            case .notDetermined:
                UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
                    guard granted else { return }
                    DispatchQueue.main.async { UIApplication.shared.registerForRemoteNotifications() }
                }
            case .denied, .ephemeral:
                break
            @unknown default:
                break
            }
        }
    }

    /// 设置页"开启通知"这一行用来判断按钮该显示"开启"还是"去系统设置"。
    func currentAuthorizationStatus() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    func openSystemSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    func didRegister(deviceToken: Data) {
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        Task { await environment?.registerPushToken(token) }
    }

    func didFailToRegister(error: Error) {
        // 本地/模拟器没有真实 APNs 证书时这里恒失败，不影响其余功能，不需要上报用户。
    }

    /// 通知点击跳转：payload 里 `target_type`/`target_id` 与后端
    /// `notifications.notify(target_type=..., target_id=...)` 写入的字段同名。
    func handleNotificationTap(userInfo: [AnyHashable: Any]) {
        guard let targetType = userInfo["target_type"] as? String,
              let targetID = userInfo["target_id"] as? String,
              let router
        else { return }
        switch targetType {
        case "generation_job":
            router.selectTab(.create)
            router.createPath.append(CreateRoute.jobDetail(jobID: targetID))
        case "work":
            router.selectTab(.discover)
            router.discoverPath.append(DiscoverRoute.workDetail(workID: targetID))
        default:
            break
        }
    }
}

/// `UNUserNotificationCenterDelegate` 要求继承 `NSObject`，单独一个空 extension 承载。
extension PushManager: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo
        Task { @MainActor in
            PushManager.shared.handleNotificationTap(userInfo: userInfo)
        }
        completionHandler()
    }
}

/// 只承载 APNs 生命周期回调，不管理任何其余 App 状态——状态全在 `AppEnvironment`/`AppRouter`。
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = PushManager.shared
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in PushManager.shared.didRegister(deviceToken: deviceToken) }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in PushManager.shared.didFailToRegister(error: error) }
    }
}
