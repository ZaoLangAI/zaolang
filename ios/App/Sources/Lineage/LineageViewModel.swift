import Observation
import ZaolangKit

@MainActor
@Observable
final class LineageViewModel {
    private let apiClient: APIClient
    let workID: String

    private(set) var state: LoadableState<LineageGraph> = .loading
    var depth = 3 {
        didSet {
            guard oldValue != depth else { return }
            Task { await load() }
        }
    }

    var selectedNodeID: String?
    private(set) var diffState: LoadableState<VersionDiffResponse> = .empty

    init(workID: String, apiClient: APIClient) {
        self.workID = workID
        self.apiClient = apiClient
    }

    func load() async {
        state = .loading
        do {
            let response = try await apiClient.lineage(workID: workID, depth: depth)
            // `LineageGraph` 至少总有当前作品这一个节点，`.empty` 这个 case 在这里用不到——
            // "只有一个节点"是 `graphBody` 里按 `nodes.count == 1` 判断的展示态，不是取数失败。
            state = .loaded(LineageGraph(response: response))
        } catch let error as ApiError {
            state = .failed(error)
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
        }
    }

    func selectNode(_ nodeID: String) {
        selectedNodeID = nodeID
        Task { await loadDiff(for: nodeID) }
    }

    func clearSelection() {
        selectedNodeID = nil
        diffState = .empty
    }

    /// 后端按 `child_version_id` 自动找父版本；没有父版本（选中的是这条链最早的节点）就是
    /// 404，这里把它当作正常的"起点"状态呈现，不是错误。
    private func loadDiff(for versionID: String) async {
        diffState = .loading
        do {
            let diff = try await apiClient.versionDiff(childVersionID: versionID)
            diffState = diff.entries.isEmpty ? .empty : .loaded(diff)
        } catch ApiError.notFound {
            diffState = .empty
        } catch let error as ApiError {
            diffState = .failed(error)
        } catch {
            diffState = .failed(.unexpectedResponse(status: 0))
        }
    }
}
