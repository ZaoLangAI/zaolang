import Observation
import ZaolangKit

@MainActor
@Observable
final class CreateViewModel {
    private let apiClient: APIClient
    private(set) var draftsState: LoadableState<[DraftResponse]> = .loading

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        do {
            let page = try await apiClient.listDrafts(limit: 10)
            draftsState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            draftsState = .failed(error)
        } catch {
            draftsState = .failed(.unexpectedResponse(status: 0))
        }
    }
}
