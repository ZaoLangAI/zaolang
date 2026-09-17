import Observation
import ZaolangKit

/// 对应 `(site)/profile/[handle]/page.tsx`：主页信息一次请求，作品列表另一次「一次取满」。
/// `PublicProfileResponse` 没有浏览/点赞/被二创的汇总字段，跟 Web 一样从取到的作品列表里累加
/// ——这本来就是个基于当前页作品的估算值，不是精确的全量统计。
@MainActor
@Observable
final class ProfileViewModel {
    private let apiClient: APIClient
    let handle: String

    private(set) var state: LoadableState<PublicProfileResponse> = .loading
    private(set) var works: [WorkSummary] = []
    /// `PublicProfileResponse` 没有可写副本，关注状态的乐观更新叠在这个覆盖值上。
    private var followingOverride: Bool?

    init(handle: String, apiClient: APIClient) {
        self.handle = handle
        self.apiClient = apiClient
    }

    func load() async {
        state = .loading
        works = []
        do {
            let profile = try await apiClient.profile(handle: handle)
            state = .loaded(profile)
        } catch let error as ApiError {
            state = .failed(error)
            return
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
            return
        }
        do {
            works = try await apiClient.profileWorks(handle: handle).items
        } catch {
            works = [] // 主页信息已经拿到了，作品列表失败只让网格显示空态，不整屏报错
        }
    }

    var viewCount: Int { works.reduce(0) { $0 + $1.stats.viewCount } }
    var likeCount: Int { works.reduce(0) { $0 + $1.stats.likeCount } }
    var remixCount: Int { works.reduce(0) { $0 + $1.stats.remixCount } }

    var isFollowing: Bool { followingOverride ?? state.value?.viewerFollowing ?? false }

    func toggleFollow(userID: String) async {
        let previous = isFollowing
        followingOverride = !previous
        do {
            if followingOverride == true {
                _ = try await apiClient.followUser(id: userID)
            } else {
                _ = try await apiClient.unfollowUser(id: userID)
            }
        } catch {
            followingOverride = previous
        }
    }

    var styleTags: [String] {
        var seen: Set<String> = []
        var ordered: [String] = []
        for tag in works.flatMap(\.tags) where !seen.contains(tag) {
            seen.insert(tag)
            ordered.append(tag)
            if ordered.count == 4 { break }
        }
        return ordered
    }
}
