import Observation
import ZaolangKit

/// 与 `front/src/components/notifications/notification-list.tsx` 同一套分组/取文案规则：
/// 正文优先取 `payload` 里的 `title`/`work_title`/`actor_name`/`message`，都没有才落回 `title_key` 原串。
enum NotificationGroup {
    case remix, follow, job, royalty, moderation, system

    var labelKey: String {
        switch self {
        case .remix: "notificationsPage.typeRemix"
        case .follow: "notificationsPage.typeFollow"
        case .job: "notificationsPage.typeJob"
        case .royalty: "notificationsPage.typeRoyalty"
        case .moderation: "notificationsPage.typeModeration"
        case .system: "notificationsPage.typeSystem"
        }
    }

    var systemImage: String {
        switch self {
        case .remix: "arrow.triangle.branch"
        case .follow: "person.fill"
        case .job: "sparkles"
        case .royalty: "banknote"
        case .moderation: "shield.fill"
        case .system: "bell.fill"
        }
    }

    init(type: NotificationType?) {
        switch type {
        case .workRemixed, .workLiked: self = .remix
        case .newFollower: self = .follow
        case .jobProgress, .jobSucceeded, .jobFailed: self = .job
        case .royaltyReceived: self = .royalty
        case .moderation: self = .moderation
        case .system, nil: self = .system
        }
    }
}

enum NotificationDestination: Equatable {
    case work(workID: String)
    case job(jobID: String)
    // 没有"按 user id 查主页"的端点（`GET /v1/profiles/{handle}` 只认 handle），
    // `new_follower` 通知的 payload 也只有 `follower_user_id`，拿不到 handle——不提供跳转，
    // 总比给一个打不开的链接好。
}

extension NotificationResponse {
    var group: NotificationGroup { NotificationGroup(type: type.value) }

    var bodyText: String {
        for field in ["title", "work_title", "actor_name", "message"] {
            if case .string(let value)? = payload[field] { return value }
        }
        return titleKey
    }

    var destination: NotificationDestination? {
        guard let targetID else { return nil }
        switch targetType {
        case "work": return .work(workID: targetID)
        case "generation_job": return .job(jobID: targetID)
        default: return nil
        }
    }
}

@MainActor
@Observable
final class NotificationsViewModel {
    private let apiClient: APIClient

    private(set) var state: LoadableState<[NotificationResponse]> = .loading
    /// `NotificationResponse` 只有解码 init、没有可写副本，标已读靠这个覆盖集合叠加在
    /// `item.read` 上，跟 `WorkDetailViewModel`/`ProfileViewModel` 的乐观更新是同一套写法。
    private(set) var readOverrides: Set<String> = []

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func isRead(_ item: NotificationResponse) -> Bool { item.read || readOverrides.contains(item.id) }

    var unreadCount: Int { state.value?.filter { !isRead($0) }.count ?? 0 }

    func load() async {
        state = .loading
        readOverrides = []
        do {
            let page = try await apiClient.listNotifications(limit: 50)
            state = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            state = .failed(error)
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
        }
    }

    func markAllRead() async {
        guard let items = state.value else { return }
        readOverrides.formUnion(items.map(\.id))
        _ = try? await apiClient.markNotificationsRead()
    }

    func markRead(id: String) async {
        readOverrides.insert(id)
        _ = try? await apiClient.markNotificationsRead(notificationID: id)
    }
}
