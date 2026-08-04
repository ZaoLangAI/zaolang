import Foundation

/// 全仓统一的编解码配置。所有 DTO 的 `CodingKeys` 都手写字面量 snake_case，
/// 所以这里**不用** `.convertFromSnakeCase`（那个策略会把 CodingKeys 的原始字符串再转一次，
/// 跟手写的字面量键打架）。日期走自定义策略，兼容后端 pydantic 默认输出的
/// 微秒精度 `+00:00` offset（`2026-08-03T11:50:24.594953+00:00`），也兼容不带小数秒的形式。
enum ZaolangJSONCoding {
    private static let withFractionalSeconds: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let withoutFractionalSeconds: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let raw = try container.decode(String.self)
            if let date = withFractionalSeconds.date(from: raw) ?? withoutFractionalSeconds.date(from: raw) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "无法解析日期字符串：\(raw)"
            )
        }
        return decoder
    }

    static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(withFractionalSeconds.string(from: date))
        }
        return encoder
    }
}

extension JSONDecoder {
    /// 全 Kit 共享的解码器；不要在别处再 new 一个不带日期策略的 `JSONDecoder()`。
    public static let zaolang = ZaolangJSONCoding.makeDecoder()
}

extension JSONEncoder {
    public static let zaolang = ZaolangJSONCoding.makeEncoder()
}
