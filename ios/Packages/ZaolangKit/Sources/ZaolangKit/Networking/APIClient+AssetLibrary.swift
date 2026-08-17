import Foundation

/// The character/scene libraries the "图片创作" studio reads from and writes
/// back to. Both endpoints return a plain array (no pagination) — creators
/// keep dozens of these at most, not hundreds.
public extension APIClient {
    func listCharacters() async throws -> [CharacterResponse] {
        try await send(.get("/v1/characters"))
    }

    func createCharacter(_ payload: CharacterCreateRequest) async throws -> CharacterResponse {
        try await send(.post("/v1/characters", body: payload))
    }

    /// Re-fetched after a "补全侧面/背面" completion job succeeds, so the
    /// caller sees the newly attached side/back reference assets without
    /// re-listing the whole roster.
    func fetchCharacter(id: String) async throws -> CharacterResponse {
        try await send(.get("/v1/characters/\(id)"))
    }

    func listScenes() async throws -> [SceneResponse] {
        try await send(.get("/v1/scenes"))
    }

    func createScene(_ payload: SceneCreateRequest) async throws -> SceneResponse {
        try await send(.post("/v1/scenes", body: payload))
    }
}
