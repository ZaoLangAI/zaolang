import Observation
import ZaolangKit

/// 拉取已通过审核的用户发表学习内容（`GET /v1/learn/posts`，游客可读）。
/// 不再借用 `listWorks` 的封面——学习页完全由 UGC 发表内容驱动。
@MainActor
@Observable
final class LearnViewModel {
    private let apiClient: APIClient
    private(set) var postsState: LoadableState<[LearnPostSummary]> = .loading

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    var posts: [LearnPostSummary] { postsState.value ?? [] }

    /// Hero 区展示最新通过审核的一条（后端按 `published_at DESC` 排序，第一条即最新）。
    var heroPost: LearnPostSummary? { posts.first }

    func load() async {
        postsState = .loading
        do {
            let page = try await apiClient.listLearnPosts(.init(limit: 12))
            postsState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            postsState = .failed(error)
        } catch {
            postsState = .failed(.unexpectedResponse(status: 0))
        }
    }
}
