import Foundation

/// `GET /v1/generation-jobs/{id}/events` 每一帧 `data:` 字段里的 JSON——
/// 跟 `JobEventResponse` 字段一样，但没有 `internal_code`/`created_at`（后端 `_sse()` 只发这五个）。
public struct JobStreamEvent: Decodable, Sendable, Equatable {
    public let sequence: Int
    public let eventType: String
    public let status: RawOrUnknown<JobStatus>
    public let progress: Int
    public let message: String

    private enum CodingKeys: String, CodingKey {
        case sequence
        case eventType = "event_type"
        case status, progress, message
    }
}

public extension EventStreamClient {
    /// 任务详情页的唯一入口：接进度、终态就结束（服务端在终态事件后主动关闭连接，
    /// 上层的 `EventStreamClient.events` 不会对这种"正常关闭"重连）。解码失败的帧直接丢弃
    /// 不中断整条流——单帧噪音不该打断已经在跑的任务。
    func jobEvents(jobID: String) -> AsyncThrowingStream<JobStreamEvent, Error> {
        let raw = events(path: "/v1/generation-jobs/\(jobID)/events")
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    for try await sseEvent in raw {
                        guard let data = sseEvent.data.data(using: .utf8),
                              let decoded = try? JSONDecoder.zaolang.decode(JobStreamEvent.self, from: data)
                        else { continue }
                        continuation.yield(decoded)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
