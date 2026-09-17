import Foundation

/// 分页信封，字段名固定为 `items` / `next_cursor` / `has_more`（见 `back/openapi.json` 的 `Page[T]`）。
///
/// 只有 `GET /v1/works` 与 `GET /v1/credits/ledger` 真正落地了游标；其余列表端点也回这个信封，
/// 只是 `nextCursor` 恒为 `nil`。UI 只看 `nextCursor` 决定是否显示"加载更多"，
/// 后端补游标后客户端零改动（契约缺口清单见 `zaolang-ios-client` skill 的 roadmap.md）。
public struct Page<T: Codable & Sendable>: Codable, Sendable {
    public let items: [T]
    public let nextCursor: String?
    public let hasMore: Bool

    public init(items: [T], nextCursor: String? = nil, hasMore: Bool = false) {
        self.items = items
        self.nextCursor = nextCursor
        self.hasMore = hasMore
    }

    private enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
        case hasMore = "has_more"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        items = try container.decode([T].self, forKey: .items)
        nextCursor = try container.decodeIfPresent(String.self, forKey: .nextCursor)
        hasMore = try container.decodeIfPresent(Bool.self, forKey: .hasMore) ?? false
    }

    public static var empty: Page<T> { Page(items: []) }
}

/// 承载后端 `additionalProperties: true` 之类自由字段的值类型：
/// `ReusableParams.extra`、`VersionDiffEntry.parent_value/child_value` 都是这种未声明类型的字段。
///
/// 只用来"收下、原样显示或回传"，不承担业务语义；业务字段一律走具名 Codable 结构体。
public indirect enum JSONValue: Codable, Sendable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let v = try? container.decode(Bool.self) {
            self = .bool(v)
        } else if let v = try? container.decode(Double.self) {
            self = .number(v)
        } else if let v = try? container.decode(String.self) {
            self = .string(v)
        } else if let v = try? container.decode([String: JSONValue].self) {
            self = .object(v)
        } else if let v = try? container.decode([JSONValue].self) {
            self = .array(v)
        } else {
            self = .null
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let v): try container.encode(v)
        case .number(let v): try container.encode(v)
        case .bool(let v): try container.encode(v)
        case .object(let v): try container.encode(v)
        case .array(let v): try container.encode(v)
        case .null: try container.encodeNil()
        }
    }

    /// 尽力转成可直接展示的字符串，用于创作链 diff 这类"哪个类型都要能显示"的场景。
    public var displayString: String {
        switch self {
        case .string(let v): v
        case .number(let v): v.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(v)) : String(v)
        case .bool(let v): v ? "true" : "false"
        case .null: "—"
        case .object, .array: "\u{2026}" // 结构化值不适合单行展示，调用方应自行处理
        }
    }
}
