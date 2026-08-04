import Foundation

/// 订阅一个 SSE 端点（如 `/v1/generation-jobs/{id}/events`），断线按 `SSEReconnectPolicy`
/// 自动重连并带上 `Last-Event-ID` 续传。M1 没有生成流程界面接它，先保证这段纯逻辑能编译、
/// 逻辑自洽，M2 的任务详情页直接复用。
public actor EventStreamClient {
    private let baseURL: URL
    private let session: URLSession
    private let authProvider: AccessTokenProviding?

    public init(baseURL: URL, session: URLSession, authProvider: AccessTokenProviding? = nil) {
        self.baseURL = baseURL
        self.session = session
        self.authProvider = authProvider
    }

    /// 调用方 `for try await event in await client.events(path:)` 消费；
    /// 取消外层 Task（或让消费方 for-await 提前 break）就会停止重连并关闭连接。
    public func events(path: String) -> AsyncThrowingStream<SSEEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var policy = SSEReconnectPolicy()
                var lastEventID: String?
                while !Task.isCancelled {
                    do {
                        try await self.runOnce(path: path, lastEventID: lastEventID) { event in
                            lastEventID = event.id ?? lastEventID
                            policy.reset()
                            continuation.yield(event)
                        }
                        continuation.finish() // 服务端正常关闭（任务到终态后主动断开），不重连
                        return
                    } catch is CancellationError {
                        continuation.finish()
                        return
                    } catch {
                        let delay = policy.nextDelay()
                        try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                    }
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private func runOnce(
        path: String,
        lastEventID: String?,
        onEvent: @escaping (SSEEvent) -> Void
    ) async throws {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        if let lastEventID {
            request.setValue(lastEventID, forHTTPHeaderField: "Last-Event-ID")
        }
        if let token = await authProvider?.currentAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (byteStream, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw ApiError.unexpectedResponse(status: (response as? HTTPURLResponse)?.statusCode ?? 0)
        }

        var parser = SSEFrameParser(lastEventID: lastEventID)
        var buffer = Data()
        for try await byte in byteStream {
            buffer.append(byte)
            if buffer.count >= 512 {
                for event in parser.feed(buffer) { onEvent(event) }
                buffer.removeAll(keepingCapacity: true)
            }
        }
        if !buffer.isEmpty {
            for event in parser.feed(buffer) { onEvent(event) }
        }
    }
}
