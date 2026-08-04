import Foundation

public extension APIClient {
    func createDraft(_ payload: DraftCreateRequest) async throws -> DraftResponse {
        try await send(.post("/v1/drafts", body: payload))
    }

    func listDrafts(limit: Int = 20) async throws -> Page<DraftResponse> {
        try await send(.get("/v1/drafts", query: [URLQueryItem(name: "limit", value: String(limit))]))
    }

    func fetchDraft(id: String) async throws -> DraftResponse {
        try await send(.get("/v1/drafts/\(id)"))
    }

    func publishDraft(id: String, _ payload: PublishRequest) async throws -> PublishResponse {
        try await send(.post("/v1/drafts/\(id)/publish", body: payload))
    }

    func deleteDraft(id: String) async throws {
        try await sendDiscardingBody(.delete("/v1/drafts/\(id)"))
    }
}
