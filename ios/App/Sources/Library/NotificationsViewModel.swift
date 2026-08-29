import Observation
import ZaolangKit

/// 与 `front/src/components/notifications/notification-list.tsx` 同一套分组 / 正文 / 图标规则。
enum NotificationGroup {
    case remix, like, follow, job, royalty, moderation, system

    var labelKey: String {
        switch self {
        case .remix: "notificationsPage.typeRemix"
        case .like: "notificationsPage.typeLike"
        case .follow: "notificationsPage.typeFollow"
        case .job: "notificationsPage.typeJob"
        case .royalty: "notificationsPage.typeRoyalty"
        case .moderation: "notificationsPage.typeModeration"
        case .system: "notificationsPage.typeSystem"
        }
    }

    init(type: NotificationType?) {
        switch type {
        case .workRemixed: self = .remix
        case .workLiked: self = .like
        case .newFollower: self = .follow
        case .jobProgress, .jobSucceeded, .jobFailed, .jobCancelled: self = .job
        case .royaltyReceived, .accessSold: self = .royalty
        case .moderation, .draftPublished, .draftPublishRejected: self = .moderation
        case .system, nil: self = .system
        }
    }
}

enum NotificationDestination: Equatable {
    case work(workID: String)
    case job(jobID: String)
    case profile(handle: String)
    case learn(postID: String)
    case publish(draftID: String)
}

extension NotificationResponse {
    var group: NotificationGroup { NotificationGroup(type: type.value) }

    var bodyText: String {
        let payload = payload
        switch titleKey {
        case "notification.work_approved":
            return L10n.t("notificationBody.workApproved")
        case "notification.work_hidden":
            if let reason = payload.string("reason"), !reason.isEmpty {
                return L10n.t("notificationBody.workHiddenReason", ["reason": reason])
            }
            return L10n.t("notificationBody.workHidden")
        case "notification.work_restored":
            return L10n.t("notificationBody.workRestored")
        case "notification.work_tombstoned":
            return L10n.t("notificationBody.workTombstoned", ["reason": payload.string("reason") ?? ""])
        case "notification.appeal_granted":
            return L10n.t("notificationBody.appealGranted")
        case "notification.appeal_denied":
            if let note = payload.string("note"), !note.isEmpty {
                return L10n.t("notificationBody.appealDeniedReason", ["note": note])
            }
            return L10n.t("notificationBody.appealDenied")
        case "notification.skill_approved":
            return L10n.t("notificationBody.skillApproved", ["title": payload.string("title") ?? ""])
        case "notification.skill_rejected":
            return L10n.t(
                "notificationBody.skillRejected",
                ["title": payload.string("title") ?? "", "reason": payload.string("reason") ?? ""]
            )
        case "notification.skill_takedown":
            return L10n.t(
                "notificationBody.skillTakedown",
                ["title": payload.string("title") ?? "", "reason": payload.string("reason") ?? ""]
            )
        case "notification.learn_post_approved":
            return L10n.t("notificationBody.learnPostApproved", ["title": payload.string("title") ?? ""])
        case "notification.learn_post_rejected":
            return L10n.t(
                "notificationBody.learnPostRejected",
                ["title": payload.string("title") ?? "", "reason": payload.string("reason") ?? ""]
            )
        case "notification.job_queued":
            return L10n.t("notificationBody.jobQueued", jobArgs)
        case "notification.job_running":
            return L10n.t("notificationBody.jobRunning", jobArgs)
        case "notification.job_awaiting_input":
            return L10n.t("notificationBody.jobAwaitingInput", jobArgs)
        case "notification.job_succeeded":
            return L10n.t("notificationBody.jobSucceeded", jobArgs)
        case "notification.job_failed":
            return L10n.t("notificationBody.jobFailed", jobArgs)
        case "notification.job_cancelled":
            return L10n.t("notificationBody.jobCancelled", jobArgs)
        case "notification.job_expired":
            return L10n.t("notificationBody.jobExpired", jobArgs)
        case "notification.export_queued":
            return L10n.t("notificationBody.exportQueued", exportArgs)
        case "notification.export_running":
            return L10n.t("notificationBody.exportRunning", exportArgs)
        case "notification.export_succeeded":
            return L10n.t("notificationBody.exportSucceeded", exportArgs)
        case "notification.export_failed":
            return L10n.t("notificationBody.exportFailed", exportArgs)
        case "notification.export_cancelled":
            return L10n.t("notificationBody.exportCancelled", exportArgs)
        case "notification.work_remixed":
            return L10n.t("notificationBody.workRemixed", ["work_title": payload.string("work_title") ?? ""])
        case "notification.royalty_received":
            return L10n.t(
                "notificationBody.royaltyReceived",
                ["work_title": payload.string("work_title") ?? "", "amount": payload.string("amount") ?? ""]
            )
        case "notification.new_follower":
            return L10n.t(
                "notificationBody.newFollower",
                ["actor_name": payload.string("follower_display_name") ?? payload.string("actor_name") ?? ""]
            )
        case "notification.announcement":
            return L10n.t("notificationBody.announcement")
        case "notification.draft_published":
            return L10n.t("notificationBody.draftPublished", ["title": payload.string("title") ?? ""])
        case "notification.draft_publish_rejected":
            return L10n.t(
                "notificationBody.draftPublishRejected",
                ["title": payload.string("title") ?? "", "reason": payload.string("public_message") ?? ""]
            )
        default:
            for field in ["title", "work_title", "actor_name", "message"] {
                if let value = payload.string(field), !value.isEmpty { return value }
            }
            return titleKey
        }
    }

    var systemImage: String {
        if payload.bool("is_remix") == true { return "arrow.triangle.branch" }
        if let profile = payload.string("shortform_profile"), !profile.isEmpty { return "iphone" }
        switch payload.string("operation") {
        case "text_to_image": return "photo"
        case "image_to_image": return "wand.and.stars"
        case "text_to_video", "video_to_video", "drama_export": return "video"
        case "image_to_video": return "photo"
        case "audio_generation": return "mic"
        default: break
        }
        switch type.value {
        case .workRemixed: return "arrow.triangle.branch"
        case .workLiked: return "heart.fill"
        case .newFollower: return "person.fill"
        case .royaltyReceived, .accessSold: return "banknote"
        case .moderation: return "shield.fill"
        case .draftPublished: return "checkmark.circle"
        case .draftPublishRejected: return "exclamationmark.triangle"
        case .jobSucceeded: return "checkmark.circle"
        case .jobFailed: return "exclamationmark.triangle"
        case .jobCancelled: return "xmark.circle"
        case .jobProgress: return "sparkles"
        case .system, nil: return "bell.fill"
        }
    }

    var destination: NotificationDestination? {
        switch targetType {
        case "work":
            return targetID.map { .work(workID: $0) }
        case "generation_job":
            return targetID.map { .job(jobID: $0) }
        case "learn_post":
            return targetID.map { .learn(postID: $0) }
        case "draft":
            if let workID = payload.string("work_id"), !workID.isEmpty {
                return .work(workID: workID)
            }
            return targetID.map { .publish(draftID: $0) }
        case "user":
            if let handle = payload.string("follower_handle"), !handle.isEmpty {
                return .profile(handle: handle)
            }
            return nil
        default:
            return nil
        }
    }

    private var jobArgs: [String: CustomStringConvertible] {
        [
            "operation": operationLabel,
            "excerpt": payload.string("prompt_excerpt") ?? "",
            "tier": payload.string("quality_tier") ?? "",
        ]
    }

    private var exportArgs: [String: CustomStringConvertible] {
        [
            "series": payload.string("series_title") ?? "",
            "episode": payload.string("episode_title") ?? "",
        ]
    }

    private var operationLabel: String {
        if payload.bool("is_remix") == true { return L10n.t("notificationBody.opRemix") }
        if let profile = payload.string("shortform_profile"), !profile.isEmpty {
            return L10n.t("notificationBody.opShortform")
        }
        switch payload.string("operation") {
        case "text_to_image": return L10n.t("notificationBody.opTextToImage")
        case "image_to_image": return L10n.t("notificationBody.opImageToImage")
        case "text_to_video": return L10n.t("notificationBody.opTextToVideo")
        case "image_to_video": return L10n.t("notificationBody.opImageToVideo")
        case "video_to_video": return L10n.t("notificationBody.opVideoToVideo")
        case "audio_generation": return L10n.t("notificationBody.opAudio")
        case "drama_export": return L10n.t("notificationBody.opDramaExport")
        default: return payload.string("operation") ?? ""
        }
    }
}

private extension Dictionary where Key == String, Value == JSONValue {
    func string(_ key: String) -> String? {
        guard let value = self[key] else { return nil }
        switch value {
        case .string(let text): return text
        case .number(let number):
            return number.truncatingRemainder(dividingBy: 1) == 0
                ? String(Int(number))
                : String(number)
        default: return nil
        }
    }

    func bool(_ key: String) -> Bool? {
        if case .bool(let value)? = self[key] { return value }
        return nil
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
