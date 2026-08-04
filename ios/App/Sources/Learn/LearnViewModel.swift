import Observation
import ZaolangKit

/// 拉 4 个真实社区作品做课程封面插图（`GET /v1/works?sort=popular&remixable=true&limit=4`），
/// 对应 Web 端注释：设计不允许用占位图，课程配图必须是真实作品（`(site)/learn/page.tsx`）。
@MainActor
@Observable
final class LearnViewModel {
    private let apiClient: APIClient
    private(set) var examples: [WorkSummary] = []
    private(set) var loaded = false

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        guard !loaded else { return }
        do {
            examples = try await apiClient.listWorks(.init(remixable: true, sort: .popular, limit: 4)).items
        } catch {
            examples = [] // 插图拉不到就退回纯文字卡片，不影响课程内容本身可读
        }
        loaded = true
    }

    func heroCover() -> WorkSummary? { examples[safe: 3] ?? examples.first }

    func courseCover(at position: Int) -> WorkSummary? { examples[safe: position] }

    func exampleWork() -> WorkSummary? { examples.first }
}

private extension Array {
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}
