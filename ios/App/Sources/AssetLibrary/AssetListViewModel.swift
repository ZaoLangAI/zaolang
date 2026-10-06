import Observation
import ZaolangKit

/// One row of a 角色 / 场景 / 道具 library.
struct AssetListRow: Identifiable {
    let id: String
    let name: String
    let description: String?
    /// A character's voice description.
    let voiceDescription: String?
    let heroURL: String?
    /// The default look / variant's `(done, total)`; `nil` without one.
    let completeness: (done: Int, total: Int)?
}

/// A library list (`GET /v1/{characters,scenes,props}`, bare arrays). The full
/// payload, not `?view=summary`: the completeness badge needs the variants'
/// entries, as on the web library cards.
@MainActor
@Observable
final class AssetListViewModel {
    let kind: AssetCardKind
    private let apiClient: APIClient

    private(set) var state: LoadableState<[AssetListRow]> = .loading

    init(kind: AssetCardKind, apiClient: APIClient) {
        self.kind = kind
        self.apiClient = apiClient
    }

    func load() async {
        do {
            let rows: [AssetListRow]
            switch kind {
            case .character:
                rows = try await apiClient.listCharacters().map {
                    row($0.id, $0.name, $0.description, $0.voiceDescription, $0.heroURL, $0.looks ?? [])
                }
            case .scene:
                rows = try await apiClient.listScenes().map {
                    row($0.id, $0.name, $0.description, nil, $0.heroURL, $0.variants)
                }
            case .prop:
                rows = try await apiClient.listProps().map {
                    row($0.id, $0.name, $0.description, nil, $0.heroURL, $0.variants)
                }
            }
            state = rows.isEmpty ? .empty : .loaded(rows)
        } catch let error as ApiError {
            state = .failed(error)
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
        }
    }

    private func row(
        _ id: String, _ name: String, _ description: String?, _ voice: String?, _ hero: String?,
        _ variants: [AssetVariantView]
    ) -> AssetListRow {
        AssetListRow(
            id: id,
            name: name,
            description: description,
            voiceDescription: voice,
            heroURL: hero,
            completeness: AssetSlots.cardCompleteness(kind, variants: variants)
        )
    }
}
