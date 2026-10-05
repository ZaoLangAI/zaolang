import Observation
import ZaolangKit

/// 角色库列表（`GET /v1/characters?view=summary`，裸数组，不带造型图）。
@MainActor
@Observable
final class CharacterLibraryViewModel {
    private let apiClient: APIClient

    private(set) var state: LoadableState<[CharacterResponse]> = .loading

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        do {
            let characters = try await apiClient.listCharacters(summary: true)
            state = characters.isEmpty ? .empty : .loaded(characters)
        } catch let error as ApiError {
            state = .failed(error)
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
        }
    }
}
