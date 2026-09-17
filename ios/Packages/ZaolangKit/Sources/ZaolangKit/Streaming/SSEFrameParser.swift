import Foundation

/// 一个完整的 SSE 事件（`text/event-stream` 里空行分隔的一段）。
public struct SSEEvent: Sendable, Equatable {
    public let id: String?
    public let event: String?
    public let data: String
    public let retryMS: Int?
}

/// `text/event-stream` 的增量帧解析器：喂字节进来，攒够一帧就吐一个 `SSEEvent`。
///
/// 值类型，不是 actor——调用方（`EventStreamClient`）本来就要串行喂数据，
/// 这里没有并发访问的需求，没必要额外加锁。
///
/// 已知的一个极窄边界情况没处理：如果服务端用 `\r\n` 换行，且这一对字符恰好被
/// 网络分片切在中间（前一个 chunk 结尾是 `\r`，下一个 chunk 开头是 `\n`），
/// 会被当成两行空行处理。这个仓库的后端 SSE 端点写的是纯 `\n`，且 M1 还不接界面，
/// 先不为这个几乎不会命中的场景加缓冲复杂度（YAGNI）。
public struct SSEFrameParser: Sendable {
    private var lineBuffer: String = ""
    private var eventType: String?
    private var dataLines: [String] = []
    private var retryMS: Int?

    /// SSE 规范里的"最后一次事件 ID 缓冲"：一旦被某个 `id:` 行设置过，
    /// 后续没带 `id:` 的帧也会沿用它，直到被下一个 `id:` 行覆盖。
    public private(set) var lastEventID: String?

    public init(lastEventID: String? = nil) {
        self.lastEventID = lastEventID
    }

    /// 喂入新收到的字节，返回这一批数据里凑出的完整事件（可能 0 个或多个）。
    public mutating func feed(_ chunk: Data) -> [SSEEvent] {
        guard let text = String(data: chunk, encoding: .utf8) else { return [] }
        lineBuffer += text

        var events: [SSEEvent] = []
        while let newlineIndex = lineBuffer.firstIndex(where: { $0.isNewline }) {
            let line = String(lineBuffer[lineBuffer.startIndex..<newlineIndex])
            lineBuffer.removeSubrange(lineBuffer.startIndex...newlineIndex)
            if let event = process(line: line) {
                events.append(event)
            }
        }
        return events
    }

    private mutating func process(line: String) -> SSEEvent? {
        if line.isEmpty {
            return dispatch()
        }
        if line.hasPrefix(":") {
            return nil // 注释行（常用于心跳），按规范忽略
        }

        let field: Substring
        var value: Substring
        if let colonIndex = line.firstIndex(of: ":") {
            field = line[line.startIndex..<colonIndex]
            value = line[line.index(after: colonIndex)...]
            if value.hasPrefix(" ") { value.removeFirst() }
        } else {
            field = Substring(line)
            value = ""
        }

        switch field {
        case "id": lastEventID = String(value)
        case "event": eventType = String(value)
        case "data": dataLines.append(String(value))
        case "retry": retryMS = Int(value)
        default: break // 未知字段按规范忽略
        }
        return nil
    }

    private mutating func dispatch() -> SSEEvent? {
        defer {
            eventType = nil
            dataLines = []
            retryMS = nil
        }
        guard !dataLines.isEmpty else { return nil } // 没有 data 字段的空行不算一个事件
        return SSEEvent(id: lastEventID, event: eventType, data: dataLines.joined(separator: "\n"), retryMS: retryMS)
    }
}
