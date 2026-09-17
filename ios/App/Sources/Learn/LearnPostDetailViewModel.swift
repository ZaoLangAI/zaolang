import Observation
import ZaolangKit

/// 拉取单篇学习内容详情。`approved` 所有人可见，其它状态仅作者本人可见，
/// 否则后端回 404——`ApiError.notFound` 已经把私有语义合并，这里不需要额外处理"无权限"文案。
@MainActor
@Observable
final class LearnPostDetailViewModel {
    private let apiClient: APIClient
    let postID: String

    private(set) var state: LoadableState<LearnPostDetail> = .loading

    init(postID: String, apiClient: APIClient) {
        self.postID = postID
        self.apiClient = apiClient
    }

    func load() async {
        state = .loading
        do {
            let detail = try await apiClient.fetchLearnPost(id: postID)
            state = .loaded(detail)
        } catch let error as ApiError {
            state = .failed(error)
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
        }
    }
}
