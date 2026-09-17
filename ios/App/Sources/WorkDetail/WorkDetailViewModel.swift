import Observation
import ZaolangKit

@MainActor
@Observable
final class WorkDetailViewModel {
    private let apiClient: APIClient
    let workID: String

    private(set) var state: LoadableState<WorkDetail> = .loading
    private(set) var similarState: LoadableState<[WorkSummary]> = .loading

    // `WorkDetail` 只有解码 init，没有可写副本；点赞/收藏/关注的乐观更新走这几个覆盖值叠加在
    // `state.value` 上，不是改模型本身。
    private var likedOverride: Bool?
    private var likeCountOverride: Int?
    private var bookmarkedOverride: Bool?
    private var followingOverride: Bool?

    var isLiked: Bool { likedOverride ?? state.value?.viewerLiked ?? false }
    var likeCount: Int { likeCountOverride ?? state.value?.stats.likeCount ?? 0 }
    var isBookmarked: Bool { bookmarkedOverride ?? state.value?.viewerBookmarked ?? false }
    /// `WorkDetail` 不带"是否已关注作者"字段（只有 `PublicProfileResponse` 有），
    /// 未点击前恒为 false——跟前端同一份数据限制，不是遗漏。
    var isFollowingAuthor: Bool { followingOverride ?? false }

    init(workID: String, apiClient: APIClient) {
        self.workID = workID
        self.apiClient = apiClient
    }

    func load() async {
        state = .loading
        similarState = .loading
        do {
            let detail = try await apiClient.fetchWork(id: workID)
            state = .loaded(detail)
        } catch let error as ApiError {
            state = .failed(error)
            return
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
            return
        }
        await loadSimilar()
    }

    private func loadSimilar() async {
        do {
            let page = try await apiClient.similarWorks(workID: workID)
            similarState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            similarState = .failed(error)
        } catch {
            similarState = .failed(.unexpectedResponse(status: 0))
        }
    }

    /// 三个写操作都是"先改本地、失败再回滚"的乐观更新；调用方（`WorkDetailView`）
    /// 负责先过 `AppEnvironment.requireAuth`，这里假设已经登录。
    func toggleLike() async {
        let previousLiked = isLiked
        let previousCount = likeCount
        likedOverride = !previousLiked
        likeCountOverride = previousCount + (previousLiked ? -1 : 1)
        do {
            if likedOverride == true {
                _ = try await apiClient.likeWork(id: workID)
            } else {
                _ = try await apiClient.unlikeWork(id: workID)
            }
        } catch {
            likedOverride = previousLiked
            likeCountOverride = previousCount
        }
    }

    func toggleBookmark() async {
        let previous = isBookmarked
        bookmarkedOverride = !previous
        do {
            if bookmarkedOverride == true {
                _ = try await apiClient.bookmarkWork(id: workID)
            } else {
                _ = try await apiClient.unbookmarkWork(id: workID)
            }
        } catch {
            bookmarkedOverride = previous
        }
    }

    func toggleFollowAuthor(userID: String) async {
        let previous = isFollowingAuthor
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
}
