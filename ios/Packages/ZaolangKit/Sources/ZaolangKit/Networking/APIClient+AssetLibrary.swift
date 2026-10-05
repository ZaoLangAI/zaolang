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

    /// The character's management graph: looks + images, relations,
    /// voices, running jobs (`GET /v1/characters/{id}/graph`).
    func fetchCharacterGraph(id: String) async throws -> AssetGraphResponse {
        try await send(.get("/v1/characters/\(id)/graph"))
    }

    /// Text fields only (name / description / voice description).
    func updateCharacterProfile(id: String, _ payload: CharacterProfileUpdate) async throws -> CharacterResponse {
        try await send(try .patch("/v1/characters/\(id)", body: payload))
    }

    /// Scripts that link this character — 「AI 生成」 is offered only when any do.
    func characterScriptLinks(id: String) async throws -> [CharacterScriptLink] {
        try await send(.get("/v1/characters/\(id)/script-links"))
    }

    /// A draft of the description / voice description from the linked
    /// scripts. Saves nothing.
    func describeCharacter(id: String, _ payload: CharacterDescribeRequest = .init()) async throws -> CharacterDescribeResponse {
        try await send(try .post("/v1/characters/\(id)/describe", body: payload))
    }

    /// 定稿: a candidate image becomes the approved one of its slot.
    func approveCharacterEntry(characterID: String, entryID: String) async throws -> AssetEntryView {
        try await send(.post("/v1/characters/\(characterID)/entries/\(entryID):approve"))
    }

    func makeDefaultVoice(characterID: String, voiceID: String) async throws -> CharacterVoiceView {
        try await send(try .patch("/v1/characters/\(characterID)/voices/\(voiceID)", body: MakeDefaultVoice()))
    }

    /// `dryRun` prices; otherwise submits one preview job (reuse the same
    /// `idempotencyKey` on retry). Its audio becomes the voice's preview.
    func previewVoice(
        characterID: String, voiceID: String, dryRun: Bool, idempotencyKey: String? = nil
    ) async throws -> VoicePreviewResponse {
        try await send(
            try .post(
                "/v1/characters/\(characterID)/voices/\(voiceID):preview",
                body: VoicePreviewRequest(dryRun: dryRun),
                idempotencyKey: idempotencyKey
            )
        )
    }

    func listScenes() async throws -> [SceneResponse] {
        try await send(.get("/v1/scenes"))
    }

    func createScene(_ payload: SceneCreateRequest) async throws -> SceneResponse {
        try await send(.post("/v1/scenes", body: payload))
    }
}
