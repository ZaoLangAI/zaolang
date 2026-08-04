import Foundation

/// 报价 / 提交 / 列表 / 详情 / 取消 / 重试。SSE 事件流不在这里——那是长连接，
/// 走 `Streaming/EventStreamClient.swift`，不是一次性 `send`。
public extension APIClient {
    func quoteGeneration(_ payload: QuoteRequest) async throws -> QuoteResponse {
        try await send(.post("/v1/generation-jobs/quote", body: payload))
    }

    /// `idempotencyKey` 必须是调用方持有的同一个键（断网重发要复用），不要每次调用都新生成。
    func submitGeneration(_ payload: GenerationJobCreateRequest, idempotencyKey: String) async throws -> GenerationJobResponse {
        try await send(try .post("/v1/generation-jobs", body: payload, idempotencyKey: idempotencyKey))
    }

    func listGenerationJobs(status: JobStatus? = nil, limit: Int = 20) async throws -> Page<GenerationJobResponse> {
        var query = [URLQueryItem(name: "limit", value: String(limit))]
        if let status { query.append(URLQueryItem(name: "status", value: status.rawValue)) }
        return try await send(.get("/v1/generation-jobs", query: query))
    }

    func fetchGenerationJob(id: String) async throws -> GenerationJobResponse {
        try await send(.get("/v1/generation-jobs/\(id)"))
    }

    func cancelGenerationJob(id: String) async throws -> GenerationJobResponse {
        try await send(.post("/v1/generation-jobs/\(id)/cancel"))
    }

    /// 重试落一个新 job id，不是复用旧的——旧任务的释放记录与新任务的预扣记录在账本上分开，
    /// 界面层拿到新响应后要把当前屏幕跳到新 id，不能停在旧任务详情上继续轮询。
    func retryGenerationJob(id: String, idempotencyKey: String) async throws -> GenerationJobResponse {
        try await send(APIRequest(method: .post, path: "/v1/generation-jobs/\(id)/retry", idempotencyKey: idempotencyKey))
    }
}
