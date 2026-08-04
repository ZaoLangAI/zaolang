import Foundation

/// 预签名握手；真正把字节传上去的那一步在 `Media/UploadTransport.swift`，
/// 因为目标是签名 URL，不走这个 client 的鉴权/幂等逻辑。
public extension APIClient {
    func presignUpload(_ payload: UploadPresignRequest) async throws -> UploadPresignResponse {
        try await send(.post("/v1/uploads/presign", body: payload))
    }

    func completeUpload(sessionID: String) async throws -> AssetResponse {
        try await send(.post("/v1/uploads/complete", body: UploadCompleteRequest(uploadSessionID: sessionID)))
    }

    /// 素材详情已经有 `asset(id:)`（`APIClient+Discovery.swift`），这里只补溯源清单。
    func assetProvenance(id: String) async throws -> ProvenanceResponse {
        try await send(.get("/v1/assets/\(id)/provenance"))
    }
}
